import importlib.util
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote
from unittest import mock

from apps.financeiro.pdf_report import (
    FinancePdfReportError,
    build_finance_titles_pdf,
    collect_title_pdf_attachments,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
MARKUP = (PROJECT_DIR / "apps" / "financeiro" / "source.html").read_text(encoding="utf-8")
APP_JS = (PROJECT_DIR / "apps" / "financeiro" / "static" / "app.js").read_text(encoding="utf-8")
HAS_FLASK = importlib.util.find_spec("flask") is not None
HAS_PDF_DEPS = all(importlib.util.find_spec(name) is not None for name in ("reportlab", "pypdf"))
portal = __import__("app") if HAS_FLASK else None


class FinanceiroPrintTests(unittest.TestCase):
    def test_dashboard_e_contas_possuem_acao_de_impressao(self):
        for element_id in (
            'id="btnImprimirDashboard"',
            'id="btnImprimirAP"',
            'id="btnImprimirAR"',
        ):
            self.assertIn(element_id, MARKUP)

        self.assertIn('$("#btnImprimirDashboard").addEventListener("click", printDashboardReport)', APP_JS)
        self.assertIn('event=>printTitlesReport("AP", event.currentTarget)', APP_JS)
        self.assertIn('event=>printTitlesReport("AR", event.currentTarget)', APP_JS)

    def test_relatorio_de_contas_envia_filtro_e_ids_ao_gerador_unificado(self):
        start = APP_JS.index("function titleReportFilters")
        end = APP_JS.index('$("#tabs")', start)
        source = APP_JS[start:end]

        self.assertIn("renderTabelaTitulos(tipo)", source)
        self.assertIn("const titles = filteredTitulos(tipo)", source)
        self.assertIn('financeSelectedText(`#${prefix}Conta`)', source)
        self.assertIn('financeSelectedText(`#${prefix}Status`)', source)
        self.assertIn('$(`#${prefix}Ini`)?.value', source)
        self.assertIn('$(`#${prefix}Fim`)?.value', source)
        self.assertIn('$(`#${prefix}Busca`)?.value?.trim()', source)
        self.assertIn('fetch("/apps/financeiro/api/titles-report-pdf"', source)
        self.assertIn("revision: financeStateRevision", source)
        self.assertIn("tituloIds: titles.map(title => title.id)", source)
        self.assertIn("const blob = await response.blob()", source)
        self.assertIn("previewWindow.location.replace(objectUrl)", source)

    def test_listagem_e_pdf_reutilizam_a_mesma_funcao_de_filtro(self):
        renderer_start = APP_JS.index("function filteredTitulos")
        renderer_end = APP_JS.index('$("#btnFiltrarAP")', renderer_start)
        source = APP_JS[renderer_start:renderer_end]

        self.assertIn("function renderTabelaTitulos", source)
        self.assertIn("const list = filteredTitulos(tipo)", source)
        self.assertIn('list.filter(t=>t.vencimento >= ini)', source)
        self.assertIn('list.filter(t=>t.vencimento <= fim)', source)

    def test_relatorio_do_dashboard_usa_conta_e_mes_selecionados(self):
        start = APP_JS.index("function printDashboardReport")
        end = APP_JS.index("function titleReportFilters", start)
        source = APP_JS[start:end]

        self.assertIn("renderDashboard()", source)
        self.assertIn('financeSelectedText("#dashConta")', source)
        self.assertIn('financeReportMonth($("#dashMes")?.value)', source)
        self.assertIn("dashboard.innerHTML", source)

    def test_dashboard_mantem_documento_de_impressao_independente_do_portal(self):
        start = APP_JS.index("function openFinancePrintReport")
        end = APP_JS.index("function printDashboardReport", start)
        source = APP_JS[start:end]

        self.assertIn('window.open("", "_blank")', source)
        self.assertIn("@page { size: A4 landscape", source)
        self.assertIn('printWindow.print()', source)
        self.assertIn("NanotechSoft · Financeiro", source)

    @unittest.skipUnless(shutil.which("google-chrome"), "google-chrome não instalado")
    def test_javascript_dos_relatorios_e_valido_no_navegador(self):
        start = APP_JS.index("function financeReportDate")
        end = APP_JS.index('$("#tabs")', start)
        report_source = APP_JS[start:end]
        page = f"<body><script>{report_source}\ndocument.body.textContent='ok';</script></body>"
        result = subprocess.run(
            [
                shutil.which("google-chrome"), "--headless", "--no-sandbox",
                "--disable-gpu", "--disable-dev-shm-usage", "--dump-dom",
                "data:text/html;charset=utf-8," + quote(page),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertIn("<body>ok</body>", result.stdout)


class FinanceiroPdfMergeTests(unittest.TestCase):
    def test_coleta_pdf_do_titulo_e_lancamento_sem_duplicar_arquivo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            attachments_dir = Path(temp_dir)
            (attachments_dir / "titulo.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
            (attachments_dir / "lancamento.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
            state = {
                "lancamentos": [{
                    "id": "lanc-1",
                    "anexos": [{"path": "lancamento.pdf", "mime": "application/pdf"}],
                }]
            }
            titles = [{
                "id": "titulo-1",
                "lancId": "lanc-1",
                "anexos": [
                    {"path": "titulo.pdf", "mime": "application/pdf"},
                    {"path": "titulo.pdf", "mime": "application/pdf"},
                    {"path": "foto.png", "mime": "image/png"},
                ],
            }]

            attachments = collect_title_pdf_attachments(state, titles, attachments_dir)

            self.assertEqual(["titulo.pdf", "lancamento.pdf"], [path.name for path, _ in attachments])

    def test_pdf_referenciado_mas_ausente_interrompe_relatorio(self):
        title = {
            "id": "titulo-1",
            "anexos": [{"name": "boleto.pdf", "path": "ausente.pdf", "mime": "application/pdf"}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(FinancePdfReportError, "não foi encontrado"):
                collect_title_pdf_attachments({"lancamentos": []}, [title], temp_dir)

    @unittest.skipUnless(HAS_PDF_DEPS, "reportlab/pypdf não instalados")
    def test_arquivo_final_contem_relatorio_e_todos_os_pdfs(self):
        from pypdf import PdfReader
        from reportlab.pdfgen import canvas

        with tempfile.TemporaryDirectory() as temp_dir:
            attachments_dir = Path(temp_dir)
            for filename, label in (("titulo.pdf", "Título"), ("lancamento.pdf", "Lançamento")):
                pdf = canvas.Canvas(str(attachments_dir / filename))
                pdf.drawString(72, 720, label)
                pdf.showPage()
                pdf.save()

            title = {
                "id": "titulo-1", "tipo": "AP", "vencimento": "2026-08-20",
                "contaId": "conta-1", "categoriaIds": ["cat-1"],
                "pessoa": "Fornecedor", "desc": "Energia", "valor": 150.5,
                "status": "ABERTO", "lancId": "lanc-1",
                "anexos": [{"name": "Título", "path": "titulo.pdf", "mime": "application/pdf"}],
            }
            state = {
                "contas": [{"id": "conta-1", "nome": "Caixa"}],
                "categorias": [{"id": "cat-1", "nome": "Energia"}],
                "lancamentos": [{
                    "id": "lanc-1",
                    "anexos": [{"name": "Lançamento", "path": "lancamento.pdf", "mime": "application/pdf"}],
                }],
            }

            output, attachment_count = build_finance_titles_pdf(
                state, [title], "AP", [("Conta", "Caixa")], attachments_dir
            )
            result = PdfReader(output)

            self.assertEqual(2, attachment_count)
            self.assertEqual(3, len(result.pages))

    @unittest.skipUnless(HAS_FLASK, "Flask não instalado")
    def test_api_preserva_ordem_filtrada_e_retorna_pdf_inline(self):
        client = portal.app.test_client()
        with client.session_transaction() as session:
            session["usuario_id"] = 1
        user = {"id": 1, "perfil": "admin", "ativo": 1}
        state = {
            **portal.default_finance_state(),
            "titulos": [
                {"id": "primeiro", "tipo": "AP"},
                {"id": "segundo", "tipo": "AP"},
            ],
        }
        generated = io.BytesIO(b"%PDF-1.4\n%%EOF\n")

        with (
            mock.patch.object(portal, "ensure_database"),
            mock.patch.object(portal, "current_user_or_logout", return_value=user),
            mock.patch.object(portal, "app_visible_to_user", return_value=True),
            mock.patch.object(portal, "get_finance_state", return_value=state),
            mock.patch.object(
                portal, "build_finance_titles_pdf", return_value=(generated, 2)
            ) as builder,
        ):
            response = client.post(
                "/apps/financeiro/api/titles-report-pdf",
                json={
                    "tipo": "AP",
                    "revision": portal.finance_state_revision(state),
                    "tituloIds": ["segundo", "primeiro"],
                    "filtros": [{"label": "Status", "value": "Em aberto"}],
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("application/pdf", response.mimetype)
        self.assertIn("inline", response.headers["Content-Disposition"])
        self.assertEqual("2", response.headers["X-Finance-Pdf-Attachments"])
        selected = builder.call_args.args[1]
        self.assertEqual(["segundo", "primeiro"], [item["id"] for item in selected])

    @unittest.skipUnless(HAS_FLASK, "Flask não instalado")
    def test_api_nao_expoe_contas_a_pagar_sem_permissao(self):
        client = portal.app.test_client()
        with client.session_transaction() as session:
            session["usuario_id"] = 7
        user = {"id": 7, "perfil": "usuario", "ativo": 1}

        with (
            mock.patch.object(portal, "ensure_database"),
            mock.patch.object(portal, "current_user_or_logout", return_value=user),
            mock.patch.object(portal, "app_visible_to_user", return_value=True),
            mock.patch.object(portal, "allowed_resources_for_app", return_value=["receber"]),
            mock.patch.object(portal, "build_finance_titles_pdf") as builder,
        ):
            response = client.post(
                "/apps/financeiro/api/titles-report-pdf",
                json={"tipo": "AP", "tituloIds": []},
            )

        self.assertEqual(403, response.status_code)
        builder.assert_not_called()


if __name__ == "__main__":
    unittest.main()
