from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .db import Database


SCHEMA_SQL = """
create schema if not exists raiox;

create table if not exists raiox.patient (
    id bigserial primary key,
    external_patient_id varchar(64),
    full_name varchar(160) not null,
    birth_date date,
    sex varchar(16),
    cpf varchar(14),
    phone varchar(32),
    email varchar(160),
    notes text,
    created_at timestamp not null default now(),
    updated_at timestamp not null default now()
);

create unique index if not exists raiox_patient_cpf_uidx on raiox.patient (cpf) where cpf is not null and cpf <> '';
create index if not exists raiox_patient_name_idx on raiox.patient (full_name);

create table if not exists raiox.procedure_catalog (
    id bigserial primary key,
    code varchar(32) not null unique,
    name varchar(160) not null,
    modality varchar(16),
    default_price numeric(12,2) not null default 0,
    duration_minutes integer not null default 20,
    active boolean not null default true,
    created_at timestamp not null default now(),
    updated_at timestamp not null default now()
);

create table if not exists raiox.convenio (
    id bigserial primary key,
    code varchar(32) not null unique,
    name varchar(160) not null,
    active boolean not null default true,
    created_at timestamp not null default now(),
    updated_at timestamp not null default now()
);

create table if not exists raiox.convenio_price (
    id bigserial primary key,
    convenio_id bigint not null references raiox.convenio(id) on delete cascade,
    procedure_id bigint references raiox.procedure_catalog(id) on delete cascade,
    incidences_count integer not null default 1,
    price numeric(12,2) not null default 0,
    active boolean not null default true,
    created_at timestamp not null default now(),
    updated_at timestamp not null default now(),
    unique (convenio_id, procedure_id, incidences_count)
);

create table if not exists raiox.exam_order (
    id bigserial primary key,
    patient_id bigint not null references raiox.patient(id) on delete restrict,
    reference varchar(64),
    notes text,
    discount numeric(12,2) not null default 0,
    amount numeric(12,2) not null default 0,
    net_amount numeric(12,2) not null default 0,
    billing_status varchar(24) not null default 'pending',
    status varchar(24) not null default 'draft',
    paid_at timestamp,
    payment_method varchar(32),
    created_at timestamp not null default now(),
    updated_at timestamp not null default now()
);

create table if not exists raiox.exam (
    id bigserial primary key,
    patient_id bigint not null references raiox.patient(id) on delete restrict,
    procedure_id bigint not null references raiox.procedure_catalog(id) on delete restrict,
    order_id bigint references raiox.exam_order(id) on delete set null,
    convenio_code varchar(32) not null default 'PARTICULAR',
    incidences_count integer not null default 1,
    accession_number varchar(16) not null unique,
    study_instance_uid varchar(64) not null unique,
    requested_procedure_id varchar(32),
    requested_description varchar(160),
    referring_physician varchar(128),
    performing_physician varchar(128),
    scheduled_at timestamp,
    modality varchar(16),
    priority varchar(16) not null default 'ROUTINE',
    station_aet varchar(32),
    status varchar(24) not null default 'scheduled',
    workflow_stage varchar(24) not null default 'draft',
    worklist_status varchar(24) not null default 'draft',
    pacs_study_found boolean not null default false,
    pacs_report_status varchar(24),
    price numeric(12,2) not null default 0,
    billing_status varchar(24) not null default 'pending',
    notes text,
    created_at timestamp not null default now(),
    updated_at timestamp not null default now()
);

alter table raiox.exam add column if not exists workflow_stage varchar(24) not null default 'reception';
alter table raiox.exam alter column workflow_stage set default 'draft';
alter table raiox.exam alter column worklist_status set default 'draft';
alter table raiox.exam add column if not exists convenio_code varchar(32) not null default 'PARTICULAR';
alter table raiox.exam add column if not exists incidences_count integer not null default 1;
alter table raiox.exam add column if not exists order_id bigint references raiox.exam_order(id) on delete set null;
alter table raiox.exam alter column convenio_code set default 'PARTICULAR';
alter table raiox.exam alter column incidences_count set default 1;
create index if not exists raiox_exam_order_idx on raiox.exam (order_id);

update raiox.exam
set workflow_stage = case workflow_stage
    when 'reception' then 'draft'
    when 'waiting' then 'arrived'
    when 'worklist' then 'scheduled'
    when 'acquisition' then 'started'
    when 'delivery' then 'finalized'
    else workflow_stage
end
where workflow_stage in ('reception', 'waiting', 'worklist', 'acquisition', 'delivery');

update raiox.exam
set worklist_status = case worklist_status
    when 'pending' then 'draft'
    when 'published' then 'scheduled'
    else worklist_status
end
where worklist_status in ('pending', 'published');

update raiox.exam
set convenio_code = coalesce(nullif(convenio_code, ''), 'PARTICULAR'),
    incidences_count = case
        when incidences_count between 1 and 3 then incidences_count
        else 1
    end;

create index if not exists raiox_exam_patient_idx on raiox.exam (patient_id);
create index if not exists raiox_exam_status_idx on raiox.exam (status);
create index if not exists raiox_exam_schedule_idx on raiox.exam (scheduled_at);
create index if not exists raiox_exam_workflow_idx on raiox.exam (workflow_stage);
create index if not exists raiox_exam_worklist_idx on raiox.exam (worklist_status);
create index if not exists raiox_exam_convenio_idx on raiox.exam (convenio_code, incidences_count);

create table if not exists raiox.medical_report (
    exam_id bigint primary key references raiox.exam(id) on delete cascade,
    study_instance_uid varchar(64),
    doctor_name varchar(120),
    status varchar(24) not null default 'draft',
    title varchar(160),
    body text,
    impression text,
    signed_at timestamp,
    created_at timestamp not null default now(),
    updated_at timestamp not null default now()
);

create index if not exists raiox_medical_report_status_idx on raiox.medical_report (status);

create table if not exists raiox.exam_attachment (
    id bigserial primary key,
    exam_id bigint not null references raiox.exam(id) on delete cascade,
    kind varchar(24) not null default 'image',
    original_name varchar(255) not null,
    stored_name varchar(255) not null,
    mime_type varchar(160),
    file_ext varchar(16),
    file_size bigint,
    file_path text not null,
    created_at timestamp not null default now()
);

create index if not exists raiox_exam_attachment_exam_idx on raiox.exam_attachment (exam_id, created_at desc);

create table if not exists raiox.share_access (
    id bigserial primary key,
    slug varchar(64) not null unique,
    scope_type varchar(16) not null,
    patient_id bigint references raiox.patient(id) on delete cascade,
    exam_id bigint references raiox.exam(id) on delete cascade,
    username varchar(64) not null,
    password_hash varchar(255) not null,
    note varchar(160),
    expires_at timestamp,
    active boolean not null default true,
    last_login_at timestamp,
    created_at timestamp not null default now(),
    updated_at timestamp not null default now()
);

create index if not exists raiox_share_scope_idx on raiox.share_access (scope_type, patient_id, exam_id, active);

create table if not exists raiox.invoice (
    id bigserial primary key,
    exam_id bigint references raiox.exam(id) on delete cascade,
    order_id bigint references raiox.exam_order(id) on delete cascade,
    invoice_number varchar(32) not null unique,
    amount numeric(12,2) not null,
    discount numeric(12,2) not null default 0,
    status varchar(24) not null default 'open',
    due_date date,
    paid_at timestamp,
    payment_method varchar(32),
    notes text,
    created_at timestamp not null default now(),
    updated_at timestamp not null default now(),
    check (exam_id is not null or order_id is not null)
);

create unique index if not exists raiox_invoice_exam_idx on raiox.invoice (exam_id) where exam_id is not null;
create unique index if not exists raiox_invoice_order_idx on raiox.invoice (order_id) where order_id is not null;
create index if not exists raiox_invoice_status_idx on raiox.invoice (status);
create index if not exists raiox_invoice_due_idx on raiox.invoice (due_date);

create table if not exists raiox.sync_log (
    id bigserial primary key,
    exam_id bigint references raiox.exam(id) on delete set null,
    target varchar(32) not null,
    event_type varchar(32) not null,
    success boolean not null default true,
    message text,
    payload jsonb,
    created_at timestamp not null default now()
);

create table if not exists raiox.operator (
    id bigserial primary key,
    name varchar(120) not null,
    role varchar(64),
    sector varchar(64),
    extension varchar(32),
    sip_username varchar(64),
    sip_password varchar(128),
    active boolean not null default true,
    created_at timestamp not null default now(),
    updated_at timestamp not null default now()
);

create index if not exists raiox_operator_active_idx on raiox.operator (active);
create index if not exists raiox_operator_name_idx on raiox.operator (name);

create table if not exists raiox.chat_message (
    id bigserial primary key,
    sender_operator_id bigint not null references raiox.operator(id) on delete cascade,
    recipient_operator_id bigint not null references raiox.operator(id) on delete cascade,
    body text not null,
    read_at timestamp,
    created_at timestamp not null default now()
);

create index if not exists raiox_chat_sender_idx on raiox.chat_message (sender_operator_id, created_at desc);
create index if not exists raiox_chat_recipient_idx on raiox.chat_message (recipient_operator_id, read_at, created_at desc);

create table if not exists raiox.camera (
    id bigserial primary key,
    name varchar(120) not null,
    mode varchar(16) not null default 'rtsp',
    source_url text not null,
    transport varchar(8) not null default 'tcp',
    enabled boolean not null default true,
    created_at timestamp not null default now(),
    updated_at timestamp not null default now()
);

create index if not exists raiox_camera_enabled_idx on raiox.camera (enabled);

create table if not exists raiox.system_settings (
    key varchar(64) primary key,
    value jsonb not null default '{}'::jsonb,
    updated_at timestamp not null default now()
);

create table if not exists raiox.call_ticket (
    id bigserial primary key,
    exam_id bigint not null unique references raiox.exam(id) on delete cascade,
    queue_date date not null default current_date,
    ticket_number integer not null,
    status varchar(24) not null default 'waiting',
    destination varchar(64),
    called_at timestamp,
    completed_at timestamp,
    created_at timestamp not null default now(),
    updated_at timestamp not null default now(),
    unique (queue_date, ticket_number)
);

create index if not exists raiox_call_ticket_status_idx on raiox.call_ticket (queue_date, status);
create index if not exists raiox_call_ticket_exam_idx on raiox.call_ticket (exam_id);

create table if not exists raiox.budget (
    id bigserial primary key,
    patient_id bigint not null references raiox.patient(id) on delete cascade,
    reference varchar(64),
    items_json jsonb not null,
    discount numeric(12,2) not null default 0,
    total_amount numeric(12,2) not null default 0,
    net_amount numeric(12,2) not null default 0,
    status varchar(24) not null default 'draft',
    created_at timestamp not null default now(),
    updated_at timestamp not null default now()
);

create index if not exists raiox_budget_patient_idx on raiox.budget (patient_id);
create index if not exists raiox_budget_status_idx on raiox.budget (status);
create index if not exists raiox_budget_created_idx on raiox.budget (created_at desc);

create table if not exists raiox.call_log (
    id bigserial primary key,
    ticket_id bigint not null references raiox.call_ticket(id) on delete cascade,
    exam_id bigint not null references raiox.exam(id) on delete cascade,
    destination varchar(64),
    called_by bigint references raiox.operator(id) on delete set null,
    created_at timestamp not null default now()
);

create index if not exists raiox_call_log_ticket_idx on raiox.call_log (ticket_id, created_at desc);

create table if not exists public.worklist (
    patientid varchar(64),
    patientname varchar(128),
    patientbd varchar(8),
    patientsex varchar(16),
    referringphysician varchar(64),
    accessionnumber varchar(16) not null primary key,
    medicalalerts varchar(64),
    reasonforprocedure varchar(64),
    currentlocation varchar(64),
    studyinstanceuid varchar(64),
    requestedproceduredescription varchar(64),
    modality varchar(16),
    institutionname varchar(64),
    spsdate varchar(8),
    spsstarttime varchar(16),
    performingphysician varchar(64),
    spsdescription varchar(64),
    spsid varchar(32),
    spsstatus varchar(16),
    scheduledstation varchar(16),
    requestedprocedureid varchar(16),
    sopinstanceuid varchar(64),
    requestedprocedurepriority varchar(8)
);

create table if not exists public.study (
    studyinstanceuid varchar(64) not null primary key,
    studydate varchar(8),
    studytime varchar(16),
    studyid varchar(16),
    studydescription varchar(128),
    accessionnumber varchar(16),
    referphysician varchar(128),
    studymodality varchar(64),
    stationname varchar(32),
    institutionname varchar(128),
    studypath varchar(255),
    patientid varchar(64),
    patientname varchar(128),
    patientsex varchar(16),
    patientbd varchar(8),
    reportts varchar(16),
    operatorsname varchar(128),
    medicalalerts varchar(64),
    readingphysician varchar(128),
    patientcomments varchar(1024)
);

create table if not exists public.series (
    seriesinstanceuid varchar(64) not null primary key,
    seriesnumber varchar(12),
    seriesdate varchar(8),
    seriestime varchar(16),
    seriesdescription varchar(128),
    modality varchar(16),
    institutionname varchar(128),
    manufacturer varchar(128),
    modelname varchar(128),
    bodypartexamined varchar(64),
    protocolname varchar(128),
    seriespath varchar(255),
    studyinstanceuid varchar(64)
);

create index if not exists series_index on public.series (studyinstanceuid);

create table if not exists public.reports (
    studyinstanceuid varchar(64) not null primary key,
    username varchar(16),
    status integer,
    assigned varchar(12),
    preliminary varchar(12),
    final varchar(12),
    addendum varchar(12)
);

create table if not exists public.objects (
    sopinstanceuid varchar(64) not null primary key,
    sopclassuid varchar(64),
    imagenumber integer,
    contentdate varchar(8),
    contenttime varchar(16),
    acquisitionnumber integer,
    acquisitiondate varchar(8),
    acquisitiontime varchar(16),
    slicelocation varchar(32),
    receiveddate varchar(8),
    seriesinstanceuid varchar(64),
    studyinstanceuid varchar(64),
    convolutionkernel varchar(32),
    backupstatus integer,
    keyobject varchar(1),
    filepath text,
    transfersyntaxuid varchar(64),
    filesize bigint,
    receivedat timestamp not null default now()
);

alter table public.objects add column if not exists filepath text;
alter table public.objects add column if not exists transfersyntaxuid varchar(64);
alter table public.objects add column if not exists filesize bigint;
alter table public.objects add column if not exists receivedat timestamp not null default now();

create index if not exists se_object_index on public.objects (seriesinstanceuid);
create index if not exists st_object_index on public.objects (studyinstanceuid);
create index if not exists object_receivedat_idx on public.objects (receivedat desc);
"""


def _default_settings(database: Database) -> dict[str, Any]:
    settings = database.settings
    return {
        "sip_config": {
            "enabled": settings.sip_enabled,
            "mode_active": settings.sip_mode_active,
            "freepbx": {
                "ws_url": settings.sip_ws_url,
                "domain": settings.sip_domain,
                "registrar_server": settings.sip_registrar_server,
                "outbound_proxy": settings.sip_outbound_proxy,
                "prefix": settings.sip_prefix,
                "caller_id_template": settings.sip_caller_id_template,
                "auto_register": settings.sip_auto_register,
            },
        },
        "panel_config": {
            "title": settings.panel_title,
            "subtitle": settings.panel_subtitle,
            "video_url": settings.panel_video_url,
            "destinations": settings.panel_destinations,
            "auto_announce": True,
        },
        "pricing_config": {
            "convenios": [
                {
                    "code": "PARTICULAR",
                    "name": "Particular",
                    "prices": {"1": 0, "2": 0, "3": 0},
                },
            ]
        },
        "integration_config": {
            "pacs": {
                "mode": "local",
                "host": "",
                "port": settings.dicom_port,
                "ae_title": settings.pacs_aet,
            },
            "worklist": {
                "mode": "local",
                "host": "",
                "port": settings.worklist_port,
                "ae_title": settings.worklist_ae_title,
            },
            "web": {
                "public_url": settings.pacs_web_url,
            },
        },
    }


def _seed_settings(cur: Any, database: Database) -> None:
    for key, value in _default_settings(database).items():
        if key == "integration_config" and _should_force_local_integration(database):
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
            continue

        cur.execute(
            """
            insert into raiox.system_settings (key, value)
            values (%s, %s::jsonb)
            on conflict (key) do nothing
            """,
            (key, json.dumps(value)),
        )


def _should_force_local_integration(database: Database) -> bool:
    web_url = (database.settings.pacs_web_url or "").strip().lower()
    return web_url.startswith("http://localhost") or web_url.startswith("https://localhost") or web_url.startswith("http://127.0.0.1") or web_url.startswith("https://127.0.0.1")


def _seed_default_operators(cur: Any) -> None:
    cur.execute("select count(*) as total from raiox.operator")
    row = cur.fetchone() or {}
    if int(row.get("total") or 0) > 0:
        return

    cur.executemany(
        """
        insert into raiox.operator (name, role, sector, extension, sip_username, sip_password, active)
        values (%s, %s, %s, %s, %s, %s, %s)
        """,
        [
            ("Recepcao", "department", "Recepcao", None, None, None, True),
            ("Sala de Raiox", "department", "Sala de Raiox", None, None, None, True),
            ("Sala de Ultrassom", "department", "Sala de Ultrassom", None, None, None, True),
            ("Sala Raio-X", "tecnico", "Raio-X", "202", "202", "", True),
            ("Tomografia", "tecnico", "Tomografia", "203", "203", "", True),
            ("Ultrassom", "medico", "Ultrassom", "204", "204", "", True),
            ("Financeiro", "financeiro", "Financeiro", "205", "205", "", True),
            ("Laudos", "radiologista", "Laudos", "206", "206", "", True),
        ],
    )


def _seed_default_exam_catalog(cur: Any, database: Database) -> None:
    root_dir = database.settings.root_dir
    seed_path = root_dir / "scripts" / "import_tabela_exames.sql"
    if not seed_path.is_file():
        return

    sql_text = seed_path.read_text(encoding="utf-8")
    normalized_sql = sql_text.replace("'CR'", "'DR'").replace("'RX'", "'DR'")
    seed_hash = hashlib.sha256(normalized_sql.encode("utf-8")).hexdigest()

    cur.execute("select value from raiox.system_settings where key = %s", ("exam_catalog_seed_sha",))
    row = cur.fetchone()
    current_hash = ""
    if row:
        value = row.get("value")
        if isinstance(value, dict):
            current_hash = str(value.get("hash") or value.get("sha") or "")
        elif isinstance(value, str):
            current_hash = value.strip()
    if current_hash == seed_hash:
        return

    cur.execute(normalized_sql)
    cur.execute(
        """
        insert into raiox.system_settings (key, value, updated_at)
        values (%s, %s::jsonb, now())
        on conflict (key) do update
        set value = excluded.value,
            updated_at = now()
        """,
        ("exam_catalog_seed_sha", json.dumps({"hash": seed_hash, "source": seed_path.name})),
    )


def _normalize_legacy_modalities(cur: Any) -> None:
    cur.execute(
        """
        update raiox.procedure_catalog
        set modality = case
            when upper(coalesce(modality, '')) = 'US' then 'US'
            when upper(coalesce(modality, '')) in ('RX', 'CR', 'DX', 'DR') then 'DR'
            else modality
        end
        where upper(coalesce(modality, '')) in ('RX', 'CR', 'DX', 'DR', 'US')
        """
    )
    cur.execute(
        """
        update raiox.exam
        set modality = case
            when upper(coalesce(modality, '')) = 'US' then 'US'
            when upper(coalesce(modality, '')) in ('RX', 'CR', 'DX', 'DR') then 'DR'
            else modality
        end
        where upper(coalesce(modality, '')) in ('RX', 'CR', 'DX', 'DR', 'US')
        """
    )
    cur.execute(
        """
        update public.worklist
        set modality = case
            when upper(coalesce(modality, '')) = 'US' then 'US'
            when upper(coalesce(modality, '')) in ('RX', 'CR', 'DX', 'DR') then 'DR'
            else modality
        end
        where upper(coalesce(modality, '')) in ('RX', 'CR', 'DX', 'DR', 'US')
        """
    )


def ensure_schema(database: Database) -> None:
    with database.clinic() as conn:
        with conn.cursor() as cur:
            cur.execute("select pg_advisory_lock(%s)", (420502011,))
            try:
                cur.execute(SCHEMA_SQL)
                _seed_settings(cur, database)
                _seed_default_operators(cur)
                _seed_default_exam_catalog(cur, database)
                _normalize_legacy_modalities(cur)
            finally:
                cur.execute("select pg_advisory_unlock(%s)", (420502011,))
        conn.commit()
