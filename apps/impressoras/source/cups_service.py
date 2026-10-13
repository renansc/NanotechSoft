"""Small, testable adapter around pycups.

The portal owns authentication and audit data. CUPS remains the spooler; the
guard only maintains the native secure-release defaults on existing queues.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import threading
import time

try:
    import cups
except ImportError:  # pragma: no cover - exercised in installations without CUPS
    cups = None


class CupsUnavailable(RuntimeError):
    pass


STATE_NAMES = {
    3: "PENDENTE",
    4: "RETIDO",
    5: "IMPRIMINDO",
    6: "PARADO",
    7: "CANCELADO",
    8: "FALHOU",
    9: "CONCLUIDO",
}

PRINTER_STATES = {3: "OCIOSA", 4: "IMPRIMINDO", 5: "PARADA"}


def _utc_datetime(value):
    if value in (None, "", 0, "0"):
        return None
    try:
        return dt.datetime.fromtimestamp(int(value), tz=dt.timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None


def _positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


class CupsService:
    def __init__(self):
        self._lock = threading.RLock()

    def _connection(self):
        if cups is None:
            raise CupsUnavailable("Suporte CUPS indisponivel. Instale o pacote pycups no portal.")
        kwargs = {}
        host = str(os.environ.get("CUPS_SERVER") or "").strip()
        port = str(os.environ.get("CUPS_PORT") or "").strip()
        if host:
            kwargs["host"] = host
        if port:
            kwargs["port"] = int(port)
        user = str(os.environ.get("CUPS_USER") or "").strip()
        password = str(os.environ.get("CUPS_PASSWORD") or "")
        if user:
            cups.setUser(user)
        if password:
            cups.setPasswordCB(lambda _prompt: password)
        try:
            return cups.Connection(**kwargs)
        except Exception as exc:
            target = f"{host or 'socket local'}:{port or '631'}"
            raise CupsUnavailable(f"Nao foi possivel conectar ao CUPS em {target}: {exc}") from exc

    def printers(self):
        with self._lock:
            conn = self._connection()
            try:
                rows = conn.getPrinters()
                details = {}
                for name in rows:
                    try:
                        details[name] = conn.getPrinterAttributes(
                            name,
                            requested_attributes=[
                                "job-hold-until-default",
                                "printer-state-reasons",
                            ],
                        )
                    except Exception:
                        details[name] = {}
            except Exception as exc:
                raise CupsUnavailable(f"Falha ao consultar impressoras no CUPS: {exc}") from exc
        result = []
        for name, attrs in sorted(rows.items(), key=lambda item: item[0].casefold()):
            attrs = {**attrs, **details.get(name, {})}
            state = int(attrs.get("printer-state") or 0)
            reasons = attrs.get("printer-state-reasons") or []
            if isinstance(reasons, str):
                reasons = [reasons]
            result.append({
                "name": name,
                "info": attrs.get("printer-info") or name,
                "model": attrs.get("printer-make-and-model") or "",
                "location": attrs.get("printer-location") or "",
                "state": PRINTER_STATES.get(state, "DESCONHECIDA"),
                "stateCode": state,
                "message": attrs.get("printer-state-message") or "",
                "reasons": reasons,
                "accepting": bool(attrs.get("printer-is-accepting-jobs", True)),
                "secureDefault": str(attrs.get("job-hold-until-default") or "").lower() in {"hold", "indefinite"},
                "holdingNewJobs": "hold-new-jobs" in reasons,
            })
        return result

    def enforce_secure_queues(self):
        """Set and verify native secure-release defaults on every server queue.

        CUPS applies this policy to portal uploads and clients that inherit the
        queue default. Like every native CUPS default, a client administrator
        can explicitly override it with ``job-hold-until=no-hold``.
        """
        with self._lock:
            conn = self._connection()
            try:
                names = sorted(conn.getPrinters(), key=str.casefold)
            except Exception as exc:
                raise CupsUnavailable(f"Falha ao consultar filas para retencao segura: {exc}") from exc
            results = []
            for name in names:
                try:
                    attrs = conn.getPrinterAttributes(
                        name,
                        requested_attributes=["job-hold-until-default", "printer-state-reasons"],
                    )
                    if str(attrs.get("job-hold-until-default") or "").lower() not in {"hold", "indefinite"}:
                        conn.addPrinterOptionDefault(name, "job-hold-until", "indefinite")
                    reasons = attrs.get("printer-state-reasons") or []
                    if isinstance(reasons, str):
                        reasons = [reasons]
                    if "hold-new-jobs" not in reasons:
                        user = str(os.environ.get("CUPS_USER") or "root").strip() or "root"
                        completed = subprocess.run(
                            ["cupsdisable", "--hold", "-U", user, name],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=20,
                            env=os.environ.copy(),
                        )
                        if completed.returncode:
                            message = (completed.stderr or completed.stdout or "falha desconhecida").strip()
                            raise RuntimeError(message)
                    verified = conn.getPrinterAttributes(
                        name,
                        requested_attributes=["job-hold-until-default", "printer-state-reasons"],
                    )
                    verified_reasons = verified.get("printer-state-reasons") or []
                    if isinstance(verified_reasons, str):
                        verified_reasons = [verified_reasons]
                    verified_default = str(verified.get("job-hold-until-default") or "").lower()
                    if verified_default not in {"hold", "indefinite"} or "hold-new-jobs" not in verified_reasons:
                        raise RuntimeError("CUPS nao confirmou a retencao padrao da fila")
                    results.append({"name": name, "secure": True})
                except Exception as exc:
                    results.append({"name": name, "secure": False, "error": str(exc)})
            return results

    def jobs(self):
        attrs = [
            "job-id", "job-name", "job-originating-user-name", "job-printer-uri",
            "job-state", "job-state-reasons", "job-k-octets", "copies",
            "job-impressions", "job-impressions-completed", "job-media-sheets-completed",
            "time-at-creation", "time-at-processing", "time-at-completed",
        ]
        with self._lock:
            conn = self._connection()
            try:
                rows = conn.getJobs(which_jobs="all", my_jobs=False, requested_attributes=attrs)
            except Exception as exc:
                raise CupsUnavailable(f"Falha ao consultar trabalhos no CUPS: {exc}") from exc
        job_users = self._lpstat_job_users() if any(
            not str(item.get("job-originating-user-name") or "").strip()
            for item in rows.values()
        ) else {}
        result = []
        for job_id, item in rows.items():
            state_code = int(item.get("job-state") or 0)
            printer_uri = str(item.get("job-printer-uri") or "")
            completed = _positive_int(item.get("job-impressions-completed"))
            if completed is None:
                completed = _positive_int(item.get("job-media-sheets-completed"))
            result.append({
                "cupsJobId": int(job_id),
                "printer": printer_uri.rstrip("/").rsplit("/", 1)[-1],
                "cupsUser": str(item.get("job-originating-user-name") or job_users.get(int(job_id)) or ""),
                "document": str(item.get("job-name") or f"Trabalho {job_id}"),
                "state": STATE_NAMES.get(state_code, "DESCONHECIDO"),
                "held": state_code == 4,
                "requestedPages": _positive_int(item.get("job-impressions")),
                "printedPages": completed,
                "copies": max(1, _positive_int(item.get("copies")) or 1),
                "sizeKb": _positive_int(item.get("job-k-octets")),
                "submittedAt": _utc_datetime(item.get("time-at-creation")),
                "processedAt": _utc_datetime(item.get("time-at-processing")),
                "completedAt": _utc_datetime(item.get("time-at-completed")),
                "details": {"stateReasons": item.get("job-state-reasons") or []},
            })
        return result

    @staticmethod
    def _lpstat_job_users():
        """Recover job owners hidden by CUPS IPP privacy defaults."""
        environment = os.environ.copy()
        environment["LC_ALL"] = "C"
        try:
            completed = subprocess.run(
                ["lpstat", "-W", "all", "-o"],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
                env=environment,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        if completed.returncode:
            return {}
        users = {}
        pattern = re.compile(r"^\S+-(\d+)\s+(\S+)\s+\d+\s+")
        for line in completed.stdout.splitlines():
            match = pattern.match(line)
            if match:
                users[int(match.group(1))] = match.group(2)
        return users

    def submit_held(self, printer, path, title, copies=1):
        options = {"job-hold-until": "indefinite", "copies": str(max(1, int(copies)))}
        with self._lock:
            conn = self._connection()
            try:
                return int(conn.printFile(printer, str(path), title, options))
            except Exception as exc:
                raise CupsUnavailable(f"CUPS recusou o envio para {printer}: {exc}") from exc

    def release(self, job_id):
        with self._lock:
            try:
                self._connection().setJobHoldUntil(int(job_id), "resume")
            except Exception as exc:
                raise CupsUnavailable(f"Nao foi possivel liberar o trabalho {job_id}: {exc}") from exc

    def cancel(self, job_id):
        with self._lock:
            try:
                self._connection().cancelJob(int(job_id), purge_job=False)
            except Exception as exc:
                raise CupsUnavailable(f"Nao foi possivel cancelar o trabalho {job_id}: {exc}") from exc

    def printer_action(self, printer, action):
        methods = {
            "pause": "disablePrinter",
            "resume": "enablePrinter",
            "reject": "rejectJobs",
            "accept": "acceptJobs",
        }
        method = methods.get(action)
        if not method:
            raise ValueError("acao de impressora invalida")
        with self._lock:
            try:
                getattr(self._connection(), method)(printer)
            except Exception as exc:
                raise CupsUnavailable(f"Nao foi possivel executar {action} em {printer}: {exc}") from exc


def _guard_once(service):
    results = service.enforce_secure_queues()
    print(json.dumps({"event": "cups-secure-queues", "queues": results}, ensure_ascii=False), flush=True)
    return not any(not item["secure"] for item in results)


def main():
    parser = argparse.ArgumentParser(description="Mantem todas as filas CUPS em liberacao segura.")
    parser.add_argument("--watch", action="store_true", help="reaplica a politica continuamente")
    args = parser.parse_args()
    service = CupsService()
    if not args.watch:
        raise SystemExit(0 if _guard_once(service) else 1)
    interval = max(2, int(os.environ.get("CUPS_GUARD_INTERVAL_SECONDS") or 10))
    while True:
        try:
            _guard_once(service)
        except Exception as exc:
            print(json.dumps({"event": "cups-secure-queues", "error": str(exc)}, ensure_ascii=False), flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
