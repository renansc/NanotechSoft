import datetime as dt
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import server


class VendasDiarioPastasTest(unittest.TestCase):
    def setUp(self):
        self.status_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.status_dir.cleanup)
        status_path = os.path.join(self.status_dir.name, "ultima-leitura.json")
        patcher = mock.patch.object(server, "VENDAS_DIARIO_STATUS_FILE", status_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        lock_patcher = mock.patch.object(server, "_VENDAS_DIARIO_IMPORT_LOCK", threading.Lock())
        lock_patcher.start()
        self.addCleanup(lock_patcher.stop)
        server._VENDAS_DIARIO_MANUAL_PENDING = False

    def test_cleanup_removes_only_successfully_processed_files(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(server, "VENDAS_DIARIO_LIMPAR_PROCESSADOS", "1"):
            imported = Path(root) / "importado.txt"
            failed = Path(root) / "erro.pdf"
            imported.write_text("ok", encoding="utf-8")
            failed.write_bytes(b"%PDF-erro")

            clean_result = server._vendas_diario_aplicar_limpeza(
                os.fspath(imported), root, [{"status": "ja_importado", "tipo": "txt"}]
            )
            error_result = server._vendas_diario_aplicar_limpeza(
                os.fspath(failed), root, [{"status": "erro", "tipo": "pdf", "erro": "invalido"}]
            )

            self.assertFalse(imported.exists())
            self.assertTrue(clean_result[0]["arquivo_removido"])
            self.assertTrue(failed.exists())
            self.assertNotIn("arquivo_removido", error_result[0])

    def test_manual_read_waits_in_queue_until_current_read_finishes(self):
        completed = threading.Event()
        calls = []

        def run(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return {"processando": True}
            completed.set()
            return {"processando": False}

        with mock.patch.object(server, "_vendas_diario_importar_pasta", side_effect=run), \
                mock.patch.object(server.time, "sleep"):
            self.assertTrue(server._vendas_diario_agendar_manual_pendente())
            self.assertTrue(completed.wait(2))

        self.assertEqual(2, len(calls))
        self.assertEqual(
            {"incluir_sellout": True, "origem": "manual_fila"}, calls[-1]
        )

    def test_scheduler_runs_repeatedly_only_inside_windows_share_window(self):
        with mock.patch.object(server, "VENDAS_DIARIO_JANELA_INICIO", "07:10"), \
                mock.patch.object(server, "VENDAS_DIARIO_JANELA_FIM", "17:00"), \
                mock.patch.object(server, "VENDAS_DIARIO_INTERVALO_MINUTOS", "15"):
            self.assertFalse(server._vendas_diario_janela_ativa(dt.datetime(2026, 8, 26, 7, 9)))
            self.assertTrue(server._vendas_diario_janela_ativa(dt.datetime(2026, 8, 26, 7, 10)))
            self.assertTrue(server._vendas_diario_janela_ativa(dt.datetime(2026, 8, 26, 16, 59)))
            self.assertFalse(server._vendas_diario_janela_ativa(dt.datetime(2026, 8, 26, 17, 0)))
            self.assertEqual(
                server._vendas_diario_scheduler_slot(dt.datetime(2026, 8, 26, 14, 44)),
                server._vendas_diario_scheduler_slot(dt.datetime(2026, 8, 26, 14, 40)),
            )

    def test_scheduler_log_summary_does_not_repeat_every_file(self):
        result = {
            "arquivos": 3,
            "sellout_diario": {"linhas": 1130},
            "resultados": [
                {"status": "importado"},
                {"status": "ja_importado"},
                {"status": "ja_importado"},
            ],
        }

        self.assertEqual(
            {"arquivos": 3, "sellout_diario": 1130, "status": {"importado": 1, "ja_importado": 2}},
            server._vendas_diario_scheduler_result_summary(result),
        )

    def test_scheduler_snapshot_changes_only_when_source_file_changes(self):
        with tempfile.TemporaryDirectory() as root:
            ind3 = Path(root) / "IND3_SELLOUT_D.CSV"
            indb = Path(root) / "INDB_SELLOUT_D.CSV"
            ind3.write_text("primeira versao", encoding="utf-8")
            indb.write_text("outra base", encoding="utf-8")
            with mock.patch.object(server, "fontes_diarias_configuradas", return_value=[os.fspath(ind3), os.fspath(indb)]):
                first = server._vendas_diario_source_snapshot()
                self.assertEqual(first, server._vendas_diario_source_snapshot())
                ind3.write_text("segunda versao maior", encoding="utf-8")
                self.assertNotEqual(first, server._vendas_diario_source_snapshot())

    def test_infers_seller_from_map_prefix(self):
        self.assertEqual("6", server._vendas_diario_vendedor_por_carga({"mapa": "060401"}))
        self.assertEqual("15", server._vendas_diario_vendedor_por_carga({"mapa": "153101"}))

    def test_cards_match_by_route_or_city_only_on_same_date(self):
        astorga = {"data_ref": "2026-08-04", "rota": "521 - Astorga", "cidade": "Astorga", "veiculo_id": None}
        same_route = {"data_ref": "2026-08-04", "rota": "521 - ASTORGA", "cidade": "", "veiculo_id": None}
        same_city = {"data_ref": "2026-08-04", "rota": "Outra rota", "cidade": "Astorga / Iguaracu", "veiculo_id": None}
        other_date = {"data_ref": "2026-08-05", "rota": "521 - ASTORGA", "cidade": "Astorga", "veiculo_id": None}
        other_vehicle = {"data_ref": "2026-08-04", "rota": "521 - ASTORGA", "cidade": "Astorga", "veiculo_id": 2}

        self.assertTrue(server._vendas_diario_cards_compativeis(astorga, same_route))
        self.assertTrue(server._vendas_diario_cards_compativeis(astorga, same_city))
        self.assertFalse(server._vendas_diario_cards_compativeis(astorga, other_date))
        self.assertFalse(server._vendas_diario_cards_compativeis({**astorga, "veiculo_id": 1}, other_vehicle))

    def test_automatic_import_reads_only_sellout_daily_sources(self):
        daily = {"status": "importado", "linhas": 6500,
                 "fontes": [{"nome": "IND3", "linhas": 790}, {"nome": "INDB", "linhas": 5710}]}
        with mock.patch.object(server, "fontes_diarias_configuradas", return_value=["IND3/D", "INDB/D"]), \
                mock.patch.object(server, "_vendas_sellout_diario_importar", return_value=daily) as importer:
            result = server._vendas_diario_importar_pasta()
        self.assertFalse(result["processando"])
        self.assertEqual(2, result["arquivos"])
        self.assertEqual(["sellout_diario"], [item["tipo"] for item in result["resultados"]])
        importer.assert_called_once_with()

    def test_sellout_daily_error_preserves_previous_base(self):
        with mock.patch.object(server, "fontes_diarias_configuradas", return_value=["IND3/D", "INDB/D"]), \
                mock.patch.object(server, "_vendas_sellout_diario_importar", side_effect=ValueError("SELLOUT_D invalido")):
            result = server._vendas_diario_importar_pasta()
        self.assertEqual("erro", result["resultados"][0]["status"])
        self.assertIn("SELLOUT_D invalido", result["sellout_diario"]["erro"])

    def test_linked_pdf_for_same_seller_is_idempotent_not_error(self):
        conn = mock.MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchone.side_effect = [
            {"id": 17},
            {"id": 31, "status": "enviado_frete", "frete_id": 8, "vendedor_codigo": "15"},
        ]
        carga = {"assinatura": "abc", "mapa": "151501"}
        with mock.patch.object(server, "get_conn", return_value=conn):
            result = server._vendas_diario_importar_carga_pdf_arquivo(
                "/tmp/carga.pdf", vendedor_codigo="15", carga=carga
            )
        self.assertEqual("ja_importado", result["status"])
        self.assertEqual(2, cursor.fetchone.call_count)

    def test_linked_pdf_rejects_different_seller_with_visible_conflict(self):
        conn = mock.MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchone.side_effect = [
            {"id": 17},
            {"id": 31, "status": "enviado_frete", "frete_id": 8, "vendedor_codigo": "15"},
        ]
        carga = {"assinatura": "abc", "mapa": "151501"}
        with mock.patch.object(server, "get_conn", return_value=conn):
            result = server._vendas_diario_importar_carga_pdf_arquivo(
                "/tmp/carga.pdf", vendedor_codigo="16", carga=carga
            )
        self.assertEqual("erro", result["status"])
        self.assertIn("vinculado a um frete", result["erro"])
        self.assertEqual("15", result["vendedor_codigo"])

    def test_manual_status_persists_each_sellout_source(self):
        with tempfile.TemporaryDirectory() as root:
            txt_dir = Path(root) / "txt"
            pdf_dir = Path(root) / "pdf"
            txt_dir.mkdir()
            pdf_dir.mkdir()
            sellout = {
                "status": "ja_importado",
                "fontes": [
                    {"nome": "IND3", "linhas": 201, "linhas_incluidas": 201},
                    {"nome": "INDB", "linhas": 929, "linhas_incluidas": 929},
                ],
            }
            sources = [
                os.path.join(root, "IND3", "SELLOUT_D.CSV"),
                os.path.join(root, "INDB", "SELLOUT_D.CSV"),
            ]
            for source in sources:
                Path(source).parent.mkdir()
                Path(source).write_text("csv", encoding="utf-8")
            with mock.patch.object(server, "fontes_diarias_configuradas", return_value=sources), \
                    mock.patch.object(server, "_vendas_sellout_diario_importar", return_value=sellout):
                result = server._vendas_diario_importar_pasta(incluir_sellout=True, origem="manual")
                persisted = server._vendas_diario_status_publico()
            self.assertEqual("manual", result["ultima_leitura"]["origem"])
            self.assertEqual("sem_alteracoes", persisted["fontes"]["sellout_d_ind3"]["status"])
            self.assertEqual(201, persisted["fontes"]["sellout_d_ind3"]["linhas"])
            self.assertEqual(929, persisted["fontes"]["sellout_d_indb"]["linhas"])
            self.assertFalse(persisted["em_andamento"])

    def test_status_em_andamento_vira_interrompido_sem_lock(self):
        server._vendas_diario_status_iniciar("manual", incluir_sellout=True)
        status = server._vendas_diario_status_publico()
        self.assertFalse(status["em_andamento"])
        self.assertEqual("interrompido", status["fontes"]["sellout_d_ind3"]["status"])


if __name__ == "__main__":
    unittest.main()
