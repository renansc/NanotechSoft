import datetime as dt
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app as portal


PROJECT_DIR = Path(__file__).resolve().parents[1]


class ChamadosTests(unittest.TestCase):
    def test_manifest_schema_and_allowed_app(self):
        manifest = json.loads((PROJECT_DIR / "apps/chamados/app.json").read_text(encoding="utf-8"))
        schema = (PROJECT_DIR / "sql/schema.sql").read_text(encoding="utf-8")
        allowed = (PROJECT_DIR / "apps_liberados.txt").read_text(encoding="utf-8").splitlines()

        self.assertEqual("chamados", manifest["app_key"])
        self.assertEqual("apps/chamados/source", manifest["source_dir"])
        self.assertIn("workflow", manifest["menu_groups"])
        self.assertIn("relatorios", manifest["menu_groups"])
        self.assertIn("chamados", allowed)
        self.assertIn("CREATE TABLE IF NOT EXISTS chamados (", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS chamados_intervencoes (", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS chamados_documentos (", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS chamados_agenda (", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS chamados_conky_sync (", schema)
        self.assertTrue(any(item["recurso"] == "agenda" for item in manifest["menu_groups"]["workflow"]))
        self.assertTrue(any(item["recurso"] == "agenda" for item in manifest["workflow_cards"]))

    def test_routes_and_static_integration_are_registered(self):
        routes = {rule.rule: rule.methods for rule in portal.app.url_map.iter_rules()}

        self.assertIn("chamados", portal.STATIC_APP_DIRS)
        self.assertEqual("Chamados", portal.STATIC_APP_NAMES["chamados"])
        self.assertIn("/apps/chamados", routes)
        self.assertIn("GET", routes["/apps/chamados/api/bootstrap"])
        self.assertIn("POST", routes["/apps/chamados/api/tickets"])
        self.assertIn("PUT", routes["/apps/chamados/api/tickets/<int:chamado_id>"])
        self.assertIn("POST", routes["/apps/chamados/api/tickets/<int:chamado_id>/interventions"])
        self.assertIn(
            "PUT",
            routes["/apps/chamados/api/tickets/<int:chamado_id>/interventions/<int:intervencao_id>"],
        )
        self.assertIn("GET", routes["/apps/chamados/api/similar"])
        self.assertIn("POST", routes["/apps/chamados/api/documents"])
        self.assertIn("PUT", routes["/apps/chamados/api/documents/<int:document_id>"])
        self.assertIn("POST", routes["/apps/chamados/api/agenda"])
        self.assertIn("GET", routes["/apps/chamados/api/agenda"])
        self.assertIn("PUT", routes["/apps/chamados/api/agenda/<int:agenda_id>"])

    def test_agenda_payload_converts_local_schedule_to_utc_and_validates_recipients(self):
        payload = portal.chamado_agenda_payload({
            "type": "REUNIAO",
            "title": "Reunião de orçamento",
            "scheduledAt": "2026-08-28T14:00:00-03:00",
            "reminderMinutes": 60,
            "recipients": "compras@example.com; DIRETORIA@example.com",
        })

        self.assertEqual(dt.datetime(2026, 8, 28, 17, 0), payload["scheduled_at"])
        self.assertEqual(dt.datetime(2026, 8, 28, 16, 0), payload["notify_at"])
        self.assertEqual("compras@example.com,diretoria@example.com", payload["recipients"])

    def test_agenda_email_uses_existing_smtp_and_task_recipients(self):
        smtp = mock.MagicMock()
        smtp.return_value.__enter__.return_value = smtp.return_value
        item = {
            "id": 2, "tipo": "ORCAMENTO", "titulo": "Enviar orçamento",
            "descricao": "Revisar valores antes do envio.",
            "agendado_em": dt.datetime(2026, 8, 28, 17, 0),
            "destinatarios": "cliente@example.com,equipe@example.com",
            "protocolo": "CH-2026-000002", "chamado_titulo": "Cotação de servidor",
        }
        config = {
            "host": "smtp.example.com", "port": 587, "user": "portal@example.com",
            "password": "secret", "sender": "portal@example.com", "useTls": True,
        }
        with (
            mock.patch.object(portal, "technology_email_config", return_value=config),
            mock.patch.object(portal.smtplib, "SMTP", smtp),
        ):
            recipients = portal.send_chamado_agenda_email(item)

        self.assertEqual(["cliente@example.com", "equipe@example.com"], recipients)
        smtp.return_value.starttls.assert_called_once()
        message = smtp.return_value.send_message.call_args.args[0]
        self.assertIn("Enviar orçamento", message["Subject"])
        self.assertIn("cliente@example.com", message["To"])

    def test_nanotech_chamados_bootstrap_filters_legacy_rio_seed_records(self):
        conn = mock.MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchall.side_effect = [[], []]
        cursor.fetchone.return_value = {}
        with (
            portal.app.test_request_context("/apps/chamados/api/bootstrap"),
            mock.patch.object(portal, "current_user_or_logout", return_value={"id": 9, "nome": "Local", "login": "local"}),
            mock.patch.object(portal, "configured_client_id", return_value="nanotech"),
            mock.patch.object(portal, "start_chamados_agenda_scheduler"),
            mock.patch.object(portal, "get_conn", return_value=conn),
        ):
            portal.session["usuario_id"] = 9
            response = portal.chamados_bootstrap_api()

        self.assertEqual(200, response.status_code)
        user_sql, user_params = cursor.execute.call_args_list[0].args
        device_sql, device_params = cursor.execute.call_args_list[1].args
        self.assertIn("login NOT IN", user_sql)
        self.assertIn("host NOT IN", device_sql)
        self.assertIn("riob", user_params)
        self.assertIn("192.168.200.254", device_params)

    def test_public_ticket_exposes_time_and_linked_records(self):
        row = {
            "id": 9, "protocolo": "CH-2026-000009", "titulo": "Sem rede",
            "descricao": "Estacao sem acesso", "categoria": "TI", "prioridade": "ALTA",
            "status": "RESOLVIDO", "solicitante_id": 2, "solicitante_nome": "Rebeca",
            "responsavel_id": 1, "responsavel_nome": "Administrador", "dispositivo_id": 12,
            "dispositivo_nome": "PC RB02", "dispositivo_tipo": "COMPUTADOR",
            "dispositivo_host": "192.168.200.21", "minutos_gastos": 35,
            "intervencoes_count": 3, "documentos_count": 1,
            "created_at": dt.datetime(2026, 8, 25, 10, 0),
            "updated_at": dt.datetime(2026, 8, 25, 11, 0),
        }

        item = portal.chamado_public_row(row)

        self.assertEqual(35, item["minutesSpent"])
        self.assertEqual("Rebeca", item["requesterName"])
        self.assertEqual("PC RB02", item["deviceName"])
        self.assertTrue(item["createdAt"].endswith("Z"))

    def test_similar_search_prioritizes_same_category_and_terms(self):
        resolved = {
            "id": 5, "protocolo": "CH-2026-000005", "titulo": "Impressora nao imprime",
            "descricao": "Fila travada", "categoria": "TI", "subcategoria": "Impressora",
            "prioridade": "MEDIA", "status": "RESOLVIDO", "solucao_resumo": "Limpar fila e reiniciar spooler",
            "causa_raiz": "Spooler travado", "minutos_gastos": 20, "created_at": None,
            "updated_at": None,
        }
        conn = mock.MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchall.side_effect = [[resolved], []]
        with mock.patch.object(portal, "get_conn", return_value=conn):
            result = portal.chamado_similar_suggestions(
                "impressora com fila travada e nao imprime", "TI", "Impressora"
            )

        self.assertEqual("CH-2026-000005", result["tickets"][0]["protocol"])
        self.assertIn("mesma categoria", result["tickets"][0]["similarityReasons"])
        self.assertEqual([], result["documents"])

    def test_solution_history_lists_recorded_solution_before_ticket_is_closed(self):
        in_progress = {
            "id": 6, "protocolo": "CH-2026-000006", "titulo": "Teste de fonte",
            "descricao": "Equipamento reiniciando", "categoria": "TI", "subcategoria": "Hardware",
            "prioridade": "MEDIA", "status": "EM_ATENDIMENTO",
            "solucao_resumo": "Fonte substituida e carga validada", "minutos_gastos": 30,
            "created_at": None, "updated_at": None,
        }
        conn = mock.MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchall.side_effect = [[in_progress], []]
        with mock.patch.object(portal, "get_conn", return_value=conn):
            result = portal.chamado_similar_suggestions(browse_history=True)

        self.assertEqual("CH-2026-000006", result["tickets"][0]["protocol"])
        self.assertIn("solução registrada", result["tickets"][0]["similarityReasons"])
        first_sql = cursor.execute.call_args_list[0].args[0]
        self.assertIn("TRIM(c.solucao_resumo)", first_sql)

    def test_intervention_history_can_be_edited_and_updates_resolution_summary(self):
        current = {
            "id": 1, "titulo": "Falha eletrica", "descricao": "Tomada sem energia",
            "categoria": "ELETRICA", "prioridade": "ALTA", "status": "RESOLVIDO",
            "solucao_resumo": "Troca do disjuntor",
        }
        intervention = {
            "id": 8, "chamado_id": 1, "tipo": "SOLUCAO", "descricao": "Disjuntor trocado",
            "minutos_gastos": 25, "solucao_aplicada": "Troca do disjuntor",
        }
        conn = mock.MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchone.side_effect = [intervention, {"solucao_aplicada": "Reaperto e troca do disjuntor"}]
        with (
            portal.app.test_request_context(
                "/apps/chamados/api/tickets/1/interventions/8", method="PUT",
                json={"description": "Conexoes reapertadas", "resolution": "Reaperto e troca do disjuntor"},
            ),
            mock.patch.object(portal, "get_chamado", return_value=current),
            mock.patch.object(portal, "get_conn", return_value=conn),
        ):
            portal.session["usuario_id"] = 1
            response = portal.chamados_intervention_update_api(1, 8)

        self.assertEqual(200, response.status_code)
        executed_sql = "\n".join(call.args[0] for call in cursor.execute.call_args_list)
        self.assertIn("UPDATE chamados_intervencoes", executed_sql)
        self.assertIn("UPDATE chamados SET solucao_resumo", executed_sql)
        conn.commit.assert_called_once()

    def test_resolved_status_requires_resolution_measure(self):
        current = {
            "id": 1, "titulo": "Falha eletrica", "descricao": "Tomada sem energia",
            "categoria": "ELETRICA", "prioridade": "ALTA", "status": "EM_ATENDIMENTO",
        }
        with (
            portal.app.test_request_context(
                "/apps/chamados/api/tickets/1", method="PUT", json={"status": "RESOLVIDO"}
            ),
            mock.patch.object(portal, "get_chamado", return_value=current),
            mock.patch.object(portal, "current_user_or_logout", return_value={"id": 1, "perfil": "admin"}),
        ):
            portal.session["usuario_id"] = 1
            response, status = portal.chamados_ticket_api(1)

        self.assertEqual(400, status)
        self.assertIn("medida resolutiva", response.get_json()["erro"])

    def test_document_metadata_can_be_edited_without_replacing_current_file(self):
        current = {
            "id": 4, "dispositivo_id": 2, "categoria": "TI", "titulo": "Manual antigo",
            "descricao": "Procedimento", "nome_arquivo": "manual.pdf",
            "arquivo_armazenado": "abc123.pdf", "mime_type": "application/pdf",
            "tamanho_bytes": 512, "url_externa": "",
        }
        conn = mock.MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchone.return_value = current
        with (
            portal.app.test_request_context(
                "/apps/chamados/api/documents/4", method="PUT",
                data={"title": "Manual atualizado", "category": "TI", "deviceId": "", "description": "Nova versao"},
            ),
            mock.patch.object(portal, "get_conn", return_value=conn),
        ):
            portal.session["usuario_id"] = 1
            response = portal.chamados_document_update_api(4)

        self.assertEqual(200, response.status_code)
        update_call = next(call for call in cursor.execute.call_args_list if "UPDATE chamados_documentos" in call.args[0])
        params = update_call.args[1]
        self.assertEqual("Manual atualizado", params[2])
        self.assertEqual("abc123.pdf", params[5])
        conn.commit.assert_called_once()

    def test_document_file_replacement_removes_old_file_only_after_database_update(self):
        current = {
            "id": 4, "dispositivo_id": None, "categoria": "TI", "titulo": "Manual",
            "descricao": "Procedimento", "nome_arquivo": "antigo.pdf",
            "arquivo_armazenado": "old-file.pdf", "mime_type": "application/pdf",
            "tamanho_bytes": 10, "url_externa": "https://example.test/manual",
        }
        conn = mock.MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchone.return_value = current
        with tempfile.TemporaryDirectory() as temp_dir:
            upload_dir = Path(temp_dir)
            old_file = upload_dir / "old-file.pdf"
            old_file.write_bytes(b"old")
            with (
                portal.app.test_request_context(
                    "/apps/chamados/api/documents/4", method="PUT",
                    data={
                        "title": "Manual novo", "category": "TI",
                        "file": (io.BytesIO(b"new pdf"), "novo.pdf"),
                        "externalUrl": "https://example.test/manual",
                    },
                ),
                mock.patch.object(portal, "get_conn", return_value=conn),
                mock.patch.object(portal, "CHAMADOS_UPLOAD_DIR", upload_dir),
            ):
                portal.session["usuario_id"] = 1
                response = portal.chamados_document_update_api(4)

            self.assertEqual(200, response.status_code)
            update_call = next(call for call in cursor.execute.call_args_list if "UPDATE chamados_documentos" in call.args[0])
            params = update_call.args[1]
            self.assertNotEqual("old-file.pdf", params[5])
            self.assertEqual("", params[8])
            self.assertFalse(old_file.exists())
            self.assertTrue((upload_dir / params[5]).is_file())
            conn.commit.assert_called_once()

    def test_static_frontend_contains_required_workflows(self):
        html = (PROJECT_DIR / "apps/chamados/source/index.html").read_text(encoding="utf-8")
        javascript = (PROJECT_DIR / "apps/chamados/source/app.js").read_text(encoding="utf-8")

        self.assertIn("Chamados e Manutenções", html)
        self.assertIn("Histórico de soluções", html)
        self.assertIn("Manuais e documentos", html)
        self.assertIn("Agenda de tarefas", html)
        self.assertIn("E-mails destinatários", html)
        self.assertIn("Tempo gasto", html)
        self.assertIn("Medida resolutiva", html)
        self.assertIn("Salvar alterações do chamado", html)
        self.assertIn("cancelDocumentEdit", html)
        self.assertIn("data-edit-document", javascript)
        self.assertIn("data-edit-intervention", javascript)
        self.assertIn('const API = "/apps/chamados/api"', javascript)
        self.assertIn("/interventions", javascript)
        self.assertIn("/similar", javascript)
        self.assertIn("/agenda", javascript)
        self.assertIn("submitAgenda", javascript)

    def test_conky_status_mapping_preserves_triage_until_column_changes(self):
        self.assertEqual("todo", portal.CHAMADO_TO_CONKY["ABERTO"])
        self.assertEqual("todo", portal.CHAMADO_TO_CONKY["TRIAGEM"])
        self.assertEqual("today", portal.CHAMADO_TO_CONKY["EM_ATENDIMENTO"])
        self.assertEqual("waiting", portal.CHAMADO_TO_CONKY["AGUARDANDO"])

        cursor = mock.MagicMock()
        ticket = {"id": 7, "titulo": "Revisar servidor", "status": "TRIAGEM"}
        unchanged_task = {
            "status": "todo", "text": "Revisar servidor",
            "syncedStatus": "todo", "syncedText": "Revisar servidor",
        }
        changed_task = {**unchanged_task, "status": "today"}

        self.assertFalse(portal._update_chamado_from_conky(cursor, unchanged_task, ticket))
        self.assertTrue(portal._update_chamado_from_conky(cursor, changed_task, ticket))
        update_params = cursor.execute.call_args_list[0].args[1]
        self.assertEqual("EM_ATENDIMENTO", update_params[1])

    def test_conky_task_creates_ticket_and_persists_link_metadata(self):
        connection = mock.MagicMock()
        cursor = connection.cursor.return_value
        cursor.lastrowid = 55
        cursor.fetchall.side_effect = [
            [],
            [{
                "id": 55, "protocolo": "CH-2026-000055", "titulo": "Trocar toner",
                "status": "ABERTO", "created_at": dt.datetime(2026, 9, 3, 12, 0),
                "updated_at": dt.datetime(2026, 9, 3, 12, 0),
                "sync_key": "abc123", "tarefa_id": "1",
            }],
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            task_file = Path(temp_dir) / "kanban-tasks.json"
            task_file.write_text(json.dumps([{
                "id": "1", "status": "todo", "text": "Trocar toner",
                "created": 1, "updated": 1, "syncKey": "abc123",
            }]), encoding="utf-8")
            with mock.patch.object(portal, "get_conn", return_value=connection):
                result = portal.sync_chamados_conky(task_file)
            persisted = json.loads(task_file.read_text(encoding="utf-8"))[0]

        self.assertEqual(1, result["created"])
        self.assertEqual("55", persisted["id"])
        self.assertEqual(55, persisted["ticketId"])
        self.assertEqual("CH-2026-000055", persisted["protocol"])
        executed_sql = "\n".join(call.args[0] for call in cursor.execute.call_args_list)
        self.assertIn("INSERT INTO chamados\n", executed_sql)
        self.assertIn("INSERT INTO chamados_conky_sync", executed_sql)
        connection.commit.assert_called()

    def test_conky_legacy_save_recovers_link_instead_of_duplicating_ticket(self):
        task = {
            "id": "2", "status": "today", "text": "gps integrar vendas",
            "created": 1, "updated": 2, "syncKey": "temporary-new-key",
        }
        linked = [{
            "id": 12, "sync_key": "stable-key", "tarefa_id": "2",
            "titulo": "gps integrar vendas", "status": "ABERTO",
        }]

        by_key, recovered = portal._recover_chamado_conky_links([task], linked)

        self.assertEqual(1, recovered)
        self.assertEqual("stable-key", task["syncKey"])
        self.assertEqual(12, task["ticketId"])
        self.assertIn("stable-key", by_key)

    def test_javascript_has_valid_syntax_in_chrome(self):
        browser = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("node")
        if not browser:
            self.skipTest("Nenhum validador JavaScript instalado")
        javascript = PROJECT_DIR / "apps/chamados/source/app.js"
        if Path(browser).name == "node":
            result = subprocess.run([browser, "--check", str(javascript)], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            return
        with tempfile.TemporaryDirectory() as temp_dir:
            page = Path(temp_dir) / "index.html"
            page.write_text(f"<script>{javascript.read_text(encoding='utf-8')}</script>", encoding="utf-8")
            result = subprocess.run([browser, "--headless", "--no-sandbox", "--dump-dom", page.as_uri()], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
