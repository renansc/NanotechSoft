from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock


class TerminalError(RuntimeError):
    pass


MAX_BUFFER_SIZE = 250_000


@dataclass
class TerminalSession:
    sid: str
    owner_id: str
    host: str
    port: int
    username: str
    process: subprocess.Popen[bytes]
    temp_dir: str
    askpass_path: str
    created_at: datetime
    legacy_compat: bool
    _buffer: str = ""
    _offset: int = 0
    _closed: bool = False
    _returncode: int | None = None
    _lock: RLock = field(default_factory=RLock, repr=False)
    _reader_thread: threading.Thread | None = field(default=None, repr=False)

    def start(self) -> None:
        reader = threading.Thread(target=self._pump_output, name=f"ssh-terminal-{self.sid}", daemon=True)
        self._reader_thread = reader
        reader.start()

    def append_output(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._buffer += text
            if len(self._buffer) > MAX_BUFFER_SIZE:
                excess = len(self._buffer) - MAX_BUFFER_SIZE
                self._buffer = self._buffer[excess:]
                self._offset += excess

    def read_since(self, cursor: int) -> tuple[str, int, bool, int | None]:
        with self._lock:
            if cursor < self._offset:
                start = 0
            else:
                start = cursor - self._offset
            data = self._buffer[start:]
            next_cursor = self._offset + len(self._buffer)
            return data, next_cursor, self._closed, self._returncode

    def write(self, data: str) -> None:
        if self._closed:
            raise TerminalError("A sessao SSH ja foi encerrada.")
        stdin = self.process.stdin
        if stdin is None:
            raise TerminalError("A sessao SSH nao possui entrada disponivel.")
        try:
            stdin.write(data.encode("utf-8", errors="ignore"))
            stdin.flush()
        except OSError as exc:
            raise TerminalError(f"Falha ao enviar dados para a sessao SSH: {exc}") from exc

    def resize(self, cols: int, rows: int) -> None:
        self.write(f"\x1b[8;{rows};{cols}t")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True

        try:
            if self.process.stdin is not None:
                self.process.stdin.write(b"exit\n")
                self.process.stdin.flush()
        except OSError:
            pass

        try:
            self.process.terminate()
            self.process.wait(timeout=3)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass
        finally:
            self._cleanup()

    def to_public_dict(self) -> dict[str, object]:
        return {
            "sid": self.sid,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "legacy_compat": self.legacy_compat,
            "created_at": self.created_at.astimezone(timezone.utc).isoformat(),
        }

    def _pump_output(self) -> None:
        stream = self.process.stdout
        if stream is None:
            self.append_output("Terminal sem stream de saida.\r\n")
            self._mark_closed(self.process.poll())
            self._cleanup()
            return

        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                self.append_output(chunk.decode("utf-8", errors="replace"))
        finally:
            returncode = None
            try:
                returncode = self.process.wait(timeout=1)
            except Exception:
                returncode = self.process.poll()
            self._mark_closed(returncode)
            self._cleanup()

    def _mark_closed(self, returncode: int | None) -> None:
        with self._lock:
            self._closed = True
            self._returncode = returncode

    def _cleanup(self) -> None:
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass


class TerminalStore:
    def __init__(self) -> None:
        self._items: dict[str, TerminalSession] = {}
        self._lock = RLock()

    def create(
        self,
        *,
        owner_id: str,
        host: str,
        port: int,
        username: str,
        password: str,
        legacy_compat: bool,
    ) -> TerminalSession:
        if not host or not username:
            raise TerminalError("Host e usuario SSH sao obrigatorios.")
        if not password:
            raise TerminalError("A senha SSH e obrigatoria para iniciar o terminal web.")

        temp_dir = tempfile.mkdtemp(prefix="vsphere-terminal-")
        askpass_path = self._write_askpass_script(temp_dir)
        process = self._spawn_process(
            host=host,
            port=port,
            username=username,
            password=password,
            askpass_path=askpass_path,
            legacy_compat=legacy_compat,
        )

        session = TerminalSession(
            sid=uuid.uuid4().hex,
            owner_id=owner_id,
            host=host,
            port=port,
            username=username,
            process=process,
            temp_dir=temp_dir,
            askpass_path=askpass_path,
            created_at=datetime.now(tz=timezone.utc),
            legacy_compat=legacy_compat,
        )
        session.start()

        with self._lock:
            self._items[session.sid] = session
        return session

    def get(self, sid: str | None, *, owner_id: str) -> TerminalSession:
        if not sid:
            raise TerminalError("Sessao de terminal invalida.")
        with self._lock:
            session = self._items.get(sid)
        if session is None or session.owner_id != owner_id:
            raise TerminalError("Sessao de terminal nao encontrada.")
        return session

    def remove(self, sid: str | None, *, owner_id: str) -> None:
        if not sid:
            return
        with self._lock:
            session = self._items.get(sid)
            if session is None:
                return
            if session.owner_id != owner_id:
                raise TerminalError("Sessao de terminal nao encontrada.")
            self._items.pop(sid, None)
        session.close()

    def remove_for_owner(self, owner_id: str) -> None:
        with self._lock:
            targets = [sid for sid, session in self._items.items() if session.owner_id == owner_id]
        for sid in targets:
            self.remove(sid, owner_id=owner_id)

    def reap_closed(self) -> None:
        with self._lock:
            stale = [sid for sid, session in self._items.items() if session.read_since(0)[2]]
        for sid in stale:
            with self._lock:
                session = self._items.get(sid)
                if session is None or not session.read_since(0)[2]:
                    continue
                self._items.pop(sid, None)
            time.sleep(0)

    def _write_askpass_script(self, temp_dir: str) -> str:
        if os.name == "nt":
            path = Path(temp_dir) / "askpass.cmd"
            path.write_text("@echo off\r\necho %CODEX_SSH_PASS%\r\n", encoding="ascii")
            return str(path)

        path = Path(temp_dir) / "askpass.sh"
        path.write_text("#!/bin/sh\nprintf '%s\\n' \"$CODEX_SSH_PASS\"\n", encoding="ascii")
        path.chmod(0o700)
        return str(path)

    def _spawn_process(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        askpass_path: str,
        legacy_compat: bool,
    ) -> subprocess.Popen[bytes]:
        ssh_command = self._detect_ssh_command()
        known_hosts_path = "NUL" if os.name == "nt" else "/dev/null"
        command = [
            ssh_command,
            "-tt",
            "-p",
            str(port),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            f"UserKnownHostsFile={known_hosts_path}",
            "-o",
            "PreferredAuthentications=password,keyboard-interactive",
            "-o",
            "KbdInteractiveAuthentication=yes",
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=1",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "LogLevel=ERROR",
        ]
        if legacy_compat:
            command.extend(
                [
                    "-o",
                    "HostKeyAlgorithms=+ssh-rsa",
                    "-o",
                    "PubkeyAcceptedAlgorithms=+ssh-rsa",
                ]
            )
        command.append(f"{username}@{host}")

        env = os.environ.copy()
        env["DISPLAY"] = "codex"
        env["SSH_ASKPASS"] = askpass_path
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env["CODEX_SSH_PASS"] = password

        try:
            return subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                cwd=tempfile.gettempdir(),
                bufsize=0,
            )
        except OSError as exc:
            raise TerminalError(f"Falha ao iniciar o cliente SSH local: {exc}") from exc

    def _detect_ssh_command(self) -> str:
        if os.name == "nt":
            return shutil.which("ssh.exe") or shutil.which("ssh") or "ssh.exe"
        return shutil.which("ssh") or "ssh"


terminal_store = TerminalStore()
