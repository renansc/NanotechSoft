"""Baixas auditaveis, sem duplicar diferencas de contagem ou movimentos."""
import datetime as dt
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask
from estoque_contagem import register_estoque_contagem, ensure_contagem_schema
from estoque_perdas import register_estoque_perdas, ensure_perdas_schema, hoje
from test_estoque_contagem import Connection


class PerdasTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name)/'perdas.sqlite'); self.fail = False
        self.mysql = os.environ.get('RB_PERDAS_TEST_MYSQL') == '1'
        if self.mysql:
            if os.environ.get('DB_NAME') != 'perdas_test':
                raise RuntimeError('Use somente o banco descartavel perdas_test para esta suite.')
            import mysql.connector
            self.connect = lambda:mysql.connector.connect(host=os.environ['DB_HOST'],user=os.environ['DB_USER'],password=os.environ['DB_PASSWORD'],database=os.environ['DB_NAME'])
            conn=self.connect(); cur=conn.cursor()
            for table in ['estoque_perdas','estoque_contagem_resultados','estoque_contagens','estoque_movimentos','estoque_produtos']:
                cur.execute('DROP TABLE IF EXISTS '+table)
            ensure_perdas_schema(cur); ensure_contagem_schema(cur)
            ensure_perdas_schema(cur)  # startup idempotente
            cur.execute('''CREATE TABLE estoque_movimentos(id INT AUTO_INCREMENT PRIMARY KEY, codigo_barras VARCHAR(120),codigo_produto_nfe VARCHAR(120),numero_nota VARCHAR(120),nome_produto VARCHAR(255),quantidade DECIMAL(12,3),valor_unitario DECIMAL(12,2),tipo_movimento VARCHAR(20),origem_setor VARCHAR(80),destino_setor VARCHAR(80),referencia_tipo VARCHAR(60),referencia_id INT,usuario_registro VARCHAR(180),UNIQUE KEY(referencia_tipo,referencia_id))''')
            cur.execute('CREATE TABLE estoque_produtos(id INT PRIMARY KEY, ativo INT)')
            cur.execute('INSERT INTO estoque_produtos VALUES (1,1),(2,1)')
            cur.execute("INSERT INTO estoque_movimentos(codigo_produto_nfe,nome_produto,quantidade,tipo_movimento) VALUES ('1','Produto 1',10,'entrada'),('2','Produto 2',20,'entrada')")
            conn.commit();cur.close();conn.close()
        else:
            self.connect = lambda:Connection(self.path,self.fail)
            conn=sqlite3.connect(self.path)
            conn.executescript('''
              CREATE TABLE estoque_perdas(id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT DEFAULT 'conferida', produto_id INTEGER,produto_key TEXT,nome_produto TEXT,codigo_barras TEXT,codigo_produto_nfe TEXT,unidade TEXT,grupo_estoque TEXT,data_ocorrencia TEXT,motivo TEXT,justificativa TEXT,pallets NUMERIC,volumes NUMERIC,unidades NUMERIC,por_pallet NUMERIC,por_volume NUMERIC,quantidade NUMERIC,saldo_antes NUMERIC,saldo_depois NUMERIC,usuario_id INTEGER,usuario TEXT,criado_em TEXT DEFAULT CURRENT_TIMESTAMP,finalizado_em TEXT,movimento_id INTEGER);
              CREATE TABLE estoque_contagens(id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER, usuario TEXT,status TEXT DEFAULT 'conferida',observacao TEXT,criado_em TEXT DEFAULT CURRENT_TIMESTAMP,finalizado_em TEXT);
              CREATE TABLE estoque_contagem_resultados(id INTEGER PRIMARY KEY AUTOINCREMENT,contagem_id INTEGER,produto_id INTEGER,produto_key TEXT,nome_produto TEXT,codigo_barras TEXT,codigo_produto_nfe TEXT,saldo_antes NUMERIC,quantidade_contada NUMERIC,pallets NUMERIC,volumes NUMERIC,unidades NUMERIC,por_pallet NUMERIC,por_volume NUMERIC,diferenca NUMERIC,desperdicio NUMERIC,sobra NUMERIC,movimento_id INTEGER);
              CREATE TABLE estoque_movimentos(id INTEGER PRIMARY KEY AUTOINCREMENT,codigo_barras TEXT,codigo_produto_nfe TEXT,numero_nota TEXT,nome_produto TEXT,quantidade NUMERIC,valor_unitario NUMERIC,tipo_movimento TEXT,origem_setor TEXT,destino_setor TEXT,referencia_tipo TEXT,referencia_id INTEGER,usuario_registro TEXT,UNIQUE(referencia_tipo,referencia_id));
              CREATE TABLE estoque_produtos(id INTEGER PRIMARY KEY,ativo INTEGER);
              INSERT INTO estoque_produtos VALUES (1,1),(2,1);
              INSERT INTO estoque_movimentos(codigo_produto_nfe,nome_produto,quantidade,tipo_movimento) VALUES ('1','Produto 1',10,'entrada'),('2','Produto 2',20,'entrada');
            ''');conn.close()
        def snapshot(cur, ids, **kwargs):
            products={}
            for pid in ids:
                if pid not in (1,2): continue
                cur.execute("SELECT SUM(CASE WHEN tipo_movimento='entrada' THEN quantidade ELSE -quantidade END) saldo FROM estoque_movimentos WHERE codigo_produto_nfe=%s",(str(pid),))
                products[pid]={'produto_id':pid,'produto_key':str(pid),'nome_produto':f'Produto {pid}','codigo_barras':'','codigo_produto_nfe':str(pid),'saldo':cur.fetchone()['saldo'],'por_pallet':10,'por_volume':2,'valor_unitario':7.5,'unidade':'UN' if pid==1 else 'KG','grupo_estoque':'PET' if pid==1 else 'MATERIA_PRIMA'}
            return products
        self.snapshot=snapshot
        self.app=Flask(__name__);self.app.config['TESTING']=True
        self.after=mock.Mock()
        services={'get_conn':self.connect,'snapshot':snapshot,'actor':lambda:'Operador teste','after_commit':self.after}
        register_estoque_perdas(self.app,services);register_estoque_contagem(self.app,services)
        self.client=self.app.test_client()
        self.headers={'X-Usuario-Id':'42','X-Usuario-Perfil':'usuario','X-Usuario-Recursos':'estoque_perdas,estoque_contagem_finalizar'}
        self.payload={'produto_id':1,'data_ocorrencia':hoje().isoformat(),'motivo':'avaria','justificativa':'Produto danificado na armazenagem','unidades':2}

    def prepare(self, **changes):
        return self.client.post('/api/estoque/perdas/conferir',json={**self.payload,**changes},headers=self.headers)

    def finish(self,pid,headers=None):
        return self.client.post(f'/api/estoque/perdas/{pid}/finalizar',headers=self.headers if headers is None else headers)

    def stock(self):
        conn=self.connect();cur=conn.cursor(dictionary=True)
        result=self.snapshot(cur,[1,2]);cur.close();conn.close();return result

    def test_confirmacao_idempotente_e_historico_auditavel(self):
        preview=self.prepare();self.assertEqual(201,preview.status_code)
        self.assertEqual(10,self.stock()[1]['saldo'])
        result=self.finish(preview.json['id']);self.assertEqual(200,result.status_code)
        self.assertEqual(8,self.stock()[1]['saldo'])
        self.assertEqual(result.json,self.finish(preview.json['id']).json)
        self.assertEqual(8,self.stock()[1]['saldo']);self.after.assert_called_once()
        history=self.client.get('/api/estoque/perdas',headers=self.headers).json
        self.assertEqual(1,history['total'])
        row=history['itens'][0]
        self.assertEqual((10,8,2),(row['saldo_antes'],row['saldo_depois'],row['quantidade']))
        self.assertEqual('Operador teste',row['usuario']);self.assertEqual(self.payload['justificativa'],row['justificativa'])
        self.assertTrue(row['movimento_id'])

    def test_quantidades_convertidas_e_saldo_do_cliente_ignorado(self):
        preview=self.prepare(volumes=2,unidades=1,saldo_antes=900,saldo_depois=899)
        self.assertEqual(5,preview.json['quantidade']);self.assertEqual(10,preview.json['saldo_antes'])
        self.finish(preview.json['id']);self.assertEqual(5,self.stock()[1]['saldo'])

    def test_perda_atualiza_proxima_contagem_sem_desperdicio_duplicado(self):
        self.finish(self.prepare().json['id'])
        count=self.client.post('/api/estoque/contagens/conferir',json={'itens':[{'produto_id':1,'unidades':8}]},headers=self.headers)
        self.assertEqual(0,count.json['resumo']['desperdicio'])
        result=self.client.post(f"/api/estoque/contagens/{count.json['id']}/finalizar",headers=self.headers)
        self.assertEqual(200,result.status_code);self.assertEqual(8,self.stock()[1]['saldo'])

    def test_perda_invalida_conferencia_de_contagem_aberta(self):
        count=self.client.post('/api/estoque/contagens/conferir',json={'itens':[{'produto_id':1,'unidades':8}]},headers=self.headers)
        self.finish(self.prepare().json['id'])
        self.assertEqual(409,self.client.post(f"/api/estoque/contagens/{count.json['id']}/finalizar",headers=self.headers).status_code)

    def test_conferencias_sobre_mesmo_saldo_exigem_reconferencia(self):
        first=self.prepare(unidades=6);second=self.prepare(unidades=6)
        self.assertEqual(200,self.finish(first.json['id']).status_code)
        self.assertEqual(409,self.finish(second.json['id']).status_code)
        self.assertEqual(4,self.stock()[1]['saldo'])

    def test_invalidos_nao_baixam_nem_admitem_estoque_negativo(self):
        for fields in [{'produto_id':999},{'produto_id':True},{'unidades':11},{'unidades':0},{'unidades':-1}, {'unidades':'NaN'},{'unidades':.0001},{'pallets':.5},{'motivo':'inventado'},{'motivo':[]},{'justificativa':''},{'justificativa':'x'*1001},{'data_ocorrencia':'errada'},{'data_ocorrencia':(hoje()+dt.timedelta(days=1)).isoformat()}]:
            with self.subTest(fields=fields): self.assertEqual(400,self.prepare(**fields).status_code)
        self.assertEqual(10,self.stock()[1]['saldo'])

    def test_sessao_recurso_e_responsavel(self):
        for headers,status in [({},401),({**self.headers,'X-Usuario-Recursos':'estoque'},403)]:
            for path in ['/api/estoque/perdas','/api/estoque/perdas/produtos']:
                self.assertEqual(status,self.client.get(path,headers=headers).status_code)
            self.assertEqual(status,self.client.post('/api/estoque/perdas/conferir',json=self.payload,headers=headers).status_code)
            self.assertEqual(status,self.finish(1,headers).status_code)
        preview=self.prepare()
        self.assertEqual(403,self.finish(preview.json['id'],{**self.headers,'X-Usuario-Id':'43'}).status_code)
        self.assertEqual(200,self.finish(preview.json['id'],{**self.headers,'X-Usuario-Id':'43','X-Usuario-Perfil':'admin'}).status_code)

    def test_rollback_preserva_saldo_e_rascunho(self):
        if self.mysql: self.skipTest('Falha injetada no adaptador SQLite')
        preview=self.prepare(produto_id=2)
        self.fail=True
        with self.assertLogs(self.app.logger,level='ERROR'):
            self.assertEqual(500,self.finish(preview.json['id']).status_code)
        self.fail=False
        self.assertEqual(20,self.stock()[2]['saldo']);self.after.assert_not_called()
        self.assertEqual(0,self.client.get('/api/estoque/perdas',headers=self.headers).json['total'])
        self.assertEqual(200,self.finish(preview.json['id']).status_code)

    def test_filtros_e_totais_separam_unidades(self):
        self.finish(self.prepare().json['id'])
        self.finish(self.prepare(produto_id=2,motivo='desperdicio').json['id'])
        history=self.client.get('/api/estoque/perdas',headers=self.headers).json
        self.assertEqual(2,history['total']);self.assertEqual(2,len(history['totais_unidade']))
        for filters in ['motivo=avaria','q=Produto+1','inicio='+hoje().isoformat()+'&fim='+hoje().isoformat()+'&q=Produto+1']:
            self.assertEqual(1,self.client.get('/api/estoque/perdas?'+filters,headers=self.headers).json['total'])
        for filters in ['inicio=errada','inicio=2026-10-02&fim=2026-10-01','pagina=0','motivo=errado']:
            self.assertEqual(400,self.client.get('/api/estoque/perdas?'+filters,headers=self.headers).status_code)


if __name__=='__main__': unittest.main()
