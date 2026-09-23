import json
import sqlite3
import unittest
import test_custo_produto as produto_tests


class CustoDiarioTests(unittest.TestCase):
    def setUp(self):
        self.fixture=produto_tests.CustoProdutoTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.client=self.fixture.client
        self.headers={**self.fixture.headers,'X-Usuario-Recursos':'custo_diario'}
        self.read_headers=self.fixture.dashboard_headers
        self.sql('''CREATE TABLE custo_diario_lancamentos(data_ref TEXT PRIMARY KEY,dados_json TEXT,resultado_json TEXT,revisao INTEGER DEFAULT 1,atualizado_por TEXT,atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP);
          CREATE TABLE estoque_grupos(codigo TEXT PRIMARY KEY,nome TEXT);
          INSERT INTO estoque_grupos VALUES('PET','PET'),('GFA','Retornavel'),('INSUMOS','Materia prima');
          CREATE TABLE estoque_contagens(id INTEGER PRIMARY KEY,status TEXT,finalizado_em TEXT);
          CREATE TABLE estoque_contagem_resultados(id INTEGER PRIMARY KEY,contagem_id INTEGER,produto_id INTEGER,nome_produto TEXT,desperdicio NUMERIC);
        ''')
        self.fixture.save();self.fixture.save(2,produto_tests.formula('600',dose='200'))
        self.url='/api/custo-diario?data=2026-09-22'

    def sql(self,text):
        c=sqlite3.connect(self.fixture.path);c.executescript(text);c.commit();c.close()

    def payload(self):
        return {'revisao':0,'dados':{'producao':[
            {'produto_id':1,'embalagens':500,'por_pacote':6,'volume_ml':2000},
            {'produto_id':2,'embalagens':1000,'por_pacote':24,'volume_ml':600}],
            'despesas':[{'grupo':'','setor':'Geral','descricao':'Pessoal do dia','categoria':'pessoal','valor':160},
                        {'grupo':'PET','setor':'Producao','descricao':'Energia','categoria':'energia','valor':50}]}}

    def save(self,payload=None):
        return self.client.put(self.url,json=payload or self.payload(),headers=self.headers)

    def dashboard(self):
        return self.client.get('/api/custo-diario/dashboard?data=2026-09-22',headers=self.read_headers).json

    def test_real_litres_allocate_shared_and_group_expenses_and_packages(self):
        response=self.save();self.assertEqual(200,response.status_code,response.json)
        rows={r['produto_id']:r for r in response.json['resultado']['produtos']}
        # 500 PET de 2 L: formula 540, pessoal 100, energia 50 = 690.
        self.assertEqual(690,rows[1]['total'])
        self.assertEqual(1.38,rows[1]['por_unidade']['embalagens']['total'])
        self.assertEqual(8.28,rows[1]['por_unidade']['pacotes']['total'])
        self.assertEqual(.69,rows[1]['por_unidade']['litros']['total'])
        # 1000 retornaveis de 600 ml: formula 624 + pessoal 60 = 684.
        self.assertEqual(684,rows[2]['total'])
        self.assertEqual(1374,response.json['resultado']['resumo']['total'])

    def test_finalized_shortfalls_only_and_dynamic_counts_without_double_stock_post(self):
        self.save()
        self.sql("""INSERT INTO estoque_contagens VALUES(1,'finalizada','2026-09-22 09:00:00'),(2,'conferida',NULL),(3,'finalizada','2026-09-21 10:00:00');
          INSERT INTO estoque_contagem_resultados VALUES(1,1,1,'Uva PET',10),(2,1,6,'Acucar',2),(3,2,1,'Rascunho',500),(4,3,1,'Ontem',500),(5,1,1,'Sem falta',0);
        """)
        result=self.dashboard()['resultado'];rows={r['produto_id']:r for r in result['produtos']}
        # 10 embalagens PET * 1.08, mais 2 kg de acucar * 5 rateado 1000/1600.
        self.assertAlmostEqual(17.05,rows[1]['componentes']['desperdicio'])
        self.assertAlmostEqual(3.75,rows[2]['componentes']['desperdicio'])
        self.assertEqual(2,len(result['perdas']))
        self.assertEqual(result,self.dashboard()['resultado'])
        self.assertEqual(1,self.dashboard()['revisao'])

    def test_formula_snapshot_does_not_change_when_recipe_is_edited(self):
        self.save();before=self.dashboard()['resultado']
        self.fixture.base(50)
        after=self.dashboard()['resultado']
        self.assertEqual(before,after)
        data=self.payload();data['revisao']=1
        updated=self.save(data)
        self.assertGreater(updated.json['resultado']['resumo']['total'],before['resumo']['total'])

    def test_shortfall_without_price_keeps_total_pending(self):
        self.sql("INSERT INTO estoque_contagens VALUES(1,'finalizada','2026-09-22 09:00:00'); INSERT INTO estoque_contagem_resultados VALUES(1,1,9,'Aroma',2);")
        response=self.save()
        self.assertIsNone(response.json['resultado']['resumo']['total'])
        self.assertIsNone(response.json['resultado']['produtos'][0]['componentes']['desperdicio'])
        self.assertTrue(response.json['resultado']['produtos'][0]['pendencias'])

    def test_no_production_keeps_expenses_unallocated_and_no_division_by_zero(self):
        data=self.payload();data['dados']['producao']=[]
        response=self.save(data)
        self.assertEqual(200,response.status_code)
        result=response.json['resultado']
        self.assertIsNone(result['resumo']['total']);self.assertEqual(2,len(result['nao_rateado']))
        self.assertIsNone(result['resumo']['por_unidade']['litros']['total'])

    def test_counts_are_visible_even_without_daily_entry(self):
        self.sql("INSERT INTO estoque_contagens VALUES(1,'finalizada','2026-09-22 09:00:00'); INSERT INTO estoque_contagem_resultados VALUES(1,1,1,'PET',10);")
        result=self.dashboard();self.assertEqual(0,result['revisao'])
        self.assertEqual(1,len(result['resultado']['perdas']))
        self.assertIsNone(result['resultado']['resumo']['total'])

    def test_revision_validation_and_manual_loss_blocked(self):
        self.assertEqual(200,self.save().status_code)
        self.assertEqual(409,self.save().status_code)
        data=self.payload();data['revisao']=1;data['dados']['perdas']=[{'valor':100}]
        self.assertEqual(400,self.save(data).status_code)
        for key,value in [('embalagens',0),('por_pacote',0),('volume_ml','NaN'),('embalagens',1.5),('produto_id',999)]:
            data=self.payload();data['revisao']=1;data['dados']['producao'][0][key]=value
            self.assertEqual(400,self.save(data).status_code)
        self.assertEqual(1,self.dashboard()['revisao'])

    def test_day_cutoff_and_separate_permissions(self):
        for headers,status in [({},401),(self.read_headers,403),(self.fixture.headers,403),(self.headers,200)]:
            self.assertEqual(status,self.client.get(self.url,headers=headers).status_code)
        self.assertEqual(403,self.client.put(self.url,json=self.payload(),headers=self.read_headers).status_code)
        self.assertEqual(403,self.client.get('/api/custo-diario/dashboard',headers=self.headers).status_code)
        self.assertEqual(400,self.client.get('/api/custo-diario?data=2099-01-01',headers=self.headers).status_code)
        self.url='/api/custo-diario?data=2026-01-15'
        response=self.save();rows={r['produto_id']:r for r in response.json['resultado']['produtos']}
        self.assertEqual(440,rows[1]['componentes']['formula'])


if __name__=='__main__':unittest.main()
