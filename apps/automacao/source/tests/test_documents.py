import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from pypdf import PdfWriter
import database
from app import app


class DocumentUploadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        patch = mock.patch.object(database, "DB_NAME", Path(temporary.name) / "docs.db")
        patch.start()
        self.addCleanup(patch.stop)
        database.init_database()
        self.client = app.test_client()
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        out = io.BytesIO()
        writer.write(out)
        self.pdf = out.getvalue()

    def upload(self, **overrides):
        data = dict(titulo="Protocolo da maquina", equipamento="Cyklop",
                    tipo="protocolo", descricao="Documento fornecido pela operacao",
                    arquivo=(io.BytesIO(self.pdf), "protocolo.pdf"))
        data.update(overrides)
        return self.client.post("/documentacao/cadastrar", data=data)

    def test_upload_joins_existing_catalog_and_survives_startup(self):
        response = self.upload()
        self.assertEqual(303, response.status_code)
        self.assertEqual("/documentacao?cadastrado=1", response.location)
        database.init_database()
        listing = self.client.get(response.location).get_data(as_text=True)
        for text in ("Documento cadastrado", "Protocolo da maquina", "Rodighero",
                     "Zegla Unimix", "Envasadora Zegla", "Impressora a laser Cyklop",
                     '/documentacao/arquivos/1'):
            self.assertIn(text, listing)
        pdf = self.client.get("/documentacao/arquivos/1")
        self.assertEqual(200, pdf.status_code)
        self.assertEqual("application/pdf", pdf.mimetype)
        self.assertEqual(self.pdf, pdf.data)
        self.assertEqual("private, no-store", pdf.headers["Cache-Control"])
        self.assertEqual("nosniff", pdf.headers["X-Content-Type-Options"])
        pdf.close()

    def test_invalid_inputs_do_not_save_documents(self):
        for data in ({"titulo": ""}, {"titulo": "x" * 161}, {"equipamento": "x" * 161},
                     {"descricao": "x" * 2001}, {"tipo": "exe"}, {"arquivo": None},
                     {"arquivo": (io.BytesIO(b"hello"), "arquivo.pdf")},
                     {"arquivo": (io.BytesIO(b"%PDF-1.7\ninvalid"), "arquivo.pdf")},
                     {"arquivo": (io.BytesIO(self.pdf), "arquivo.html")}):
            with self.subTest(data=list(data)):
                response = self.upload(**data)
                self.assertEqual(400, response.status_code)
                self.assertIn(b'role="alert"', response.data)
        conn = database.get_connection()
        self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM documentos_maquinas").fetchone()[0])
        conn.close()

    def test_encrypted_pdf_rejected(self):
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.encrypt("senha")
        encrypted = io.BytesIO()
        writer.write(encrypted)
        encrypted.seek(0)
        self.assertEqual(400, self.upload(arquivo=(encrypted, "protegido.pdf")).status_code)

    def test_file_limit_and_request_limit(self):
        with mock.patch("app.MAX_DOCUMENT_BYTES", len(self.pdf) - 1):
            self.assertEqual(413, self.upload().status_code)
        with mock.patch.dict(app.config, {"MAX_CONTENT_LENGTH": 100}):
            response = self.upload()
        self.assertEqual(413, response.status_code)
        self.assertIn(b"20 MB", response.data)

    def test_metadata_is_escaped_and_missing_file_is_404(self):
        self.assertEqual(303, self.upload(titulo='<script>alert(1)</script>',
            arquivo=(io.BytesIO(self.pdf), '../../manual.pdf')).status_code)
        listing = self.client.get('/documentacao').get_data(as_text=True)
        self.assertNotIn('<script>alert(1)</script>', listing)
        self.assertIn('&lt;script&gt;', listing)
        self.assertEqual(404, self.client.get('/documentacao/arquivos/9999').status_code)


if __name__ == '__main__':
    unittest.main()
