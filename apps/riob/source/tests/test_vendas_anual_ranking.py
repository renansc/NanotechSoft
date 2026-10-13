"""Comparação e detalhamento anuais em tabelas temporárias, sem dados reais."""
import datetime as dt
import os
import unittest
from unittest import mock
import test_vendas_relatorios_performance as performance


@unittest.skipUnless(os.environ.get('RB_REPORT_TEST_MYSQL') == '1', 'SQL real opcional')
class RankingSqlTest(performance.AnualSqlTest):
    def setUp(self):
        super().setUp()
        cur=self.conn.cursor()
        cur.execute("ALTER TABLE vendas_relatorio_itens ADD id BIGINT PRIMARY KEY AUTO_INCREMENT, ADD numero_nf VARCHAR(80) DEFAULT '', ADD produto VARCHAR(255) DEFAULT '', ADD valor_venda DECIMAL(18,2) DEFAULT 0")
        cur.close()

    def test_ranking_vendedores_clientes_total_e_janela_sao_os_do_comparativo(self):
        for seller, customer, start, end in [('', '', None, None), ('VENDEDOR 1', '', None, None),
                ('VENDEDOR 2', 'CLIENTE B', None, None), ('VENDEDOR 1','CLIENTE B',None,None),
                ('','', '2025-01-01','2026-02-15'),('VENDEDOR 1','','2026-01-01','2026-01-01')]:
            with self.subTest(seller=seller,customer=customer,start=start,end=end):
                rows,ref,_,_=self.s._vendas_anual_consultar_sql('teste',seller,customer,start,end)
                expected=self.s._vendas_comparativo_anual(rows,referencia=ref)['resumo']
                rank=self.s._vendas_anual_ranking_sql('teste',ref,seller,customer,start,end)
                for field in ['total_atual','total_anterior','diferenca_volume']:
                    self.assertAlmostEqual(expected[field],sum(r[field] for r in rank),places=3)
                self.assertTrue(all(r['tipo']==('cliente' if seller else 'vendedor') for r in rank))
                for row in rank:
                    vendas=self.s._vendas_anual_vendas_sql('teste',ref,
                        cliente=row['chave'] if seller else customer,
                        vendedor=seller or row['chave'],data_inicio=start,data_fim=end)
                    self.assertEqual(row['itens'],len(vendas['vendas']))
                    self.assertAlmostEqual(row['total_atual']+row['total_anterior'],sum(v['volume'] for v in vendas['vendas']),places=3)
        rank=self.s._vendas_anual_ranking_sql('teste',dt.date(2026,9,1))
        self.assertNotIn('VENDEDOR 3',[r['chave'] for r in rank])
        self.assertNotIn(90,[r['total_anterior'] for r in rank], 'Dezembro do ano anterior não é perda em setembro')

    def test_clientes_restritos_mesmo_com_cache_e_filtro_de_outro_cliente(self):
        for seller, expected in [('',{'CLIENTE A','CLIENTE B','CLIENTE C'}),('VENDEDOR 1',{'CLIENTE A'}),
                                 ('VENDEDOR 2',{'CLIENTE B'}),('INEXISTENTE',set())]:
            rows,ref,vendors,customers=self.s._vendas_anual_consultar_sql('teste',seller,'CLIENTE C')
            self.assertEqual(expected,{c['chave'] for c in customers})
            self.assertEqual(3,len(vendors))
            self.assertEqual(2026,ref.year)

    def test_queda_sem_base_negativos_e_paginacao_sem_duplicar(self):
        cur=self.conn.cursor()
        for i in range(205):
            cur.execute("""INSERT INTO vendas_relatorio_itens
                (import_id,data_ref,vendedor_key,vendedor_key_upper,vendedor_nome,cliente,cliente_norm,litros,tab_venda,valor_venda,numero_nf,produto)
                VALUES ('teste','2026-03-01','VENDEDOR 4','VENDEDOR 4','VENDEDOR 4','CLIENTE D','CLIENTE D',100,1,5,%s,'COLA')""",(str(i),))
        cur.execute("""INSERT INTO vendas_relatorio_itens
                (import_id,data_ref,vendedor_key,vendedor_key_upper,vendedor_nome,cliente,cliente_norm,litros,tab_venda)
                VALUES ('teste','2025-03-01','VENDEDOR 4','VENDEDOR 4','VENDEDOR 4','CLIENTE D','CLIENTE D',30000,1)""")
        cur.close()
        rank=self.s._vendas_anual_ranking_sql('teste',dt.date(2026,9,1),'VENDEDOR 4')
        self.assertEqual(-95,rank[0]['diferenca_volume'])
        self.assertEqual(1025,rank[0]['venda_atual'])
        pages=[self.s._vendas_anual_vendas_sql('teste',dt.date(2026,9,1),'CLIENTE D','VENDEDOR 4',pagina=n) for n in [1,2,3]]
        self.assertEqual([100,100,6],[len(p['vendas']) for p in pages])
        self.assertEqual([True,True,False],[p['tem_proxima'] for p in pages])
        self.assertEqual(206,len({v['numero_nf'] for p in pages for v in p['vendas']}))
        for page in ['-1','x',0,100001]:
            with self.assertRaises(ValueError):
                self.s._vendas_anual_vendas_sql('teste',dt.date(2026,9,1),'CLIENTE D',pagina=page)
        with self.assertRaises(ValueError):
            self.s._vendas_anual_vendas_sql('teste',dt.date(2026,9,1))
        self.assertEqual([],self.s._vendas_anual_ranking_sql('teste',dt.date(2026,9,1),"' OR 1=1 --"))


if __name__ == '__main__': unittest.main()
