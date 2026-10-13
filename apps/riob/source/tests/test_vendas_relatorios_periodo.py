"""Regras comuns dos relatorios; integracao usa somente tabelas temporarias."""
import datetime as dt
import os
import unittest
from unittest import mock

from vendas_report_test_support import load_sales_server


class SalesRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = load_sales_server()

    def test_autonomos_e_alias_legado(self):
        for nome in ['Luis Carlos Pires', 'Norival Vignoto', 'Luiz Humberto Vignoto', 'Luiz Humbert Vignoto']:
            self.assertEqual('autonomo', self.s._vendas_tipo_vendedor(nome, '001 - ' + nome))
        self.assertEqual('clt', self.s._vendas_tipo_vendedor('Outro vendedor'))

    def test_exclusao_por_nome_e_codigo_preserva_vendedor_real(self):
        for nome in ['001 - BALCÃO', 'BALCAO', '009-OUTROS', 'Venda de balcão']:
            self.assertTrue(self.s._vendas_vendedor_excluido({'vendedor_key': nome}))
        self.assertFalse(self.s._vendas_vendedor_excluido({'vendedor_nome': 'Joao Balcaoneto'}))

    def test_intervalo_inclusivo_substitui_mes_e_aceita_um_limite(self):
        sql, params = self.s._vendas_sql_periodo_where('test', '2026-09', '2026-09-30', '2026-10-02')
        self.assertEqual(['test', dt.date(2026, 9, 30), dt.date(2026, 10, 2)], params)
        self.assertIn('data_ref <= %s', sql)
        self.assertEqual(['test', dt.date(2026, 9, 1), dt.date(2026, 9, 30)],
                         self.s._vendas_sql_periodo_where('test', '2026-09')[1])
        self.assertEqual(['test', dt.date(2026, 10, 2)],
                         self.s._vendas_sql_periodo_where('test', '2026-09', data_fim='2026-10-02')[1])
        for inicio, fim in [('x', ''), ('2026-02-30', ''), ('2026-10-02', '2026-09-30')]:
            with self.assertRaises(ValueError):
                self.s._vendas_validar_periodo(inicio, fim)


@unittest.skipUnless(os.environ.get('RB_REPORT_TEST_MYSQL') == '1', 'SQL real opcional')
class SalesPeriodSqlTest(unittest.TestCase):
    def setUp(self):
        import mysql.connector
        self.s = load_sales_server()
        self.conn = mysql.connector.connect(host=os.environ['DB_HOST'],
            port=int(os.environ.get('DB_PORT', 3306)), user=os.environ['DB_USER'],
            password=os.environ['DB_PASSWORD'], database=os.environ['DB_NAME'])
        self.addCleanup(self.conn.close)
        cur = self.conn.cursor()
        texts = ['import_id', 'data_texto', 'vendedor_key', 'vendedor_key_upper', 'vendedor_codigo',
                 'vendedor_nome', 'cliente_norm', 'cliente', 'cidade', 'numero_nf', 'produto',
                 'grupo_raw', 'grupo_norm', 'categoria_norm', 'tipo_operacao', 'condicao']
        nums = ['quantidade', 'litros', 'caixas', 'caixa_fisica', 'valor_venda', 'valor_devolvido',
                'bonificacao', 'valor_liquido', 'quantidade_devolvida', 'litro_devolvido', 'caixa_devolvida']
        cur.execute('CREATE TEMPORARY TABLE vendas_relatorio_itens (data_ref DATE, tab_venda INT DEFAULT 1, ' +
                    ', '.join(f"{name} VARCHAR(100) DEFAULT ''" for name in texts) + ', ' +
                    ', '.join(f'{name} DECIMAL(18,3) DEFAULT 0' for name in nums) + ')')
        for date, seller, product, value in [
            ('2026-09-30', 'CLT TESTE', 'COLA PET 2L', 100),
            ('2026-09-30', 'CLT TESTE', 'ASTUBA PET 2L', 50),
            ('2026-10-01', 'Luis Carlos Pires', 'COLA PET 2L', 200),
            ('2026-10-01', 'Norival Vignoto', 'COLA PET 2L', 300),
            ('2026-10-02', 'Luiz Humberto Vignoto', 'ASTUBA PET 2L', 400),
            ('2026-09-30', '001 - BALCÃO', 'COLA PET 2L', 9000),
            ('2026-10-01', '002 - OUTROS', 'ASTUBA PET 2L', 8000),
            ('2026-10-03', 'CLT TESTE', 'COLA PET 2L', 7000),
        ]:
            cur.execute('''INSERT INTO vendas_relatorio_itens
                (import_id, data_ref, vendedor_key, vendedor_key_upper, vendedor_nome,
                 produto, valor_venda, quantidade, litros, grupo_norm, cliente_norm, cliente, cidade, numero_nf)
                VALUES ('test', %s, %s, %s, %s, %s, %s, 10, 20, 'PET 2L', 'CLIENTE A', 'Cliente A', 'Cidade', '123')''',
                (date, seller, seller.upper(), seller, product, value))
        cur.close()
        proxy = mock.Mock()
        proxy.cursor.side_effect = self.conn.cursor
        self.s.get_conn.return_value = proxy
        self.entry = {'id': 'test'}
        self.s._vendas_obter_cache_ativo.return_value = (self.entry, {}, {})
        self.dates = dict(data_inicio='2026-09-30', data_fim='2026-10-02')

    def test_totais_opcoes_e_consultas_das_cinco_abas(self):
        s = self.s
        groups = s._vendas_cabecalho_resumo('test', **self.dates)
        self.assertEqual([1050, 150, 900], [g['valor_venda'] for g in groups])
        self.assertEqual([5, 2, 3], [g['itens'] for g in groups])
        options, _ = s._vendas_periodo_opcoes('test', **self.dates)
        self.assertEqual(4, len(options))
        bonus = s._vendas_bonificacoes_payload(self.entry, {}, {}, mes='2026-09', **self.dates)
        self.assertEqual(1050, bonus['resumo_geral']['valor_venda'])
        self.assertEqual(5, bonus['resumo_geral']['itens'])
        self.assertEqual(groups, bonus['resumo_grupos'])
        filtered = s._vendas_bonificacoes_payload(self.entry, {}, {}, filtro_vendedor='CLT TESTE', **self.dates)
        self.assertEqual(150, filtered['resumo_geral']['valor_venda'])
        variation = s._vendas_coletar_relatorio_variacao_preco_sql(self.entry, {}, {}, **self.dates)
        self.assertEqual(5, variation['resumo_geral']['itens'])
        self.assertEqual([], variation['variacoes'], 'Astuba nao deve criar falsa variacao de PET 2L')
        detail_var = s._vendas_coletar_relatorio_variacao_preco_sql(self.entry, {}, {}, filtro_vendedor='CLT TESTE', **self.dates)
        self.assertEqual({'PET 2L', 'Astuba 2L'}, {row['grupo'] for row in detail_var['detalhes_vendedor']})
        mix = s._vendas_mix_embalagens_payload(self.entry, {}, {}, **self.dates)
        self.assertEqual(1, mix['clientes'][0]['qtd_grupos'])
        self.assertEqual(['PET 2L'], mix['clientes'][0]['grupos'])
        self.assertEqual(5, mix['clientes'][0]['itens'])
        avg = s._coletar_relatorio_vendas_preco_medio(filtro_vendedor='CLT TESTE', **self.dates)
        self.assertEqual({'Pet 2L', 'Astuba 2L'}, set(avg['categorias']))
        detail = next(row for row in avg['precos_medios_vendedor_cidade'] if row['tipo_linha'] != 'resumo_cidade')
        self.assertEqual(10, detail['categorias']['Pet 2L']['preco_medio'])
        self.assertEqual(5, detail['categorias']['Astuba 2L']['preco_medio'])
        annual = s._coletar_relatorio_vendas_percentual_vendas_anual(**self.dates)
        self.assertEqual(4, len(annual['vendedores']))
        self.assertEqual(1, annual['resumo_geral']['total_atual'])

    def test_mes_sem_range_e_range_vazio(self):
        s = self.s
        self.assertEqual([150, 150, 0], [g['valor_venda'] for g in s._vendas_cabecalho_resumo('test', mes='2026-09')])
        dates = dict(data_inicio='2028-01-01', data_fim='2028-01-01')
        self.assertEqual([0, 0, 0], [g['valor_venda'] for g in s._vendas_cabecalho_resumo('test', **dates)])
        self.assertEqual([], s._vendas_mix_embalagens_payload(self.entry, {}, {}, **dates)['clientes'])
