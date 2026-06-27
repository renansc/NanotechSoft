from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class DockerError(RuntimeError):
    pass


@dataclass
class DockerConnectionInfo:
    engine_name: str | None
    server_version: str | None
    operating_system: str | None


@dataclass
class RemoteCommandResult:
    stdout: str
    stderr: str
    combined: str


class DockerHostService:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        legacy_compat: bool,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.legacy_compat = legacy_compat

    @staticmethod
    def normalize_endpoint(host: str, port: Any = None) -> tuple[str, int]:
        normalized_host = str(host or "").strip()
        if not normalized_host:
            raise DockerError("Host ou IP do Docker sao obrigatorios.")

        resolved_port = 22 if port in (None, "") else port
        try:
            normalized_port = int(resolved_port)
        except (TypeError, ValueError) as exc:
            raise DockerError("A porta SSH do Docker precisa ser numerica.") from exc

        if not 1 <= normalized_port <= 65535:
            raise DockerError("A porta SSH do Docker precisa estar entre 1 e 65535.")

        return normalized_host, normalized_port

    @classmethod
    def probe_connection(
        cls,
        *,
        host: str,
        port: Any,
        username: str,
        password: str,
        legacy_compat: bool,
    ) -> tuple[DockerConnectionInfo, dict[str, Any]]:
        normalized_host, normalized_port = cls.normalize_endpoint(host, port)
        service = cls(
            host=normalized_host,
            port=normalized_port,
            username=str(username or "").strip(),
            password=password,
            legacy_compat=legacy_compat,
        )
        info = service.get_overview()
        connection_info = DockerConnectionInfo(
            engine_name=info.get("name"),
            server_version=info.get("server_version"),
            operating_system=info.get("operating_system"),
        )
        return connection_info, info

    def get_overview(self) -> dict[str, Any]:
        raw = self._run_json("docker info --format '{{json .}}'")
        return {
            "name": raw.get("Name"),
            "server_version": raw.get("ServerVersion"),
            "operating_system": raw.get("OperatingSystem"),
            "os_type": raw.get("OSType"),
            "architecture": raw.get("Architecture"),
            "cpus": raw.get("NCPU"),
            "memory_total_bytes": raw.get("MemTotal"),
            "containers": raw.get("Containers"),
            "containers_running": raw.get("ContainersRunning"),
            "containers_paused": raw.get("ContainersPaused"),
            "containers_stopped": raw.get("ContainersStopped"),
            "images": raw.get("Images"),
            "driver": raw.get("Driver"),
            "docker_root_dir": raw.get("DockerRootDir"),
        }

    def list_containers(self) -> list[dict[str, Any]]:
        lines = self._run_json_lines("docker ps -a --no-trunc --format '{{json .}}'")
        stats_lines = self._run_json_lines("docker stats --no-stream --no-trunc --format '{{json .}}'", allow_empty=True)
        stats_by_id = {
            item.get("ID") or item.get("Container"): item
            for item in stats_lines
            if item.get("ID") or item.get("Container")
        }

        result: list[dict[str, Any]] = []
        for item in lines:
            container_id = item.get("ID") or ""
            stats = stats_by_id.get(container_id, {})
            result.append(
                {
                    "id": container_id,
                    "short_id": container_id[:12] if container_id else None,
                    "name": item.get("Names"),
                    "image": item.get("Image"),
                    "command": item.get("Command"),
                    "created_at": item.get("CreatedAt"),
                    "running_for": item.get("RunningFor"),
                    "ports": item.get("Ports"),
                    "state": item.get("State"),
                    "status": item.get("Status"),
                    "mounts": item.get("Mounts"),
                    "networks": item.get("Networks"),
                    "labels": item.get("Labels"),
                    "cpu_percent": stats.get("CPUPerc"),
                    "memory_percent": stats.get("MemPerc"),
                    "memory_usage": stats.get("MemUsage"),
                    "net_io": stats.get("NetIO"),
                    "block_io": stats.get("BlockIO"),
                    "pids": stats.get("PIDs"),
                }
            )
        return sorted(result, key=lambda entry: (entry.get("name") or "").lower())

    def get_container_details(self, container_id: str) -> dict[str, Any]:
        data = self._run_json_list(f"docker inspect {shlex.quote(container_id)}")
        if not data:
            raise DockerError("Container nao encontrado.")
        item = data[0]

        networks = {}
        network_settings = item.get("NetworkSettings", {}).get("Networks", {}) or {}
        for name, network in network_settings.items():
            networks[name] = {
                "ip_address": network.get("IPAddress"),
                "gateway": network.get("Gateway"),
                "mac_address": network.get("MacAddress"),
                "aliases": network.get("Aliases") or [],
            }

        mounts = [
            {
                "type": mount.get("Type"),
                "source": mount.get("Source"),
                "destination": mount.get("Destination"),
                "mode": mount.get("Mode"),
                "rw": mount.get("RW"),
            }
            for mount in item.get("Mounts", []) or []
        ]

        config = item.get("Config", {}) or {}
        state = item.get("State", {}) or {}
        host_config = item.get("HostConfig", {}) or {}

        return {
            "id": item.get("Id"),
            "name": str(item.get("Name", "")).lstrip("/") or item.get("Id"),
            "image": config.get("Image"),
            "created": item.get("Created"),
            "entrypoint": config.get("Entrypoint") or [],
            "command": config.get("Cmd") or [],
            "env": config.get("Env") or [],
            "working_dir": config.get("WorkingDir"),
            "restart_policy": (host_config.get("RestartPolicy") or {}).get("Name"),
            "state": {
                "status": state.get("Status"),
                "running": state.get("Running"),
                "paused": state.get("Paused"),
                "restarting": state.get("Restarting"),
                "oom_killed": state.get("OOMKilled"),
                "exit_code": state.get("ExitCode"),
                "started_at": state.get("StartedAt"),
                "finished_at": state.get("FinishedAt"),
                "error": state.get("Error"),
            },
            "mounts": mounts,
            "networks": networks,
            "ports": item.get("NetworkSettings", {}).get("Ports") or {},
        }

    def get_container_logs(self, container_id: str, *, tail: int = 200) -> str:
        safe_tail = max(10, min(int(tail), 1000))
        return self._run_text(
            f"docker logs --tail {safe_tail} --timestamps {shlex.quote(container_id)}",
            allow_empty=True,
        )

    def create_container(
        self,
        *,
        image: str,
        name: str | None = None,
        command: str | None = None,
        ports: str | None = None,
        environment: str | None = None,
        volumes: str | None = None,
        network: str | None = None,
        restart_policy: str | None = None,
        extra_args: str | None = None,
        detach: bool = True,
    ) -> dict[str, Any]:
        image_name = str(image or "").strip()
        if not image_name:
            raise DockerError("Informe a imagem do novo container.")

        tokens = ["docker", "run"]
        if detach:
            tokens.append("-d")

        container_name = str(name or "").strip()
        if container_name:
            tokens.extend(["--name", container_name])

        normalized_restart = str(restart_policy or "").strip().lower()
        if normalized_restart:
            if normalized_restart not in {"no", "always", "unless-stopped", "on-failure"}:
                raise DockerError("Politica de restart invalida para o novo container.")
            if normalized_restart != "no":
                tokens.extend(["--restart", normalized_restart])

        network_name = str(network or "").strip()
        if network_name:
            tokens.extend(["--network", network_name])

        for port_mapping in self._split_multiline_values(ports):
            tokens.extend(["-p", port_mapping])

        for env_item in self._split_multiline_values(environment):
            tokens.extend(["-e", env_item])

        for volume_item in self._split_multiline_values(volumes):
            tokens.extend(["-v", volume_item])

        if extra_args:
            tokens.extend(self._parse_command_words(extra_args, field_name="argumentos extras"))

        tokens.append(image_name)

        if command:
            tokens.extend(self._parse_command_words(command, field_name="comando do container"))

        safe_command = self._quote_command(tokens)
        result = self._run_remote_command(safe_command, allow_empty=True)

        container = None
        container_ref = result.stdout.splitlines()[-1].strip() if result.stdout else ""
        if not container_ref:
            container_ref = container_name
        if container_ref:
            try:
                container = self.get_container_details(container_ref)
            except DockerError:
                container = None

        return {
            "command": safe_command,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "output": result.combined,
            "container": container,
        }

    def execute_container_action(self, container_id: str, action: str) -> dict[str, Any]:
        commands = {
            "start": f"docker start {shlex.quote(container_id)}",
            "stop": f"docker stop {shlex.quote(container_id)}",
            "restart": f"docker restart {shlex.quote(container_id)}",
            "remove": f"docker rm -f {shlex.quote(container_id)}",
        }
        if action not in commands:
            raise DockerError("Acao de container nao suportada.")

        self._run_text(commands[action], allow_empty=True)
        if action == "remove":
            return {"id": container_id, "removed": True}
        return self.get_container_details(container_id)

    def run_docker_command(self, command: str) -> dict[str, Any]:
        safe_command = self._normalize_docker_command(command)
        result = self._run_remote_command(safe_command, allow_empty=True)
        return {
            "command": safe_command,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "output": result.combined,
        }

    def _run_json(self, remote_command: str) -> dict[str, Any]:
        text = self._run_text(remote_command)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DockerError("Resposta JSON invalida do host Docker.") from exc
        if not isinstance(data, dict):
            raise DockerError("Resposta inesperada do host Docker.")
        return data

    def _run_json_list(self, remote_command: str) -> list[dict[str, Any]]:
        text = self._run_text(remote_command)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DockerError("Resposta JSON invalida do host Docker.") from exc
        if not isinstance(data, list):
            raise DockerError("Resposta inesperada do host Docker.")
        return [item for item in data if isinstance(item, dict)]

    def _run_json_lines(self, remote_command: str, *, allow_empty: bool = False) -> list[dict[str, Any]]:
        text = self._run_text(remote_command, allow_empty=allow_empty)
        items: list[dict[str, Any]] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DockerError("Resposta JSON invalida do host Docker.") from exc
            if isinstance(data, dict):
                items.append(data)
        return items

    def _run_text(self, remote_command: str, *, allow_empty: bool = False) -> str:
        return self._run_remote_command(remote_command, allow_empty=allow_empty).stdout

    def _run_remote_command(self, remote_command: str, *, allow_empty: bool = False) -> RemoteCommandResult:
        if not self.host or not self.username or not self.password:
            raise DockerError("Conexao Docker SSH incompleta.")

        temp_dir = tempfile.mkdtemp(prefix="docker-ssh-")
        askpass_path = self._write_askpass_script(temp_dir)
        env = os.environ.copy()
        env["DISPLAY"] = "codex"
        env["SSH_ASKPASS"] = askpass_path
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env["CODEX_SSH_PASS"] = self.password

        command = self._build_ssh_command(remote_command)
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                cwd=tempfile.gettempdir(),
                timeout=40,
            )
        except subprocess.TimeoutExpired as exc:
            raise DockerError("Tempo esgotado ao consultar o host Docker.") from exc
        except OSError as exc:
            raise DockerError(f"Falha ao iniciar o cliente SSH local: {exc}") from exc
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        combined = "\n".join(part for part in (stdout, stderr) if part).strip()

        if completed.returncode != 0:
            raise DockerError(self._normalize_ssh_error(combined or stdout or stderr))

        if not stdout and not stderr and not allow_empty:
            raise DockerError("O host Docker nao retornou dados.")
        return RemoteCommandResult(stdout=stdout, stderr=stderr, combined=combined)

    def _build_ssh_command(self, remote_command: str) -> list[str]:
        command = [
            self._detect_ssh_command(),
            "-p",
            str(self.port),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            f"UserKnownHostsFile={'NUL' if os.name == 'nt' else '/dev/null'}",
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
        if self.legacy_compat:
            command.extend(
                [
                    "-o",
                    "HostKeyAlgorithms=+ssh-rsa",
                    "-o",
                    "PubkeyAcceptedAlgorithms=+ssh-rsa",
                ]
            )
        command.append(f"{self.username}@{self.host}")
        command.append(remote_command)
        return command

    def _write_askpass_script(self, temp_dir: str) -> str:
        if os.name == "nt":
            path = Path(temp_dir) / "askpass.cmd"
            path.write_text("@echo off\r\necho %CODEX_SSH_PASS%\r\n", encoding="ascii")
            return str(path)

        path = Path(temp_dir) / "askpass.sh"
        path.write_text("#!/bin/sh\nprintf '%s\\n' \"$CODEX_SSH_PASS\"\n", encoding="ascii")
        path.chmod(0o700)
        return str(path)

    def _detect_ssh_command(self) -> str:
        if os.name == "nt":
            return shutil.which("ssh.exe") or shutil.which("ssh") or "ssh.exe"
        return shutil.which("ssh") or "ssh"

    @staticmethod
    def _split_multiline_values(raw_value: Any) -> list[str]:
        if raw_value in (None, ""):
            return []
        return [
            line.strip()
            for line in str(raw_value).replace("\r", "\n").split("\n")
            if line.strip()
        ]

    @staticmethod
    def _quote_command(tokens: list[str]) -> str:
        return " ".join(shlex.quote(str(token)) for token in tokens if str(token) != "")

    def _parse_command_words(self, raw_value: str, *, field_name: str) -> list[str]:
        try:
            return shlex.split(str(raw_value or "").strip(), posix=True)
        except ValueError as exc:
            raise DockerError(f"Conteudo invalido em {field_name}. Revise aspas e escapes.") from exc

    def _normalize_docker_command(self, command: str) -> str:
        raw_command = str(command or "").strip()
        if not raw_command:
            raise DockerError("Informe o comando Docker para executar.")

        tokens = self._parse_command_words(raw_command, field_name="comando Docker")
        if not tokens:
            raise DockerError("Informe o comando Docker para executar.")
        if tokens[0] not in {"docker", "docker-compose"}:
            raise DockerError("Use apenas comandos iniciados por 'docker' ou 'docker-compose'.")

        return self._quote_command(tokens)

    def _normalize_ssh_error(self, message: str) -> str:
        text = str(message or "").strip()
        lowered = text.lower()
        if "no matching host key type found" in lowered and not self.legacy_compat:
            return "O host SSH aceita apenas algoritmos legados. Marque a compatibilidade legada SSH."
        if "permission denied" in lowered:
            if "docker daemon socket" in lowered:
                return "O usuario conectou por SSH, mas nao tem permissao para usar o Docker daemon."
            return "Falha de autenticacao SSH. Revise usuario e senha."
        if "docker: command not found" in lowered:
            return "O comando docker nao foi encontrado no host remoto."
        if "docker-compose: command not found" in lowered:
            return "O comando docker-compose nao foi encontrado no host remoto."
        if "cannot connect to the docker daemon" in lowered:
            return "O Docker respondeu, mas o daemon nao esta acessivel no host remoto."
        if "connection timed out" in lowered:
            return "Tempo esgotado ao conectar no host Docker."
        if "could not resolve hostname" in lowered:
            return "Nao foi possivel resolver o hostname do host Docker."
        return text or "Falha ao executar comando Docker remoto."
