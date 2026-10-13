"""Relatorio diario e dashboard mensal consultam a mesma fonte operacional."""
import ast
import datetime as dt
import os
from pathlib import Path
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from vendas_report_test_support import load_sales_server
from vendas_diario import volume_item_sql


def load_daily():
    s = load_sales_server()
    names = {'_vendas_diario_consultar', '_vendas_diario_mes_atual',
             '_vendas_diario_preencher_nomes_vendedores', 'vendas_diario_dashboard_api',
             'vendas_diario_relatorio_api'}
    nodes = [n for n in ast.parse(Path(s.__file__).read_text()).body
             if isinstance(n, ast.FunctionDef) and n.name in names]
    for node in nodes:
        node.decorator_list = []
    s.__dict__.update(ZoneInfo=ZoneInfo, volume_item_sql=volume_item_sql)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), s.__file__, 'exec'), s.__dict__)
    return s


class DailyRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from flask import Flask, request, jsonify
        cls.app = Flask(__name__)
        cls.s = load_daily()
        cls.s.__dict__.update(request=request, jsonify=jsonify)

    def test_current_month_uses_sao_paulo_including_year_boundary(self):
        for now, inicio, fim in [(dt.datetime(2026, 9, 29), dt.date(2026, 9, 1), dt.date(2026, 9, 30)),
                                (dt.datetime(2026, 12, 31), dt.date(2026, 12, 1), dt.date(2026, 12, 31)),
                                (dt.datetime(2028, 2, 29), dt.date(2028, 2, 1), dt.date(2028, 2, 29))]:
            with mock.patch.object(self.s.datetime, 'datetime', wraps=dt.datetime) as clock:
                clock.now.return_value = now
                self.assertEqual((inicio, fim), self.s._vendas_diario_mes_atual())
                self.assertEqual('America/Sao_Paulo', str(clock.now.call_args.args[0]))

    def test_dashboard_ignores_historical_dates_and_report_accepts_them(self):
        with mock.patch.object(self.s, '_vendas_diario_mes_atual', return_value=(dt.date(2026, 9, 1), dt.date(2026, 9, 30))), \
             mock.patch.object(self.s, '_vendas_diario_consultar', return_value={}) as query:
            with self.app.test_request_context('/?data_inicio=2020-01-01&data_fim=2020-01-02'):
                self.s.vendas_diario_dashboard_api()
            self.assertEqual((dt.date(2026, 9, 1), dt.date(2026, 9, 30), ''), query.call_args.args)
            with self.app.test_request_context('/?data_inicio=2020-01-01&data_fim=2020-01-02&vendedor=1'):
                self.s.vendas_diario_relatorio_api()
            self.assertEqual((dt.date(2020, 1, 1), dt.date(2020, 1, 2), '', '1'), query.call_args.args)
            self.assertEqual({'por_dia': True}, query.call_args.kwargs)
            with self.app.test_request_context('/?data_inicio=2020-01-02&data_fim=2020-01-01'):
                self.assertEqual(400, self.s.vendas_diario_relatorio_api()[1])


@unittest.skipUnless(os.environ.get('RB_REPORT_TEST_MYSQL') == '1', 'SQL real opcional')
class DailySqlTest(unittest.TestCase):
    def setUp(self):
        import mysql.connector
        self.s = load_daily()
        self.conn = mysql.connector.connect(host=os.environ['DB_HOST'], user=os.environ['DB_USER'],
            password=os.environ['DB_PASSWORD'], database=os.environ['DB_NAME'])
        self.addCleanup(self.conn.close)
        cur = self.conn.cursor()
        schemas = {
            'vendas_diario_importacoes': 'id INT, arquivo_nome VARCHAR(100)',
            'vendas_diario_pedidos': '''id INT, importacao_id INT, data_ref DATE, vendedor_codigo VARCHAR(20),
                cliente_codigo VARCHAR(20), cliente_nome VARCHAR(100), fantasia VARCHAR(100), cidade VARCHAR(100),
                status VARCHAR(20), valor_total DECIMAL(18,2)''',
            'vendas_diario_itens': '''pedido_id INT, tabela_venda INT, quantidade DECIMAL(18,3), valor_unitario DECIMAL(18,2),
                produto_codigo VARCHAR(30), unidade VARCHAR(20), descricao VARCHAR(100)''',
            'vendas_diario_kanban': '''id INT, importacao_id INT, vendedor_codigo VARCHAR(20),
                origem_tipo VARCHAR(20), status VARCHAR(20), card_principal_id INT''',
            'comissao_cadastros': 'codigo INT, nome VARCHAR(100), funcao VARCHAR(30), ativo INT',
        }
        for name, columns in schemas.items():
            cur.execute(f'CREATE TEMPORARY TABLE {name} ({columns})')
        for code, name in [(1, 'CLT teste'), (2, 'Luis Carlos Pires'), (3, 'Balcão'), (4, 'Outros')]:
            cur.execute("INSERT INTO comissao_cadastros VALUES (%s,%s,'vendedor',1)", (code, name))
        for id, date, seller, value, origin, status in [
            (1,'2026-09-01','1',100,'txt','importado'),
            (2,'2026-09-30','1',200,'txt','importado'),
            (3,'2026-09-30','2',300,'txt','importado'),
            (4,'2026-08-31','1',400,'txt','importado'),
            (5,'2026-10-01','1',500,'txt','importado'),
            (6,'2026-09-30','3',9000,'txt','importado'),
            (7,'2026-09-30','4',8000,'txt','importado'),
            (8,'2026-09-30','1',7000,'pdf','importado'),
            (9,'2026-09-30','2',6000,'txt','excluido')]:
            cur.execute('INSERT INTO vendas_diario_importacoes VALUES (%s,%s)', (id, f'{id}.{origin}'))
            cur.execute("INSERT INTO vendas_diario_pedidos VALUES (%s,%s,%s,%s,%s,%s,'','Cidade','positiva',%s)",
                        (id,id,date,seller,str(id),f'Cliente {id}',value))
            cur.execute('INSERT INTO vendas_diario_kanban VALUES (%s,%s,%s,%s,%s,NULL)', (id,id,seller,origin,status))
            cur.execute("INSERT INTO vendas_diario_itens VALUES (%s,1,10,10,'1','PC','COLA PET 2L')",(id,))
        cur.execute("INSERT INTO vendas_diario_itens VALUES (1,91,2,5,'1','PC','ASTUBA 2L')")
        cur.close()
        proxy = mock.Mock()
        proxy.cursor.side_effect = self.conn.cursor
        self.s.get_conn.return_value = proxy

    def test_current_month_totals_and_daily_history_preserve_sources(self):
        dashboard = self.s._vendas_diario_consultar(dt.date(2026,9,1),dt.date(2026,9,30))
        self.assertEqual(600, dashboard['resumo']['valor_bruto'])
        self.assertEqual(10, dashboard['resumo']['valor_bonificacao'])
        self.assertEqual(590, dashboard['resumo']['valor_liquido'])
        self.assertEqual(2, len(dashboard['vendedores']))
        self.assertEqual([600,300,300], [row['valor_venda'] for row in dashboard['cabecalho_resumo']])
        self.assertEqual({'1','2','3'}, {row['chave'] for row in dashboard['clientes_disponiveis']})
        self.assertEqual(['1.txt','2.txt','3.txt'], dashboard['arquivo']['nomes'])
        daily = self.s._vendas_diario_consultar(dt.date(2026,8,31),dt.date(2026,10,1),por_dia=True)
        self.assertEqual(1500, daily['resumo']['valor_bruto'])
        self.assertEqual(5, len(daily['vendedores']))
        self.assertEqual(2, daily['resumo']['vendedores'])
        filtered = self.s._vendas_diario_consultar(dt.date(2026,9,1),dt.date(2026,9,30),filtro_vendedor='2',por_dia=True)
        self.assertEqual(300, filtered['resumo']['valor_bruto'])
        customer = self.s._vendas_diario_consultar(dt.date(2026,9,1),dt.date(2026,9,30),filtro_cliente='1',por_dia=True)
        self.assertEqual(100, customer['resumo']['valor_bruto'])
        empty = self.s._vendas_diario_consultar(dt.date(2027,1,1),dt.date(2027,1,31),por_dia=True)
        self.assertEqual(0, empty['resumo']['valor_bruto'])
