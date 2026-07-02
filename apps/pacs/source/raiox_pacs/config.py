from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def env_json(name: str, default: object) -> object:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def resolve_local_path(path: str) -> str:
    candidate = (path or "").strip()
    if not candidate:
        return candidate
    if os.name != "nt":
        if candidate.startswith("/"):
            return candidate
        if len(candidate) > 2 and candidate[1] == ":":
            drive = candidate[0].lower()
            tail = candidate[2:].replace("\\", "/").lstrip("/")
            return f"/mnt/{drive}/{tail}"
    return candidate


def parse_database_url(value: str) -> dict[str, str]:
    raw = (value or "").strip()
    if not raw:
        return {}
    try:
        parsed = urlsplit(raw)
    except Exception:
        return {}
    if parsed.scheme not in {"postgres", "postgresql"}:
        return {}

    query = parse_qs(parsed.query, keep_blank_values=True)
    payload: dict[str, str] = {
        "host": parsed.hostname or "",
        "port": str(parsed.port or 5432),
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": unquote(parsed.path.lstrip("/") or ""),
        "sslmode": str((query.get("sslmode") or [""])[0] or "").strip(),
    }
    return payload


@dataclass(slots=True)
class Settings:
    app_debug: bool
    app_host: str
    app_port: int
    database_url: str
    pg_host: str
    pg_port: int
    pg_user: str
    pg_password: str
    pg_database: str
    pg_sslmode: str
    pacs_router_database: str
    pacs_aet: str
    dicom_bind_host: str
    dicom_port: int
    dicom_status_host: str
    pacs_station_aet: str
    pacs_institution_name: str
    pacs_imagebox_path: str
    pacs_web_url: str
    rad_uid_root: str
    worklist_bind_host: str
    worklist_port: int
    worklist_status_host: str
    worklist_ae_title: str
    sip_enabled: bool
    sip_mode_active: str
    sip_ws_url: str
    sip_domain: str
    sip_registrar_server: str
    sip_outbound_proxy: str
    sip_prefix: str
    sip_caller_id_template: str
    sip_auto_register: bool
    panel_video_url: str
    panel_title: str
    panel_subtitle: str
    panel_destinations: list[str]
    move_destinations: dict[str, list[object]]
    auto_bootstrap_schema: bool
    runtime_root: Path
    root_dir: Path

    @classmethod
    def load(cls, root_dir: Path) -> "Settings":
        env_path = root_dir / ".env"
        if load_dotenv is not None and env_path.exists():
            load_dotenv(env_path, override=False)
        move_destinations = env_json("DICOM_MOVE_DESTINATIONS", {})
        if not isinstance(move_destinations, dict):
            move_destinations = {}
        database_url = (os.getenv("DATABASE_URL", "") or "").strip()
        database_url_values = parse_database_url(database_url)
        app_port = int(os.getenv("PORT", os.getenv("APP_PORT", "5020")))
        runtime_root_raw = os.getenv("RUNTIME_ROOT", "").strip() or str(root_dir / "runtime")
        runtime_root = Path(resolve_local_path(runtime_root_raw))
        default_imagebox = str(runtime_root / "imagebox")
        default_pacs_web_url = (
            os.getenv("RENDER_EXTERNAL_URL", "").strip()
            or f"http://localhost:{app_port}"
        )

        return cls(
            app_debug=env_flag("APP_DEBUG"),
            app_host=os.getenv("APP_HOST", "0.0.0.0").strip() or "0.0.0.0",
            app_port=app_port,
            database_url=database_url,
            pg_host=os.getenv("PGHOST", database_url_values.get("host", "127.0.0.1")).strip() or "127.0.0.1",
            pg_port=int(os.getenv("PGPORT", database_url_values.get("port", "5432"))),
            pg_user=os.getenv("PGUSER", database_url_values.get("user", "postgres")).strip() or "postgres",
            pg_password=os.getenv("PGPASSWORD", database_url_values.get("password", "rocklee23")),
            pg_database=os.getenv("PGDATABASE", database_url_values.get("database", "raioxpacs")).strip() or "raioxpacs",
            pg_sslmode=os.getenv("PGSSLMODE", database_url_values.get("sslmode", "")).strip(),
            pacs_router_database=os.getenv("PACS_ROUTER_DATABASE", "").strip(),
            pacs_aet=os.getenv("PACS_AET", "PACSrenan").strip() or "PACSrenan",
            dicom_bind_host=os.getenv("DICOM_BIND_HOST", "0.0.0.0").strip() or "0.0.0.0",
            dicom_port=int(os.getenv("DICOM_PORT", "11112")),
            dicom_status_host=os.getenv("DICOM_STATUS_HOST", "127.0.0.1").strip() or "127.0.0.1",
            pacs_station_aet=os.getenv("PACS_STATION_AET", os.getenv("PACS_AET", "PACSrenan")).strip() or "PACSrenan",
            pacs_institution_name=os.getenv("PACS_INSTITUTION_NAME", "Clinica de Radiologia").strip() or "Clinica de Radiologia",
            pacs_imagebox_path=resolve_local_path(
                os.getenv("PACS_IMAGEBOX_PATH", default_imagebox).strip()
                or default_imagebox
            ),
            pacs_web_url=os.getenv("PACS_WEB_URL", default_pacs_web_url).strip() or default_pacs_web_url,
            rad_uid_root=os.getenv("RAD_UID_ROOT", "2.25").strip() or "2.25",
            worklist_bind_host=os.getenv("WORKLIST_BIND_HOST", "0.0.0.0").strip() or "0.0.0.0",
            worklist_port=int(os.getenv("WORKLIST_PORT", "11115")),
            worklist_status_host=os.getenv("WORKLIST_STATUS_HOST", "127.0.0.1").strip() or "127.0.0.1",
            worklist_ae_title=os.getenv("WORKLIST_AE_TITLE", "RAIOXMWL").strip() or "RAIOXMWL",
            sip_enabled=env_flag("SIP_ENABLED", "0"),
            sip_mode_active=os.getenv("SIP_MODE_ACTIVE", "freepbx").strip() or "freepbx",
            sip_ws_url=os.getenv("SIP_FREEPBX_WS_URL", "").strip(),
            sip_domain=os.getenv("SIP_FREEPBX_DOMAIN", "").strip(),
            sip_registrar_server=os.getenv("SIP_FREEPBX_REGISTRAR_SERVER", "").strip(),
            sip_outbound_proxy=os.getenv("SIP_OUTBOUND_PROXY", "").strip(),
            sip_prefix=os.getenv("SIP_PREFIX", "").strip(),
            sip_caller_id_template=os.getenv("SIP_CALLER_ID_TEMPLATE", "{nome} raioXPacs").strip() or "{nome} raioXPacs",
            sip_auto_register=env_flag("SIP_AUTO_REGISTER", "1"),
            panel_video_url=os.getenv("PANEL_VIDEO_URL", "").strip(),
            panel_title=os.getenv("PANEL_TITLE", "Painel de Chamadas").strip() or "Painel de Chamadas",
            panel_subtitle=os.getenv("PANEL_SUBTITLE", "Clinica de Radiologia").strip() or "Clinica de Radiologia",
            panel_destinations=[
                str(item).strip()
                for item in env_json(
                    "PANEL_DESTINATIONS",
                    ["Recepcao", "Sala de Raios-X", "Tomografia", "Ultrassom", "Entrega de Exames"],
                )
                if str(item).strip()
            ],
            move_destinations={
                str(key).strip().upper(): list(value)
                for key, value in move_destinations.items()
                if str(key).strip() and isinstance(value, list) and len(value) >= 2
            },
            auto_bootstrap_schema=env_flag("AUTO_BOOTSTRAP_SCHEMA", "1"),
            runtime_root=runtime_root,
            root_dir=root_dir,
        )
