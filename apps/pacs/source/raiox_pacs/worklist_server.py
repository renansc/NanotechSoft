from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

from pydicom.dataset import Dataset
from pynetdicom import AE, evt
from pynetdicom.sop_class import ModalityWorklistInformationFind, Verification

from .bootstrap import ensure_schema
from .config import Settings
from .db import Database
from .utils import format_dicom_date, format_dicom_time


LOGGER = logging.getLogger("raiox_pacs.worklist")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore").strip()
    return str(value).strip()


def _safe_attribute(dataset: Dataset, keyword: str, default: Any = "") -> Any:
    try:
        return getattr(dataset, keyword, default)
    except Exception as exc:
        LOGGER.warning("Campo DICOM invalido ignorado na consulta MWL: %s (%s)", keyword, exc)
        return default


def _normalize_dicom_text(value: Any) -> list[str]:
    text = _text(value).replace("^", " ")
    normalized = unicodedata.normalize("NFKD", text)
    ascii_value = normalized.encode("ascii", errors="ignore").decode("ascii")
    return [token for token in re.split(r"[^a-z0-9]+", ascii_value.lower()) if token]


def _normalize_dicom_alnum(value: Any) -> str:
    text = _text(value)
    normalized = unicodedata.normalize("NFKD", text)
    ascii_value = normalized.encode("ascii", errors="ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())


def _normalize_dicom_date(value: Any) -> str:
    text = _text(value)
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return text


def _dicom_worklist_modality(value: Any) -> str:
    raw = _text(value).strip().upper()
    if raw == "US":
        return "US"
    if raw in {"CR", "DX", "DR"}:
        return "CR"
    return "CR"


def _requested_station_aet(identifier: Dataset) -> str:
    sps_sequence = _safe_attribute(identifier, "ScheduledProcedureStepSequence", [])
    if not sps_sequence or len(sps_sequence) == 0:
        return ""
    return _text(_safe_attribute(sps_sequence[0], "ScheduledStationAETitle", ""))


def _response_station_aet(row: dict[str, Any], requested_station_aet: str = "") -> str:
    stored_station_aet = _text(row.get("station_aet"))
    # Prefer the station stored with the exam to preserve the legacy MWL shape
    # that previously matched the LG workstation behavior.
    return (stored_station_aet or requested_station_aet)[:16]


def _worklist_response_summary(row: dict[str, Any], dataset: Dataset, requested_station_aet: str = "") -> dict[str, str]:
    requested_procedure_id = _text(getattr(dataset, "RequestedProcedureID", ""))
    study_description = _text(getattr(dataset, "StudyDescription", ""))
    procedure_sequence = list(getattr(dataset, "RequestedProcedureCodeSequence", []) or [])
    procedure_item = procedure_sequence[0] if procedure_sequence else Dataset()
    sps_sequence = list(getattr(dataset, "ScheduledProcedureStepSequence", []) or [])
    sps = sps_sequence[0] if sps_sequence else Dataset()
    response_station_aet = _text(getattr(sps, "ScheduledStationAETitle", ""))
    response_modality = _text(getattr(sps, "Modality", ""))
    legacy_requested_procedure_id = _text(row.get("requested_procedure_id") or row.get("procedure_code"))
    legacy_station_aet = _text(row.get("station_aet"))
    return {
        "exam_id": str(row.get("id") or ""),
        "accession": _text(row.get("accession_number")),
        "study_uid": _text(getattr(dataset, "StudyInstanceUID", "")),
        "requested_procedure_id": requested_procedure_id,
        "study_description": study_description,
        "procedure_code": _text(getattr(procedure_item, "CodeValue", "")),
        "procedure_scheme": _text(getattr(procedure_item, "CodingSchemeDesignator", "")),
        "procedure_meaning": _text(getattr(procedure_item, "CodeMeaning", "")),
        "response_station_aet": response_station_aet,
        "stored_station_aet": legacy_station_aet,
        "requested_station_aet": requested_station_aet,
        "response_modality": response_modality,
        "legacy_requested_procedure_id": legacy_requested_procedure_id,
        "legacy_requested_procedure_match": "yes" if requested_procedure_id == legacy_requested_procedure_id else "no",
        "legacy_station_match": "yes" if response_station_aet == (legacy_station_aet or requested_station_aet) else "no",
        "has_study_description": "yes" if study_description else "no",
        "has_requested_procedure_code_sequence": "yes" if procedure_sequence else "no",
    }


def _log_worklist_response(row: dict[str, Any], dataset: Dataset, requested_station_aet: str = "") -> None:
    summary = _worklist_response_summary(row, dataset, requested_station_aet=requested_station_aet)
    LOGGER.info(
        "MWL resposta exame=%s accession=%s req_proc=%s legacy_req_proc=%s legacy_match=%s "
        "study_uid=%s study_desc=%s code_seq=%s code=%s meaning=%s modality=%s "
        "station_resp=%s station_req=%s station_saved=%s station_match=%s",
        summary["exam_id"] or "-",
        summary["accession"] or "-",
        summary["requested_procedure_id"] or "-",
        summary["legacy_requested_procedure_id"] or "-",
        summary["legacy_requested_procedure_match"] or "-",
        summary["study_uid"] or "-",
        summary["has_study_description"] or "-",
        summary["has_requested_procedure_code_sequence"] or "-",
        summary["procedure_code"] or "-",
        summary["procedure_meaning"] or "-",
        summary["response_modality"] or "-",
        summary["response_station_aet"] or "-",
        summary["requested_station_aet"] or "-",
        summary["stored_station_aet"] or "-",
        summary["legacy_station_match"] or "-",
    )


def _patient_name_matches(query_name: Any, candidate_name: Any) -> bool:
    query_tokens = _normalize_dicom_text(query_name)
    if not query_tokens:
        return True

    candidate_tokens = _normalize_dicom_text(candidate_name)
    if not candidate_tokens:
        return False

    # Many modalities send PatientName as DICOM PN ("SOBRENOME^NOME").
    # We accept the tokens in any order so the same exam still matches the
    # clinic's natural-language patient name stored in the database.
    return all(
        any(candidate_token.startswith(query_token) or query_token.startswith(candidate_token) for candidate_token in candidate_tokens)
        for query_token in query_tokens
    )


def _query_filters(identifier: Dataset) -> tuple[list[str], list[Any], dict[str, str]]:
    clauses = [
        "coalesce(e.status, 'scheduled') not in ('reported', 'cancelled')",
        "coalesce(e.worklist_status, 'draft') in ('scheduled', 'arrived', 'started')",
    ]
    params: list[Any] = []
    criteria: dict[str, str] = {}
    criteria["query_level"] = _text(_safe_attribute(identifier, "QueryRetrieveLevel", ""))
    criteria["scheduled_station_aet"] = ""

    patient_id = _text(_safe_attribute(identifier, "PatientID", ""))
    if patient_id:
        normalized_patient_id = _normalize_dicom_alnum(patient_id)
        if normalized_patient_id:
            clauses.append(
                """
                (
                    regexp_replace(lower(coalesce(nullif(btrim(p.external_patient_id), ''), '')), '[^a-z0-9]+', '', 'g') = %s
                    or regexp_replace(lower(coalesce(nullif(btrim(p.cpf), ''), '')), '[^0-9]+', '', 'g') = %s
                    or lower(concat('rxp', lpad(p.id::text, 6, '0'))) = %s
                )
                """
            )
            params.extend([normalized_patient_id, normalized_patient_id, normalized_patient_id])
        criteria["patient_id"] = patient_id

    accession = _text(_safe_attribute(identifier, "AccessionNumber", ""))
    if accession:
        clauses.append("e.accession_number = %s")
        params.append(accession)
        criteria["accession"] = accession

    patient_name = _text(_safe_attribute(identifier, "PatientName", ""))
    if patient_name:
        criteria["patient_name"] = patient_name

    sps_sequence = _safe_attribute(identifier, "ScheduledProcedureStepSequence", [])
    if sps_sequence and len(sps_sequence) > 0:
        sps = sps_sequence[0]
        station = _text(_safe_attribute(sps, "ScheduledStationAETitle", ""))
        modality = _text(_safe_attribute(sps, "Modality", ""))
        if modality:
            criteria["modality"] = modality
        if station:
            criteria["scheduled_station_aet"] = station
        sps_date = _normalize_dicom_date(_safe_attribute(sps, "ScheduledProcedureStepStartDate", ""))
        if sps_date:
            criteria["scheduled_date"] = sps_date

    return clauses, params, criteria


def _exam_rows(database: Database, identifier: Dataset) -> list[dict[str, Any]]:
    clauses, params, criteria = _query_filters(identifier)
    LOGGER.info(
        "MWL consulta recebida nivel=%s data=%s paciente=%s accession=%s modalidade=%s station=%s",
        criteria.get("query_level") or "-",
        criteria.get("scheduled_date") or "-",
        criteria.get("patient_name") or criteria.get("patient_id") or "-",
        criteria.get("accession") or "-",
        criteria.get("modality") or "-",
        criteria.get("scheduled_station_aet") or "-",
    )

    def run_query(query_clauses: list[str], query_params: list[Any]) -> list[dict[str, Any]]:
        sql = f"""
        select
            e.id,
            e.accession_number,
            e.study_instance_uid,
            e.requested_procedure_id,
            e.requested_description,
            e.referring_physician,
            e.performing_physician,
            e.scheduled_at,
            e.priority,
            e.station_aet,
            e.worklist_status,
            p.id as patient_pk,
            p.external_patient_id,
            p.full_name,
            p.birth_date,
            p.sex,
            proc.code as procedure_code,
            proc.name as procedure_name,
            coalesce(e.modality, proc.modality, '') as modality
        from raiox.exam e
        join raiox.patient p on p.id = e.patient_id
        join raiox.procedure_catalog proc on proc.id = e.procedure_id
        where {' and '.join(query_clauses)}
        order by e.scheduled_at asc nulls last, e.id asc
        limit 200
        """
        with database.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, query_params)
                return list(cur.fetchall())

    rows = run_query(clauses, params)

    patient_name = criteria.get("patient_name")
    if patient_name:
        rows = [row for row in rows if _patient_name_matches(patient_name, row.get("full_name"))]

    return rows


def _dataset_for_exam(row: dict[str, Any], requested_station_aet: str = "") -> Dataset:
    requested_procedure_id = (
        (row.get("requested_procedure_id") or row.get("procedure_code") or "").strip() or f"RXP{int(row['id']):08d}"
    )
    procedure_code = ((row.get("procedure_code") or row.get("requested_procedure_id") or requested_procedure_id).strip())[:16]
    procedure_description = (row.get("requested_description") or row.get("procedure_name") or "")[:64]
    ds = Dataset()
    ds.PatientName = (row.get("full_name") or "")[:128]
    ds.PatientID = (row.get("external_patient_id") or f"RXP{row['patient_pk']:06d}")[:64]
    ds.PatientBirthDate = format_dicom_date(row.get("birth_date"))
    ds.PatientSex = (row.get("sex") or "")[:16]
    ds.AccessionNumber = (row.get("accession_number") or "")[:16]
    ds.StudyInstanceUID = (row.get("study_instance_uid") or "")[:64]
    ds.StudyDescription = procedure_description[:64]
    ds.ReferringPhysicianName = (row.get("referring_physician") or "")[:64]
    ds.RequestedProcedureID = requested_procedure_id[:32]
    ds.RequestedProcedureDescription = procedure_description
    ds.RequestedProcedurePriority = (row.get("priority") or "ROUTINE")[:16]
    procedure_item = Dataset()
    procedure_item.CodeValue = procedure_code
    procedure_item.CodingSchemeDesignator = "RAIOX"
    procedure_item.CodeMeaning = procedure_description
    ds.RequestedProcedureCodeSequence = [procedure_item]

    sps = Dataset()
    sps.Modality = _dicom_worklist_modality(row.get("modality"))[:16]
    sps.ScheduledStationAETitle = _response_station_aet(row, requested_station_aet=requested_station_aet)
    sps.ScheduledProcedureStepStartDate = format_dicom_date(row.get("scheduled_at"))
    sps.ScheduledProcedureStepStartTime = format_dicom_time(row.get("scheduled_at"))
    sps.ScheduledPerformingPhysicianName = (row.get("performing_physician") or "")[:64]
    sps.ScheduledProcedureStepDescription = (row.get("procedure_name") or "")[:64]
    sps.ScheduledProcedureStepID = f"RXS{row['id']:08d}"[:32]
    sps.ScheduledProcedureStepStatus = {
        "arrived": "ARRIVED",
        "started": "STARTED",
    }.get((row.get("worklist_status") or "").strip().lower(), "SCHEDULED")
    ds.ScheduledProcedureStepSequence = [sps]
    return ds


def build_find_handler(database: Database):
    def handle_find(event):
        if event.identifier is None:
            yield 0xC310, None
            return
        try:
            requestor = getattr(getattr(event, "assoc", None), "requestor", None)
            requestor_ae = _text(getattr(requestor, "ae_title", ""))
            requestor_address = _text(getattr(requestor, "address", ""))
            LOGGER.info(
                "MWL C-FIND recebido de AE=%s addr=%s",
                requestor_ae or "?",
                requestor_address or "?",
            )
            requested_station_aet = _requested_station_aet(event.identifier)
            for row in _exam_rows(database, event.identifier):
                if event.is_cancelled:
                    yield 0xFE00, None
                    return
                dataset = _dataset_for_exam(row, requested_station_aet=requested_station_aet)
                _log_worklist_response(row, dataset, requested_station_aet=requested_station_aet)
                yield 0xFF00, dataset
            yield 0x0000, None
        except Exception:
            LOGGER.exception("Falha ao processar C-FIND da worklist.")
            yield 0xC311, None

    return handle_find


def handle_echo(event):
    requestor = getattr(getattr(event, "assoc", None), "requestor", None)
    requestor_ae = _text(getattr(requestor, "ae_title", ""))
    requestor_address = _text(getattr(requestor, "address", ""))
    LOGGER.info(
        "MWL C-ECHO recebido de AE=%s addr=%s",
        requestor_ae or "?",
        requestor_address or "?",
    )
    return 0x0000


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    project_root = Path(__file__).resolve().parent.parent
    settings = Settings.load(project_root)
    database = Database(settings)
    if settings.auto_bootstrap_schema:
        ensure_schema(database)

    ae = AE(ae_title=settings.worklist_ae_title)
    ae.add_supported_context(Verification)
    ae.add_supported_context(ModalityWorklistInformationFind)
    handlers = [
        (evt.EVT_C_ECHO, handle_echo),
        (evt.EVT_C_FIND, build_find_handler(database)),
    ]
    print(
        f"Starting MWL on {settings.worklist_bind_host}:{settings.worklist_port} "
        f"with AE={settings.worklist_ae_title}"
    )
    ae.start_server((settings.worklist_bind_host, settings.worklist_port), evt_handlers=handlers, block=True)


if __name__ == "__main__":
    main()
