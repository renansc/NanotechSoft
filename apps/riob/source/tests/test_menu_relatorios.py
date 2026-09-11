import datetime
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from flask import Flask
import legacy_services as legacy
# Extrai funcoes puras/rota para evitar o bootstrap operacional do server nos testes.
import ast
import types
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask import request, jsonify
server = types.ModuleType("report_fixture")
server.__dict__.update(app=Flask("report_fixture"), datetime=datetime, request=request, jsonify=jsonify,
                       Decimal=Decimal, InvalidOperation=InvalidOperation, ROUND_HALF_UP=ROUND_HALF_UP,
                       get_conn=lambda: None)
source = Path(__file__).resolve().parents[1] / "server.py"
names = {"_as_str", "_as_int", "_fmt_date", "_vendas_orcamento_codigo", "_vendas_orcamento_decimal", "_vendas_orcamento_numero_publico", "vendas_orcamentos_relatorio_api"}
nodes = [n for n in ast.parse(source.read_text()).body if isinstance(n, ast.FunctionDef) and n.name in names]
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), server.__dict__)


class QuoteReportTests(unittest.TestCase):
    def test_filters_pagination_and_stored_values(self):
        cur = mock.MagicMock()
        cur.fetchone.return_value = {"total": 75, "valor_real": 9876.54}
        cur.fetchall.return_value = [{"id": 123, "data_ref": datetime.date(2026, 9, 10), "cliente_nome": "Cliente", "valor_bruto": 100, "valor_liquido": 80, "valor_real": 87}]
        conn = mock.MagicMock()
        conn.cursor.return_value = cur
        with server.app.test_request_context("/api/vendas/orcamentos/relatorio?inicio=2026-09-01&fim=2026-09-10&q=Cliente&pagina=2"), mock.patch.object(server, "get_conn", return_value=conn):
            data = server.vendas_orcamentos_relatorio_api().get_json()
        self.assertEqual((75, 2, 50, 9876.54), (data["total"], data["pagina"], data["limite"], data["valor_real"]))
        self.assertEqual("ORC-2026-000123", data["orcamentos"][0]["codigo"])
        self.assertEqual(87, data["orcamentos"][0]["valor_real"])
        self.assertEqual((50, 50), cur.execute.call_args.args[1][-2:])
        self.assertIn("Cliente", cur.execute.call_args.args[1][2])
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_invalid_dates_do_not_open_database(self):
        for query in ("inicio=errada", "inicio=2026-09-10&fim=2026-09-01"):
            with server.app.test_request_context("/api/vendas/orcamentos/relatorio?"+query), mock.patch.object(server, "get_conn") as conn:
                self.assertEqual(400, server.vendas_orcamentos_relatorio_api()[1])
                conn.assert_not_called()


class EmailMenuTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test-fixture"
        self.app.register_blueprint(legacy.EMAIL_BP)
        self.client = self.app.test_client()

    def test_opening_action_pages_never_runs_jobs(self):
        with mock.patch.object(legacy, "_rows") as rows, mock.patch.object(legacy, "_email_page", side_effect=lambda body: body):
            for page, action in (("historico", "importar-historico-xml"), ("recuperar", "recuperar-conteudo"), ("backup", "backup/download")):
                response = self.client.get("/gestor-emails/"+page)
                self.assertEqual(200, response.status_code)
                self.assertIn("/gestor-emails/"+action, response.text)
            rows.assert_not_called()

    def test_backup_contains_content_and_records_missing_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "nota.xml").write_text("<nfe>fixture</nfe>")
            messages = [{"id": 1, "subject": "Teste", "body_text": "Conteudo"}]
            attachments = [{"id": 2, "email_id": 1, "filename": "nota.xml", "path_relativo": "nota.xml"}, {"id": 3, "email_id": 1, "filename": "ausente", "path_relativo": "ausente"}, {"id": 4, "email_id": 1, "filename": "fora", "path_relativo": "../../etc/passwd"}]
            def rows(sql, params):
                self.assertNotIn("config", sql)
                if params[0]: return []
                return messages if "gestor_email_mensagens" in sql else attachments
            with mock.patch.object(legacy, "_email_attachment_dir", root), mock.patch.object(legacy, "_rows", side_effect=rows):
                response = self.client.post("/gestor-emails/backup/download")
                self.assertEqual(200, response.status_code)
                self.assertEqual("no-store", response.headers["Cache-Control"])
                with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                    self.assertEqual(b"<nfe>fixture</nfe>", archive.read("anexos/2/nota.xml"))
                    self.assertIn("Conteudo", archive.read("metadados/0-mensagens.jsonl").decode())
                    metadata = [json.loads(s) for s in archive.read("metadados/0-anexos.jsonl").decode().splitlines()]
                    self.assertEqual([True, True], [m["indisponivel"] for m in metadata[1:]])
                    self.assertNotIn("path_relativo", metadata[0])
                response.close()


if __name__ == "__main__":
    unittest.main()
