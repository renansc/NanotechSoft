import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apps.financeiro.pdf_import import (
    FinancePdfImportError,
    parse_caixa_statement_text,
    parse_inter_statement_text,
    parse_installment_pages,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
HAS_FLASK = importlib.util.find_spec("flask") is not None
portal = __import__("app") if HAS_FLASK else None


CAIXA_OCR_SAMPLE = """
CAIXA
Extrato por período
Cliente RENAN SANTOS COUTINHO
Conta 1318 / 3701.000593104889-4
Período dos lançamentos 01/07/2026 até 31/07/2026
27/07/2026 - 00:00:00 000000 SALDO DIA 0,00 C 877,29 D
25/07/2026 - 14:33:22 251433 CREDITO TRANSF INTERNET R C R de Jesus E C **818.646/0*** 350,00 C 877,29 D
24/07/2026 - 18:03:23 241803 COMPRA CARTAO DEBITO Jc Combustiveis Lt 206,49 D 1.227,29 D
22/07/2026 - 09:22:29 220922 PAGAMENTO DE BOLETO Cartoes Caixa Elo **360.305/0*** 1.164,93 D 1.770,80 D
Alô CAIXA: 4004 0104
"""

INTER_SAMPLE = """
R S COUTINHO INFORMATICA
CPF/CNPJ: 46.025.190/0001-00, Instituição: Banco Inter, Agência: 0001-9, Conta: 51867017-1
Período: 01/07/2026 a 13/08/2026

Saldo total                Saldo disponível:     Saldo bloqueado:
R$ 1.488,61                R$ 1.488,61           R$ 0,00

 7 de Julho de 2026 Saldo do dia: R$ 2.800,64                       Valor          Saldo por transação
 Compra no debito: "No estabelecimento SUPERMERCADO ALIANCA ASTORGA BRA"     -R$ 199,73   -R$ 199,36
 Pix recebido: "Cp :79342069-BEBIDAS WHITE RIVER LTDA"                       R$ 3.000,00   R$ 2.800,64

 13 de Julho de 2026 Saldo do dia: R$ 2.450,64
 Pix enviado: "Cp :90400888-Claudio Amaro"                                    -R$ 350,00   R$ 2.450,64

 12 de Agosto de 2026 Saldo do dia: R$ 1.488,61
 Pix enviado: "Cp :90400888-Claudio Amaro"                                    -R$ 350,00   R$ 1.488,61
"""

DARF_SAMPLE = """
Documento de Arrecadação de Receitas Federais
CNPJ                              Razão Social
46.025.190/0001-00                NANOTECH LTDA
Período de Apuração               Data de Vencimento              Número do Documento
janeiro/2026                      20/02/2026                       07.16.26225.8911046-2
Pagar este documento até
13/08/2026
Valor Total do Documento
225,93
Documento de Arrecadação de Receitas Federais                         Pague com o PIX
Pagar até: 13/08/2026
Valor: 225,93
85870000002 2 25930385262 6 25071626225 7 89110462919 8
"""


class FinanceiroPdfImportTests(unittest.TestCase):
    def setUp(self):
        if not HAS_FLASK:
            return
        ensure_database = mock.patch.object(portal, "ensure_database")
        ensure_database.start()
        self.addCleanup(ensure_database.stop)

    def test_parser_caixa_ignora_saldo_dia_e_preserva_credito_debito(self):
        result = parse_caixa_statement_text(CAIXA_OCR_SAMPLE)

        self.assertEqual("CAIXA", result["bank"])
        self.assertEqual("1318 / 3701.000593104889-4", result["account"])
        self.assertEqual("2026-07-01", result["periodStart"])
        self.assertEqual("2026-07-31", result["periodEnd"])
        self.assertEqual("2026-07-27", result["balanceDate"])
        self.assertEqual(-877.29, result["closingBalance"])
        self.assertEqual([350.0, -206.49, -1164.93], [tx["amount"] for tx in result["txs"]])
        self.assertTrue(all(tx["fitid"].startswith("pdf-caixa-") for tx in result["txs"]))
        self.assertFalse(any("SALDO DIA" in tx["memo"] for tx in result["txs"]))

    def test_fitid_caixa_e_deterministico(self):
        first = parse_caixa_statement_text(CAIXA_OCR_SAMPLE)
        second = parse_caixa_statement_text(CAIXA_OCR_SAMPLE)

        self.assertEqual(
            [tx["fitid"] for tx in first["txs"]],
            [tx["fitid"] for tx in second["txs"]],
        )

    def test_parser_inter_preserva_valor_saldo_e_periodo(self):
        result = parse_inter_statement_text(INTER_SAMPLE)

        self.assertEqual("BANCO INTER", result["bank"])
        self.assertEqual("51867017-1", result["account"])
        self.assertEqual("2026-07-01", result["periodStart"])
        self.assertEqual("2026-08-13", result["periodEnd"])
        self.assertEqual("2026-08-12", result["balanceDate"])
        self.assertEqual(1488.61, result["closingBalance"])
        self.assertEqual([-199.73, 3000.0, -350.0, -350.0], [tx["amount"] for tx in result["txs"]])
        self.assertEqual(-199.36, result["txs"][0]["transactionBalance"])
        self.assertTrue(all(tx["fitid"].startswith("pdf-inter-") for tx in result["txs"]))

    def test_fitid_inter_e_deterministico(self):
        first = parse_inter_statement_text(INTER_SAMPLE)
        second = parse_inter_statement_text(INTER_SAMPLE)

        self.assertEqual(
            [tx["fitid"] for tx in first["txs"]],
            [tx["fitid"] for tx in second["txs"]],
        )

    def test_pdf_de_banco_desconhecido_e_rejeitado(self):
        with self.assertRaises(FinancePdfImportError):
            parse_caixa_statement_text("Extrato sem identificação bancária")

    @unittest.skipUnless(HAS_FLASK, "Flask nao instalado")
    def test_rota_pdf_exige_arquivo_pdf(self):
        user = {"id": 1, "perfil": "admin", "ativo": 1}
        client = portal.app.test_client()
        with client.session_transaction() as session:
            session["usuario_id"] = 1

        with (
            mock.patch.object(portal, "current_user_or_logout", return_value=user),
            mock.patch.object(portal, "app_visible_to_user", return_value=True),
        ):
            response = client.post(
                "/apps/financeiro/api/import-pdf",
                data={"file": (Path(__file__).open("rb"), "extrato.txt")},
                content_type="multipart/form-data",
            )

        self.assertEqual(400, response.status_code)
        self.assertIn("PDF", response.get_json()["error"])

    def test_frontend_aceita_pdf_e_remove_duplicidades(self):
        source = (PROJECT_DIR / "apps/financeiro/static/app.js").read_text(encoding="utf-8")
        markup = (PROJECT_DIR / "apps/financeiro/source.html").read_text(encoding="utf-8")

        self.assertIn('/apps/financeiro/api/import-pdf', source)
        self.assertIn("importedBankFitids", source)
        self.assertIn("O mesmo movimento pode vir com FITIDs diferentes em OFX e PDF", source)
        self.assertNotIn("statementOpeningBalance", source)
        self.assertNotIn("Object.assign(conta, balanceReference)", source)
        self.assertIn("salvo somente para conferência", source)
        self.assertIn("statementCompletionTarget", source)
        self.assertIn("completeStatementImport", source)
        self.assertIn("Extrato completado", source)
        self.assertIn('data-act="completeImport"', source)
        self.assertIn("application/pdf", markup)

    def test_pdf_parcelado_reconhece_dados_por_pagina(self):
        pages = parse_installment_pages([
            "Vencimento 15/09/2026 Valor do Documento R$ 1.234,56\n"
            "00190.00009 01234.567890 12345.678901 1 12340000123456",
            "Data de vencimento: 15/10/2026\nValor da parcela 500,00",
        ])

        self.assertEqual(2, len(pages))
        self.assertEqual("2026-09-15", pages[0]["dueDate"])
        self.assertEqual(1234.56, pages[0]["amount"])
        self.assertTrue(pages[0]["barcode"])
        self.assertEqual(1, pages[0]["page"])
        self.assertEqual(2, pages[0]["pageCount"])
        self.assertEqual("2026-10-15", pages[1]["dueDate"])
        self.assertEqual(500.0, pages[1]["amount"])

    def test_pdf_darf_usa_valor_total_e_data_limite_para_pagamento(self):
        pages = parse_installment_pages([DARF_SAMPLE])

        self.assertEqual(1, len(pages))
        self.assertEqual("2026-08-13", pages[0]["dueDate"])
        self.assertEqual(225.93, pages[0]["amount"])
        self.assertEqual([], pages[0]["issues"])

    def test_pdf_com_tres_boletos_na_pagina_gera_tres_parcelas(self):
        page = """
033-7 03399.28509 78800.000578 38308.101013 1 15390000009990
Parcela Vencimento Local de Pagamento
001 / 036 15/08/2026 Banco
( = ) Valor do Documento
99,90
033-7 03399.28509 78800.000578 38309.001014 1 15700000009990
Parcela Vencimento Local de Pagamento
002 / 036 15/09/2026 Banco
( = ) Valor do Documento
99,90
033-7 03399.28509 78800.000578 38310.301015 5 16000000009990
Parcela Vencimento Local de Pagamento
003 / 036 15/10/2026 Banco
( = ) Valor do Documento
99,90
"""
        parcelas = parse_installment_pages([page])

        self.assertEqual(3, len(parcelas))
        self.assertEqual([1, 2, 3], [item["installmentNumber"] for item in parcelas])
        self.assertEqual(["2026-08-15", "2026-09-15", "2026-10-15"], [item["dueDate"] for item in parcelas])
        self.assertTrue(all(len(item["barcode"]) == 47 for item in parcelas))
        self.assertEqual([1, 2, 3], [item["region"] for item in parcelas])

    def test_frontend_importa_pdf_parcelado_e_abre_pagina_correta(self):
        source = (PROJECT_DIR / "apps/financeiro/static/app.js").read_text(encoding="utf-8")
        markup = (PROJECT_DIR / "apps/financeiro/source.html").read_text(encoding="utf-8")

        self.assertIn('id="btnImportarParcelasPdf"', markup)
        self.assertIn('/apps/financeiro/api/import-installments-pdf', source)
        self.assertIn('page: item.page', source)
        self.assertIn('#page=${Number(anexo.page)}', source)
        self.assertIn('barcode: item.barcode', source)
        self.assertIn('Cada uma abre diretamente na página correspondente', source)
        self.assertIn('data-preview-index', source)
        self.assertIn('regionsOnPage: item.regionsOnPage', source)
        self.assertIn('id="modalCodigoPagamento"', markup)
        self.assertIn('payment-code-image', source)
        self.assertIn('payment-code-info', source)
        self.assertIn('Ver código', source)

    @unittest.skipUnless(HAS_FLASK, "Flask nao instalado")
    def test_api_salva_visualiza_e_remove_anexo_pdf(self):
        user = {"id": 1, "perfil": "admin", "ativo": 1}
        client = portal.app.test_client()
        with client.session_transaction() as session:
            session["usuario_id"] = 1

        with tempfile.TemporaryDirectory(prefix="financeiro-anexo-test-") as temp_dir:
            with (
                mock.patch.object(portal, "current_user_or_logout", return_value=user),
                mock.patch.object(portal, "app_visible_to_user", return_value=True),
                mock.patch.object(portal, "FINANCEIRO_ATTACHMENTS_DIR", Path(temp_dir)),
            ):
                upload = client.post(
                    "/api/finance/attachments",
                    data={
                        "attachmentId": "anx_teste",
                        "file": (io.BytesIO(b"%PDF-1.4\n%%EOF\n"), "comprovante.pdf"),
                    },
                    content_type="multipart/form-data",
                )
                self.assertEqual(200, upload.status_code, upload.get_data(as_text=True))
                attachment = upload.get_json()["attachment"]
                self.assertEqual("application/pdf", attachment["mime"])

                view = client.get(attachment["url"])
                self.assertEqual(200, view.status_code)
                self.assertTrue(view.data.startswith(b"%PDF-"))
                view.close()

                delete = client.delete(f'/api/finance/attachments?path={attachment["path"]}')
                self.assertEqual(204, delete.status_code)
                self.assertFalse((Path(temp_dir) / attachment["path"]).exists())


if __name__ == "__main__":
    unittest.main()
