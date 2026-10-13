"""SQL de preços com dados sintéticos em tabela TEMPORARY, sem alterar a base real.

RB_REPORT_TEST_MYSQL=1 habilita integração; DB_* aponta para MariaDB/MySQL.
RB_REPORT_TEST_SOURCE permite testar um server.py ainda não implantado.
"""
import ast
import datetime
from decimal import Decimal
import os
from pathlib import Path
import re
import types
import unittest
import unicodedata
from unittest import mock


def load_server():
    path = Path(os.environ.get('RB_REPORT_TEST_SOURCE') or Path(__file__).resolve().parents[1] / 'server.py')
    names = {'_vendas_precos_cidade_payload', '_vendas_validar_periodo', '_vendas_sql_periodo_where',
             '_vendas_sql_campos_financeiros', '_vendas_sql_categoria_preco_medio_expr',
             '_vendas_sql_vendedores_validos', '_vendas_vendedor_excluido', '_vendas_texto_sem_acentos', '_vendas_publicar_opcoes_relatorio', '_vendas_mes_subtrair', '_as_str', '_as_int',
             '_as_float', '_parse_data_br', '_fmt_date', '_vendas_cabecalho_resumo', '_vendas_periodo_opcoes'}
    nodes = [n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name in names]
    s = types.ModuleType('precos_cidade_test')
    s.__dict__.update(datetime=datetime, Decimal=Decimal, os=os, re=re, unicodedata=unicodedata,
        _vendas_cache_entry_publico=lambda entry:entry,
        _vendas_meses_disponiveis_db=lambda key:['2026-09'],
        _vendas_relatorio_cache_chave=lambda *a,**k:None,
        _vendas_relatorio_cache_obter=lambda key:None,
        _vendas_relatorio_cache_guardar=lambda *a:None)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),s.__dict__)
    return s


class ValidationTest(unittest.TestCase):
    def test_invalid_dates_types_and_incomplete_drilldown_fail_before_database(self):
        s=load_server()
        for args in [dict(data_inicio='bad'),dict(data_inicio='2026-10-02',data_fim='2026-09-01'),
                     dict(detalhe=True),dict(detalhe=True,cidade='C',produto='P')]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                s._vendas_precos_cidade_payload({'id':'test'},{},'variacao_preco',**args)
        with self.assertRaises(ValueError):
            s._vendas_precos_cidade_payload({'id':'test'},{},'bonificacoes')


@unittest.skipUnless(os.environ.get('RB_REPORT_TEST_MYSQL')=='1','SQL real opcional')
class PricesSqlTest(unittest.TestCase):
    def setUp(self):
        import mysql.connector
        self.s=load_server()
        self.conn=mysql.connector.connect(host=os.environ['DB_HOST'],port=int(os.environ.get('DB_PORT',3306)),
            user=os.environ['DB_USER'],password=os.environ['DB_PASSWORD'],database=os.environ['DB_NAME'])
        self.addCleanup(self.conn.close)
        cur=self.conn.cursor()
        texts=['import_id','vendedor_key','vendedor_key_upper','vendedor_nome','vendedor_codigo','cliente_norm',
               'cliente','cidade','produto','grupo_norm','grupo_raw','tipo_operacao','condicao','numero_nf']
        nums=['quantidade','quantidade_devolvida','valor_venda','valor_devolvido','litros','litro_devolvido',
              'caixa_fisica','caixas','caixa_devolvida','bonificacao','valor_liquido']
        cur.execute('CREATE TEMPORARY TABLE vendas_relatorio_itens (data_ref DATE, tab_venda INT DEFAULT 1, '+
                    ','.join(f"{n} VARCHAR(100) DEFAULT ''" for n in texts)+','+
                    ','.join(f'{n} DECIMAL(18,3) DEFAULT 0' for n in nums)+') DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci')
        cur.close()
        proxy=mock.Mock(); proxy.cursor.side_effect=self.conn.cursor
        self.s.get_conn=lambda:proxy
        self.add(cliente='A',quantidade=10,valor_venda=100)
        self.add(cliente='A',quantidade=30,valor_venda=600)
        self.add(cliente='B',quantidade=10,valor_venda=300,vendedor_nome='Luis Carlos Pires',vendedor_key='AUTO',vendedor_key_upper='AUTO')
        self.add(cliente='A',quantidade=0,valor_venda=0,quantidade_devolvida=2,valor_devolvido=20,tipo_operacao='DEV')
        self.add(cliente='APENAS DEV',quantidade=0,valor_venda=0,quantidade_devolvida=3,valor_devolvido=999,tipo_operacao='DEV')
        self.add(cliente='BONUS',tab_venda=91,valor_venda=999)
        self.add(cliente='OUTRA CIDADE',cidade='OUTRA',valor_venda=999)
        self.add(cliente='OUTRO PRODUTO',produto='LARANJA PET 2L',valor_venda=999)
        self.add(cliente='FORA PERIODO',data_ref='2026-10-01',valor_venda=999)
        self.add(cliente='BALCAO',vendedor_nome='001 - BALCÃO',vendedor_key='001 - BALCÃO',vendedor_key_upper='001 - BALCÃO',valor_venda=999)
        self.add(cliente='ASTUBA',produto='ASTUBA PET 2L',valor_venda=50)
        self.add(cliente='OUTRA BASE',import_id='outra',valor_venda=999)
        self.detail=dict(cidade='CIDADE',produto='COLA PET 2L',grupo='PET 2L',detalhe=True)

    def add(self,**values):
        row=dict(import_id='test',data_ref='2026-09-30',vendedor_key='CLT',vendedor_key_upper='CLT',vendedor_nome='CLT TESTE',
                 cliente='A',cidade='CIDADE',produto='COLA PET 2L',grupo_norm='PET 2L',quantidade=10,valor_venda=100)
        row.update(values); row['cliente_norm']=row['cliente']
        cur=self.conn.cursor()
        cur.execute('INSERT INTO vendas_relatorio_itens ('+','.join(row)+') VALUES ('+','.join(['%s']*len(row))+')',tuple(row.values()))
        cur.close()

    def report(self,tipo='variacao_preco',**kwargs):
        return self.s._vendas_precos_cidade_payload({'id':'test'},{},tipo,**kwargs)

    def test_same_pdvs_extrema_weighted_average_returns_and_permissions(self):
        variation=self.report(**self.detail)
        mean=self.report('preco_medio',**self.detail)
        self.assertEqual({'A','B'},{p['chave'] for p in variation['pdvs']})
        self.assertEqual({'A','B'},{p['chave'] for p in mean['pdvs']})
        self.assertEqual((10,30,2),(variation['linhas'][0]['preco_min'],variation['linhas'][0]['preco_max'],variation['linhas'][0]['pdvs']))
        self.assertEqual(round(980/48,2),mean['linhas'][0]['preco_medio'])
        self.assertEqual(round(680/38,2),next(p for p in mean['pdvs'] if p['chave']=='A')['preco_medio'])
        self.assertNotIn('preco_medio',str(variation))
        self.assertNotIn('preco_min',str(mean)); self.assertNotIn('preco_max',str(mean))
        self.assertEqual('2026-09-01',variation['filtros']['data_inicio'])
        self.assertEqual('2026-09-30',variation['filtros']['data_fim'])

    def test_seller_group_dates_empty_and_bound_parameters(self):
        report=self.report(vendedor='CLT',grupo='PET 2L',data_inicio='2026-09-30',data_fim='2026-09-30')
        row=next(r for r in report['linhas'] if r['cidade']=='CIDADE' and r['produto']=='COLA PET 2L')
        self.assertEqual((10,20,1),(row['preco_min'],row['preco_max'],row['pdvs']))
        self.assertIn('Astuba 2L',report['grupos_disponiveis'])
        astuba=self.report(grupo='Astuba 2L')
        self.assertEqual(['ASTUBA PET 2L'],[r['produto'] for r in astuba['linhas']])
        self.assertEqual([50,50,0],[r['valor_venda'] for r in astuba['cabecalho_resumo']])
        self.assertEqual([],self.report(grupo="' OR 1=1 --")['linhas'])
        self.assertEqual([],self.report(data_inicio='2030-01-01')['linhas'])
        partial=self.report(data_fim='2026-09-30')
        self.assertEqual('',partial['filtros']['data_inicio'])
        self.assertTrue(all(r['cidade']!='BALCAO' for r in partial['linhas']))

    def test_detail_matches_summary_under_database_collation(self):
        self.add(cliente='ACENTO',cidade='CÍDADE',produto='CÓLA PET 2L')
        rows=[r for r in self.report()['linhas'] if r['produto'] in {'COLA PET 2L','CÓLA PET 2L'} and r['cidade']!='OUTRA']
        self.assertEqual(2,len(rows))
        self.assertEqual(3,sum(row['pdvs'] for row in rows))
        for row in rows:
            detail=self.report(detalhe=True,**{key:row[key] for key in ['cidade','produto','grupo']})
            self.assertEqual(row['pdvs'],len(detail['pdvs']))
            self.assertEqual(row['preco_min'],detail['linhas'][0]['preco_min'])
            self.assertEqual(row['preco_max'],detail['linhas'][0]['preco_max'])

    def test_zero_missing_and_more_than_legacy_sample_limit(self):
        self.add(cliente='ZERO',valor_venda=0)
        self.add(cliente='SEM QTD',quantidade=0,valor_venda=50)
        self.add(cliente='ZERA SALDO',quantidade=1,valor_venda=10)
        self.add(cliente='ZERA SALDO',quantidade=0,valor_venda=0,quantidade_devolvida=1,valor_devolvido=10)
        for i in range(310): self.add(cliente=f'PDV {i}')
        variation=self.report(**self.detail); mean=self.report('preco_medio',**self.detail)
        self.assertEqual(315,len(mean['pdvs']))
        self.assertEqual(0,variation['linhas'][0]['preco_min'])
        prices={p['chave']:p['preco_medio'] for p in mean['pdvs']}
        self.assertEqual(0,prices['ZERO']); self.assertIsNone(prices['SEM QTD']); self.assertIsNone(prices['ZERA SALDO'])


if __name__=='__main__': unittest.main()
