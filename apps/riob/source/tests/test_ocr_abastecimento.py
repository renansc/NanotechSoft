import io
import unittest
from unittest import mock

import server


class _FakeImage:
    def load(self):
        return None


class _FakeImageModule:
    @staticmethod
    def open(_stream):
        return _FakeImage()


class _FakeCursor:
    def __init__(self, fetch_rows=None):
        self.fetch_rows = list(fetch_rows or [])
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.fetch_rows.pop(0) if self.fetch_rows else None

    def close(self):
        return None


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self, dictionary=False):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        return None


class OcrAbastecimentoTests(unittest.TestCase):
    def test_normalizar_combustivel_mantem_compatibilidade_com_diesel_legado(self):
        self.assertEqual(server._normalizar_combustivel_tipo("diesel"), "diesel_s10")
        self.assertEqual(server._normalizar_combustivel_tipo("S-500"), "diesel_500")
        self.assertEqual(server._normalizar_combustivel_tipo("Arla 32"), "arla")
        self.assertEqual(server._normalizar_combustivel_tipo("Gasolina C Comum"), "gasolina")
        self.assertEqual(server._normalizar_combustivel_tipo("Etanol Hidratado"), "etanol")
        self.assertEqual(server._combustivel_tipo_label("diesel_s10"), "Diesel S10")
        self.assertEqual(server._combustivel_tipo_label("diesel_500"), "Diesel 500")
        self.assertEqual(server._combustivel_tipo_label("gasolina"), "Gasolina")
        self.assertEqual(server._combustivel_tipo_label("etanol"), "Etanol")

    def test_validar_combustivel_rejeita_tipo_fora_da_lista(self):
        with self.assertRaisesRegex(ValueError, "Gasolina, Etanol"):
            server._validar_combustivel_tipo("gnv")

    def test_combustivel_do_veiculo_define_padrao_e_restringe_por_tipo(self):
        cursor_s10 = _FakeCursor([{"combustivel_padrao": "diesel_s10"}])
        self.assertEqual(
            server._validar_combustivel_para_veiculo(cursor_s10, 1, ""),
            "diesel_s10",
        )

        cursor_arla = _FakeCursor([{"combustivel_padrao": "diesel_s10"}])
        self.assertEqual(
            server._validar_combustivel_para_veiculo(cursor_arla, 1, "arla"),
            "arla",
        )

        cursor_s500 = _FakeCursor([{"combustivel_padrao": "diesel_500"}])
        with self.assertRaisesRegex(ValueError, "nao permite abastecimento com Arla"):
            server._validar_combustivel_para_veiculo(cursor_s500, 2, "arla")

        cursor_flex_gasolina = _FakeCursor([{"combustivel_padrao": "flex"}])
        self.assertEqual(
            server._validar_combustivel_para_veiculo(
                cursor_flex_gasolina,
                3,
                "",
            ),
            "gasolina",
        )
        cursor_flex_etanol = _FakeCursor([{"combustivel_padrao": "flex"}])
        self.assertEqual(
            server._validar_combustivel_para_veiculo(
                cursor_flex_etanol,
                3,
                "etanol",
            ),
            "etanol",
        )
        cursor_flex_diesel = _FakeCursor([{"combustivel_padrao": "flex"}])
        with self.assertRaisesRegex(ValueError, "Gasolina ou Etanol"):
            server._validar_combustivel_para_veiculo(
                cursor_flex_diesel,
                3,
                "diesel_s10",
            )

    def test_gol_polo_e_saveiro_sao_classificados_como_flex(self):
        for modelo in ("Gol", "VW Polo Track", "Saveiro Robust"):
            self.assertTrue(server._modelo_veiculo_e_flex(modelo))
            self.assertEqual(
                server._combustivel_padrao_para_modelo(modelo, "diesel_500"),
                "flex",
            )

    def test_detectar_combustivel_diferencia_s10_e_500(self):
        self.assertEqual(server._detectar_combustivel_tipo_item("OLEO DIESEL S10"), "diesel_s10")
        self.assertEqual(server._detectar_combustivel_tipo_item("DIESEL S-500 COMUM"), "diesel_500")
        self.assertEqual(server._detectar_combustivel_tipo_item("GASOLINA COMUM"), "gasolina")
        self.assertEqual(server._detectar_combustivel_tipo_item("ETANOL HIDRATADO COMUM"), "etanol")
        self.assertEqual(server._detectar_combustivel_tipo_item("ARLA 32"), "arla")
        self.assertEqual(
            server.COMBUSTIVEL_TIPOS,
            ("diesel_s10", "diesel_500", "gasolina", "etanol", "arla"),
        )

    def test_api_liberar_rejeita_combustivel_fora_da_lista(self):
        with server.app.test_client() as client:
            response = client.post("/api/abastecimentos/liberar", json={
                "veiculo_id": 1,
                "km": 1000,
                "posto": "Posto Teste",
                "combustivel_tipo": "gnv",
            })

        self.assertEqual(response.status_code, 400)
        self.assertIn("Diesel S10", response.get_json()["erro"])

    def test_api_atualiza_polo_para_flex_e_reprocessa_xmls(self):
        cursor = _FakeCursor([{"combustivel_padrao": "diesel_500"}])
        connection = _FakeConnection(cursor)
        resumo_sync = {"criados": 1, "pendentes": 0}

        with mock.patch.object(server, "get_conn", return_value=connection), \
            mock.patch.object(
                server,
                "_sincronizar_xml_apos_cadastro_veiculo",
                return_value=resumo_sync,
            ) as sync_mock, \
            server.app.test_client() as client:
            response = client.put("/api/veiculos/77", json={
                "nome": "Polo administrativo",
                "placa": "ABC-1D23",
                "modelo": "VW Polo Track",
                "km_atual": 50000,
                "intervalo_manut_km": 10000,
                "intervalo_oleo_km": 5000,
                "combustivel_padrao": "diesel_500",
            })

        self.assertEqual(200, response.status_code)
        update_params = next(
            params
            for sql, params in cursor.executed
            if "UPDATE veiculos" in sql
        )
        self.assertEqual("flex", update_params[6])
        self.assertEqual(resumo_sync, response.get_json()["sincronizacao_xml"])
        sync_mock.assert_called_once_with()

    def test_api_editar_abastecimento_atualiza_tipo_e_dados(self):
        cursor_edicao = _FakeCursor([
            {
                "id": 7,
                "status": "abastecido",
                "data_abastecimento": "2026-06-01 08:00:00",
            },
            {"combustivel_padrao": "diesel_500"},
        ])
        cursor_pdf = _FakeCursor([{
            "id": 7,
            "veiculo_id": 2,
            "status": "abastecido",
            "combustivel_tipo": "diesel_500",
        }])
        conn_edicao = _FakeConnection(cursor_edicao)
        conn_pdf = _FakeConnection(cursor_pdf)

        with mock.patch.object(server, "get_conn", side_effect=[conn_edicao, conn_pdf]), \
            mock.patch.object(server, "_carregar_nfe_config", return_value={"bloquear_notas_duplicadas": True}), \
            mock.patch.object(server, "_build_abastecimento_pdf") as pdf_mock, \
            server.app.test_client() as client:
            response = client.put("/api/abastecimentos/7", json={
                "veiculo_id": 2,
                "km": 2500,
                "posto": "Posto Novo",
                "combustivel_tipo": "diesel_500",
                "chave_acesso_nfe": "",
                "numero_nota": "",
                "emitente_nome": "Posto Novo Ltda",
                "valor": 700,
                "quantidade_litros": 100,
                "data_abastecimento": "2026-06-09T14:30",
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["combustivel_tipo"], "diesel_500")
        self.assertTrue(conn_edicao.committed)
        update_params = next(
            params
            for sql, params in cursor_edicao.executed
            if "UPDATE abastecimentos" in sql
        )
        self.assertEqual(update_params[3], "diesel_500")
        pdf_mock.assert_called_once()

    def test_metricas_abastecimento_incluem_gasolina_e_ignoram_arla_no_km_l(self):
        rows = [
            {"id": 1, "veiculo_id": 10, "km": 1000, "quantidade_litros": 100, "valor": 600, "status": "abastecido", "combustivel_tipo": "diesel_s10"},
            {"id": 2, "veiculo_id": 10, "km": 1100, "quantidade_litros": 20, "valor": 80, "status": "abastecido", "combustivel_tipo": "arla"},
            {"id": 3, "veiculo_id": 10, "km": 1500, "quantidade_litros": 100, "valor": 650, "status": "abastecido", "combustivel_tipo": "gasolina"},
        ]

        metricas = server._calcular_metricas_abastecimentos(rows)

        self.assertIsNone(metricas[2]["km_l"])
        self.assertEqual(metricas[2]["valor_litro"], 4.0)
        self.assertEqual(metricas[3]["km_inicial"], 1000)
        self.assertEqual(metricas[3]["km_rodado"], 500)
        self.assertEqual(metricas[3]["km_l"], 5.0)

    def test_extrair_resumo_nota_amarela_ocr(self):
        linhas = [
            "POSTO EXEMPLO",
            "DIESEL 31,64 LT X 6,99",
            "TOTAL R$ 221,10",
        ]

        resumo = server._extrair_resumo_nota_amarela_ocr(linhas, combustivel_tipo="diesel")

        self.assertEqual(resumo["quantidade_litros"], 31.64)
        self.assertEqual(resumo["valor"], 221.10)
        self.assertEqual(resumo["combustivel_tipo"], "diesel_s10")

    def test_extrair_url_payload_barcode(self):
        raw = "https://www.exemplo.com/nfce?q=1&p=123"
        self.assertEqual(server._extrair_url_payload_barcode(raw), raw)

    def test_montar_url_consulta_nfe_com_chave(self):
        url = server._montar_url_consulta_nfe("https://consulta.exemplo.com?a=1", "1" * 44)
        self.assertIn("nfe=" + ("1" * 44), url)

    def test_scrape_resumo_abastecimento_html_por_tabela(self):
        html = """
        <html><body>
          <table>
            <tr><th>Produto</th><th>Quantidade</th><th>Valor Total</th></tr>
            <tr><td>OLEO DIESEL S10</td><td>1200,000</td><td>6598,80</td></tr>
          </table>
        </body></html>
        """

        resumo = server._scrape_resumo_abastecimento_html(html, chave_acesso="1" * 44, combustivel_tipo="diesel")

        self.assertEqual(resumo["quantidade_litros"], 1200.0)
        self.assertEqual(resumo["valor"], 6598.80)
        self.assertEqual(resumo["chave_acesso_nfe"], "1" * 44)

    def test_scrape_resumo_abastecimento_html_nota_amarela(self):
        html = """
        <html><body>
          <div>ARLA 32 LT 250,000</div>
          <div>TOTAL R$ 300,00</div>
        </body></html>
        """

        resumo = server._scrape_resumo_abastecimento_html(html, chave_acesso="2" * 44, combustivel_tipo="arla")

        self.assertEqual(resumo["quantidade_litros"], 250.0)
        self.assertEqual(resumo["valor"], 300.0)
        self.assertEqual(resumo["combustivel_tipo"], "arla")

    def test_extrair_resumo_combustivel_secao_ocr_funciona_sem_cabecalho_completo_da_nfe(self):
        texto = """
        COD DESCRICAO UN QTD V.UNIT V.TOTAL
        1 DIESEL S10 LT 1200,000 5,499 6598,80
        """

        resumo = server._extrair_resumo_combustivel_secao_ocr(texto, combustivel_tipo="diesel")

        self.assertEqual(resumo["quantidade_litros"], 1200.0)
        self.assertEqual(resumo["valor"], 6598.80)

    def test_extrair_resumo_combustivel_secao_ocr_reconhece_nota_amarela(self):
        texto = """
        DIESEL 31,64 LT X 6,99
        TOTAL R$ 221,10
        """

        resumo = server._extrair_resumo_combustivel_secao_ocr(texto, combustivel_tipo="diesel")

        self.assertEqual(resumo["quantidade_litros"], 31.64)
        self.assertEqual(resumo["valor"], 221.10)

    def test_selecionar_resumo_combustivel_ocr_textos_prefere_par_mais_recorrente(self):
        textos = ["ocr-1", "ocr-2", "ocr-3"]

        def fake_extract(texto, combustivel_tipo=""):
            if texto == "ocr-1":
                return {"combustivel_tipo": "diesel_s10", "quantidade_litros": 1200.0, "valor": 6598.80, "valor_unitario": 5.499}
            if texto == "ocr-2":
                return {"combustivel_tipo": "diesel_s10", "quantidade_litros": 1200.0, "valor": 6598.80, "valor_unitario": 5.499}
            return {"combustivel_tipo": "diesel_s10", "quantidade_litros": 1200.0, "valor": 6599.10, "valor_unitario": 5.499}

        with mock.patch.object(server, "_extrair_resumo_combustivel_secao_ocr", side_effect=fake_extract):
            resumo, variantes = server._selecionar_resumo_combustivel_ocr_textos(textos, combustivel_tipo="diesel")

        self.assertEqual(resumo["quantidade_litros"], 1200.0)
        self.assertEqual(resumo["valor"], 6598.80)
        self.assertEqual(resumo["itens_encontrados"], 2)
        self.assertEqual(variantes[0]["ocorrencias"], 2)
        self.assertEqual(variantes[0]["valor"], 6598.80)

    def test_ocr_preview_abastecimento_prioriza_secao_produtos_para_valor_e_quantidade(self):
        textos = ["ocr-a", "ocr-b"]
        resumo = {
            "combustivel_tipo": "diesel_s10",
            "quantidade_litros": 1200.0,
            "valor": 6598.80,
            "itens_encontrados": 2,
        }

        with mock.patch.object(server, "_carregar_dependencias_ocr", return_value=(io.BytesIO, _FakeImageModule, object())), \
            mock.patch.object(server, "_preparar_candidatos_ocr_imagem", return_value=[_FakeImage()]), \
            mock.patch.object(server, "_coletar_textos_ocr_imagem", return_value=textos), \
            mock.patch.object(server, "_selecionar_resumo_combustivel_ocr_textos", return_value=(resumo, [])):
            preview = server._ocr_preview_abastecimento_imagem_bytes(b"fake-image", arquivo_origem="teste.jpg", combustivel_tipo="diesel")

        self.assertEqual(preview["quantidade_litros"], 1200.0)
        self.assertEqual(preview["valor"], 6598.80)
        self.assertEqual(preview["valor_total"], 6598.80)
        self.assertEqual(preview["combustivel_tipo"], "diesel_s10")
        self.assertEqual(preview["chave_acesso"], "")
        self.assertTrue(any("Quantidade e V.Total" in msg for msg in preview["warnings"]))

    def test_barcode_preview_abastecimento_usa_curl_e_scraping_do_qr_code(self):
        payload = {
            "raw": "https://www.exemplo.com/consulta?p=abc",
            "url": "https://www.exemplo.com/consulta?p=abc",
            "chave_acesso": "1" * 44,
        }
        resumo = {
            "combustivel_tipo": "diesel_s10",
            "quantidade_litros": 1200.0,
            "valor": 6598.80,
            "itens_encontrados": 1,
            "numero_nota": "",
            "emitente_nome": "",
        }

        with mock.patch.object(server, "_detectar_payload_barcode_imagem_bytes", return_value=payload), \
            mock.patch.object(server, "_resumo_abastecimento_por_url_barcode", return_value=resumo):
            preview = server._barcode_preview_abastecimento_imagem_bytes(b"fake-image", arquivo_origem="barcode.jpg", combustivel_tipo="diesel")

        self.assertEqual(preview["source_type"], "barcode_scrape")
        self.assertEqual(preview["chave_acesso"], "1" * 44)
        self.assertEqual(preview["quantidade_litros"], 1200.0)
        self.assertEqual(preview["valor"], 6598.80)
        self.assertTrue(any("scraping" in msg.lower() for msg in preview["warnings"]))

    def test_barcode_preview_abastecimento_monta_url_quando_payload_tem_so_chave(self):
        payload = {
            "raw": "123456",
            "url": "",
            "chave_acesso": "1" * 44,
        }
        resumo = {
            "combustivel_tipo": "diesel_s10",
            "quantidade_litros": 31.64,
            "valor": 221.10,
            "itens_encontrados": 1,
            "numero_nota": "",
            "emitente_nome": "",
        }

        with mock.patch.object(server, "_detectar_payload_barcode_imagem_bytes", return_value=payload), \
            mock.patch.object(server, "_carregar_nfe_config", return_value={"consulta_url": "https://consulta.exemplo.com?tipo=1"}), \
            mock.patch.object(server, "_resumo_abastecimento_por_url_barcode", return_value=resumo) as resumo_mock:
            preview = server._barcode_preview_abastecimento_imagem_bytes(b"fake-image", arquivo_origem="barcode.jpg", combustivel_tipo="diesel")

        called_url = resumo_mock.call_args.args[0]
        self.assertIn("nfe=" + ("1" * 44), called_url)
        self.assertEqual(preview["quantidade_litros"], 31.64)
        self.assertTrue(any("montou a URL" in msg for msg in preview["warnings"]))


if __name__ == "__main__":
    unittest.main()
