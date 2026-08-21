import importlib.util
import unittest
from unittest import mock

from apps.financeiro.pix import (
    PixPayloadError,
    build_static_pix_payload,
    normalize_pix_key,
    pix_crc16,
)


HAS_FLASK = importlib.util.find_spec("flask") is not None
portal = __import__("app") if HAS_FLASK else None


class FinanceiroPixTests(unittest.TestCase):
    def test_crc16_confere_com_exemplo_oficial(self):
        prefix = (
            "00020126580014br.gov.bcb.pix0136123e4567-e12b-12d1-a456-"
            "4266554400005204000053039865802BR5913Fulano de Tal6008BRASILIA"
            "62070503***6304"
        )
        self.assertEqual("1D3D", pix_crc16(prefix))

    def test_telefone_brasileiro_e_normalizado_para_formato_internacional(self):
        self.assertEqual("+5544999999999", normalize_pix_key("(44) 99999-9999", "TELEFONE"))
        self.assertEqual("+5544999999999", normalize_pix_key("+55 44 99999-9999", "TELEFONE"))

    def test_payload_estatico_contem_chave_valor_e_crc(self):
        result = build_static_pix_payload(
            key="(44) 99999-9999",
            key_type="TELEFONE",
            amount=99.9,
            merchant_name="Fornecedor Árvore",
            merchant_city="Astorga",
        )

        payload = result["payload"]
        self.assertIn("+5544999999999", payload)
        self.assertIn("540599.90", payload)
        self.assertIn("ASTORGA", payload)
        self.assertEqual(pix_crc16(payload[:-4]), payload[-4:])

    def test_chave_numerica_sem_tipo_e_rejeitada(self):
        with self.assertRaises(PixPayloadError):
            normalize_pix_key("44999999999", "AUTO")

    def test_cpf_cnpj_rejeita_letras(self):
        with self.assertRaises(PixPayloadError):
            normalize_pix_key("abcdefghijk", "CPF_CNPJ")

    def test_chave_aleatoria_exige_uuid(self):
        with self.assertRaises(PixPayloadError):
            normalize_pix_key("qualquer-chave", "ALEATORIA")
        self.assertEqual(
            "123e4567-e89b-12d3-a456-426614174000",
            normalize_pix_key("123E4567-E89B-12D3-A456-426614174000", "ALEATORIA"),
        )

    @unittest.skipUnless(HAS_FLASK, "Flask nao instalado")
    def test_api_gera_qr_code_pix(self):
        user = {"id": 1, "perfil": "admin", "ativo": 1}
        client = portal.app.test_client()
        with client.session_transaction() as session:
            session["usuario_id"] = 1

        with (
            mock.patch.object(portal, "current_user_or_logout", return_value=user),
            mock.patch.object(portal, "app_visible_to_user", return_value=True),
        ):
            response = client.post("/api/finance/pix-code", json={
                "key": "(44) 99999-9999",
                "keyType": "TELEFONE",
                "amount": 99.9,
                "merchantName": "Fornecedor",
                "merchantCity": "Astorga",
            })

        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertTrue(payload["image"].startswith("data:image/png;base64,"))
        self.assertIn("+5544999999999", payload["payload"])

    def test_tela_exibe_acao_ver_pix_qr(self):
        from pathlib import Path

        project = Path(__file__).resolve().parents[1]
        source = (project / "apps/financeiro/static/app.js").read_text(encoding="utf-8")
        markup = (project / "apps/financeiro/source.html").read_text(encoding="utf-8")
        self.assertIn('id="tPixKey"', markup)
        self.assertIn('id="tPixKeyType"', markup)
        self.assertIn("Ver PIX QR", source)
        self.assertIn("/api/finance/pix-code", source)
        self.assertIn("requestPixCode", source)


if __name__ == "__main__":
    unittest.main()
