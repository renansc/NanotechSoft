import unittest
from pathlib import Path
from unittest import mock

import server


class EstoqueTaxonomiaBebidasTests(unittest.TestCase):
    def test_normaliza_sabor_volume_e_apresentacao(self):
        self.assertEqual(
            "UVA 2L",
            server._estoque_base_nome_inferido("Refrigerante Uva PET 2 L"),
        )
        self.assertEqual(
            "LIMAO (SODA) 600ML",
            server._estoque_base_nome_inferido("Soda limão PET 600 ml"),
        )
        self.assertEqual(
            "RETORNAVEL LARANJA 200ML",
            server._estoque_base_nome_inferido(
                "Garrafa retornável Laranja 200 ml",
            ),
        )
        self.assertEqual(
            "AGUA SEM GAS 510ML",
            server._estoque_base_nome_inferido("Água sem gás 510 ml"),
        )

    def test_nome_canonico_prevalece_sobre_cadastro_duplicado(self):
        self.assertEqual(
            "COLA 2L",
            server._estoque_base_nome_inferido(
                "Refrigerante Cola PET 2L",
                grupo_estoque="PET",
                produto_base_nome="REFRI COLA DO CADASTRO ANTIGO",
            ),
        )

    def test_agua_bonita_no_fornecedor_nao_vira_agua_mineral(self):
        saco = "SACO PP BIG BAG 4 ALCAS 1200 KG AGUA BONITA UN"
        acucar = "ACUCAR CRISTAL A GRANEL AGUA BONITA GRANEL"
        self.assertEqual("OUTROS", server._estoque_grupo_inferido(saco))
        self.assertEqual("OUTROS", server._estoque_grupo_inferido(acucar))
        self.assertEqual(
            "SACO PP BIG BAG 4 ALCAS 1200 KG AGUA BONITA",
            server._estoque_base_nome_inferido(saco),
        )
        self.assertEqual(
            "SACO PP BIG BAG 4 ALCAS 1200 KG AGUA BONITA UN",
            server._estoque_base_nome_inferido(
                saco,
                grupo_estoque="OUTROS",
                produto_base_nome=saco,
            ),
        )
        self.assertEqual(
            "AGUA",
            server._estoque_grupo_inferido("Agua mineral sem gas 510 ml"),
        )

    def test_inferencia_reconhece_tampas_preforma_e_grupo_customizado(self):
        self.assertEqual(
            "TAMPAS",
            server._estoque_grupo_inferido("Tampa baixa vermelha"),
        )
        self.assertEqual(
            "PREFORMA",
            server._estoque_grupo_inferido("Pré-forma PET 28 mm"),
        )
        self.assertEqual(
            "MATERIAL_PROMOCIONAL",
            server._estoque_grupo_normalizado("Material promocional"),
        )

    def test_saldo_prioriza_codigo_exato_antes_da_familia(self):
        rows = [
            {
                "codigo_produto_nfe": "005900",
                "produto_base_key": "AGUA:AGUA SEM GAS 510ML",
                "quantidade_atual": 800,
            },
            {
                "codigo_produto_nfe": "000222",
                "produto_base_key": "OUTROS:SACO PP BIG BAG 4 ALCAS 1200 KG AGUA BONITA",
                "quantidade_atual": 365,
            },
        ]
        with mock.patch.object(
            server,
            "_estoque_resumo_produtos_data",
            return_value={"rows": rows},
        ):
            saldo = server._saldo_atual_produto_estoque(
                None,
                codigo_produto_nfe="000222",
                nome_produto="AGUA SEM GAS 510ML",
            )
        self.assertEqual(365, saldo)

    def test_fatores_padrao_das_embalagens(self):
        self.assertEqual(
            6,
            server._fator_base_produto("Uva PET 2L", "PCT", "PCT", "PET"),
        )
        self.assertEqual(
            12,
            server._fator_base_produto("Uva PET 600ML", "PCT", "PCT", "PET"),
        )
        self.assertEqual(
            24,
            server._fator_base_produto(
                "Uva retornável 600ML", "CX", "CX", "GFA",
            ),
        )
        self.assertEqual(
            48,
            server._fator_base_produto(
                "Uva retornável 200ML", "CX", "CX", "GFA",
            ),
        )
        self.assertEqual(
            12,
            server._fator_base_produto(
                "Água com gás 510ML", "PCT", "PCT", "AGUA",
            ),
        )

    def test_classifica_hierarquia_operacional_do_estoque(self):
        self.assertEqual(
            {
                "estoque_area": "PRODUCAO",
                "estoque_subgrupo": "PRODUTOS",
                "exibir_dashboard": True,
            },
            server._estoque_classificacao_operacional(
                {"nome_produto": "Refrigerante Cola PET 2L", "grupo_estoque": "PET"}
            ),
        )
        self.assertEqual(
            "MATERIA_PRIMA",
            server._estoque_classificacao_operacional(
                {
                    "nome_produto": "Concentrado de guaraná",
                    "fornecedor_categorias": ["materia_prima"],
                }
            )["estoque_subgrupo"],
        )
        self.assertEqual(
            "ALMOXARIFADO_GERAL",
            server._estoque_classificacao_operacional(
                {"nome_produto": "Papel A4"}
            )["estoque_area"],
        )

    def test_agua_com_e_sem_gas_nao_sao_unificadas(self):
        com_gas = server._estoque_produto_meta(
            {"nome_produto": "Agua mineral com gas 510 ml", "grupo_estoque": "AGUA"}
        )
        sem_gas = server._estoque_produto_meta(
            {"nome_produto": "AGUA SEM GAS 510ML", "grupo_estoque": "AGUA"}
        )
        self.assertNotEqual(com_gas["produto_base_key"], sem_gas["produto_base_key"])

    def test_normaliza_codigos_por_origem(self):
        codigos, informado = server._estoque_codigos_payload({
            "codigos_nfe_entrada": "000123, 000123;NF-45",
            "codigos_sellout": ["77", "00077"],
            "codigos_nfe_saida": "900\n901",
        })
        self.assertTrue(informado)
        self.assertEqual(["000123", "NF-45"], codigos["nfe_entrada"])
        self.assertEqual(["77"], codigos["sellout"])
        self.assertEqual(["900", "901"], codigos["nfe_saida"])

    def test_amarracao_fica_restrita_a_pet_e_agua(self):
        self.assertTrue(server._estoque_produto_eh_vendido({"grupo_estoque": "PET"}))
        self.assertTrue(server._estoque_produto_eh_vendido({"grupo_estoque": "AGUA"}))
        self.assertFalse(server._estoque_produto_eh_vendido({"grupo_estoque": "GFA"}))
        self.assertFalse(server._estoque_produto_eh_vendido({"grupo_estoque": "OUTROS"}))

    def test_lookup_respeita_o_tipo_de_codigo(self):
        entrada = {"id": 1, "nome_produto": "COLA PET 2L"}
        venda = {"id": 2, "nome_produto": "AGUA SEM GAS 510ML"}
        lookup = {
            "codigo_barras": {},
            "codigo_produto_nfe": {},
            "nome_produto": {},
            "produto_base_key": {},
            "codigo_origem": {
                "nfe_entrada": {"10": entrada},
                "sellout": {"10": venda},
            },
        }
        self.assertIs(
            entrada,
            server._resolver_produto_lookup_estoque(
                lookup, codigo_produto_nfe="000010", origem_codigo="nfe_entrada"
            ),
        )
        self.assertIs(
            venda,
            server._resolver_produto_lookup_estoque(
                lookup, codigo_produto_nfe="10", origem_codigo="sellout"
            ),
        )

    def test_lookup_tipado_prioriza_nome_antes_do_codigo_legado(self):
        codigo_legado = {"id": 1, "nome_produto": "COLA PET 2L"}
        descricao_sellout = {"id": 2, "nome_produto": "AGUA SEM GAS 510ML"}
        lookup = {
            "codigo_barras": {},
            "codigo_produto_nfe": {"10": codigo_legado},
            "nome_produto": {"AGUA SEM GAS 510ML": descricao_sellout},
            "produto_base_key": {},
            "codigo_origem": {origem: {} for origem in server._ESTOQUE_CODIGO_ORIGENS},
        }
        self.assertIs(
            descricao_sellout,
            server._resolver_produto_lookup_estoque(
                lookup,
                codigo_produto_nfe="10",
                nome_produto="Agua sem gas 510ml",
                origem_codigo="sellout",
            ),
        )

    def test_previsao_semanal_nao_duplica_venda_e_saida(self):
        previsao = server._estoque_previsao_producao_semanal(
            vendas_semana=70,
            saidas_semana=60,
            saldo_disponivel=20,
            dias_decorridos=7,
        )
        self.assertEqual(70, previsao["demanda_semana_observada"])
        self.assertEqual(70, previsao["previsao_demanda_semana"])
        self.assertEqual(50, previsao["necessidade_producao_semana"])

    def test_previsao_semanal_projeta_periodo_parcial(self):
        previsao = server._estoque_previsao_producao_semanal(
            vendas_semana=30,
            saidas_semana=40,
            saldo_disponivel=10,
            dias_decorridos=2,
        )
        self.assertEqual(140, previsao["previsao_demanda_semana"])
        self.assertEqual(130, previsao["necessidade_producao_semana"])

    def test_previsao_mensal_usa_sazonalidade_e_media_recente(self):
        previsao = server._estoque_previsao_producao_mensal(
            vendas_mes_atual=200,
            vendas_mes_ano_anterior=1000,
            vendas_meses_recentes=[800, 900, 1000],
            saldo_disponivel=300,
        )
        self.assertEqual(900, previsao["media_vendas_ultimos_meses"])
        self.assertEqual(1000, previsao["demanda_referencia_mensal"])
        self.assertEqual(800, previsao["demanda_restante_mes"])
        self.assertEqual(500, previsao["necessidade_producao_mensal"])

    def test_previsao_mensal_funciona_com_historico_parcial(self):
        previsao = server._estoque_previsao_producao_mensal(
            vendas_mes_atual=100,
            vendas_mes_ano_anterior=None,
            vendas_meses_recentes=[600, 900],
            saldo_disponivel=200,
        )
        self.assertIsNone(previsao["vendas_mes_ano_anterior"])
        self.assertEqual(750, previsao["demanda_referencia_mensal"])
        self.assertEqual(450, previsao["necessidade_producao_mensal"])

    def test_identifica_mes_em_arquivo_historico_sem_data_por_linha(self):
        self.assertEqual(
            "2026-06",
            server._estoque_mes_chave(
                server._estoque_mes_nome_arquivo("20260808_SELLOUT_Mes_junho2026.CSV")
            ),
        )

    def test_interface_permite_definir_saldo_fisico(self):
        raiz = Path(__file__).resolve().parents[1]
        html = (raiz / "RioBranco.html").read_text(encoding="utf-8")
        script = (raiz / "script.js").read_text(encoding="utf-8")
        self.assertIn('id="estoqueCadastroSaldoAtual"', html)
        self.assertIn("definirSaldoAtualProdutoEstoqueCadastro", script)
        self.assertIn("quantidade_atual", script)

    def test_interface_salva_cadastro_e_acerto_na_mesma_acao(self):
        raiz = Path(__file__).resolve().parents[1]
        html = (raiz / "RioBranco.html").read_text(encoding="utf-8")
        script = (raiz / "script.js").read_text(encoding="utf-8")
        self.assertIn("Salvar Cadastro e Acerto", html)
        self.assertIn("let ajustePayload = null", script)
        self.assertIn("body: JSON.stringify(ajustePayload)", script)
        self.assertIn("ensureProdutosEstoqueCache(true)", script)

    def test_acerto_repetido_nao_reutiliza_referencia_unica_do_produto(self):
        class Cursor:
            def __init__(self):
                self.inserts = []

            def execute(self, sql, params=None):
                if "INSERT INTO estoque_movimentos" in sql:
                    self.inserts.append(params)

            def close(self):
                pass

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()
                self.commits = 0

            def cursor(self, dictionary=False):
                return self.cursor_instance

            def commit(self):
                self.commits += 1

            def close(self):
                pass

        connection = Connection()
        produto = {
            "id": 112,
            "codigo_barras": "",
            "codigo_produto_nfe": "18810327",
            "nome_produto": "TAMPA BAIXA VERMELHA",
            "grupo_estoque": "OUTROS",
            "produto_base_nome": "TAMPA BAIXA VERMELHA",
            "unidade": "CX",
            "embalagem_tipo_padrao": "CX",
            "fator_embalagem_padrao": 7000,
        }
        with (
            mock.patch.object(server, "get_conn", return_value=connection),
            mock.patch.object(server, "_carregar_produto_estoque_por_id", return_value=produto),
            mock.patch.object(server, "_saldo_atual_produto_estoque", side_effect=[140150, 910000]),
            server.app.test_client() as client,
        ):
            headers = {"X-Usuario-Perfil": "admin"}
            primeira = client.post(
                "/api/estoque/produtos/112/ajuste",
                json={"quantidade_atual": 910000, "motivo_ajuste": "Inventario fisico"},
                headers=headers,
            )
            segunda = client.post(
                "/api/estoque/produtos/112/ajuste",
                json={"quantidade_atual": 900000, "motivo_ajuste": "Recontagem"},
                headers=headers,
            )

        self.assertEqual(200, primeira.status_code)
        self.assertEqual(200, segunda.status_code)
        self.assertEqual(2, connection.commits)
        self.assertEqual([None, None], [params[9] for params in connection.cursor_instance.inserts])

    def test_acerto_com_saldo_ja_correto_retorna_sucesso_sem_movimento(self):
        class Cursor:
            def __init__(self):
                self.inserts = []

            def execute(self, sql, params=None):
                if "INSERT INTO estoque_movimentos" in sql:
                    self.inserts.append(params)

            def close(self):
                pass

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()
                self.commits = 0

            def cursor(self, dictionary=False):
                return self.cursor_instance

            def commit(self):
                self.commits += 1

            def close(self):
                pass

        connection = Connection()
        produto = {
            "id": 128,
            "codigo_barras": "",
            "codigo_produto_nfe": "000222",
            "nome_produto": "SACO PP BIG BAG 4 ALCAS 1200 KG AGUA BONITA UN",
            "grupo_estoque": "OUTROS",
            "produto_base_nome": "SACO PP BIG BAG 4 ALCAS 1200 KG AGUA BONITA UN",
            "unidade": "UN",
            "embalagem_tipo_padrao": "UN",
            "fator_embalagem_padrao": 1,
        }
        with (
            mock.patch.object(server, "get_conn", return_value=connection),
            mock.patch.object(server, "_carregar_produto_estoque_por_id", return_value=produto),
            mock.patch.object(server, "_saldo_atual_produto_estoque", return_value=365),
            server.app.test_client() as client,
        ):
            resp = client.post(
                "/api/estoque/produtos/128/ajuste",
                json={"quantidade_atual": 365, "motivo_ajuste": "Conferencia"},
                headers={"X-Usuario-Perfil": "admin"},
            )

        self.assertEqual(200, resp.status_code)
        self.assertTrue(resp.get_json()["sem_alteracao"])
        self.assertEqual([], connection.cursor_instance.inserts)
        self.assertEqual(0, connection.commits)

    def test_interface_usa_fator_cadastrado_para_caixas_do_almoxarifado(self):
        raiz = Path(__file__).resolve().parents[1]
        script = (raiz / "script.js").read_text(encoding="utf-8")
        self.assertIn("fatorCadastro > 1 ? fatorCadastro : 0", script)
        self.assertIn('if (embalagem.startsWith("CX")) return "caixas";', script)
        self.assertIn("fatoresEmbalagem.length === 1", script)

    def test_dashboard_exibe_somente_produtos_ativos_e_cadastrados(self):
        rows = [
            {"produto_id": 1, "produto_cadastrado": True, "produto_ativo": True, "exibir_dashboard": True, "grupo_estoque": "GFA", "quantidade_comprometida": 5},
            {"produto_id": 4, "produto_cadastrado": True, "produto_ativo": True, "exibir_dashboard": True, "grupo_estoque": "TAMPAS", "quantidade_comprometida": 0},
            {"produto_id": 2, "produto_cadastrado": True, "produto_ativo": False, "exibir_dashboard": True},
            {"produto_id": 0, "produto_cadastrado": False, "produto_ativo": True, "exibir_dashboard": True},
            {"produto_id": 3, "produto_cadastrado": True, "produto_ativo": True, "exibir_dashboard": False},
        ]
        with mock.patch.object(
            server,
            "_estoque_resumo_produtos_data",
            return_value={"rows": rows, "meta": {}},
        ) as resumo_mock:
            payload = server._dashboard_estoque_data()
        self.assertEqual([1], [row["produto_id"] for row in payload["rows"]])
        self.assertEqual([1], [row["produto_id"] for row in payload["retornaveis"]])
        self.assertEqual([], payload["pet_agua"])
        self.assertEqual([1], [row["produto_id"] for row in payload["comprometidos"]])
        self.assertTrue(payload["rows"][0]["sugestao_producao_aplicavel"])
        self.assertEqual(1, payload["meta"]["itens_dashboard"])
        self.assertEqual(5, payload["meta"]["quantidade_comprometida_total"])
        resumo_mock.assert_called_once_with(incluir_fornecedores=False)

    def test_interface_tem_grupos_dinamicos_e_atualizacao_a_cada_cinco_segundos(self):
        raiz = Path(__file__).resolve().parents[1]
        html = (raiz / "RioBranco.html").read_text(encoding="utf-8")
        script = (raiz / "script.js").read_text(encoding="utf-8")
        self.assertIn('id="estoqueGruposBody"', html)
        self.assertIn('id="estoqueGrupoDashboard"', html)
        self.assertNotIn('id="dashEstoquePrevisaoBody"', html)
        self.assertIn('/api/estoque/grupos', script)
        self.assertIn('}, 5000);', script)
        self.assertIn('dashboardEstoqueAtualizando', script)

    def test_dashboard_separa_retornavel_de_pet_agua_e_relatorio_fica_em_relatorios(self):
        raiz = Path(__file__).resolve().parents[1]
        html = (raiz / "RioBranco.html").read_text(encoding="utf-8")
        script = (raiz / "script.js").read_text(encoding="utf-8")
        self.assertIn('id="dashEstoqueRetornavelBody"', html)
        self.assertIn('id="dashEstoquePetAguaBody"', html)
        self.assertNotIn('id="dashEstoqueComprometidoBody"', html)
        self.assertIn("Previsão de Consumo da Semana", html)
        self.assertIn("Sugestão de Produção para Semana", html)
        self.assertIn('id="relatorios"', html)
        self.assertIn('id="relatorioEstoqueDataInicio"', html)
        self.assertIn('id="relatorioEstoqueDataFim"', html)
        self.assertIn('id="relatorioEstoqueGrupo"', html)
        self.assertIn('id="relatorioEstoqueProduto"', html)
        self.assertIn("abrirPdfRelatorioEstoqueComprometido", script)
        self.assertIn("sugestao_producao_semana", script)

    def test_previsao_semanal_historica_desconta_consumo_e_estoque(self):
        previsao = server._estoque_previsao_consumo_semanal_historica(
            demanda_referencia_mensal=310,
            referencias_disponiveis=2,
            vendas_semana=20,
            saidas_semana=18,
            saldo_disponivel=30,
            dias_mes=31,
        )
        self.assertEqual(70, previsao["previsao_consumo_semana"])
        self.assertEqual(20, previsao["consumo_semana_realizado"])
        self.assertEqual(50, previsao["consumo_restante_semana"])
        self.assertEqual(20, previsao["sugestao_producao_semana"])
        self.assertEqual("historico_mensal", previsao["origem_previsao_semana"])

    def test_relatorio_comprometido_filtra_data_grupo_e_produto(self):
        rows = [{
            "produto_id": 10,
            "produto_cadastrado": True,
            "produto_ativo": True,
            "nome_produto": "COLA 2L",
            "grupo_estoque": "PET",
            "quantidade_atual": 100,
            "comprometimentos": [
                {"carga_id": 1, "carga_nome": "Carga antiga", "data_comprometimento": "2026-08-01", "quantidade": 15},
                {"carga_id": 2, "carga_nome": "Carga atual", "data_comprometimento": "2026-08-20", "quantidade": 25},
            ],
        }]
        with mock.patch.object(
            server,
            "_estoque_resumo_produtos_data",
            return_value={"rows": rows, "meta": {"grupos_estoque": [{"codigo": "PET", "nome": "PET", "ativo": True}]}},
        ):
            relatorio = server._estoque_relatorio_comprometido_data(
                data_inicio=server._parse_data_br("2026-08-10"),
                data_fim=server._parse_data_br("2026-08-31"),
                grupo_estoque="PET",
                produto_id=10,
            )
        self.assertEqual(1, len(relatorio["rows"]))
        self.assertEqual(25, relatorio["rows"][0]["quantidade_comprometida"])
        self.assertEqual(75, relatorio["rows"][0]["saldo_remanescente"])
        self.assertEqual(25, relatorio["meta"]["quantidade_comprometida_total"])

    def test_exclusao_de_produto_preserva_historico_e_desativa_cadastro(self):
        fonte = Path(server.__file__).read_text(encoding="utf-8")
        self.assertIn("UPDATE estoque_produtos SET ativo=0 WHERE id=%s", fonte)
        self.assertIn("UPDATE estoque_produto_codigos SET ativo=0 WHERE produto_id=%s", fonte)

    def test_dashboard_busca_ultimo_valor_sem_subconsulta_por_linha(self):
        fonte = Path(server.__file__).read_text(encoding="utf-8")
        self.assertIn("MAX(e.id) AS ultimo_movimento_id", fonte)
        self.assertIn("SELECT id, valor_unitario FROM estoque_movimentos WHERE id IN", fonte)
        self.assertNotIn("SELECT e2.valor_unitario", fonte)


if __name__ == "__main__":
    unittest.main()
