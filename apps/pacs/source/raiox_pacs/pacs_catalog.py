from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydicom import dcmread
from pydicom.dataset import Dataset
from pynetdicom import build_context

from .config import Settings
from .db import Database


def _string(value: Any, size: int = 0) -> str:
    text = str(value or "").strip()
    return text[:size] if size else text


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _like_value(value: str) -> str:
    return value.replace("*", "%").replace("?", "_")


def pacs_storage_root(settings: Settings) -> Path:
    root = Path(settings.pacs_imagebox_path)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _instance_path(settings: Settings, study_uid: str, series_uid: str, sop_uid: str) -> Path:
    study_dir = pacs_storage_root(settings) / study_uid / series_uid
    study_dir.mkdir(parents=True, exist_ok=True)
    return study_dir / f"{sop_uid}.dcm"


def _match_exam(cur: Any, accession: str, study_uid: str) -> dict[str, Any] | None:
    cur.execute(
        """
        select id, accession_number, study_instance_uid
        from raiox.exam
        where accession_number = %s or study_instance_uid = %s
        order by case when study_instance_uid = %s then 0 else 1 end, id asc
        limit 1
        """,
        (accession or "", study_uid or "", study_uid or ""),
    )
    return cur.fetchone()


def store_instance(
    database: Database,
    settings: Settings,
    dataset: Dataset,
    file_meta: Dataset,
    source_ae: str = "",
) -> dict[str, Any]:
    ds = dataset[0x00030000:]
    ds.file_meta = file_meta

    study_uid = _string(getattr(ds, "StudyInstanceUID", ""), 64)
    series_uid = _string(getattr(ds, "SeriesInstanceUID", ""), 64)
    sop_uid = _string(getattr(ds, "SOPInstanceUID", ""), 64)
    sop_class_uid = _string(getattr(ds, "SOPClassUID", ""), 64)
    if not study_uid or not series_uid or not sop_uid:
        raise ValueError("Dataset DICOM sem Study/Series/SOP Instance UID.")

    file_path = _instance_path(settings, study_uid, series_uid, sop_uid)
    ds.save_as(file_path, write_like_original=False)
    file_size = file_path.stat().st_size

    accession_number = _string(getattr(ds, "AccessionNumber", ""), 16)
    patient_name = _string(getattr(ds, "PatientName", ""), 128)
    patient_id = _string(getattr(ds, "PatientID", ""), 64)
    patient_birth_date = _string(getattr(ds, "PatientBirthDate", ""), 8)
    patient_sex = _string(getattr(ds, "PatientSex", ""), 16)
    modality = _string(getattr(ds, "Modality", ""), 16)
    institution_name = _string(getattr(ds, "InstitutionName", ""), 128) or settings.pacs_institution_name[:128]
    station_name = _string(getattr(ds, "StationName", ""), 32) or settings.pacs_station_aet[:32]
    study_date = _string(getattr(ds, "StudyDate", ""), 8)
    study_time = _string(getattr(ds, "StudyTime", ""), 16)
    series_date = _string(getattr(ds, "SeriesDate", ""), 8)
    series_time = _string(getattr(ds, "SeriesTime", ""), 16)
    content_date = _string(getattr(ds, "ContentDate", ""), 8)
    content_time = _string(getattr(ds, "ContentTime", ""), 16)
    acquisition_date = _string(getattr(ds, "AcquisitionDate", ""), 8)
    acquisition_time = _string(getattr(ds, "AcquisitionTime", ""), 16)
    image_number = _int(getattr(ds, "InstanceNumber", None) or getattr(ds, "ImageNumber", None))
    acquisition_number = _int(getattr(ds, "AcquisitionNumber", None))
    transfer_syntax_uid = _string(getattr(file_meta, "TransferSyntaxUID", ""), 64)

    with database.clinic() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into public.study (
                    studyinstanceuid, studydate, studytime, studyid, studydescription,
                    accessionnumber, referphysician, studymodality, stationname, institutionname,
                    studypath, patientid, patientname, patientsex, patientbd,
                    operatorsname, medicalalerts, readingphysician, patientcomments
                ) values (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                on conflict (studyinstanceuid) do update
                set studydate = excluded.studydate,
                    studytime = excluded.studytime,
                    studyid = excluded.studyid,
                    studydescription = excluded.studydescription,
                    accessionnumber = excluded.accessionnumber,
                    referphysician = excluded.referphysician,
                    studymodality = excluded.studymodality,
                    stationname = excluded.stationname,
                    institutionname = excluded.institutionname,
                    studypath = excluded.studypath,
                    patientid = excluded.patientid,
                    patientname = excluded.patientname,
                    patientsex = excluded.patientsex,
                    patientbd = excluded.patientbd,
                    operatorsname = excluded.operatorsname,
                    medicalalerts = excluded.medicalalerts,
                    readingphysician = excluded.readingphysician,
                    patientcomments = excluded.patientcomments
                """,
                (
                    study_uid,
                    study_date or None,
                    study_time or None,
                    _string(getattr(ds, "StudyID", ""), 16) or None,
                    _string(getattr(ds, "StudyDescription", ""), 128) or None,
                    accession_number or None,
                    _string(getattr(ds, "ReferringPhysicianName", ""), 128) or None,
                    modality or None,
                    station_name or None,
                    institution_name or None,
                    str(file_path.parent.parent)[:255],
                    patient_id or None,
                    patient_name or None,
                    patient_sex or None,
                    patient_birth_date or None,
                    _string(getattr(ds, "OperatorsName", ""), 128) or None,
                    _string(getattr(ds, "MedicalAlerts", ""), 64) or None,
                    _string(getattr(ds, "NameOfPhysiciansReadingStudy", ""), 128) or None,
                    _string(getattr(ds, "PatientComments", ""), 1024) or None,
                ),
            )
            cur.execute(
                """
                insert into public.series (
                    seriesinstanceuid, seriesnumber, seriesdate, seriestime, seriesdescription,
                    modality, institutionname, manufacturer, modelname, bodypartexamined,
                    protocolname, seriespath, studyinstanceuid
                ) values (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s
                )
                on conflict (seriesinstanceuid) do update
                set seriesnumber = excluded.seriesnumber,
                    seriesdate = excluded.seriesdate,
                    seriestime = excluded.seriestime,
                    seriesdescription = excluded.seriesdescription,
                    modality = excluded.modality,
                    institutionname = excluded.institutionname,
                    manufacturer = excluded.manufacturer,
                    modelname = excluded.modelname,
                    bodypartexamined = excluded.bodypartexamined,
                    protocolname = excluded.protocolname,
                    seriespath = excluded.seriespath,
                    studyinstanceuid = excluded.studyinstanceuid
                """,
                (
                    series_uid,
                    _string(getattr(ds, "SeriesNumber", ""), 12) or None,
                    series_date or None,
                    series_time or None,
                    _string(getattr(ds, "SeriesDescription", ""), 128) or None,
                    modality or None,
                    institution_name or None,
                    _string(getattr(ds, "Manufacturer", ""), 128) or None,
                    _string(getattr(ds, "ManufacturerModelName", ""), 128) or None,
                    _string(getattr(ds, "BodyPartExamined", ""), 64) or None,
                    _string(getattr(ds, "ProtocolName", ""), 128) or None,
                    str(file_path.parent)[:255],
                    study_uid,
                ),
            )
            cur.execute(
                """
                insert into public.objects (
                    sopinstanceuid, sopclassuid, imagenumber, contentdate, contenttime,
                    acquisitionnumber, acquisitiondate, acquisitiontime, slicelocation, receiveddate,
                    seriesinstanceuid, studyinstanceuid, convolutionkernel, backupstatus, keyobject,
                    filepath, transfersyntaxuid, filesize, receivedat
                ) values (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, to_char(now(), 'YYYYMMDD'),
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, now()
                )
                on conflict (sopinstanceuid) do update
                set sopclassuid = excluded.sopclassuid,
                    imagenumber = excluded.imagenumber,
                    contentdate = excluded.contentdate,
                    contenttime = excluded.contenttime,
                    acquisitionnumber = excluded.acquisitionnumber,
                    acquisitiondate = excluded.acquisitiondate,
                    acquisitiontime = excluded.acquisitiontime,
                    slicelocation = excluded.slicelocation,
                    receiveddate = excluded.receiveddate,
                    seriesinstanceuid = excluded.seriesinstanceuid,
                    studyinstanceuid = excluded.studyinstanceuid,
                    convolutionkernel = excluded.convolutionkernel,
                    filepath = excluded.filepath,
                    transfersyntaxuid = excluded.transfersyntaxuid,
                    filesize = excluded.filesize,
                    receivedat = now()
                """,
                (
                    sop_uid,
                    sop_class_uid or None,
                    image_number,
                    content_date or None,
                    content_time or None,
                    acquisition_number,
                    acquisition_date or None,
                    acquisition_time or None,
                    _string(getattr(ds, "SliceLocation", ""), 32) or None,
                    series_uid,
                    study_uid,
                    _string(getattr(ds, "ConvolutionKernel", ""), 32) or None,
                    0,
                    _string(getattr(ds, "KeyObjectSelectionDocument", ""), 1) or None,
                    str(file_path),
                    transfer_syntax_uid or None,
                    file_size,
                ),
            )
            if accession_number:
                cur.execute(
                    """
                    update public.worklist
                    set studyinstanceuid = %s,
                        spsstatus = 'COMPLETED'
                    where accessionnumber = %s
                    """,
                    (study_uid, accession_number),
                )
            matched = _match_exam(cur, accession_number, study_uid)
            if matched:
                cur.execute(
                    """
                    update raiox.exam
                    set study_instance_uid = %s,
                        status = 'executed',
                        workflow_stage = 'executed',
                        worklist_status = 'executed',
                        pacs_study_found = true,
                        updated_at = now()
                    where id = %s
                    """,
                    (study_uid, matched["id"]),
                )
                cur.execute(
                    """
                    insert into raiox.sync_log (exam_id, target, event_type, success, message, payload)
                    values (%s, 'dicom', 'c-store', true, %s, %s::jsonb)
                    """,
                    (
                        matched["id"],
                        "Instancia DICOM recebida e persistida no PACS local.",
                        json.dumps(
                            {
                                "study_instance_uid": study_uid,
                                "series_instance_uid": series_uid,
                                "sop_instance_uid": sop_uid,
                                "source_ae": _string(source_ae, 64),
                            }
                        ),
                    ),
                )
        conn.commit()

    return {
        "study_instance_uid": study_uid,
        "series_instance_uid": series_uid,
        "sop_instance_uid": sop_uid,
        "accession_number": accession_number,
        "filepath": str(file_path),
        "source_ae": _string(source_ae, 64),
    }


def _apply_study_filters(identifier: Dataset, clauses: list[str], params: list[Any]) -> None:
    study_uid = _string(getattr(identifier, "StudyInstanceUID", ""), 64)
    if study_uid:
        clauses.append("st.studyinstanceuid = %s")
        params.append(study_uid)

    accession = _string(getattr(identifier, "AccessionNumber", ""), 16)
    if accession:
        clauses.append("coalesce(st.accessionnumber, '') = %s")
        params.append(accession)

    patient_id = _string(getattr(identifier, "PatientID", ""), 64)
    if patient_id:
        clauses.append("coalesce(st.patientid, '') = %s")
        params.append(patient_id)

    patient_name = _string(getattr(identifier, "PatientName", ""), 128)
    if patient_name:
        clauses.append("coalesce(st.patientname, '') ilike %s")
        params.append(_like_value(patient_name))

    study_date = _string(getattr(identifier, "StudyDate", ""), 8)
    if study_date:
        clauses.append("coalesce(st.studydate, '') = %s")
        params.append(study_date)

    modality = _string(getattr(identifier, "ModalitiesInStudy", "") or getattr(identifier, "Modality", ""), 16)
    if modality:
        clauses.append("coalesce(st.studymodality, '') = %s")
        params.append(modality)


def find_matches(database: Database, identifier: Dataset) -> tuple[str, list[dict[str, Any]]]:
    level = _string(getattr(identifier, "QueryRetrieveLevel", ""), 16).upper() or "STUDY"
    if level not in {"STUDY", "SERIES", "IMAGE"}:
        raise ValueError("QueryRetrieveLevel invalido.")

    clauses = ["1 = 1"]
    params: list[Any] = []
    _apply_study_filters(identifier, clauses, params)

    if level == "STUDY":
        sql = f"""
            select
                st.studyinstanceuid,
                st.studydate,
                st.studytime,
                st.studyid,
                st.studydescription,
                st.accessionnumber,
                st.referphysician,
                st.studymodality,
                st.stationname,
                st.institutionname,
                st.patientid,
                st.patientname,
                st.patientsex,
                st.patientbd,
                count(distinct sr.seriesinstanceuid) as number_of_study_related_series,
                count(obj.sopinstanceuid) as number_of_study_related_instances,
                max(obj.receivedat) as last_received_at
            from public.study st
            left join public.series sr on sr.studyinstanceuid = st.studyinstanceuid
            left join public.objects obj on obj.studyinstanceuid = st.studyinstanceuid
            where {' and '.join(clauses)}
            group by
                st.studyinstanceuid, st.studydate, st.studytime, st.studyid, st.studydescription,
                st.accessionnumber, st.referphysician, st.studymodality, st.stationname,
                st.institutionname, st.patientid, st.patientname, st.patientsex, st.patientbd
            order by max(obj.receivedat) desc nulls last, st.studydate desc nulls last
            limit 200
        """
    elif level == "SERIES":
        series_uid = _string(getattr(identifier, "SeriesInstanceUID", ""), 64)
        if series_uid:
            clauses.append("sr.seriesinstanceuid = %s")
            params.append(series_uid)
        modality = _string(getattr(identifier, "Modality", ""), 16)
        if modality:
            clauses.append("coalesce(sr.modality, '') = %s")
            params.append(modality)
        sql = f"""
            select
                st.studyinstanceuid,
                st.studydate,
                st.studytime,
                st.accessionnumber,
                st.patientid,
                st.patientname,
                st.patientsex,
                st.patientbd,
                sr.seriesinstanceuid,
                sr.seriesnumber,
                sr.seriesdate,
                sr.seriestime,
                sr.seriesdescription,
                sr.modality,
                count(obj.sopinstanceuid) as number_of_series_related_instances,
                max(obj.receivedat) as last_received_at
            from public.series sr
            join public.study st on st.studyinstanceuid = sr.studyinstanceuid
            left join public.objects obj on obj.seriesinstanceuid = sr.seriesinstanceuid
            where {' and '.join(clauses)}
            group by
                st.studyinstanceuid, st.studydate, st.studytime, st.accessionnumber,
                st.patientid, st.patientname, st.patientsex, st.patientbd,
                sr.seriesinstanceuid, sr.seriesnumber, sr.seriesdate, sr.seriestime,
                sr.seriesdescription, sr.modality
            order by max(obj.receivedat) desc nulls last, sr.seriesnumber asc nulls last
            limit 500
        """
    else:
        series_uid = _string(getattr(identifier, "SeriesInstanceUID", ""), 64)
        if series_uid:
            clauses.append("obj.seriesinstanceuid = %s")
            params.append(series_uid)
        sop_uid = _string(getattr(identifier, "SOPInstanceUID", ""), 64)
        if sop_uid:
            clauses.append("obj.sopinstanceuid = %s")
            params.append(sop_uid)
        sql = f"""
            select
                st.studyinstanceuid,
                st.studydate,
                st.studytime,
                st.accessionnumber,
                st.patientid,
                st.patientname,
                sr.seriesinstanceuid,
                sr.seriesnumber,
                sr.modality,
                obj.sopinstanceuid,
                obj.sopclassuid,
                obj.imagenumber,
                obj.contentdate,
                obj.contenttime,
                obj.filepath,
                obj.transfersyntaxuid,
                obj.receivedat
            from public.objects obj
            join public.series sr on sr.seriesinstanceuid = obj.seriesinstanceuid
            join public.study st on st.studyinstanceuid = obj.studyinstanceuid
            where {' and '.join(clauses)}
            order by obj.receivedat desc nulls last, obj.imagenumber asc nulls last
            limit 1000
        """

    with database.clinic() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = list(cur.fetchall())

    return level, rows


def build_find_dataset(level: str, row: dict[str, Any], ae_title: str) -> Dataset:
    ds = Dataset()
    ds.QueryRetrieveLevel = level
    if level == "STUDY":
        ds.StudyInstanceUID = _string(row.get("studyinstanceuid"), 64)
        ds.StudyDate = _string(row.get("studydate"), 8)
        ds.StudyTime = _string(row.get("studytime"), 16)
        ds.StudyID = _string(row.get("studyid"), 16)
        ds.StudyDescription = _string(row.get("studydescription"), 128)
        ds.AccessionNumber = _string(row.get("accessionnumber"), 16)
        ds.PatientID = _string(row.get("patientid"), 64)
        ds.PatientName = _string(row.get("patientname"), 128)
        ds.PatientBirthDate = _string(row.get("patientbd"), 8)
        ds.PatientSex = _string(row.get("patientsex"), 16)
        ds.ModalitiesInStudy = _string(row.get("studymodality"), 16)
        ds.ReferringPhysicianName = _string(row.get("referphysician"), 128)
        ds.InstitutionName = _string(row.get("institutionname"), 128)
        ds.NumberOfStudyRelatedSeries = int(row.get("number_of_study_related_series") or 0)
        ds.NumberOfStudyRelatedInstances = int(row.get("number_of_study_related_instances") or 0)
    elif level == "SERIES":
        ds.StudyInstanceUID = _string(row.get("studyinstanceuid"), 64)
        ds.SeriesInstanceUID = _string(row.get("seriesinstanceuid"), 64)
        ds.SeriesNumber = _string(row.get("seriesnumber"), 12)
        ds.SeriesDate = _string(row.get("seriesdate"), 8)
        ds.SeriesTime = _string(row.get("seriestime"), 16)
        ds.SeriesDescription = _string(row.get("seriesdescription"), 128)
        ds.Modality = _string(row.get("modality"), 16)
        ds.PatientID = _string(row.get("patientid"), 64)
        ds.PatientName = _string(row.get("patientname"), 128)
        ds.PatientBirthDate = _string(row.get("patientbd"), 8)
        ds.PatientSex = _string(row.get("patientsex"), 16)
        ds.NumberOfSeriesRelatedInstances = int(row.get("number_of_series_related_instances") or 0)
    else:
        ds.StudyInstanceUID = _string(row.get("studyinstanceuid"), 64)
        ds.SeriesInstanceUID = _string(row.get("seriesinstanceuid"), 64)
        ds.SOPInstanceUID = _string(row.get("sopinstanceuid"), 64)
        ds.SOPClassUID = _string(row.get("sopclassuid"), 64)
        ds.InstanceNumber = _int(row.get("imagenumber")) or 0
        ds.ContentDate = _string(row.get("contentdate"), 8)
        ds.ContentTime = _string(row.get("contenttime"), 16)
        ds.PatientID = _string(row.get("patientid"), 64)
        ds.PatientName = _string(row.get("patientname"), 128)
        ds.Modality = _string(row.get("modality"), 16)

    ds.RetrieveAETitle = ae_title[:16]
    return ds


def retrieve_matches(database: Database, identifier: Dataset) -> list[dict[str, Any]]:
    level, _ = find_matches(database, identifier)
    clauses = ["1 = 1"]
    params: list[Any] = []
    _apply_study_filters(identifier, clauses, params)

    series_uid = _string(getattr(identifier, "SeriesInstanceUID", ""), 64)
    if series_uid:
        clauses.append("obj.seriesinstanceuid = %s")
        params.append(series_uid)

    sop_uid = _string(getattr(identifier, "SOPInstanceUID", ""), 64)
    if sop_uid:
        clauses.append("obj.sopinstanceuid = %s")
        params.append(sop_uid)

    sql = f"""
        select
            obj.sopinstanceuid,
            obj.sopclassuid,
            obj.transfersyntaxuid,
            obj.filepath,
            obj.studyinstanceuid,
            obj.seriesinstanceuid
        from public.objects obj
        join public.study st on st.studyinstanceuid = obj.studyinstanceuid
        where {' and '.join(clauses)} and coalesce(obj.filepath, '') <> ''
        order by obj.receivedat asc nulls last, obj.imagenumber asc nulls last
        limit 2000
    """
    with database.clinic() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = list(cur.fetchall())

    if level not in {"STUDY", "SERIES", "IMAGE"}:
        raise ValueError("QueryRetrieveLevel invalido.")
    return rows


def move_contexts(matches: list[dict[str, Any]]) -> list[Any]:
    contexts: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for row in matches:
        abstract_syntax = _string(row.get("sopclassuid"), 64)
        transfer_syntax = _string(row.get("transfersyntaxuid"), 64)
        if not abstract_syntax:
            continue
        key = (abstract_syntax, transfer_syntax or "")
        if key in seen:
            continue
        seen.add(key)
        if transfer_syntax:
            contexts.append(build_context(abstract_syntax, [transfer_syntax]))
        else:
            contexts.append(build_context(abstract_syntax))
    return contexts[:128]


def load_dataset(filepath: str) -> Dataset:
    return dcmread(str(filepath))


def list_studies(database: Database, limit: int = 50) -> list[dict[str, Any]]:
    with database.clinic() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    st.studyinstanceuid,
                    st.studydate,
                    st.studytime,
                    st.accessionnumber,
                    st.studydescription,
                    st.studymodality,
                    st.patientid,
                    st.patientname,
                    count(distinct sr.seriesinstanceuid) as series_count,
                    count(obj.sopinstanceuid) as object_count,
                    max(obj.receivedat) as last_received_at
                from public.study st
                left join public.series sr on sr.studyinstanceuid = st.studyinstanceuid
                left join public.objects obj on obj.studyinstanceuid = st.studyinstanceuid
                group by
                    st.studyinstanceuid, st.studydate, st.studytime, st.accessionnumber,
                    st.studydescription, st.studymodality, st.patientid, st.patientname
                order by max(obj.receivedat) desc nulls last, st.studydate desc nulls last
                limit %s
                """,
                (limit,),
            )
            return list(cur.fetchall())


def study_detail(database: Database, study_instance_uid: str) -> dict[str, Any] | None:
    with database.clinic() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select *
                from public.study
                where studyinstanceuid = %s
                """,
                (study_instance_uid,),
            )
            study = cur.fetchone()
            if not study:
                return None
            cur.execute(
                """
                select
                    sr.*,
                    count(obj.sopinstanceuid) as object_count
                from public.series sr
                left join public.objects obj on obj.seriesinstanceuid = sr.seriesinstanceuid
                where sr.studyinstanceuid = %s
                group by sr.seriesinstanceuid
                order by sr.seriesnumber asc nulls last
                """,
                (study_instance_uid,),
            )
            series = list(cur.fetchall())
            cur.execute(
                """
                select
                    sopinstanceuid,
                    sopclassuid,
                    imagenumber,
                    contentdate,
                    contenttime,
                    seriesinstanceuid,
                    studyinstanceuid,
                    filepath,
                    transfersyntaxuid,
                    receivedat
                from public.objects
                where studyinstanceuid = %s
                order by receivedat desc nulls last, imagenumber asc nulls last
                limit 500
                """,
                (study_instance_uid,),
            )
            instances = list(cur.fetchall())
    return {"study": study, "series": series, "instances": instances}
