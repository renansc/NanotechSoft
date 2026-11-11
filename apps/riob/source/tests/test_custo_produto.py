import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock
from flask import Flask
from custo_produto import register_custo_produto, calcular_formula, volume_sugerido
from custo_produto_compras import assinatura_preforma, assinatura_rotulo, carregar_compras, embalagem_compativel, fator_item, precificar_item, unidade, ultimas_compras


class Cursor:
    def __init__(self, owner): self.owner=owner;self.raw=owner.raw.cursor()
    def execute(self, sql, args=()):
        if self.owner.fail and ('UPDATE custo_produto_formulas' in sql or 'DELETE FROM custo_produto_formulas' in sql or 'custo_produto_exclusoes' in sql and ('INSERT INTO' in sql or 'DELETE FROM' in sql)): raise RuntimeError('Falha simulada')
        self.raw.execute(sql.replace('%s','?').replace(' FOR UPDATE',''),tuple(str(v) if isinstance(v,Decimal) else v for v in args))
    def fetchone(self):
        row=self.raw.fetchone();return dict(row) if row else None
    def fetchall(self): return [dict(r) for r in self.raw.fetchall()]
    def close(self): self.raw.close()


class Connection:
    def __init__(self,path,fail=False):
        self.raw=sqlite3.connect(path);self.raw.row_factory=sqlite3.Row;self.fail=fail
    def cursor(self,**kwargs): return Cursor(self)
    def commit(self): self.raw.commit()
    def rollback(self): self.raw.rollback()
    def close(self): self.raw.close()


def formula(volume='2000', revision=0, dose='100'):
    try:
        quantidade = Decimal(str(volume)) * Decimal('2') / Decimal('1000000')
        if not quantidade.is_finite() or quantidade <= 0:
            raise ValueError
    except (ValueError, ArithmeticError):
        quantidade = Decimal('.004')
    return {'volume_ml':volume,'unidades_pacote':6,'revisao':revision,'xarope_litros':dose,'xarope_revisao':1,
            'xarope_composto_id':1,'xarope_composto_revisao':1,
            'itens':[{'produto_id':7,'nome':'Nome adulterado','unidade':'l','quantidade':str(quantidade),'preco_unitario':'999999'}]}


class CustoProdutoTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=str(Path(temp.name)/'custos.sqlite');self.fail=False
        patch=mock.patch('custo_produto.hoje',return_value=dt.date(2026,9,22));patch.start();self.addCleanup(patch.stop)
        c=sqlite3.connect(self.path)
        c.executescript('''
          CREATE TABLE estoque_produtos(id INTEGER PRIMARY KEY,nome_produto TEXT,produto_base_nome TEXT DEFAULT '',descricao_sped TEXT DEFAULT '',grupo_estoque TEXT,ativo INTEGER,unidade TEXT,codigo_barras TEXT DEFAULT '',codigo_produto_nfe TEXT DEFAULT '',fator_embalagem_padrao NUMERIC DEFAULT 1);
          INSERT INTO estoque_produtos(id,nome_produto,grupo_estoque,ativo,unidade) VALUES
           (1,'Uva PET 2 L','PET',1,'UN'),(2,'Uva GFA 600 ML','GFA',1,'UN'),(3,'Laranja PET 200 ML','PET',1,'UN'),
           (4,'Agua 500 ML','AGUA',1,'UN'),(5,'Inativo','INSUMOS',0,'KG'),
           (6,'Acucar','INSUMOS',1,'KG'),(7,'Concentrado','INSUMOS',1,'L'),(8,'Tampa','INSUMOS',1,'UN'),(9,'Aroma','INSUMOS',1,'L');
          CREATE TABLE custo_produto_formulas(produto_id INTEGER PRIMARY KEY,volume_ml NUMERIC,xarope_litros NUMERIC,xarope_composto_id INTEGER,agua_quente_litros NUMERIC,agua_quente_valor_litro NUMERIC,unidades_pacote INTEGER,itens_json TEXT,revisao INTEGER DEFAULT 1,atualizado_por TEXT,atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP);
          CREATE TABLE custo_produto_exclusoes(produto_id INTEGER PRIMARY KEY,excluido_por TEXT,excluido_em TEXT DEFAULT CURRENT_TIMESTAMP);
          CREATE TABLE custo_produto_xarope(id INTEGER PRIMARY KEY,rendimento_litros NUMERIC,itens_json TEXT,revisao INTEGER DEFAULT 0,atualizado_por TEXT DEFAULT '',atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP);
          CREATE TABLE custo_produto_xaropes_compostos(id INTEGER PRIMARY KEY AUTOINCREMENT,nome TEXT UNIQUE,xarope_base_litros NUMERIC,rendimento_litros NUMERIC,dose_litros_1000 NUMERIC,itens_json TEXT,revisao INTEGER DEFAULT 1,atualizado_por TEXT,atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP);
          CREATE TABLE custo_produto_rateio(id INTEGER PRIMARY KEY,volume_mensal_litros NUMERIC,capacidade_litros_hora NUMERIC,horas_semanais NUMERIC DEFAULT 44,itens_json TEXT,revisao INTEGER DEFAULT 0,atualizado_por TEXT DEFAULT '',atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP);
          INSERT INTO custo_produto_rateio(id,itens_json) VALUES(1,'[]');
          CREATE TABLE abastecimentos(id INTEGER PRIMARY KEY,valor NUMERIC,quantidade_litros NUMERIC,status TEXT,data_liberacao TEXT,data_abastecimento TEXT);
          CREATE TABLE estoque_produto_codigos(produto_id INTEGER,codigo_norm TEXT,ativo INTEGER,origem_tipo TEXT);
          CREATE TABLE estoque_xml_descartes(nota_key TEXT,status TEXT);
          CREATE TABLE estoque_movimentos(id INTEGER PRIMARY KEY,referencia_tipo TEXT,referencia_id INTEGER,tipo_movimento TEXT,nome_produto TEXT,codigo_barras TEXT,codigo_produto_nfe TEXT);
          CREATE TABLE importar_xml_estoque_itens(id INTEGER PRIMARY KEY,chave_nfe TEXT,numero_nota TEXT,serie TEXT DEFAULT '1',emitente_cnpj TEXT DEFAULT '123',emitente_nome TEXT DEFAULT 'Fornecedor',data_emissao TEXT,natureza_operacao TEXT DEFAULT 'Venda',cfop TEXT DEFAULT '5101',codigo_produto TEXT DEFAULT '',descricao_produto TEXT,unidade TEXT,quantidade NUMERIC DEFAULT 1,valor_unitario NUMERIC,dados_json TEXT DEFAULT '{}',tipo_movimento TEXT DEFAULT 'ENTRADA_ESTOQUE',padrao_detectado TEXT DEFAULT 'ENTRADA_FORNECEDOR');
          CREATE TABLE custo_produto_sped_itens(id INTEGER PRIMARY KEY AUTOINCREMENT,identidade TEXT UNIQUE,empresa_cnpj TEXT,periodo TEXT,chave_documento TEXT,numero_nota TEXT,item_numero TEXT,data_emissao TEXT,fornecedor_cnpj TEXT,fornecedor_nome TEXT,codigo_produto TEXT,descricao_produto TEXT,unidade TEXT,quantidade NUMERIC,valor_item NUMERIC,valor_desconto NUMERIC DEFAULT 0,cfop TEXT,arquivo_origem TEXT,importado_por TEXT,atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')
        c.execute('INSERT INTO custo_produto_xarope(id,rendimento_litros,itens_json,revisao) VALUES (1,100,?,1)',(json.dumps([{'produto_id':6,'nome':'Acucar','unidade':'kg','quantidade':'100','preco_unitario':'777'}]),))
        c.execute('INSERT INTO custo_produto_xaropes_compostos(id,nome,xarope_base_litros,rendimento_litros,dose_litros_1000,itens_json,revisao,atualizado_por) VALUES (1,?,?,?,?,?,1,?)',
                  ('Uva',100,1000,2000,json.dumps([{'produto_id':4,'nome':'Agua 500 ML','unidade':'l','quantidade':'.000001','preco_provisorio':'.000001'}]),'Operador'))
        c.commit();c.close()
        self.purchase(10,'Acucar','4','2026-01-05','KG')
        self.purchase(11,'Concentrado','20','2026-01-05','L')
        self.purchase(12,'Acucar','5','2026-02-10','KG')
        self.purchase(13,'Acucar','1000','2099-01-01','KG')
        app=Flask(__name__);app.config['TESTING']=True
        register_custo_produto(app,{'get_conn':lambda:Connection(self.path,self.fail),'actor':lambda:'Operador'})
        self.client=app.test_client()
        self.headers={'X-Usuario-Id':'42','X-Usuario-Perfil':'usuario','X-Usuario-Recursos':'custo_produto'}
        self.dashboard_headers={**self.headers,'X-Usuario-Recursos':'custo_produto_dashboard'}

    def purchase(self,pid,name,price,date,unit='KG',**extra):
        data={'id':pid,'chave_nfe':str(pid).zfill(44),'numero_nota':str(pid),'descricao_produto':name,'valor_unitario':price,'data_emissao':date,'unidade':unit,**extra}
        c=sqlite3.connect(self.path);c.execute('INSERT INTO importar_xml_estoque_itens ('+','.join(data)+') VALUES ('+','.join('?' for _ in data)+')',tuple(data.values()));c.commit();c.close()
    def save(self,pid=1,payload=None,headers=None):
        return self.client.put(f'/api/custo-produto/{pid}',json=formula() if payload is None else payload,headers=self.headers if headers is None else headers)
    def delete(self,pid=1,revision=1,headers=None):
        return self.client.delete(f'/api/custo-produto/{pid}',json={'revisao':revision},headers=self.headers if headers is None else headers)
    def hide(self,pid=1,headers=None):
        return self.client.delete(f'/api/custo-produto/produtos/{pid}',headers=self.headers if headers is None else headers)
    def restore(self,pid=1,headers=None):
        return self.client.post(f'/api/custo-produto/produtos/{pid}/restaurar',headers=self.headers if headers is None else headers)
    def data(self): return self.client.get('/api/custo-produto',headers=self.headers).json
    def base(self,yield_litres=100,revision=1):
        return self.client.put('/api/custo-produto/xarope',headers=self.headers,json={'revisao':revision,'rendimento_litros':yield_litres,'itens':[{'produto_id':6,'unidade':'kg','quantidade':'100','preco_unitario':'0'}]})

    def test_last_purchase_reprices_base_and_ignores_client_or_legacy_prices(self):
        saved=self.save();self.assertEqual(200,saved.status_code)
        self.assertEqual('Concentrado',saved.json['itens'][0]['nome'])
        self.assertEqual('20',saved.json['itens'][0]['preco_unitario'])
        self.assertEqual(1.08,saved.json['calculo']['custo_unidade'])
        self.assertEqual(5,self.data()['xarope']['custo_litro'])
        self.purchase(20,'Acucar','6','2026-03-01')
        rows={p['produto_id']:p for p in self.data()['produtos']}
        self.assertEqual(1.28,rows[1]['calculo']['custo_unidade'])
        self.assertEqual(1,rows[1]['revisao'])

    def test_finished_beverage_yield_scales_all_presentations(self):
        self.save();self.save(2,formula('600',dose='200'))
        data=self.base(50).json
        rows={p['produto_id']:p for p in data['produtos']}
        self.assertEqual(2.08,rows[1]['calculo']['custo_unidade'])
        self.assertEqual(.624,rows[2]['calculo']['custo_unidade'])
        self.assertEqual(409,self.base().status_code)
        self.assertEqual(200,self.save(3).status_code)

    def test_flavor_compound_is_shared_by_pet_and_returnable_presentations(self):
        payload={'revisao':0,'xarope_revisao':1,'nome':'Limao','xarope_base_litros':'20',
                 'rendimento_litros':'100','dose_litros_1000':'999999',
                 'itens':[{'produto_id':7,'unidade':'l','quantidade':'1'}]}
        response=self.client.post('/api/custo-produto/xaropes-compostos',headers=self.headers,json=payload)
        self.assertEqual(200,response.status_code)
        composto=next(x for x in response.json['xaropes_compostos'] if x['nome']=='Limao')
        self.assertEqual(1.2,composto['custo_litro'])
        self.assertEqual(.2,composto['custo_sabor_sem_base_litro_bebida'])
        self.assertEqual(1.2,composto['custo_com_base_litro_bebida'])
        self.assertEqual(100,composto['custo_base_lote'])
        self.assertEqual(20,composto['custo_itens_sabor_lote'])
        self.assertEqual(1200,composto['custo_1000_litros'])
        self.assertEqual(200,composto['xarope_base_litros_1000'])
        self.assertEqual(200,composto['dose_litros_1000'])
        pet=formula();pet.update(itens=[],xarope_composto_id=composto['id'],xarope_composto_revisao=1)
        gfa=formula('600');gfa.update(itens=[],xarope_composto_id=composto['id'],xarope_composto_revisao=1)
        self.assertEqual(2.4,self.save(1,pet).json['calculo']['custo_unidade'])
        self.assertEqual(.72,self.save(2,gfa).json['calculo']['custo_unidade'])
        payload.update(revisao=1,xarope_base_litros='10')
        updated=self.client.put(f"/api/custo-produto/xaropes-compostos/{composto['id']}",headers=self.headers,json=payload)
        self.assertEqual(200,updated.status_code)
        rows={p['produto_id']:p for p in updated.json['produtos']}
        self.assertEqual('Limao',rows[1]['xarope_composto_nome'])
        self.assertEqual(1.4,rows[1]['calculo']['custo_unidade'])
        self.assertEqual(.42,rows[2]['calculo']['custo_unidade'])
        self.assertEqual(409,self.save(3,{**pet,'revisao':0}).status_code)

    def test_dashboard_uses_latest_current_price_and_ignores_future_purchase(self):
        self.save()
        response=self.client.get('/api/custo-produto/dashboard',headers=self.dashboard_headers)
        self.assertEqual(200,response.status_code)
        self.assertEqual('2026-09-22',response.json['data_referencia'])
        self.assertNotIn('meses',response.json)
        self.assertEqual([1],[p['produto_id'] for p in response.json['produtos']])
        self.assertEqual(5,response.json['xarope_base']['custo_litro'])
        base_item=response.json['xarope_base']['itens'][0]
        self.assertEqual('nfe',base_item['fonte_preco'])
        self.assertEqual('12',base_item['compra']['nota'])
        self.assertEqual('KG',base_item['compra']['unidade_compra'])
        self.assertEqual(500,base_item['custo_formula'])
        self.assertEqual(['Uva'],[s['nome'] for s in response.json['sabores']])
        row=next(p for p in response.json['produtos'] if p['produto_id']==1)
        self.assertEqual(1.08,row['atual']['custo_unidade'])
        self.assertEqual(1.08,row['atual']['custo_unidade_sem_rateio'])
        self.assertEqual('11',row['itens'][0]['compra']['nota'])
        self.assertEqual(.08,row['itens'][0]['custo_formula'])
        self.assertNotIn('mensal',row)

    def test_water_formula_does_not_require_or_charge_syrup(self):
        payload=formula('500')
        saved=self.save(4,payload)
        self.assertEqual(200,saved.status_code)
        self.assertFalse(saved.json['usa_xarope'])
        self.assertIsNone(saved.json['xarope_composto_id'])
        self.assertEqual(0,saved.json['calculo']['componentes_unidade']['xarope'])
        self.assertEqual(.02,saved.json['calculo']['custo_unidade_sem_rateio'])
        dashboard=self.client.get('/api/custo-produto/dashboard',headers=self.dashboard_headers).json
        self.assertEqual([4],[p['produto_id'] for p in dashboard['produtos']])

    def test_base_only_and_missing_price_saved_with_pending_cost(self):
        payload=formula();payload['itens']=[]
        self.assertEqual(1,self.save(payload=payload).json['calculo']['custo_unidade'])
        payload=formula();payload['itens'][0]['produto_id']=9
        row=self.save(2,payload).json
        self.assertIsNone(row['calculo']);self.assertTrue(row['pendencias'])
        self.assertIsNone(row['itens'][0]['preco_unitario'])

    def test_provisional_price_is_used_only_until_supplier_invoice_arrives(self):
        payload=formula()
        payload['itens']=[{'produto_id':9,'unidade':'l','quantidade':'.004','preco_provisorio':'7'}]
        saved=self.save(2,payload).json
        self.assertEqual('7',saved['itens'][0]['preco_unitario'])
        self.assertEqual('provisorio',saved['itens'][0]['fonte_preco'])
        self.assertEqual(514,saved['calculo']['custo_1000_litros'])
        self.purchase(20,'Aroma','8','2026-03-01','L')
        row=next(p for p in self.data()['produtos'] if p['produto_id']==2)
        self.assertEqual('8',row['itens'][0]['preco_unitario'])
        self.assertEqual('nfe',row['itens'][0]['fonte_preco'])
        self.assertEqual('7',row['itens'][0]['preco_provisorio'])
        self.assertEqual(516,row['calculo']['custo_1000_litros'])
        dashboard=self.client.get('/api/custo-produto/dashboard',headers=self.dashboard_headers).json
        current=next(p for p in dashboard['produtos'] if p['produto_id']==2)['atual']
        self.assertEqual(516,current['custo_1000_litros'])

    def test_hot_water_quantity_and_litre_price_are_persisted_and_costed(self):
        payload=formula()
        payload.update(agua_quente_litros='100',agua_quente_valor_litro='.5')
        saved=self.save(payload=payload).json
        self.assertEqual(100,saved['agua_quente_litros'])
        self.assertEqual(.5,saved['agua_quente_valor_litro'])
        self.assertEqual(50,saved['calculo']['custo_agua_quente'])
        self.assertEqual(590,saved['calculo']['custo_1000_litros'])
        self.assertEqual(1.18,saved['calculo']['custo_unidade'])
        invalid=formula(revision=1);invalid['agua_quente_litros']='100'
        response=self.save(payload=invalid)
        self.assertEqual(400,response.status_code)
        self.assertIn('quantidade em litros e o valor por litro',response.json['erro'])

    def test_standard_overhead_is_allocated_to_unit_and_package(self):
        payload={'revisao':0,'volume_mensal_litros':'10000','itens':[
            {'categoria':'mao_obra','descricao':'Folha da producao','tipo':'mensal','valor':'3000'},
            {'categoria':'energia','descricao':'Energia fabril','tipo':'litro','valor':'.1'},
            {'categoria':'impostos','descricao':'Impostos industriais','tipo':'percentual','valor':'10'}]}
        saved=self.client.put('/api/custo-produto/rateio',headers=self.headers,json=payload)
        self.assertEqual(200,saved.status_code)
        product=self.save().json
        self.assertEqual(6,product['unidades_pacote'])
        self.assertAlmostEqual(1.988,product['calculo']['custo_unidade'],places=5)
        self.assertAlmostEqual(11.928,product['calculo']['custo_pacote'],places=5)
        self.assertAlmostEqual(1.08,product['calculo']['custo_unidade_sem_rateio'],places=5)
        self.assertAlmostEqual(6.48,product['calculo']['custo_pacote_sem_rateio'],places=5)
        parts=product['calculo']['componentes_unidade']
        self.assertAlmostEqual(.6,parts['mao_obra'],places=6)
        self.assertAlmostEqual(.2,parts['energia'],places=6)
        self.assertAlmostEqual(.108,parts['impostos'],places=5)
        dashboard=self.client.get('/api/custo-produto/dashboard',headers=self.dashboard_headers).json
        row=next(p for p in dashboard['produtos'] if p['produto_id']==1)
        self.assertAlmostEqual(11.928,row['atual']['custo_pacote'],places=5)
        self.assertEqual(403,self.client.put('/api/custo-produto/rateio',headers=self.dashboard_headers,json={**payload,'revisao':1}).status_code)
        self.assertEqual(409,self.client.put('/api/custo-produto/rateio',headers=self.headers,json=payload).status_code)

    def test_monthly_overhead_requires_reference_volume(self):
        response=self.client.put('/api/custo-produto/rateio',headers=self.headers,json={'revisao':0,'itens':[
            {'categoria':'agua','descricao':'Conta de agua','tipo':'mensal','valor':'100'}]})
        self.assertEqual(400,response.status_code)
        self.assertIn('volume mensal',response.json['erro'].lower())

    def test_boiler_hourly_cost_is_converted_by_productive_capacity(self):
        payload={'revisao':0,'capacidade_litros_hora':'2500','itens':[
            {'categoria':'caldeira','descricao':'Lenha da caldeira','tipo':'hora','valor':'250'}]}
        saved=self.client.put('/api/custo-produto/rateio',headers=self.headers,json=payload)
        self.assertEqual(200,saved.status_code)
        self.assertEqual(2500,saved.json['capacidade_litros_hora'])
        product=self.save().json
        self.assertAlmostEqual(.2,product['calculo']['componentes_unidade']['caldeira'],places=6)
        self.assertAlmostEqual(1.28,product['calculo']['custo_unidade'],places=5)
        self.assertAlmostEqual(7.68,product['calculo']['custo_pacote'],places=5)
        invalid=self.client.put('/api/custo-produto/rateio',headers=self.headers,json={
            'revisao':1,'itens':[{'categoria':'caldeira','descricao':'Lenha','tipo':'hora','valor':'250'}]})
        self.assertEqual(400,invalid.status_code)
        self.assertIn('litros por hora',invalid.json['erro'].lower())

    def test_monthly_fuel_is_distributed_over_44_weekly_hours_and_capacity(self):
        payload={'revisao':0,'capacidade_litros_hora':'6000','horas_semanais':'44','itens':[
            {'categoria':'combustivel','descricao':'Combustivel da producao','tipo':'mensal_horas','valor':'1000'}]}
        saved=self.client.put('/api/custo-produto/rateio',headers=self.headers,json=payload)
        self.assertEqual(200,saved.status_code)
        self.assertEqual(44,saved.json['horas_semanais'])
        product=self.save().json
        # 44 * 52 / 12 = 190,6667 h/mes; R$ 1000 / horas / 6000 L/h.
        self.assertAlmostEqual(.001748252,product['calculo']['componentes_unidade']['combustivel'],places=6)
        dashboard=self.client.get('/api/custo-produto/dashboard',headers=self.dashboard_headers).json
        self.assertEqual('mensal_horas',dashboard['rateio']['itens'][0]['tipo'])

    def test_posted_fuel_uses_all_completed_entries_from_latest_available_month(self):
        c=sqlite3.connect(self.path)
        c.executemany('INSERT INTO abastecimentos VALUES(?,?,?,?,?,?)',[
            (1,100,15,'abastecido','2026-08-01','2026-08-02'),
            (2,120,18,'abastecido','2026-09-01','2026-09-02'),
            (3,180,22,'abastecido','2026-09-10','2026-09-11'),
            (4,999,99,'liberado','2026-10-01',None),
        ])
        c.commit();c.close()
        payload={'revisao':0,'volume_mensal_litros':'10000','itens':[
            {'categoria':'combustivel','descricao':'Combustivel lancado','tipo':'abastecimentos'}]}
        saved=self.client.put('/api/custo-produto/rateio',headers=self.headers,json=payload)
        self.assertEqual(200,saved.status_code)
        item=saved.json['itens'][0]
        self.assertEqual(300,float(item['valor']))
        self.assertEqual('2026-09',item['periodo_referencia'])
        self.assertEqual(2,item['registros_origem'])
        self.assertEqual(40,item['litros_combustivel'])
        product=self.save().json
        self.assertAlmostEqual(.06,product['calculo']['componentes_unidade']['combustivel'],places=6)
        dashboard=self.client.get('/api/custo-produto/dashboard',headers=self.dashboard_headers).json
        self.assertEqual(300,float(dashboard['rateio']['combustivel_lancado']['valor_total']))

    def test_kg_grams_and_milheiro_conversion(self):
        payload=formula();payload['itens']=[{'produto_id':6,'unidade':'g','quantidade':'2'}]
        self.assertEqual('0.005',self.save(payload=payload).json['itens'][0]['preco_unitario'])
        self.purchase(20,'Tampa','50','2026-04-01','MIL')
        payload=formula();payload['itens']=[{'produto_id':8,'unidade':'un','quantidade':'1'}]
        saved=self.save(2,payload)
        self.assertEqual('0.05',saved.json['itens'][0]['preco_unitario'])
        self.assertEqual(525,saved.json['calculo']['custo_1000_litros'])
        self.assertEqual(.05,saved.json['calculo']['custo_itens_unidade'])

    def test_ml_from_piece_invoice_is_treated_as_milheiro_not_millilitre(self):
        self.purchase(20,'Tampa','54.25','2026-04-01','ML')
        payload=formula();payload['itens']=[{'produto_id':8,'unidade':'un','quantidade':'1'}]
        saved=self.save(payload=payload).json
        self.assertEqual('0.05425',saved['itens'][0]['preco_unitario'])
        self.assertEqual('1000',saved['itens'][0]['fator_aplicado'])
        self.assertEqual(.05425,saved['calculo']['custo_itens_unidade'])

    def test_legacy_sped_unit_codes_convert_labels_to_exact_units(self):
        self.assertEqual('KG', unidade('1'))
        self.assertEqual('UN', unidade('4'))
        self.assertEqual('SC', unidade('22'))
        self.assertEqual('MIL', unidade('28'))
        self.assertEqual('MIL', unidade('68'))
        self.assertEqual('MIL', unidade('429'))
        purchase = {'preco':'24.80','unidade_compra':'429','descricao_xml':'ROTULOS 600 ML'}
        self.assertEqual(Decimal('1000'), fator_item(purchase, {'unidade':'un'}))
        label = {'nome_produto':'ROTULO BOOB ABACAXI PET 12X200ML','grupo_estoque':'OUTROS'}
        self.assertTrue(embalagem_compativel(label, 'ROTULOS DE BOPP 16.6X4.0 ABACAXI 200ML'))
        self.assertFalse(embalagem_compativel(label, 'ABACAXI PET 12X200ML'))
        self.assertEqual(('GUARANA', 200), assinatura_rotulo('ROTULOS DE BOPP 16.6X4.0 (GUARANA RIO BRANCO 200ML)'))
        self.assertEqual(('LIMAO', 200), assinatura_rotulo('ROTULOS BOPP SODINHA PET 12X200ML'))
        self.assertEqual(('LARANJA', 2000), assinatura_rotulo('ROTULOS BOPP 33.5X7.5 (LARANJA RIO BRANC'))
        self.assertEqual(('CITRUS', 2000), assinatura_rotulo('ROTULOS BOPP MET. 33.5X7.5 (CITRUS RIO BRANCO 2L)'))
        self.assertEqual(('VERDE', 600), assinatura_preforma('PREFORMA PET 23,6GR VERDE I CPT SHORT NECK 15768'))
        self.assertEqual(Decimal(100) / Decimal('23'), fator_item(
            {'unidade_compra':'MT','descricao_xml':'ROTULOS BOPP 23X5.1 ABACAXI 600 ML'}, {'unidade':'un'}))
        self.assertEqual(Decimal(100) / Decimal('16.6'), fator_item(
            {'unidade_compra':'M','descricao_xml':'ROTULOS BOPP 16,6X4,0 GUARANA 200 ML'}, {'unidade':'un'}))

    def test_packaging_conversion_requires_explicit_factor_and_same_unit(self):
        self.purchase(20,'Concentrado','250','2026-03-01','BB')
        saved=self.save();self.assertIsNone(saved.json['calculo'])
        payload=formula(revision=1);payload['itens'][0].update(fator_compra='25',unidade_compra='BB')
        self.assertEqual('10',self.save(payload=payload).json['itens'][0]['preco_unitario'])
        self.purchase(21,'Concentrado','300','2026-04-01','SC')
        row=next(p for p in self.data()['produtos'] if p['produto_id']==1)
        self.assertIsNone(row['calculo'])

    def test_raw_supplier_code_does_not_match_unrelated_product_and_confirmed_link_wins(self):
        c=sqlite3.connect(self.path);c.execute("UPDATE estoque_produtos SET codigo_produto_nfe='XYZ' WHERE id=6");c.commit();c.close()
        self.purchase(30,'Outro produto','100','2026-05-01',codigo_produto='XYZ')
        self.assertEqual(5,self.data()['xarope']['custo_litro'])
        c=sqlite3.connect(self.path);c.execute("INSERT INTO estoque_movimentos VALUES(1,'importar_xml',30,'entrada','Acucar','','XYZ')");c.commit();c.close()
        self.assertEqual(100,self.data()['xarope']['custo_litro'])

    def test_typed_alias_and_discard_transfer_return_bonus_excluded(self):
        c=sqlite3.connect(self.path);c.execute("INSERT INTO estoque_produto_codigos VALUES(6,'ALIAS',1,'nfe_entrada')");c.commit();c.close()
        self.purchase(30,'Nome fornecedor','7','2026-05-01',codigo_produto='ALIAS')
        for i,extra in enumerate([{'padrao_detectado':'TRANSFERENCIA_INTERNA'}, {'natureza_operacao':'Devolucao'}, {'cfop':'5910'}, {'tipo_movimento':'SAIDA_ESTOQUE'}],31):
            self.purchase(i,'Acucar','999','2026-06-01',**extra)
        self.purchase(40,'Acucar','999','2026-07-01')
        c=sqlite3.connect(self.path);c.execute('INSERT INTO estoque_xml_descartes VALUES (?,?)',(str(40).zfill(44),'descartado'));c.commit();c.close()
        self.assertEqual(7,self.data()['xarope']['custo_litro'])

    def test_reimport_old_invoice_does_not_replace_latest_by_issue_date(self):
        self.purchase(100,'Acucar','4','2026-01-05',chave_nfe=str(10).zfill(44))
        self.assertEqual(5,self.data()['xarope']['custo_litro'])
        c=Connection(self.path);cur=c.cursor();history=carregar_compras(cur);cur.close();c.close()
        self.assertEqual(1,len([h for h in history if h['nota']=='10']))

    def test_sped_reference_reprices_cost_and_xml_wins_tie(self):
        payload={'arquivo':'sped-ago.txt','periodo':'2026-08','empresa_cnpj':'20984401000130','itens':[
            {'chave_documento':'35260800000000000000550010000009991000009999','numero_nota':'999',
             'item_numero':'1','data_emissao':'2026-08-10','fornecedor_cnpj':'123',
             'fornecedor_nome':'Fornecedor SPED','codigo_produto':'ACU','descricao_produto':'Acucar',
             'unidade':'KG','quantidade':'10','valor_item':'82','valor_desconto':'2','cfop':'1101'}]}
        response=self.client.post('/api/custo-produto/sped',headers=self.headers,json=payload)
        self.assertEqual(200,response.status_code,response.json)
        self.assertEqual(1,response.json['itens_gravados'])
        base=self.data()['xarope']
        self.assertEqual(8,base['custo_litro'])
        self.assertEqual('sped',base['itens'][0]['fonte_preco'])
        self.assertEqual('SPED Fiscal',base['itens'][0]['compra']['origem'])
        self.purchase(99,'Acucar','9','2026-08-10','KG')
        base=self.data()['xarope']
        self.assertEqual(9,base['custo_litro'])
        self.assertEqual('nfe',base['itens'][0]['fonte_preco'])

    def test_explicit_product_sped_description_links_different_stock_name(self):
        c=sqlite3.connect(self.path)
        c.execute('''INSERT INTO estoque_produtos
            (id,nome_produto,descricao_sped,grupo_estoque,ativo,unidade)
            VALUES(10,?,?,?,?,?)''',(
                'Concentrado liquido para ref. framboesa',
                'CONCENTRADO P/REFRI FRAMBOESA BD25 C/C',
                'PRIMA',1,'KG'))
        c.commit();c.close()
        payload={'arquivo':'sped-set.txt','periodo':'2026-09','empresa_cnpj':'20984401000130','itens':[
            {'numero_nota':'8451','item_numero':'1','data_emissao':'2026-09-18','fornecedor_cnpj':'123',
             'fornecedor_nome':'Fornecedor concentrado','codigo_produto':'FR25',
             'descricao_produto':'concentrado p/refri framboesa bd25 c/c',
             'unidade':'KG','quantidade':'25','valor_item':'875','valor_desconto':'0','cfop':'1101'}]}
        response=self.client.post('/api/custo-produto/sped',headers=self.headers,json=payload)
        self.assertEqual(200,response.status_code,response.json)
        purchase=next(item for item in self.data()['insumos'] if item['id']==10)['ultima_compra']
        self.assertEqual('8451',purchase['nota'])
        self.assertEqual('sped',purchase['fonte'])
        self.assertEqual('Descricao SPED informada no cadastro do produto',purchase['vinculo'])
        self.assertEqual('CONCENTRADO P/REFRI FRAMBOESA BD25 C/C',
                         next(item for item in self.data()['insumos'] if item['id']==10)['descricao_sped'])

    def test_manual_product_gets_unique_compatible_sped_description_and_existing_factor(self):
        c=sqlite3.connect(self.path)
        c.execute("INSERT INTO estoque_produtos(id,nome_produto,grupo_estoque,ativo,unidade) VALUES(10,'Aroma Natural Laranja Especial','PRIMA',1,'KG')")
        c.commit();c.close()
        payload={'arquivo':'sped-ago.txt','periodo':'2026-08','empresa_cnpj':'20984401000130','itens':[
            {'numero_nota':'812','item_numero':'1','data_emissao':'2026-08-10','fornecedor_cnpj':'84430149000109',
             'fornecedor_nome':'Duas Rodas','codigo_produto':'30112','descricao_produto':'LARANJA AROMA NATURAL DE',
             'unidade':'31','quantidade':'5','valor_item':'1312.10','valor_desconto':'0','cfop':'1101'}]}
        self.assertEqual(200,self.client.post('/api/custo-produto/sped',headers=self.headers,json=payload).status_code)
        ingredient=next(item for item in self.data()['insumos'] if item['id']==10)
        purchase=ingredient['ultima_compra']
        self.assertEqual('sped',purchase['fonte'])
        self.assertIn('compativel e nao ambigua',purchase['vinculo'])
        priced=precificar_item({'produto_id':10,'unidade':'ml','quantidade':'90',
                                'fator_compra':'1000','unidade_compra':''},{10:purchase})
        self.assertEqual('0.26242',priced['preco_unitario'])
        self.assertEqual('31',priced['unidade_compra'])

    def test_single_distinctive_manual_name_links_diatomita_sped_and_requests_fraction(self):
        c=sqlite3.connect(self.path)
        c.execute("INSERT INTO estoque_produtos(id,nome_produto,grupo_estoque,ativo,unidade) VALUES(10,'DIATOMITA','PRIMA',1,'KG')")
        c.commit();c.close()
        payload={'arquivo':'sped-jan.txt','periodo':'2025-01','empresa_cnpj':'20984401000130','itens':[
            {'chave_documento':'43250102664051000143550100000755061001685928','numero_nota':'75506',
             'item_numero':'3','data_emissao':'2025-01-07','fornecedor_cnpj':'02664051000143',
             'fornecedor_nome':'VENETO MERCANTIL IMPORTADORA LTDA','codigo_produto':'97520000000048',
             'descricao_produto':'DIATOMITA CA 500','unidade':'22','quantidade':'13',
             'valor_item':'2773.16','valor_desconto':'0','cfop':'2101'}]}
        self.assertEqual(200,self.client.post('/api/custo-produto/sped',headers=self.headers,json=payload).status_code)
        ingredient=next(item for item in self.data()['insumos'] if item['id']==10)
        purchase=ingredient['ultima_compra']
        self.assertEqual('75506',purchase['nota'])
        self.assertEqual('sped',purchase['fonte'])
        self.assertEqual('SC',purchase['unidade_compra'])
        self.assertIn('compativel e nao ambigua',purchase['vinculo'])
        pending=precificar_item({'produto_id':10,'unidade':'kg','quantidade':'3'}, {10:purchase})
        self.assertIsNone(pending['preco_unitario'])
        self.assertIn('quantidade em kg por SC',pending['pendencia_preco'])
        priced=precificar_item({'produto_id':10,'unidade':'kg','quantidade':'3',
                                'fator_compra':'22.7','unidade_compra':'SC'}, {10:purchase})
        self.assertEqual('sped',priced['fonte_preco'])
        self.assertEqual('22.7',priced['fator_aplicado'])
        self.assertAlmostEqual(9.397356828193832, float(priced['preco_unitario']))

    def test_preform_sped_links_unique_color_size_inferred_from_weight(self):
        c=sqlite3.connect(self.path)
        c.execute("INSERT INTO estoque_produtos(id,nome_produto,grupo_estoque,ativo,unidade) VALUES(10,'PREFORMA VERDE 600ML','PREFORMA',1,'UN')")
        c.commit();c.close()
        payload={'arquivo':'sped-set.txt','periodo':'2026-09','empresa_cnpj':'20984401000130','itens':[
            {'numero_nota':'20655','item_numero':'1','data_emissao':'2026-09-21','fornecedor_cnpj':'123',
             'fornecedor_nome':'Fornecedor PET','codigo_produto':'PR23601100451',
             'descricao_produto':'PREFORMA PET 23,6GR VERDE I CPT SHORT NECK 15768',
             'unidade':'68','quantidade':'47.304','valor_item':'16821.30','valor_desconto':'0','cfop':'2101'}]}
        self.assertEqual(200,self.client.post('/api/custo-produto/sped',headers=self.headers,json=payload).status_code)
        purchase=next(item for item in self.data()['insumos'] if item['id']==10)['ultima_compra']
        self.assertEqual('20655',purchase['nota'])
        self.assertEqual('MIL',purchase['unidade_compra'])
        self.assertIn('cor e apresentacao',purchase['vinculo'])
        priced=precificar_item({'produto_id':10,'unidade':'un','quantidade':'1'}, {10:purchase})
        self.assertEqual('sped',priced['fonte_preco'])
        self.assertEqual('1000',priced['fator_aplicado'])

    def test_missing_pet_sizes_receive_reviewable_same_flavor_suggestion(self):
        c=sqlite3.connect(self.path)
        c.executemany('''INSERT INTO estoque_produtos
            (id,nome_produto,grupo_estoque,ativo,unidade,fator_embalagem_padrao) VALUES(?,?,?,?,?,?)''',[
            (10,'Abacaxi PET 2 L','PET',1,'UN',6),(11,'Abacaxi PET 600 ML','PET',1,'UN',12),
            (12,'Abacaxi PET 200 ML','PET',1,'UN',12),(13,'Tampa baixa verde','TAMPAS',1,'UN',1),
            (14,'Preforma verde 2 L','PREFORMA',1,'UN',1),(15,'Rotulo Abacaxi 2 L','OUTROS',1,'UN',1),
            (16,'Preforma verde 600 ML','PREFORMA',1,'UN',1),(17,'Rotulo Abacaxi 600 ML','OUTROS',1,'UN',1),
            (18,'Preforma verde 200 ML','PREFORMA',1,'UN',1),(19,'Rotulo Abacaxi PET 12X200ML','OUTROS',1,'UN',1),
        ])
        c.execute('''INSERT INTO custo_produto_xaropes_compostos
            (id,nome,xarope_base_litros,rendimento_litros,dose_litros_1000,itens_json,revisao,atualizado_por)
            VALUES(2,'Abacaxi',20,100,200,?,1,'Operador')''',(json.dumps([{'produto_id':7,'nome':'Concentrado','unidade':'l','quantidade':'1'}]),))
        source_items=[{'produto_id':13,'nome':'Tampa baixa verde','unidade':'un','quantidade':'1'},
                      {'produto_id':14,'nome':'Preforma verde 2 L','unidade':'un','quantidade':'1'},
                      {'produto_id':15,'nome':'Rotulo Abacaxi 2 L','unidade':'un','quantidade':'1'}]
        c.execute('''INSERT INTO custo_produto_formulas
            (produto_id,volume_ml,xarope_composto_id,unidades_pacote,itens_json,revisao,atualizado_por)
            VALUES(10,2000,2,6,?,1,'Operador')''',(json.dumps(source_items),))
        c.commit();c.close()
        products={row['produto_id']:row for row in self.data()['produtos']}
        self.assertEqual([13,16,17],[item['produto_id'] for item in products[11]['sugestao_formula']['itens']])
        self.assertEqual([13,18,19],[item['produto_id'] for item in products[12]['sugestao_formula']['itens']])
        suggestion=products[11]['sugestao_formula']
        saved=self.save(11,{'volume_ml':suggestion['volume_ml'],'unidades_pacote':suggestion['unidades_pacote'],
            'revisao':0,'xarope_composto_id':suggestion['xarope_composto_id'],
            'xarope_composto_revisao':suggestion['xarope_composto_revisao'],'itens':suggestion['itens']})
        self.assertEqual(200,saved.status_code,saved.json)
        self.assertEqual('Abacaxi',saved.json['xarope_composto_nome'])
        self.assertEqual(1,saved.json['revisao'])

    def test_sped_sync_replaces_period_and_discards_non_purchase_cfop(self):
        payload={'arquivo':'sped-ago.txt','periodo':'2026-08','empresa_cnpj':'20984401000130','itens':[
            {'numero_nota':'1','item_numero':'1','data_emissao':'2026-08-10','fornecedor_cnpj':'123',
             'fornecedor_nome':'Fornecedor','codigo_produto':'ACU','descricao_produto':'Acucar',
             'unidade':'KG','quantidade':'10','valor_item':'80','cfop':'5101'}]}
        response=self.client.post('/api/custo-produto/sped',headers=self.headers,json=payload)
        self.assertEqual(200,response.status_code)
        self.assertEqual(0,response.json['itens_gravados'])
        self.assertEqual(1,response.json['itens_descartados'])

    def test_typed_numeric_alias_uses_canonical_code_without_leading_zeros(self):
        c=sqlite3.connect(self.path);c.execute("INSERT INTO estoque_produto_codigos VALUES(6,'123',1,'nfe_entrada')");c.commit();c.close()
        self.purchase(30,'Descricao fornecedor','7','2026-05-01',codigo_produto='000123')
        self.assertEqual(7,self.data()['xarope']['custo_litro'])

    def test_sugar_xml_order_delivery_reuses_confirmed_mapping_after_rename(self):
        c=sqlite3.connect(self.path)
        c.execute("UPDATE estoque_produtos SET nome_produto='ACUCAR CRISTAL BAGS',codigo_produto_nfe='000500072' WHERE id=6")
        c.execute("INSERT INTO estoque_movimentos VALUES(1,'importar_xml',20,'entrada','Acucar Cristal Bags Tipo 3','','000500072')")
        c.commit();c.close()
        extras={'codigo_produto':'500072','natureza_operacao':'Remessa merc.conta ord.terc.em venda à ordem','cfop':'6923'}
        self.purchase(20,'Acucar Cristal Bags Tipo 3','1540','2026-07-10','TO',**extras)
        self.purchase(21,'Acucar Cristal Bags Tipo 3','1560','2026-09-18','TO',**extras)
        base=self.data()['xarope']
        self.assertEqual(1.56,base['custo_litro'])
        item=base['itens'][0]
        self.assertEqual('21',item['compra']['nota'])
        self.assertEqual('T',item['compra']['unidade_compra'])
        self.assertIn('Fornecedor e codigo XML',item['compra']['vinculo'])
        # Mesmo codigo de outro fornecedor nao herda esse vinculo.
        self.purchase(22,'Outro insumo','9999','2026-09-20','TO',emitente_cnpj='999',**extras)
        self.assertEqual(1.56,self.data()['xarope']['custo_litro'])
        # Remessas sem venda a ordem permanecem excluidas.
        self.purchase(23,'Acucar Cristal Bags Tipo 3','9999','2026-09-21','TO',**{**extras,'natureza_operacao':'Remessa para armazenagem'})
        self.assertEqual(1.56,self.data()['xarope']['custo_litro'])
        self.save()
        dashboard=self.client.get('/api/custo-produto/dashboard',headers=self.dashboard_headers).json
        product=next(p for p in dashboard['produtos'] if p['produto_id']==1)
        self.assertEqual(.392,product['atual']['custo_unidade'])
        # Outro emitente com o MESMO codigo e descricao ja confirmados mantem
        # o vinculo, mesmo que o nome atual do cadastro tenha sido abreviado.
        self.purchase(24,'Acucar Cristal Bags Tipo 3','1570','2026-09-22','TO',emitente_cnpj='888',**extras)
        self.assertEqual(1.57,self.data()['xarope']['custo_litro'])
        self.assertIn('Codigo e descricao XML',self.data()['xarope']['itens'][0]['compra']['vinculo'])

    def test_registered_stock_pack_capacity_is_reused_only_for_confirmed_source_unit(self):
        c=sqlite3.connect(self.path)
        c.execute("UPDATE estoque_produtos SET fator_embalagem_padrao=50 WHERE id=6")
        c.execute("INSERT INTO estoque_movimentos VALUES(1,'importar_xml',20,'entrada','Acucar','','')")
        c.commit();c.close()
        self.purchase(20,'Acucar','75','2026-08-01','SC')
        self.assertEqual(1.5,self.data()['xarope']['custo_litro'])
        self.purchase(21,'Acucar','80','2026-09-01','SC')
        self.assertEqual(1.6,self.data()['xarope']['custo_litro'])
        self.purchase(22,'Acucar','100','2026-09-02','BB')
        self.assertFalse(self.data()['xarope']['precificado'])

    def test_conflicting_historical_xml_mappings_do_not_guess_a_product(self):
        self.purchase(20,'Descricao antiga','6','2026-03-01',codigo_produto='AB')
        self.purchase(21,'Outra descricao','7','2026-04-01',codigo_produto='AB')
        c=sqlite3.connect(self.path)
        c.execute("INSERT INTO estoque_movimentos VALUES(1,'importar_xml',20,'entrada','Acucar','','')")
        c.execute("INSERT INTO estoque_movimentos VALUES(2,'importar_xml',21,'entrada','Aroma','','')")
        c.commit();c.close()
        self.purchase(22,'Descricao antiga','999','2026-05-01',codigo_produto='AB')
        self.assertEqual(6,self.data()['xarope']['custo_litro'])

    def test_invalid_values_products_and_duplicate_items_rejected(self):
        for value in ['',None,'-1','NaN','Infinity','1e40','0.0000001']:
            payload=formula();payload['itens'][0]['quantidade']=value
            self.assertEqual(400,self.save(payload=payload).status_code)
        for pid in [None,999,5,True]:
            payload=formula();payload['itens'][0]['produto_id']=pid
            self.assertEqual(400,self.save(payload=payload).status_code)
        payload=formula();payload['itens']*=2
        self.assertEqual(400,self.save(payload=payload).status_code)
        for value in ['0','-1','NaN','Infinity']:
            payload=formula();payload['itens'][0]['preco_provisorio']=value
            self.assertEqual(400,self.save(payload=payload).status_code)
        for volume in [None,0,-1,'NaN']:
            self.assertEqual(400,self.save(payload=formula(volume)).status_code)
        for pid in [5,999]:self.assertEqual(404,self.save(pid).status_code)

    def test_stale_recipe_and_failed_write_preserve_saved_formula(self):
        self.save();self.assertEqual(409,self.save().status_code)
        self.fail=True
        with self.assertLogs(level='ERROR'):self.assertEqual(500,self.save(payload=formula(revision=1)).status_code)
        self.assertEqual(1,next(p for p in self.data()['produtos'] if p['produto_id']==1)['revisao'])

    def test_delete_formula_preserves_product_and_references_and_allows_recreation(self):
        self.assertEqual(200,self.save().status_code)
        deleted=self.delete()
        self.assertEqual(200,deleted.status_code)
        self.assertTrue(deleted.json['ok'])
        row=next(p for p in self.data()['produtos'] if p['produto_id']==1)
        self.assertEqual(0,row['revisao'])
        self.assertIsNone(row['calculo'])
        self.assertEqual([],row['itens'])
        self.assertEqual(200,self.save().status_code)
        dashboard=self.client.get('/api/custo-produto/dashboard',headers=self.dashboard_headers).json
        self.assertEqual([1],[p['produto_id'] for p in dashboard['produtos']])

    def test_delete_formula_rejects_stale_missing_unauthorized_and_failed_writes(self):
        self.assertEqual(200,self.save().status_code)
        self.assertEqual(409,self.delete(revision=0).status_code)
        self.assertEqual(403,self.delete(headers=self.dashboard_headers).status_code)
        self.fail=True
        with self.assertLogs(level='ERROR'):
            self.assertEqual(500,self.delete().status_code)
        self.fail=False
        self.assertEqual(1,next(p for p in self.data()['produtos'] if p['produto_id']==1)['revisao'])
        self.assertEqual(200,self.delete().status_code)
        self.assertEqual(404,self.delete().status_code)

    def test_product_can_leave_and_return_to_production_list_without_data_loss(self):
        self.assertEqual(200,self.save().status_code)
        self.assertEqual(200,self.hide().status_code)
        row=next(p for p in self.data()['produtos'] if p['produto_id']==1)
        self.assertTrue(row['excluido_custo'])
        self.assertEqual(1,row['revisao'])
        self.assertEqual([],[p['produto_id'] for p in self.client.get('/api/custo-produto/dashboard',headers=self.dashboard_headers).json['produtos']])
        self.assertEqual(200,self.restore().status_code)
        restored=next(p for p in self.data()['produtos'] if p['produto_id']==1)
        self.assertFalse(restored['excluido_custo'])
        self.assertEqual(1,restored['revisao'])
        self.assertEqual([1],[p['produto_id'] for p in self.client.get('/api/custo-produto/dashboard',headers=self.dashboard_headers).json['produtos']])

    def test_product_list_visibility_validates_permission_product_and_rolls_back(self):
        self.assertEqual(403,self.hide(headers=self.dashboard_headers).status_code)
        self.assertEqual(403,self.restore(headers=self.dashboard_headers).status_code)
        self.assertEqual(404,self.hide(5).status_code)
        self.assertEqual(404,self.hide(999).status_code)
        self.fail=True
        with self.assertLogs(level='ERROR'):
            self.assertEqual(500,self.hide().status_code)
        self.fail=False
        self.assertFalse(next(p for p in self.data()['produtos'] if p['produto_id']==1)['excluido_custo'])

    def test_missing_base_and_legacy_recipe_preserved(self):
        c=sqlite3.connect(self.path)
        c.execute('INSERT INTO custo_produto_formulas(produto_id,volume_ml,itens_json) VALUES(1,2000,?)',(json.dumps([{'nome':'Antigo','unidade':'kg','quantidade':'2','preco_unitario':'3'}]),))
        c.execute("UPDATE custo_produto_xarope SET itens_json='[]',rendimento_litros=NULL,revisao=0");c.commit();c.close()
        row=next(p for p in self.data()['produtos'] if p['produto_id']==1)
        self.assertIsNone(row['calculo']);self.assertEqual('Antigo',row['itens'][0]['nome'])
        self.assertEqual(400,self.save(2).status_code)
        self.assertEqual(200,self.base(revision=0).status_code)

    def test_zero_latest_price_requires_provisional_not_legacy_client_value(self):
        self.purchase(20,'Concentrado','0','2026-04-01','L')
        self.assertIsNone(self.save().json['calculo'])
        payload=formula(revision=1);payload['itens'][0]['preco_provisorio']='9'
        saved=self.save(payload=payload).json
        self.assertEqual('provisorio',saved['itens'][0]['fonte_preco'])
        self.assertEqual('9',saved['itens'][0]['preco_unitario'])

    def test_authorization_editor_dashboard_and_anonymous(self):
        for path,method in [('/api/custo-produto','get'),('/api/custo-produto/1','put'),('/api/custo-produto/1','delete'),('/api/custo-produto/produtos/1','delete'),('/api/custo-produto/produtos/1/restaurar','post'),('/api/custo-produto/xarope','put'),('/api/custo-produto/xaropes-compostos','post'),('/api/custo-produto/rateio','put'),('/api/custo-produto/sped','post')]:
            call=getattr(self.client,method)
            self.assertEqual(401,call(path,json={}).status_code)
            self.assertEqual(403,call(path,headers=self.dashboard_headers,json={}).status_code)
        self.assertEqual(403,self.client.get('/api/custo-produto/dashboard',headers=self.headers).status_code)
        self.assertEqual(200,self.client.get('/api/custo-produto/dashboard',headers=self.dashboard_headers).status_code)

    def test_decimal_no_intermediate_rounding_and_volume_inference(self):
        items=[{'quantidade':'.001','preco_unitario':'.001'}]*3
        self.assertEqual(.0015,calcular_formula(2000,items)['custo_1000_litros'])
        for name,volume in [('Uva 2L',2000),('Cola 1,5 L',1500),('GFA 600 ML CX24',600),('Uva',None),('Kit 200 ML e 600 ML',None)]:
            self.assertEqual(volume,volume_sugerido({'nome_produto':name}))

    def test_unit_chain_direct_overhead_unit_and_package_is_coherent(self):
        result=calcular_formula(600,[{'quantidade':'.6','preco_unitario':'.1'}],
        {'custo_lote_exato':'200','rendimento_litros':1250,'itens_sem_custo':0},80,
            20,.5,{'volume_mensal_litros':10000,'capacidade_litros_hora':2000,'itens':[
                {'categoria':'mao_obra','tipo':'mensal','valor':1000},
                {'categoria':'caldeira','tipo':'hora','valor':200},
                {'categoria':'agua','tipo':'litro','valor':.05},
                {'categoria':'impostos','tipo':'percentual','valor':10}]},24)
        self.assertEqual(270,result['custo_1000_litros_sem_rateio'])
        self.assertEqual(547,result['custo_1000_litros'])
        self.assertEqual(.162,result['custo_unidade_sem_rateio'])
        self.assertEqual(.3282,result['custo_unidade'])
        self.assertEqual(3.888,result['custo_pacote_sem_rateio'])
        self.assertEqual(7.8768,result['custo_pacote'])

    def test_500_litre_base_batch_is_scaled_by_finished_beverage_yield(self):
        result=calcular_formula(2000,[],
            {'custo_lote_exato':'1500','rendimento_litros':3750,'itens_sem_custo':0},7560,
            unidades_pacote=6)
        self.assertEqual(400,result['custo_1000_litros_sem_rateio'])
        self.assertEqual(.8,result['custo_unidade_sem_rateio'])
        self.assertEqual(4.8,result['custo_pacote_sem_rateio'])

    def test_one_pet_cap_and_label_are_added_once_per_finished_bottle(self):
        items = [
            {'produto_id':8,'nome':'Tampa','unidade':'un','quantidade':'1','preco_unitario':'.05'},
            {'produto_id':10,'nome':'PET','unidade':'un','quantidade':'1','preco_unitario':'.4'},
            {'produto_id':11,'nome':'Rotulo','unidade':'un','quantidade':'1','preco_unitario':'.02'},
        ]
        result=calcular_formula(2000,items,
            {'custo_lote_exato':'400','rendimento_litros':1000,'itens_sem_custo':0},
            rateio={'itens':[{'categoria':'mao_obra','tipo':'litro','valor':'.1'}]},
            unidades_pacote=6)
        self.assertEqual(.47,result['custo_itens_unidade'])
        self.assertEqual(235,result['custo_itens_1000_litros'])
        self.assertEqual(.8,result['componentes_unidade']['xarope'])
        self.assertEqual(.47,result['componentes_unidade']['embalagem'])
        self.assertEqual(.2,result['componentes_unidade']['mao_obra'])
        self.assertEqual(1.47,result['custo_unidade'])
        self.assertEqual(8.82,result['custo_pacote'])
        self.assertEqual([.05,.4,.02],[item['custo_unidade'] for item in result['itens_unidade']])
        self.assertEqual([.3,2.4,.12],[item['custo_pacote'] for item in result['itens_unidade']])
        self.assertEqual([25,200,10],[item['custo_1000_litros'] for item in result['itens_unidade']])

    def test_preform_milheiro_cost_is_shown_per_bottle_package_and_1000_litres(self):
        # NF-e a R$ 526,50/MIL = R$ 0,5265 por preforma, nao R$ 526,50 por caixa de 8.352.
        result=calcular_formula(2000,[{'produto_id':10,'nome':'Preforma 44 g','unidade':'un',
            'quantidade':'1','preco_unitario':'.5265'}],unidades_pacote=6)
        item=result['itens_unidade'][0]
        self.assertEqual(.5265,item['custo_unidade'])
        self.assertEqual(3.159,item['custo_pacote'])
        self.assertEqual(263.25,item['custo_1000_litros'])
        self.assertEqual(500,result['unidades_1000_litros'])


if __name__=='__main__':unittest.main()
