from __future__ import annotations

import concurrent.futures
import ipaddress
import re
import socket
import subprocess
import time
from typing import Any


DEVICE_TYPES = {"INTERNET", "ROTEADOR", "SERVIDOR", "IMPRESSORA", "OUTRO"}
PROBE_TYPES = {"ICMP", "TCP"}
PRINTER_PORTS = (9100, 631, 515)


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


def probe_device(device: dict[str, Any]) -> dict[str, Any]:
    host = normalize_host(device.get("host"))
    probe_type = str(device.get("sonda") or "ICMP").upper()
    port = int(device.get("porta") or 0)
    ping_result = ping_host(host)
    tcp_result = tcp_host(host, port) if port else None
    dns_result = dns_probe() if str(device.get("tipo") or "").upper() == "INTERNET" else None

    reachable = ping_result["reachable"] or bool(tcp_result and tcp_result["reachable"])
    latency = ping_result.get("latencyMs")
    if latency is None and tcp_result:
        latency = tcp_result.get("latencyMs")
    loss = float(ping_result.get("packetLossPct") or 0)
    jitter = ping_result.get("jitterMs")
    service_failed = bool(port and tcp_result and not tcp_result["reachable"])
    dns_failed = bool(dns_result and not dns_result["ok"])
    degraded = reachable and (
        service_failed
        or dns_failed
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
        "details": {"icmp": ping_result, "tcp": tcp_result, "dns": dns_result, "probeType": probe_type},
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


def build_network_diagnosis(devices: list[dict[str, Any]]) -> list[dict[str, str]]:
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
    if not offline and not degraded and active:
        notes.append({"level": "ok", "text": "Os equipamentos centrais estão estáveis nas medições atuais."})
    notes.append({
        "level": "info",
        "text": "A sonda está no servidor cabeado: para medir sinal, canal e roaming do Wi-Fi será necessário SNMP/API do roteador ou um agente conectado por Wi-Fi.",
    })
    return notes
