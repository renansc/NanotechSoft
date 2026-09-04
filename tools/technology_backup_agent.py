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
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo


AGENT_VERSION = "1.5.0"
FILE_MANIFEST_FORMAT = "nanotech-files-incremental-v1"
FILE_MANIFEST_SUFFIX = ".files.json.gz"
FILE_OBJECT_STORE = Path("arquivos_incrementais") / "objetos"


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
    job["operatingWindows"] = normalize_operating_windows(job.get("operatingWindows"))
    ZoneInfo(str(job["timezone"]))
    if backup_type == "FILES":
        source_paths = job.get("sourcePaths")
        if not isinstance(source_paths, list) or not source_paths:
            raise ValueError("o backup de arquivos não possui origens configuradas")
    return job


def normalize_operating_windows(value):
    if value in (None, "", {}):
        return {}
    if not isinstance(value, dict):
        raise ValueError("janelas de execução inválidas")
    windows = {}
    for raw_weekday, raw_window in value.items():
        try:
            weekday = int(raw_weekday)
        except (TypeError, ValueError) as exc:
            raise ValueError("dia da semana inválido nas janelas de execução") from exc
        if weekday < 0 or weekday > 6 or not isinstance(raw_window, dict):
            raise ValueError("dia da semana inválido nas janelas de execução")
        start = str(raw_window.get("start") or "").strip()
        end = str(raw_window.get("end") or "").strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", start):
            raise ValueError(f"início inválido para o dia {weekday}")
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", end) or end <= start:
            raise ValueError(f"fim inválido para o dia {weekday}")
        window = {"start": start, "end": end}
        raw_times = raw_window.get("times")
        if raw_times not in (None, "", []):
            if not isinstance(raw_times, list) or not raw_times:
                raise ValueError(f"horários inválidos para o dia {weekday}")
            day_times = []
            for value in raw_times:
                scheduled = str(value or "").strip()
                if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", scheduled):
                    raise ValueError(f"horário inválido para o dia {weekday}: {scheduled}")
                if not (start <= scheduled < end):
                    raise ValueError(f"horário fora da janela do dia {weekday}: {scheduled}")
                if scheduled not in day_times:
                    day_times.append(scheduled)
            window["times"] = sorted(day_times)
        windows[str(weekday)] = window
    return {key: windows[key] for key in sorted(windows, key=int)}


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


def promotion_tiers(
    scheduled_time: str,
    times,
    local_date: dt.date,
    cloud_sync_path="",
    operating_windows=None,
):
    tiers = ["diario"]
    windows = normalize_operating_windows(operating_windows)
    window = windows.get(str(local_date.weekday())) if windows else None
    day_times = (window.get("times") or times) if window else times
    active_times = sorted(
        item for item in day_times
        if not window or window["start"] <= item < window["end"]
    )
    if active_times and scheduled_time == active_times[-1]:
        tiers.append("semana")
        last_weekday = max((int(day) for day in windows), default=6)
        if local_date.weekday() == last_weekday:
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
        if not path.is_file() or not (
            path.name.endswith(".sql.gz")
            or path.name.endswith(".tar.gz")
            or path.name.endswith(FILE_MANIFEST_SUFFIX)
        ):
            continue
        try:
            if path.stat().st_mtime < cutoff:
                try:
                    path.unlink()
                except PermissionError:
                    # Backups antigos podem ter sido criados dentro de uma pasta
                    # sem bit de escrita. Repara a pasta quando ela pertence ao
                    # usuário do agente e tenta a retenção novamente.
                    ensure_writable_directory(path.parent)
                    path.unlink()
                removed += 1
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"[backup] aviso: não foi possível remover arquivo expirado: {exc}", file=sys.stderr)
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


def file_object_path(repository_root: Path, digest: str):
    if not re.fullmatch(r"[a-f0-9]{64}", str(digest or "")):
        raise ValueError("identificador de conteúdo inválido no manifesto incremental")
    return repository_root / FILE_OBJECT_STORE / digest[:2] / f"{digest}.gz"


def load_file_manifest(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("format") != FILE_MANIFEST_FORMAT or not isinstance(manifest.get("entries"), list):
        raise ValueError(f"manifesto incremental inválido: {path}")
    return manifest


def latest_file_manifest(repository_root: Path):
    daily_root = repository_root / "diario"
    if not daily_root.exists():
        return None, None
    candidates = [path for path in daily_root.rglob(f"*{FILE_MANIFEST_SUFFIX}") if path.is_file()]
    for path in sorted(candidates, key=lambda item: item.stat().st_mtime_ns, reverse=True):
        try:
            return path, load_file_manifest(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return None, None


def source_archive_names(sources):
    used_names = set()
    result = []
    for index, source in enumerate(sources, start=1):
        base_name = safe_name(source.name or f"origem-{index}")
        archive_name = base_name if base_name not in used_names else f"{index:02d}-{base_name}"
        used_names.add(archive_name)
        result.append((source, archive_name))
    return result


def file_manifest_entry(path: Path, manifest_path: str):
    metadata = os.lstat(path)
    common = {
        "path": manifest_path,
        "mode": stat.S_IMODE(metadata.st_mode),
        "mtimeNs": metadata.st_mtime_ns,
    }
    if stat.S_ISLNK(metadata.st_mode):
        return {
            **common,
            "type": "symlink",
            "target": os.readlink(path),
            "targetIsDirectory": path.is_dir(),
        }
    if stat.S_ISDIR(metadata.st_mode):
        return {**common, "type": "directory"}
    if stat.S_ISREG(metadata.st_mode):
        return {**common, "type": "file", "size": metadata.st_size}
    raise RuntimeError(f"tipo de arquivo não suportado no backup: {path}")


def iter_source_entries(source: Path, archive_name: str):
    root_entry = file_manifest_entry(source, archive_name)
    yield source, root_entry
    if root_entry["type"] != "directory":
        return
    for current, directory_names, file_names in os.walk(source, topdown=True, followlinks=False):
        directory_names.sort()
        file_names.sort()
        current_path = Path(current)
        relative = current_path.relative_to(source)
        traversable = []
        for name in directory_names:
            child = current_path / name
            child_relative = "/".join((archive_name, *relative.parts, name))
            entry = file_manifest_entry(child, child_relative)
            yield child, entry
            if entry["type"] == "directory":
                traversable.append(name)
        directory_names[:] = traversable
        for name in file_names:
            child = current_path / name
            child_relative = "/".join((archive_name, *relative.parts, name))
            yield child, file_manifest_entry(child, child_relative)


def store_file_object(source: Path, repository_root: Path):
    for attempt in range(2):
        before = source.stat()
        staging = ensure_writable_directory(repository_root / FILE_OBJECT_STORE / ".staging")
        temporary = staging / f"object.part-{os.getpid()}-{time.time_ns()}"
        try:
            calculated = hashlib.sha256()
            with source.open("rb") as input_file, temporary.open("wb", buffering=4 * 1024 * 1024) as raw_output:
                with gzip.GzipFile(filename="", fileobj=raw_output, mode="wb", compresslevel=6, mtime=0) as compressed:
                    for block in iter(lambda: input_file.read(1024 * 1024), b""):
                        calculated.update(block)
                        compressed.write(block)
            after_copy = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after_copy.st_size, after_copy.st_mtime_ns):
                if attempt == 0:
                    continue
                raise RuntimeError(f"arquivo alterado durante o backup: {source}")
            digest = calculated.hexdigest()
            object_path = file_object_path(repository_root, digest)
            if object_path.exists():
                return digest, 0, False
            ensure_writable_directory(object_path.parent)
            try:
                os.replace(temporary, object_path)
            except OSError:
                if not object_path.exists():
                    raise
            return digest, object_path.stat().st_size, True
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    raise RuntimeError(f"não foi possível obter uma versão estável do arquivo: {source}")


def write_file_manifest(output_path: Path, manifest):
    ensure_writable_directory(output_path.parent)
    temporary = output_path.with_name(f"{output_path.name}.part-{os.getpid()}-{time.time_ns()}")
    try:
        with temporary.open("wb", buffering=1024 * 1024) as raw_output:
            with gzip.GzipFile(filename="", fileobj=raw_output, mode="wb", compresslevel=6, mtime=0) as compressed:
                compressed.write(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        os.replace(temporary, output_path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def create_incremental_file_backup(job, output_path: Path, created_at=None):
    sources = [Path(str(value)).expanduser() for value in job.get("sourcePaths") or []]
    missing = [str(path) for path in sources if not path.exists() and not path.is_symlink()]
    if missing:
        raise RuntimeError(f"origem não encontrada: {', '.join(missing[:5])}")
    destination = str(job.get("destinationPath") or "")
    if os.name != "nt" and (destination.startswith("//") or destination.startswith("\\\\")):
        raise RuntimeError("no Linux, monte o compartilhamento SMB e use um caminho local como /mnt/backup")
    repository_root = Path(destination)
    ensure_writable_directory(repository_root / FILE_OBJECT_STORE)
    destination_resolved = repository_root.resolve()
    for source in sources:
        source_resolved = source.resolve()
        if source_resolved == destination_resolved or source_resolved in destination_resolved.parents:
            raise RuntimeError(f"o destino do backup está dentro da origem: {source}")

    previous_path, previous_manifest = latest_file_manifest(repository_root)
    previous_files = {
        entry.get("path"): entry
        for entry in (previous_manifest or {}).get("entries", [])
        if entry.get("type") == "file"
    }
    entries = []
    statistics = {
        "files": 0,
        "directories": 0,
        "symlinks": 0,
        "unchangedFiles": 0,
        "changedFiles": 0,
        "deletedFiles": 0,
        "objectsWritten": 0,
        "logicalBytes": 0,
        "objectBytesWritten": 0,
    }
    current_files = set()
    for source, archive_name in source_archive_names(sources):
        for disk_path, entry in iter_source_entries(source, archive_name):
            entry_type = entry["type"]
            if entry_type == "file":
                statistics["files"] += 1
                statistics["logicalBytes"] += entry["size"]
                current_files.add(entry["path"])
                previous = previous_files.get(entry["path"])
                previous_digest = str((previous or {}).get("object") or "")
                unchanged = (
                    previous
                    and previous.get("size") == entry["size"]
                    and previous.get("mtimeNs") == entry["mtimeNs"]
                    and re.fullmatch(r"[a-f0-9]{64}", previous_digest)
                    and file_object_path(repository_root, previous_digest).is_file()
                )
                if unchanged:
                    entry["object"] = previous_digest
                    statistics["unchangedFiles"] += 1
                else:
                    digest, stored_bytes, written = store_file_object(disk_path, repository_root)
                    entry["object"] = digest
                    statistics["changedFiles"] += 1
                    statistics["objectBytesWritten"] += stored_bytes
                    statistics["objectsWritten"] += int(written)
            elif entry_type == "directory":
                statistics["directories"] += 1
            else:
                statistics["symlinks"] += 1
            entries.append(entry)
    statistics["deletedFiles"] = len(set(previous_files) - current_files)
    manifest = {
        "format": FILE_MANIFEST_FORMAT,
        "createdAt": (created_at or dt.datetime.now(dt.UTC)).isoformat(),
        "objectStore": FILE_OBJECT_STORE.as_posix(),
        "previousManifest": str(previous_path) if previous_path else None,
        "sources": [
            {"path": str(source), "archiveName": archive_name}
            for source, archive_name in source_archive_names(sources)
        ],
        "entries": entries,
        "statistics": statistics,
    }
    write_file_manifest(output_path, manifest)
    statistics["manifestBytes"] = output_path.stat().st_size
    statistics["bytesWritten"] = statistics["objectBytesWritten"] + statistics["manifestBytes"]
    return sha256_file(output_path), statistics


def promote_local_file(source: Path, destination: Path):
    """Promove sem duplicar espaço quando as camadas estão no mesmo volume."""
    ensure_writable_directory(destination.parent)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def manifest_object_digests(manifest):
    digests = set()
    for entry in manifest.get("entries") or []:
        if entry.get("type") != "file":
            continue
        digest = str(entry.get("object") or "")
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("manifesto incremental contém referência de conteúdo inválida")
        digests.add(digest)
    return digests


def sync_file_manifest_to_cloud(manifest_path: Path, repository_root: Path, cloud_root: Path, cloud_path: Path):
    manifest = load_file_manifest(manifest_path)
    ensure_writable_directory(cloud_root / FILE_OBJECT_STORE)
    copied_objects = 0
    copied_bytes = 0
    for digest in sorted(manifest_object_digests(manifest)):
        source = file_object_path(repository_root, digest)
        if not source.is_file():
            raise RuntimeError(f"conteúdo {digest} não encontrado para sincronização em nuvem")
        destination = file_object_path(cloud_root, digest)
        if destination.is_file():
            continue
        ensure_writable_directory(destination.parent)
        shutil.copy2(source, destination)
        copied_objects += 1
        copied_bytes += destination.stat().st_size
    ensure_writable_directory(cloud_path.parent)
    shutil.copy2(manifest_path, cloud_path)
    return {"cloudObjectsCopied": copied_objects, "cloudBytesCopied": copied_bytes + cloud_path.stat().st_size}


def copy_promotions(job, daily_path: Path, scheduled_time: str, local_date: dt.date):
    root = Path(str(job["destinationPath"]))
    ensure_writable_directory(root)
    tiers = promotion_tiers(
        scheduled_time,
        job["times"],
        local_date,
        job.get("cloudSyncPath"),
        job.get("operatingWindows"),
    )
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
            if daily_path.name.endswith(FILE_MANIFEST_SUFFIX):
                sync_file_manifest_to_cloud(monthly, root, cloud_root, cloud)
            else:
                shutil.copy2(monthly, cloud)
    return tiers


def remove_unreferenced_file_objects(repository_root: Path):
    manifests = []
    for tier in ("diario", "semana", "mes"):
        tier_root = repository_root / tier
        if tier_root.exists():
            manifests.extend(path for path in tier_root.rglob(f"*{FILE_MANIFEST_SUFFIX}") if path.is_file())
    referenced = set()
    try:
        for path in manifests:
            referenced.update(manifest_object_digests(load_file_manifest(path)))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"objectsRemoved": 0, "objectGcSkipped": True}
    object_root = repository_root / FILE_OBJECT_STORE
    removed = 0
    if object_root.exists():
        for path in object_root.rglob("*.gz"):
            digest = path.name[:-3]
            if digest not in referenced:
                try:
                    path.unlink()
                    removed += 1
                except FileNotFoundError:
                    pass
        for directory in sorted((item for item in object_root.rglob("*") if item.is_dir()), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
    return {"objectsRemoved": removed, "objectGcSkipped": False}


def apply_retention(job, now=None):
    root = Path(str(job["destinationPath"]))
    result = {
        "dailyRemoved": remove_expired_files(root / "diario", int(job.get("dailyRetentionDays") or 7), now),
        "weeklyRemoved": remove_expired_files(root / "semana", int(job.get("weeklyRetentionWeeks") or 5) * 7, now),
        "monthlyRemoved": remove_expired_files(root / "mes", int(job.get("monthlyRetentionMonths") or 12) * 31, now),
    }
    if str(job.get("databaseType") or "MYSQL").upper() == "FILES":
        result.update(remove_unreferenced_file_objects(root))
    return result


def file_restore_path(destination: Path, manifest_path: str):
    parts = str(manifest_path or "").split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"caminho inseguro no manifesto: {manifest_path}")
    target = destination.joinpath(*parts)
    destination_resolved = destination.resolve()
    target_parent = target.parent.resolve()
    if target_parent != destination_resolved and destination_resolved not in target_parent.parents:
        raise ValueError(f"caminho fora do destino no manifesto: {manifest_path}")
    return target


def locate_file_repository(manifest_path: Path):
    resolved = manifest_path.resolve()
    for candidate in resolved.parents:
        if (candidate / FILE_OBJECT_STORE).is_dir():
            return candidate
    raise RuntimeError("depósito de conteúdo incremental não encontrado junto ao manifesto")


def restore_incremental_file_backup(manifest_path: Path, destination: Path):
    manifest_path = manifest_path.expanduser()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifesto não encontrado: {manifest_path}")
    manifest = load_file_manifest(manifest_path)
    repository_root = locate_file_repository(manifest_path)
    destination = destination.expanduser()
    ensure_writable_directory(destination)
    entries = manifest["entries"]
    restored_files = 0
    restored_bytes = 0

    for entry in sorted((item for item in entries if item.get("type") == "directory"), key=lambda item: item["path"].count("/")):
        target = file_restore_path(destination, entry["path"])
        target.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        entry_type = entry.get("type")
        if entry_type == "directory":
            continue
        target = file_restore_path(destination, entry.get("path"))
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"a restauração não sobrescreve caminho existente: {target}")
        if entry_type == "symlink":
            target.symlink_to(
                str(entry.get("target") or ""),
                target_is_directory=bool(entry.get("targetIsDirectory")),
            )
            continue
        if entry_type != "file":
            raise ValueError(f"tipo desconhecido no manifesto: {entry_type}")
        digest = str(entry.get("object") or "")
        object_path = file_object_path(repository_root, digest)
        if not object_path.is_file():
            raise FileNotFoundError(f"conteúdo {digest} não encontrado para restaurar {entry['path']}")
        temporary = target.with_name(f"{target.name}.part-{os.getpid()}-{time.time_ns()}")
        calculated = hashlib.sha256()
        try:
            with gzip.open(object_path, "rb") as source, temporary.open("wb") as output:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    calculated.update(block)
                    output.write(block)
            if calculated.hexdigest() != digest:
                raise RuntimeError(f"SHA-256 inválido no conteúdo de {entry['path']}")
            os.replace(temporary, target)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        try:
            target.chmod(int(entry.get("mode") or 0o600))
            os.utime(target, ns=(int(entry["mtimeNs"]), int(entry["mtimeNs"])))
        except OSError:
            pass
        restored_files += 1
        restored_bytes += int(entry.get("size") or 0)

    for entry in sorted((item for item in entries if item.get("type") == "directory"), key=lambda item: item["path"].count("/"), reverse=True):
        target = file_restore_path(destination, entry["path"])
        try:
            target.chmod(int(entry.get("mode") or 0o700))
            os.utime(target, ns=(int(entry["mtimeNs"]), int(entry["mtimeNs"])))
        except OSError:
            pass
    return {"filesRestored": restored_files, "bytesRestored": restored_bytes}


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
    extension = "files.json.gz" if backup_type == "FILES" else "sql.gz"
    source_name = "arquivos" if backup_type == "FILES" else safe_name(job["databaseName"])
    filename = f"{source_name}_{local_now.strftime('%Y-%m-%d_%H-%M-%S')}.{extension}"
    daily_path = root / "diario" / local_now.strftime("%Y-%m-%d") / filename
    try:
        ensure_writable_directory(root)
        ensure_writable_directory(root / "diario")
        ensure_writable_directory(daily_path.parent)
        checksum = None
        file_statistics = None
        if backup_type == "FILES":
            checksum, file_statistics = create_incremental_file_backup(job, daily_path, started)
        else:
            create_dump(job, daily_path)
        tiers = copy_promotions(job, daily_path, scheduled_time, local_now.date())
        retention = apply_retention(job)
        if file_statistics:
            message = (
                f"Backup incremental concluído: {file_statistics['changedFiles']} novo(s)/alterado(s), "
                f"{file_statistics['unchangedFiles']} reutilizado(s) e "
                f"{file_statistics['deletedFiles']} excluído(s) desde o ponto anterior."
            )
            reported_size = file_statistics["bytesWritten"]
        else:
            message = "Backup de banco concluído e validado com SHA-256."
            reported_size = daily_path.stat().st_size
        payload = {
            **running,
            "status": "SUCCESS",
            "completedAt": dt.datetime.now(dt.UTC).isoformat(),
            "filePath": str(daily_path),
            "sizeBytes": reported_size,
            "sha256": checksum or sha256_file(daily_path),
            "tiers": tiers,
            "message": message,
            "details": {"retention": retention, "incremental": file_statistics},
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
    windows = normalize_operating_windows(job.get("operatingWindows"))
    window = windows.get(str(local_now.weekday())) if windows else None
    if windows and not window:
        return None, local_now
    current_time = local_now.strftime("%H:%M")
    if window and not (window["start"] <= current_time < window["end"]):
        return None, local_now
    today = local_now.date().isoformat()
    completed = set(state.get("completedSlots", {}).get(today, []))
    day_times = (window.get("times") or times) if window else times
    due = [
        item for item in day_times
        if item <= current_time
        and item not in completed
        and (not window or window["start"] <= item < window["end"])
    ]
    return (due[-1], local_now) if due else (None, local_now)


def trim_state(state, local_date):
    slots = state.setdefault("completedSlots", {})
    minimum = (local_date - dt.timedelta(days=14)).isoformat()
    for key in list(slots):
        if key < minimum:
            del slots[key]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agente de backup do módulo Tecnologia")
    parser.add_argument("--config", type=Path, help="JSON baixado no cadastro do backup")
    parser.add_argument("--once", action="store_true", help="consulta e executa somente um ciclo")
    parser.add_argument("--run-now", action="store_true", help="força um backup imediato")
    parser.add_argument("--validate", action="store_true", help="valida o JSON e a configuração remota")
    parser.add_argument("--ca-file", type=Path, help="CA interna PEM usada para validar o HTTPS do portal")
    parser.add_argument("--restore-manifest", type=Path, help="restaura um manifesto incremental de arquivos")
    parser.add_argument("--restore-to", type=Path, help="pasta nova/vazia que receberá a restauração")
    args = parser.parse_args(argv)
    if args.restore_manifest:
        if not args.restore_to:
            parser.error("--restore-to é obrigatório com --restore-manifest")
        restored = restore_incremental_file_backup(args.restore_manifest, args.restore_to)
        print(
            f"Restauração concluída: {restored['filesRestored']} arquivo(s), "
            f"{restored['bytesRestored']} byte(s)."
        )
        return 0
    if not args.config:
        parser.error("--config é obrigatório para validar ou executar backups")
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
