"""Small, testable adapter around pycups.

The portal owns authentication and audit data. CUPS remains the spooler and is
never reconfigured automatically by this adapter.
"""
from __future__ import annotations

import datetime as dt
import os
import threading

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
            except Exception as exc:
                raise CupsUnavailable(f"Falha ao consultar impressoras no CUPS: {exc}") from exc
        result = []
        for name, attrs in sorted(rows.items(), key=lambda item: item[0].casefold()):
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
            })
        return result

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
                "cupsUser": str(item.get("job-originating-user-name") or ""),
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