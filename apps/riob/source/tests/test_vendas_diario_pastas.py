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
            "txt": {"arquivos": 1},
            "pdf": {"arquivos": 2},
            "resultados": [
                {"status": "importado"},
                {"status": "ja_importado"},
                {"status": "ja_importado"},
            ],
        }

        self.assertEqual(
            {"arquivos": 3, "txt": 1, "pdf": 2, "status": {"importado": 1, "ja_importado": 2}},
            server._vendas_diario_scheduler_result_summary(result),
        )

    def test_scheduler_snapshot_changes_only_when_source_file_changes(self):
        with tempfile.TemporaryDirectory() as root:
            txt_dir = Path(root) / "txt"
            pdf_dir = Path(root) / "pdf"
            txt_dir.mkdir()
            pdf_dir.mkdir()
            txt_path = txt_dir / "vendas.txt"
            txt_path.write_text("primeira versao", encoding="utf-8")
            with mock.patch.object(server, "VENDAS_DIARIO_TXT_DIR", os.fspath(txt_dir)), \
                    mock.patch.object(server, "VENDAS_DIARIO_PDF_DIR", os.fspath(pdf_dir)):
                first = server._vendas_diario_source_snapshot()
                self.assertEqual(first, server._vendas_diario_source_snapshot())
                txt_path.write_text("segunda versao maior", encoding="utf-8")
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

    def test_automatic_import_reads_txt_and_pdf_directories(self):
        with tempfile.TemporaryDirectory() as root:
            txt_dir = Path(root) / "CargasTxt"
            pdf_dir = Path(root) / "VendasDiarioPdfs"
            txt_dir.mkdir()
            pdf_dir.mkdir()
            txt_path = txt_dir / "vendas.txt"
            pdf_path = pdf_dir / "carga.pdf"
            txt_path.write_text("relatorio", encoding="utf-8")
            pdf_path.write_bytes(b"%PDF-test")

            with mock.patch.object(server, "VENDAS_DIARIO_TXT_DIR", os.fspath(txt_dir)), \
                    mock.patch.object(server, "VENDAS_DIARIO_PDF_DIR", os.fspath(pdf_dir)), \
                    mock.patch.object(server, "_vendas_diario_importar_arquivo", return_value={"status": "importado", "data_ref": "2026-08-04"}) as txt_import, \
                    mock.patch.object(server, "parse_cargas_pdf", return_value=[{"pagina": 1, "mapa": "060401"}]), \
                    mock.patch.object(server, "_vendas_diario_importar_carga_pdf_arquivo", return_value={"status": "importado"}) as pdf_import, \
                    mock.patch.object(server, "_vendas_diario_unificar_cards_semelhantes", return_value={"grupos": 1, "cards_unificados": 1}):
                result = server._vendas_diario_importar_pasta()

            self.assertFalse(result["processando"])
            self.assertEqual(2, result["arquivos"])
            self.assertEqual(1, result["txt"]["arquivos"])
            self.assertEqual(1, result["pdf"]["arquivos"])
            self.assertEqual("2026-08-04", result["data_ref"])
            self.assertEqual(["txt", "pdf"], [item["tipo"] for item in result["resultados"]])
            self.assertEqual("sucesso", result["ultima_leitura"]["fontes"]["txt"]["status"])
            self.assertEqual("sucesso", result["ultima_leitura"]["fontes"]["pdf"]["status"])
            self.assertEqual("automatico_pastas", result["ultima_leitura"]["origem"])
            txt_import.assert_called_once_with(os.fspath(txt_path))
            pdf_import.assert_called_once_with(
                os.fspath(pdf_path), usuario="importacao_automatica", carga={"pagina": 1, "mapa": "060401"}
            )

    def test_error_in_one_directory_does_not_block_the_other(self):
        with tempfile.TemporaryDirectory() as root:
            txt_dir = Path(root) / "CargasTxt"
            pdf_dir = Path(root) / "VendasDiarioPdfs"
            txt_dir.mkdir()
            pdf_dir.mkdir()
            (txt_dir / "vendas.txt").write_text("relatorio", encoding="utf-8")
            (pdf_dir / "carga.pdf").write_bytes(b"%PDF-test")

            with mock.patch.object(server, "VENDAS_DIARIO_TXT_DIR", os.fspath(txt_dir)), \
                    mock.patch.object(server, "VENDAS_DIARIO_PDF_DIR", os.fspath(pdf_dir)), \
                    mock.patch.object(server, "_vendas_diario_importar_arquivo", side_effect=ValueError("TXT invalido")), \
                    mock.patch.object(server, "parse_cargas_pdf", return_value=[{"pagina": 1, "mapa": "060401"}]), \
                    mock.patch.object(server, "_vendas_diario_importar_carga_pdf_arquivo", return_value={"status": "importado"}), \
                    mock.patch.object(server, "_vendas_diario_unificar_cards_semelhantes", return_value={"grupos": 1, "cards_unificados": 1}):
                result = server._vendas_diario_importar_pasta()

            self.assertEqual("erro", result["resultados"][0]["status"])
            self.assertEqual("importado", result["resultados"][1]["status"])
            self.assertEqual("erro", result["ultima_leitura"]["fontes"]["txt"]["status"])
            self.assertEqual("sucesso", result["ultima_leitura"]["fontes"]["pdf"]["status"])

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
                os.path.join(root, "IND3", "SELLOUT_M.CSV"),
                os.path.join(root, "INDB", "SELLOUT_M.CSV"),
            ]
            for source in sources:
                Path(source).parent.mkdir()
                Path(source).write_text("csv", encoding="utf-8")
            with mock.patch.object(server, "VENDAS_DIARIO_TXT_DIR", os.fspath(txt_dir)), \
                    mock.patch.object(server, "VENDAS_DIARIO_PDF_DIR", os.fspath(pdf_dir)), \
                    mock.patch.object(server, "fontes_mensais_configuradas", return_value=sources), \
                    mock.patch.object(server, "_vendas_sellout_mensal_importar", return_value=sellout), \
                    mock.patch.object(server, "_vendas_diario_unificar_cards_semelhantes", return_value={}):
                result = server._vendas_diario_importar_pasta(incluir_sellout=True, origem="manual")
                persisted = server._vendas_diario_status_publico()
            self.assertEqual("manual", result["ultima_leitura"]["origem"])
            self.assertEqual("sem_arquivos", persisted["fontes"]["txt"]["status"])
            self.assertEqual("sem_arquivos", persisted["fontes"]["pdf"]["status"])
            self.assertEqual("sem_alteracoes", persisted["fontes"]["sellout_ind3"]["status"])
            self.assertEqual(201, persisted["fontes"]["sellout_ind3"]["linhas"])
            self.assertEqual(929, persisted["fontes"]["sellout_indb"]["linhas"])
            self.assertFalse(persisted["em_andamento"])

    def test_status_em_andamento_vira_interrompido_sem_lock(self):
        server._vendas_diario_status_iniciar("manual", incluir_sellout=True)
        status = server._vendas_diario_status_publico()
        self.assertFalse(status["em_andamento"])
        self.assertEqual("interrompido", status["fontes"]["txt"]["status"])
        self.assertEqual("interrompido", status["fontes"]["sellout_ind3"]["status"])


if __name__ == "__main__":
    unittest.main()
