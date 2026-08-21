from __future__ import annotations

import concurrent.futures
import ipaddress
import json
import os
import random
import re
import socket
import struct
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEVICE_TYPES = {
    "INTERNET", "ROTEADOR", "SERVIDOR", "IMPRESSORA",
    "COMPUTADOR", "NOTEBOOK", "RELOGIO_PONTO", "NVR", "OUTRO",
}
PROBE_TYPES = {"ICMP", "TCP", "SNMP", "PROMETHEUS"}
PRINTER_PORTS = (9100, 631, 515)
COMPUTER_PORTS = (22, 135, 139, 445, 3389, 5357, 5985, 5986, 9100, 9182)


def normalize_host(value: Any) -> str:
    host = str(value or "").strip().lower()
    if not host or len(host) > 253:
        raise ValueError("Host ou IP inválido.")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", host):
        raise ValueError("Host ou IP inválido.")
    return host


def normalize_device_payload(payload: dict[str, Any]) -> dict[str, Any]:
    device_type = str(payload.get("tipo") or "OUTRO").strip().upper()
    probe_type = str(payload.get("sonda") or "ICMP").strip().upper()
    if device_type not in DEVICE_TYPES:
        raise ValueError("Tipo de equipamento inválido.")
    if probe_type not in PROBE_TYPES:
        raise ValueError("Tipo de teste inválido.")
    name = str(payload.get("nome") or "").strip()
    if not name or len(name) > 120:
        raise ValueError("Informe um nome com até 120 caracteres.")
    host = normalize_host(payload.get("host"))
    port_value = payload.get("porta")
    port = int(port_value or 0)
    if probe_type == "TCP" and not (1 <= port <= 65535):
        raise ValueError("O teste TCP exige uma porta entre 1 e 65535.")
    if port and not (1 <= port <= 65535):
        raise ValueError("Porta inválida.")
    latency_warning = float(payload.get("latenciaAlertaMs") or 80)
    loss_warning = float(payload.get("perdaAlertaPct") or 5)
    if not (1 <= latency_warning <= 60000):
        raise ValueError("Limite de latência inválido.")
    if not (0 <= loss_warning <= 100):
        raise ValueError("Limite de perda inválido.")
    snmp_community = str(payload.get("snmpCommunity") or "").strip()
    if len(snmp_community) > 160:
        raise ValueError("Comunidade SNMP inválida.")
    snmp_port = int(payload.get("snmpPort") or 161)
    if not (1 <= snmp_port <= 65535):
        raise ValueError("Porta SNMP inválida.")
    agent_port_value = payload.get("agentPort")
    agent_port = int(agent_port_value or 0) or None
    if agent_port is not None and not (1 <= agent_port <= 65535):
        raise ValueError("Porta do agente inválida.")
    if probe_type == "SNMP" and not snmp_community and not bool(payload.get("preserveSnmpCommunity")):
        raise ValueError("Informe a comunidade SNMP somente leitura.")
    if probe_type == "PROMETHEUS" and not agent_port:
        raise ValueError("O agente Prometheus exige a porta do exporter.")
    agent_path = str(payload.get("agentPath") or "/metrics").strip()
    if not re.fullmatch(r"/[A-Za-z0-9._~!$&'()*+,;=:@%/-]{0,119}", agent_path):
        raise ValueError("Caminho de métricas inválido.")

    thresholds = {
        "download_alerta_mbps": float(payload.get("downloadAlertMbps") or 50),
        "upload_alerta_mbps": float(payload.get("uploadAlertMbps") or 10),
        "cpu_alerta_pct": float(payload.get("cpuAlertPct") or 90),
        "memoria_alerta_pct": float(payload.get("memoryAlertPct") or 90),
        "disco_alerta_pct": float(payload.get("diskAlertPct") or 90),
        "trafego_alerta_mbps": float(payload.get("trafficAlertMbps") or 100),
    }
    for field in ("cpu_alerta_pct", "memoria_alerta_pct", "disco_alerta_pct"):
        if not (1 <= thresholds[field] <= 100):
            raise ValueError("Limite percentual do agente inválido.")
    for field in ("download_alerta_mbps", "upload_alerta_mbps", "trafego_alerta_mbps"):
        if not (0.1 <= thresholds[field] <= 100000):
            raise ValueError("Limite de velocidade inválido.")
    return {
        "nome": name,
        "tipo": device_type,
        "host": host,
        "porta": port or None,
        "sonda": probe_type,
        "localizacao": str(payload.get("localizacao") or "").strip()[:160],
        "observacoes": str(payload.get("observacoes") or "").strip()[:500],
        "critico": 1 if bool(payload.get("critico", False)) else 0,
        "ativo": 1 if bool(payload.get("ativo", True)) else 0,
        "latencia_alerta_ms": latency_warning,
        "perda_alerta_pct": loss_warning,
        **thresholds,
        "snmp_community": snmp_community,
        "snmp_port": snmp_port,
        "agente_porta": agent_port,
        "agente_path": agent_path,
    }


def parse_ping_output(output: str, return_code: int = 0) -> dict[str, Any]:
    text = str(output or "")
    loss_match = re.search(r"([0-9]+(?:\.[0-9]+)?)%\s+packet loss", text, flags=re.I)
    timing_match = re.search(
        r"(?:rtt|round-trip)[^=]*=\s*([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+)",
        text,
        flags=re.I,
    )
    loss = float(loss_match.group(1)) if loss_match else (100.0 if return_code else 0.0)
    return {
        "reachable": loss < 100,
        "packetLossPct": round(loss, 2),
        "latencyMs": round(float(timing_match.group(2)), 2) if timing_match else None,
        "jitterMs": round(float(timing_match.group(4)), 2) if timing_match else None,
    }


def ping_host(host: str, count: int = 4, timeout_seconds: int = 1) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            ["ping", "-n", "-c", str(count), "-W", str(timeout_seconds), host],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(4, count * timeout_seconds + 3),
        )
        parsed = parse_ping_output(f"{result.stdout}\n{result.stderr}", result.returncode)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        parsed = {"reachable": False, "packetLossPct": 100.0, "latencyMs": None, "jitterMs": None}
    parsed["elapsedMs"] = round((time.monotonic() - started) * 1000, 2)
    return parsed


def tcp_host(host: str, port: int, timeout_seconds: float = 2.0) -> dict[str, Any]:
    started = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_seconds):
            pass
        return {"reachable": True, "latencyMs": round((time.monotonic() - started) * 1000, 2)}
    except OSError as exc:
        return {
            "reachable": False,
            "latencyMs": round((time.monotonic() - started) * 1000, 2),
            "error": type(exc).__name__,
        }


def dns_probe(hostname: str = "example.com") -> dict[str, Any]:
    started = time.monotonic()
    try:
        addresses = sorted({row[4][0] for row in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)})
        return {
            "ok": True,
            "elapsedMs": round((time.monotonic() - started) * 1000, 2),
            "addresses": addresses[:3],
        }
    except OSError as exc:
        return {
            "ok": False,
            "elapsedMs": round((time.monotonic() - started) * 1000, 2),
            "error": type(exc).__name__,
        }


def _skip_dns_name(data: bytes, offset: int) -> int:
    if offset >= len(data):
        return offset
    if data[offset] & 0xC0 == 0xC0:
        return offset + 2
    while offset < len(data):
        size = data[offset]
        offset += 1
        if size == 0:
            return offset
        offset += size
    return offset


def netbios_node_status(host: str, timeout_seconds: float = 0.35) -> dict[str, Any]:
    host = normalize_host(host)
    transaction_id = random.randrange(65536)
    wildcard = b"*" + (b"\0" * 15)
    encoded = b"".join(bytes((65 + (value >> 4), 65 + (value & 15))) for value in wildcard)
    request = (
        struct.pack("!HHHHHH", transaction_id, 0, 1, 0, 0, 0)
        + bytes((32,)) + encoded + b"\0" + struct.pack("!HH", 0x21, 1)
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout_seconds)
    try:
        sock.sendto(request, (host, 137))
        data, _ = sock.recvfrom(4096)
    except OSError:
        return {"ok": False, "name": ""}
    finally:
        sock.close()
    if len(data) < 12:
        return {"ok": False, "name": ""}
    response_id, _flags, question_count, answer_count, _authority, _additional = struct.unpack("!HHHHHH", data[:12])
    if response_id != transaction_id:
        return {"ok": False, "name": ""}
    offset = 12
    for _ in range(question_count):
        offset = _skip_dns_name(data, offset) + 4
    names = []
    for _ in range(answer_count):
        offset = _skip_dns_name(data, offset)
        if offset + 10 > len(data):
            break
        record_type, _record_class, _ttl, data_length = struct.unpack("!HHIH", data[offset:offset + 10])
        offset += 10
        end = min(len(data), offset + data_length)
        if record_type == 0x21 and offset < end:
            count = data[offset]
            offset += 1
            for _ in range(count):
                if offset + 18 > end:
                    break
                name = data[offset:offset + 15].decode("ascii", errors="ignore").rstrip()
                suffix = data[offset + 15]
                flags = struct.unpack("!H", data[offset + 16:offset + 18])[0]
                offset += 18
                if name:
                    names.append({"name": name, "suffix": suffix, "group": bool(flags & 0x8000)})
        offset = end
    workstation = next((row["name"] for row in names if row["suffix"] == 0 and not row["group"]), "")
    return {"ok": bool(workstation), "name": workstation, "names": names}


def _previous_telemetry(device: dict[str, Any]) -> dict[str, Any]:
    details = device.get("ultima_detalhes") or {}
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except (TypeError, ValueError):
            details = {}
    telemetry = details.get("telemetry") if isinstance(details, dict) else None
    return telemetry if isinstance(telemetry, dict) else {}


def _counter_rates(current: dict[str, float], previous: dict[str, Any], checked_at: float) -> dict[str, float | None]:
    previous_counters = previous.get("counters") if isinstance(previous.get("counters"), dict) else {}
    previous_at = float(previous.get("checkedEpoch") or 0)
    elapsed = checked_at - previous_at
    rates: dict[str, float | None] = {"downloadMbps": None, "uploadMbps": None}
    if elapsed <= 0 or elapsed > 86400:
        return rates
    for source, target in (("rxBytes", "downloadMbps"), ("txBytes", "uploadMbps")):
        old = previous_counters.get(source)
        new = current.get(source)
        if old is None or new is None or float(new) < float(old):
            continue
        rates[target] = round((float(new) - float(old)) * 8 / elapsed / 1_000_000, 3)
    return rates


def _snmp_walk(host: str, community: str, port: int, oid: str) -> list[tuple[str, str]]:
    try:
        result = subprocess.run(
            [
                "snmpwalk", "-v2c", "-c", community, "-t", "2", "-r", "0",
                "-On", f"{host}:{int(port)}", oid,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("cliente SNMP indisponível") from exc
    if result.returncode:
        raise RuntimeError("equipamento não respondeu ao SNMP")
    rows: list[tuple[str, str]] = []
    for raw_line in result.stdout.splitlines():
        if " = " not in raw_line:
            continue
        item_oid, value = raw_line.split(" = ", 1)
        if ": " in value:
            value = value.split(": ", 1)[1]
        rows.append((item_oid.strip(), value.strip().strip('"')))
    return rows


def _snmp_number(value: Any) -> float | None:
    match = re.search(r"\((-?[0-9]+(?:\.[0-9]+)?)\)|(-?[0-9]+(?:\.[0-9]+)?)", str(value or ""))
    if not match:
        return None
    return float(match.group(1) or match.group(2))


def collect_snmp_metrics(device: dict[str, Any]) -> dict[str, Any]:
    host = normalize_host(device.get("host"))
    community = str(device.get("snmp_community") or "").strip()
    if not community:
        raise RuntimeError("comunidade SNMP não configurada")
    port = int(device.get("snmp_port") or 161)
    system_rows = _snmp_walk(host, community, port, ".1.3.6.1.2.1.1")
    name_rows = _snmp_walk(host, community, port, ".1.3.6.1.2.1.31.1.1.1.1")
    rx_rows = _snmp_walk(host, community, port, ".1.3.6.1.2.1.31.1.1.1.6")
    tx_rows = _snmp_walk(host, community, port, ".1.3.6.1.2.1.31.1.1.1.10")
    cpu_rows = _snmp_walk(host, community, port, ".1.3.6.1.2.1.25.3.3.1.2")

    def indexed(rows: list[tuple[str, str]]) -> dict[str, Any]:
        return {oid.rsplit(".", 1)[-1]: value for oid, value in rows}

    names = indexed(name_rows)
    rx = indexed(rx_rows)
    tx = indexed(tx_rows)
    ignored = {"lo", "loopback", "null0"}
    rx_total = sum(_snmp_number(value) or 0 for index, value in rx.items() if names.get(index, "").lower() not in ignored)
    tx_total = sum(_snmp_number(value) or 0 for index, value in tx.items() if names.get(index, "").lower() not in ignored)
    checked_at = time.time()
    counters = {"rxBytes": rx_total, "txBytes": tx_total}
    rates = _counter_rates(counters, _previous_telemetry(device), checked_at)
    cpu_values = [number for _, value in cpu_rows if (number := _snmp_number(value)) is not None]
    system_values = {oid: value for oid, value in system_rows}
    system_name = next((value for oid, value in system_values.items() if oid.endswith(".1.5.0")), "")
    description = next((value for oid, value in system_values.items() if oid.endswith(".1.1.0")), "")
    uptime_raw = next((value for oid, value in system_values.items() if oid.endswith(".1.3.0")), "")
    return {
        "ok": True,
        "protocol": "SNMPv2c",
        "checkedEpoch": checked_at,
        "systemName": system_name,
        "description": description[:240],
        "uptimeTicks": _snmp_number(uptime_raw),
        "cpuPct": round(sum(cpu_values) / len(cpu_values), 1) if cpu_values else None,
        "memoryPct": None,
        "diskPct": None,
        "downloadMbps": rates["downloadMbps"],
        "uploadMbps": rates["uploadMbps"],
        "counters": counters,
        "interfaces": len(names),
    }


def _prometheus_labels(raw: str) -> dict[str, str]:
    def unescape(value: str) -> str:
        return re.sub(
            r'\\([\\n"])',
            lambda match: {"\\": "\\", "n": "\n", '"': '"'}[match.group(1)],
            value,
        )

    return {
        key: unescape(value)
        for key, value in re.findall(r'([A-Za-z_][A-Za-z0-9_]*)="((?:\\.|[^"\\])*)"', raw or "")
    }


def _parse_prometheus(text: str) -> dict[str, list[tuple[dict[str, str], float]]]:
    metrics: dict[str, list[tuple[dict[str, str], float]]] = {}
    pattern = re.compile(r"^([A-Za-z_:][A-Za-z0-9_:]*)(?:\{(.*)\})?\s+([-+0-9.eE]+)(?:\s+[0-9]+)?$")
    for raw_line in str(text or "").splitlines():
        if not raw_line or raw_line.startswith("#"):
            continue
        match = pattern.match(raw_line.strip())
        if not match:
            continue
        try:
            value = float(match.group(3))
        except ValueError:
            continue
        metrics.setdefault(match.group(1), []).append((_prometheus_labels(match.group(2) or ""), value))
    return metrics


def _metric_sum(metrics: dict[str, list[tuple[dict[str, str], float]]], names: tuple[str, ...], *, exclude_loopback=False) -> float | None:
    for name in names:
        rows = metrics.get(name) or []
        values = [
            value for labels, value in rows
            if not exclude_loopback or labels.get("device", labels.get("nic", "")).lower() not in {"lo", "loopback", "software loopback interface 1"}
        ]
        if values:
            return sum(values)
    return None


def _first_metric_labels(
    metrics: dict[str, list[tuple[dict[str, str], float]]], names: tuple[str, ...]
) -> dict[str, str]:
    for name in names:
        rows = metrics.get(name) or []
        if rows:
            return rows[0][0]
    return {}


def collect_prometheus_metrics(device: dict[str, Any]) -> dict[str, Any]:
    host = normalize_host(device.get("host"))
    port = int(device.get("agente_porta") or 0)
    if not port:
        raise RuntimeError("porta do exporter não configurada")
    path = str(device.get("agente_path") or "/metrics")
    url = f"http://{host}:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read(8 * 1024 * 1024).decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError("exporter Prometheus não respondeu") from exc
    metrics = _parse_prometheus(body)
    has_machine_metrics = any(
        name.startswith("node_") or name.startswith("windows_")
        for name in metrics
    )
    if not has_machine_metrics:
        if any(name.startswith("prometheus_") for name in metrics):
            raise RuntimeError(
                "porta do servidor Prometheus, sem métricas da máquina; "
                "use Node Exporter :9100 ou Windows Exporter :9182"
            )
        raise RuntimeError("endpoint respondeu sem métricas de sistema compatíveis")

    cpu_rows = metrics.get("node_cpu_seconds_total") or metrics.get("windows_cpu_time_total") or []
    cpu_total = sum(value for _, value in cpu_rows)
    cpu_idle = sum(value for labels, value in cpu_rows if labels.get("mode") == "idle")
    total_memory = _metric_sum(metrics, (
        "node_memory_MemTotal_bytes",
        "windows_memory_physical_total_bytes",
        "windows_cs_physical_memory_bytes",
    ))
    available_memory = _metric_sum(metrics, (
        "node_memory_MemAvailable_bytes",
        "windows_memory_available_bytes",
        "windows_os_physical_memory_free_bytes",
    ))
    rx_total = _metric_sum(metrics, ("node_network_receive_bytes_total", "windows_net_bytes_received_total"), exclude_loopback=True)
    tx_total = _metric_sum(metrics, ("node_network_transmit_bytes_total", "windows_net_bytes_sent_total"), exclude_loopback=True)
    checked_at = time.time()
    counters = {
        "cpuTotal": cpu_total,
        "cpuIdle": cpu_idle,
        "rxBytes": rx_total,
        "txBytes": tx_total,
    }
    previous = _previous_telemetry(device)
    previous_counters = previous.get("counters") if isinstance(previous.get("counters"), dict) else {}
    cpu_pct = None
    cpu_delta = cpu_total - float(previous_counters.get("cpuTotal") or cpu_total)
    idle_delta = cpu_idle - float(previous_counters.get("cpuIdle") or cpu_idle)
    if cpu_delta > 0 and 0 <= idle_delta <= cpu_delta:
        cpu_pct = round((1 - idle_delta / cpu_delta) * 100, 1)
    rates = _counter_rates(counters, previous, checked_at)

    disk_usages = []
    disks = []
    size_names = ("node_filesystem_size_bytes", "windows_logical_disk_size_bytes")
    free_names = ("node_filesystem_avail_bytes", "windows_logical_disk_free_bytes")
    for size_name, free_name in zip(size_names, free_names):
        free_by_key = {
            (labels.get("device"), labels.get("mountpoint", labels.get("volume"))): value
            for labels, value in metrics.get(free_name, [])
        }
        for labels, size in metrics.get(size_name, []):
            key = (labels.get("device"), labels.get("mountpoint", labels.get("volume")))
            free = free_by_key.get(key)
            filesystem = labels.get("fstype", "").lower()
            if size > 0 and free is not None and filesystem not in {"tmpfs", "devtmpfs", "overlay", "squashfs"}:
                usage = (1 - free / size) * 100
                disk_usages.append(usage)
                disks.append({
                    "name": labels.get("volume") or labels.get("mountpoint") or labels.get("device") or "Disco",
                    "sizeBytes": round(size),
                    "freeBytes": round(free),
                    "usedPct": round(usage, 1),
                })
    memory_pct = None
    if total_memory and available_memory is not None:
        memory_pct = round((1 - available_memory / total_memory) * 100, 1)
    os_labels = _first_metric_labels(metrics, ("windows_os_info", "node_uname_info"))
    hostname_labels = _first_metric_labels(metrics, (
        "windows_os_hostname",
        "windows_cs_hostname",
        "node_uname_info",
    ))
    system_name = (
        hostname_labels.get("hostname")
        or hostname_labels.get("nodename")
        or os_labels.get("hostname")
        or ""
    )
    os_name = os_labels.get("product") or os_labels.get("sysname") or ""
    os_version = os_labels.get("version") or os_labels.get("release") or ""
    os_build = os_labels.get("build_number") or os_labels.get("build") or ""
    architecture = os_labels.get("machine") or os_labels.get("architecture") or ""
    cpu_names = {
        labels.get("cpu") or labels.get("core")
        for labels, _ in cpu_rows
        if labels.get("cpu") is not None or labels.get("core") is not None
    }
    logical_processors = _metric_sum(metrics, (
        "windows_cpu_logical_processor",
        "windows_cs_logical_processors",
    ))
    cpu_cores = int(logical_processors) if logical_processors else len(cpu_names) or None
    boot_time = _metric_sum(metrics, ("node_boot_time_seconds",))
    windows_boot_time = _metric_sum(metrics, ("windows_system_boot_time_timestamp",))
    windows_uptime = _metric_sum(metrics, ("windows_system_system_up_time",))
    uptime_seconds = windows_uptime
    if boot_time and checked_at >= boot_time:
        uptime_seconds = checked_at - boot_time
    elif windows_boot_time and checked_at >= windows_boot_time:
        uptime_seconds = checked_at - windows_boot_time
    interface_rows = (
        metrics.get("node_network_receive_bytes_total")
        or metrics.get("windows_net_bytes_received_total")
        or []
    )
    interfaces = sorted({
        labels.get("device") or labels.get("nic")
        for labels, _ in interface_rows
        if (labels.get("device") or labels.get("nic"))
        and (labels.get("device") or labels.get("nic", "")).lower()
        not in {"lo", "loopback", "software loopback interface 1"}
    })
    return {
        "ok": True,
        "protocol": "Prometheus",
        "checkedEpoch": checked_at,
        "systemName": system_name,
        "osName": os_name,
        "osVersion": os_version,
        "osBuild": os_build,
        "architecture": architecture,
        "cpuCores": cpu_cores,
        "cpuPct": cpu_pct,
        "memoryPct": memory_pct,
        "memoryTotalBytes": round(total_memory) if total_memory is not None else None,
        "diskPct": round(max(disk_usages), 1) if disk_usages else None,
        "disks": disks[:20],
        "downloadMbps": rates["downloadMbps"],
        "uploadMbps": rates["uploadMbps"],
        "load1": (_metric_sum(metrics, ("node_load1",))),
        "uptimeSeconds": round(uptime_seconds) if uptime_seconds is not None else None,
        "interfaces": interfaces[:30],
        "counters": counters,
        "series": sum(len(rows) for rows in metrics.values()),
    }


def _http_download(url: str, size: int, timeout: float) -> int:
    query = urllib.parse.urlencode({"bytes": int(size), "cache": time.time_ns()})
    separator = "&" if "?" in url else "?"
    request = urllib.request.Request(f"{url}{separator}{query}", headers={"User-Agent": "NanotechSoft-Monitor/1.0"})
    received = 0
    with urllib.request.urlopen(request, timeout=timeout) as response:
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            received += len(chunk)
    return received


def _http_upload(url: str, size: int, timeout: float) -> int:
    data = b"0" * int(size)
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/octet-stream", "User-Agent": "NanotechSoft-Monitor/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read(64 * 1024)
    return len(data)


def measure_internet_speed(
    download_url: str | None = None,
    upload_url: str | None = None,
    download_bytes: int | None = None,
    upload_bytes: int | None = None,
    streams: int = 4,
) -> dict[str, Any]:
    download_url = download_url or os.environ.get("TECH_SPEED_DOWNLOAD_URL", "https://speed.cloudflare.com/__down")
    upload_url = upload_url or os.environ.get("TECH_SPEED_UPLOAD_URL", "https://speed.cloudflare.com/__up")
    download_bytes = max(1_000_000, int(download_bytes or os.environ.get("TECH_SPEED_DOWNLOAD_BYTES", "10000000")))
    upload_bytes = max(500_000, int(upload_bytes or os.environ.get("TECH_SPEED_UPLOAD_BYTES", "4000000")))
    streams = min(8, max(1, int(streams)))
    timeout = float(os.environ.get("TECH_SPEED_TIMEOUT_SECONDS", "25"))
    started = time.monotonic()
    try:
        _http_download(download_url, 0, timeout)
        latency_samples = []
        for _ in range(3):
            latency_started = time.monotonic()
            _http_download(download_url, 0, timeout)
            latency_samples.append((time.monotonic() - latency_started) * 1000)
        latency_ms = round(sorted(latency_samples)[len(latency_samples) // 2], 2)
        per_download = max(250_000, download_bytes // streams)
        transfer_started = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=streams) as executor:
            downloaded = sum(executor.map(lambda _: _http_download(download_url, per_download, timeout), range(streams)))
        download_seconds = max(0.001, time.monotonic() - transfer_started)
        per_upload = max(125_000, upload_bytes // streams)
        transfer_started = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=streams) as executor:
            uploaded = sum(executor.map(lambda _: _http_upload(upload_url, per_upload, timeout), range(streams)))
        upload_seconds = max(0.001, time.monotonic() - transfer_started)
        download_mbps = round(downloaded * 8 / download_seconds / 1_000_000, 2)
        upload_mbps = round(uploaded * 8 / upload_seconds / 1_000_000, 2)
        return {
            "status": "OK",
            "downloadMbps": download_mbps,
            "uploadMbps": upload_mbps,
            "latencyMs": latency_ms,
            "message": f"download {download_mbps:.1f} Mbps, upload {upload_mbps:.1f} Mbps",
            "details": {
                "downloadBytes": downloaded,
                "uploadBytes": uploaded,
                "downloadSeconds": round(download_seconds, 3),
                "uploadSeconds": round(upload_seconds, 3),
                "elapsedSeconds": round(time.monotonic() - started, 3),
                "provider": "Cloudflare",
                "latencySamplesMs": [round(value, 2) for value in latency_samples],
            },
        }
    except Exception as exc:
        return {
            "status": "FALHA",
            "downloadMbps": None,
            "uploadMbps": None,
            "latencyMs": None,
            "message": f"teste de velocidade falhou ({type(exc).__name__})",
            "details": {"elapsedSeconds": round(time.monotonic() - started, 3)},
        }


def probe_device(device: dict[str, Any]) -> dict[str, Any]:
    host = normalize_host(device.get("host"))
    probe_type = str(device.get("sonda") or "ICMP").upper()
    port = int(device.get("porta") or 0)
    ping_result = ping_host(host)
    tcp_result = tcp_host(host, port) if port else None
    dns_result = dns_probe() if str(device.get("tipo") or "").upper() == "INTERNET" else None
    netbios_result = None
    if str(device.get("tipo") or "").upper() in {"COMPUTADOR", "NOTEBOOK"}:
        netbios_result = netbios_node_status(host)

    reachable = (
        ping_result["reachable"]
        or bool(tcp_result and tcp_result["reachable"])
        or bool(netbios_result and netbios_result["ok"])
    )
    latency = ping_result.get("latencyMs")
    if latency is None and tcp_result:
        latency = tcp_result.get("latencyMs")
    loss = float(ping_result.get("packetLossPct") or 0)
    jitter = ping_result.get("jitterMs")
    service_failed = bool(port and tcp_result and not tcp_result["reachable"])
    dns_failed = bool(dns_result and not dns_result["ok"])
    telemetry = None
    telemetry_error = ""
    if probe_type in {"SNMP", "PROMETHEUS"} and reachable:
        try:
            telemetry = collect_snmp_metrics(device) if probe_type == "SNMP" else collect_prometheus_metrics(device)
        except RuntimeError as exc:
            telemetry_error = str(exc)

    resource_reasons = []
    if telemetry:
        for field, threshold_field, label in (
            ("cpuPct", "cpu_alerta_pct", "CPU"),
            ("memoryPct", "memoria_alerta_pct", "memória"),
            ("diskPct", "disco_alerta_pct", "disco"),
        ):
            value = telemetry.get(field)
            threshold = float(device.get(threshold_field) or 90)
            if value is not None and float(value) >= threshold:
                resource_reasons.append(f"{label} {float(value):.0f}%")
        traffic_threshold = float(device.get("trafego_alerta_mbps") or 100)
        traffic = max(float(telemetry.get("downloadMbps") or 0), float(telemetry.get("uploadMbps") or 0))
        if traffic >= traffic_threshold:
            resource_reasons.append(f"tráfego {traffic:.1f} Mbps")
    degraded = reachable and (
        service_failed
        or dns_failed
        or bool(telemetry_error)
        or bool(resource_reasons)
        or loss >= float(device.get("perda_alerta_pct") or 5)
        or (latency is not None and latency >= float(device.get("latencia_alerta_ms") or 80))
    )
    status = "OFFLINE" if not reachable else ("DEGRADADO" if degraded else "ONLINE")
    reasons = []
    if not reachable:
        reasons.append("sem resposta")
    if service_failed:
        reasons.append(f"porta {port} fechada")
    if dns_failed:
        reasons.append("DNS sem resposta")
    if telemetry_error:
        reasons.append(telemetry_error)
    reasons.extend(resource_reasons)
    if loss:
        reasons.append(f"perda {loss:.0f}%")
    if latency is not None and latency >= float(device.get("latencia_alerta_ms") or 80):
        reasons.append(f"latência {latency:.1f} ms")
    message = ", ".join(reasons) if reasons else "resposta normal"
    return {
        "status": status,
        "latencyMs": latency,
        "packetLossPct": loss,
        "jitterMs": jitter,
        "serviceOk": None if not port else bool(tcp_result and tcp_result["reachable"]),
        "message": message,
        "details": {
            "icmp": ping_result,
            "tcp": tcp_result,
            "dns": dns_result,
            "netbios": netbios_result,
            "probeType": probe_type,
            "telemetry": telemetry,
        },
    }


def _open_printer_ports(host: str, timeout_seconds: float) -> list[int]:
    open_ports = []
    for port in PRINTER_PORTS:
        result = tcp_host(host, port, timeout_seconds=timeout_seconds)
        if result["reachable"]:
            open_ports.append(port)
    return open_ports


def discover_printers(subnet: str, timeout_seconds: float = 0.15) -> list[dict[str, Any]]:
    network = ipaddress.ip_network(str(subnet or "").strip(), strict=False)
    if network.version != 4 or not network.is_private or network.prefixlen < 24:
        raise ValueError("Use uma sub-rede IPv4 privada com no máximo 254 hosts, por exemplo 192.168.200.0/24.")
    hosts = [str(host) for host in network.hosts()]
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(96, max(1, len(hosts)))) as executor:
        rows = list(executor.map(lambda host: (host, _open_printer_ports(host, timeout_seconds)), hosts))
    return [
        {"host": host, "ports": ports, "suggestedPort": 9100 if 9100 in ports else ports[0]}
        for host, ports in rows
        if ports
    ]


def _computer_identity(host: str, timeout_seconds: float) -> dict[str, Any] | None:
    try:
        ping = subprocess.run(
            ["ping", "-n", "-c", "1", "-W", "1", host],
            check=False, capture_output=True, text=True, timeout=3,
        )
        ping_text = f"{ping.stdout}\n{ping.stderr}"
        ttl_match = re.search(r"ttl[= ]([0-9]+)", ping_text, flags=re.I)
        ttl = int(ttl_match.group(1)) if ttl_match else None
        ping_ok = ping.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        ttl = None
        ping_ok = False
    netbios = netbios_node_status(host, timeout_seconds=timeout_seconds)
    if not ping_ok and not netbios.get("ok"):
        return None
    open_ports = [
        port for port in COMPUTER_PORTS
        if tcp_host(host, port, timeout_seconds=timeout_seconds).get("reachable")
    ]
    windows_ports = {135, 139, 445, 3389, 5357, 5985, 5986, 9182}
    netbios_name = str(netbios.get("name") or "")
    embedded_name = netbios_name.upper().startswith(("RT-", "ROUTER", "ROTEADOR", "ACCESS-POINT", "AP-"))
    if embedded_name:
        return None
    printer_only = 9100 in open_ports and not windows_ports.intersection(open_ports)
    linux_hint = 22 in open_ports and (
        (ttl is not None and ttl <= 64)
        or "linux" in netbios_name.lower()
        or "ubuntu" in netbios_name.lower()
    )
    windows_hint = bool(windows_ports.intersection(open_ports)) or bool(netbios_name and not printer_only)
    if linux_hint:
        os_family = "Linux"
    elif windows_hint:
        os_family = "Windows"
    else:
        return None
    suggested_type = "NOTEBOOK" if any(word in netbios_name.upper() for word in ("NOTE", "LAPTOP")) else "COMPUTADOR"
    return {
        "host": host,
        "name": netbios_name or host,
        "osFamily": os_family,
        "suggestedType": suggested_type,
        "ports": open_ports,
        "ttl": ttl,
        "reachable": True,
    }


def discover_computers(subnet: str, timeout_seconds: float = 0.2) -> list[dict[str, Any]]:
    network = ipaddress.ip_network(str(subnet or "").strip(), strict=False)
    if network.version != 4 or not network.is_private or network.prefixlen < 24:
        raise ValueError("Use uma sub-rede IPv4 privada com no máximo 254 hosts, por exemplo 192.168.200.0/24.")
    hosts = [str(host) for host in network.hosts()]
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(96, max(1, len(hosts)))) as executor:
        rows = [row for row in executor.map(lambda host: _computer_identity(host, timeout_seconds), hosts) if row]
    return sorted(rows, key=lambda row: ipaddress.ip_address(row["host"]))


def build_network_diagnosis(devices: list[dict[str, Any]], speed: dict[str, Any] | None = None) -> list[dict[str, str]]:
    active = [item for item in devices if item.get("ativo", True)]
    offline = [item for item in active if (item.get("ultimaMetrica") or {}).get("status") == "OFFLINE"]
    degraded = [item for item in active if (item.get("ultimaMetrica") or {}).get("status") == "DEGRADADO"]
    internet = next((item for item in active if item.get("tipo") == "INTERNET"), None)
    router = next((item for item in active if item.get("tipo") == "ROTEADOR"), None)
    notes: list[dict[str, str]] = []
    if internet and (internet.get("ultimaMetrica") or {}).get("status") == "OFFLINE":
        notes.append({"level": "critical", "text": "O destino externo está indisponível: verifique o link da operadora e o gateway."})
    if router and (router.get("ultimaMetrica") or {}).get("status") in {"OFFLINE", "DEGRADADO"}:
        notes.append({"level": "critical", "text": "O gateway 192.168.200.1 apresenta falha ou instabilidade na rede local."})
    if offline:
        notes.append({"level": "critical", "text": f"{len(offline)} equipamento(s) estão sem resposta."})
    if degraded:
        notes.append({"level": "warning", "text": f"{len(degraded)} equipamento(s) ultrapassaram os limites de perda, latência ou serviço."})
    if speed:
        if speed.get("status") == "FALHA":
            notes.append({"level": "warning", "text": "Não foi possível concluir o último teste de velocidade do link."})
        else:
            download = speed.get("downloadMbps")
            upload = speed.get("uploadMbps")
            min_download = speed.get("downloadAlertMbps")
            min_upload = speed.get("uploadAlertMbps")
            if download is not None and min_download is not None and float(download) < float(min_download):
                notes.append({"level": "warning", "text": f"Download baixo: {float(download):.1f} Mbps; mínimo configurado {float(min_download):.1f} Mbps."})
            if upload is not None and min_upload is not None and float(upload) < float(min_upload):
                notes.append({"level": "warning", "text": f"Upload baixo: {float(upload):.1f} Mbps; mínimo configurado {float(min_upload):.1f} Mbps."})
    for device in active:
        telemetry = ((device.get("ultimaMetrica") or {}).get("telemetry") or {})
        for field, label in (("cpuPct", "CPU"), ("memoryPct", "memória"), ("diskPct", "disco")):
            value = telemetry.get(field)
            threshold = {
                "cpuPct": device.get("cpuAlertPct"),
                "memoryPct": device.get("memoryAlertPct"),
                "diskPct": device.get("diskAlertPct"),
            }[field]
            if value is not None and threshold is not None and float(value) >= float(threshold):
                notes.append({"level": "warning", "text": f"{device.get('nome')}: {label} em {float(value):.0f}%."})
        traffic = max(float(telemetry.get("downloadMbps") or 0), float(telemetry.get("uploadMbps") or 0))
        if traffic and traffic >= float(device.get("trafficAlertMbps") or 100):
            notes.append({"level": "warning", "text": f"{device.get('nome')}: tráfego alto, {traffic:.1f} Mbps na interface monitorada."})
    if not offline and not degraded and active:
        notes.append({"level": "ok", "text": "Os equipamentos centrais estão estáveis nas medições atuais."})
    notes.append({
        "level": "info",
        "text": "A sonda está no servidor cabeado. SNMP/exporters medem interfaces e recursos; sinal do Wi-Fi exige dados do roteador, e consumo por IP exige NetFlow, sFlow, IPFIX ou API compatível.",
    })
    return notes
