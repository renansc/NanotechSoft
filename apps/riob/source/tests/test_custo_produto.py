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
from custo_produto_compras import carregar_compras, precificar_item, ultimas_compras


class Cursor:
    def __init__(self, owner): self.owner=owner;self.raw=owner.raw.cursor()
    def execute(self, sql, args=()):
        if self.owner.fail and 'UPDATE custo_produto_formulas' in sql: raise RuntimeError('Falha simulada')
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
    return {'volume_ml':volume,'revisao':revision,'xarope_litros':dose,'xarope_revisao':1,
            'itens':[{'produto_id':7,'nome':'Nome adulterado','unidade':'l','quantidade':'2','preco_unitario':'999999'}]}


class CustoProdutoTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=str(Path(temp.name)/'custos.sqlite');self.fail=False
        patch=mock.patch('custo_produto.hoje',return_value=dt.date(2026,9,22));patch.start();self.addCleanup(patch.stop)
        c=sqlite3.connect(self.path)
        c.executescript('''
          CREATE TABLE estoque_produtos(id INTEGER PRIMARY KEY,nome_produto TEXT,produto_base_nome TEXT DEFAULT '',grupo_estoque TEXT,ativo INTEGER,unidade TEXT,codigo_barras TEXT DEFAULT '',codigo_produto_nfe TEXT DEFAULT '',fator_embalagem_padrao NUMERIC DEFAULT 1);
          INSERT INTO estoque_produtos(id,nome_produto,grupo_estoque,ativo,unidade) VALUES
           (1,'Uva PET 2 L','PET',1,'UN'),(2,'Uva GFA 600 ML','GFA',1,'UN'),(3,'Laranja PET 200 ML','PET',1,'UN'),
           (4,'Agua 500 ML','AGUA',1,'UN'),(5,'Inativo','INSUMOS',0,'KG'),
           (6,'Acucar','INSUMOS',1,'KG'),(7,'Concentrado','INSUMOS',1,'L'),(8,'Tampa','INSUMOS',1,'UN'),(9,'Aroma','INSUMOS',1,'L');
          CREATE TABLE custo_produto_formulas(produto_id INTEGER PRIMARY KEY,volume_ml NUMERIC,xarope_litros NUMERIC,itens_json TEXT,revisao INTEGER DEFAULT 1,atualizado_por TEXT,atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP);
          CREATE TABLE custo_produto_xarope(id INTEGER PRIMARY KEY,rendimento_litros NUMERIC,itens_json TEXT,revisao INTEGER DEFAULT 0,atualizado_por TEXT DEFAULT '',atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP);
          CREATE TABLE estoque_produto_codigos(produto_id INTEGER,codigo_norm TEXT,ativo INTEGER,origem_tipo TEXT);
          CREATE TABLE estoque_xml_descartes(nota_key TEXT,status TEXT);
          CREATE TABLE estoque_movimentos(id INTEGER PRIMARY KEY,referencia_tipo TEXT,referencia_id INTEGER,tipo_movimento TEXT,nome_produto TEXT,codigo_barras TEXT,codigo_produto_nfe TEXT);
          CREATE TABLE importar_xml_estoque_itens(id INTEGER PRIMARY KEY,chave_nfe TEXT,numero_nota TEXT,serie TEXT DEFAULT '1',emitente_cnpj TEXT DEFAULT '123',emitente_nome TEXT DEFAULT 'Fornecedor',data_emissao TEXT,natureza_operacao TEXT DEFAULT 'Venda',cfop TEXT DEFAULT '5101',codigo_produto TEXT DEFAULT '',descricao_produto TEXT,unidade TEXT,quantidade NUMERIC DEFAULT 1,valor_unitario NUMERIC,dados_json TEXT DEFAULT '{}',tipo_movimento TEXT DEFAULT 'ENTRADA_ESTOQUE',padrao_detectado TEXT DEFAULT 'ENTRADA_FORNECEDOR');
        ''')
        c.execute('INSERT INTO custo_produto_xarope(id,rendimento_litros,itens_json,revisao) VALUES (1,100,?,1)',(json.dumps([{'produto_id':6,'nome':'Acucar','unidade':'kg','quantidade':'100','preco_unitario':'777'}]),))
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

    def test_different_doses_and_shared_yield(self):
        self.save();self.save(2,formula('600',dose='200'))
        data=self.base(50).json
        rows={p['produto_id']:p for p in data['produtos']}
        self.assertEqual(2.08,rows[1]['calculo']['custo_unidade'])
        self.assertEqual(1.224,rows[2]['calculo']['custo_unidade'])
        self.assertEqual(409,self.base().status_code)
        self.assertEqual(409,self.save(3).status_code)

    def test_monthly_last_price_at_cutoff_no_future_or_zero_fabrication(self):
        self.save()
        response=self.client.get('/api/custo-produto/dashboard?ano=2026',headers=self.dashboard_headers)
        self.assertEqual(200,response.status_code)
        self.assertEqual(9,len(response.json['meses']))
        row=next(p for p in response.json['produtos'] if p['produto_id']==1)
        self.assertEqual(.88,row['mensal'][0]['calculo']['custo_unidade'])
        self.assertEqual(1.08,row['mensal'][1]['calculo']['custo_unidade'])
        self.assertEqual(1.08,row['atual']['custo_unidade'])
        old=self.client.get('/api/custo-produto/dashboard?ano=2025',headers=self.dashboard_headers).json
        self.assertTrue(all(m['calculo'] is None for p in old['produtos'] for m in p['mensal']))
        self.assertEqual(400,self.client.get('/api/custo-produto/dashboard?ano=2099',headers=self.dashboard_headers).status_code)

    def test_base_only_and_missing_price_saved_with_pending_cost(self):
        payload=formula();payload['itens']=[]
        self.assertEqual(1,self.save(payload=payload).json['calculo']['custo_unidade'])
        payload=formula();payload['itens'][0]['produto_id']=9
        row=self.save(2,payload).json
        self.assertIsNone(row['calculo']);self.assertTrue(row['pendencias'])
        self.assertIsNone(row['itens'][0]['preco_unitario'])

    def test_kg_grams_and_milheiro_conversion(self):
        payload=formula();payload['itens']=[{'produto_id':6,'unidade':'g','quantidade':'1000'}]
        self.assertEqual('0.005',self.save(payload=payload).json['itens'][0]['preco_unitario'])
        self.purchase(20,'Tampa','50','2026-04-01','MIL')
        payload=formula();payload['itens']=[{'produto_id':8,'unidade':'un','quantidade':'1000'}]
        saved=self.save(2,payload)
        self.assertEqual('0.05',saved.json['itens'][0]['preco_unitario'])
        self.assertEqual(550,saved.json['calculo']['custo_1000_litros'])

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
        series=self.client.get('/api/custo-produto/dashboard?ano=2026',headers=self.dashboard_headers).json
        product=next(p for p in series['produtos'] if p['produto_id']==1)
        self.assertEqual(.388,product['mensal'][6]['calculo']['custo_unidade'])
        self.assertEqual(.392,product['mensal'][8]['calculo']['custo_unidade'])
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
        for volume in [None,0,-1,'NaN']:
            self.assertEqual(400,self.save(payload=formula(volume)).status_code)
        for pid in [4,5,999]:self.assertEqual(404,self.save(pid).status_code)

    def test_stale_recipe_and_failed_write_preserve_saved_formula(self):
        self.save();self.assertEqual(409,self.save().status_code)
        self.fail=True
        with self.assertLogs(level='ERROR'):self.assertEqual(500,self.save(payload=formula(revision=1)).status_code)
        self.assertEqual(1,next(p for p in self.data()['produtos'] if p['produto_id']==1)['revisao'])

    def test_missing_base_and_legacy_recipe_preserved(self):
        c=sqlite3.connect(self.path)
        c.execute('INSERT INTO custo_produto_formulas(produto_id,volume_ml,itens_json) VALUES(1,2000,?)',(json.dumps([{'nome':'Antigo','unidade':'kg','quantidade':'2','preco_unitario':'3'}]),))
        c.execute("UPDATE custo_produto_xarope SET itens_json='[]',rendimento_litros=NULL,revisao=0");c.commit();c.close()
        row=next(p for p in self.data()['produtos'] if p['produto_id']==1)
        self.assertIsNone(row['calculo']);self.assertEqual('Antigo',row['itens'][0]['nome'])
        self.assertEqual(400,self.save(2).status_code)
        self.assertEqual(200,self.base(revision=0).status_code)

    def test_zero_latest_price_not_replaced_by_previous_or_manual_value(self):
        self.purchase(20,'Concentrado','0','2026-04-01','L')
        self.assertIsNone(self.save().json['calculo'])

    def test_authorization_editor_dashboard_and_anonymous(self):
        for path,method in [('/api/custo-produto','get'),('/api/custo-produto/1','put'),('/api/custo-produto/xarope','put')]:
            call=getattr(self.client,method)
            self.assertEqual(401,call(path,json={}).status_code)
            self.assertEqual(403,call(path,headers=self.dashboard_headers,json={}).status_code)
        self.assertEqual(403,self.client.get('/api/custo-produto/dashboard',headers=self.headers).status_code)
        self.assertEqual(200,self.client.get('/api/custo-produto/dashboard',headers=self.dashboard_headers).status_code)

    def test_decimal_no_intermediate_rounding_and_volume_inference(self):
        items=[{'quantidade':'.001','preco_unitario':'.001'}]*3
        self.assertEqual(.000003,calcular_formula(2000,items)['custo_1000_litros'])
        for name,volume in [('Uva 2L',2000),('Cola 1,5 L',1500),('GFA 600 ML CX24',600),('Uva',None),('Kit 200 ML e 600 ML',None)]:
            self.assertEqual(volume,volume_sugerido({'nome_produto':name}))


if __name__=='__main__':unittest.main()
