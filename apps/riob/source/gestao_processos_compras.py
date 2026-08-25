"""Gestao de processos internos e compras integrada ao RioB."""

import datetime
import math
import os
import re
from collections import defaultdict

import mysql.connector
from flask import Blueprint, jsonify, request, send_file
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


PROCESS_STATUSES = ("solicitado", "analise", "execucao", "aguardando", "concluido", "cancelado")
PURCHASE_STATUSES = ("solicitado", "cotacao", "aprovacao", "pedido", "aguardando", "recebido", "cancelado")
PRIORITIES = ("baixa", "normal", "alta", "urgente")


def purchase_forecast(
    last_year_month=0,
    recent_months=None,
    current_week=0,
    elapsed_week_days=1,
    month_days=30,
    current_stock=0,
    open_purchases=0,
    safety_stock=0,
    lead_days=7,
    minimum_lot=0,
    purchase_multiple=1,
):
    """Calcula consumo e compra sugerida sem depender de Flask ou banco."""
    recent = [float(value or 0) for value in (recent_months or []) if value is not None]
    recent_average = sum(recent) / len(recent) if recent else 0.0
    last_year = max(0.0, float(last_year_month or 0))
    monthly_reference = max(last_year, recent_average)
    elapsed = max(1, int(elapsed_week_days or 1))
    weekly_pace = max(0.0, float(current_week or 0)) / elapsed * 7
    days = max(1, int(month_days or 30))
    weekly_forecast = monthly_reference / days * 7 if monthly_reference > 0 else weekly_pace
    daily_forecast = monthly_reference / days if monthly_reference > 0 else weekly_pace / 7
    lead = max(1, int(lead_days or 7))
    gross_need = daily_forecast * lead + max(0.0, float(safety_stock or 0))
    suggestion = max(0.0, gross_need - float(current_stock or 0) - float(open_purchases or 0))
    if suggestion > 0:
        suggestion = max(suggestion, max(0.0, float(minimum_lot or 0)))
        multiple = max(0.001, float(purchase_multiple or 1))
        suggestion = math.ceil((suggestion - 0.0000001) / multiple) * multiple
    source = "historico_mensal" if monthly_reference > 0 else ("ritmo_semana" if weekly_pace > 0 else "sem_historico")
    return {
        "consumo_mes_ano_anterior": round(last_year, 3),
        "media_consumo_meses_recentes": round(recent_average, 3),
        "consumo_referencia_mensal": round(monthly_reference, 3),
        "previsao_consumo_semana": round(weekly_forecast, 3),
        "necessidade_periodo_entrega": round(gross_need, 3),
        "sugestao_compra": round(suggestion, 3),
        "origem_previsao": source,
    }


def register_gestao_processos_compras(app, services):
    bp = Blueprint("gestao_processos_compras", __name__)
    get_conn = services["get_conn"]
    as_int = services["as_int"]
    as_float = services["as_float"]
    as_str = services["as_str"]
    fmt_date = services["fmt_date"]
    fmt_dt = services["fmt_dt"]
    parse_date = services["parse_date"]
    usuario_ator = services["usuario_ator"]
    estoque_resumo = services["estoque_resumo"]
    estoque_lookup = services["estoque_lookup"]
    estoque_resolver = services["estoque_resolver"]
    estoque_classificar = services["estoque_classificar"]
    month_shift = services["month_shift"]
    month_end = services["month_end"]
    month_key = services["month_key"]
    report_header = services["report_header"]
    pdf_escape = services["pdf_escape"]
    decimal_br = services["decimal_br"]

    def data(value):
        return parse_date(value) if as_str(value) else None

    def collaborator_name(cur, collaborator_id, fallback=""):
        collaborator_id = as_int(collaborator_id, 0)
        if collaborator_id <= 0:
            return as_str(fallback)
        cur.execute("SELECT nome FROM colaboradores WHERE id=%s LIMIT 1", (collaborator_id,))
        row = cur.fetchone() or {}
        return as_str(row.get("nome") if isinstance(row, dict) else row[0]) or as_str(fallback)

    def process_list(args):
        status = as_str(args.get("status")).lower()
        type_id = as_int(args.get("tipo_id"), 0)
        responsible_id = as_int(args.get("responsavel_id"), 0)
        search = as_str(args.get("busca"))
        start = data(args.get("data_inicio"))
        end = data(args.get("data_fim"))
        where = ["p.ativo=1"]
        params = []
        if status in PROCESS_STATUSES:
            where.append("p.status=%s")
            params.append(status)
        if type_id:
            where.append("p.tipo_id=%s")
            params.append(type_id)
        if responsible_id:
            where.append("p.responsavel_id=%s")
            params.append(responsible_id)
        if search:
            where.append("(p.titulo LIKE %s OR p.descricao LIKE %s OR p.solicitante LIKE %s OR p.responsavel_nome LIKE %s)")
            params.extend([f"%{search}%"] * 4)
        if start:
            where.append("COALESCE(p.data_abertura, DATE(p.criado_em)) >= %s")
            params.append(start)
        if end:
            where.append("COALESCE(p.data_abertura, DATE(p.criado_em)) <= %s")
            params.append(end)
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                f"""
                SELECT p.*, t.nome AS tipo_nome, t.cor AS tipo_cor, t.sla_dias,
                       c.nome AS colaborador_nome
                FROM processos_internos p
                LEFT JOIN processos_tipos t ON t.id=p.tipo_id
                LEFT JOIN colaboradores c ON c.id=p.responsavel_id
                WHERE {' AND '.join(where)}
                ORDER BY CASE p.prioridade WHEN 'urgente' THEN 0 WHEN 'alta' THEN 1
                         WHEN 'normal' THEN 2 ELSE 3 END,
                         COALESCE(p.prazo, '2999-12-31'), p.id DESC
                """,
                tuple(params),
            )
            rows = cur.fetchall() or []
            cur.execute("SELECT id, nome, descricao, sla_dias, cor, ativo FROM processos_tipos WHERE ativo=1 ORDER BY nome")
            types = cur.fetchall() or []
            cur.execute("SELECT id, nome FROM colaboradores ORDER BY nome")
            collaborators = cur.fetchall() or []
        finally:
            cur.close()
            conn.close()
        today = datetime.date.today()
        for row in rows:
            row["data_abertura"] = fmt_date(row.get("data_abertura"))
            row["prazo"] = fmt_date(row.get("prazo"))
            row["criado_em"] = fmt_dt(row.get("criado_em"))
            row["atualizado_em"] = fmt_dt(row.get("atualizado_em"))
            row["responsavel_nome"] = as_str(row.get("colaborador_nome") or row.get("responsavel_nome"))
            deadline = data(row.get("prazo"))
            row["atrasado"] = bool(deadline and deadline < today and row.get("status") not in ("concluido", "cancelado"))
        return {
            "rows": rows,
            "opcoes": {"tipos": types, "colaboradores": collaborators, "status": list(PROCESS_STATUSES)},
            "meta": {
                "total": len(rows),
                "atrasados": sum(1 for row in rows if row.get("atrasado")),
                "por_status": {status: sum(1 for row in rows if row.get("status") == status) for status in PROCESS_STATUSES},
                "atualizado_em": fmt_dt(datetime.datetime.now()),
            },
        }

    def process_payload(cur, payload, current=None):
        current = current or {}
        title = as_str(payload.get("titulo", current.get("titulo")))[:255]
        if not title:
            raise ValueError("Informe o titulo do processo.")
        type_id = as_int(payload.get("tipo_id", current.get("tipo_id")), 0) or None
        status = as_str(payload.get("status", current.get("status") or "solicitado")).lower()
        if status not in PROCESS_STATUSES:
            raise ValueError("Status de processo invalido.")
        priority = as_str(payload.get("prioridade", current.get("prioridade") or "normal")).lower()
        priority = priority if priority in PRIORITIES else "normal"
        responsible_id = as_int(payload.get("responsavel_id", current.get("responsavel_id")), 0) or None
        opening = data(payload.get("data_abertura", current.get("data_abertura"))) or datetime.date.today()
        deadline = data(payload.get("prazo", current.get("prazo")))
        if not deadline and type_id:
            cur.execute("SELECT sla_dias FROM processos_tipos WHERE id=%s AND ativo=1", (type_id,))
            type_row = cur.fetchone() or {}
            sla = as_int(type_row.get("sla_dias") if isinstance(type_row, dict) else type_row[0], 0)
            if sla:
                deadline = opening + datetime.timedelta(days=sla)
        return {
            "titulo": title,
            "tipo_id": type_id,
            "solicitante": as_str(payload.get("solicitante", current.get("solicitante")))[:180],
            "responsavel_id": responsible_id,
            "responsavel_nome": collaborator_name(cur, responsible_id, payload.get("responsavel_nome", current.get("responsavel_nome")))[:180],
            "prioridade": priority,
            "status": status,
            "data_abertura": opening,
            "prazo": deadline,
            "descricao": as_str(payload.get("descricao", current.get("descricao"))),
        }

    @bp.route("/api/processos-internos", methods=["GET", "POST"])
    def processes_api():
        if request.method == "GET":
            return jsonify(process_list(request.args))
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            values = process_payload(cur, request.get_json(silent=True) or {})
            actor = usuario_ator()
            cur.execute(
                """INSERT INTO processos_internos
                (titulo,tipo_id,solicitante,responsavel_id,responsavel_nome,prioridade,
                 status,data_abertura,prazo,descricao,criado_por)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (*values.values(), actor),
            )
            item_id = cur.lastrowid
            cur.execute("INSERT INTO processos_historico (processo_id,acao,status_novo,usuario,detalhes) VALUES (%s,'criado',%s,%s,%s)", (item_id, values["status"], actor, values["titulo"]))
            conn.commit()
            return jsonify({"ok": True, "id": item_id}), 201
        except ValueError as exc:
            conn.rollback()
            return jsonify({"erro": str(exc)}), 400
        finally:
            cur.close()
            conn.close()

    @bp.route("/api/processos-internos/<int:item_id>", methods=["PUT", "DELETE"])
    def process_item_api(item_id):
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT * FROM processos_internos WHERE id=%s AND ativo=1 FOR UPDATE", (item_id,))
            current = cur.fetchone()
            if not current:
                return jsonify({"erro": "Processo nao encontrado."}), 404
            actor = usuario_ator()
            if request.method == "DELETE":
                cur.execute("UPDATE processos_internos SET ativo=0, atualizado_em=NOW() WHERE id=%s", (item_id,))
                cur.execute("INSERT INTO processos_historico (processo_id,acao,status_anterior,usuario,detalhes) VALUES (%s,'excluido',%s,%s,%s)", (item_id, current.get("status"), actor, current.get("titulo")))
                conn.commit()
                return jsonify({"ok": True})
            values = process_payload(cur, request.get_json(silent=True) or {}, current)
            completed_at = datetime.datetime.now() if values["status"] == "concluido" else None
            cur.execute(
                """UPDATE processos_internos SET titulo=%s,tipo_id=%s,solicitante=%s,
                responsavel_id=%s,responsavel_nome=%s,prioridade=%s,status=%s,
                data_abertura=%s,prazo=%s,descricao=%s,concluido_em=%s,atualizado_em=NOW()
                WHERE id=%s""",
                (*values.values(), completed_at, item_id),
            )
            action = "status" if values["status"] != current.get("status") else "editado"
            cur.execute("INSERT INTO processos_historico (processo_id,acao,status_anterior,status_novo,usuario,detalhes) VALUES (%s,%s,%s,%s,%s,%s)", (item_id, action, current.get("status"), values["status"], actor, values["titulo"]))
            conn.commit()
            return jsonify({"ok": True, "id": item_id})
        except ValueError as exc:
            conn.rollback()
            return jsonify({"erro": str(exc)}), 400
        finally:
            cur.close()
            conn.close()

    @bp.route("/api/processos-internos/tipos", methods=["GET", "POST"])
    def process_types_api():
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            if request.method == "GET":
                cur.execute("SELECT * FROM processos_tipos WHERE ativo=1 ORDER BY nome")
                return jsonify(cur.fetchall() or [])
            payload = request.get_json(silent=True) or {}
            name = as_str(payload.get("nome"))[:160]
            if not name:
                return jsonify({"erro": "Informe o nome do tipo de processo."}), 400
            cur.execute("INSERT INTO processos_tipos (nome,descricao,sla_dias,cor,ativo) VALUES (%s,%s,%s,%s,1)", (name, as_str(payload.get("descricao"))[:500], max(0, as_int(payload.get("sla_dias"), 7)), as_str(payload.get("cor"))[:20] or "#2563eb"))
            conn.commit()
            return jsonify({"ok": True, "id": cur.lastrowid}), 201
        except mysql.connector.IntegrityError:
            conn.rollback()
            return jsonify({"erro": "Ja existe um tipo com esse nome."}), 409
        finally:
            cur.close()
            conn.close()

    @bp.route("/api/processos-internos/tipos/<int:item_id>", methods=["PUT", "DELETE"])
    def process_type_item_api(item_id):
        conn = get_conn()
        cur = conn.cursor()
        try:
            if request.method == "DELETE":
                cur.execute("UPDATE processos_tipos SET ativo=0 WHERE id=%s", (item_id,))
            else:
                payload = request.get_json(silent=True) or {}
                name = as_str(payload.get("nome"))[:160]
                if not name:
                    return jsonify({"erro": "Informe o nome do tipo de processo."}), 400
                cur.execute("UPDATE processos_tipos SET nome=%s,descricao=%s,sla_dias=%s,cor=%s,ativo=1 WHERE id=%s", (name, as_str(payload.get("descricao"))[:500], max(0, as_int(payload.get("sla_dias"), 7)), as_str(payload.get("cor"))[:20] or "#2563eb", item_id))
            conn.commit()
            return jsonify({"ok": True})
        except mysql.connector.IntegrityError:
            conn.rollback()
            return jsonify({"erro": "Ja existe um tipo com esse nome."}), 409
        finally:
            cur.close()
            conn.close()

    def purchase_list(args):
        status = as_str(args.get("status")).lower()
        supplier_id = as_int(args.get("fornecedor_id"), 0)
        product_id = as_int(args.get("produto_id"), 0)
        search = as_str(args.get("busca"))
        start = data(args.get("data_inicio"))
        end = data(args.get("data_fim"))
        where = ["c.ativo=1"]
        params = []
        if status in PURCHASE_STATUSES:
            where.append("c.status=%s"); params.append(status)
        if supplier_id:
            where.append("c.fornecedor_id=%s"); params.append(supplier_id)
        if product_id:
            where.append("c.produto_id=%s"); params.append(product_id)
        if search:
            where.append("(c.titulo LIKE %s OR c.justificativa LIKE %s OR p.nome_produto LIKE %s OR f.nome LIKE %s OR f.dominios LIKE %s OR f.emails LIKE %s)")
            params.extend([f"%{search}%"] * 6)
        if start:
            where.append("COALESCE(c.data_necessidade,DATE(c.criado_em)) >= %s"); params.append(start)
        if end:
            where.append("COALESCE(c.data_necessidade,DATE(c.criado_em)) <= %s"); params.append(end)
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                f"""SELECT c.*,p.nome_produto,p.produto_base_nome,p.grupo_estoque,
                COALESCE(NULLIF(f.nome,''),NULLIF(f.dominios,''),NULLIF(f.emails,'')) AS fornecedor_nome,
                col.nome AS colaborador_nome
                FROM compras_solicitacoes c
                LEFT JOIN estoque_produtos p ON p.id=c.produto_id
                LEFT JOIN gestor_email_fornecedores f ON f.id=c.fornecedor_id
                LEFT JOIN colaboradores col ON col.id=c.responsavel_id
                WHERE {' AND '.join(where)}
                ORDER BY CASE c.prioridade WHEN 'urgente' THEN 0 WHEN 'alta' THEN 1
                WHEN 'normal' THEN 2 ELSE 3 END,COALESCE(c.data_necessidade,'2999-12-31'),c.id DESC""",
                tuple(params),
            )
            rows = cur.fetchall() or []
            cur.execute("""SELECT f.id,f.nome,f.cnpj,f.dominios,f.emails,
                COALESCE(NULLIF(f.nome,''),NULLIF(f.dominios,''),NULLIF(f.emails,''),CONCAT('Fornecedor #',f.id)) AS nome_exibicao,
                COALESCE(cfg.contato_compras,'') AS contato_compras,
                COALESCE(cfg.representante_nome,'') AS representante_nome,
                COALESCE(cfg.telefone,'') AS telefone,COALESCE(cfg.endereco,'') AS endereco
                FROM gestor_email_fornecedores f LEFT JOIN compras_fornecedor_config cfg
                ON cfg.fornecedor_id=f.id WHERE f.ativo=1 ORDER BY nome_exibicao""")
            suppliers = cur.fetchall() or []
            cur.execute("SELECT id,nome_produto,produto_base_nome,grupo_estoque,unidade FROM estoque_produtos WHERE ativo=1 ORDER BY nome_produto")
            products = cur.fetchall() or []
            cur.execute("SELECT id,nome FROM colaboradores ORDER BY nome")
            collaborators = cur.fetchall() or []
        finally:
            cur.close()
            conn.close()
        today = datetime.date.today()
        for row in rows:
            row["data_necessidade"] = fmt_date(row.get("data_necessidade"))
            row["data_previsao_entrega"] = fmt_date(row.get("data_previsao_entrega"))
            row["criado_em"] = fmt_dt(row.get("criado_em"))
            row["atualizado_em"] = fmt_dt(row.get("atualizado_em"))
            row["produto_nome"] = as_str(row.get("produto_base_nome") or row.get("nome_produto"))
            row["responsavel_nome"] = as_str(row.get("colaborador_nome") or row.get("responsavel_nome"))
            need_date = data(row.get("data_necessidade"))
            row["atrasado"] = bool(need_date and need_date < today and row.get("status") not in ("recebido", "cancelado"))
            row["valor_total_previsto"] = round(as_float(row.get("quantidade"), 0) * as_float(row.get("valor_unitario_previsto"), 0), 2)
        return {
            "rows": rows,
            "opcoes": {"fornecedores": suppliers, "produtos": products, "colaboradores": collaborators, "status": list(PURCHASE_STATUSES)},
            "meta": {
                "total": len(rows),
                "atrasadas": sum(1 for row in rows if row.get("atrasado")),
                "valor_total_previsto": round(sum(as_float(row.get("valor_total_previsto"), 0) for row in rows), 2),
                "por_status": {status: sum(1 for row in rows if row.get("status") == status) for status in PURCHASE_STATUSES},
                "atualizado_em": fmt_dt(datetime.datetime.now()),
            },
        }

    def purchase_payload(cur, payload, current=None):
        current = current or {}
        product_id = as_int(payload.get("produto_id", current.get("produto_id")), 0) or None
        title = as_str(payload.get("titulo", current.get("titulo")))[:255]
        if not title and product_id:
            cur.execute("SELECT COALESCE(NULLIF(produto_base_nome,''),nome_produto) AS nome FROM estoque_produtos WHERE id=%s", (product_id,))
            product = cur.fetchone() or {}
            title = f"Compra - {as_str(product.get('nome'))}"[:255]
        if not title:
            raise ValueError("Informe o titulo ou o produto da compra.")
        quantity = as_float(payload.get("quantidade", current.get("quantidade")), 0)
        if quantity <= 0:
            raise ValueError("A quantidade deve ser maior que zero.")
        status = as_str(payload.get("status", current.get("status") or "solicitado")).lower()
        if status not in PURCHASE_STATUSES:
            raise ValueError("Status de compra invalido.")
        priority = as_str(payload.get("prioridade", current.get("prioridade") or "normal")).lower()
        priority = priority if priority in PRIORITIES else "normal"
        responsible_id = as_int(payload.get("responsavel_id", current.get("responsavel_id")), 0) or None
        return {
            "titulo": title,
            "produto_id": product_id,
            "fornecedor_id": as_int(payload.get("fornecedor_id", current.get("fornecedor_id")), 0) or None,
            "quantidade": quantity,
            "unidade": as_str(payload.get("unidade", current.get("unidade") or "UN"))[:30] or "UN",
            "valor_unitario_previsto": max(0, as_float(payload.get("valor_unitario_previsto", current.get("valor_unitario_previsto")), 0)),
            "prioridade": priority,
            "status": status,
            "solicitante": as_str(payload.get("solicitante", current.get("solicitante")))[:180],
            "responsavel_id": responsible_id,
            "responsavel_nome": collaborator_name(cur, responsible_id, payload.get("responsavel_nome", current.get("responsavel_nome")))[:180],
            "data_necessidade": data(payload.get("data_necessidade", current.get("data_necessidade"))),
            "data_previsao_entrega": data(payload.get("data_previsao_entrega", current.get("data_previsao_entrega"))),
            "justificativa": as_str(payload.get("justificativa", current.get("justificativa"))),
            "origem": as_str(payload.get("origem", current.get("origem") or "manual"))[:40] or "manual",
        }

    @bp.route("/api/compras/solicitacoes", methods=["GET", "POST"])
    def purchases_api():
        if request.method == "GET":
            return jsonify(purchase_list(request.args))
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            values = purchase_payload(cur, request.get_json(silent=True) or {})
            actor = usuario_ator()
            cur.execute(
                """INSERT INTO compras_solicitacoes
                (titulo,produto_id,fornecedor_id,quantidade,unidade,valor_unitario_previsto,
                 prioridade,status,solicitante,responsavel_id,responsavel_nome,data_necessidade,
                 data_previsao_entrega,justificativa,origem,criado_por)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (*values.values(), actor),
            )
            item_id = cur.lastrowid
            cur.execute("INSERT INTO compras_historico (compra_id,acao,status_novo,usuario,detalhes) VALUES (%s,'criado',%s,%s,%s)", (item_id, values["status"], actor, values["titulo"]))
            conn.commit()
            return jsonify({"ok": True, "id": item_id}), 201
        except ValueError as exc:
            conn.rollback()
            return jsonify({"erro": str(exc)}), 400
        finally:
            cur.close()
            conn.close()

    @bp.route("/api/compras/solicitacoes/<int:item_id>", methods=["PUT", "DELETE"])
    def purchase_item_api(item_id):
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT * FROM compras_solicitacoes WHERE id=%s AND ativo=1 FOR UPDATE", (item_id,))
            current = cur.fetchone()
            if not current:
                return jsonify({"erro": "Compra nao encontrada."}), 404
            actor = usuario_ator()
            if request.method == "DELETE":
                cur.execute("UPDATE compras_solicitacoes SET ativo=0,atualizado_em=NOW() WHERE id=%s", (item_id,))
                cur.execute("INSERT INTO compras_historico (compra_id,acao,status_anterior,usuario,detalhes) VALUES (%s,'excluido',%s,%s,%s)", (item_id, current.get("status"), actor, current.get("titulo")))
                conn.commit()
                return jsonify({"ok": True})
            values = purchase_payload(cur, request.get_json(silent=True) or {}, current)
            received_at = datetime.datetime.now() if values["status"] == "recebido" else None
            cur.execute(
                """UPDATE compras_solicitacoes SET titulo=%s,produto_id=%s,fornecedor_id=%s,
                quantidade=%s,unidade=%s,valor_unitario_previsto=%s,prioridade=%s,status=%s,
                solicitante=%s,responsavel_id=%s,responsavel_nome=%s,data_necessidade=%s,
                data_previsao_entrega=%s,justificativa=%s,origem=%s,recebido_em=%s,
                atualizado_em=NOW() WHERE id=%s""",
                (*values.values(), received_at, item_id),
            )
            action = "status" if values["status"] != current.get("status") else "editado"
            cur.execute("INSERT INTO compras_historico (compra_id,acao,status_anterior,status_novo,usuario,detalhes) VALUES (%s,%s,%s,%s,%s,%s)", (item_id, action, current.get("status"), values["status"], actor, values["titulo"]))
            conn.commit()
            return jsonify({"ok": True, "id": item_id})
        except ValueError as exc:
            conn.rollback()
            return jsonify({"erro": str(exc)}), 400
        finally:
            cur.close()
            conn.close()

    def purchase_forecast_data(group_filter="", product_filter=0):
        today = datetime.date.today()
        week_start = today - datetime.timedelta(days=(today.weekday() + 1) % 7)
        elapsed = max(1, (today - week_start).days + 1)
        month_start = today.replace(day=1)
        last_year_month = month_start.replace(year=month_start.year - 1)
        recent_months = [month_shift(month_start, -index) for index in (1, 2, 3)]
        history_keys = {month_key(last_year_month), *[month_key(month) for month in recent_months]}
        stock_payload = estoque_resumo(incluir_fornecedores=True)
        stock_by_product = {as_int(row.get("produto_id"), 0): row for row in stock_payload.get("rows") or []}
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            lookup = estoque_lookup(cur)
            cur.execute(
                """SELECT p.id,p.nome_produto,p.produto_base_nome,p.grupo_estoque,p.unidade,
                p.embalagem_tipo_padrao,p.fator_embalagem_padrao,g.nome AS grupo_nome,
                g.estoque_area,g.estoque_subgrupo,cfg.fornecedor_id,cfg.estoque_seguranca,
                cfg.prazo_entrega_dias,cfg.lote_minimo,cfg.multiplo_compra,
                cfg.ativo AS previsao_ativa,
                COALESCE(NULLIF(f.nome,''),NULLIF(f.dominios,''),NULLIF(f.emails,'')) AS fornecedor_nome
                FROM estoque_produtos p
                LEFT JOIN estoque_grupos g ON g.codigo=p.grupo_estoque AND g.ativo=1
                LEFT JOIN compras_produto_config cfg ON cfg.produto_id=p.id
                LEFT JOIN gestor_email_fornecedores f ON f.id=cfg.fornecedor_id AND f.ativo=1
                WHERE p.ativo=1 ORDER BY COALESCE(g.ordem,100),p.nome_produto"""
            )
            products = cur.fetchall() or []
            history = defaultdict(lambda: defaultdict(float))
            cur.execute(
                """SELECT codigo_barras,codigo_produto_nfe,nome_produto,
                DATE_FORMAT(data_registro,'%%Y-%%m') AS mes,SUM(quantidade) AS quantidade
                FROM estoque_movimentos WHERE tipo_movimento='saida' AND data_registro >= %s
                GROUP BY codigo_barras,codigo_produto_nfe,nome_produto,DATE_FORMAT(data_registro,'%%Y-%%m')""",
                (min([last_year_month, *recent_months]),),
            )
            for movement in cur.fetchall() or []:
                product = estoque_resolver(
                    lookup,
                    codigo_barras=movement.get("codigo_barras"),
                    codigo_produto_nfe=movement.get("codigo_produto_nfe"),
                    nome_produto=movement.get("nome_produto"),
                ) or {}
                product_id = as_int(product.get("id"), 0)
                key = as_str(movement.get("mes"))
                if product_id and key in history_keys:
                    history[product_id][key] += as_float(movement.get("quantidade"), 0)
            cur.execute("""SELECT produto_id,SUM(quantidade) AS quantidade_aberta
                FROM compras_solicitacoes WHERE ativo=1 AND status NOT IN ('recebido','cancelado')
                AND produto_id IS NOT NULL GROUP BY produto_id""")
            open_purchases = {as_int(row.get("produto_id"), 0): as_float(row.get("quantidade_aberta"), 0) for row in (cur.fetchall() or [])}
            cur.execute("""SELECT f.id,f.nome,f.cnpj,f.dominios,f.emails,
                COALESCE(NULLIF(f.nome,''),NULLIF(f.dominios,''),NULLIF(f.emails,''),CONCAT('Fornecedor #',f.id)) AS nome_exibicao,
                COALESCE(cfg.contato_compras,'') AS contato_compras,
                COALESCE(cfg.representante_nome,'') AS representante_nome,
                COALESCE(cfg.telefone,'') AS telefone,COALESCE(cfg.endereco,'') AS endereco
                FROM gestor_email_fornecedores f LEFT JOIN compras_fornecedor_config cfg
                ON cfg.fornecedor_id=f.id WHERE f.ativo=1 ORDER BY nome_exibicao""")
            suppliers = cur.fetchall() or []
        finally:
            cur.close()
            conn.close()
        normalized_group = services["normalize_stock_group"](group_filter) if group_filter else ""
        product_filter = as_int(product_filter, 0)
        rows = []
        for product in products:
            product_id = as_int(product.get("id"), 0)
            group = services["normalize_stock_group"](product.get("grupo_estoque"))
            classification = estoque_classificar(product)
            if classification.get("estoque_subgrupo") == "PRODUTOS" and group in {"GFA", "PET", "AGUA"}:
                continue
            if normalized_group and group != normalized_group:
                continue
            if product_filter and product_id != product_filter:
                continue
            stock = stock_by_product.get(product_id) or {}
            lead = as_int(product.get("prazo_entrega_dias"), 7) or 7
            calculation = purchase_forecast(
                last_year_month=history[product_id].get(month_key(last_year_month), 0),
                recent_months=[history[product_id].get(month_key(month), 0) for month in recent_months],
                current_week=stock.get("saidas_semana", 0),
                elapsed_week_days=elapsed,
                month_days=month_end(month_start).day,
                current_stock=stock.get("quantidade_atual", 0),
                open_purchases=open_purchases.get(product_id, 0),
                safety_stock=product.get("estoque_seguranca", 0),
                lead_days=lead,
                minimum_lot=product.get("lote_minimo", 0),
                purchase_multiple=product.get("multiplo_compra", 1),
            )
            rows.append({
                **product,
                **classification,
                **calculation,
                "produto_id": product_id,
                "nome_produto": as_str(product.get("produto_base_nome") or product.get("nome_produto")),
                "grupo_estoque": group,
                "grupo_nome": as_str(product.get("grupo_nome")) or group,
                "quantidade_atual": round(as_float(stock.get("quantidade_atual"), 0), 3),
                "consumo_semana_atual": round(as_float(stock.get("saidas_semana"), 0), 3),
                "compras_abertas": round(open_purchases.get(product_id, 0), 3),
                "prazo_entrega_dias": lead,
                "estoque_seguranca": round(as_float(product.get("estoque_seguranca"), 0), 3),
                "lote_minimo": round(as_float(product.get("lote_minimo"), 0), 3),
                "multiplo_compra": round(max(0.001, as_float(product.get("multiplo_compra"), 1)), 3),
                "previsao_ativa": bool(as_int(product.get("previsao_ativa"), 1)),
            })
        rows.sort(key=lambda row: (-as_float(row.get("sugestao_compra"), 0), as_str(row.get("grupo_nome")), as_str(row.get("nome_produto"))))
        groups = sorted({(row.get("grupo_estoque"), row.get("grupo_nome")) for row in rows})
        return {
            "rows": rows,
            "opcoes": {
                "grupos": [{"codigo": code, "nome": name} for code, name in groups],
                "produtos": [{"id": row["produto_id"], "nome": row["nome_produto"], "grupo_estoque": row["grupo_estoque"]} for row in rows],
                "fornecedores": suppliers,
            },
            "meta": {
                "atualizado_em": fmt_dt(datetime.datetime.now()),
                "itens": len(rows),
                "itens_com_sugestao": sum(1 for row in rows if as_float(row.get("sugestao_compra"), 0) > 0),
                "sugestao_total": round(sum(as_float(row.get("sugestao_compra"), 0) for row in rows), 3),
                "inicio_semana": fmt_date(week_start),
                "fim_semana": fmt_date(week_start + datetime.timedelta(days=6)),
            },
        }

    @bp.route("/api/compras/previsao", methods=["GET"])
    def purchase_forecast_api():
        return jsonify(purchase_forecast_data(request.args.get("grupo_estoque") or "", request.args.get("produto_id") or 0))

    @bp.route("/api/compras/produtos/<int:product_id>/config", methods=["PUT"])
    def purchase_product_config_api(product_id):
        payload = request.get_json(silent=True) or {}
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                """INSERT INTO compras_produto_config
                (produto_id,fornecedor_id,estoque_seguranca,prazo_entrega_dias,lote_minimo,multiplo_compra,ativo)
                VALUES (%s,%s,%s,%s,%s,%s,1)
                ON DUPLICATE KEY UPDATE fornecedor_id=VALUES(fornecedor_id),
                estoque_seguranca=VALUES(estoque_seguranca),prazo_entrega_dias=VALUES(prazo_entrega_dias),
                lote_minimo=VALUES(lote_minimo),multiplo_compra=VALUES(multiplo_compra),ativo=1,atualizado_em=NOW()""",
                (product_id, as_int(payload.get("fornecedor_id"), 0) or None,
                 max(0, as_float(payload.get("estoque_seguranca"), 0)),
                 max(1, as_int(payload.get("prazo_entrega_dias"), 7)),
                 max(0, as_float(payload.get("lote_minimo"), 0)),
                 max(0.001, as_float(payload.get("multiplo_compra"), 1))),
            )
            conn.commit()
            return jsonify({"ok": True})
        finally:
            cur.close()
            conn.close()

    def save_supplier_config(cur, supplier_id, payload):
        cur.execute(
            """INSERT INTO compras_fornecedor_config
            (fornecedor_id,prazo_entrega_dias,pedido_minimo_valor,condicao_pagamento,contato_compras,
             representante_nome,telefone,endereco)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE prazo_entrega_dias=VALUES(prazo_entrega_dias),
            pedido_minimo_valor=VALUES(pedido_minimo_valor),condicao_pagamento=VALUES(condicao_pagamento),
            contato_compras=VALUES(contato_compras),representante_nome=VALUES(representante_nome),
            telefone=VALUES(telefone),endereco=VALUES(endereco),atualizado_em=NOW()""",
            (supplier_id, max(1, as_int(payload.get("prazo_entrega_dias"), 7)),
             max(0, as_float(payload.get("pedido_minimo_valor"), 0)),
             as_str(payload.get("condicao_pagamento"))[:180], as_str(payload.get("contato_compras"))[:255],
             as_str(payload.get("representante_nome"))[:255], as_str(payload.get("telefone"))[:80],
             as_str(payload.get("endereco"))[:500]),
        )

    @bp.route("/api/compras/fornecedores", methods=["GET", "POST"])
    def purchase_suppliers_api():
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            if request.method == "GET":
                cur.execute("""SELECT f.*,COALESCE(cfg.prazo_entrega_dias,7) AS prazo_entrega_dias,
                    COALESCE(cfg.pedido_minimo_valor,0) AS pedido_minimo_valor,
                    COALESCE(cfg.condicao_pagamento,'') AS condicao_pagamento,
                    COALESCE(cfg.contato_compras,'') AS contato_compras,
                    COALESCE(cfg.representante_nome,'') AS representante_nome,
                    COALESCE(cfg.telefone,'') AS telefone,
                    COALESCE(cfg.endereco,'') AS endereco
                    FROM gestor_email_fornecedores f LEFT JOIN compras_fornecedor_config cfg
                    ON cfg.fornecedor_id=f.id WHERE f.ativo=1 ORDER BY f.nome""")
                return jsonify(cur.fetchall() or [])
            payload = request.get_json(silent=True) or {}
            name = as_str(payload.get("nome"))[:255]
            if not name:
                return jsonify({"erro": "Informe o nome do fornecedor."}), 400
            cnpj = re.sub(r"\D+", "", as_str(payload.get("cnpj"))) or None
            now = fmt_dt(datetime.datetime.now())
            cur.execute("""INSERT INTO gestor_email_fornecedores
                (cnpj,nome,categoria,emails,dominios,observacoes,ativo,origem,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,1,'compras',%s,%s)""",
                (cnpj, name, as_str(payload.get("categoria"))[:40] or "outros", as_str(payload.get("emails")), as_str(payload.get("dominios")), as_str(payload.get("observacoes")), now, now))
            supplier_id = cur.lastrowid
            save_supplier_config(cur, supplier_id, payload)
            conn.commit()
            return jsonify({"ok": True, "id": supplier_id}), 201
        except mysql.connector.IntegrityError:
            conn.rollback()
            return jsonify({"erro": "Ja existe um fornecedor com esse CNPJ."}), 409
        finally:
            cur.close()
            conn.close()

    @bp.route("/api/compras/fornecedores/<int:supplier_id>", methods=["PUT", "DELETE"])
    def purchase_supplier_item_api(supplier_id):
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            if request.method == "DELETE":
                cur.execute("UPDATE gestor_email_fornecedores SET ativo=0,updated_at=%s WHERE id=%s", (fmt_dt(datetime.datetime.now()), supplier_id))
            else:
                payload = request.get_json(silent=True) or {}
                name = as_str(payload.get("nome"))[:255]
                if not name:
                    return jsonify({"erro": "Informe o nome do fornecedor."}), 400
                cnpj = re.sub(r"\D+", "", as_str(payload.get("cnpj"))) or None
                cur.execute("""UPDATE gestor_email_fornecedores SET cnpj=%s,nome=%s,categoria=%s,
                    emails=%s,dominios=%s,observacoes=%s,ativo=1,updated_at=%s WHERE id=%s""",
                    (cnpj, name, as_str(payload.get("categoria"))[:40] or "outros", as_str(payload.get("emails")), as_str(payload.get("dominios")), as_str(payload.get("observacoes")), fmt_dt(datetime.datetime.now()), supplier_id))
                save_supplier_config(cur, supplier_id, payload)
            conn.commit()
            return jsonify({"ok": True})
        except mysql.connector.IntegrityError:
            conn.rollback()
            return jsonify({"erro": "Ja existe um fornecedor com esse CNPJ."}), 409
        finally:
            cur.close()
            conn.close()

    @bp.route("/api/dashboard_processos", methods=["GET"])
    def process_dashboard_api():
        return jsonify(process_list({}))

    @bp.route("/api/dashboard_compras", methods=["GET"])
    def purchase_dashboard_api():
        return jsonify({"compras": purchase_list({}), "previsao": purchase_forecast_data()})

    def build_pdf(title, headers, rows, summary):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower())
        path = os.path.join("/tmp", f"{slug}_{stamp}.pdf")
        doc = SimpleDocTemplate(path, pagesize=landscape(A4), topMargin=24, leftMargin=18, rightMargin=18, bottomMargin=30)
        styles = getSampleStyleSheet()
        body = styles["BodyText"].clone("GestaoBody")
        body.fontSize = 7
        body.leading = 8
        elements = [report_header(styles), Spacer(1, 10), Paragraph(pdf_escape(title), styles["Heading2"]), Paragraph(pdf_escape(summary), styles["Normal"]), Spacer(1, 8)]
        table_rows = [headers] + [[Paragraph(pdf_escape(value), body) for value in row] for row in rows]
        if len(table_rows) == 1:
            table_rows.append([Paragraph("Nenhum registro para os filtros selecionados.", body)] + [""] * (len(headers) - 1))
        table = Table(table_rows, repeatRows=1, colWidths=[790 / len(headers)] * len(headers))
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f59e0b")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ]))
        elements.append(table)
        doc.build(elements)
        return path

    @bp.route("/api/processos-internos/relatorio", methods=["GET"])
    def process_report_api():
        return jsonify(process_list(request.args))

    @bp.route("/api/processos-internos/relatorio/pdf", methods=["GET"])
    def process_report_pdf_api():
        payload = process_list(request.args)
        rows = [[row.get("id"), row.get("titulo"), row.get("tipo_nome"), row.get("status"), row.get("prioridade"), row.get("responsavel_nome"), row.get("prazo") or "-"] for row in payload["rows"]]
        path = build_pdf("Relatorio de Processos Internos", ["ID", "Processo", "Tipo", "Status", "Prioridade", "Responsavel", "Prazo"], rows, f"Total: {payload['meta']['total']} | Atrasados: {payload['meta']['atrasados']}")
        return send_file(path, as_attachment=False, mimetype="application/pdf", download_name=os.path.basename(path))

    @bp.route("/api/compras/relatorio", methods=["GET"])
    def purchase_report_api():
        return jsonify(purchase_list(request.args))

    @bp.route("/api/compras/relatorio/pdf", methods=["GET"])
    def purchase_report_pdf_api():
        payload = purchase_list(request.args)
        rows = [[row.get("id"), row.get("titulo"), row.get("produto_nome") or "-", row.get("fornecedor_nome") or "-", row.get("status"), f"{decimal_br(row.get('quantidade'), 3)} {row.get('unidade') or 'UN'}", decimal_br(row.get("valor_total_previsto"), 2), row.get("data_necessidade") or "-"] for row in payload["rows"]]
        summary = f"Total: {payload['meta']['total']} | Atrasadas: {payload['meta']['atrasadas']} | Valor previsto: R$ {decimal_br(payload['meta']['valor_total_previsto'], 2)}"
        path = build_pdf("Relatorio de Compras", ["ID", "Compra", "Produto", "Fornecedor", "Status", "Quantidade", "Valor previsto", "Necessidade"], rows, summary)
        return send_file(path, as_attachment=False, mimetype="application/pdf", download_name=os.path.basename(path))

    app.register_blueprint(bp)
