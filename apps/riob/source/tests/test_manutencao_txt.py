import io
import json
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import manutencao_txt
import server


def _ods_bytes():
    content = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
 xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
 <office:body><office:spreadsheet><table:table table:name="MANUTENCOES">
  <table:table-row>
   <table:table-cell><text:p>LOCAL</text:p></table:table-cell>
   <table:table-cell><text:p>TIPO/AGRUPADO</text:p></table:table-cell>
   <table:table-cell><text:p>VEICULO</text:p></table:table-cell>
   <table:table-cell><text:p>DIA</text:p></table:table-cell>
   <table:table-cell><text:p>MES</text:p></table:table-cell>
   <table:table-cell><text:p>DESC</text:p></table:table-cell>
   <table:table-cell><text:p>VALOR</text:p></table:table-cell>
   <table:table-cell><text:p>ID</text:p></table:table-cell>
  </table:table-row>
  <table:table-row><table:table-cell><text:p>TORNEARIA</text:p></table:table-cell><table:table-cell><text:p>N1</text:p></table:table-cell><table:table-cell><text:p>21</text:p></table:table-cell><table:table-cell><text:p>17</text:p></table:table-cell><table:table-cell><text:p>7</text:p></table:table-cell><table:table-cell><text:p>SERVICO A</text:p></table:table-cell><table:table-cell><text:p>150</text:p></table:table-cell><table:table-cell><text:p>POLACO</text:p></table:table-cell></table:table-row>
  <table:table-row><table:table-cell><text:p>TORNEARIA</text:p></table:table-cell><table:table-cell><text:p>N1</text:p></table:table-cell><table:table-cell><text:p>21</text:p></table:table-cell><table:table-cell><text:p>17</text:p></table:table-cell><table:table-cell><text:p>7</text:p></table:table-cell><table:table-cell><text:p>SERVICO B</text:p></table:table-cell><table:table-cell><text:p>50</text:p></table:table-cell><table:table-cell/></table:table-row>
  <table:table-row><table:table-cell><text:p>PECAS</text:p></table:table-cell><table:table-cell/><table:table-cell><text:p>ACY1488</text:p></table:table-cell><table:table-cell/><table:table-cell/><table:table-cell><text:p>PECA SEM DATA</text:p></table:table-cell><table:table-cell><text:p>10,90</text:p></table:table-cell><table:table-cell/></table:table-row>
  <table:table-row table:number-rows-repeated="1048572"><table:table-cell table:number-columns-repeated="1024"/></table:table-row>
 </table:table></office:spreadsheet></office:body>
</office:document-content>"""
    meta = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta
 xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
 <office:meta><dc:date>2026-09-17T08:58:45</dc:date></office:meta>
</office:document-meta>"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("content.xml", content)
        archive.writestr("meta.xml", meta)
    return output.getvalue()


class _Cursor:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))

    def fetchall(self):
        return list(self.rows)

    def close(self):
        return None


class _Connection:
    def __init__(self, cursor):
        self.cursor_instance = cursor

    def cursor(self, dictionary=False):
        return self.cursor_instance

    def close(self):
        return None


class ManutencaoTxtTests(unittest.TestCase):
    def test_header_metadata_currency_and_grouping(self):
        raw = """FORNECEDOR: TIGRAO AUTO PECAS LTDA
DOCUMENTO | DATA | ITEM | VALOR | PLACA/FROTA
3611/1 | 19/08/2026 | ATUADOR DA EMBREAGEM | R$ 503,00 | AWG 7931
3611/1 | 19/08/2026 | SERVO DE EMBREAGEM | R$ 1.660,00 | AWG 7931
""".encode("utf-8")

        result = manutencao_txt.parse_maintenance_text(raw, "tigrao.txt")

        self.assertEqual("TIGRAO AUTO PECAS LTDA", result["fornecedor"])
        self.assertEqual(1, result["meta"]["documentos"])
        self.assertEqual(2, result["meta"]["itens"])
        document = result["documentos"][0]
        self.assertEqual("3611/1", document["numero_nota"])
        self.assertEqual("2026-08-19", document["data_documento"])
        self.assertEqual(2163.0, document["valor_total"])
        self.assertEqual("AWG 7931", document["referencia_veiculo"])

    def test_headerless_file_keeps_duplicates_and_warns_missing_vehicle(self):
        raw = """86549 | 19/08/2026 | TRAVA MB 1113/1313 | R$ 12,00
86549 | 19/08/2026 | TRAVA MB 1113/1313 | R$ 12,00
""".encode("cp1252")

        result = manutencao_txt.parse_maintenance_text(raw, "notas_matara.txt")

        self.assertIn("inferidas", result["warnings"][0])
        document = result["documentos"][0]
        self.assertEqual(2, len(document["itens"]))
        self.assertTrue(any("Veículo não informado" in item for item in document["warnings"]))
        self.assertTrue(any("linhas idênticas" in item for item in document["warnings"]))

    def test_uncertain_document_and_illegible_item_are_not_corrected(self):
        raw = """Nº ORÇAMENTO | DATA | ITEM | VALOR | PLACA
518? | 03/08/2026 | 01 [item manuscrito pouco legível] | R$ 70,00 | AIB6358
""".encode("utf-8")

        document = manutencao_txt.parse_maintenance_text(raw, "carrocerias.txt")["documentos"][0]

        self.assertEqual("518?", document["numero_nota"])
        self.assertTrue(any("incerto" in item for item in document["warnings"]))
        self.assertTrue(any("legível" in item for item in document["warnings"]))

    def test_future_semicolon_header_synonyms_are_supported(self):
        raw = "Nota;Emissão;Descrição;Total;Veículo\n77;01-09-2026;Correia;49,90;ABC-1D23\n"

        result = manutencao_txt.parse_maintenance_text(raw, "futuro.csv")

        self.assertEqual(1, result["meta"]["documentos"])
        self.assertEqual(49.9, result["documentos"][0]["valor_total"])

    def test_ods_pattern_groups_rows_and_preserves_missing_fields(self):
        result = manutencao_txt.parse_maintenance_file(_ods_bytes(), "MANUTENCOES.ods")

        self.assertEqual("ods", result["origem_tipo"])
        self.assertEqual({"documentos": 2, "itens": 3, "linhas_invalidas": 0}, result["meta"])
        grouped, ungrouped = result["documentos"]
        self.assertEqual("N1", grouped["numero_nota"])
        self.assertEqual("2026-07-17", grouped["data_documento"])
        self.assertEqual(200.0, grouped["valor_total"])
        self.assertIn("ID/responsável: POLACO", grouped["itens"][0]["observacao"])
        self.assertTrue(ungrouped["numero_nota"].startswith("S/N L"))
        self.assertEqual("", ungrouped["data_documento"])
        self.assertTrue(any("Data não informada" in item for item in ungrouped["warnings"]))
        self.assertTrue(any("foi usado 2026" in item for item in result["warnings"]))

    def test_preview_api_does_not_return_raw_source_text(self):
        cursor = _Cursor([{"id": 9, "nome": "19", "placa": "ABC-1D23", "modelo": "Truck"}])
        connection = _Connection(cursor)
        content = b"Documento | Data | Item | Valor | Placa\n1 | 01/09/2026 | Peca | R$ 10,00 | ABC-1D23\n"
        with mock.patch.object(server, "get_conn", return_value=connection), server.app.test_client() as client:
            response = client.post(
                "/api/manutencoes/importacoes-txt/preview",
                data={"arquivos": (io.BytesIO(content), "nota.txt")},
                content_type="multipart/form-data",
            )

        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertNotIn("texto_bruto", json.dumps(payload))
        document = payload["arquivos"][0]["documentos"][0]
        self.assertEqual(9, document["veiculo_id"])
        self.assertEqual("referencia_exata_txt", document["origem_veiculo"])

    def test_similar_vehicle_reference_is_left_for_manual_review(self):
        vehicle, confidence, source = server._manutencao_txt_veiculo_sugerido(
            "ACJ1489",
            [{"id": 22, "nome": "22", "placa": "ACY-1488"}],
        )
        self.assertIsNone(vehicle)
        self.assertEqual(0.0, confidence)
        self.assertEqual("", source)

    def test_exact_numeric_fleet_reference_is_suggested(self):
        vehicle, confidence, source = server._manutencao_txt_veiculo_sugerido(
            "21",
            [{"id": 36, "nome": "21", "placa": "AEX-0335"}],
        )
        self.assertEqual(36, vehicle["id"])
        self.assertEqual(1.0, confidence)
        self.assertEqual("referencia_exata_txt", source)

    def test_interface_exposes_preview_before_import(self):
        html = Path("RioBranco.html").read_text(encoding="utf-8")
        script = Path("script.js").read_text(encoding="utf-8")
        self.assertIn('id="manutTxtImportDialog"', html)
        self.assertIn(".ods", html)
        self.assertIn("/api/manutencoes/importacoes-txt/preview", script)
        self.assertIn("confirmarImportacaoManutencaoTxt", script)


if __name__ == "__main__":
    unittest.main()
