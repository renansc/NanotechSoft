import ast
import datetime
import sqlite3
import tempfile
import unittest
from io import BytesIO
from decimal import Decimal
from pathlib import Path
from unittest import mock

from flask import Flask
from pypdf import PdfReader
from estoque_contagem import calcular_item, register_estoque_contagem


class Cursor:
    def __init__(self, owner): self.owner=owner; self.raw=owner.raw.cursor()
    def execute(self, sql, args=()):
        if self.owner.fail and 'INSERT INTO estoque_movimentos' in sql and args[3]=='Produto 2':
            raise RuntimeError('Falha simulada no segundo ajuste')
        sql=sql.replace('%s','?').replace(' FOR UPDATE','').replace('NOW()','CURRENT_TIMESTAMP')
        self.raw.execute(sql, tuple(float(v) if isinstance(v,Decimal) else str(v) if hasattr(v,'isoformat') else v for v in args))
        return self
    def fetchone(self):
        row=self.raw.fetchone();return dict(row) if row is not None else None
    def fetchall(self): return [dict(row) for row in self.raw.fetchall()]
    @property
    def lastrowid(self): return self.raw.lastrowid
    def close(self): self.raw.close()


class Connection:
    def __init__(self, path, fail=False):
        self.raw=sqlite3.connect(path);self.raw.row_factory=sqlite3.Row;self.fail=fail
    def cursor(self, **kwargs):return Cursor(self)
    def start_transaction(self, **kwargs):self.raw.execute('BEGIN')
    def commit(self):self.raw.commit()
    def rollback(self):self.raw.rollback()
    def close(self):self.raw.close()


class EstoqueContagemTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/'test.sqlite');self.fail=False
        conn=sqlite3.connect(self.path)
        conn.executescript('''
          CREATE TABLE estoque_contagens(id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER, usuario TEXT, status TEXT DEFAULT 'conferida', observacao TEXT, criado_em TEXT DEFAULT CURRENT_TIMESTAMP, finalizado_em TEXT);
          CREATE TABLE estoque_contagem_resultados(id INTEGER PRIMARY KEY AUTOINCREMENT, contagem_id INTEGER, produto_id INTEGER, produto_key TEXT, nome_produto TEXT, codigo_barras TEXT, codigo_produto_nfe TEXT, saldo_antes NUMERIC, quantidade_contada NUMERIC, pallets NUMERIC, volumes NUMERIC, unidades NUMERIC, por_pallet NUMERIC, por_volume NUMERIC, diferenca NUMERIC, desperdicio NUMERIC, sobra NUMERIC, movimento_id INTEGER, UNIQUE(contagem_id,produto_id));
          CREATE TABLE estoque_movimentos(id INTEGER PRIMARY KEY AUTOINCREMENT, codigo_barras TEXT, codigo_produto_nfe TEXT, numero_nota TEXT, nome_produto TEXT, quantidade NUMERIC, valor_unitario NUMERIC, tipo_movimento TEXT, origem_setor TEXT, destino_setor TEXT, referencia_tipo TEXT, referencia_id INTEGER, usuario_registro TEXT, UNIQUE(referencia_tipo,referencia_id));
          INSERT INTO estoque_movimentos(codigo_produto_nfe,nome_produto,quantidade,tipo_movimento) VALUES ('1','Produto 1',10,'entrada'),('2','Produto 2',20,'entrada');
        ''');conn.close()
        def snapshot(cur, ids, **kwargs):
            result={}
            for pid in ids:
                cur.execute('SELECT COALESCE(SUM(CASE WHEN tipo_movimento=\'entrada\' THEN quantidade ELSE -quantidade END),0) saldo FROM estoque_movimentos WHERE codigo_produto_nfe=%s',(str(pid),))
                result[pid]={'produto_id':pid,'produto_key':str(pid),'nome_produto':f'Produto {pid}', 'codigo_barras':'', 'codigo_produto_nfe':str(pid), 'saldo':cur.fetchone()['saldo'],'por_pallet':10,'por_volume':2,'valor_unitario':7.5}
            return result
        self.snapshot=snapshot
        self.app=Flask(__name__);self.app.config['TESTING']=True
        self.after=mock.Mock()
        register_estoque_contagem(self.app,{'get_conn':lambda:Connection(self.path,self.fail),'snapshot':snapshot,'actor':lambda:'Operador','after_commit':self.after})
        self.client=self.app.test_client()
        self.headers={'X-Usuario-Id':'42','X-Usuario-Perfil':'usuario','X-Usuario-Recursos':'estoque_contagem_finalizar,estoque_contagem_relatorio'}
    def prepare(self, items=None, headers=None):
        return self.client.post('/api/estoque/contagens/conferir',json={'itens':items if items is not None else [{'produto_id':1,'unidades':'8'},{'produto_id':2,'unidades':'25'}]},headers=self.headers if headers is None else headers)
    def finish(self,cid):return self.client.post(f'/api/estoque/contagens/{cid}/finalizar',headers=self.headers)
    def movements(self):
        conn=sqlite3.connect(self.path); rows=conn.execute("SELECT * FROM estoque_movimentos WHERE referencia_tipo='contagem_estoque'").fetchall();conn.close();return rows
    def test_conferencia_nao_ajusta_ate_confirmar_e_finaliza_uma_vez(self):
        preview=self.prepare();self.assertEqual(201,preview.status_code)
        self.assertEqual(2,preview.json['resumo']['desperdicio']);self.assertEqual(5,preview.json['resumo']['sobra'])
        self.assertEqual([],self.movements())
        final=self.finish(preview.json['id']);self.assertEqual(200,final.status_code)
        self.assertEqual('finalizada',final.json['status']);self.assertEqual(2,len(self.movements()))
        repeat=self.finish(preview.json['id']);self.assertEqual(final.json,repeat.json)
        self.assertEqual(2,len(self.movements()));self.after.assert_called_once()
        self.assertTrue(all(row[6]==7.5 for row in self.movements()))
        conn=Connection(self.path); cur=conn.cursor();balances=self.snapshot(cur,[1,2]);conn.close()
        self.assertEqual([8,25],[balances[i]['saldo'] for i in (1,2)])
    def test_produto_nao_informado_fica_fora_e_zero_e_valido(self):
        preview=self.prepare([{'produto_id':1,'unidades':0}]);self.finish(preview.json['id'])
        conn=Connection(self.path);cur=conn.cursor();balances=self.snapshot(cur,[1,2]);conn.close()
        self.assertEqual([0,20],[balances[i]['saldo'] for i in (1,2)])
    def test_saldo_falso_do_cliente_e_ignorado(self):
        response=self.prepare([{'produto_id':1,'unidades':8,'saldo_antes':1000,'desperdicio':992}])
        self.assertEqual(10,response.json['itens'][0]['saldo_antes']);self.assertEqual(2,response.json['itens'][0]['desperdicio'])
    def test_movimentacao_apos_popup_exige_nova_conferencia(self):
        preview=self.prepare();conn=sqlite3.connect(self.path)
        conn.execute("INSERT INTO estoque_movimentos(codigo_produto_nfe,nome_produto,quantidade,tipo_movimento) VALUES ('1','Produto 1',1,'saida')");conn.commit();conn.close()
        self.assertEqual(409,self.finish(preview.json['id']).status_code);self.assertEqual([],self.movements())
    def test_falha_reverte_todos_ajustes_e_contadores(self):
        preview=self.prepare();self.fail=True
        with self.assertLogs(self.app.logger,level='ERROR'):
            self.assertEqual(500,self.finish(preview.json['id']).status_code)
        self.assertEqual([],self.movements())
        report=self.client.get('/api/estoque/contagens/relatorio',headers=self.headers)
        self.assertEqual(0,report.json['resumo']['total']);self.after.assert_not_called()
    def test_permissoes_independentes_e_dono_da_contagem(self):
        self.assertEqual(401,self.prepare(headers={}).status_code)
        read={**self.headers,'X-Usuario-Recursos':'estoque_contagem'}
        self.assertEqual(403,self.prepare(headers=read).status_code)
        self.assertEqual(403,self.client.get('/api/estoque/contagens/relatorio',headers=read).status_code)
        preview=self.prepare();other={**self.headers,'X-Usuario-Id':'43'}
        self.assertEqual(403,self.client.post(f"/api/estoque/contagens/{preview.json['id']}/finalizar",headers=other).status_code)
        self.assertEqual([],self.movements())
    def test_invalidos_duplicados_e_vazios_nao_criam_conferencia(self):
        for items in ([],[{'produto_id':1}], [{'produto_id':1,'unidades':-1}], [{'produto_id':1,'unidades':'NaN'}], [{'produto_id':1,'pallets':.5}], [{'produto_id':1,'unidades':.0001}], [{'produto_id':1,'unidades':1}]*2):
            with self.subTest(items=items):self.assertEqual(400,self.prepare(items).status_code)
        self.assertEqual([],self.movements())
    def test_relatorio_separa_faltas_e_sobras_e_filtra(self):
        self.finish(self.prepare().json['id'])
        for kind, expected in (('',2),('sobra',1),('desperdicio',1),('sem_diferenca',0)):
            result=self.client.get('/api/estoque/contagens/relatorio?tipo='+kind,headers=self.headers)
            self.assertEqual(expected,result.json['resumo']['total'])
        pdf=self.client.get('/api/estoque/contagens/relatorio/pdf?tipo=desperdicio',headers=self.headers)
        self.assertEqual(200,pdf.status_code);self.assertTrue(pdf.data.startswith(b'%PDF'))
        self.assertEqual(400,self.client.get('/api/estoque/contagens/relatorio?inicio=errada',headers=self.headers).status_code)
    def test_conversao_pallet_embalagem_unidade(self):
        result=calcular_item({'por_pallet':100,'por_volume':12,'saldo':150},{'pallets':1,'volumes':3,'unidades':2})
        self.assertEqual(138,result['quantidade_contada']);self.assertEqual(12,result['desperdicio'])

    def test_pdf_inclui_registros_alem_da_primeira_pagina(self):
        preview=self.prepare([{'produto_id':pid,'unidades':1} for pid in range(1,61)])
        self.assertEqual(200,self.finish(preview.json['id']).status_code)
        report=self.client.get('/api/estoque/contagens/relatorio',headers=self.headers).json
        self.assertEqual(60,report['resumo']['total']);self.assertEqual(50,len(report['itens']))
        pdf=self.client.get('/api/estoque/contagens/relatorio/pdf',headers=self.headers)
        reader=PdfReader(BytesIO(pdf.data))
        self.assertGreater(len(reader.pages),1)
        content='\n'.join(page.extract_text() for page in reader.pages)
        for pid in range(1,61):self.assertIn(f'Produto {pid}\n',content)

    def test_conferencia_sem_diferenca_registra_historico_sem_movimento(self):
        preview=self.prepare([{'produto_id':1,'unidades':10}]);self.finish(preview.json['id'])
        self.assertEqual([],self.movements())
        report=self.client.get('/api/estoque/contagens/relatorio?tipo=sem_diferenca',headers=self.headers).json
        self.assertEqual(1,report['resumo']['total'])
        self.assertEqual(0,report['resumo']['desperdicio']);self.assertEqual(0,report['resumo']['sobra'])


class SaldoConferenciaTest(unittest.TestCase):
    def test_consulta_saldos_nao_carrega_importacao_ou_indicadores_de_vendas(self):
        # Executa a funcao real sem importar o servidor e seus agendadores.
        source=Path(__file__).resolve().parents[1]/'server.py'
        node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='_estoque_resumo_produtos_data')
        conn=mock.MagicMock();cur=conn.cursor.return_value
        cur.fetchall.side_effect=[[
            {'nome_produto':'Produto','quantidade_atual':123,'entradas_total':130,'saidas_total':7,'ultimo_movimento_id':1},
        ],[{'id':1,'valor_unitario':7.5}]]
        item={'nome_produto':'Produto','produto_base_key':'OUTROS:PRODUTO','entradas_total':0,'saidas_total':0,
              'saidas_dia':0,'saidas_semana':0,'quantidade_atual':0,'ultimo_valor':0}
        def merge(rows,aliases,row):rows['produto']=item;return item
        sales=mock.Mock(side_effect=AssertionError('Indicadores de vendas nao pertencem a conferencia'))
        namespace={'datetime':datetime,'get_conn':lambda:conn,'_fmt_date':str,'_fmt_dt':lambda v:str(v or ''),
                   '_as_int':lambda v,d=0:int(v or d),'_as_float':lambda v,d=0:float(v or d),'_as_str':lambda v:str(v or ''),
                   '_estoque_mes_deslocar':lambda d,n:d,'_estoque_mes_chave':str,
                   '_carregar_lookup_produtos_estoque':lambda c:{},'_estoque_grupos_map':lambda c:{},
                   '_resolver_produto_lookup_estoque':lambda *a,**kw:{},'_estoque_merge_row':merge,
                   '_estoque_registrar_filtro_fornecedor':lambda *a:None,'_vendas_obter_cache_ativo':sales,
                   '_estoque_aplicar_comprometimentos_vendas_diario':sales}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
        result=namespace['_estoque_resumo_produtos_data'](incluir_fornecedores=False,somente_saldos=True)
        self.assertEqual(123,result['rows'][0]['quantidade_atual'])
        self.assertEqual(7.5,result['rows'][0]['ultimo_valor'])
        sales.assert_not_called();conn.close.assert_called_once();cur.close.assert_called_once()
        self.assertTrue(all(call.args[0].strip().startswith('SELECT') for call in cur.execute.call_args_list))


if __name__=='__main__':unittest.main()
