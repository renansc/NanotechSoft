from __future__ import annotations

import os
from datetime import date
from io import BytesIO
from mimetypes import guess_type
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, redirect, render_template, request, send_file, send_from_directory, session, url_for

from .bootstrap import ensure_schema
from .camera_runtime import CameraRuntime
from .config import Settings
from .db import Database
from .services import ClinicService
from .utils import normalize_json

APP_NAME = "Laboratorio Santa Terezinha"
BROWSER_TITLE = "Lab. S. Terezinha"
VIEWER_NAME = "Viewer Laboratorio Santa Terezinha"
SHARE_NAME = "Compartilhamento de Imagens Santa Terezinha"
CONFIG_ADMIN_PASSWORD = "St123456!"
CONFIG_ADMIN_PASSWORDS = {
    password
    for password in {
        CONFIG_ADMIN_PASSWORD,
        (os.getenv("APP_ADMIN_PASSWORD") or "").strip(),
    }
    if password
}


def create_app() -> Flask:
    project_root = Path(__file__).resolve().parent.parent
    docs_root = project_root / "docs"
    asset_version = str(
        int(
            max(
                (project_root / "templates" / "index.html").stat().st_mtime,
                (project_root / "templates" / "login.html").stat().st_mtime,
                (project_root / "static" / "app.js").stat().st_mtime,
                (project_root / "static" / "style.css").stat().st_mtime,
            )
        )
    )
    settings = Settings.load(project_root)
    database = Database(settings)
    if settings.auto_bootstrap_schema:
        ensure_schema(database)
    camera_runtime = CameraRuntime(settings)
    service = ClinicService(database, settings, camera_runtime=camera_runtime)
    service.normalize_public_worklist_device_scope()
    if settings.auto_bootstrap_schema:
        service.ensure_chat_departments()
    camera_runtime.sync(service.list_cameras())

    app = Flask(
        __name__,
        template_folder=str(project_root / "templates"),
        static_folder=str(project_root / "static"),
    )
    app.config["DEBUG"] = settings.app_debug
    app.config["SECRET_KEY"] = os.getenv("APP_SECRET_KEY", "raioxpacs-share-dev-secret")

    def ok(payload: object, status: int = 200):
        return jsonify(normalize_json(payload)), status

    def fail(message: str, status: int = 400):
        return ok({"error": message}, status)

    def report_filters_from_request() -> dict[str, object]:
        period_mode = (request.args.get("period_mode") or "").strip().lower()
        period_value = (
            request.args.get("period_value")
            or request.args.get("period_date")
            or request.args.get("period_month")
            or ""
        ).strip()
        if not period_mode:
            period_mode = "month" if request.args.get("period_month") else "day"
        return {
            "period_mode": period_mode,
            "period_value": period_value,
            "convenio_code": (request.args.get("convenio_code") or "").strip(),
            "patient_id": (
                int(request.args.get("patient_id") or 0)
                if str(request.args.get("patient_id") or "").strip().isdigit()
                else None
            ),
        }

    def share_public_payload(share: dict[str, object] | None) -> dict[str, object] | None:
        if not share:
            return None
        return {
            "slug": share.get("slug"),
            "scope_type": share.get("scope_type"),
            "username": share.get("username"),
            "note": share.get("note"),
            "expires_at": share.get("expires_at"),
            "active": bool(share.get("active")),
            "last_login_at": share.get("last_login_at"),
        }

    def share_session_key(slug: str) -> str:
        return f"share-auth:{(slug or '').strip().lower()}"

    def share_authenticated(slug: str) -> bool:
        item = session.get(share_session_key(slug))
        return bool(isinstance(item, dict) and item.get("slug") == (slug or "").strip().lower())

    def require_share_session(slug: str) -> None:
        if not share_authenticated(slug):
            raise PermissionError("Sessao do compartilhamento expirou. Entre novamente.")

    def parse_optional_float(raw: str | None) -> float | None:
        value = (raw or "").strip()
        if not value:
            return None
        return float(value)

    def parse_preview_size(raw: str | None) -> int:
        value = (raw or "").strip()
        if not value:
            return 1200
        return max(128, min(int(value), 2048))

    def public_share_url(slug: str) -> str:
        config = service.get_integration_config()
        public_url = str((config.get("web") or {}).get("public_url") or "").strip().rstrip("/")
        if public_url:
            parts = urlsplit(public_url)
            if parts.scheme and parts.netloc:
                return f"{public_url}/share/{slug}"
        return url_for("share_portal", slug=slug, _external=True)

    def department_session_key() -> str:
        return "department_id"

    def admin_session_key() -> str:
        return "admin_unlocked"

    def current_user_role() -> str:
        if bool(session.get(admin_session_key())):
            return "admin"
        return str(session.get("user_role") or "technician").strip().lower() or "technician"

    def current_department_id() -> int | None:
        raw = session.get(department_session_key())
        try:
            return int(raw) if raw is not None and str(raw).strip() else None
        except (TypeError, ValueError):
            return None

    def require_admin_access() -> None:
        if current_user_role() != "admin":
            raise PermissionError("Acesso admin necessario para alterar a configuracao.")

    def require_exam_delete_access() -> None:
        if current_user_role() not in {"admin", "technician", "tecnico"}:
            raise PermissionError("Acesso tecnico necessario para excluir exame.")

    def build_preview_response(sop_instance_uid: str):
        window_center = parse_optional_float(request.args.get("wc"))
        window_width = parse_optional_float(request.args.get("ww"))
        invert = (request.args.get("invert") or "").strip().lower() in {"1", "true", "yes", "on"}
        max_size = parse_preview_size(request.args.get("size"))
        image_bytes, defaults = service.render_pacs_object_preview(
            sop_instance_uid,
            window_center=window_center,
            window_width=window_width,
            invert=invert,
            max_size=max_size,
        )
        response = send_file(
            BytesIO(image_bytes),
            mimetype="image/png",
            as_attachment=False,
            download_name=f"{sop_instance_uid}.png",
        )
        if defaults.get("window_center") is not None:
            response.headers["X-Window-Center"] = str(defaults["window_center"])
        if defaults.get("window_width") is not None:
            response.headers["X-Window-Width"] = str(defaults["window_width"])
        if defaults.get("photometric_interpretation"):
            response.headers["X-Photometric-Interpretation"] = str(defaults["photometric_interpretation"])
        if defaults.get("rows"):
            response.headers["X-Image-Rows"] = str(defaults["rows"])
        if defaults.get("columns"):
            response.headers["X-Image-Columns"] = str(defaults["columns"])
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.after_request
    def add_cache_headers(response):
        content_type = (response.headers.get("Content-Type") or "").lower()
        if content_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.get("/")
    def home():
        department_id = current_department_id()
        user_role = current_user_role()
        if not department_id and user_role != "admin":
            return redirect(url_for("login_page"))
        departments = service.list_chat_departments()
        current_department = None
        current_department_name = "Admin" if user_role == "admin" and not department_id else ""
        if department_id:
            current_department = next((item for item in departments if int(item["id"]) == department_id), None)
        if department_id and not current_department:
            session.pop(department_session_key(), None)
            session.pop(admin_session_key(), None)
            session.pop("user_role", None)
            session.modified = True
            return redirect(url_for("login_page"))
        if current_department:
            current_department_name = current_department.get("name") or ""
        return render_template(
            "index.html",
            app_name=APP_NAME,
            browser_title=BROWSER_TITLE,
            menu_brand_line_1="Laboratorio Santa",
            menu_brand_line_2="Terezinha",
            asset_version=asset_version,
            pacs_web_url=settings.pacs_web_url,
            pacs_imagebox_path=settings.pacs_imagebox_path,
            pg_database=settings.pg_database,
            pacs_aet=settings.pacs_aet,
            pacs_station_aet=settings.pacs_station_aet,
            dicom_port=settings.dicom_port,
            worklist_ae_title=settings.worklist_ae_title,
            worklist_port=settings.worklist_port,
            current_department_id=department_id,
            current_department_name=current_department_name,
            admin_unlocked=bool(session.get(admin_session_key())),
            user_role=user_role,
        )

    @app.get("/login")
    def login_page():
        if current_department_id() or current_user_role() == "admin":
            return redirect(url_for("home"))
        return render_template(
            "login.html",
            app_name=APP_NAME,
            browser_title=BROWSER_TITLE,
            asset_version=asset_version,
            departments=service.list_chat_departments(),
            selected_profile="technician",
            selected_department_id="",
        )

    @app.post("/login")
    def login_submit():
        try:
            department_id = int(request.form.get("department_id") or 0)
        except ValueError:
            department_id = 0
        profile = str(request.form.get("profile") or "technician").strip().lower() or "technician"
        password = str(request.form.get("password") or "")
        departments = service.list_chat_departments()
        selected = next((item for item in departments if int(item["id"]) == department_id), None)
        if profile != "admin" and not selected:
            return render_template(
                "login.html",
                app_name=APP_NAME,
                browser_title=BROWSER_TITLE,
                asset_version=asset_version,
                departments=departments,
                selected_profile=profile,
                selected_department_id=department_id,
                error="Selecione um departamento valido.",
            ), 400
        if profile == "admin":
            if password not in CONFIG_ADMIN_PASSWORDS:
                return render_template(
                    "login.html",
                    app_name=APP_NAME,
                    browser_title=BROWSER_TITLE,
                    asset_version=asset_version,
                    departments=departments,
                    selected_profile=profile,
                    selected_department_id=department_id,
                    error="Senha admin invalida.",
                ), 401
            session.pop(department_session_key(), None)
        else:
            session[department_session_key()] = int(selected["id"])
        if profile == "admin":
            session["user_role"] = "admin"
            session[admin_session_key()] = True
        else:
            session["user_role"] = "technician"
            session.pop(admin_session_key(), None)
        session.modified = True
        return redirect(url_for("home"))

    @app.get("/logout")
    def logout():
        session.pop(department_session_key(), None)
        session.pop(admin_session_key(), None)
        session.pop("user_role", None)
        session.modified = True
        return redirect(url_for("login_page"))

    @app.post("/api/auth/department")
    def update_department_session():
        try:
            department_id = int((request.get_json(force=True, silent=True) or {}).get("department_id") or 0)
            departments = service.list_chat_departments()
            if not any(int(item["id"]) == department_id for item in departments):
                raise ValueError("Departamento invalido.")
            session[department_session_key()] = department_id
            session.modified = True
            selected = next(item for item in departments if int(item["id"]) == department_id)
            return ok({
                "department_id": department_id,
                "department_name": selected.get("name") or "",
                "admin_unlocked": bool(session.get(admin_session_key())),
            })
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/docs")
    @app.get("/docs/")
    def docs_index():
        return redirect(url_for("docs_files", filename="index.html"))

    @app.get("/docs/<path:filename>")
    def docs_files(filename: str):
        return send_from_directory(str(docs_root), filename)

    @app.get("/viewer/exams/<int:exam_id>")
    def viewer_exam(exam_id: int):
        try:
            service.get_exam(exam_id)
            return render_template(
                "viewer.html",
                app_name=VIEWER_NAME,
                viewer_mode="internal",
                exam_id=exam_id,
                share_slug="",
                share=None,
            )
        except ValueError as exc:
            return render_template(
                "share_login.html",
                app_name=VIEWER_NAME,
                share=None,
                error=str(exc),
                share_slug="",
            ), 404

    @app.get("/share/<slug>")
    def share_portal(slug: str):
        try:
            share = share_public_payload(service.get_share_access_by_slug(slug))
        except ValueError as exc:
            return render_template(
                "share_login.html",
                app_name=SHARE_NAME,
                share=None,
                error=str(exc),
                share_slug=(slug or "").strip().lower(),
            ), 404

        if not share_authenticated(slug):
            return render_template(
                "share_login.html",
                app_name=SHARE_NAME,
                share=share,
                error="",
                share_slug=(slug or "").strip().lower(),
            )

        return render_template(
            "viewer.html",
            app_name=SHARE_NAME,
            viewer_mode="share",
            exam_id="",
            share_slug=(slug or "").strip().lower(),
            share=share,
        )

    @app.post("/share/<slug>/login")
    def share_login(slug: str):
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        try:
            share = service.authenticate_share(slug, username, password)
            session[share_session_key(slug)] = {
                "id": share["id"],
                "slug": share["slug"],
                "username": share["username"],
            }
            session.modified = True
            return redirect(url_for("share_portal", slug=share["slug"]))
        except ValueError as exc:
            share = None
            try:
                share = share_public_payload(service.get_share_access_by_slug(slug))
            except ValueError:
                share = None
            return render_template(
                "share_login.html",
                app_name=SHARE_NAME,
                share=share,
                error=str(exc),
                share_slug=(slug or "").strip().lower(),
            ), 401

    @app.post("/share/<slug>/logout")
    def share_logout(slug: str):
        session.pop(share_session_key(slug), None)
        session.modified = True
        return redirect(url_for("share_portal", slug=(slug or "").strip().lower()))

    @app.get("/camera-streams/<path:filename>")
    def camera_streams(filename: str):
        return send_from_directory(camera_runtime.stream_root, filename)

    @app.get("/media/exam-attachments/<int:attachment_id>")
    def exam_attachment_file(attachment_id: int):
        try:
            attachment = service.get_exam_attachment(attachment_id)
            download_name = attachment.get("original_name") or attachment.get("stored_name") or f"anexo-{attachment_id}"
            mimetype = attachment.get("mime_type") or guess_type(download_name)[0] or "application/octet-stream"
            return send_file(
                str(attachment["file_path"]),
                mimetype=mimetype,
                as_attachment=(request.args.get("download") or "0") == "1",
                download_name=download_name,
            )
        except FileNotFoundError:
            return fail("Arquivo anexado nao encontrado no disco. Reenvie o anexo deste exame.", 404)
        except ValueError as exc:
            return fail(str(exc), 404)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/media/pacs/objects/<path:sop_instance_uid>")
    def pacs_object_file(sop_instance_uid: str):
        try:
            obj = service.get_pacs_object(sop_instance_uid)
            return send_file(
                str(obj["filepath"]),
                mimetype="application/dicom",
                as_attachment=(request.args.get("download") or "1") != "0",
                download_name=f"{sop_instance_uid}.dcm",
            )
        except ValueError as exc:
            return fail(str(exc), 404)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/media/pacs/objects/<path:sop_instance_uid>/preview.png")
    def pacs_object_preview(sop_instance_uid: str):
        try:
            return build_preview_response(sop_instance_uid)
        except ValueError as exc:
            return fail(str(exc), 404)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/share/<slug>/media/exam-attachments/<int:attachment_id>")
    def shared_exam_attachment_file(slug: str, attachment_id: int):
        try:
            require_share_session(slug)
            attachment = service.get_shared_attachment(slug, attachment_id)
            mime_type = attachment.get("mime_type") or guess_type(attachment.get("original_name") or "")[0] or "application/octet-stream"
            if not str(mime_type).lower().startswith("image/"):
                raise ValueError("Este compartilhamento libera somente imagens.")
            download_name = attachment.get("original_name") or attachment.get("stored_name") or f"anexo-{attachment_id}"
            return send_file(
                str(attachment["file_path"]),
                mimetype=mime_type,
                as_attachment=False,
                download_name=download_name,
            )
        except FileNotFoundError:
            return fail("Arquivo anexado nao encontrado no disco. Reenvie o anexo deste exame.", 404)
        except PermissionError as exc:
            return fail(str(exc), 401)
        except ValueError as exc:
            return fail(str(exc), 404)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/share/<slug>/media/pacs/objects/<path:sop_instance_uid>/preview.png")
    def shared_pacs_object_preview(slug: str, sop_instance_uid: str):
        try:
            require_share_session(slug)
            service.get_shared_pacs_object(slug, sop_instance_uid)
            return build_preview_response(sop_instance_uid)
        except PermissionError as exc:
            return fail(str(exc), 401)
        except ValueError as exc:
            return fail(str(exc), 404)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/viewer/exams/<int:exam_id>")
    def viewer_exam_payload(exam_id: int):
        try:
            return ok(
                {
                    "viewer_mode": "internal",
                    "workspace": service.get_exam_workspace(exam_id),
                    "shares": service.list_share_accesses(exam_id=exam_id),
                }
            )
        except ValueError as exc:
            return fail(str(exc), 404)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/viewer/shares")
    def create_viewer_share():
        try:
            share = service.create_share_access(request.get_json(force=True, silent=True) or {})
            share["share_url"] = public_share_url(str(share["slug"]))
            return ok(share, 201)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/share/<slug>/workspace")
    def shared_workspace(slug: str):
        try:
            require_share_session(slug)
            exam_id = int(request.args.get("exam_id") or 0) or None
            payload = service.get_shared_workspace(slug, exam_id)
            payload["viewer_mode"] = "share"
            return ok(payload)
        except PermissionError as exc:
            return fail(str(exc), 401)
        except ValueError as exc:
            return fail(str(exc), 404)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/ping")
    def ping():
        return ok({"ok": True, "app": "raioXPacs"})

    @app.get("/api/health")
    def health():
        try:
            return ok(
                {
                    "app": "raioXPacs",
                    "database": database.ping(),
                    "integrations": service.integration_status(),
                    "settings": {
                        "pg_database": settings.pg_database,
                        "imagebox_path": settings.pacs_imagebox_path,
                        "pacs_aet": settings.pacs_aet,
                        "dicom_port": settings.dicom_port,
                        "worklist_ae_title": settings.worklist_ae_title,
                        "worklist_port": settings.worklist_port,
                    },
                }
            )
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/integrations/config")
    def integration_config():
        try:
            return ok(service.get_integration_config())
        except Exception as exc:
            return fail(str(exc), 500)

    @app.put("/api/integrations/config")
    def update_integration_config():
        try:
            require_admin_access()
            return ok(service.update_integration_config(request.get_json(force=True, silent=True) or {}))
        except PermissionError as exc:
            return fail(str(exc), 403)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/pricing/config")
    def pricing_config():
        try:
            return ok(service.get_pricing_config())
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/pricing/overrides")
    def pricing_overrides():
        try:
            return ok(service.get_pricing_overrides())
        except Exception as exc:
            return fail(str(exc), 500)

    @app.put("/api/pricing/config")
    def update_pricing_config():
        try:
            require_admin_access()
            return ok(service.update_pricing_config(request.get_json(force=True, silent=True) or {}))
        except PermissionError as exc:
            return fail(str(exc), 403)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.put("/api/pricing/overrides")
    def update_pricing_override():
        try:
            require_admin_access()
            return ok(service.update_pricing_override(request.get_json(force=True, silent=True) or {}))
        except PermissionError as exc:
            return fail(str(exc), 403)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/integrations/status")
    def integration_status():
        try:
            return ok(service.integration_status())
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/admin/bootstrap")
    def bootstrap():
        try:
            require_admin_access()
            ensure_schema(database)
            camera_runtime.sync(service.list_cameras())
            return ok({"ok": True, "message": "Schema raiox inicializado."})
        except PermissionError as exc:
            return fail(str(exc), 403)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/overview")
    def overview():
        try:
            return ok(service.overview())
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/kanban")
    def kanban():
        try:
            return ok(service.kanban_board())
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/exams/history")
    def exams_history():
        try:
            return ok({"items": service.list_exam_history()})
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/exams/sync")
    def sync_exams():
        try:
            return ok(service.sync_exam_statuses())
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/patients")
    def patients():
        try:
            return ok({"items": service.list_patients()})
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/patients")
    def create_patient():
        try:
            return ok(service.save_patient(request.get_json(force=True, silent=True) or {}), 201)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.put("/api/patients/<int:patient_id>")
    def update_patient(patient_id: int):
        try:
            return ok(service.save_patient(request.get_json(force=True, silent=True) or {}, patient_id=patient_id))
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/procedures")
    def procedures():
        try:
            return ok({"items": service.list_procedures()})
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/procedures")
    def create_procedure():
        try:
            require_admin_access()
            return ok(service.save_procedure(request.get_json(force=True, silent=True) or {}), 201)
        except PermissionError as exc:
            return fail(str(exc), 403)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.put("/api/procedures/<int:procedure_id>")
    def update_procedure(procedure_id: int):
        try:
            require_admin_access()
            return ok(service.save_procedure(request.get_json(force=True, silent=True) or {}, procedure_id=procedure_id))
        except PermissionError as exc:
            return fail(str(exc), 403)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.delete("/api/procedures/<int:procedure_id>")
    def delete_procedure(procedure_id: int):
        try:
            require_admin_access()
            return ok(service.delete_procedure(procedure_id))
        except PermissionError as exc:
            return fail(str(exc), 403)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/operators")
    def operators():
        try:
            return ok({"items": service.list_operators()})
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/operators")
    def create_operator():
        try:
            require_admin_access()
            return ok(service.save_operator(request.get_json(force=True, silent=True) or {}), 201)
        except PermissionError as exc:
            return fail(str(exc), 403)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.put("/api/operators/<int:operator_id>")
    def update_operator(operator_id: int):
        try:
            require_admin_access()
            return ok(service.save_operator(request.get_json(force=True, silent=True) or {}, operator_id=operator_id))
        except PermissionError as exc:
            return fail(str(exc), 403)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/exams")
    def exams():
        try:
            return ok({"items": service.list_exams()})
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/exams")
    def create_exam():
        try:
            return ok(service.save_exam(request.get_json(force=True, silent=True) or {}), 201)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.put("/api/exams/<int:exam_id>")
    def update_exam(exam_id: int):
        try:
            require_admin_access()
            return ok(service.save_exam(request.get_json(force=True, silent=True) or {}, exam_id=exam_id))
        except PermissionError as exc:
            return fail(str(exc), 403)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/exams/<int:exam_id>/publish-worklist")
    def publish_exam(exam_id: int):
        try:
            return ok(service.publish_exam_to_worklist(exam_id))
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/exams/<int:exam_id>/remove-worklist")
    def remove_exam(exam_id: int):
        try:
            return ok(service.remove_exam_from_worklist(exam_id))
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.delete("/api/exams/<int:exam_id>")
    def delete_exam(exam_id: int):
        try:
            require_exam_delete_access()
            return ok(service.delete_exam(exam_id))
        except PermissionError as exc:
            return fail(str(exc), 403)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/exam-orders")
    def exam_orders():
        try:
            return ok({"items": service.list_exam_orders()})
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/exam-orders")
    def create_exam_order():
        try:
            return ok(service.create_exam_order(request.get_json(force=True, silent=True) or {}), 201)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/exam-orders/<int:order_id>")
    def get_exam_order(order_id: int):
        try:
            return ok(service.get_exam_order(order_id))
        except ValueError as exc:
            return fail(str(exc), 404)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/exam-orders/<int:order_id>/mark-paid")
    def mark_order_paid(order_id: int):
        try:
            return ok(service.mark_order_paid(order_id, request.get_json(force=True, silent=True) or {}))
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/exams/<int:exam_id>/order-items")
    def add_exam_order_item(exam_id: int):
        try:
            return ok(service.add_exam_order_item_from_exam(exam_id, request.get_json(force=True, silent=True) or {}))
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.delete("/api/exam-orders/<int:order_id>")
    def delete_exam_order(order_id: int):
        try:
            require_exam_delete_access()
            return ok(service.delete_exam_order(order_id))
        except PermissionError as exc:
            return fail(str(exc), 403)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/exam-orders/<int:order_id>.pdf")
    def exam_order_pdf(order_id: int):
        try:
            return send_file(
                BytesIO(service.build_exam_order_pdf(order_id)),
                mimetype="application/pdf",
                as_attachment=False,
                download_name=f"orcamento-{order_id}.pdf",
            )
        except ValueError as exc:
            return fail(str(exc), 404)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/exams/<int:exam_id>/workspace")
    def exam_workspace(exam_id: int):
        try:
            return ok(service.get_exam_workspace(exam_id))
        except ValueError as exc:
            return fail(str(exc), 404)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.put("/api/exams/<int:exam_id>/report")
    def save_exam_report(exam_id: int):
        try:
            return ok(service.save_medical_report(exam_id, request.get_json(force=True, silent=True) or {}))
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/exams/<int:exam_id>/attachments")
    def upload_exam_attachment(exam_id: int):
        try:
            return ok(service.upload_exam_attachment(exam_id, request.files.get("file")), 201)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.put("/api/exams/<int:exam_id>/workflow-stage")
    def update_exam_stage(exam_id: int):
        try:
            payload = request.get_json(force=True, silent=True) or {}
            return ok(service.update_exam_stage(exam_id, payload.get("stage") or ""))
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/worklist")
    def worklist():
        try:
            return ok(service.list_worklist())
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/finance/overview")
    def finance_overview():
        try:
            return ok(service.finance_overview())
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/finance/invoices")
    def invoices():
        try:
            return ok({"items": service.list_invoices()})
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/reports/<report_type>")
    def report_payload(report_type: str):
        try:
            return ok(service.build_report(report_type, report_filters_from_request()))
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/reports/<report_type>.pdf")
    def report_pdf(report_type: str):
        try:
            report = service.build_report(report_type, report_filters_from_request())
            pdf_bytes = service.build_report_pdf(report)
            period_label = str(report.get("period_label") or "relatorio").replace("/", "-")
            filename = f"relatorio-{report.get('report_type') or 'financeiro'}-{period_label}.pdf"
            return send_file(
                BytesIO(pdf_bytes),
                mimetype="application/pdf",
                as_attachment=False,
                download_name=filename,
            )
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/finance/invoices/<int:invoice_id>/mark-paid")
    def mark_invoice_paid(invoice_id: int):
        try:
            return ok(service.mark_invoice_paid(invoice_id, request.get_json(force=True, silent=True) or {}))
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/finance/invoices/<int:invoice_id>/reopen-payment")
    def reopen_invoice_payment(invoice_id: int):
        try:
            return ok(service.reopen_invoice_payment(invoice_id))
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/chat/conversation")
    def conversation():
        try:
            operator_id = int(request.args.get("operator_id") or 0)
            contact_id = int(request.args.get("contact_id") or 0)
            return ok({"items": service.chat_conversation(operator_id, contact_id)})
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/chat/departments")
    def chat_departments():
        try:
            sender_id = int(request.args.get("operator_id") or request.args.get("sender_id") or 0)
            return ok({"items": service.list_chat_departments(sender_id or None)})
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/chat/messages")
    def send_chat_message():
        try:
            return ok(service.send_chat_message(request.get_json(force=True, silent=True) or {}), 201)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/chat/read")
    def mark_chat_read():
        try:
            payload = request.get_json(force=True, silent=True) or {}
            return ok(service.mark_chat_read(int(payload.get("operator_id") or 0), int(payload.get("contact_id") or 0)))
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/chat/unread")
    def unread_chat():
        try:
            operator_id = int(request.args.get("operator_id") or 0)
            return ok(service.chat_unread(operator_id))
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/sip/config")
    def sip_config():
        try:
            return ok(service.get_sip_config())
        except Exception as exc:
            return fail(str(exc), 500)

    @app.put("/api/sip/config")
    def update_sip_config():
        try:
            require_admin_access()
            return ok(service.update_sip_config(request.get_json(force=True, silent=True) or {}))
        except PermissionError as exc:
            return fail(str(exc), 403)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/sip/context")
    def sip_context():
        try:
            operator_id = int(request.args.get("operator_id") or 0)
            return ok(service.get_sip_context(operator_id))
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/cameras")
    def cameras():
        try:
            return ok({"items": service.list_cameras()})
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/cameras")
    def create_camera():
        try:
            require_admin_access()
            camera = service.save_camera(request.get_json(force=True, silent=True) or {})
            return ok(camera, 201)
        except PermissionError as exc:
            return fail(str(exc), 403)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.put("/api/cameras/<int:camera_id>")
    def update_camera(camera_id: int):
        try:
            require_admin_access()
            return ok(service.save_camera(request.get_json(force=True, silent=True) or {}, camera_id=camera_id))
        except PermissionError as exc:
            return fail(str(exc), 403)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.delete("/api/cameras/<int:camera_id>")
    def delete_camera(camera_id: int):
        try:
            require_admin_access()
            return ok(service.delete_camera(camera_id))
        except PermissionError as exc:
            return fail(str(exc), 403)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/panel")
    def panel():
        try:
            raw_date = (request.args.get("date") or "").strip()
            queue_date = date.fromisoformat(raw_date) if raw_date else date.today()
            return ok(service.list_call_panel(queue_date))
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/panel/tickets/<int:ticket_id>/call")
    def call_panel_ticket(ticket_id: int):
        try:
            return ok(service.call_ticket(ticket_id, request.get_json(force=True, silent=True) or {}))
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/panel/tickets/<int:ticket_id>/status")
    def update_panel_ticket(ticket_id: int):
        try:
            return ok(service.update_call_ticket_status(ticket_id, request.get_json(force=True, silent=True) or {}))
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/panel/config")
    def panel_config():
        try:
            return ok(service.get_panel_config())
        except Exception as exc:
            return fail(str(exc), 500)

    @app.put("/api/panel/config")
    def update_panel_config():
        try:
            require_admin_access()
            return ok(service.update_panel_config(request.get_json(force=True, silent=True) or {}))
        except PermissionError as exc:
            return fail(str(exc), 403)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/storage")
    def storage():
        try:
            return ok(service.storage_overview())
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/backups")
    def backups():
        try:
            return ok(service.list_backups())
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/backups/database")
    def create_database_backup():
        try:
            return ok(service.create_database_backup(), 201)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.post("/api/backups/images")
    def create_images_backup():
        try:
            return ok(service.create_images_backup(), 201)
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/backups/<kind>/<path:filename>")
    def download_backup(kind: str, filename: str):
        try:
            backup = service.get_backup_file(kind, filename)
            return send_file(
                str(backup["path"]),
                mimetype=backup["mimetype"],
                as_attachment=True,
                download_name=backup["filename"],
            )
        except ValueError as exc:
            return fail(str(exc), 404)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/pacs/studies")
    def pacs_studies():
        try:
            limit = int(request.args.get("limit") or 50)
            return ok({"items": service.list_pacs_studies(limit=limit)})
        except ValueError as exc:
            return fail(str(exc), 400)
        except Exception as exc:
            return fail(str(exc), 500)

    @app.get("/api/pacs/studies/<path:study_instance_uid>")
    def pacs_study(study_instance_uid: str):
        try:
            return ok(service.get_pacs_study(study_instance_uid))
        except ValueError as exc:
            return fail(str(exc), 404)
        except Exception as exc:
            return fail(str(exc), 500)

    return app
