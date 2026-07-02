from __future__ import annotations

import json
import gzip
import mimetypes
import os
import re
import secrets
import shutil
import socket
import subprocess
import tarfile
import unicodedata
from collections import defaultdict
from contextlib import nullcontext
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

from pydicom import dcmread
from pydicom.dataset import FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage
from werkzeug.security import check_password_hash, generate_password_hash

from .camera_runtime import CameraRuntime
from .config import Settings
from .db import Database
from .pacs_catalog import list_studies as list_pacs_catalog_studies
from .pacs_catalog import study_detail as pacs_study_detail
from .pacs_catalog import store_instance
from .report_pdf import build_text_pdf
from .utils import (
    build_accession_number,
    build_uid,
    clean_digits,
    format_dicom_date,
    format_dicom_time,
    invoice_number_for_exam,
    invoice_number_for_order,
    normalize_json,
    parse_bool,
    parse_date,
    parse_datetime,
)


WORKFLOW_STAGES = [
    "draft",
    "scheduled",
    "arrived",
    "started",
    "executed",
    "reporting",
    "finalized",
    "cancelled",
    "removed",
]
WORKFLOW_LABELS = {
    "draft": "Cadastro",
    "scheduled": "Na worklist",
    "arrived": "Chegou",
    "started": "Em execucao",
    "executed": "Executado",
    "reporting": "Laudando",
    "finalized": "Finalizado",
    "cancelled": "Cancelado",
    "removed": "Removido",
}
WORKFLOW_ALIASES = {
    "reception": "draft",
    "pending": "draft",
    "waiting": "arrived",
    "worklist": "scheduled",
    "published": "scheduled",
    "acquisition": "started",
    "completed": "executed",
    "delivery": "finalized",
    "reported": "finalized",
    "discontinued": "cancelled",
    "suspended": "cancelled",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}
WORKFLOW_RANK = {stage: index for index, stage in enumerate(WORKFLOW_STAGES)}
WORKLIST_OPEN_STATUSES = {"scheduled", "arrived", "started"}
WORKLIST_ACTIVE_STATUSES = WORKLIST_OPEN_STATUSES | {"executed"}
WORKLIST_TERMINAL_STATUSES = {"cancelled", "removed"}
MANUAL_TRANSITION_STAGES = {"draft", "scheduled", "arrived", "started", "executed", "cancelled", "removed"}
WORKLIST_PROGRESS = ["draft", "scheduled", "arrived", "started", "executed"]
WORKLIST_PROGRESS_RANK = {stage: index for index, stage in enumerate(WORKLIST_PROGRESS)}
FINALIZED_HISTORY_HOURS = 24
CHAT_DEPARTMENTS = (
    "Recepcao",
    "Sala de Raiox",
    "Sala de Ultrassom",
)
ALLOWED_MODALITIES = ("DR", "US")
DEFAULT_PRICING_CONVENIOS = (
    ("PARTICULAR", "Particular"),
)
REPORT_CATALOG = (
    {
        "key": "financeiro",
        "label": "Resumo financeiro",
        "description": "Mostra pagos, em aberto e formas de pagamento por periodo.",
    },
    {
        "key": "convenio",
        "label": "Por convenio",
        "description": "Agrupa quantidade e valor dos exames por convenio.",
    },
    {
        "key": "paciente",
        "label": "Por paciente",
        "description": "Agrupa quantidade e valor dos exames por paciente.",
    },
    {
        "key": "comissao_tecnico",
        "label": "Comissao do tecnico",
        "description": "Calcula a comissao fixa por exame do tecnico e detalha cada exame.",
    },
)
PAYMENT_METHOD_LABELS = {
    "dinheiro": "Dinheiro",
    "pix": "Pix",
    "cartao": "Cartao",
    "cheque": "Cheque",
}
INVOICE_STATUS_LABELS = {
    "paid": "Pago",
    "open": "Em aberto",
    "pending": "Pendente",
    "ready": "Pronto para faturar",
    "cancelled": "Cancelado",
    "canceled": "Cancelado",
}
PACS_WORKLIST_TO_STAGE = {
    "SCHEDULED": "scheduled",
    "ARRIVED": "arrived",
    "READY": "arrived",
    "STARTED": "started",
    "IN PROGRESS": "started",
    "COMPLETED": "executed",
    "DISCONTINUED": "cancelled",
    "SUSPENDED": "cancelled",
    "CANCELLED": "cancelled",
    "CANCELED": "cancelled",
}
STAGE_TO_PACS_WORKLIST = {
    "scheduled": "SCHEDULED",
    "arrived": "ARRIVED",
    "started": "STARTED",
    "executed": "COMPLETED",
    "cancelled": "DISCONTINUED",
}
CALL_STATUS = {"waiting", "called", "in_service", "done"}
SHARE_PASSWORD_WORDS = (
    "manga",
    "carro",
    "brisa",
    "cafe",
    "lago",
    "sol",
    "atlas",
    "trilha",
    "nuvem",
    "cacto",
    "ponte",
    "vento",
)
BACKUP_TABLES = (
    ("raiox", "patient"),
    ("raiox", "procedure_catalog"),
    ("raiox", "convenio"),
    ("raiox", "convenio_price"),
    ("raiox", "exam"),
    ("raiox", "medical_report"),
    ("raiox", "exam_attachment"),
    ("raiox", "invoice"),
    ("raiox", "operator"),
    ("raiox", "chat_message"),
    ("raiox", "camera"),
    ("raiox", "call_ticket"),
    ("raiox", "call_log"),
    ("raiox", "sync_log"),
    ("raiox", "share_access"),
    ("raiox", "system_settings"),
    ("public", "worklist"),
    ("public", "study"),
    ("public", "series"),
    ("public", "objects"),
    ("public", "reports"),
)


class ClinicService:
    def __init__(self, database: Database, settings: Settings, camera_runtime: CameraRuntime | None = None):
        self.database = database
        self.settings = settings
        self.camera_runtime = camera_runtime

    def _worklist_requested_procedure_id(self, exam: dict[str, Any]) -> str:
        value = (exam.get("requested_procedure_id") or exam.get("procedure_code") or "").strip()
        if value:
            return value[:16]
        return f"RXP{int(exam['id']):08d}"[:16]

    def normalize_public_worklist_device_scope(self) -> int:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update public.worklist wl
                    set scheduledstation = left(coalesce(nullif(btrim(e.station_aet), ''), %s), 16),
                        requestedprocedureid = left(coalesce(nullif(btrim(e.requested_procedure_id), ''), ('RXP' || lpad(e.id::text, 8, '0'))), 16)
                    from raiox.exam e
                    where wl.accessionnumber = e.accession_number
                      and (
                          coalesce(wl.scheduledstation, '') <> left(coalesce(nullif(btrim(e.station_aet), ''), %s), 16)
                          or coalesce(wl.requestedprocedureid, '') <> left(coalesce(nullif(btrim(e.requested_procedure_id), ''), ('RXP' || lpad(e.id::text, 8, '0'))), 16)
                      )
                    """,
                    (self.settings.pacs_station_aet, self.settings.pacs_station_aet),
                )
                updated = cur.rowcount or 0
            conn.commit()
        return updated

    def ensure_chat_departments(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                for index, department_name in enumerate(CHAT_DEPARTMENTS, start=1):
                    cur.execute(
                        """
                        select *
                        from raiox.operator
                        where name = %s
                        limit 1
                        """,
                        (department_name,),
                    )
                    row = cur.fetchone()
                    if row:
                        cur.execute(
                            """
                            update raiox.operator
                            set role = 'department',
                                sector = %s,
                                extension = null,
                                sip_username = null,
                                sip_password = null,
                                active = true,
                                updated_at = now()
                            where id = %s
                            returning *
                            """,
                            (department_name, row["id"]),
                        )
                        row = cur.fetchone()
                    else:
                        cur.execute(
                            """
                            insert into raiox.operator (
                                name, role, sector, extension, sip_username, sip_password, active
                            ) values (
                                %s, 'department', %s, null, null, null, true
                            )
                            returning *
                            """,
                            (department_name, department_name),
                        )
                        row = cur.fetchone()
                    if row:
                        row["sort_order"] = index
                        records.append(row)
            conn.commit()
        return records

    def list_chat_departments(self, sender_operator_id: int | None = None) -> list[dict[str, Any]]:
        self.ensure_chat_departments()
        unread_join = """
            left join (
                select sender_operator_id, count(*) as total
                from raiox.chat_message
                where recipient_operator_id = %s and read_at is null
                group by sender_operator_id
            ) unread on unread.sender_operator_id = o.id
        """
        params: list[Any] = [sender_operator_id or 0]
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    select
                        o.*,
                        coalesce(unread.total, 0) as pending_messages
                    from raiox.operator o
                    {unread_join}
                    where o.role = 'department' and o.name in (%s, %s, %s)
                    order by case o.name
                        when %s then 1
                        when %s then 2
                        when %s then 3
                        else 99
                    end, o.name asc
                    """,
                    [*params, *CHAT_DEPARTMENTS, *CHAT_DEPARTMENTS],
                )
                rows = list(cur.fetchall())
        return rows

    def _normalize_stage(self, value: str | None, default: str = "draft") -> str:
        stage = WORKFLOW_ALIASES.get((value or "").strip().lower(), (value or "").strip().lower())
        return stage if stage in WORKFLOW_RANK else default

    def _normalize_worklist_status(self, value: str | None, default: str = "draft") -> str:
        return self._normalize_stage(value, default)

    def _promote_stage(self, current: str | None, target: str | None) -> str:
        current_stage = self._normalize_stage(current)
        target_stage = self._normalize_stage(target, current_stage)
        if WORKFLOW_RANK[target_stage] > WORKFLOW_RANK[current_stage]:
            return target_stage
        return current_stage

    def _stage_from_pacs_worklist(self, value: str | None) -> str:
        key = (value or "").strip().upper()
        return PACS_WORKLIST_TO_STAGE.get(key, "")

    def _worklist_status_from_stage(self, stage: str | None, current_status: str = "draft") -> str:
        normalized_stage = self._normalize_stage(stage)
        normalized_current = self._normalize_worklist_status(current_status)
        if normalized_stage in {"draft", "scheduled", "arrived", "started", "executed", "cancelled", "removed"}:
            return normalized_stage
        if normalized_stage in {"reporting", "finalized"}:
            return "executed"
        return normalized_current

    def _exam_status_from_stage(self, stage: str | None) -> str:
        normalized_stage = self._normalize_stage(stage)
        if normalized_stage == "finalized":
            return "reported"
        if normalized_stage == "reporting":
            return "reporting"
        if normalized_stage == "executed":
            return "executed"
        if normalized_stage == "started":
            return "started"
        if normalized_stage == "cancelled":
            return "cancelled"
        if normalized_stage == "removed":
            return "removed"
        return "scheduled"

    def _derive_worklist_status(self, row: dict[str, Any]) -> str:
        current_status = self._normalize_worklist_status(row.get("worklist_status"))
        pacs_status = self._stage_from_pacs_worklist(row.get("pacs_worklist_status"))
        if current_status in WORKLIST_TERMINAL_STATUSES:
            return current_status
        if pacs_status == "cancelled":
            return "cancelled"
        if row.get("live_study_instance_uid"):
            return "executed"
        if current_status == "executed":
            return "executed"
        if pacs_status and WORKLIST_PROGRESS_RANK.get(pacs_status, -1) > WORKLIST_PROGRESS_RANK.get(current_status, -1):
            return pacs_status
        return current_status

    def _recommended_stage_from_row(self, row: dict[str, Any]) -> str:
        worklist_status = self._derive_worklist_status(row)
        current_stage = self._normalize_stage(row.get("workflow_stage"))
        if worklist_status == "removed":
            return self._promote_stage(current_stage, "removed")
        if worklist_status == "cancelled":
            return self._promote_stage(current_stage, "cancelled")
        if row.get("report_final") or row.get("live_status") == "reported":
            return self._promote_stage(current_stage, "finalized")
        if row.get("report_preliminary") or row.get("report_assigned"):
            return self._promote_stage(current_stage, "reporting")
        if worklist_status in WORKFLOW_RANK:
            return self._promote_stage(current_stage, worklist_status)
        return current_stage if current_stage in WORKFLOW_RANK else "draft"

    def _manual_transition_lock(self, row: dict[str, Any]) -> tuple[bool, str]:
        stage = self._normalize_stage(row.get("workflow_stage"))
        worklist_status = self._derive_worklist_status(row)
        if stage == "removed" or worklist_status == "removed":
            return True, "Exame removido da worklist pela aplicacao."
        if stage == "cancelled" or worklist_status == "cancelled":
            return True, "Exame cancelado na worklist/aparelho."
        if row.get("report_final") or stage == "finalized":
            return True, "Exame finalizado e bloqueado para movimentacao manual."
        if stage in {"reporting", "executed"} or worklist_status == "executed" or row.get("live_study_instance_uid"):
            return True, "Exame ja executado pelo aparelho/PACS."
        return False, ""

    def _complete_call_ticket_if_needed(self, cur: Any, exam_id: int, stage: str | None) -> None:
        normalized_stage = self._normalize_stage(stage)
        if normalized_stage not in {"executed", "reporting", "finalized", "cancelled", "removed"}:
            return
        cur.execute(
            """
            update raiox.call_ticket
            set status = 'done',
                completed_at = coalesce(completed_at, now()),
                updated_at = now()
            where exam_id = %s and status <> 'done'
            """,
            (exam_id,),
        )

    def _insert_sync_log(
        self,
        cur: Any,
        exam_id: int,
        target: str,
        event_type: str,
        success: bool,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        cur.execute(
            """
            insert into raiox.sync_log (exam_id, target, event_type, success, message, payload)
            values (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            (exam_id, target, event_type, success, message, json.dumps(payload or {})),
        )

    def _panel_default(self) -> dict[str, Any]:
        return {
            "title": self.settings.panel_title,
            "subtitle": self.settings.panel_subtitle,
            "video_url": self.settings.panel_video_url,
            "destinations": self.settings.panel_destinations,
            "auto_announce": True,
        }

    def _sip_default(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.sip_enabled,
            "mode_active": self.settings.sip_mode_active,
            "freepbx": {
                "ws_url": self.settings.sip_ws_url,
                "domain": self.settings.sip_domain,
                "registrar_server": self.settings.sip_registrar_server,
                "outbound_proxy": self.settings.sip_outbound_proxy,
                "prefix": self.settings.sip_prefix,
                "caller_id_template": self.settings.sip_caller_id_template,
                "auto_register": self.settings.sip_auto_register,
            },
        }

    def _integration_default(self) -> dict[str, Any]:
        return {
            "pacs": {
                "mode": "local",
                "host": "",
                "port": self.settings.dicom_port,
                "ae_title": self.settings.pacs_aet,
            },
            "worklist": {
                "mode": "local",
                "host": "",
                "port": self.settings.worklist_port,
                "ae_title": self.settings.worklist_ae_title,
            },
            "web": {
                "public_url": self.settings.pacs_web_url,
            },
        }

    def _pricing_default(self) -> dict[str, Any]:
        return {
            "convenios": [
                {
                    "code": code,
                    "name": name,
                    "prices": {"1": 0, "2": 0, "3": 0},
                    "commission_amount": 10 if code == "PARTICULAR" else 6,
                }
                for code, name in DEFAULT_PRICING_CONVENIOS
            ]
        }

    def _default_commission_amount(self, convenio_code: str | None) -> Decimal:
        return Decimal("10") if self._normalize_convenio_code(convenio_code) == "PARTICULAR" else Decimal("6")

    def _commission_amount_source(self, item: dict[str, Any]) -> Any:
        return item.get("commission_amount", item.get("commission_rate"))

    def _normalize_commission_amount(self, value: Any, convenio_code: str | None) -> Decimal:
        if value in (None, ""):
            return self._default_commission_amount(convenio_code)
        try:
            amount = Decimal(str(value)).quantize(Decimal("0.01"))
        except Exception:
            return self._default_commission_amount(convenio_code)
        if amount < 0:
            return Decimal("0")
        return amount

    def _normalize_modality(self, value: str | None, default: str = "DR") -> str:
        normalized = self._normalized_letters(value).upper()
        raw = (value or "").strip().upper()
        if raw in ALLOWED_MODALITIES:
            return raw
        if normalized in {"RX", "CR", "DX", "DR", "RAIOX", "RADIOX", "XRAY"}:
            return "DR"
        if normalized in {"US", "ULTRASSOM", "ULTRASSONOGRAFIA", "ECO"}:
            return "US"
        return default if default in ALLOWED_MODALITIES else "DR"

    def _dicom_modality(self, value: str | None) -> str:
        return "US" if self._normalize_modality(value) == "US" else "DR"

    def _normalize_convenio_code(self, value: str | None) -> str:
        raw = (value or "").strip().upper()
        return raw or "PARTICULAR"

    def _normalize_pricing_config(self, value: Any) -> dict[str, Any]:
        source = value if isinstance(value, dict) else {}
        convenios_by_code: dict[str, dict[str, Any]] = {}
        for item in source.get("convenios") or []:
            if not isinstance(item, dict):
                continue
            code = self._normalize_convenio_code(item.get("code"))
            if not code:
                continue
            fallback_name = code.replace("_", " ").title()
            name = (item.get("name") or fallback_name).strip()[:160] or fallback_name
            prices_raw = item.get("prices") or {}
            prices: dict[str, Any] = {}
            for incidence in ("1", "2", "3"):
                try:
                    price_value = Decimal(str((prices_raw or {}).get(incidence) or 0))
                except Exception:
                    price_value = Decimal("0")
                prices[incidence] = price_value
            convenios_by_code[code] = {
                "code": code,
                "name": name,
                "prices": prices,
                "commission_amount": self._normalize_commission_amount(self._commission_amount_source(item), code),
            }

        convenios: list[dict[str, Any]] = list(convenios_by_code.values())
        existing_codes = {item["code"] for item in convenios}
        for code, name in DEFAULT_PRICING_CONVENIOS:
            if code not in existing_codes:
                convenios.append({
                    "code": code,
                    "name": name,
                    "prices": {"1": Decimal("0"), "2": Decimal("0"), "3": Decimal("0")},
                    "commission_amount": self._default_commission_amount(code),
                })

        convenios.sort(key=lambda item: (item["code"] != "PARTICULAR", item["name"].lower()))
        return {"convenios": convenios}

    def get_pricing_config(self) -> dict[str, Any]:
        table_config = self._pricing_config_from_tables()
        if not table_config:
            cached_config = self._setting_json("pricing_config", self._pricing_default())
            self._sync_pricing_config_tables(self._normalize_pricing_config(cached_config)["convenios"])
            table_config = self._pricing_config_from_tables()
        config = table_config or self._pricing_default()
        normalized = self._normalize_pricing_config(config)
        for convenio in normalized["convenios"]:
            for incidence, price in list(convenio["prices"].items()):
                convenio["prices"][incidence] = float(price)
            commission_amount = self._normalize_commission_amount(self._commission_amount_source(convenio), convenio.get("code"))
            convenio["commission_amount"] = float(commission_amount)
            convenio["commission_rate"] = float(commission_amount)
        return normalized

    def _pricing_config_from_tables(self) -> dict[str, Any] | None:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select code, name
                    from raiox.convenio
                    where active = true
                    order by code <> 'PARTICULAR', name asc
                    """
                )
                rows = list(cur.fetchall())
        if not rows:
            return None

        stored_config = self._normalize_pricing_config(self._setting_json("pricing_config", self._pricing_default()))
        stored_by_code = {item["code"]: item for item in stored_config.get("convenios") or []}
        return {
            "convenios": [
                {
                    "code": self._normalize_convenio_code(row.get("code")),
                    "name": row.get("name") or self._normalize_convenio_code(row.get("code")).title(),
                    "prices": stored_by_code.get(self._normalize_convenio_code(row.get("code")), {}).get(
                        "prices",
                        {"1": Decimal("0"), "2": Decimal("0"), "3": Decimal("0")},
                    ),
                    "commission_amount": stored_by_code.get(
                        self._normalize_convenio_code(row.get("code")),
                        {},
                    ).get(
                        "commission_amount",
                        stored_by_code.get(
                            self._normalize_convenio_code(row.get("code")),
                            {},
                        ).get("commission_rate", self._default_commission_amount(row.get("code"))),
                    ),
                }
                for row in rows
            ]
        }

    def _sync_pricing_config_tables(self, convenios: list[dict[str, Any]]) -> None:
        active_codes = [self._normalize_convenio_code(item.get("code")) for item in convenios if item.get("code")]
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                for item in convenios:
                    code = self._normalize_convenio_code(item.get("code"))
                    if not code:
                        continue
                    fallback_name = code.replace("_", " ").title()
                    cur.execute(
                        """
                        insert into raiox.convenio (code, name, active, updated_at)
                        values (%s, %s, true, now())
                        on conflict (code) do update
                        set name = excluded.name,
                            active = true,
                            updated_at = now()
                        """,
                        (code, (item.get("name") or fallback_name).strip()[:160] or fallback_name),
                    )
                if active_codes:
                    cur.execute(
                        """
                        update raiox.convenio
                        set active = false,
                            updated_at = now()
                        where code <> 'PARTICULAR'
                          and code <> all(%s)
                        """,
                        (active_codes,),
                    )
            conn.commit()

    def update_pricing_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        convenios_payload = payload.get("convenios") or []
        if not isinstance(convenios_payload, list):
            raise ValueError("Formato de convênios invalido.")

        convenios: list[dict[str, Any]] = []
        for item in convenios_payload:
            if not isinstance(item, dict):
                continue
            code = self._normalize_convenio_code(item.get("code"))
            if not code:
                continue
            fallback_name = code.replace("_", " ").title()
            name = (item.get("name") or fallback_name).strip()[:160] or fallback_name
            prices_payload = item.get("prices") or {}
            prices: dict[str, str] = {}
            for incidence in ("1", "2", "3"):
                try:
                    price = Decimal(str((prices_payload or {}).get(incidence) or 0)).quantize(Decimal("0.01"))
                except Exception as exc:
                    raise ValueError(f"Preco invalido para {code} incidencias {incidence}.") from exc
                prices[incidence] = str(price)
            commission_amount_raw = item.get("commission_amount", item.get("commission_rate"))
            if commission_amount_raw in (None, ""):
                commission_amount_raw = self._default_commission_amount(code)
            try:
                commission_amount = Decimal(str(commission_amount_raw)).quantize(Decimal("0.01"))
            except Exception as exc:
                raise ValueError(f"Comissao invalida para {code}.") from exc
            if commission_amount < 0:
                raise ValueError(f"Comissao invalida para {code}. Use um valor maior ou igual a zero.")
            convenios.append({
                "code": code,
                "name": name,
                "prices": prices,
                "commission_amount": str(commission_amount),
            })

        if not any(self._normalize_convenio_code(item.get("code")) == "PARTICULAR" for item in convenios):
            convenios.insert(0, {
                "code": "PARTICULAR",
                "name": "Particular",
                "prices": {"1": "0.00", "2": "0.00", "3": "0.00"},
                "commission_amount": "10.00",
            })

        normalized = self._normalize_pricing_config({"convenios": convenios})
        stored = {
            "convenios": [
                {
                    "code": item["code"],
                    "name": item["name"],
                    "prices": {incidence: str(price) for incidence, price in item["prices"].items()},
                    "commission_amount": str(self._normalize_commission_amount(self._commission_amount_source(item), item.get("code"))),
                }
                for item in normalized["convenios"]
            ]
        }
        self._sync_pricing_config_tables(stored["convenios"])
        return self._save_setting_json("pricing_config", stored)

    def _resolve_exam_price(
        self,
        procedure: dict[str, Any],
        convenio_code: str,
        incidences_count: int,
        manual_price: Decimal | None = None,
    ) -> Decimal:
        if manual_price is not None and manual_price > 0:
            return manual_price

        convenio = self._normalize_convenio_code(convenio_code)
        procedure_id = int(procedure.get("id") or 0)
        if procedure_id:
            table_price = self._pricing_price_from_tables(convenio, procedure_id, incidences_count)
            if table_price is not None:
                return table_price

            overrides = self.get_pricing_overrides()
            for item in overrides.get("items") or []:
                if self._normalize_convenio_code(item.get("convenio_code")) != convenio:
                    continue
                if int(item.get("procedure_id") or 0) != procedure_id:
                    continue
                prices = item.get("prices") or {}
                price_value = prices.get(str(max(1, min(int(incidences_count or 1), 3))))
                if price_value is not None:
                    return Decimal(str(price_value))
                break

        config = self.get_pricing_config()
        for item in config.get("convenios") or []:
            if self._normalize_convenio_code(item.get("code")) != convenio:
                continue
            prices = item.get("prices") or {}
            price_value = prices.get(str(max(1, min(int(incidences_count or 1), 3))))
            if price_value not in (None, "", 0, 0.0):
                return Decimal(str(price_value))
            break

        if convenio == "PARTICULAR":
            try:
                return Decimal(str(procedure.get("default_price") or 0))
            except Exception:
                return Decimal("0")

        return Decimal("0")

    def _pricing_price_from_tables(self, convenio_code: str, procedure_id: int, incidences_count: int) -> Decimal | None:
        incidence = max(1, min(int(incidences_count or 1), 3))
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select cp.price
                    from raiox.convenio_price cp
                    join raiox.convenio c on c.id = cp.convenio_id
                    where c.code = %s
                      and c.active = true
                      and cp.procedure_id = %s
                      and cp.incidences_count = %s
                      and cp.active = true
                    """,
                    (convenio_code, procedure_id, incidence),
                )
                row = cur.fetchone()
        if not row:
            return None
        try:
            return Decimal(str(row.get("price") or 0))
        except Exception:
            return Decimal("0")

    def _is_local_host(self, host: str | None) -> bool:
        normalized = (host or "").strip().lower()
        return normalized in {"", "localhost", "127.0.0.1", "::1", "0.0.0.0"}

    def _socket_status(self, host: str, port: int | None, timeout_seconds: float = 1.2) -> dict[str, Any]:
        if not host or not port:
            return {"ok": False, "message": "Endereco incompleto.", "latency_ms": None}
        started = datetime.now()
        try:
            with socket.create_connection((host, int(port)), timeout=timeout_seconds):
                latency = round((datetime.now() - started).total_seconds() * 1000, 1)
                return {"ok": True, "message": "Conexao estabelecida.", "latency_ms": latency}
        except Exception as exc:
            return {"ok": False, "message": str(exc), "latency_ms": None}

    def _local_listener_host(self, host: str | None) -> str:
        normalized = (host or "").strip()
        return "127.0.0.1" if self._is_local_host(normalized) else normalized

    def _normalize_integration_endpoint(
        self,
        payload: dict[str, Any] | None,
        *,
        default_mode: str,
        default_host: str,
        default_port: int,
        default_ae_title: str,
    ) -> dict[str, Any]:
        values = payload or {}
        mode = (values.get("mode") or default_mode or "local").strip().lower()
        if mode not in {"local", "external"}:
            mode = "local"
        host = (values.get("host") or "").strip()
        if mode == "local":
            host = ""
        try:
            port = int(values.get("port") or default_port or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("Porta invalida para a integracao.") from exc
        ae_title = (values.get("ae_title") or default_ae_title or "").strip()[:32]
        return {
            "mode": mode,
            "host": host,
            "port": port,
            "ae_title": ae_title or default_ae_title,
            "effective_host": host if mode == "external" else default_host,
            "effective_port": port if mode == "external" else default_port,
            "effective_ae_title": ae_title or default_ae_title,
        }

    def _database_runtime_info(self) -> dict[str, Any]:
        host = self.settings.pg_host
        return {
            "mode": "external" if not self._is_local_host(host) else "local",
            "host": host,
            "port": self.settings.pg_port,
            "database": self.settings.pg_database,
            "user": self.settings.pg_user,
            "sslmode": self.settings.pg_sslmode or "",
            "managed_via": "DATABASE_URL" if self.settings.database_url else "PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE",
        }

    def get_integration_config(self) -> dict[str, Any]:
        payload = self._setting_json("integration_config", self._integration_default())
        pacs = self._normalize_integration_endpoint(
            payload.get("pacs") if isinstance(payload, dict) else {},
            default_mode="local",
            default_host=self.settings.dicom_status_host or self._local_listener_host(self.settings.dicom_bind_host),
            default_port=self.settings.dicom_port,
            default_ae_title=self.settings.pacs_aet,
        )
        worklist = self._normalize_integration_endpoint(
            payload.get("worklist") if isinstance(payload, dict) else {},
            default_mode="local",
            default_host=self.settings.worklist_status_host or self._local_listener_host(self.settings.worklist_bind_host),
            default_port=self.settings.worklist_port,
            default_ae_title=self.settings.worklist_ae_title,
        )
        web_payload = payload.get("web") if isinstance(payload, dict) else {}
        web_public_url = (
            str((web_payload or {}).get("public_url") or self.settings.pacs_web_url).strip()
            or self.settings.pacs_web_url
        )
        return {
            "pacs": pacs,
            "worklist": worklist,
            "web": {"public_url": web_public_url},
            "database": self._database_runtime_info(),
        }

    def update_integration_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self.get_integration_config()
        pacs_payload = payload.get("pacs") or {}
        worklist_payload = payload.get("worklist") or {}
        web_payload = payload.get("web") or {}

        pacs = self._normalize_integration_endpoint(
            {**config["pacs"], **pacs_payload},
            default_mode="local",
            default_host=self.settings.dicom_status_host or self._local_listener_host(self.settings.dicom_bind_host),
            default_port=self.settings.dicom_port,
            default_ae_title=self.settings.pacs_aet,
        )
        worklist = self._normalize_integration_endpoint(
            {**config["worklist"], **worklist_payload},
            default_mode="local",
            default_host=self.settings.worklist_status_host or self._local_listener_host(self.settings.worklist_bind_host),
            default_port=self.settings.worklist_port,
            default_ae_title=self.settings.worklist_ae_title,
        )
        if pacs["mode"] == "external" and not pacs["host"]:
            raise ValueError("Informe o IP/host do PACS externo.")
        if worklist["mode"] == "external" and not worklist["host"]:
            raise ValueError("Informe o IP/host da worklist externa.")

        public_url = str(web_payload.get("public_url") or config["web"].get("public_url") or "").strip()
        stored = {
            "pacs": {
                "mode": pacs["mode"],
                "host": pacs["host"],
                "port": pacs["port"],
                "ae_title": pacs["effective_ae_title"],
            },
            "worklist": {
                "mode": worklist["mode"],
                "host": worklist["host"],
                "port": worklist["port"],
                "ae_title": worklist["effective_ae_title"],
            },
            "web": {
                "public_url": public_url,
            },
        }
        self._save_setting_json("integration_config", stored)
        return self.get_integration_config()

    def integration_status(self) -> dict[str, Any]:
        config = self.get_integration_config()
        pacs = config["pacs"]
        worklist = config["worklist"]

        database_status: dict[str, Any]
        try:
            ping = self.database.ping()
            database_status = {
                **config["database"],
                "ok": True,
                "message": "Banco online.",
                "version": ping.get("version"),
            }
        except Exception as exc:
            database_status = {
                **config["database"],
                "ok": False,
                "message": str(exc),
                "version": "",
            }

        pacs_probe = self._socket_status(str(pacs["effective_host"]), int(pacs["effective_port"]))
        worklist_probe = self._socket_status(str(worklist["effective_host"]), int(worklist["effective_port"]))

        return {
            "database": database_status,
            "pacs": {
                **pacs,
                "ok": pacs_probe["ok"],
                "message": pacs_probe["message"],
                "latency_ms": pacs_probe["latency_ms"],
            },
            "worklist": {
                **worklist,
                "ok": worklist_probe["ok"],
                "message": worklist_probe["message"],
                "latency_ms": worklist_probe["latency_ms"],
            },
            "external_enabled": pacs["mode"] == "external" or worklist["mode"] == "external" or database_status["mode"] == "external",
        }

    def _setting_json(self, key: str, default: dict[str, Any]) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute("select value from raiox.system_settings where key = %s", (key,))
                row = cur.fetchone()
        if not row:
            return default
        value = row.get("value")
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return default
            return parsed if isinstance(parsed, dict) else default
        return default

    def _save_setting_json(self, key: str, value: dict[str, Any]) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into raiox.system_settings (key, value, updated_at)
                    values (%s, %s::jsonb, now())
                    on conflict (key) do update
                    set value = excluded.value,
                        updated_at = now()
                    """,
                    (key, json.dumps(value)),
                )
            conn.commit()
        return self._setting_json(key, value)

    def _normalize_pricing_overrides(self, value: Any) -> dict[str, Any]:
        source = value if isinstance(value, dict) else {}
        items: list[dict[str, Any]] = []
        for item in source.get("items") or []:
            if not isinstance(item, dict):
                continue
            convenio_code = self._normalize_convenio_code(item.get("convenio_code") or item.get("code"))
            try:
                procedure_id = int(item.get("procedure_id") or 0)
            except (TypeError, ValueError):
                continue
            if procedure_id <= 0:
                continue
            prices_raw = item.get("prices") or {}
            prices: dict[str, Any] = {}
            for incidence in ("1", "2", "3"):
                try:
                    price_value = Decimal(str((prices_raw or {}).get(incidence) or 0))
                except Exception:
                    price_value = Decimal("0")
                prices[incidence] = price_value
            items.append({
                "convenio_code": convenio_code,
                "procedure_id": procedure_id,
                "prices": prices,
                "active": bool(item.get("active", True)),
            })
        return {"items": items}

    def get_pricing_overrides(self) -> dict[str, Any]:
        table_overrides = self._pricing_overrides_from_tables()
        if not table_overrides:
            cached_overrides = self._normalize_pricing_overrides(self._setting_json("pricing_overrides", {"items": []}))
            if cached_overrides.get("items"):
                self._sync_pricing_overrides_tables(cached_overrides["items"])
                table_overrides = self._pricing_overrides_from_tables()
        config = table_overrides or {"items": []}
        normalized = self._normalize_pricing_overrides(config)
        for item in normalized["items"]:
            for incidence, price in list(item["prices"].items()):
                item["prices"][incidence] = float(price)
        return normalized

    def _pricing_overrides_from_tables(self) -> dict[str, Any] | None:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        c.code as convenio_code,
                        cp.procedure_id,
                        cp.incidences_count,
                        cp.price
                    from raiox.convenio_price cp
                    join raiox.convenio c on c.id = cp.convenio_id
                    join raiox.procedure_catalog p on p.id = cp.procedure_id
                    where c.active = true
                      and p.active = true
                      and cp.active = true
                    order by c.code, p.name, cp.incidences_count
                    """
                )
                rows = list(cur.fetchall())
        if not rows:
            return None

        items_by_key: dict[tuple[str, int], dict[str, Any]] = {}
        for row in rows:
            convenio_code = self._normalize_convenio_code(row.get("convenio_code"))
            procedure_id = int(row.get("procedure_id") or 0)
            if procedure_id <= 0:
                continue
            key = (convenio_code, procedure_id)
            item = items_by_key.setdefault(
                key,
                {
                    "convenio_code": convenio_code,
                    "procedure_id": procedure_id,
                    "prices": {"1": Decimal("0"), "2": Decimal("0"), "3": Decimal("0")},
                    "active": True,
                },
            )
            incidence = str(max(1, min(int(row.get("incidences_count") or 1), 3)))
            try:
                item["prices"][incidence] = Decimal(str(row.get("price") or 0))
            except Exception:
                item["prices"][incidence] = Decimal("0")

        items = [item for item in items_by_key.values() if item.get("active")]
        return {"items": items} if items else None

    def _save_pricing_overrides_cache(self, overrides: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_pricing_overrides(overrides)
        stored_items = [
            {
                "convenio_code": item["convenio_code"],
                "procedure_id": item["procedure_id"],
                "prices": {incidence: str(price) for incidence, price in item["prices"].items()},
                "active": bool(item.get("active", True)),
            }
            for item in normalized["items"]
        ]
        return self._save_setting_json("pricing_overrides", {"items": stored_items})

    def _sync_pricing_overrides_tables(self, items: list[dict[str, Any]]) -> None:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                for item in items:
                    convenio_code = self._normalize_convenio_code(item.get("convenio_code"))
                    procedure_id = int(item.get("procedure_id") or 0)
                    prices = item.get("prices") or {}
                    if procedure_id <= 0:
                        continue
                    cur.execute("select id from raiox.procedure_catalog where id = %s", (procedure_id,))
                    if not cur.fetchone():
                        continue
                    convenio_id = self._upsert_convenio(cur, convenio_code)
                    for incidence in ("1", "2", "3"):
                        price = prices.get(incidence, Decimal("0"))
                        cur.execute(
                            """
                            insert into raiox.convenio_price (
                                convenio_id, procedure_id, incidences_count, price, active, updated_at
                            ) values (%s, %s, %s, %s, %s, now())
                            on conflict (convenio_id, procedure_id, incidences_count) do update
                            set price = excluded.price,
                                active = excluded.active,
                                updated_at = now()
                            """,
                            (convenio_id, procedure_id, int(incidence), price, bool(item.get("active", True))),
                        )
            conn.commit()

    def _upsert_convenio(self, cur: Any, convenio_code: str) -> int:
        fallback_name = convenio_code.replace("_", " ").title()
        cur.execute(
            """
            insert into raiox.convenio (code, name, active, updated_at)
            values (%s, %s, true, now())
            on conflict (code) do update
            set active = true,
                updated_at = now()
            returning id
            """,
            (convenio_code, fallback_name),
        )
        row = cur.fetchone() or {}
        return int(row.get("id") or 0)

    def update_pricing_override(self, payload: dict[str, Any]) -> dict[str, Any]:
        convenio_code = self._normalize_convenio_code(payload.get("convenio_code") or "PARTICULAR")
        try:
            procedure_id = int(payload.get("procedure_id") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("Procedimento invalido para ajuste de preco.") from exc
        if procedure_id <= 0:
            raise ValueError("Procedimento invalido para ajuste de preco.")

        current = self._normalize_pricing_overrides(self._pricing_overrides_from_tables() or self._setting_json("pricing_overrides", {"items": []}))
        existing = next((
            item for item in current["items"]
            if self._normalize_convenio_code(item.get("convenio_code")) == convenio_code
            and int(item.get("procedure_id") or 0) == procedure_id
        ), None)
        prices_payload = payload.get("prices") or {}
        prices: dict[str, Any] = {}
        for incidence in ("1", "2", "3"):
            raw_value = prices_payload.get(incidence)
            if raw_value in (None, "") and existing:
                raw_value = (existing.get("prices") or {}).get(incidence)
            try:
                price_value = Decimal(str(raw_value or 0)).quantize(Decimal("0.01"))
            except Exception as exc:
                raise ValueError(f"Preco invalido para ajuste de incidencias {incidence}.") from exc
            prices[incidence] = price_value

        has_active_price = any(float(price) != 0 for price in prices.values())
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute("select id from raiox.procedure_catalog where id = %s and active = true", (procedure_id,))
                if not cur.fetchone():
                    raise ValueError("Procedimento ativo nao encontrado para ajuste de preco.")
                convenio_id = self._upsert_convenio(cur, convenio_code)
                if has_active_price:
                    for incidence, price in prices.items():
                        cur.execute(
                            """
                            insert into raiox.convenio_price (
                                convenio_id, procedure_id, incidences_count, price, active, updated_at
                            ) values (%s, %s, %s, %s, true, now())
                            on conflict (convenio_id, procedure_id, incidences_count) do update
                            set price = excluded.price,
                                active = true,
                                updated_at = now()
                            """,
                            (convenio_id, procedure_id, int(incidence), price),
                        )
                else:
                    cur.execute(
                        """
                        update raiox.convenio_price
                        set active = false,
                            updated_at = now()
                        where convenio_id = %s
                          and procedure_id = %s
                        """,
                        (convenio_id, procedure_id),
                    )
            conn.commit()

        self._save_pricing_overrides_cache(self._pricing_overrides_from_tables() or {"items": []})
        return self.get_pricing_overrides()

    def list_patients(self) -> list[dict[str, Any]]:
        sql = """
            select
                p.id,
                p.external_patient_id,
                p.full_name,
                p.birth_date,
                p.sex,
                p.cpf,
                p.phone,
                p.email,
                p.notes,
                p.created_at,
                p.updated_at,
                count(e.id) as exam_count,
                max(e.scheduled_at) as last_exam_at
            from raiox.patient p
            left join raiox.exam e on e.patient_id = p.id
            group by p.id
            order by p.full_name asc
        """
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                return list(cur.fetchall())

    def get_patient(self, patient_id: int) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute("select * from raiox.patient where id = %s", (patient_id,))
                row = cur.fetchone()
                if not row:
                    raise ValueError("Paciente nao encontrado.")
                return row

    def _normalized_letters(self, value: str | None) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
        return "".join(char for char in ascii_value.lower() if char.isalpha())

    def _share_username_for_patient(self, patient: dict[str, Any]) -> str:
        cpf = clean_digits(patient.get("cpf") or "")
        if cpf:
            return cpf[:64]
        external_id = clean_digits(patient.get("external_patient_id") or "")
        if external_id:
            return external_id[:64]
        return f"paciente{int(patient['id']):06d}"

    def _share_password_for_patient(self, patient: dict[str, Any]) -> str:
        letters = self._normalized_letters(patient.get("full_name") or "")
        if not letters:
            letters = "paciente"
        first = letters[0]
        last = letters[-1]
        marker = letters[len(letters) // 2]
        first_word = secrets.choice(SHARE_PASSWORD_WORDS)
        remaining_words = tuple(word for word in SHARE_PASSWORD_WORDS if word != first_word) or SHARE_PASSWORD_WORDS
        second_word = secrets.choice(remaining_words)
        return f"{first}&{last}@{marker}{first_word}{second_word}"

    def suggest_share_credentials(self, *, patient_id: int | None = None, exam_id: int | None = None) -> dict[str, Any]:
        resolved_patient_id = int(patient_id or 0) or None
        if not resolved_patient_id and exam_id:
            exam = self.get_exam(exam_id)
            resolved_patient_id = int(exam["patient_id"])
        if not resolved_patient_id:
            raise ValueError("Selecione um paciente para gerar o acesso externo.")
        patient = self.get_patient(resolved_patient_id)
        return {
            "username": self._share_username_for_patient(patient),
            "password": self._share_password_for_patient(patient),
        }

    def save_patient(self, payload: dict[str, Any], patient_id: int | None = None) -> dict[str, Any]:
        full_name = (payload.get("full_name") or "").strip()
        if not full_name:
            raise ValueError("Nome do paciente e obrigatorio.")

        values = {
            "external_patient_id": (payload.get("external_patient_id") or "").strip() or None,
            "full_name": full_name,
            "birth_date": parse_date(payload.get("birth_date") or ""),
            "sex": (payload.get("sex") or "").strip().upper() or None,
            "cpf": clean_digits(payload.get("cpf") or "") or None,
            "phone": (payload.get("phone") or "").strip() or None,
            "email": (payload.get("email") or "").strip() or None,
            "notes": (payload.get("notes") or "").strip() or None,
        }
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                if patient_id is None:
                    cur.execute(
                        """
                        insert into raiox.patient (
                            external_patient_id, full_name, birth_date, sex, cpf, phone, email, notes
                        ) values (%(external_patient_id)s, %(full_name)s, %(birth_date)s, %(sex)s, %(cpf)s, %(phone)s, %(email)s, %(notes)s)
                        returning id
                        """,
                        values,
                    )
                    patient_id = cur.fetchone()["id"]
                else:
                    values["id"] = patient_id
                    cur.execute(
                        """
                        update raiox.patient
                        set external_patient_id = %(external_patient_id)s,
                            full_name = %(full_name)s,
                            birth_date = %(birth_date)s,
                            sex = %(sex)s,
                            cpf = %(cpf)s,
                            phone = %(phone)s,
                            email = %(email)s,
                            notes = %(notes)s,
                            updated_at = now()
                        where id = %(id)s
                        """,
                        values,
                    )
            conn.commit()
        return self.get_patient(patient_id)

    def list_procedures(self) -> list[dict[str, Any]]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select *
                    from raiox.procedure_catalog
                    where active = true
                    order by name asc
                    """
                )
                rows = list(cur.fetchall())
        for row in rows:
            row["modality"] = self._normalize_modality(row.get("modality") or "DR")
        return rows

    def get_procedure(self, procedure_id: int) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute("select * from raiox.procedure_catalog where id = %s", (procedure_id,))
                row = cur.fetchone()
                if not row:
                    raise ValueError("Procedimento nao encontrado.")
                row["modality"] = self._normalize_modality(row.get("modality") or "DR")
                return row

    def save_procedure(self, payload: dict[str, Any], procedure_id: int | None = None) -> dict[str, Any]:
        code = (payload.get("code") or "").strip().upper()
        name = (payload.get("name") or "").strip()
        if not name:
            raise ValueError("Nome do procedimento e obrigatorio.")
        if not code:
            code = self._generate_procedure_code(name, procedure_id=procedure_id)

        values = {
            "code": code,
            "name": name,
            "modality": self._normalize_modality(payload.get("modality") or "DR"),
            "default_price": Decimal(str(payload.get("default_price") or "0")),
            "duration_minutes": int(payload.get("duration_minutes") or 20),
            "active": parse_bool(payload.get("active"), True),
        }
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                if procedure_id is None:
                    cur.execute(
                        """
                        insert into raiox.procedure_catalog (
                            code, name, modality, default_price, duration_minutes, active
                        ) values (%(code)s, %(name)s, %(modality)s, %(default_price)s, %(duration_minutes)s, %(active)s)
                        returning id
                        """,
                        values,
                    )
                    procedure_id = cur.fetchone()["id"]
                else:
                    values["id"] = procedure_id
                    cur.execute(
                        """
                        update raiox.procedure_catalog
                        set code = %(code)s,
                            name = %(name)s,
                            modality = %(modality)s,
                            default_price = %(default_price)s,
                            duration_minutes = %(duration_minutes)s,
                            active = %(active)s,
                            updated_at = now()
                        where id = %(id)s
                        """,
                        values,
                    )
            conn.commit()
        return self.get_procedure(procedure_id)

    def delete_procedure(self, procedure_id: int) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute("select id, name from raiox.procedure_catalog where id = %s", (procedure_id,))
                procedure = cur.fetchone()
                if not procedure:
                    raise ValueError("Procedimento nao encontrado.")

                cur.execute("select count(*) as total from raiox.exam where procedure_id = %s", (procedure_id,))
                exam_count = int((cur.fetchone() or {}).get("total") or 0)
                if exam_count > 0:
                    raise ValueError(
                        f"Procedimento nao pode ser excluido porque possui {exam_count} exame(s) no workflow."
                    )

                cur.execute(
                    "select count(*) as total from raiox.convenio_price where procedure_id = %s",
                    (procedure_id,),
                )
                price_count = int((cur.fetchone() or {}).get("total") or 0)
                if price_count > 0:
                    raise ValueError(
                        f"Procedimento nao pode ser excluido porque possui {price_count} vinculo(s) financeiro(s)."
                    )

                cur.execute("delete from raiox.procedure_catalog where id = %s", (procedure_id,))
            conn.commit()
        return {"deleted": True, "id": procedure_id, "name": procedure.get("name")}

    def _generate_procedure_code(self, name: str, procedure_id: int | None = None) -> str:
        base = re.sub(r"[^A-Z0-9]+", "", self._normalized_letters(name).upper()) or "PROC"
        base = base[:24]
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                params: list[Any] = []
                sql = "select code from raiox.procedure_catalog"
                if procedure_id is not None:
                    sql += " where id <> %s"
                    params.append(procedure_id)
                cur.execute(sql, params)
                existing_codes = {str(row.get("code") or "").strip().upper() for row in cur.fetchall()}
        code = base
        suffix = 2
        while code in existing_codes:
            suffix_text = f"-{suffix}"
            prefix_len = max(1, 32 - len(suffix_text))
            code = f"{base[:prefix_len]}{suffix_text}"
            suffix += 1
        return code[:32]

    def list_operators(self) -> list[dict[str, Any]]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        o.*,
                        count(m.id) filter (where m.read_at is null) as pending_messages
                    from raiox.operator o
                    left join raiox.chat_message m on m.recipient_operator_id = o.id
                    group by o.id
                    order by o.active desc, o.sector asc nulls last, o.name asc
                    """
                )
                return list(cur.fetchall())

    def get_operator(self, operator_id: int) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute("select * from raiox.operator where id = %s", (operator_id,))
                row = cur.fetchone()
                if not row:
                    raise ValueError("Operador nao encontrado.")
                return row

    def save_operator(self, payload: dict[str, Any], operator_id: int | None = None) -> dict[str, Any]:
        name = (payload.get("name") or "").strip()
        if not name:
            raise ValueError("Nome do operador e obrigatorio.")

        values = {
            "name": name[:120],
            "role": (payload.get("role") or "").strip()[:64] or None,
            "sector": (payload.get("sector") or "").strip()[:64] or None,
            "extension": (payload.get("extension") or "").strip()[:32] or None,
            "sip_username": (payload.get("sip_username") or "").strip()[:64] or None,
            "sip_password": (payload.get("sip_password") or "").strip()[:128] or None,
            "active": parse_bool(payload.get("active"), True),
        }
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                if operator_id is None:
                    cur.execute(
                        """
                        insert into raiox.operator (
                            name, role, sector, extension, sip_username, sip_password, active
                        ) values (
                            %(name)s, %(role)s, %(sector)s, %(extension)s, %(sip_username)s, %(sip_password)s, %(active)s
                        )
                        returning id
                        """,
                        values,
                    )
                    operator_id = cur.fetchone()["id"]
                else:
                    values["id"] = operator_id
                    cur.execute(
                        """
                        update raiox.operator
                        set name = %(name)s,
                            role = %(role)s,
                            sector = %(sector)s,
                            extension = %(extension)s,
                            sip_username = %(sip_username)s,
                            sip_password = %(sip_password)s,
                            active = %(active)s,
                            updated_at = now()
                        where id = %(id)s
                        """,
                        values,
                    )
            conn.commit()
        return self.get_operator(operator_id)

    def get_sip_config(self) -> dict[str, Any]:
        return self._setting_json("sip_config", self._sip_default())

    def update_sip_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = payload.get("freepbx") or {}
        config = {
            "enabled": parse_bool(payload.get("enabled"), self.settings.sip_enabled),
            "mode_active": (payload.get("mode_active") or self.settings.sip_mode_active or "freepbx").strip() or "freepbx",
            "freepbx": {
                "ws_url": (profile.get("ws_url") or "").strip(),
                "domain": (profile.get("domain") or "").strip(),
                "registrar_server": (profile.get("registrar_server") or "").strip(),
                "outbound_proxy": (profile.get("outbound_proxy") or "").strip(),
                "prefix": (profile.get("prefix") or "").strip(),
                "caller_id_template": (profile.get("caller_id_template") or "{nome} raioXPacs").strip() or "{nome} raioXPacs",
                "auto_register": parse_bool(profile.get("auto_register"), True),
            },
        }
        return self._save_setting_json("sip_config", config)

    def get_sip_context(self, operator_id: int) -> dict[str, Any]:
        return {
            "config": self.get_sip_config(),
            "operator": self.get_operator(operator_id),
        }

    def get_panel_config(self) -> dict[str, Any]:
        panel = self._setting_json("panel_config", self._panel_default())
        panel["destinations"] = [str(item).strip() for item in panel.get("destinations") or [] if str(item).strip()]
        if not panel["destinations"]:
            panel["destinations"] = self.settings.panel_destinations
        return panel

    def update_panel_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        destinations = payload.get("destinations") or []
        if isinstance(destinations, str):
            destinations = [item.strip() for item in destinations.split(",") if item.strip()]
        panel = {
            "title": (payload.get("title") or self.settings.panel_title).strip() or self.settings.panel_title,
            "subtitle": (payload.get("subtitle") or self.settings.panel_subtitle).strip() or self.settings.panel_subtitle,
            "video_url": (payload.get("video_url") or "").strip(),
            "destinations": [str(item).strip() for item in destinations if str(item).strip()] or self.settings.panel_destinations,
            "auto_announce": parse_bool(payload.get("auto_announce"), True),
        }
        return self._save_setting_json("panel_config", panel)

    def _exam_base_query(self) -> str:
        return """
            select
                e.id,
                e.patient_id,
                e.procedure_id,
                e.convenio_code,
                e.incidences_count,
                e.accession_number,
                e.study_instance_uid,
                e.requested_procedure_id,
                e.requested_description,
                e.referring_physician,
                e.performing_physician,
                e.scheduled_at,
                e.modality,
                e.priority,
                e.station_aet,
                e.status,
                e.workflow_stage,
                e.worklist_status,
                e.pacs_study_found,
                e.pacs_report_status,
                e.price,
                e.order_id,
                o.reference as order_reference,
                o.status as order_status,
                o.discount as order_discount,
                o.amount as order_amount,
                o.net_amount as order_net_amount,
                o.billing_status as order_billing_status,
                e.billing_status,
                e.notes,
                e.created_at,
                e.updated_at,
                p.full_name as patient_name,
                p.cpf as patient_cpf,
                p.birth_date as patient_birth_date,
                p.sex as patient_sex,
                p.phone as patient_phone,
                p.email as patient_email,
                p.external_patient_id,
                proc.code as procedure_code,
                proc.name as procedure_name,
                proc.modality as procedure_modality,
                ct.id as ticket_id,
                ct.queue_date,
                ct.ticket_number,
                ct.status as queue_status,
                ct.destination as queue_destination,
                ct.called_at,
                ct.completed_at,
                wl.accessionnumber is not null as pacs_worklist_present,
                wl.spsstatus as pacs_worklist_status,
                st.studyinstanceuid as live_study_instance_uid,
                st.studydate as live_study_date,
                st.studytime as live_study_time,
                st.stationname as live_station_name,
                mr.status as local_report_status,
                mr.doctor_name as local_report_doctor_name,
                mr.updated_at as local_report_updated_at,
                coalesce(mr.signed_at, ct.completed_at, e.updated_at, e.created_at) as finalized_at,
                rp.status as live_report_status_code,
                rp.assigned as report_assigned,
                rp.preliminary as report_preliminary,
                rp.final as report_final,
                (
                    select count(*) from public.objects obj
                    where obj.studyinstanceuid = coalesce(st.studyinstanceuid, e.study_instance_uid)
                ) as object_count
            from raiox.exam e
            join raiox.patient p on p.id = e.patient_id
            join raiox.procedure_catalog proc on proc.id = e.procedure_id
            left join raiox.call_ticket ct on ct.exam_id = e.id
            left join public.worklist wl on wl.accessionnumber = e.accession_number
            left join raiox.medical_report mr on mr.exam_id = e.id
            left join raiox.exam_order o on o.id = e.order_id
            left join public.study st
                on st.studyinstanceuid = e.study_instance_uid
                or st.accessionnumber = e.accession_number
            left join lateral (
                select rp.*
                from public.reports rp
                where rp.studyinstanceuid = coalesce(st.studyinstanceuid, e.study_instance_uid)
                limit 1
            ) rp on true
        """

    def _decorate_exam_row(self, row: dict[str, Any]) -> dict[str, Any]:
        local_report_status = self._normalize_report_status(row.get("local_report_status")) if row.get("local_report_status") else ""
        report_assigned = bool(row.get("report_assigned")) or local_report_status in {"assigned", "preliminary", "final"}
        report_preliminary = bool(row.get("report_preliminary")) or local_report_status in {"preliminary", "final"}
        report_final = bool(row.get("report_final")) or local_report_status == "final"
        row["report_assigned"] = report_assigned
        row["report_preliminary"] = report_preliminary
        row["report_final"] = report_final

        report_stage = ""
        if report_final:
            report_stage = "final"
        elif report_preliminary:
            report_stage = "preliminary"
        elif report_assigned:
            report_stage = "assigned"
        elif row.get("live_study_instance_uid"):
            report_stage = "acquired"

        worklist_status = self._derive_worklist_status(row)
        live_status = row.get("status") or "scheduled"
        if report_final:
            live_status = "reported"
        elif report_preliminary or report_assigned:
            live_status = "reporting"
        elif worklist_status == "cancelled":
            live_status = "cancelled"
        elif worklist_status == "removed":
            live_status = "removed"
        elif row.get("live_study_instance_uid"):
            live_status = "executed"
        elif worklist_status in WORKLIST_OPEN_STATUSES:
            live_status = worklist_status

        workflow_stage = self._recommended_stage_from_row({**row, "live_status": live_status, "worklist_status": worklist_status})
        locked, lock_reason = self._manual_transition_lock(
            {**row, "workflow_stage": workflow_stage, "live_status": live_status, "worklist_status": worklist_status}
        )

        row["live_status"] = live_status
        row["live_report_stage"] = report_stage
        row["patient_label"] = f"{row.get('patient_name')} ({row.get('procedure_name')})"
        row["modality"] = self._normalize_modality(row.get("modality") or row.get("procedure_modality") or "DR")
        row["procedure_modality"] = self._normalize_modality(row.get("procedure_modality") or row.get("modality") or "DR")
        row["worklist_status"] = worklist_status
        row["workflow_stage"] = workflow_stage
        row["workflow_label"] = WORKFLOW_LABELS.get(workflow_stage, workflow_stage)
        row["worklist_status_label"] = WORKFLOW_LABELS.get(worklist_status, worklist_status)
        row["convenio_label"] = row.get("convenio_code") or "PARTICULAR"
        row["order_id"] = row.get("order_id")
        row["order_reference"] = row.get("order_reference")
        row["order_status"] = row.get("order_status")
        row["order_discount"] = row.get("order_discount") or 0
        row["order_amount"] = row.get("order_amount") or 0
        row["order_net_amount"] = row.get("order_net_amount") or 0
        row["order_billing_status"] = row.get("order_billing_status")
        row["incidences_label"] = f"{int(row.get('incidences_count') or 1)} incidencias"
        row["finalized_at"] = row.get("finalized_at") or row.get("local_report_updated_at") or row.get("updated_at")
        row["pacs_worklist_status_label"] = WORKFLOW_LABELS.get(
            self._stage_from_pacs_worklist(row.get("pacs_worklist_status")),
            (row.get("pacs_worklist_status") or "").strip().upper() or "-",
        )
        row["manual_transition_allowed"] = not locked
        row["manual_transition_reason"] = lock_reason
        row["local_worklist_active"] = worklist_status in WORKLIST_OPEN_STATUSES
        return row

    def list_exams(self) -> list[dict[str, Any]]:
        sql = self._exam_base_query() + " order by coalesce(e.scheduled_at, e.created_at) desc, e.id desc"
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = list(cur.fetchall())
        return [self._decorate_exam_row(row) for row in rows]

    def _is_archived_finalized(self, exam: dict[str, Any], cutoff: datetime | None = None) -> bool:
        if self._normalize_stage(exam.get("workflow_stage")) != "finalized":
            return False
        finalized_at = exam.get("finalized_at") or exam.get("local_report_updated_at") or exam.get("updated_at")
        if not isinstance(finalized_at, datetime):
            return False
        compare_cutoff = cutoff or (datetime.now() - timedelta(hours=FINALIZED_HISTORY_HOURS))
        return finalized_at <= compare_cutoff

    def list_exam_history(self, limit: int = 100) -> list[dict[str, Any]]:
        cutoff = datetime.now() - timedelta(hours=FINALIZED_HISTORY_HOURS)
        history = [exam for exam in self.list_exams() if self._is_archived_finalized(exam, cutoff)]
        history.sort(key=lambda row: row.get("finalized_at") or row.get("local_report_updated_at") or row.get("updated_at"), reverse=True)
        return history[:max(1, limit)]

    def get_exam(self, exam_id: int) -> dict[str, Any]:
        sql = self._exam_base_query() + " where e.id = %s"
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (exam_id,))
                row = cur.fetchone()
                if not row:
                    raise ValueError("Exame nao encontrado.")
        return self._decorate_exam_row(row)

    def _ensure_invoice(self, cur: Any, exam_id: int, amount: Decimal, scheduled_at: datetime | None) -> None:
        due_date = (scheduled_at.date() if scheduled_at else date.today()) + timedelta(days=15)
        cur.execute("select id, status from raiox.invoice where exam_id = %s", (exam_id,))
        existing = cur.fetchone()
        if existing:
            if existing["status"] != "paid":
                cur.execute(
                    """
                    update raiox.invoice
                    set amount = %s,
                        due_date = %s,
                        updated_at = now()
                    where exam_id = %s
                    """,
                    (amount, due_date, exam_id),
                )
            return

        cur.execute(
            """
            insert into raiox.invoice (exam_id, invoice_number, amount, due_date)
            values (%s, %s, %s, %s)
            """,
            (exam_id, invoice_number_for_exam(exam_id), amount, due_date),
        )

    def _order_due_date(self, scheduled_at: datetime | None) -> date:
        if scheduled_at:
            return scheduled_at.date() + timedelta(days=15)
        return date.today() + timedelta(days=15)

    def _ensure_order_invoice(self, cur: Any, order_id: int, scheduled_at: datetime | None) -> None:
        cur.execute("select id, discount from raiox.exam_order where id = %s", (order_id,))
        order_row = cur.fetchone()
        if not order_row:
            raise ValueError("Ordem de exame nao encontrada.")

        cur.execute(
            "select coalesce(sum(price), 0) as total_amount from raiox.exam where order_id = %s",
            (order_id,),
        )
        totals = cur.fetchone() or {}
        amount = Decimal(str(totals.get("total_amount") or 0))
        discount = Decimal(str(order_row.get("discount") or 0))
        net_amount = amount - discount
        if net_amount < 0:
            net_amount = Decimal("0")

        due_date = self._order_due_date(scheduled_at)
        cur.execute(
            "update raiox.exam_order set amount = %s, net_amount = %s, updated_at = now() where id = %s",
            (amount, net_amount, order_id),
        )

        cur.execute("select id, status from raiox.invoice where order_id = %s", (order_id,))
        existing = cur.fetchone()
        if existing:
            if existing["status"] != "paid":
                cur.execute(
                    """
                    update raiox.invoice
                    set amount = %s,
                        discount = %s,
                        due_date = %s,
                        updated_at = now()
                    where order_id = %s
                    """,
                    (amount, discount, due_date, order_id),
                )
            return

        cur.execute(
            """
            insert into raiox.invoice (order_id, invoice_number, amount, discount, due_date)
            values (%s, %s, %s, %s, %s)
            """,
            (order_id, invoice_number_for_order(order_id), amount, discount, due_date),
        )

    def _ensure_call_ticket(self, cur: Any, exam_id: int, scheduled_at: datetime | None) -> None:
        cur.execute("select id from raiox.call_ticket where exam_id = %s", (exam_id,))
        if cur.fetchone():
            return
        queue_date = scheduled_at.date() if scheduled_at else date.today()
        cur.execute(
            "select coalesce(max(ticket_number), 0) + 1 as next_ticket from raiox.call_ticket where queue_date = %s",
            (queue_date,),
        )
        row = cur.fetchone() or {}
        next_ticket = int(row.get("next_ticket") or 1)
        cur.execute(
            """
            insert into raiox.call_ticket (exam_id, queue_date, ticket_number, status)
            values (%s, %s, %s, 'waiting')
            on conflict (exam_id) do nothing
            """,
            (exam_id, queue_date, next_ticket),
        )

    def save_exam(self, payload: dict[str, Any], exam_id: int | None = None, conn: Any | None = None, commit: bool | None = None) -> dict[str, Any]:
        patient_id = int(payload.get("patient_id") or 0)
        procedure_id = int(payload.get("procedure_id") or 0)
        if not patient_id or not procedure_id:
            raise ValueError("Paciente e procedimento sao obrigatorios.")

        manual_price_raw = Decimal(str(payload.get("price") or "0"))
        accession_number = (payload.get("accession_number") or "").strip() or build_accession_number()
        study_instance_uid = (payload.get("study_instance_uid") or "").strip() or build_uid(self.settings.rad_uid_root)
        convenio_code_input = payload.get("convenio_code")
        convenio_code = self._normalize_convenio_code(convenio_code_input or "PARTICULAR")
        incidences_input = payload.get("incidences_count")
        try:
            incidences_count = max(1, min(int(incidences_input or 1), 3))
        except (TypeError, ValueError) as exc:
            raise ValueError("Quantidade de incidencias invalida.") from exc

        order_id = payload.get("order_id")
        if order_id is not None and not isinstance(order_id, int):
            order_id_text = str(order_id).strip()
            order_id = int(order_id_text) if order_id_text.isdigit() else None
        if order_id == 0:
            order_id = None

        commit_on_exit = commit if commit is not None else conn is None
        connection_context = self.database.clinic() if conn is None else nullcontext(conn)
        with connection_context as active_conn:
            with active_conn.cursor() as cur:
                current_stage = "scheduled"
                current_worklist_status = "scheduled"
                current_procedure_id = None
                current_order_id = None
                if exam_id is not None:
                    cur.execute(
                        "select procedure_id, workflow_stage, worklist_status, convenio_code, incidences_count, scheduled_at, order_id from raiox.exam where id = %s",
                        (exam_id,),
                    )
                    current_row = cur.fetchone()
                    if not current_row:
                        raise ValueError("Exame nao encontrado.")
                    current_procedure_id = int(current_row.get("procedure_id") or 0)
                    current_order_id = current_row.get("order_id")
                    current_stage = self._normalize_stage(current_row.get("workflow_stage"))
                    current_worklist_status = self._normalize_worklist_status(current_row.get("worklist_status"))
                    current_scheduled_at = current_row.get("scheduled_at")
                    if convenio_code_input in (None, ""):
                        convenio_code = self._normalize_convenio_code(current_row.get("convenio_code") or convenio_code)
                    if incidences_input in (None, ""):
                        incidences_count = max(1, min(int(current_row.get("incidences_count") or incidences_count), 3))
                else:
                    current_scheduled_at = None

                cur.execute("select id from raiox.patient where id = %s", (patient_id,))
                if not cur.fetchone():
                    raise ValueError("Paciente nao cadastrado. Cadastre o paciente antes de lancar o exame.")

                if order_id is not None:
                    cur.execute("select id from raiox.exam_order where id = %s", (order_id,))
                    if not cur.fetchone():
                        raise ValueError("Ordem de exame nao encontrada.")

                scheduled_at = parse_datetime(payload.get("scheduled_at") or "")
                if not scheduled_at:
                    scheduled_at = current_scheduled_at or datetime.combine(date.today(), datetime.min.time())

                cur.execute(
                    "select id, name, code, modality, active from raiox.procedure_catalog where id = %s",
                    (procedure_id,),
                )
                procedure = cur.fetchone()
                if not procedure:
                    raise ValueError("Procedimento nao encontrado.")
                if procedure.get("active") is False and procedure_id != current_procedure_id:
                    raise ValueError("Procedimento inativo nao pode ser selecionado para novo exame.")

                price = self._resolve_exam_price(
                    procedure,
                    convenio_code,
                    incidences_count,
                    manual_price_raw if manual_price_raw > 0 else None,
                )

                workflow_stage = self._normalize_stage(payload.get("workflow_stage"), current_stage)
                worklist_status = self._normalize_worklist_status(
                    payload.get("worklist_status"),
                    self._worklist_status_from_stage(workflow_stage, current_worklist_status),
                )
                if payload.get("workflow_stage") and not payload.get("worklist_status"):
                    worklist_status = self._worklist_status_from_stage(workflow_stage, current_worklist_status)
                if not payload.get("workflow_stage") and payload.get("worklist_status"):
                    workflow_stage = self._normalize_stage(payload.get("worklist_status"), current_stage)

                values = {
                    "patient_id": patient_id,
                    "procedure_id": procedure_id,
                    "order_id": order_id,
                    "convenio_code": convenio_code,
                    "incidences_count": incidences_count,
                    "accession_number": accession_number[:16],
                    "study_instance_uid": study_instance_uid[:64],
                    "requested_procedure_id": ((payload.get("requested_procedure_id") or procedure["code"]).strip())[:32],
                    "requested_description": ((payload.get("requested_description") or procedure["name"]).strip())[:160],
                    "referring_physician": ((payload.get("referring_physician") or "").strip())[:128] or None,
                    "performing_physician": ((payload.get("performing_physician") or "").strip())[:128] or None,
                    "scheduled_at": scheduled_at,
                    "modality": self._normalize_modality(payload.get("modality") or procedure["modality"] or "DR"),
                    "priority": ((payload.get("priority") or "ROUTINE").strip().upper())[:16] or "ROUTINE",
                    "station_aet": ((payload.get("station_aet") or self.settings.pacs_station_aet).strip())[:32] or self.settings.pacs_station_aet,
                    "status": self._exam_status_from_stage(workflow_stage),
                    "workflow_stage": workflow_stage,
                    "worklist_status": worklist_status,
                    "price": price,
                    "billing_status": ((payload.get("billing_status") or "pending").strip().lower())[:24] or "pending",
                    "notes": (payload.get("notes") or "").strip() or None,
                }

                if exam_id is None:
                    cur.execute(
                        """
                        insert into raiox.exam (
                            patient_id, procedure_id, order_id, convenio_code, incidences_count, accession_number, study_instance_uid,
                            requested_procedure_id, requested_description, referring_physician, performing_physician,
                            scheduled_at, modality, priority, station_aet, status, workflow_stage, worklist_status,
                            price, billing_status, notes
                        ) values (
                            %(patient_id)s, %(procedure_id)s, %(order_id)s, %(convenio_code)s, %(incidences_count)s, %(accession_number)s, %(study_instance_uid)s,
                            %(requested_procedure_id)s, %(requested_description)s, %(referring_physician)s, %(performing_physician)s,
                            %(scheduled_at)s, %(modality)s, %(priority)s, %(station_aet)s, %(status)s, %(workflow_stage)s, %(worklist_status)s,
                            %(price)s, %(billing_status)s, %(notes)s
                        )
                        returning id
                        """,
                        values,
                    )
                    exam_id = cur.fetchone()["id"]
                else:
                    values["id"] = exam_id
                    cur.execute(
                        """
                        update raiox.exam
                        set patient_id = %(patient_id)s,
                            procedure_id = %(procedure_id)s,
                            order_id = %(order_id)s,
                            convenio_code = %(convenio_code)s,
                            incidences_count = %(incidences_count)s,
                            accession_number = %(accession_number)s,
                            study_instance_uid = %(study_instance_uid)s,
                            requested_procedure_id = %(requested_procedure_id)s,
                            requested_description = %(requested_description)s,
                            referring_physician = %(referring_physician)s,
                            performing_physician = %(performing_physician)s,
                            scheduled_at = %(scheduled_at)s,
                            modality = %(modality)s,
                            priority = %(priority)s,
                            station_aet = %(station_aet)s,
                            status = %(status)s,
                            workflow_stage = %(workflow_stage)s,
                            worklist_status = %(worklist_status)s,
                            price = %(price)s,
                            billing_status = %(billing_status)s,
                            notes = %(notes)s,
                            updated_at = now()
                        where id = %(id)s
                        """,
                        values,
                    )

                if order_id is not None:
                    cur.execute(
                        "delete from raiox.invoice where exam_id = %s and status <> 'paid'",
                        (exam_id,),
                    )
                    self._ensure_order_invoice(cur, order_id, scheduled_at)
                    if current_order_id is not None and current_order_id != order_id:
                        self._ensure_order_invoice(cur, current_order_id, None)
                else:
                    self._ensure_invoice(cur, exam_id, price, scheduled_at)
                    if current_order_id is not None:
                        self._ensure_order_invoice(cur, current_order_id, None)
                self._ensure_call_ticket(cur, exam_id, scheduled_at)
                self._complete_call_ticket_if_needed(cur, exam_id, values["workflow_stage"])
                if not commit_on_exit:
                    sql = self._exam_base_query() + " where e.id = %s"
                    cur.execute(sql, (exam_id,))
                    row = cur.fetchone()
                    if not row:
                        raise ValueError("Exame nao encontrado.")
                    return self._decorate_exam_row(row)
            if commit_on_exit:
                active_conn.commit()
        return self.get_exam(exam_id)

    def list_exam_orders(self) -> list[dict[str, Any]]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        o.*,
                        p.full_name as patient_name,
                        count(e.id) as exam_count
                    from raiox.exam_order o
                    join raiox.patient p on p.id = o.patient_id
                    left join raiox.exam e on e.order_id = o.id
                    group by o.id, p.full_name
                    order by o.created_at desc, o.id desc
                    """
                )
                return list(cur.fetchall())

    def get_exam_order(self, order_id: int) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        o.*,
                        p.full_name as patient_name
                    from raiox.exam_order o
                    join raiox.patient p on p.id = o.patient_id
                    where o.id = %s
                    """,
                    (order_id,),
                )
                order_row = cur.fetchone()
                if not order_row:
                    raise ValueError("Ordem de exame nao encontrada.")

                sql = self._exam_base_query() + " where e.order_id = %s order by e.id"
                cur.execute(sql, (order_id,))
                order_row["items"] = [self._decorate_exam_row(row) for row in cur.fetchall()]
                order_row["exam_count"] = len(order_row["items"])
                return order_row

    def create_exam_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        patient_id = int(payload.get("patient_id") or 0)
        patient_name = (payload.get("patient_name") or "").strip()
        if not patient_id:
            if not patient_name:
                raise ValueError("Paciente e procedimentos sao obrigatorios.")

        items = payload.get("items") or []
        if not isinstance(items, list) or not items:
            raise ValueError("Lista de exames obrigatoria.")

        reference = (payload.get("reference") or "").strip() or None
        notes = (payload.get("notes") or "").strip() or None
        discount = Decimal(str(payload.get("discount") or "0"))
        if discount < 0:
            raise ValueError("Desconto invalido.")
        status = (payload.get("status") or "confirmed").strip().lower()[:24] or "confirmed"

        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                if not patient_id:
                    cur.execute(
                        """
                        insert into raiox.patient (full_name)
                        values (%s)
                        returning id
                        """,
                        (patient_name[:160],),
                    )
                    patient_id = cur.fetchone()["id"]
                cur.execute(
                    """
                    insert into raiox.exam_order (patient_id, reference, notes, discount, amount, net_amount, status)
                    values (%s, %s, %s, %s, 0, 0, %s)
                    returning id
                    """,
                    (patient_id, reference, notes, discount, status),
                )
                order_id = cur.fetchone()["id"]

                exams = []
                for item in items:
                    item_payload = dict(item)
                    item_payload["patient_id"] = patient_id
                    item_payload["order_id"] = order_id
                    exam = self.save_exam(item_payload, conn=conn, commit=False)
                    exams.append(exam)

                self._ensure_order_invoice(cur, order_id, None)
            conn.commit()
        return self.get_exam_order(order_id)

    def _ensure_exam_order_for_exam(self, cur: Any, exam_id: int, discount: Decimal = Decimal("0")) -> int:
        cur.execute(
            "select patient_id, order_id, scheduled_at from raiox.exam where id = %s",
            (exam_id,),
        )
        exam_row = cur.fetchone()
        if not exam_row:
            raise ValueError("Exame nao encontrado.")
        if exam_row.get("order_id"):
            order_id = int(exam_row["order_id"])
            cur.execute(
                """
                update raiox.exam_order
                set discount = %s,
                    status = case when status = 'budget' then 'confirmed' else status end,
                    updated_at = now()
                where id = %s and billing_status <> 'paid'
                """,
                (discount, order_id),
            )
            if cur.rowcount == 0:
                raise ValueError("Desfaca o pagamento antes de aplicar desconto nesta ordem.")
            return order_id

        cur.execute(
            """
            insert into raiox.exam_order (patient_id, reference, discount, status)
            values (%s, %s, %s, 'confirmed')
            returning id
            """,
            (exam_row["patient_id"], f"EXAME-{exam_id}", discount),
        )
        order_id = cur.fetchone()["id"]
        cur.execute("update raiox.exam set order_id = %s, updated_at = now() where id = %s", (order_id, exam_id))
        cur.execute("delete from raiox.invoice where exam_id = %s and status <> 'paid'", (exam_id,))
        self._ensure_order_invoice(cur, order_id, exam_row.get("scheduled_at"))
        return order_id

    def add_exam_order_item_from_exam(self, exam_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        discount = Decimal(str(payload.get("discount") or "0"))
        if discount < 0:
            raise ValueError("Desconto invalido.")
        procedure_id = int(payload.get("procedure_id") or 0)
        incidences_count = int(payload.get("incidences_count") or 1)
        price = payload.get("price")

        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                order_id = self._ensure_exam_order_for_exam(cur, exam_id, discount)
                if procedure_id:
                    cur.execute(
                        """
                        select patient_id, convenio_code, scheduled_at, priority, station_aet
                        from raiox.exam
                        where id = %s
                        """,
                        (exam_id,),
                    )
                    base_exam = cur.fetchone()
                    if not base_exam:
                        raise ValueError("Exame nao encontrado.")
                    self.save_exam(
                        {
                            "patient_id": base_exam["patient_id"],
                            "procedure_id": procedure_id,
                            "order_id": order_id,
                            "convenio_code": payload.get("convenio_code") or base_exam.get("convenio_code") or "PARTICULAR",
                            "incidences_count": incidences_count,
                            "price": price or 0,
                            "scheduled_at": payload.get("scheduled_at") or base_exam.get("scheduled_at"),
                            "priority": payload.get("priority") or base_exam.get("priority") or "ROUTINE",
                            "station_aet": base_exam.get("station_aet"),
                            "notes": payload.get("notes") or "",
                        },
                        conn=conn,
                        commit=False,
                    )
                self._ensure_order_invoice(cur, order_id, None)
            conn.commit()
        return self.get_exam_order(order_id)

    def mark_order_paid(self, order_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        payment_method = (payload.get("payment_method") or "dinheiro").strip().lower()[:32]
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute("select id from raiox.invoice where order_id = %s", (order_id,))
                invoice = cur.fetchone()
                if not invoice:
                    raise ValueError("Fatura de ordem nao encontrada.")
                invoice_id = invoice["id"]
                cur.execute(
                    """
                    update raiox.invoice
                    set status = 'paid',
                        paid_at = now(),
                        payment_method = %s,
                        updated_at = now()
                    where id = %s
                    """,
                    (payment_method, invoice_id),
                )
                cur.execute(
                    """
                    update raiox.exam_order
                    set billing_status = 'paid',
                        status = 'paid',
                        paid_at = now(),
                        payment_method = %s,
                        updated_at = now()
                    where id = %s
                    """,
                    (payment_method, order_id),
                )
                cur.execute(
                    """
                    update raiox.exam
                    set billing_status = 'paid',
                        updated_at = now()
                    where order_id = %s
                    """,
                    (order_id,),
                )
            conn.commit()
        return self.get_invoice(invoice_id)

    def delete_exam_order(self, order_id: int) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute("select id, billing_status from raiox.exam_order where id = %s", (order_id,))
                order_row = cur.fetchone()
                if not order_row:
                    raise ValueError("Orcamento nao encontrado.")
                if order_row.get("billing_status") == "paid":
                    raise ValueError("Orcamento pago nao pode ser excluido.")
                cur.execute("delete from raiox.exam where order_id = %s", (order_id,))
                deleted_exams = cur.rowcount or 0
                cur.execute("delete from raiox.exam_order where id = %s", (order_id,))
            conn.commit()
        return {"deleted": True, "order_id": order_id, "deleted_exams": deleted_exams}

    def build_exam_order_pdf(self, order_id: int) -> bytes:
        order = self.get_exam_order(order_id)
        company_header = [
            "CNPJ: 75.743.419/0005-66",
            "Razao Social: Laboratorio de Patologia Clinica Santa Terezinha Ltda - EPP",
            "Endereco: Av. Munhoz da Rocha, 1298 - Vila Sao Lourenco, Mandaguacu - PR, 87160-000",
            "Telefone: (44) 3245-3324",
        ]
        lines: list[str] = [
            f"Orcamento #{order.get('id')}",
            f"Paciente: {order.get('patient_name') or '-'}",
            f"Referencia: {order.get('reference') or '-'}",
            f"Status: {order.get('status') or '-'}",
            "",
            "Exames",
        ]
        for index, item in enumerate(order.get("items") or [], start=1):
            lines.append(
                f"{index}. {item.get('procedure_name') or '-'} | Incidencias: {item.get('incidences_count') or 1} | Valor: R$ {item.get('price') or 0}"
            )
        lines.extend(
            [
                "",
                f"Subtotal: R$ {order.get('amount') or 0}",
                f"Desconto: R$ {order.get('discount') or 0}",
                f"Total: R$ {order.get('net_amount') or 0}",
            ]
        )
        notes = (order.get("notes") or "").strip()
        if notes:
            lines.extend(["", "Observacoes", notes])
        return build_text_pdf(
            "Orcamento de exames",
            lines,
            subtitle="Laboratorio Santa Terezinha",
            header_lines=company_header,
            footer_lines=[
                "Av. Munhoz da Rocha, 1298 - Vila Sao Lourenco, Mandaguacu - PR, 87160-000",
                "Telefone: (44) 3245-3324",
            ],
            logo_path=self.settings.root_dir / "logo.png",
        )

    def _promote_exam_stage(self, cur: Any, exam_id: int, target_stage: str) -> None:
        cur.execute("select workflow_stage, worklist_status from raiox.exam where id = %s", (exam_id,))
        row = cur.fetchone()
        if not row:
            return
        next_stage = self._promote_stage(row.get("workflow_stage"), target_stage)
        if next_stage != self._normalize_stage(row.get("workflow_stage")):
            cur.execute(
                """
                update raiox.exam
                set workflow_stage = %s,
                    worklist_status = %s,
                    status = %s,
                    updated_at = now()
                where id = %s
                """,
                (
                    next_stage,
                    self._worklist_status_from_stage(next_stage, row.get("worklist_status") or "draft"),
                    self._exam_status_from_stage(next_stage),
                    exam_id,
                ),
            )

    def _pacs_worklist_payload(self, exam: dict[str, Any], pacs_status: str) -> dict[str, Any]:
        scheduled_at = exam.get("scheduled_at") or datetime.now()
        return {
            "patientid": (exam.get("external_patient_id") or f"RXP{exam['patient_id']:06d}")[:64],
            "patientname": (exam.get("patient_name") or "")[:128],
            "patientbd": format_dicom_date(exam.get("patient_birth_date")),
            "patientsex": (exam.get("patient_sex") or "")[:16],
            "referringphysician": (exam.get("referring_physician") or "")[:64],
            "accessionnumber": exam["accession_number"][:16],
            "medicalalerts": "",
            "reasonforprocedure": (exam.get("notes") or "")[:64],
            "currentlocation": self.settings.pacs_institution_name[:64],
            "studyinstanceuid": exam["study_instance_uid"][:64],
            "requestedproceduredescription": (exam.get("requested_description") or exam.get("procedure_name") or "")[:64],
            "modality": self._dicom_modality(exam.get("modality") or exam.get("procedure_modality") or ""),
            "institutionname": self.settings.pacs_institution_name[:64],
            "spsdate": format_dicom_date(scheduled_at),
            "spsstarttime": format_dicom_time(scheduled_at),
            "performingphysician": (exam.get("performing_physician") or "")[:64],
            "spsdescription": (exam.get("procedure_name") or "")[:64],
            "spsid": f"RXS{exam['id']:08d}"[:32],
            "spsstatus": pacs_status,
            "scheduledstation": (exam.get("station_aet") or self.settings.pacs_station_aet)[:16],
            "requestedprocedureid": self._worklist_requested_procedure_id(exam),
            "sopinstanceuid": build_uid(self.settings.rad_uid_root)[:64],
            "requestedprocedurepriority": (exam.get("priority") or "ROUTINE")[:8],
        }

    def _mirror_exam_to_pacs_worklist(
        self,
        cur: Any,
        exam: dict[str, Any],
        local_stage: str,
        event_type: str,
    ) -> tuple[bool, str, dict[str, Any]]:
        stage = self._normalize_stage(local_stage)
        payload = {"stage": stage, "accession_number": exam["accession_number"]}
        try:
            cur.execute("savepoint pacs_worklist_mirror")
            if stage == "removed":
                cur.execute(
                    """
                    delete from public.worklist
                    where accessionnumber = %s
                    """,
                    (exam["accession_number"],),
                )
                payload["mode"] = "delete"
            else:
                pacs_status = STAGE_TO_PACS_WORKLIST.get(stage, "SCHEDULED")
                payload = self._pacs_worklist_payload(exam, pacs_status)
                cur.execute(
                    """
                    insert into public.worklist (
                        patientid, patientname, patientbd, patientsex, referringphysician,
                        accessionnumber, medicalalerts, reasonforprocedure, currentlocation, studyinstanceuid,
                        requestedproceduredescription, modality, institutionname, spsdate, spsstarttime,
                        performingphysician, spsdescription, spsid, spsstatus, scheduledstation,
                        requestedprocedureid, sopinstanceuid, requestedprocedurepriority
                    ) values (
                        %(patientid)s, %(patientname)s, %(patientbd)s, %(patientsex)s, %(referringphysician)s,
                        %(accessionnumber)s, %(medicalalerts)s, %(reasonforprocedure)s, %(currentlocation)s, %(studyinstanceuid)s,
                        %(requestedproceduredescription)s, %(modality)s, %(institutionname)s, %(spsdate)s, %(spsstarttime)s,
                        %(performingphysician)s, %(spsdescription)s, %(spsid)s, %(spsstatus)s, %(scheduledstation)s,
                        %(requestedprocedureid)s, %(sopinstanceuid)s, %(requestedprocedurepriority)s
                    )
                    on conflict (accessionnumber) do update
                    set patientid = excluded.patientid,
                        patientname = excluded.patientname,
                        patientbd = excluded.patientbd,
                        patientsex = excluded.patientsex,
                        referringphysician = excluded.referringphysician,
                        medicalalerts = excluded.medicalalerts,
                        reasonforprocedure = excluded.reasonforprocedure,
                        currentlocation = excluded.currentlocation,
                        studyinstanceuid = excluded.studyinstanceuid,
                        requestedproceduredescription = excluded.requestedproceduredescription,
                        modality = excluded.modality,
                        institutionname = excluded.institutionname,
                        spsdate = excluded.spsdate,
                        spsstarttime = excluded.spsstarttime,
                        performingphysician = excluded.performingphysician,
                        spsdescription = excluded.spsdescription,
                        spsid = excluded.spsid,
                        spsstatus = excluded.spsstatus,
                        scheduledstation = excluded.scheduledstation,
                        requestedprocedureid = excluded.requestedprocedureid,
                        sopinstanceuid = excluded.sopinstanceuid,
                        requestedprocedurepriority = excluded.requestedprocedurepriority
                    """,
                    payload,
                )
            cur.execute("release savepoint pacs_worklist_mirror")
            return True, f"Espelho PACS atualizado para {stage}.", payload
        except Exception as exc:
            cur.execute("rollback to savepoint pacs_worklist_mirror")
            return False, f"Worklist local atualizada, mas o espelho PACS falhou: {exc}", payload

    def publish_exam_to_worklist(self, exam_id: int) -> dict[str, Any]:
        exam = self.get_exam(exam_id)
        local_stage = "scheduled" if exam.get("workflow_stage") in {"draft", "removed"} else self._normalize_stage(exam.get("workflow_stage"))
        local_worklist_status = self._worklist_status_from_stage(local_stage, exam.get("worklist_status") or "draft")
        if local_stage == "cancelled":
            raise ValueError("Exame cancelado. Use o kanban para reabrir antes de publicar novamente.")
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                if local_stage != self._normalize_stage(exam.get("workflow_stage")) or local_worklist_status != self._normalize_worklist_status(exam.get("worklist_status")):
                    cur.execute(
                        """
                        update raiox.exam
                        set worklist_status = %s,
                            workflow_stage = %s,
                            status = %s,
                            updated_at = now()
                        where id = %s
                        """,
                        (local_worklist_status, local_stage, self._exam_status_from_stage(local_stage), exam_id),
                    )
                mirror_success, mirror_message, mirror_payload = self._mirror_exam_to_pacs_worklist(
                    cur,
                    {**exam, "workflow_stage": local_stage, "worklist_status": local_worklist_status},
                    local_worklist_status,
                    "publish",
                )
                self._insert_sync_log(
                    cur,
                    exam_id,
                    "worklist",
                    "publish",
                    mirror_success,
                    mirror_message or "Exame publicado na worklist local.",
                    mirror_payload,
                )
            conn.commit()
        result = self.get_exam(exam_id)
        result["mirror_sync"] = {"success": mirror_success, "message": mirror_message}
        return result

    def remove_exam_from_worklist(self, exam_id: int) -> dict[str, Any]:
        exam = self.get_exam(exam_id)
        locked, reason = self._manual_transition_lock(exam)
        if locked:
            raise ValueError(reason)
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update raiox.exam
                    set worklist_status = 'removed',
                        workflow_stage = 'removed',
                        status = 'removed',
                        updated_at = now()
                    where id = %s
                    """,
                    (exam_id,),
                )
                self._complete_call_ticket_if_needed(cur, exam_id, "removed")
                mirror_success, mirror_message, mirror_payload = self._mirror_exam_to_pacs_worklist(
                    cur,
                    exam,
                    "removed",
                    "remove",
                )
                self._insert_sync_log(
                    cur,
                    exam_id,
                    "worklist",
                    "remove",
                    mirror_success,
                    mirror_message or "Exame removido da worklist local.",
                    mirror_payload,
                )
            conn.commit()
        result = self.get_exam(exam_id)
        result["mirror_sync"] = {"success": mirror_success, "message": mirror_message}
        return result

    def delete_exam(self, exam_id: int) -> dict[str, Any]:
        exam = self.get_exam(exam_id)
        study_uid = str(exam.get("study_instance_uid") or "").strip()
        accession_number = str(exam.get("accession_number") or "").strip()
        order_id = exam.get("order_id")
        attachment_rows: list[dict[str, Any]] = []
        object_file_paths: list[Path] = []

        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select file_path
                    from raiox.exam_attachment
                    where exam_id = %s
                    """,
                    (exam_id,),
                )
                attachment_rows = list(cur.fetchall())

                if study_uid:
                    cur.execute(
                        """
                        select filepath
                        from public.objects
                        where studyinstanceuid = %s
                        """,
                        (study_uid,),
                    )
                    object_file_paths = [Path(str(row.get("filepath") or "")) for row in cur.fetchall() if row.get("filepath")]

                    cur.execute("delete from public.objects where studyinstanceuid = %s", (study_uid,))
                    cur.execute("delete from public.series where studyinstanceuid = %s", (study_uid,))
                    cur.execute("delete from public.study where studyinstanceuid = %s", (study_uid,))
                    cur.execute("delete from public.reports where studyinstanceuid = %s", (study_uid,))

                if accession_number:
                    cur.execute("delete from public.worklist where accessionnumber = %s", (accession_number,))

                cur.execute("delete from raiox.exam where id = %s", (exam_id,))
                if order_id is not None:
                    cur.execute("select count(*) as exam_count from raiox.exam where order_id = %s", (order_id,))
                    order_count = int((cur.fetchone() or {}).get("exam_count") or 0)
                    if order_count:
                        self._ensure_order_invoice(cur, int(order_id), exam.get("scheduled_at"))
                    else:
                        cur.execute("select billing_status from raiox.exam_order where id = %s", (order_id,))
                        order_row = cur.fetchone()
                        if order_row and order_row.get("billing_status") != "paid":
                            cur.execute("delete from raiox.exam_order where id = %s", (order_id,))
            conn.commit()

        attachment_root = self.settings.runtime_root / "exam_attachments" / str(exam_id)
        if attachment_root.exists():
            shutil.rmtree(attachment_root, ignore_errors=True)

        pacs_study_root = Path(self.settings.pacs_imagebox_path) / study_uid if study_uid else None
        if pacs_study_root and pacs_study_root.exists():
            shutil.rmtree(pacs_study_root, ignore_errors=True)

        for file_path in object_file_paths:
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass

        return {
            "deleted": True,
            "exam_id": exam_id,
            "accession_number": accession_number,
            "study_instance_uid": study_uid,
            "attachments_removed": len(attachment_rows),
            "pacs_objects_removed": len(object_file_paths),
        }

    def list_worklist(self) -> dict[str, Any]:
        local_queue = [
            exam
            for exam in self.list_exams()
            if not self._is_archived_finalized(exam) and exam.get("order_status") != "budget"
        ][:100]
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select *
                    from public.worklist
                    order by spsdate desc nulls last, spsstarttime desc nulls last, accessionnumber desc
                    limit 100
                    """
                )
                worklist_rows = list(cur.fetchall())
        return {
            "items": worklist_rows,
            "local_exams": local_queue,
            "summary": {
                "local_active": sum(1 for exam in local_queue if exam.get("local_worklist_active")),
                "mirror_rows": len(worklist_rows),
                "executed": sum(1 for exam in local_queue if exam.get("workflow_stage") == "executed"),
                "closed": sum(1 for exam in local_queue if exam.get("workflow_stage") in {"finalized", "cancelled", "removed"}),
            },
        }

    def sync_exam_statuses(self) -> dict[str, Any]:
        exams = [
            exam
            for exam in self.list_exams()
            if not self._is_archived_finalized(exam) and exam.get("order_status") != "budget"
        ]
        updated = 0
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                for exam in exams:
                    live_status = exam["live_status"]
                    worklist_status = self._derive_worklist_status(exam)
                    report_status = exam.get("live_report_stage") or None
                    pacs_study_found = bool(exam.get("live_study_instance_uid"))
                    workflow_stage = self._recommended_stage_from_row(exam)
                    cur.execute(
                        """
                        update raiox.exam
                        set status = %s,
                            workflow_stage = %s,
                            worklist_status = %s,
                            pacs_study_found = %s,
                            pacs_report_status = %s,
                            billing_status = case
                                when billing_status = 'paid' then billing_status
                                when %s = 'reported' then 'ready'
                                else billing_status
                            end,
                            updated_at = now()
                        where id = %s and (
                            status is distinct from %s
                            or workflow_stage is distinct from %s
                            or worklist_status is distinct from %s
                            or pacs_study_found is distinct from %s
                            or pacs_report_status is distinct from %s
                        )
                        """,
                        (
                            live_status,
                            workflow_stage,
                            worklist_status,
                            pacs_study_found,
                            report_status,
                            live_status,
                            exam["id"],
                            live_status,
                            workflow_stage,
                            worklist_status,
                            pacs_study_found,
                            report_status,
                        ),
                    )
                    updated += cur.rowcount
                    self._complete_call_ticket_if_needed(cur, exam["id"], workflow_stage)
            conn.commit()
        return {"updated": updated, "total_exam_count": len(exams)}

    def update_exam_stage(self, exam_id: int, stage: str) -> dict[str, Any]:
        workflow_stage = self._normalize_stage(stage)
        if workflow_stage not in MANUAL_TRANSITION_STAGES:
            raise ValueError("Etapa nao pode ser movida manualmente no kanban.")
        exam = self.get_exam(exam_id)
        locked, reason = self._manual_transition_lock(exam)
        if locked:
            raise ValueError(reason)
        worklist_status = self._worklist_status_from_stage(workflow_stage, exam.get("worklist_status") or "draft")
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update raiox.exam
                    set workflow_stage = %s,
                        worklist_status = %s,
                        status = %s,
                        updated_at = now()
                    where id = %s
                    """,
                    (workflow_stage, worklist_status, self._exam_status_from_stage(workflow_stage), exam_id),
                )
                if cur.rowcount == 0:
                    raise ValueError("Exame nao encontrado.")
                self._complete_call_ticket_if_needed(cur, exam_id, workflow_stage)
                mirror_success, mirror_message, mirror_payload = self._mirror_exam_to_pacs_worklist(
                    cur,
                    exam,
                    workflow_stage,
                    "manual-stage",
                )
                self._insert_sync_log(
                    cur,
                    exam_id,
                    "worklist",
                    "manual-stage",
                    mirror_success,
                    mirror_message or f"Etapa manual atualizada para {workflow_stage}.",
                    mirror_payload,
                )
            conn.commit()
        result = self.get_exam(exam_id)
        result["mirror_sync"] = {"success": mirror_success, "message": mirror_message}
        return result

    def kanban_board(self) -> dict[str, Any]:
        exams = [
            exam
            for exam in self.list_exams()
            if not self._is_archived_finalized(exam) and exam.get("order_status") != "budget"
        ]
        grouped: dict[str, list[dict[str, Any]]] = {stage: [] for stage in WORKFLOW_STAGES}
        for exam in exams:
            grouped[self._normalize_stage(exam.get("workflow_stage"))].append(exam)
        return {
            "stages": [
                {
                    "key": stage,
                    "label": WORKFLOW_LABELS[stage],
                    "count": len(grouped[stage]),
                    "items": grouped[stage],
                }
                for stage in WORKFLOW_STAGES
            ]
        }

    def list_invoices(self) -> list[dict[str, Any]]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        i.id,
                        i.exam_id,
                        i.order_id,
                        i.invoice_number,
                        i.amount,
                        i.discount,
                        (i.amount - i.discount) as net_amount,
                        i.status,
                        i.due_date,
                        i.paid_at,
                        i.payment_method,
                        i.notes,
                        i.created_at,
                        i.updated_at,
                        e.accession_number,
                        e.status as exam_status,
                        e.workflow_stage,
                        o.reference as order_reference,
                        o.amount as order_amount,
                        o.discount as order_discount,
                        o.net_amount as order_net_amount,
                        p.full_name as patient_name,
                        proc.name as procedure_name
                    from raiox.invoice i
                    left join raiox.exam e on e.id = i.exam_id
                    left join raiox.exam_order o on o.id = i.order_id
                    left join raiox.patient p on p.id = coalesce(e.patient_id, o.patient_id)
                    left join raiox.procedure_catalog proc on proc.id = e.procedure_id
                    order by i.created_at desc, i.id desc
                    """
                )
                return list(cur.fetchall())

    def get_invoice(self, invoice_id: int) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        i.*,
                        e.accession_number,
                        e.workflow_stage,
                        o.reference as order_reference,
                        o.amount as order_amount,
                        o.discount as order_discount,
                        o.net_amount as order_net_amount,
                        p.full_name as patient_name,
                        proc.name as procedure_name
                    from raiox.invoice i
                    left join raiox.exam e on e.id = i.exam_id
                    left join raiox.exam_order o on o.id = i.order_id
                    left join raiox.patient p on p.id = coalesce(e.patient_id, o.patient_id)
                    left join raiox.procedure_catalog proc on proc.id = e.procedure_id
                    where i.id = %s
                    """,
                    (invoice_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError("Fatura nao encontrada.")
                row["net_amount"] = row["amount"] - row["discount"]
                return row

    def mark_invoice_paid(self, invoice_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        payment_method = (payload.get("payment_method") or "dinheiro").strip().lower()[:32]
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute("select exam_id, order_id from raiox.invoice where id = %s", (invoice_id,))
                existing = cur.fetchone()
                if not existing:
                    raise ValueError("Fatura nao encontrada.")
                cur.execute(
                    """
                    update raiox.invoice
                    set status = 'paid',
                        paid_at = now(),
                        payment_method = %s,
                        updated_at = now()
                    where id = %s
                    """,
                    (payment_method, invoice_id),
                )
                if existing.get("order_id") is not None:
                    cur.execute(
                        """
                        update raiox.exam_order
                        set billing_status = 'paid',
                            status = 'paid',
                            paid_at = now(),
                            payment_method = %s,
                            updated_at = now()
                        where id = %s
                        """,
                        (payment_method, existing["order_id"]),
                    )
                    cur.execute(
                        """
                        update raiox.exam
                        set billing_status = 'paid',
                            updated_at = now()
                        where order_id = %s
                        """,
                        (existing["order_id"],),
                    )
                elif existing.get("exam_id") is not None:
                    cur.execute(
                        """
                        update raiox.exam
                        set billing_status = 'paid',
                            updated_at = now()
                        where id = %s
                        """,
                        (existing["exam_id"],),
                    )
            conn.commit()
        return self.get_invoice(invoice_id)

    def reopen_invoice_payment(self, invoice_id: int) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute("select exam_id, order_id, status from raiox.invoice where id = %s", (invoice_id,))
                existing = cur.fetchone()
                if not existing:
                    raise ValueError("Fatura nao encontrada.")
                if existing.get("status") != "paid":
                    raise ValueError("A fatura ja esta em aberto.")
                cur.execute(
                    """
                    update raiox.invoice
                    set status = 'open',
                        paid_at = null,
                        payment_method = null,
                        updated_at = now()
                    where id = %s
                    """,
                    (invoice_id,),
                )
                if existing.get("order_id") is not None:
                    cur.execute(
                        """
                        update raiox.exam_order
                        set billing_status = 'pending',
                            status = case when status = 'paid' then 'confirmed' else status end,
                            paid_at = null,
                            payment_method = null,
                            updated_at = now()
                        where id = %s
                        """,
                        (existing["order_id"],),
                    )
                    cur.execute(
                        """
                        update raiox.exam
                        set billing_status = 'pending',
                            updated_at = now()
                        where order_id = %s
                        """,
                        (existing["order_id"],),
                    )
                elif existing.get("exam_id") is not None:
                    cur.execute(
                        """
                        update raiox.exam
                        set billing_status = 'pending',
                            updated_at = now()
                        where id = %s
                        """,
                        (existing["exam_id"],),
                    )
            conn.commit()
        return self.get_invoice(invoice_id)

    def finance_overview(self) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        count(*) as total_invoices,
                        count(*) filter (where status = 'open') as open_invoices,
                        count(*) filter (where status = 'paid') as paid_invoices,
                        coalesce(sum(discount), 0) as discount_total,
                        coalesce(sum(amount - discount), 0) as gross_total,
                        coalesce(sum(amount - discount) filter (where status = 'open'), 0) as open_total,
                        coalesce(sum(amount - discount) filter (where status = 'paid'), 0) as paid_total,
                        coalesce(sum(amount - discount) filter (
                            where paid_at >= date_trunc('month', now())
                        ), 0) as current_month_paid
                    from raiox.invoice
                    """
                )
                totals = cur.fetchone() or {}
                cur.execute(
                    """
                    select
                        to_char(coalesce(paid_at, created_at), 'YYYY-MM') as competency,
                        coalesce(sum(amount - discount), 0) as total
                    from raiox.invoice
                    group by 1
                    order by 1 desc
                    limit 12
                    """
                )
                monthly = list(cur.fetchall())
                cur.execute(
                    """
                    select
                        coalesce(nullif(payment_method, ''), 'dinheiro') as payment_method,
                        count(*) as total_invoices,
                        coalesce(sum(amount - discount), 0) as total_value
                    from raiox.invoice
                    where status = 'paid'
                    group by 1
                    order by total_value desc, payment_method asc
                    """
                )
                payment_methods = list(cur.fetchall())
        return {"totals": totals, "monthly": list(reversed(monthly)), "payment_methods": payment_methods}

    def _normalize_report_type(self, value: str | None) -> str:
        normalized = (value or "").strip().lower()
        for item in REPORT_CATALOG:
            if item["key"] == normalized:
                return normalized
        return REPORT_CATALOG[0]["key"]

    def _report_config(self, value: str | None) -> dict[str, str]:
        normalized = self._normalize_report_type(value)
        for item in REPORT_CATALOG:
            if item["key"] == normalized:
                return item
        return REPORT_CATALOG[0]

    def _format_brl(self, value: Any) -> str:
        amount = Decimal(str(value or 0)).quantize(Decimal("0.01"))
        text = f"{amount:,.2f}"
        return "R$ " + text.replace(",", "X").replace(".", ",").replace("X", ".")

    def _invoice_status_label(self, value: Any) -> str:
        key = str(value or "").strip().lower()
        return INVOICE_STATUS_LABELS.get(key, str(value or "-"))

    def _report_period_bounds(self, period_mode: str | None, period_value: str | None) -> tuple[datetime, datetime, str, str]:
        mode = (period_mode or "month").strip().lower()
        if mode == "day":
            reference = parse_date(period_value or "") or date.today()
            start = datetime.combine(reference, datetime.min.time())
            end = start + timedelta(days=1)
            return start, end, reference.strftime("%d/%m/%Y"), "day"

        candidate = (period_value or "").strip()
        if re.fullmatch(r"\d{4}-\d{2}", candidate):
            year, month = (int(part) for part in candidate.split("-"))
        else:
            today = date.today()
            year, month = today.year, today.month
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)
        return start, end, f"{month:02d}/{year}", "month"

    def build_report(self, report_type: str, filters: dict[str, Any]) -> dict[str, Any]:
        report_config = self._report_config(report_type)
        start_at, end_at, period_label, period_mode = self._report_period_bounds(
            filters.get("period_mode"),
            filters.get("period_value"),
        )
        convenio_code = self._normalize_convenio_code(filters.get("convenio_code") or "") if filters.get("convenio_code") else ""
        convenio_label = convenio_code.replace("_", " ").title() if convenio_code else ""
        try:
            patient_id = int(filters.get("patient_id") or 0) or None
        except (TypeError, ValueError):
            patient_id = None
        patient_label = ""
        if patient_id:
            try:
                patient_label = self.get_patient(patient_id).get("full_name") or ""
            except ValueError:
                patient_id = None
        commission_amounts = {
            self._normalize_convenio_code(item.get("code")): self._normalize_commission_amount(self._commission_amount_source(item), item.get("code"))
            for item in self.get_pricing_config().get("convenios") or []
        }

        def commission_amount_for(code: Any) -> Decimal:
            convenio = self._normalize_convenio_code(str(code or "PARTICULAR"))
            return commission_amounts.get(convenio, self._default_commission_amount(convenio))

        def commission_value(quantity: Any, amount: Decimal) -> Decimal:
            return (Decimal(str(quantity or 0)) * amount).quantize(Decimal("0.01"))

        where_clauses = [
            "coalesce(e.scheduled_at, e.created_at) >= %s",
            "coalesce(e.scheduled_at, e.created_at) < %s",
        ]
        query_params: list[Any] = [start_at, end_at]
        if convenio_code:
            where_clauses.append("upper(coalesce(e.convenio_code, 'PARTICULAR')) = %s")
            query_params.append(convenio_code)
        if patient_id:
            where_clauses.append("e.patient_id = %s")
            query_params.append(patient_id)
        where_sql = " and ".join(where_clauses)
        base_sql = f"""
            with base as (
                select
                    e.id as exam_id,
                    e.patient_id,
                    e.convenio_code,
                    e.incidences_count,
                    e.scheduled_at,
                    e.created_at,
                    e.price,
                    p.full_name as patient_name,
                    proc.name as procedure_name,
                    coalesce(e.scheduled_at, e.created_at) as report_at,
                    coalesce(
                        exam_invoice.status,
                        order_invoice.status,
                        case when e.billing_status = 'paid' then 'paid' else 'open' end
                    ) as invoice_status,
                    coalesce(nullif(exam_invoice.payment_method, ''), nullif(order_invoice.payment_method, ''), 'dinheiro') as payment_method,
                    coalesce(exam_invoice.amount, e.price, proc.default_price, 0) as amount,
                    case
                        when exam_invoice.id is not null then coalesce(exam_invoice.discount, 0)
                        when order_invoice.id is not null and coalesce(o.amount, 0) > 0 then
                            coalesce(order_invoice.discount, 0) * coalesce(e.price, 0) / o.amount
                        else 0
                    end as discount,
                    coalesce(exam_invoice.amount, e.price, proc.default_price, 0) - case
                        when exam_invoice.id is not null then coalesce(exam_invoice.discount, 0)
                        when order_invoice.id is not null and coalesce(o.amount, 0) > 0 then
                            coalesce(order_invoice.discount, 0) * coalesce(e.price, 0) / o.amount
                        else 0
                    end as net_amount
                from raiox.exam e
                join raiox.patient p on p.id = e.patient_id
                join raiox.procedure_catalog proc on proc.id = e.procedure_id
                left join raiox.exam_order o on o.id = e.order_id
                left join raiox.invoice exam_invoice on exam_invoice.exam_id = e.id
                left join raiox.invoice order_invoice on order_invoice.order_id = e.order_id
                where {where_sql}
            )
        """
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    base_sql
                    + """
                    select
                        count(*) as total_exams,
                        count(*) filter (where coalesce(invoice_status, 'open') = 'paid') as paid_exams,
                        count(*) filter (where coalesce(invoice_status, 'open') <> 'paid') as open_exams,
                        coalesce(sum(net_amount), 0) as total_value,
                        coalesce(sum(net_amount) filter (where coalesce(invoice_status, 'open') = 'paid'), 0) as paid_value,
                        coalesce(sum(net_amount) filter (where coalesce(invoice_status, 'open') <> 'paid'), 0) as open_value
                    from base
                    """,
                    query_params,
                )
                summary = cur.fetchone() or {}

                cur.execute(
                    base_sql
                    + """
                    select
                        coalesce(nullif(payment_method, ''), 'dinheiro') as payment_method,
                        count(*) as total_exams,
                        coalesce(sum(net_amount), 0) as total_value
                    from base
                    where coalesce(invoice_status, 'open') = 'paid'
                    group by 1
                    order by total_value desc, payment_method asc
                    """,
                    query_params,
                )
                payment_methods = list(cur.fetchall())

                if report_config["key"] == "financeiro":
                    group_label = "Forma de pagamento"
                    cur.execute(
                        base_sql
                        + """
                        select
                            coalesce(nullif(payment_method, ''), 'dinheiro') as group_key,
                            count(*) as total_exams,
                            coalesce(sum(net_amount), 0) as total_value,
                            count(*) as paid_exams,
                            coalesce(sum(net_amount), 0) as paid_value,
                            0 as open_exams,
                            0 as open_value
                        from base
                        where coalesce(invoice_status, 'open') = 'paid'
                        group by 1
                        order by total_value desc, group_key asc
                        """,
                        query_params,
                    )
                    grouped = list(cur.fetchall())
                elif report_config["key"] == "convenio":
                    group_label = "Convenio"
                    cur.execute(
                        base_sql
                        + """
                        select
                            upper(coalesce(nullif(convenio_code, ''), 'PARTICULAR')) as group_key,
                            count(*) as total_exams,
                            coalesce(sum(net_amount), 0) as total_value,
                            count(*) filter (where coalesce(invoice_status, 'open') = 'paid') as paid_exams,
                            coalesce(sum(net_amount) filter (where coalesce(invoice_status, 'open') = 'paid'), 0) as paid_value,
                            count(*) filter (where coalesce(invoice_status, 'open') <> 'paid') as open_exams,
                            coalesce(sum(net_amount) filter (where coalesce(invoice_status, 'open') <> 'paid'), 0) as open_value
                        from base
                        group by 1
                        order by total_value desc, group_key asc
                        """,
                        query_params,
                    )
                    grouped = list(cur.fetchall())
                elif report_config["key"] == "paciente":
                    group_label = "Paciente"
                    cur.execute(
                        base_sql
                        + """
                        select
                            patient_id as group_key,
                            patient_name as group_name,
                            count(*) as total_exams,
                            coalesce(sum(net_amount), 0) as total_value,
                            count(*) filter (where coalesce(invoice_status, 'open') = 'paid') as paid_exams,
                            coalesce(sum(net_amount) filter (where coalesce(invoice_status, 'open') = 'paid'), 0) as paid_value,
                            count(*) filter (where coalesce(invoice_status, 'open') <> 'paid') as open_exams,
                            coalesce(sum(net_amount) filter (where coalesce(invoice_status, 'open') <> 'paid'), 0) as open_value
                        from base
                        group by patient_id, patient_name
                        order by total_value desc, group_name asc
                        """,
                        query_params,
                    )
                    grouped = list(cur.fetchall())
                else:
                    group_label = "Convenio"
                    cur.execute(
                        base_sql
                        + """
                        select
                            upper(coalesce(nullif(convenio_code, ''), 'PARTICULAR')) as group_key,
                            count(*) as total_exams,
                            coalesce(sum(net_amount), 0) as total_value,
                            count(*) filter (where coalesce(invoice_status, 'open') = 'paid') as paid_exams,
                            coalesce(sum(net_amount) filter (where coalesce(invoice_status, 'open') = 'paid'), 0) as paid_value,
                            count(*) filter (where coalesce(invoice_status, 'open') <> 'paid') as open_exams,
                            coalesce(sum(net_amount) filter (where coalesce(invoice_status, 'open') <> 'paid'), 0) as open_value
                        from base
                        group by 1
                        order by total_value desc, group_key asc
                        """,
                        query_params,
                    )
                    grouped = list(cur.fetchall())

                cur.execute(
                    base_sql
                    + """
                    select
                        exam_id,
                        report_at,
                        patient_name,
                        procedure_name,
                        upper(coalesce(nullif(convenio_code, ''), 'PARTICULAR')) as convenio_code,
                        coalesce(invoice_status, 'open') as invoice_status,
                        coalesce(nullif(payment_method, ''), 'dinheiro') as payment_method,
                        net_amount
                    from base
                    order by report_at desc, exam_id desc
                    limit 120
                    """,
                    query_params,
                )
                details = list(cur.fetchall())

        group_rows: list[dict[str, Any]] = []
        for row in grouped:
            if report_config["key"] == "paciente":
                label = row.get("group_name") or f"Paciente {row.get('group_key')}"
            else:
                key = str(row.get("group_key") or "").strip().lower()
                label = PAYMENT_METHOD_LABELS.get(key, str(row.get("group_key") or "").replace("_", " ").title())
            amount = commission_amount_for(row.get("group_key"))
            group_row = {
                "key": row.get("group_key"),
                "label": label,
                "total_exams": row.get("total_exams", 0),
                "total_value": row.get("total_value", 0),
                "paid_exams": row.get("paid_exams", 0),
                "paid_value": row.get("paid_value", 0),
                "open_exams": row.get("open_exams", 0),
                "open_value": row.get("open_value", 0),
            }
            if report_config["key"] == "comissao_tecnico":
                group_row.update({
                    "commission_amount": amount,
                    "commission_rate": amount,
                    "commission_value": commission_value(row.get("total_exams", 0), amount),
                    "paid_commission_value": commission_value(row.get("paid_exams", 0), amount),
                    "open_commission_value": commission_value(row.get("open_exams", 0), amount),
                })
            group_rows.append(group_row)

        detail_rows = []
        for row in details:
            amount = commission_amount_for(row.get("convenio_code"))
            detail_row = {
                "exam_id": row.get("exam_id"),
                "report_at": row.get("report_at"),
                "patient_name": row.get("patient_name"),
                "procedure_name": row.get("procedure_name"),
                "convenio_code": row.get("convenio_code"),
                "invoice_status": row.get("invoice_status"),
                "invoice_status_label": self._invoice_status_label(row.get("invoice_status")),
                "payment_method": PAYMENT_METHOD_LABELS.get(
                    str(row.get("payment_method") or "").strip().lower(),
                    str(row.get("payment_method") or "").title(),
                ),
                "net_amount": row.get("net_amount"),
            }
            if report_config["key"] == "comissao_tecnico":
                detail_row.update({
                    "commission_amount": amount,
                    "commission_rate": amount,
                    "commission_value": commission_value(1, amount),
                    "commission_formula": f"1 exame x {self._format_brl(amount)} = {self._format_brl(commission_value(1, amount))}",
                })
            detail_rows.append(detail_row)

        total_value = summary.get("total_value", 0) or 0
        paid_value = summary.get("paid_value", 0) or 0
        open_value = summary.get("open_value", 0) or 0
        total_commission_value = sum((Decimal(str(row.get("commission_value") or 0)) for row in group_rows), Decimal("0")).quantize(Decimal("0.01"))
        paid_commission_value = sum((Decimal(str(row.get("paid_commission_value") or 0)) for row in group_rows), Decimal("0")).quantize(Decimal("0.01"))
        open_commission_value = sum((Decimal(str(row.get("open_commission_value") or 0)) for row in group_rows), Decimal("0")).quantize(Decimal("0.01"))
        filter_parts = [f"Periodo: {period_label}"]
        if convenio_label:
            filter_parts.append(f"Convenio: {convenio_label}")
        if patient_label:
            filter_parts.append(f"Paciente: {patient_label}")
        filter_summary = " | ".join(filter_parts)

        pdf_lines = [
            f"Periodo: {period_label}",
            f"Filtros: {filter_summary}",
            "-" * 92,
            "",
            "Resumo financeiro",
            f"Exames: {summary.get('total_exams', 0)}",
            f"Pagos: {summary.get('paid_exams', 0)} | {self._format_brl(paid_value)}",
            f"Em aberto: {summary.get('open_exams', 0)} | {self._format_brl(open_value)}",
            f"Valor total: {self._format_brl(total_value)}",
            "-" * 92,
            "",
            f"Agrupamento por {group_label}",
        ]
        if report_config["key"] == "comissao_tecnico":
            pdf_lines.extend([
                f"Comissao total: {self._format_brl(total_commission_value)}",
                f"Comissao sobre pagos: {self._format_brl(paid_commission_value)}",
                f"Comissao em aberto: {self._format_brl(open_commission_value)}",
                "",
            ])
        for row in group_rows:
            if report_config["key"] == "comissao_tecnico":
                pdf_lines.append(
                    f"- {row['label']}: {row['total_exams']} exames | Base {self._format_brl(row['total_value'])} | "
                    f"{self._format_brl(row['commission_amount'])} por exame | Comissao {self._format_brl(row['commission_value'])}"
                )
            else:
                pdf_lines.append(f"- {row['label']}: {row['total_exams']} exames | {self._format_brl(row['total_value'])}")
        if not group_rows:
            pdf_lines.append("- Sem registros no periodo.")
        pdf_lines.extend(["", "Formas de pagamento"])
        for row in payment_methods:
            label = PAYMENT_METHOD_LABELS.get(
                str(row.get("payment_method") or "").strip().lower(),
                str(row.get("payment_method") or "").title(),
            )
            pdf_lines.append(f"- {label}: {row.get('total_exams', 0)} exames | {self._format_brl(row.get('total_value', 0))}")
        if not payment_methods:
            pdf_lines.append("- Sem pagamentos liquidados no periodo.")
        details_header = "Data | Paciente | Procedimento | Convenio | Status | Forma | Valor"
        if report_config["key"] == "comissao_tecnico":
            details_header += " | Valor fixo | Comissao"
        pdf_lines.extend(["-" * 92, "", "Detalhes", details_header, "-" * 92])
        pdf_details = detail_rows[:40]
        for row in pdf_details:
            report_date = row.get("report_at")
            if isinstance(report_date, datetime):
                report_date_text = report_date.strftime("%d/%m/%Y %H:%M")
            elif isinstance(report_date, date):
                report_date_text = report_date.strftime("%d/%m/%Y")
            else:
                report_date_text = str(report_date or "-")
            line_parts = [
                report_date_text,
                str(row.get("patient_name") or "-"),
                str(row.get("procedure_name") or "-"),
                str(row.get("convenio_code") or "-"),
                str(row.get("invoice_status_label") or "-"),
                str(row.get("payment_method") or "-"),
                self._format_brl(row.get("net_amount", 0)),
            ]
            if report_config["key"] == "comissao_tecnico":
                line_parts.extend([self._format_brl(row.get("commission_amount", 0)), self._format_brl(row.get("commission_value", 0))])
            pdf_lines.append(" | ".join(line_parts))
        if len(detail_rows) > len(pdf_details):
            pdf_lines.append(f"... mais {len(detail_rows) - len(pdf_details)} exames nao exibidos")

        return {
            "report_type": report_config["key"],
            "title": report_config["label"],
            "description": report_config["description"],
            "group_label": group_label,
            "period_mode": period_mode,
            "period_label": period_label,
            "filters": {
                "period_mode": period_mode,
                "period_value": filters.get("period_value") or "",
                "period_label": period_label,
                "convenio_code": convenio_code,
                "convenio_label": convenio_label,
                "patient_id": patient_id,
                "patient_label": patient_label,
                "summary_label": filter_summary,
            },
            "summary": {
                "total_exams": summary.get("total_exams", 0),
                "paid_exams": summary.get("paid_exams", 0),
                "open_exams": summary.get("open_exams", 0),
                "total_value": total_value,
                "paid_value": paid_value,
                "open_value": open_value,
                "commission_value": total_commission_value if report_config["key"] == "comissao_tecnico" else None,
                "paid_commission_value": paid_commission_value if report_config["key"] == "comissao_tecnico" else None,
                "open_commission_value": open_commission_value if report_config["key"] == "comissao_tecnico" else None,
            },
            "payment_methods": [
                {
                    "payment_method": row.get("payment_method"),
                    "label": PAYMENT_METHOD_LABELS.get(
                        str(row.get("payment_method") or "").strip().lower(),
                        str(row.get("payment_method") or "").title(),
                    ),
                    "total_exams": row.get("total_exams", 0),
                    "total_value": row.get("total_value", 0),
                }
                for row in payment_methods
            ],
            "grouped": group_rows,
            "details": detail_rows,
            "pdf_lines": pdf_lines,
        }

    def build_report_pdf(self, report: dict[str, Any]) -> bytes:
        subtitle = report.get("filters", {}).get("summary_label") or report.get("description") or ""
        company_header = [
            "CNPJ: 75.743.419/0005-66",
            "Razao Social: Laboratorio de Patologia Clinica Santa Terezinha Ltda - EPP",
            "Endereco: Av. Munhoz da Rocha, 1298 - Vila Sao Lourenco, Mandaguacu - PR, 87160-000",
            "Telefone: (44) 3245-3324",
        ]
        company_footer = [
            "Av. Munhoz da Rocha, 1298 - Vila Sao Lourenco, Mandaguacu - PR, 87160-000",
            "Telefone: (44) 3245-3324",
        ]
        return build_text_pdf(
            f"Relatorio {report.get('title') or 'Financeiro'}",
            report.get("pdf_lines") or [],
            subtitle=subtitle,
            header_lines=company_header,
            footer_lines=company_footer,
            logo_path=self.settings.root_dir / "logo.png",
        )

    def _conversation_query(self) -> str:
        return """
            select
                m.id,
                m.sender_operator_id,
                m.recipient_operator_id,
                m.body,
                m.read_at,
                m.created_at,
                s.name as sender_name,
                r.name as recipient_name
            from raiox.chat_message m
            join raiox.operator s on s.id = m.sender_operator_id
            join raiox.operator r on r.id = m.recipient_operator_id
        """

    def chat_conversation(self, operator_id: int, contact_id: int, limit: int = 100) -> list[dict[str, Any]]:
        sql = self._conversation_query() + """
            where
                (m.sender_operator_id = %s and m.recipient_operator_id = %s)
                or
                (m.sender_operator_id = %s and m.recipient_operator_id = %s)
            order by m.created_at asc
            limit %s
        """
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (operator_id, contact_id, contact_id, operator_id, limit))
                messages = list(cur.fetchall())
        self.mark_chat_read(operator_id, contact_id)
        return messages

    def send_chat_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        sender_id = int(payload.get("sender_operator_id") or 0)
        recipient_id = int(payload.get("recipient_operator_id") or 0)
        body = (payload.get("body") or "").strip()
        if not sender_id or not recipient_id:
            raise ValueError("Remetente e destinatario sao obrigatorios.")
        if not body:
            raise ValueError("Mensagem vazia.")
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into raiox.chat_message (sender_operator_id, recipient_operator_id, body)
                    values (%s, %s, %s)
                    returning id
                    """,
                    (sender_id, recipient_id, body),
                )
                message_id = cur.fetchone()["id"]
            conn.commit()
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(self._conversation_query() + " where m.id = %s", (message_id,))
                return cur.fetchone()

    def mark_chat_read(self, operator_id: int, contact_id: int) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update raiox.chat_message
                    set read_at = now()
                    where recipient_operator_id = %s
                      and sender_operator_id = %s
                      and read_at is null
                    """,
                    (operator_id, contact_id),
                )
                total = cur.rowcount
            conn.commit()
        return {"updated": total}

    def chat_unread(self, operator_id: int) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select sender_operator_id as contact_id, count(*) as total
                    from raiox.chat_message
                    where recipient_operator_id = %s and read_at is null
                    group by sender_operator_id
                    """,
                    (operator_id,),
                )
                rows = list(cur.fetchall())
        counts = {str(row["contact_id"]): int(row["total"]) for row in rows}
        return {"counts": counts, "total": sum(counts.values())}

    def recent_messages(self, limit: int = 6) -> list[dict[str, Any]]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(self._conversation_query() + " order by m.created_at desc limit %s", (limit,))
                return list(cur.fetchall())

    def list_cameras(self) -> list[dict[str, Any]]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select *
                    from raiox.camera
                    order by enabled desc, name asc
                    """
                )
                rows = list(cur.fetchall())
        status_map = self.camera_runtime.status_map(rows) if self.camera_runtime else {}
        for row in rows:
            runtime = status_map.get(int(row["id"]), {})
            row["status"] = runtime.get("status", "ready" if row.get("enabled") else "disabled")
            row["stream_url"] = runtime.get("stream_url", row.get("source_url"))
            row["runtime_error"] = runtime.get("error")
        return rows

    def get_camera(self, camera_id: int) -> dict[str, Any]:
        for camera in self.list_cameras():
            if int(camera["id"]) == camera_id:
                return camera
        raise ValueError("Camera nao encontrada.")

    def save_camera(self, payload: dict[str, Any], camera_id: int | None = None) -> dict[str, Any]:
        name = (payload.get("name") or "").strip()
        mode = (payload.get("mode") or "rtsp").strip().lower()
        source_url = (payload.get("source_url") or "").strip()
        if not name or not source_url:
            raise ValueError("Nome e URL da camera sao obrigatorios.")
        if mode not in {"rtsp", "hls"}:
            raise ValueError("Modo da camera invalido.")
        values = {
            "name": name[:120],
            "mode": mode,
            "source_url": source_url,
            "transport": (payload.get("transport") or "tcp").strip().lower()[:8] or "tcp",
            "enabled": parse_bool(payload.get("enabled"), True),
        }
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                if camera_id is None:
                    cur.execute(
                        """
                        insert into raiox.camera (name, mode, source_url, transport, enabled)
                        values (%(name)s, %(mode)s, %(source_url)s, %(transport)s, %(enabled)s)
                        returning id
                        """,
                        values,
                    )
                    camera_id = cur.fetchone()["id"]
                else:
                    values["id"] = camera_id
                    cur.execute(
                        """
                        update raiox.camera
                        set name = %(name)s,
                            mode = %(mode)s,
                            source_url = %(source_url)s,
                            transport = %(transport)s,
                            enabled = %(enabled)s,
                            updated_at = now()
                        where id = %(id)s
                        """,
                        values,
                    )
                    if cur.rowcount == 0:
                        raise ValueError("Camera nao encontrada.")
            conn.commit()
        return self.get_camera(camera_id)

    def delete_camera(self, camera_id: int) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from raiox.camera where id = %s", (camera_id,))
                if cur.rowcount == 0:
                    raise ValueError("Camera nao encontrada.")
            conn.commit()
        if self.camera_runtime:
            self.camera_runtime.remove_camera(camera_id)
        return {"ok": True}

    def camera_overview(self) -> dict[str, Any]:
        cameras = self.list_cameras()
        counts = defaultdict(int)
        for camera in cameras:
            counts[str(camera.get("status") or "ready")] += 1
        return {
            "items": cameras,
            "summary": {
                "total": len(cameras),
                "streaming": counts["streaming"],
                "ready": counts["ready"],
                "starting": counts["starting"],
                "error": counts["error"],
                "disabled": counts["disabled"],
            },
        }

    def list_pacs_studies(self, limit: int = 50) -> list[dict[str, Any]]:
        return list_pacs_catalog_studies(self.database, limit=limit)

    def get_pacs_study(self, study_instance_uid: str) -> dict[str, Any]:
        payload = pacs_study_detail(self.database, study_instance_uid)
        if not payload:
            raise ValueError("Estudo PACS nao encontrado.")
        return payload

    def _normalize_report_status(self, value: str | None, default: str = "draft") -> str:
        status = (value or default).strip().lower()
        return status if status in {"draft", "assigned", "preliminary", "final"} else default

    def _derive_report_status(self, report_row: dict[str, Any] | None, pacs_row: dict[str, Any] | None) -> str:
        if report_row and self._normalize_report_status(report_row.get("status")) != "draft":
            return self._normalize_report_status(report_row.get("status"))
        if pacs_row:
            if pacs_row.get("final"):
                return "final"
            if pacs_row.get("preliminary"):
                return "preliminary"
            if pacs_row.get("assigned"):
                return "assigned"
        if report_row:
            return self._normalize_report_status(report_row.get("status"))
        return "draft"

    def _report_flags(self, status: str) -> tuple[int, str | None, str | None, str | None]:
        normalized = self._normalize_report_status(status)
        if normalized == "final":
            return 30, "Y", "Y", "Y"
        if normalized == "preliminary":
            return 20, "Y", "Y", None
        if normalized == "assigned":
            return 10, "Y", None, None
        return 0, None, None, None

    def _resolve_exam_study_uid(self, exam: dict[str, Any]) -> str:
        preferred = [
            exam.get("live_study_instance_uid"),
            exam.get("study_instance_uid"),
        ]
        for value in preferred:
            text = str(value or "").strip()
            if text:
                return text
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select studyinstanceuid
                    from public.study
                    where accessionnumber = %s
                    order by studydate desc nulls last, studytime desc nulls last
                    limit 1
                    """,
                    (exam.get("accession_number"),),
                )
                row = cur.fetchone()
        return str((row or {}).get("studyinstanceuid") or "").strip()

    def _report_snapshot(self, exam_id: int, study_instance_uid: str) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select *
                    from raiox.medical_report
                    where exam_id = %s
                    """,
                    (exam_id,),
                )
                report_row = cur.fetchone()
                pacs_row = None
                if study_instance_uid:
                    cur.execute(
                        """
                        select *
                        from public.reports
                        where studyinstanceuid = %s
                        """,
                        (study_instance_uid,),
                    )
                    pacs_row = cur.fetchone()

        return {
            "exam_id": exam_id,
            "study_instance_uid": study_instance_uid or (report_row or {}).get("study_instance_uid"),
            "doctor_name": (report_row or {}).get("doctor_name") or (pacs_row or {}).get("username") or "",
            "status": self._derive_report_status(report_row, pacs_row),
            "title": (report_row or {}).get("title") or "",
            "body": (report_row or {}).get("body") or "",
            "impression": (report_row or {}).get("impression") or "",
            "signed_at": (report_row or {}).get("signed_at"),
            "updated_at": (report_row or {}).get("updated_at"),
            "pacs_flags": {
                "assigned": bool((pacs_row or {}).get("assigned")),
                "preliminary": bool((pacs_row or {}).get("preliminary")),
                "final": bool((pacs_row or {}).get("final")),
                "status_code": (pacs_row or {}).get("status"),
            },
        }

    def _attachments_root(self, exam_id: int) -> Path:
        root = self.settings.runtime_root / "exam_attachments" / str(exam_id)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _safe_filename(self, name: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "").strip()).strip(".-")
        return cleaned[:180] or "arquivo"

    def _delete_attachments_by_ids(self, attachment_ids: list[int]) -> None:
        valid_ids = [int(item) for item in attachment_ids if int(item or 0) > 0]
        if not valid_ids:
            return
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "delete from raiox.exam_attachment where id = any(%s)",
                    (valid_ids,),
                )
            conn.commit()

    def list_exam_attachments(self, exam_id: int) -> list[dict[str, Any]]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select *
                    from raiox.exam_attachment
                    where exam_id = %s
                    order by created_at desc, id desc
                    """,
                    (exam_id,),
                )
                rows = list(cur.fetchall())
        missing_ids: list[int] = []
        available_rows: list[dict[str, Any]] = []
        for row in rows:
            mime = str(row.get("mime_type") or "").strip().lower()
            row["is_image"] = mime.startswith("image/")
            row["is_available"] = Path(str(row.get("file_path") or "")).exists()
            if not row["is_available"]:
                missing_ids.append(int(row["id"]))
                continue
            available_rows.append(row)
        if missing_ids:
            self._delete_attachments_by_ids(missing_ids)
        return available_rows

    def get_exam_attachment(self, attachment_id: int) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select *
                    from raiox.exam_attachment
                    where id = %s
                    """,
                    (attachment_id,),
                )
                row = cur.fetchone()
        if not row:
            raise ValueError("Anexo do exame nao encontrado.")
        if not Path(str(row.get("file_path") or "")).exists():
            self._delete_attachments_by_ids([int(row["id"])])
            raise ValueError("Anexo do exame removido porque o arquivo nao existe mais.")
        return row

    def get_pacs_object(self, sop_instance_uid: str) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select *
                    from public.objects
                    where sopinstanceuid = %s
                    """,
                    (sop_instance_uid,),
                )
                row = cur.fetchone()
        if not row:
            raise ValueError("Objeto DICOM nao encontrado.")
        return row

    def _sanitize_workspace_payload(self, workspace: dict[str, Any]) -> dict[str, Any]:
        attachments = []
        for item in workspace.get("attachments") or []:
            cleaned = dict(item)
            cleaned.pop("file_path", None)
            attachments.append(cleaned)

        pacs = workspace.get("pacs") or {}
        study = dict(pacs.get("study") or {})
        study.pop("studypath", None)
        series = []
        for item in pacs.get("series") or []:
            cleaned = dict(item)
            cleaned.pop("seriespath", None)
            series.append(cleaned)
        instances = []
        for item in pacs.get("instances") or []:
            cleaned = dict(item)
            cleaned.pop("filepath", None)
            instances.append(cleaned)

        return {
            **workspace,
            "attachments": attachments,
            "pacs": {
                "study": study or None,
                "series": series,
                "instances": instances,
            },
        }

    def get_exam_workspace(self, exam_id: int) -> dict[str, Any]:
        exam = self.get_exam(exam_id)
        study_instance_uid = self._resolve_exam_study_uid(exam)
        pacs_payload = pacs_study_detail(self.database, study_instance_uid) if study_instance_uid else None
        return self._sanitize_workspace_payload({
            "exam": exam,
            "study_instance_uid": study_instance_uid,
            "report": self._report_snapshot(exam_id, study_instance_uid),
            "share_suggestion": self.suggest_share_credentials(patient_id=int(exam["patient_id"])),
            "attachments": self.list_exam_attachments(exam_id),
            "pacs": pacs_payload or {"study": None, "series": [], "instances": []},
        })

    def save_medical_report(self, exam_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        exam = self.get_exam(exam_id)
        submitted_status = self._normalize_report_status(payload.get("status"))
        doctor_name = (payload.get("doctor_name") or "").strip()[:120]
        title = (payload.get("title") or "").strip()[:160]
        body = (payload.get("body") or "").strip()
        impression = (payload.get("impression") or "").strip()
        study_instance_uid = self._resolve_exam_study_uid(exam) or str(exam.get("study_instance_uid") or "").strip()
        has_report_content = any([doctor_name, title, body, impression])
        report_is_complete = bool(body and impression)
        report_status = "final" if submitted_status == "draft" and report_is_complete else submitted_status
        signed_at = datetime.now() if report_status == "final" else None

        current_stage = self._normalize_stage(exam.get("workflow_stage"))
        if report_status == "final":
            workflow_stage = self._promote_stage(current_stage, "finalized")
        elif report_status in {"assigned", "preliminary"} or has_report_content:
            workflow_stage = self._promote_stage(current_stage, "reporting")
        else:
            workflow_stage = current_stage

        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into raiox.medical_report (
                        exam_id, study_instance_uid, doctor_name, status, title, body, impression, signed_at
                    ) values (
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    on conflict (exam_id) do update
                    set study_instance_uid = excluded.study_instance_uid,
                        doctor_name = excluded.doctor_name,
                        status = excluded.status,
                        title = excluded.title,
                        body = excluded.body,
                        impression = excluded.impression,
                        signed_at = excluded.signed_at,
                        updated_at = now()
                    """,
                    (
                        exam_id,
                        study_instance_uid or None,
                        doctor_name or None,
                        report_status,
                        title or None,
                        body or None,
                        impression or None,
                        signed_at,
                    ),
                )

                if report_status != "draft" and study_instance_uid:
                    status_code, assigned, preliminary, final_flag = self._report_flags(report_status)
                    cur.execute(
                        """
                        insert into public.reports (
                            studyinstanceuid, username, status, assigned, preliminary, final, addendum
                        ) values (
                            %s, %s, %s, %s, %s, %s, %s
                        )
                        on conflict (studyinstanceuid) do update
                        set username = excluded.username,
                            status = excluded.status,
                            assigned = excluded.assigned,
                            preliminary = excluded.preliminary,
                            final = excluded.final
                        """,
                        (
                            study_instance_uid,
                            doctor_name[:16] or None,
                            status_code,
                            assigned,
                            preliminary,
                            final_flag,
                            None,
                        ),
                    )

                cur.execute(
                    """
                    update raiox.exam
                    set workflow_stage = %s,
                        worklist_status = %s,
                        status = %s,
                        pacs_report_status = %s,
                        updated_at = now()
                    where id = %s
                    """,
                    (
                        workflow_stage,
                        self._worklist_status_from_stage(workflow_stage, exam.get("worklist_status") or "draft"),
                        self._exam_status_from_stage(workflow_stage),
                        None if report_status == "draft" else report_status,
                        exam_id,
                    ),
                )
            conn.commit()
        return self.get_exam_workspace(exam_id)

    def _share_exam_ids(self, share: dict[str, Any]) -> list[int]:
        if share.get("scope_type") == "exam" and share.get("exam_id"):
            return [int(share["exam_id"])]
        if share.get("scope_type") != "patient" or not share.get("patient_id"):
            return []
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select id
                    from raiox.exam
                    where patient_id = %s
                    order by coalesce(scheduled_at, created_at) desc, id desc
                    """,
                    (share["patient_id"],),
                )
                return [int(row["id"]) for row in cur.fetchall()]

    def _serialize_share(self, share: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": share["id"],
            "slug": share["slug"],
            "scope_type": share["scope_type"],
            "patient_id": share.get("patient_id"),
            "exam_id": share.get("exam_id"),
            "username": share["username"],
            "note": share.get("note"),
            "expires_at": share.get("expires_at"),
            "active": bool(share.get("active")),
            "last_login_at": share.get("last_login_at"),
            "created_at": share.get("created_at"),
        }

    def list_share_accesses(self, exam_id: int | None = None, patient_id: int | None = None) -> list[dict[str, Any]]:
        clauses = ["1 = 1"]
        params: list[Any] = []
        if exam_id:
            clauses.append("(exam_id = %s or patient_id = (select patient_id from raiox.exam where id = %s))")
            params.extend([exam_id, exam_id])
        elif patient_id:
            clauses.append("patient_id = %s")
            params.append(patient_id)
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    select *
                    from raiox.share_access
                    where {' and '.join(clauses)}
                    order by created_at desc, id desc
                    """,
                    params,
                )
                rows = list(cur.fetchall())
        return [self._serialize_share(row) for row in rows]

    def create_share_access(self, payload: dict[str, Any]) -> dict[str, Any]:
        scope_type = (payload.get("scope_type") or "exam").strip().lower()
        username = (payload.get("username") or "").strip()[:64]
        password = str(payload.get("password") or "")
        note = (payload.get("note") or "").strip()[:160] or None
        expires_at = parse_datetime(payload.get("expires_at") or "")
        exam_id = int(payload.get("exam_id") or 0) or None
        patient_id = int(payload.get("patient_id") or 0) or None

        if scope_type not in {"exam", "patient"}:
            raise ValueError("Escopo de compartilhamento invalido.")
        if scope_type == "exam" and not exam_id:
            raise ValueError("Selecione um exame para compartilhar.")
        if scope_type == "patient" and not patient_id and not exam_id:
            raise ValueError("Selecione um paciente ou exame para compartilhar.")

        patient = None
        if exam_id:
            exam = self.get_exam(exam_id)
            patient_id = patient_id or int(exam["patient_id"])
            patient = self.get_patient(patient_id)
        elif patient_id:
            patient = self.get_patient(patient_id)

        if (not username or not password) and patient:
            suggestion = self.suggest_share_credentials(patient_id=int(patient["id"]))
            username = username or suggestion["username"]
            password = password or suggestion["password"]

        if not username or not password:
            raise ValueError("Usuario e senha do compartilhamento sao obrigatorios.")

        slug = secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:18].lower()
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into raiox.share_access (
                        slug, scope_type, patient_id, exam_id, username, password_hash, note, expires_at, active
                    ) values (
                        %s, %s, %s, %s, %s, %s, %s, %s, true
                    )
                    returning *
                    """,
                    (
                        slug,
                        scope_type,
                        patient_id,
                        exam_id if scope_type == "exam" else None,
                        username,
                        generate_password_hash(password),
                        note,
                        expires_at,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return {
            **self._serialize_share(row),
            "created_credentials": {
                "username": username,
                "password": password,
            },
        }

    def get_share_access_by_slug(self, slug: str) -> dict[str, Any]:
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select *
                    from raiox.share_access
                    where slug = %s
                    """,
                    ((slug or "").strip().lower(),),
                )
                row = cur.fetchone()
        if not row:
            raise ValueError("Compartilhamento nao encontrado.")
        return row

    def _ensure_share_active(self, share: dict[str, Any]) -> None:
        if not share.get("active"):
            raise ValueError("Compartilhamento inativo.")
        expires_at = share.get("expires_at")
        if expires_at and expires_at < datetime.now(expires_at.tzinfo):
            raise ValueError("Compartilhamento expirado.")

    def authenticate_share(self, slug: str, username: str, password: str) -> dict[str, Any]:
        share = self.get_share_access_by_slug(slug)
        self._ensure_share_active(share)
        if (share.get("username") or "").strip() != (username or "").strip():
            raise ValueError("Credenciais invalidas.")
        if not check_password_hash(share["password_hash"], password or ""):
            raise ValueError("Credenciais invalidas.")
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update raiox.share_access
                    set last_login_at = now(),
                        updated_at = now()
                    where id = %s
                    """,
                    (share["id"],),
                )
            conn.commit()
        share["last_login_at"] = datetime.now()
        return self._serialize_share(share)

    def get_shared_workspace(self, slug: str, requested_exam_id: int | None = None) -> dict[str, Any]:
        share = self.get_share_access_by_slug(slug)
        self._ensure_share_active(share)
        allowed_exam_ids = self._share_exam_ids(share)
        if not allowed_exam_ids:
            raise ValueError("Compartilhamento sem exames disponiveis.")
        selected_exam_id = int(requested_exam_id or 0) if requested_exam_id else allowed_exam_ids[0]
        if selected_exam_id not in allowed_exam_ids:
            selected_exam_id = allowed_exam_ids[0]
        exams = [exam for exam in self.list_exams() if int(exam["id"]) in allowed_exam_ids]
        return {
            "share": self._serialize_share(share),
            "exams": exams,
            "selected_exam_id": selected_exam_id,
            "workspace": self.get_exam_workspace(selected_exam_id),
        }

    def get_shared_attachment(self, slug: str, attachment_id: int) -> dict[str, Any]:
        share = self.get_share_access_by_slug(slug)
        self._ensure_share_active(share)
        attachment = self.get_exam_attachment(attachment_id)
        if int(attachment["exam_id"]) not in self._share_exam_ids(share):
            raise ValueError("Anexo indisponivel para este compartilhamento.")
        return attachment

    def get_shared_pacs_object(self, slug: str, sop_instance_uid: str) -> dict[str, Any]:
        share = self.get_share_access_by_slug(slug)
        self._ensure_share_active(share)
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        obj.*,
                        e.id as exam_id
                    from public.objects obj
                    left join public.study st on st.studyinstanceuid = obj.studyinstanceuid
                    left join raiox.exam e
                        on e.study_instance_uid = obj.studyinstanceuid
                        or e.accession_number = st.accessionnumber
                    where obj.sopinstanceuid = %s
                    order by case when e.study_instance_uid = obj.studyinstanceuid then 0 else 1 end
                    limit 1
                    """,
                    (sop_instance_uid,),
                )
                row = cur.fetchone()
        if not row:
            raise ValueError("Objeto DICOM nao encontrado.")
        if int(row.get("exam_id") or 0) not in self._share_exam_ids(share):
            raise ValueError("Objeto DICOM indisponivel para este compartilhamento.")
        return row

    def render_pacs_object_preview(
        self,
        sop_instance_uid: str,
        window_center: float | None = None,
        window_width: float | None = None,
        invert: bool = False,
        max_size: int | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        import numpy as np
        from PIL import Image

        obj = self.get_pacs_object(sop_instance_uid)
        dataset = dcmread(str(obj["filepath"]), force=True)
        pixels = dataset.pixel_array
        if getattr(pixels, "ndim", 0) == 4:
            pixels = pixels[0]
        elif getattr(pixels, "ndim", 0) == 3 and pixels.shape[-1] not in (3, 4):
            pixels = pixels[0]

        defaults = {
            "window_center": None,
            "window_width": None,
            "photometric_interpretation": str(getattr(dataset, "PhotometricInterpretation", "") or ""),
            "rows": int(getattr(dataset, "Rows", 0) or 0),
            "columns": int(getattr(dataset, "Columns", 0) or 0),
        }

        if getattr(pixels, "ndim", 0) == 2:
            array = pixels.astype("float32")
            slope = float(getattr(dataset, "RescaleSlope", 1) or 1)
            intercept = float(getattr(dataset, "RescaleIntercept", 0) or 0)
            array = array * slope + intercept
            default_wc = getattr(dataset, "WindowCenter", None)
            default_ww = getattr(dataset, "WindowWidth", None)
            if isinstance(default_wc, (list, tuple)):
                default_wc = default_wc[0]
            if isinstance(default_ww, (list, tuple)):
                default_ww = default_ww[0]
            min_value = float(array.min())
            max_value = float(array.max())
            defaults["window_center"] = float(default_wc) if default_wc not in (None, "") else (min_value + max_value) / 2.0
            defaults["window_width"] = float(default_ww) if default_ww not in (None, "") else max(max_value - min_value, 1.0)
            wc = float(window_center) if window_center not in (None, "") else defaults["window_center"]
            ww = float(window_width) if window_width not in (None, "") else defaults["window_width"]
            ww = max(ww, 1.0)
            low = wc - ww / 2.0
            high = wc + ww / 2.0
            array = np.clip((array - low) / max(high - low, 1.0), 0.0, 1.0)
            if str(getattr(dataset, "PhotometricInterpretation", "") or "").upper() == "MONOCHROME1":
                array = 1.0 - array
            if invert:
                array = 1.0 - array
            image = Image.fromarray((array * 255.0).astype("uint8"), mode="L")
        else:
            array = pixels.astype("float32")
            if array.max() <= 1.0:
                array = array * 255.0
            if invert:
                array = 255.0 - array
            image = Image.fromarray(np.clip(array, 0, 255).astype("uint8"))

        if max_size and max_size > 0:
            image.thumbnail((max_size, max_size), Image.Resampling.BILINEAR)

        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=False, compress_level=1)
        return buffer.getvalue(), defaults

    def upload_exam_attachment(self, exam_id: int, storage: Any) -> dict[str, Any]:
        exam = self.get_exam(exam_id)
        if storage is None:
            raise ValueError("Selecione um arquivo para anexar ao exame.")

        original_name = str(getattr(storage, "filename", "") or "").strip()
        mime_type = str(getattr(storage, "mimetype", "") or "").strip().lower()
        extension = Path(original_name).suffix.lower()
        if not original_name:
            raise ValueError("Arquivo invalido.")

        if extension == ".dcm" or "dicom" in mime_type:
            dataset = dcmread(storage.stream, force=True)
            dataset.AccessionNumber = str(exam.get("accession_number") or dataset.get("AccessionNumber") or "")[:16]
            dataset.StudyInstanceUID = str(exam.get("study_instance_uid") or dataset.get("StudyInstanceUID") or build_uid(self.settings.rad_uid_root))[:64]
            dataset.PatientName = str(exam.get("patient_name") or dataset.get("PatientName") or "")[:128]
            dataset.PatientID = str(exam.get("external_patient_id") or dataset.get("PatientID") or f"RXP{exam['patient_id']:06d}")[:64]
            dataset.PatientBirthDate = format_dicom_date(exam.get("patient_birth_date")) or str(dataset.get("PatientBirthDate") or "")[:8]
            dataset.PatientSex = str(exam.get("patient_sex") or dataset.get("PatientSex") or "")[:16]
            dataset.StudyDescription = str(exam.get("requested_description") or exam.get("procedure_name") or dataset.get("StudyDescription") or "")[:128]
            dataset.ReferringPhysicianName = str(exam.get("referring_physician") or dataset.get("ReferringPhysicianName") or "")[:128]
            dataset.Modality = self._dicom_modality(exam.get("modality") or exam.get("procedure_modality") or dataset.get("Modality") or "")
            dataset.StationName = str(exam.get("station_aet") or dataset.get("StationName") or self.settings.pacs_station_aet)[:32]
            if not getattr(dataset, "SeriesInstanceUID", None):
                dataset.SeriesInstanceUID = build_uid(self.settings.rad_uid_root)
            if not getattr(dataset, "SOPInstanceUID", None):
                dataset.SOPInstanceUID = build_uid(self.settings.rad_uid_root)
            if not getattr(dataset, "SOPClassUID", None):
                dataset.SOPClassUID = SecondaryCaptureImageStorage

            file_meta = getattr(dataset, "file_meta", None) or FileMetaDataset()
            file_meta.MediaStorageSOPClassUID = getattr(dataset, "SOPClassUID", SecondaryCaptureImageStorage)
            file_meta.MediaStorageSOPInstanceUID = getattr(dataset, "SOPInstanceUID")
            file_meta.TransferSyntaxUID = getattr(file_meta, "TransferSyntaxUID", None) or ExplicitVRLittleEndian

            store_instance(self.database, self.settings, dataset, file_meta, source_ae="WEBUPLOAD")
            return self.get_exam_workspace(exam_id)

        allowed_ext = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        if not mime_type.startswith("image/") and extension not in allowed_ext:
            raise ValueError("Envie uma imagem JPG/PNG/WEBP/GIF/BMP ou um arquivo DICOM (.dcm).")

        root = self._attachments_root(exam_id)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        safe_name = self._safe_filename(Path(original_name).stem)
        stored_name = f"{timestamp}-{safe_name}{extension[:16]}"
        target_path = root / stored_name
        storage.stream.seek(0)
        with target_path.open("wb") as handle:
            shutil.copyfileobj(storage.stream, handle)
        file_size = target_path.stat().st_size
        guessed_mime = mime_type or mimetypes.guess_type(target_path.name)[0] or "application/octet-stream"

        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into raiox.exam_attachment (
                        exam_id, kind, original_name, stored_name, mime_type, file_ext, file_size, file_path
                    ) values (
                        %s, 'image', %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        exam_id,
                        original_name[:255],
                        stored_name[:255],
                        guessed_mime[:160],
                        extension[:16] or None,
                        file_size,
                        str(target_path),
                    ),
                )
            conn.commit()
        return self.get_exam_workspace(exam_id)

    def list_call_panel(self, queue_date: date | None = None) -> dict[str, Any]:
        target_date = queue_date or date.today()
        panel_config = self.get_panel_config()
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        ct.id,
                        ct.exam_id,
                        ct.queue_date,
                        ct.ticket_number,
                        ct.status,
                        ct.destination,
                        ct.called_at,
                        ct.completed_at,
                        p.full_name as patient_name,
                        proc.name as procedure_name,
                        e.workflow_stage,
                        e.accession_number,
                        e.scheduled_at
                    from raiox.call_ticket ct
                    join raiox.exam e on e.id = ct.exam_id
                    join raiox.patient p on p.id = e.patient_id
                    join raiox.procedure_catalog proc on proc.id = e.procedure_id
                    where ct.queue_date = %s
                    order by ct.ticket_number asc
                    """,
                    (target_date,),
                )
                tickets = list(cur.fetchall())
                cur.execute(
                    """
                    select
                        cl.id,
                        cl.ticket_id,
                        cl.exam_id,
                        cl.destination,
                        cl.created_at,
                        p.full_name as patient_name,
                        ct.ticket_number,
                        coalesce(o.name, 'Sistema') as called_by_name
                    from raiox.call_log cl
                    join raiox.call_ticket ct on ct.id = cl.ticket_id
                    join raiox.exam e on e.id = cl.exam_id
                    join raiox.patient p on p.id = e.patient_id
                    left join raiox.operator o on o.id = cl.called_by
                    where ct.queue_date = %s
                    order by cl.created_at desc
                    limit 12
                    """,
                    (target_date,),
                )
                history = list(cur.fetchall())
        summary = {
            "waiting": sum(1 for item in tickets if item["status"] == "waiting"),
            "called": sum(1 for item in tickets if item["status"] == "called"),
            "in_service": sum(1 for item in tickets if item["status"] == "in_service"),
            "done": sum(1 for item in tickets if item["status"] == "done"),
        }
        return {
            "queue_date": target_date.isoformat(),
            "config": panel_config,
            "items": tickets,
            "history": history,
            "summary": summary,
        }

    def get_call_ticket(self, ticket_id: int) -> dict[str, Any]:
        panel = self.list_call_panel()
        for item in panel["items"]:
            if int(item["id"]) == ticket_id:
                return item
        raise ValueError("Senha nao encontrada.")

    def call_ticket(self, ticket_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        destination = (payload.get("destination") or "").strip()
        operator_id = int(payload.get("operator_id") or 0) or None
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute("select exam_id from raiox.call_ticket where id = %s", (ticket_id,))
                existing = cur.fetchone()
                if not existing:
                    raise ValueError("Senha nao encontrada.")
                cur.execute(
                    """
                    update raiox.call_ticket
                    set status = 'called',
                        destination = %s,
                        called_at = now(),
                        updated_at = now()
                    where id = %s
                    returning exam_id
                    """,
                    (destination or None, ticket_id),
                )
                row = cur.fetchone()
                cur.execute(
                    """
                    insert into raiox.call_log (ticket_id, exam_id, destination, called_by)
                    values (%s, %s, %s, %s)
                    """,
                    (ticket_id, row["exam_id"], destination or None, operator_id),
                )
            conn.commit()
        return self.get_call_ticket(ticket_id)

    def update_call_ticket_status(self, ticket_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        status = (payload.get("status") or "").strip().lower()
        if status not in CALL_STATUS:
            raise ValueError("Status da senha invalido.")
        destination = (payload.get("destination") or "").strip() or None
        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute("select exam_id from raiox.call_ticket where id = %s", (ticket_id,))
                row = cur.fetchone()
                if not row:
                    raise ValueError("Senha nao encontrada.")
                completed_at = "now()" if status == "done" else "null"
                cur.execute(
                    f"""
                    update raiox.call_ticket
                    set status = %s,
                        destination = %s,
                        completed_at = {completed_at},
                        updated_at = now()
                    where id = %s
                    """,
                    (status, destination, ticket_id),
                )
            conn.commit()
        return self.get_call_ticket(ticket_id)

    def _backup_root(self) -> Path:
        root = self.settings.runtime_root / "backups"
        (root / "database").mkdir(parents=True, exist_ok=True)
        (root / "images").mkdir(parents=True, exist_ok=True)
        return root

    def _backup_dir(self, kind: str) -> Path:
        normalized = (kind or "").strip().lower()
        if normalized not in {"database", "images"}:
            raise ValueError("Tipo de backup invalido.")
        return self._backup_root() / normalized

    def _backup_sources(self) -> dict[str, Path]:
        return {
            "imagebox": Path(self.settings.pacs_imagebox_path),
            "exam_attachments": self.settings.runtime_root / "exam_attachments",
            "cameras": self.settings.runtime_root / "cameras",
        }

    def _backup_item(self, kind: str, path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "kind": kind,
            "filename": path.name,
            "file_size_bytes": stat.st_size,
            "file_size_mb": round(stat.st_size / (1024 ** 2), 3),
            "created_at": datetime.fromtimestamp(stat.st_mtime),
            "download_path": f"/api/backups/{kind}/{path.name}",
        }

    def list_backups(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "backup_root": str(self._backup_root()),
            "database_strategy": "pg_dump" if shutil.which("pg_dump") else "logical-json",
            "database": [],
            "images": [],
        }
        for kind in ("database", "images"):
            backup_dir = self._backup_dir(kind)
            payload[kind] = [
                self._backup_item(kind, path)
                for path in sorted(backup_dir.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True)
                if path.is_file()
            ]
        return payload

    def _database_dump_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PGHOST"] = self.settings.pg_host
        env["PGPORT"] = str(self.settings.pg_port)
        env["PGUSER"] = self.settings.pg_user
        env["PGPASSWORD"] = self.settings.pg_password
        env["PGDATABASE"] = self.settings.pg_database
        if self.settings.pg_sslmode:
            env["PGSSLMODE"] = self.settings.pg_sslmode
        return env

    def _create_pg_dump_backup(self, target: Path) -> None:
        pg_dump = shutil.which("pg_dump")
        if not pg_dump:
            raise RuntimeError("pg_dump nao esta disponivel neste ambiente.")
        command = [
            pg_dump,
            "--no-owner",
            "--no-privileges",
            "--encoding=UTF8",
            "--host",
            self.settings.pg_host,
            "--port",
            str(self.settings.pg_port),
            "--username",
            self.settings.pg_user,
            "--dbname",
            self.settings.pg_database,
        ]
        with gzip.open(target, "wb") as handle:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._database_dump_env(),
            )
            assert process.stdout is not None
            shutil.copyfileobj(process.stdout, handle)
            stderr = (process.stderr.read() if process.stderr is not None else b"").decode("utf-8", "ignore").strip()
            exit_code = process.wait()
        if exit_code != 0:
            target.unlink(missing_ok=True)
            raise RuntimeError(stderr or "Falha ao executar pg_dump.")

    def _create_logical_database_backup(self, target: Path) -> None:
        metadata = normalize_json({
            "type": "metadata",
            "format": "raiox-jsonl-backup-v1",
            "created_at": datetime.now(),
            "database": self.settings.pg_database,
            "tables": [f"{schema}.{table}" for schema, table in BACKUP_TABLES],
        })
        with gzip.open(target, "wt", encoding="utf-8") as handle:
            handle.write(json.dumps(metadata, ensure_ascii=True) + "\n")
            with self.database.clinic() as conn:
                with conn.cursor() as cur:
                    for schema, table in BACKUP_TABLES:
                        table_name = f"{schema}.{table}"
                        cur.execute(f"select to_jsonb(t) as data from {table_name} t")
                        while True:
                            rows = cur.fetchmany(500)
                            if not rows:
                                break
                            for row in rows:
                                handle.write(
                                    json.dumps(
                                        normalize_json({
                                            "type": "row",
                                            "table": table_name,
                                            "data": row.get("data") or {},
                                        }),
                                        ensure_ascii=True,
                                    )
                                    + "\n"
                                )

    def create_database_backup(self) -> dict[str, Any]:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = self._backup_dir("database")
        warning = ""
        target = backup_dir / f"database-{self.settings.pg_database}-{timestamp}.sql.gz"
        try:
            self._create_pg_dump_backup(target)
            strategy = "pg_dump"
        except Exception as exc:
            warning = str(exc)
            target = backup_dir / f"database-{self.settings.pg_database}-{timestamp}.jsonl.gz"
            self._create_logical_database_backup(target)
            strategy = "logical-json"
        item = self._backup_item("database", target)
        item["strategy"] = strategy
        if warning:
            item["warning"] = warning
        return item

    def create_images_backup(self) -> dict[str, Any]:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = self._backup_dir("images")
        target = backup_dir / f"images-{timestamp}.tar.gz"
        included_paths: list[str] = []
        manifest = normalize_json({
            "created_at": datetime.now(),
            "sources": {name: str(path) for name, path in self._backup_sources().items()},
        })
        with tarfile.open(target, "w:gz") as archive:
            manifest_bytes = json.dumps(manifest, ensure_ascii=True, indent=2).encode("utf-8")
            manifest_info = tarfile.TarInfo("manifest.json")
            manifest_info.size = len(manifest_bytes)
            manifest_info.mtime = int(datetime.now().timestamp())
            archive.addfile(manifest_info, BytesIO(manifest_bytes))
            for name, source in self._backup_sources().items():
                if not source.exists():
                    continue
                archive.add(str(source), arcname=name)
                included_paths.append(str(source))
        item = self._backup_item("images", target)
        item["included_paths"] = included_paths
        return item

    def get_backup_file(self, kind: str, filename: str) -> dict[str, Any]:
        backup_dir = self._backup_dir(kind).resolve()
        candidate = (backup_dir / (filename or "").strip()).resolve()
        if backup_dir not in candidate.parents or not candidate.is_file():
            raise ValueError("Arquivo de backup nao encontrado.")
        return {
            "path": candidate,
            "filename": candidate.name,
            "mimetype": "application/gzip",
        }

    def storage_overview(self) -> dict[str, Any]:
        imagebox = Path(self.settings.pacs_imagebox_path)
        if imagebox.exists():
            root_for_disk = imagebox
        elif self.settings.runtime_root.exists():
            root_for_disk = self.settings.runtime_root
        else:
            root_for_disk = Path("/")
        disk = shutil.disk_usage(root_for_disk)
        folder_bytes = 0
        if imagebox.exists():
            try:
                result = subprocess.run(
                    ["du", "-sb", str(imagebox)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                folder_bytes = int(result.stdout.split()[0])
            except Exception:
                folder_bytes = sum(item.stat().st_size for item in imagebox.rglob("*") if item.is_file())

        with self.database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        (select count(*) from public.study) as study_count,
                        (select count(*) from public.series) as series_count,
                        (select count(*) from public.objects) as object_count,
                        (select max(receivedat) from public.objects) as latest_received_at,
                        (select count(*) from raiox.exam) as local_exam_count
                    """
                )
                counters = cur.fetchone() or {}

        return {
            "imagebox_path": str(imagebox),
            "imagebox_exists": imagebox.exists(),
            "runtime_root": str(self.settings.runtime_root),
            "disk_total_gb": round(disk.total / (1024 ** 3), 2),
            "disk_used_gb": round(disk.used / (1024 ** 3), 2),
            "disk_free_gb": round(disk.free / (1024 ** 3), 2),
            "disk_used_percent": round((disk.used / disk.total) * 100, 2) if disk.total else 0,
            "imagebox_size_gb": round(folder_bytes / (1024 ** 3), 4),
            "pacs_ae_title": self.settings.pacs_aet,
            "dicom_port": self.settings.dicom_port,
            "worklist_ae_title": self.settings.worklist_ae_title,
            "worklist_port": self.settings.worklist_port,
            **counters,
        }

    def overview(self) -> dict[str, Any]:
        exams = self.list_exams()
        visible_exams = [exam for exam in exams if not self._is_archived_finalized(exam)]
        invoices = self.list_invoices()
        finance = self.finance_overview()
        storage = self.storage_overview()
        patients = self.list_patients()
        panel = self.list_call_panel()
        departments = self.list_chat_departments()
        unread_total = 0
        for department in departments:
            unread_total += int(self.chat_unread(int(department["id"])).get("total") or 0)

        status_counts: dict[str, int] = {}
        workflow_counts: dict[str, int] = {stage: 0 for stage in WORKFLOW_STAGES}
        for exam in visible_exams:
            status_key = exam["live_status"]
            status_counts[status_key] = status_counts.get(status_key, 0) + 1
            workflow_counts[self._normalize_stage(exam.get("workflow_stage"))] += 1

        return {
            "summary": {
                "patients": len(patients),
                "exams": len(visible_exams),
                "pending_worklist": sum(1 for exam in visible_exams if exam.get("workflow_stage") == "draft"),
                "local_worklist_active": sum(1 for exam in visible_exams if exam.get("local_worklist_active")),
                "pacs_mirror_rows": sum(1 for exam in visible_exams if exam.get("pacs_worklist_present")),
                "reported": status_counts.get("reported", 0),
                "open_invoices": finance["totals"].get("open_invoices", 0),
                "open_amount": finance["totals"].get("open_total", 0),
                "paid_invoices": finance["totals"].get("paid_invoices", 0),
                "paid_amount": finance["totals"].get("paid_total", 0),
                "waiting_calls": panel["summary"].get("waiting", 0),
                "unread_messages": unread_total,
                "departments": len(departments),
            },
            "finance": finance,
            "report_catalog": list(REPORT_CATALOG),
            "status_counts": status_counts,
            "workflow_counts": workflow_counts,
            "latest_exams": visible_exams[:10],
            "latest_invoices": invoices[:10],
            "latest_messages": self.recent_messages(),
            "storage": storage,
            "communication": {
                "departments": len(departments),
                "unread_messages": unread_total,
            },
            "calls": {
                "summary": panel["summary"],
                "last_called": panel["history"][0] if panel["history"] else None,
            },
        }
