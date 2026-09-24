"""Regressoes de resultados e cache; SQL real usa apenas tabela temporaria."""
import datetime as dt
from decimal import Decimal
import os
import unittest
from unittest import mock

from vendas_report_test_support import load_sales_server


class CacheVendasTest(unittest.TestCase):
    def setUp(self):
        self.s = load_sales_server()
        self.s._vendas_db_fetch_import.return_value = {'source_signature': 'a', 'rows_importadas': 10}

    def test_cache_compacto_dura_uma_hora_mas_respeita_nova_importacao(self):
        s = self.s
        with mock.patch.object(s.time, 'time', return_value=1000):
            key = s._vendas_relatorio_cache_chave('bonificacoes', 'sellout-mensal-continuo')
            s._vendas_relatorio_cache_guardar(key, {'total': 10})
        with mock.patch.object(s.time, 'time', return_value=1600):
            self.assertEqual({'total': 10}, s._vendas_relatorio_cache_obter(key))
            s._vendas_db_fetch_import.return_value = {'source_signature': 'b', 'rows_importadas': 10}
            changed = s._vendas_relatorio_cache_chave('bonificacoes', 'sellout-mensal-continuo')
            self.assertIsNone(s._vendas_relatorio_cache_obter(changed))
        with mock.patch.object(s.time, 'time', return_value=4601):
            self.assertIsNone(s._vendas_relatorio_cache_obter(key))

    def test_linhas_brutas_e_importacoes_legadas_continuam_com_ttl_curto(self):
        s = self.s
        for tipo, cache_id in [('base_rows', 'sellout-mensal-continuo'), ('bonificacoes', 'legado')]:
            key = s._vendas_relatorio_cache_chave(tipo, cache_id)
            with mock.patch.object(s.time, 'time', return_value=1000):
                s._vendas_relatorio_cache_guardar(key, {'rows': []})
            with mock.patch.object(s.time, 'time', return_value=1301):
                self.assertIsNone(s._vendas_relatorio_cache_obter(key))

    def test_limite_lru_e_limpeza_por_importacao(self):
        s = self.s
        s._VENDAS_RELATORIO_CACHE_MAX = 2
        keys = [s._vendas_relatorio_cache_chave('bonificacoes', 'legado', mes=str(n)) for n in range(3)]
        for key in keys[:2]:
            s._vendas_relatorio_cache_guardar(key, {'ok': True})
        s._vendas_relatorio_cache_obter(keys[0])
        s._vendas_relatorio_cache_guardar(keys[2], {'ok': True})
        self.assertIsNone(s._vendas_relatorio_cache_obter(keys[1]))
        self.assertIsNotNone(s._vendas_relatorio_cache_obter(keys[0]))
        s._vendas_relatorio_cache_limpar('legado')
        self.assertEqual({}, s._VENDAS_RELATORIO_CACHE)


@unittest.skipUnless(os.environ.get('RB_REPORT_TEST_MYSQL') == '1', 'SQL real opcional: RB_REPORT_TEST_MYSQL=1')
class AnualSqlTest(unittest.TestCase):
    def setUp(self):
        import mysql.connector
        self.s = load_sales_server()
        self.conn = mysql.connector.connect(host=os.environ['DB_HOST'],
            port=int(os.environ.get('DB_PORT', 3306)), user=os.environ['DB_USER'],
            password=os.environ['DB_PASSWORD'], database=os.environ.get('DB_NAME', 'riobranco'))
        self.addCleanup(self.conn.close)
        cur = self.conn.cursor()
        # Sombreia o nome apenas nesta conexao; nenhuma tabela persistente muda.
        cur.execute('''CREATE TEMPORARY TABLE vendas_relatorio_itens (
            import_id VARCHAR(64), data_ref DATE, vendedor_key VARCHAR(80),
            vendedor_key_upper VARCHAR(80), vendedor_codigo VARCHAR(20), vendedor_nome VARCHAR(80),
            cliente_norm VARCHAR(80), cliente VARCHAR(80), caixa_fisica DECIMAL(18,3),
            caixas DECIMAL(18,3), quantidade DECIMAL(18,3), litros DECIMAL(18,3), tab_venda INT
        )''')
        self.rows = []
        for date, seller, client, litres, tab in [
            ('2025-01-01', 'VENDEDOR 1', 'CLIENTE A', '100', 1),
            ('2026-01-01', 'VENDEDOR 1', 'CLIENTE A', '.15', 1),
            ('2026-01-01', 'VENDEDOR 1', 'CLIENTE A', '.15', 1),
            ('2026-01-01', 'VENDEDOR 1', 'CLIENTE A', '.35', 1),
            ('2026-01-01', 'VENDEDOR 1', 'CLIENTE A', '-.15', 1),
            ('2026-02-15', 'VENDEDOR 2', 'CLIENTE B', '200', 2),
            ('2026-09-01', 'VENDEDOR 2', 'CLIENTE B', '10000', 91),
            ('2025-12-01', 'VENDEDOR 1', 'CLIENTE A', '9000', 1),
            ('2024-01-01', 'VENDEDOR 1', 'CLIENTE A', '9000', 1),
            (None, 'VENDEDOR 3', 'CLIENTE C', '9000', 1),
        ]:
            row = dict(data_ref=dt.date.fromisoformat(date) if date else None,
                vendedor_key=seller, vendedor_key_upper=seller, vendedor_codigo=seller[-1],
                vendedor_nome=seller, cliente_norm=client, chave=client, cliente=client,
                caixa_fisica=Decimal('0'), caixas=Decimal('2'), quantidade=Decimal('24'),
                litros=Decimal(litres), tab_venda=tab)
            self.rows.append(row)
            cur.execute('INSERT INTO vendas_relatorio_itens VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                ('teste', row['data_ref'], seller, seller, seller[-1], seller, client, client, 0, 2, 24, litres, tab))
        cur.close()
        # Permite varias consultas da funcao real sobre a mesma tabela temporaria.
        proxy = mock.Mock()
        proxy.cursor.side_effect = self.conn.cursor
        self.s.get_conn.return_value = proxy

    def test_sql_preserva_volume_por_item_filtros_e_referencia_independente(self):
        s = self.s
        for seller, client, inicio, fim in [('', '', None, None),
            ('VENDEDOR 1', '', None, None), ('', 'CLIENTE B', None, None),
            ('VENDEDOR 1', 'CLIENTE A', None, None), ('VENDEDOR 1', 'CLIENTE B', None, None),
            ('', '', '2025-01-01', '2026-02-15'), ('', '', '2027-01-01', '2027-12-31')]:
            with self.subTest(seller=seller, client=client, inicio=inicio, fim=fim):
                rows = [r for r in self.rows if
                    (not inicio or (r['data_ref'] and r['data_ref'] >= dt.date.fromisoformat(inicio))) and
                    (not fim or (r['data_ref'] and r['data_ref'] <= dt.date.fromisoformat(fim)))]
                ref = max((r['data_ref'] for r in rows if r['data_ref']), default=dt.date.today())
                expected = s._vendas_comparativo_anual(s._vendas_rows_filtradas_base(rows, seller, client), referencia=ref)
                compact, reference, vendors, customers = s._vendas_anual_consultar_sql('teste', seller, client, inicio, fim)
                actual = s._vendas_comparativo_anual(compact, referencia=reference)
                self.assertEqual(expected, actual)
                expected_vendors, expected_customers = s._vendas_publicar_opcoes_relatorio(rows)
                self.assertEqual(expected_vendors, vendors)
                self.assertEqual(expected_customers, customers)
                self.assertLessEqual(len(compact), 24)

    def test_opcoes_sao_reutilizadas_ao_trocar_vendedor(self):
        s = self.s
        first = s._vendas_anual_consultar_sql('teste')
        second = s._vendas_anual_consultar_sql('teste', 'VENDEDOR 1')
        self.assertEqual(first[1:], second[1:])
        self.assertEqual(3, len(second[3]))


if __name__ == '__main__':
    unittest.main()
