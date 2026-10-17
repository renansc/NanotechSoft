import io
import json
import unittest
from unittest import mock
from flask import Flask
import vendas_pdvs as pdvs
from vendas_report_test_support import load_sales_server

SELLERS = [{'chave':'006 - VINICIUS','codigo':'006','nome':'VINICIUS'},
           {'chave':'020 - ALEXSANDER','codigo':'020','nome':'ALEXSANDER'},
           {'chave':'011 - RICARDO','codigo':'011','nome':'RICARDO'},
           {'chave':'022 - RICARDO','codigo':'022','nome':'RICARDO'}]
TEXT = '''COBERTURA VENDEDOR/SUPERV.
Total Clientes C/Compra Negativos
  1507 ARAPONGAS                 179 146 33 81,56 291,8340
     6 VINICIUS                  408 335 73 82,11 831,3996
    20 ALEX SANDER               458 63 395 13,76 292,6500
    22 RICARDO                   434 309 125 71,20 948,5112
       Total                   1.300 707 593 54,38 0,0000
'''


class PdvsTest(unittest.TestCase):
    def test_pdf_coverage_uses_total_not_bought_city_or_grand_total(self):
        rows = pdvs.interpretar_texto(TEXT, SELLERS)
        self.assertEqual([408,458,434], [r['total'] for r in rows])
        self.assertEqual([335,63,309], [r['com_compra_pdf'] for r in rows])
        self.assertEqual('022 - RICARDO', rows[-1]['vendedor_key'])
        self.assertEqual('020 - ALEXSANDER', rows[1]['vendedor_key'])
        with self.assertRaises(ValueError): pdvs.interpretar_texto(TEXT.replace('408 335 73','400 335 73'), SELLERS)
        with self.assertRaises(ValueError): pdvs.interpretar_texto('texto qualquer', SELLERS)

    def test_validation_zero_duplicates_and_wrong_sellers(self):
        self.assertEqual(0, pdvs.validar_itens([{'vendedor_key':SELLERS[0]['chave'],'total':'0'}],SELLERS)[0]['total'])
        for value in [-1,1.5,True,'1,5','NaN',None,10000001]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                pdvs.validar_itens([{'vendedor_key':SELLERS[0]['chave'],'total':value}],SELLERS)
        for rows in [[{'vendedor_key':'desconhecido','total':1}],
                     [{'vendedor_key':SELLERS[0]['chave'],'total':1}]*2]:
            with self.assertRaises(ValueError): pdvs.validar_itens(rows,SELLERS)

    def test_percentage_uses_full_portfolio_and_missing_is_pending(self):
        server = load_sales_server()
        clients = [{'qtd_grupos':6,'grupos':['PET 2L']}]*8
        summary, bands = server._vendas_mix_embalagens_resumo(clients,400)
        self.assertEqual(8,summary['pdvs']); self.assertEqual(400,summary['total_carteira'])
        self.assertEqual(2,bands[0]['percentual'])
        for total in [None,0]:
            _, bands = server._vendas_mix_embalagens_resumo(clients,total)
            self.assertIsNone(bands[0]['percentual'])
        _, bands = server._vendas_mix_embalagens_resumo(clients,800)
        self.assertEqual(1,bands[0]['percentual'])

    def test_identity_and_scope_preserve_full_denominator(self):
        totals = [{'vendedor_key':'020 - ALEXSANDER','total':458}]
        self.assertEqual((458,[]),pdvs.base_carteira(totals,SELLERS,'020 - ALEX SANDER'))
        self.assertEqual((None,['006 - VINICIUS']),pdvs.base_carteira(totals,SELLERS,'006 - VINICIUS'))
        total, missing = pdvs.base_carteira(totals,SELLERS)
        self.assertIsNone(total); self.assertIn('022 - RICARDO',missing)
        aliases = [{'chave':'020 - ALEX SANDER'},{'chave':'020 - ALEXSANDER'}]
        self.assertEqual((458,[]),pdvs.base_carteira(totals,aliases))

    def test_partial_portfolio_displays_imported_total_without_using_partial_denominator(self):
        totals = [{'vendedor_key':f'{i:03} - VENDEDOR {i}', 'total':n} for i,n in
                  [(6,408),(7,455),(8,462),(9,448),(15,499),(16,237),(17,448),(18,448),(20,458),(22,434)]]
        sellers = [{'chave':r['vendedor_key']} for r in totals] + [{'chave':'012 - NORIVAL VIGNOTO'}]
        result = pdvs.resumo_carteira(totals,sellers)
        self.assertEqual(4297,result['total_carteira_importada'])
        self.assertIsNone(result['total_carteira'])
        self.assertEqual(['012 - NORIVAL VIGNOTO'],result['carteiras_pendentes'])
        self.assertEqual(408,pdvs.resumo_carteira(totals,sellers,'006 - VINICIUS')['total_carteira'])
        multi = pdvs.resumo_carteira(totals, sellers, ['006 - VINICIUS', '020 - ALEXSANDER'])
        self.assertEqual(866, multi['total_carteira'])
        self.assertEqual(866, multi['total_carteira_importada'])
        self.assertIsNone(pdvs.resumo_carteira(totals,sellers,'012 - NORIVAL VIGNOTO')['total_carteira_importada'])
        self.assertEqual(4297,pdvs.resumo_carteira(totals,sellers[:-1])['total_carteira'])
        self.assertIsNone(pdvs.resumo_carteira([],sellers)['total_carteira_importada'])
        self.assertEqual(0,pdvs.resumo_carteira([{'vendedor_key':'006 - VINICIUS','total':0}],[],
                                             '006 - VINICIUS')['total_carteira_importada'])
        duplicate = [{'vendedor_key':'020 - ALEX SANDER','total':458},
                     {'vendedor_key':'020 - ALEXSANDER','total':458}]
        self.assertEqual(458,pdvs.resumo_carteira(duplicate,[])['total_carteira_importada'])

    def test_revision_in_all_report_cache_keys(self):
        server = load_sales_server()
        with mock.patch.object(server.vendas_pdvs,'revisao',side_effect=[('a',400,1),('a',800,2)]):
            a = server._vendas_relatorio_cache_chave('grupos_embalagem','base')
            b = server._vendas_relatorio_cache_chave('grupos_embalagem','base')
        self.assertNotEqual(a,b)

    def test_routes_authorization_confirmation_conflict_and_rollback(self):
        app = Flask(__name__)
        conn = mock.Mock(); cur = conn.cursor.return_value
        cur.fetchall.return_value = []
        connect = mock.Mock(return_value=conn); invalidate = mock.Mock()
        pdvs.register_pdvs(app,{'get_conn':connect,'actor':lambda:'Teste','vendedores':lambda:SELLERS,'invalidate':invalidate})
        client = app.test_client()
        for headers, status in [({},401),({'X-Usuario-Id':'42','X-Usuario-Recursos':'vendas'},403),
                                 ({'X-Usuario-Id':'42','X-Usuario-Recursos':'vendas_pdvs'},200)]:
            self.assertEqual(status,client.get('/api/vendas/pdvs-totais',headers=headers).status_code)
        headers = {'X-Usuario-Id':'42','X-Usuario-Recursos':'vendas_pdvs'}
        def upload():
            return {'arquivo':(io.BytesIO(b'%PDF-test'),'teste.pdf'),
                    'itens':json.dumps([{'vendedor_key':SELLERS[0]['chave'],'total':400}]),'anteriores':'{}'}
        with mock.patch.object(pdvs,'ler_pdf',return_value=(b'%PDF-test',TEXT)):
            conn.reset_mock()
            response = client.post('/api/vendas/pdvs-totais/conferir',headers=headers,data=upload())
            self.assertEqual(200,response.status_code); conn.commit.assert_not_called()
            cur.lastrowid = 10
            response = client.post('/api/vendas/pdvs-totais',headers=headers,data=upload())
            self.assertEqual(200,response.status_code); conn.commit.assert_called_once(); invalidate.assert_called_once()
            values = cur.execute.call_args_list[-1].args[1]
            self.assertEqual(('6','006 - VINICIUS',400,10),values)
            cur.fetchall.return_value = [{'vendedor_key':'006 - VINICIUS','total':500,'importacao_id':11}]
            self.assertEqual(409,client.post('/api/vendas/pdvs-totais',headers=headers,data=upload()).status_code)
            conn.rollback.assert_called()
            cur.fetchall.return_value = []
            cur.execute.side_effect = RuntimeError('synthetic failure')
            conn.reset_mock()
            self.assertEqual(500,client.post('/api/vendas/pdvs-totais',headers=headers,data=upload()).status_code)
            conn.rollback.assert_called_once(); conn.commit.assert_not_called()


if __name__ == '__main__': unittest.main()
