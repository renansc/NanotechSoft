"""HTTP and persistence layer for the CUPS printer module."""
from __future__ import annotations

import datetime as dt
import json
import mimetypes
import tempfile
import threading
import time
from pathlib import Path

from flask import jsonify, request
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from .cups_service import CupsService, CupsUnavailable


MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".txt", ".csv"}
_cups = CupsService()
_sync_lock = threading.Lock()
_release_attempts = {}


def _iso(value):
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return value.replace(tzinfo=dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _is_admin(user):
    return str((user or {}).get("perfil") or "").lower() == "admin"


def _json_details(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _public_job(row):
    return {
        "id": int(row["id"]),
        "cupsJobId": int(row["cups_job_id"]),
        "printer": row.get("impressora") or "",
        "userId": int(row["usuario_id"]) if row.get("usuario_id") else None,
        "userName": row.get("usuario_nome") or row.get("cups_usuario") or "Nao identificado",
        "cupsUser": row.get("cups_usuario") or "",
        "document": row.get("documento") or "",
        "fileName": row.get("arquivo_original") or "",
        "origin": row.get("origem") or "CUPS",
        "state": row.get("estado") or "DESCONHECIDO",
        "held": bool(row.get("retido")),
        "requestedPages": row.get("paginas_solicitadas"),
        "printedPages": row.get("paginas_impressas"),
        "copies": int(row.get("copias") or 1),
        "sizeKb": row.get("tamanho_kb"),
        "submittedAt": _iso(row.get("enviado_em")),
        "processedAt": _iso(row.get("processado_em")),
        "completedAt": _iso(row.get("concluido_em")),
        "releasedAt": _iso(row.get("liberado_em")),
        "canceledAt": _iso(row.get("cancelado_em")),
        "details": _json_details(row.get("detalhes")),
    }


def register_printer_module(app, *, get_conn, current_user,
                            can_access, static_response, integrated_redirect,
                            cloud_read_only):
    @app.errorhandler(CupsUnavailable)
    def cups_unavailable_error(exc):
        return jsonify({"erro": str(exc), "code": "cups_unavailable"}), 503

    def allowed(user, resource):
        return bool(user and (_is_admin(user) or can_access(user, "impressoras", resource)))

    def require(resource):
        user = current_user()
        if not user:
            return None, (jsonify({"erro": "login necessario"}), 401)
        if not allowed(user, resource):
            return None, (jsonify({"erro": "recurso nao liberado para este usuario"}), 403)
        return user, None

    def sync_jobs():
        if cloud_read_only or not _sync_lock.acquire(blocking=False):
            return None
        try:
            jobs = _cups.jobs()
            conn = get_conn()
            cur = conn.cursor(dictionary=True)
            try:
                cur.execute("SELECT id, login FROM usuarios WHERE ativo=1")
                users = {str(row["login"]).casefold(): int(row["id"]) for row in cur.fetchall()}
                cur.execute(
                    """
                    SELECT v.cups_usuario, v.usuario_id
                    FROM impressoras_vinculos_usuario v
                    INNER JOIN usuarios u ON u.id=v.usuario_id AND u.ativo=1
                    """
                )
                links = {str(row["cups_usuario"]).casefold(): int(row["usuario_id"]) for row in cur.fetchall()}
                for job in jobs:
                    cups_key = job["cupsUser"].casefold()
                    user_id = links.get(cups_key) or users.get(cups_key)
                    cur.execute(
                        """
                        INSERT INTO impressoras_trabalhos
                            (cups_job_id, impressora, usuario_id, cups_usuario, documento,
                             origem, estado, retido, paginas_solicitadas, paginas_impressas,
                             copias, tamanho_kb, enviado_em, processado_em, concluido_em, detalhes)
                        VALUES (%s,%s,%s,%s,%s,'CUPS',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE
                            impressora=VALUES(impressora),
                            usuario_id=COALESCE(impressoras_trabalhos.usuario_id, VALUES(usuario_id)),
                            cups_usuario=VALUES(cups_usuario), documento=VALUES(documento),
                            estado=VALUES(estado), retido=VALUES(retido),
                            paginas_solicitadas=COALESCE(VALUES(paginas_solicitadas), paginas_solicitadas),
                            paginas_impressas=COALESCE(VALUES(paginas_impressas), paginas_impressas),
                            copias=VALUES(copias), tamanho_kb=COALESCE(VALUES(tamanho_kb), tamanho_kb),
                            enviado_em=COALESCE(VALUES(enviado_em), enviado_em),
                            processado_em=COALESCE(VALUES(processado_em), processado_em),
                            concluido_em=COALESCE(VALUES(concluido_em), concluido_em),
                            detalhes=VALUES(detalhes), sincronizado_em=CURRENT_TIMESTAMP(3)
                        """,
                        (job["cupsJobId"], job["printer"], user_id, job["cupsUser"], job["document"],
                         job["state"], int(job["held"]), job["requestedPages"], job["printedPages"],
                         job["copies"], job["sizeKb"], job["submittedAt"], job["processedAt"],
                         job["completedAt"], json.dumps(job["details"], ensure_ascii=True)),
                    )
                conn.commit()
            finally:
                cur.close()
                conn.close()
            return None
        except CupsUnavailable as exc:
            return str(exc)
        finally:
            _sync_lock.release()

    def select_jobs(user, scope="mine", limit=200):
        clauses = []
        params = []
        if scope != "all" or not allowed(user, "historico"):
            clauses.append("(t.usuario_id=%s OR (t.usuario_id IS NULL AND LOWER(t.cups_usuario)=LOWER(%s)))")
            params.extend((int(user["id"]), user.get("login") or ""))
        state = str(request.args.get("state") or "").strip().upper()
        if state:
            clauses.append("t.estado=%s")
            params.append(state)
        search = str(request.args.get("search") or "").strip()
        if search:
            clauses.append("(t.documento LIKE %s OR t.impressora LIKE %s OR u.nome LIKE %s OR t.cups_usuario LIKE %s)")
            term = f"%{search[:120]}%"
            params.extend((term, term, term, term))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        try:
            bounded_limit = max(1, min(int(limit), 1000))
        except (TypeError, ValueError):
            bounded_limit = 200
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT t.*, u.nome AS usuario_nome
            FROM impressoras_trabalhos t
            LEFT JOIN usuarios u ON u.id=t.usuario_id
            """ + where + " ORDER BY COALESCE(t.enviado_em,t.created_at) DESC, t.id DESC LIMIT %s",
            tuple(params + [bounded_limit]),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [_public_job(row) for row in rows]

    def owned_job(user, job_id, manage=False):
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM impressoras_trabalhos WHERE id=%s", (job_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None, (jsonify({"erro": "trabalho nao encontrado"}), 404)
        owner = row.get("usuario_id") == user.get("id") or (
            not row.get("usuario_id") and str(row.get("cups_usuario") or "").casefold() == str(user.get("login") or "").casefold()
        )
        if not owner and not (manage and allowed(user, "gerenciar")):
            return None, (jsonify({"erro": "trabalho pertence a outro usuario"}), 403)
        return row, None

    def password_ok(user, password):
        now = time.monotonic()
        attempts = [stamp for stamp in _release_attempts.get(user["id"], []) if now - stamp < 300]
        if len(attempts) >= 5:
            return False, "Muitas tentativas. Aguarde cinco minutos.", 429
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT senha FROM usuarios WHERE id=%s AND ativo=1", (user["id"],))
        row = cur.fetchone()
        cur.close()
        conn.close()
        try:
            valid = bool(password) and check_password_hash(str((row or {}).get("senha") or ""), password)
        except (ValueError, TypeError):
            valid = False
        if valid:
            _release_attempts.pop(user["id"], None)
            return True, "", 200
        attempts.append(now)
        _release_attempts[user["id"]] = attempts
        return False, "Senha do portal invalida.", 401

    @app.route("/apps/impressoras")
    def impressoras_root():
        return static_response("impressoras")

    @app.route("/apps/impressoras/original")
    def impressoras_original():
        return integrated_redirect("impressoras")

    @app.route("/apps/impressoras/api/overview")
    def impressoras_overview():
        user = current_user()
        if not user:
            return jsonify({"erro": "autenticacao necessaria"}), 401
        if not any(allowed(user, resource) for resource in ("monitor", "fila", "gerenciar")):
            return jsonify({"erro": "sem permissao para este recurso"}), 403
        cups_error = sync_jobs()
        printers = []
        if not cloud_read_only:
            try:
                printers = _cups.printers()
            except CupsUnavailable as exc:
                cups_error = str(exc)
        jobs = select_jobs(user, "mine", 100)
        return jsonify({
            "ok": True, "cupsOnline": not cups_error, "cupsError": cups_error or "",
            "printers": printers, "myJobs": jobs,
            "summary": {
                "printers": len(printers),
                "held": sum(1 for job in jobs if job["held"]),
                "printedPages": sum(job["printedPages"] or 0 for job in jobs),
            },
        })

    @app.route("/apps/impressoras/api/jobs")
    def impressoras_jobs():
        scope = str(request.args.get("scope") or "mine").lower()
        user, error = require("historico" if scope == "all" else "fila")
        if error:
            return error
        cups_error = sync_jobs()
        return jsonify({"ok": True, "jobs": select_jobs(user, scope, request.args.get("limit") or 300),
                        "cupsError": cups_error or ""})

    @app.route("/apps/impressoras/api/jobs", methods=["POST"])
    def impressoras_submit():
        user, error = require("fila")
        if error:
            return error
        if cloud_read_only:
            return jsonify({"erro": "envio disponivel somente no deploy local"}), 403
        upload = request.files.get("file")
        printer = str(request.form.get("printer") or "").strip()
        if not upload or not upload.filename or not printer:
            return jsonify({"erro": "selecione a impressora e o arquivo"}), 400
        filename = secure_filename(upload.filename)
        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            return jsonify({"erro": "formato nao aceito; use PDF, PNG, JPG, TXT ou CSV"}), 400
        try:
            copies = int(request.form.get("copies") or 1)
        except (TypeError, ValueError):
            return jsonify({"erro": "quantidade de copias invalida"}), 400
        copies = max(1, min(copies, 50))
        data = upload.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            return jsonify({"erro": "arquivo excede 50 MB"}), 413
        available = {item["name"] for item in _cups.printers()}
        if printer not in available:
            return jsonify({"erro": "impressora nao encontrada no CUPS"}), 404
        with tempfile.NamedTemporaryFile(suffix=extension) as temporary:
            temporary.write(data)
            temporary.flush()
            cups_job_id = _cups.submit_held(printer, temporary.name, filename, copies)
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO impressoras_trabalhos
                (cups_job_id,impressora,usuario_id,cups_usuario,documento,arquivo_original,
                 mime_type,origem,estado,retido,copias,tamanho_kb,enviado_em,detalhes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'PORTAL','RETIDO',1,%s,%s,UTC_TIMESTAMP(3),%s)
            ON DUPLICATE KEY UPDATE usuario_id=VALUES(usuario_id), origem='PORTAL',
                arquivo_original=VALUES(arquivo_original), mime_type=VALUES(mime_type), retido=1
            """,
            (cups_job_id, printer, user["id"], user.get("login") or "", filename, filename,
             mimetypes.guess_type(filename)[0] or upload.mimetype or "application/octet-stream",
             copies, (len(data) + 1023) // 1024, json.dumps({"secureRelease": "portal-password"})),
        )
        row_id = cur.lastrowid
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"ok": True, "id": row_id, "cupsJobId": cups_job_id,
                        "message": "Arquivo enviado e retido. Digite sua senha para liberar."}), 201

    @app.route("/apps/impressoras/api/user-links")
    def impressoras_user_links():
        _actor, error = require("gerenciar")
        if error:
            return error
        sync_jobs()
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                """
                SELECT v.id, v.cups_usuario, v.usuario_id, u.login, u.nome
                FROM impressoras_vinculos_usuario v
                INNER JOIN usuarios u ON u.id=v.usuario_id
                ORDER BY LOWER(v.cups_usuario)
                """
            )
            links = cur.fetchall()
            cur.execute("SELECT id, login, nome FROM usuarios WHERE ativo=1 ORDER BY nome, login")
            users = cur.fetchall()
            cur.execute(
                """
                SELECT DISTINCT t.cups_usuario
                FROM impressoras_trabalhos t
                LEFT JOIN impressoras_vinculos_usuario v
                  ON LOWER(v.cups_usuario)=LOWER(t.cups_usuario)
                WHERE t.origem='CUPS' AND t.cups_usuario<>'' AND v.id IS NULL
                ORDER BY t.cups_usuario
                """
            )
            detected = [row["cups_usuario"] for row in cur.fetchall()]
        finally:
            cur.close()
            conn.close()
        return jsonify({"ok": True, "links": links, "users": users, "detectedCupsUsers": detected})

    @app.route("/apps/impressoras/api/user-links", methods=["POST"])
    def impressoras_save_user_link():
        actor, error = require("gerenciar")
        if error:
            return error
        payload = request.get_json(silent=True) or {}
        cups_user = str(payload.get("cupsUser") or "").strip()
        try:
            user_id = int(payload.get("userId"))
        except (TypeError, ValueError):
            user_id = 0
        if not cups_user or len(cups_user) > 120 or not user_id:
            return jsonify({"erro": "informe o usuario CUPS e o usuario ativo do portal"}), 400
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT id FROM usuarios WHERE id=%s AND ativo=1", (user_id,))
            if not cur.fetchone():
                return jsonify({"erro": "usuario do portal nao encontrado ou inativo"}), 404
            cur.execute(
                """
                INSERT INTO impressoras_vinculos_usuario
                    (cups_usuario, usuario_id, atualizado_por_id)
                VALUES (%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    usuario_id=VALUES(usuario_id),
                    atualizado_por_id=VALUES(atualizado_por_id)
                """,
                (cups_user, user_id, actor["id"]),
            )
            cur.execute(
                """
                UPDATE impressoras_trabalhos
                SET usuario_id=%s
                WHERE origem='CUPS' AND LOWER(cups_usuario)=LOWER(%s)
                """,
                (user_id, cups_user),
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()
        return jsonify({"ok": True, "message": "Vinculo salvo e aplicado ao historico."})

    @app.route("/apps/impressoras/api/user-links/<int:link_id>", methods=["DELETE"])
    def impressoras_delete_user_link(link_id):
        _actor, error = require("gerenciar")
        if error:
            return error
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT cups_usuario FROM impressoras_vinculos_usuario WHERE id=%s", (link_id,))
            link = cur.fetchone()
            if not link:
                return jsonify({"erro": "vinculo nao encontrado"}), 404
            cups_user = link["cups_usuario"]
            cur.execute("DELETE FROM impressoras_vinculos_usuario WHERE id=%s", (link_id,))
            cur.execute("SELECT id FROM usuarios WHERE ativo=1 AND LOWER(login)=LOWER(%s)", (cups_user,))
            matching_user = cur.fetchone()
            cur.execute(
                """
                UPDATE impressoras_trabalhos
                SET usuario_id=%s
                WHERE origem='CUPS' AND LOWER(cups_usuario)=LOWER(%s)
                """,
                ((matching_user or {}).get("id"), cups_user),
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()
        return jsonify({"ok": True})

    @app.route("/apps/impressoras/api/jobs/<int:job_id>/release", methods=["POST"])
    def impressoras_release(job_id):
        user, error = require("fila")
        if error:
            return error
        row, error = owned_job(user, job_id)
        if error:
            return error
        valid, message, status = password_ok(user, str((request.get_json(silent=True) or {}).get("password") or ""))
        if not valid:
            return jsonify({"erro": message}), status
        _cups.release(row["cups_job_id"])
        conn = get_conn(); cur = conn.cursor()
        cur.execute("UPDATE impressoras_trabalhos SET retido=0,estado='PENDENTE',liberado_em=UTC_TIMESTAMP(3),liberado_por_id=%s WHERE id=%s", (user["id"], job_id))
        conn.commit(); cur.close(); conn.close()
        return jsonify({"ok": True})

    @app.route("/apps/impressoras/api/jobs/release-all", methods=["POST"])
    def impressoras_release_all():
        user, error = require("fila")
        if error:
            return error
        valid, message, status = password_ok(user, str((request.get_json(silent=True) or {}).get("password") or ""))
        if not valid:
            return jsonify({"erro": message}), status
        conn = get_conn(); cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id,cups_job_id FROM impressoras_trabalhos WHERE retido=1 AND (usuario_id=%s OR (usuario_id IS NULL AND LOWER(cups_usuario)=LOWER(%s)))", (user["id"], user.get("login") or ""))
        rows = cur.fetchall()
        released = []
        try:
            for row in rows:
                _cups.release(row["cups_job_id"])
                released.append(row["id"])
            if released:
                placeholders = ",".join(["%s"] * len(released))
                cur.execute(f"UPDATE impressoras_trabalhos SET retido=0,estado='PENDENTE',liberado_em=UTC_TIMESTAMP(3),liberado_por_id=%s WHERE id IN ({placeholders})", tuple([user["id"], *released]))
            conn.commit()
        finally:
            cur.close(); conn.close()
        return jsonify({"ok": True, "released": len(released)})

    @app.route("/apps/impressoras/api/jobs/<int:job_id>/cancel", methods=["POST"])
    def impressoras_cancel(job_id):
        user = current_user()
        if not user or not (allowed(user, "fila") or allowed(user, "gerenciar")):
            return jsonify({"erro": "recurso nao liberado para este usuario"}), 403
        row, error = owned_job(user, job_id, manage=True)
        if error:
            return error
        _cups.cancel(row["cups_job_id"])
        conn = get_conn(); cur = conn.cursor()
        cur.execute("UPDATE impressoras_trabalhos SET retido=0,estado='CANCELADO',cancelado_em=UTC_TIMESTAMP(3) WHERE id=%s", (job_id,))
        conn.commit(); cur.close(); conn.close()
        return jsonify({"ok": True})

    @app.route("/apps/impressoras/api/printers/<path:printer>/<action>", methods=["POST"])
    def impressoras_printer_action(printer, action):
        _user, error = require("gerenciar")
        if error:
            return error
        if action not in {"pause", "resume", "reject", "accept"}:
            return jsonify({"erro": "acao de impressora invalida"}), 400
        _cups.printer_action(printer, action)
        return jsonify({"ok": True})

    @app.route("/apps/impressoras/<path:subpath>")
    def impressoras_static(subpath):
        return static_response("impressoras", subpath)
