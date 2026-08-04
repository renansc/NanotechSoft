import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import server


class VendasDiarioPastasTest(unittest.TestCase):
    def test_infers_seller_from_map_prefix(self):
        self.assertEqual("6", server._vendas_diario_vendedor_por_carga({"mapa": "060401"}))
        self.assertEqual("15", server._vendas_diario_vendedor_por_carga({"mapa": "153101"}))

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
                    mock.patch.object(server, "_vendas_diario_importar_arquivo", return_value={"status": "importado"}) as txt_import, \
                    mock.patch.object(server, "parse_cargas_pdf", return_value=[{"pagina": 1, "mapa": "060401"}]), \
                    mock.patch.object(server, "_vendas_diario_importar_carga_pdf_arquivo", return_value={"status": "importado"}) as pdf_import:
                result = server._vendas_diario_importar_pasta()

            self.assertFalse(result["processando"])
            self.assertEqual(2, result["arquivos"])
            self.assertEqual(1, result["txt"]["arquivos"])
            self.assertEqual(1, result["pdf"]["arquivos"])
            self.assertEqual(["txt", "pdf"], [item["tipo"] for item in result["resultados"]])
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
                    mock.patch.object(server, "_vendas_diario_importar_carga_pdf_arquivo", return_value={"status": "importado"}):
                result = server._vendas_diario_importar_pasta()

            self.assertEqual("erro", result["resultados"][0]["status"])
            self.assertEqual("importado", result["resultados"][1]["status"])


if __name__ == "__main__":
    unittest.main()
