#!/usr/bin/env python3
"""Agente de backup externo do módulo Tecnologia.

O arquivo de inicialização contém somente URLs e o token do agente. A
configuração operacional é consultada como JSON no portal; a senha do banco é
lida de uma variável de ambiente local e nunca é enviada ao NanotechSoft.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo


AGENT_VERSION = "1.2.0"


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {} if default is None else default


def write_json_atomic(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def backup_ssl_context(ca_file=None):
    configured = str(ca_file or os.environ.get("NANOTECH_BACKUP_CA_FILE") or "").strip()
    if not configured:
        return None
    path = Path(configured).expanduser()
    if not path.is_file():
        raise ValueError(f"arquivo da CA não encontrado: {path}")
    return ssl.create_default_context(cafile=str(path))


def json_request(url: str, token: str, payload=None, ca_file=None):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="GET" if payload is None else "POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Backup-Agent-Version": AGENT_VERSION,
        },
    )
    options = {"timeout": 30}
    context = backup_ssl_context(ca_file)
    if context is not None and str(url).lower().startswith("https://"):
        options["context"] = context
    with urllib.request.urlopen(request, **options) as response:
        return json.loads(response.read().decode("utf-8"))


def validate_bootstrap(config):
    if not isinstance(config, dict):
        raise ValueError("o arquivo de configuração deve conter um objeto JSON")
    for field in ("configUrl", "reportUrl", "agentId", "agentToken"):
        if not str(config.get(field) or "").strip():
            raise ValueError(f"campo obrigatório ausente no JSON: {field}")
    config_origin = validate_transport_url(config["configUrl"])
    report_origin = validate_transport_url(config["reportUrl"])
    if config_origin != report_origin:
        raise ValueError("configUrl e reportUrl devem usar a mesma origem")
    return config


def validate_transport_url(value):
    parsed = urllib.parse.urlsplit(str(value or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL do portal inválida no JSON do agente")
    hostname = parsed.hostname.lower()
    if parsed.scheme == "http":
        allowed = hostname == "localhost" or hostname.endswith(".local")
        try:
            address = ipaddress.ip_address(hostname)
            allowed = address.is_private or address.is_loopback or address.is_link_local
        except ValueError:
            pass
        if not allowed:
            raise ValueError("HTTP do agente é permitido somente para endereço privado/local")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme, hostname, port


def validate_job(job):
    if not isinstance(job, dict):
        raise ValueError("o portal devolveu uma configuração de backup inválida")
    backup_type = str(job.get("databaseType") or "MYSQL").upper()
    if backup_type not in {"MYSQL", "MARIADB", "FILES"}:
        raise ValueError("tipo de backup inválido")
    required = ["destinationPath", "timezone"]
    if backup_type != "FILES":
        required.extend(("databaseHost", "databaseName", "databaseUser", "passwordEnv"))
    for field in required:
        if not str(job.get(field) or "").strip():
            raise ValueError(f"configuração sem o campo {field}")
    times = job.get("times")
    if not isinstance(times, list) or not times:
        raise ValueError("a configuração não possui horários")
    for value in times:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(value)):
            raise ValueError(f"horário inválido: {value}")
    ZoneInfo(str(job["timezone"]))
    if backup_type == "FILES":
        source_paths = job.get("sourcePaths")
        if not isinstance(source_paths, list) or not source_paths:
            raise ValueError("o backup de arquivos não possui origens configuradas")
    return job


def safe_name(value):
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "backup")).strip("-.")
    return name or "backup"


def ensure_writable_directory(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if not mode & stat.S_IWUSR:
            path.chmod(mode | stat.S_IWUSR | stat.S_IWGRP)
    except OSError:
        pass
    if not os.access(path, os.W_OK):
        raise PermissionError(f"pasta de backup sem permissão de escrita: '{path}'")
    return path


def mysql_option_value(value):
    text = str(value)
    if any(character in text for character in ("\r", "\n", "\0")):
        raise ValueError("valor inválido no arquivo local de conexão MySQL")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def promotion_tiers(scheduled_time: str, times, local_date: dt.date, cloud_sync_path=""):
    tiers = ["diario"]
    if scheduled_time == sorted(times)[-1]:
        tiers.append("semana")
        if local_date.weekday() == 6:  # domingo: último backup da semana
            tiers.append("mes")
            if str(cloud_sync_path or "").strip():
                tiers.append("nuvem")
    return tiers


def remove_expired_files(root: Path, days: int, now=None):
    if not root.exists():
        return 0
    cutoff = (now or dt.datetime.now().timestamp()) - max(1, days) * 86400
    removed = 0
    for path in root.rglob("*"):
        if not path.is_file() or not (path.name.endswith(".sql.gz") or path.name.endswith(".tar.gz")):
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except FileNotFoundError:
            pass
    for directory in sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    return removed


def create_dump(job, output_path: Path):
    password = os.environ.get(str(job["passwordEnv"]))
    if password is None:
        raise RuntimeError(f"variável {job['passwordEnv']} não definida nesta máquina")
    dump_binary = os.environ.get("NANOTECH_BACKUP_MYSQLDUMP", "mysqldump")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path = output_path.with_suffix("").with_suffix(".sql.part")
    compressed_path = output_path.with_suffix(output_path.suffix + ".part")
    defaults_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as defaults:
            defaults.write("[client]\n")
            defaults.write(f"host={mysql_option_value(job['databaseHost'])}\n")
            defaults.write(f"port={int(job.get('databasePort') or 3306)}\n")
            defaults.write(f"user={mysql_option_value(job['databaseUser'])}\n")
            defaults.write(f"password={mysql_option_value(password)}\n")
            defaults_path = Path(defaults.name)
        try:
            os.chmod(defaults_path, 0o600)
        except OSError:
            pass
        command = [
            dump_binary,
            f"--defaults-extra-file={defaults_path}",
            "--single-transaction",
            "--quick",
            "--routines",
            "--events",
            "--triggers",
            "--hex-blob",
            "--databases",
            str(job["databaseName"]),
        ]
        with raw_path.open("wb") as output:
            result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, timeout=7200, check=False)
        if result.returncode:
            error = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"mysqldump terminou com código {result.returncode}: {error[-700:]}")
        with raw_path.open("rb") as source, gzip.open(compressed_path, "wb", compresslevel=6) as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        os.replace(compressed_path, output_path)
    finally:
        for temporary in (defaults_path, raw_path, compressed_path):
            if temporary:
                try:
                    Path(temporary).unlink()
                except FileNotFoundError:
                    pass


def create_file_archive(job, output_path: Path):
    sources = [Path(str(value)).expanduser() for value in job.get("sourcePaths") or []]
    missing = [str(path) for path in sources if not path.exists()]
    if missing:
        raise RuntimeError(f"origem não encontrada: {', '.join(missing[:5])}")
    destination = str(job.get("destinationPath") or "")
    if os.name != "nt" and (destination.startswith("//") or destination.startswith("\\\\")):
        raise RuntimeError("no Linux, monte o compartilhamento SMB e use um caminho local como /mnt/backup")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".part")
    output_resolved = output_path.parent.resolve()
    digest = hashlib.sha256()

    class DigestWriter:
        def __init__(self, handle):
            self.handle = handle

        def write(self, data):
            digest.update(data)
            return self.handle.write(data)

        def __getattr__(self, name):
            return getattr(self.handle, name)

    try:
        # Com cache=none no CIFS, um buffer amplo evita transformar cada bloco
        # pequeno produzido pelo gzip em uma operação SMB síncrona.
        with temporary.open("wb", buffering=4 * 1024 * 1024) as raw_output:
            with gzip.GzipFile(fileobj=DigestWriter(raw_output), mode="wb", compresslevel=6) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|") as archive:
                    used_names = set()
                    for index, source in enumerate(sources, start=1):
                        source_resolved = source.resolve()
                        if source_resolved == output_resolved or source_resolved in output_resolved.parents:
                            raise RuntimeError(f"o destino do backup está dentro da origem: {source}")
                        base_name = safe_name(source.name or f"origem-{index}")
                        archive_name = base_name if base_name not in used_names else f"{index:02d}-{base_name}"
                        used_names.add(archive_name)
                        archive.add(source, arcname=archive_name, recursive=True)
        os.replace(temporary, output_path)
        return digest.hexdigest()
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def promote_local_file(source: Path, destination: Path):
    """Promove sem duplicar espaço quando as camadas estão no mesmo volume."""
    ensure_writable_directory(destination.parent)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def copy_promotions(job, daily_path: Path, scheduled_time: str, local_date: dt.date):
    root = Path(str(job["destinationPath"]))
    ensure_writable_directory(root)
    tiers = promotion_tiers(scheduled_time, job["times"], local_date, job.get("cloudSyncPath"))
    week_id = f"{local_date.isocalendar().year}-W{local_date.isocalendar().week:02d}"
    if "semana" in tiers:
        weekly_root = ensure_writable_directory(root / "semana")
        weekly_directory = ensure_writable_directory(weekly_root / week_id)
        weekly = weekly_directory / f"{local_date.isoformat()}-{daily_path.name}"
        promote_local_file(daily_path, weekly)
    if "mes" in tiers:
        monthly_root = ensure_writable_directory(root / "mes")
        monthly_directory = ensure_writable_directory(monthly_root / local_date.strftime("%Y-%m"))
        monthly = monthly_directory / f"{week_id}-{daily_path.name}"
        promote_local_file(daily_path, monthly)
        if "nuvem" in tiers:
            cloud_root = ensure_writable_directory(Path(str(job["cloudSyncPath"])))
            cloud_directory = ensure_writable_directory(cloud_root / local_date.strftime("%Y-%m"))
            cloud = cloud_directory / monthly.name
            shutil.copy2(monthly, cloud)
    return tiers


def apply_retention(job, now=None):
    root = Path(str(job["destinationPath"]))
    return {
        "dailyRemoved": remove_expired_files(root / "diario", int(job.get("dailyRetentionDays") or 7), now),
        "weeklyRemoved": remove_expired_files(root / "semana", int(job.get("weeklyRetentionWeeks") or 5) * 7, now),
        "monthlyRemoved": remove_expired_files(root / "mes", int(job.get("monthlyRetentionMonths") or 12) * 31, now),
    }


def sha256_file(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_backup(job, scheduled_time: str, local_now: dt.datetime, execution_id: str, report):
    started = dt.datetime.now(dt.UTC)
    running = {
        "executionId": execution_id,
        "scheduledTime": scheduled_time,
        "status": "RUNNING",
        "startedAt": started.isoformat(),
        "message": "Backup iniciado pelo agente.",
    }
    report(running)
    root = Path(str(job["destinationPath"]))
    backup_type = str(job.get("databaseType") or "MYSQL").upper()
    extension = "tar.gz" if backup_type == "FILES" else "sql.gz"
    source_name = "arquivos" if backup_type == "FILES" else safe_name(job["databaseName"])
    filename = f"{source_name}_{local_now.strftime('%Y-%m-%d_%H-%M-%S')}.{extension}"
    daily_path = root / "diario" / local_now.strftime("%Y-%m-%d") / filename
    try:
        ensure_writable_directory(root)
        ensure_writable_directory(root / "diario")
        ensure_writable_directory(daily_path.parent)
        checksum = None
        if backup_type == "FILES":
            checksum = create_file_archive(job, daily_path)
        else:
            create_dump(job, daily_path)
        tiers = copy_promotions(job, daily_path, scheduled_time, local_now.date())
        retention = apply_retention(job)
        payload = {
            **running,
            "status": "SUCCESS",
            "completedAt": dt.datetime.now(dt.UTC).isoformat(),
            "filePath": str(daily_path),
            "sizeBytes": daily_path.stat().st_size,
            "sha256": checksum or sha256_file(daily_path),
            "tiers": tiers,
            "message": f"Backup de {'arquivos' if backup_type == 'FILES' else 'banco'} concluído e validado com SHA-256.",
            "details": {"retention": retention},
        }
    except Exception as exc:
        payload = {
            **running,
            "status": "FAILED",
            "completedAt": dt.datetime.now(dt.UTC).isoformat(),
            "filePath": str(daily_path),
            "message": f"{type(exc).__name__}: {exc}"[:1000],
        }
    report(payload)
    return payload


def due_slot(job, state, now=None, force=False):
    zone = ZoneInfo(str(job["timezone"]))
    local_now = (now or dt.datetime.now(dt.UTC)).astimezone(zone)
    times = sorted(str(item) for item in job["times"])
    if force:
        return local_now.strftime("%H:%M"), local_now
    today = local_now.date().isoformat()
    completed = set(state.get("completedSlots", {}).get(today, []))
    due = [item for item in times if item <= local_now.strftime("%H:%M") and item not in completed]
    return (due[-1], local_now) if due else (None, local_now)


def trim_state(state, local_date):
    slots = state.setdefault("completedSlots", {})
    minimum = (local_date - dt.timedelta(days=14)).isoformat()
    for key in list(slots):
        if key < minimum:
            del slots[key]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agente de backup do módulo Tecnologia")
    parser.add_argument("--config", required=True, type=Path, help="JSON baixado no cadastro do backup")
    parser.add_argument("--once", action="store_true", help="consulta e executa somente um ciclo")
    parser.add_argument("--run-now", action="store_true", help="força um backup imediato")
    parser.add_argument("--validate", action="store_true", help="valida o JSON e a configuração remota")
    parser.add_argument("--ca-file", type=Path, help="CA interna PEM usada para validar o HTTPS do portal")
    args = parser.parse_args(argv)
    bootstrap = validate_bootstrap(read_json(args.config))
    state_path = args.config.with_suffix(".state.json")
    state = read_json(state_path, {})

    while True:
        try:
            response = json_request(bootstrap["configUrl"], bootstrap["agentToken"], ca_file=args.ca_file)
            job = validate_job(response.get("job"))
            state["cachedJob"] = job
            state["lastConfigAt"] = dt.datetime.now(dt.UTC).isoformat()
        except Exception as exc:
            job = state.get("cachedJob")
            if not job:
                raise RuntimeError(f"não foi possível obter a configuração: {exc}") from exc
            print(f"[backup] portal indisponível; usando última configuração válida: {exc}", file=sys.stderr)

        pending_reports = state.get("pendingReports", [])
        if pending_reports:
            remaining = []
            for pending in pending_reports:
                try:
                    json_request(bootstrap["reportUrl"], bootstrap["agentToken"], pending, ca_file=args.ca_file)
                except Exception:
                    remaining.append(pending)
            state["pendingReports"] = remaining[-100:]

        if args.validate:
            status = "ativa" if job.get("active", True) else "inativa"
            print(f"Configuração {status} para {job.get('name')} ({', '.join(job['times'])}).")
            write_json_atomic(state_path, state)
            return 0

        if not job.get("active", True):
            state["lastResult"] = {
                "status": "SKIPPED",
                "message": "Plano desativado no portal; nenhuma execução iniciada.",
            }
            write_json_atomic(state_path, state)
            if args.once or args.run_now:
                return 0
            time.sleep(max(30, min(3600, int(bootstrap.get("pollSeconds") or 60))))
            continue

        slot, local_now = due_slot(job, state, force=args.run_now)
        if slot:
            execution_id = f"{bootstrap['agentId']}-{local_now.strftime('%Y%m%d')}-{slot.replace(':', '')}"

            def report(payload):
                try:
                    json_request(bootstrap["reportUrl"], bootstrap["agentToken"], payload, ca_file=args.ca_file)
                except Exception as exc:
                    print(f"[backup] relatório pendente: {exc}", file=sys.stderr)
                    pending = state.setdefault("pendingReports", [])
                    pending.append(payload)
                    state["pendingReports"] = pending[-100:]
                    write_json_atomic(state_path, state)

            result = run_backup(job, slot, local_now, execution_id, report)
            if not args.run_now and result.get("status") == "SUCCESS":
                today_slots = state.setdefault("completedSlots", {}).setdefault(local_now.date().isoformat(), [])
                for scheduled in job["times"]:
                    if scheduled <= slot and scheduled not in today_slots:
                        today_slots.append(scheduled)
            state["lastResult"] = result
        trim_state(state, local_now.date())
        write_json_atomic(state_path, state)
        if args.once or args.run_now:
            return 0 if state.get("lastResult", {}).get("status") != "FAILED" else 1
        time.sleep(max(30, min(3600, int(bootstrap.get("pollSeconds") or 60))))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        print(f"[backup] {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
