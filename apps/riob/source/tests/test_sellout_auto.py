import ast
import csv
import datetime as dt
import os
from pathlib import Path
import tempfile
import unittest
import threading
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from unittest import mock

from sellout_auto import preparar_mensal, snapshot_estavel, particionar_historico, proxima_leitura_diaria


class SelloutMensalTest(unittest.TestCase):
    def row(self, competencia='09/  2026'):
        return {'Mes&Ano': competencia, 'Cliente': '1-Cliente', 'Produto': '1-Produto',
                'Quantidade': '2', 'Valor Venda': '10'}

    def test_competencia_sem_inventar_dia_de_venda(self):
        row = self.row()
        result = preparar_mensal(list(row), [row])
        self.assertEqual(dt.date(2026, 9, 1), result['rows'][0]['_competencia'])
        self.assertNotIn('Data', result['rows'][0])
        self.assertEqual([(dt.date(2026, 9, 1), dt.date(2026, 10, 1))], result['periodos'])

    def test_historico_preserva_data_real_e_recusa_mes_divergente(self):
        row = {**self.row('06/2025'), 'Data': '17/06/2025'}
        result = preparar_mensal(list(row), [row], preservar_datas=True)
        self.assertEqual(dt.date(2025, 6, 17), result['rows'][0]['_data_real'])
        with self.assertRaises(ValueError):
            preparar_mensal(list(row), [{**row, 'Data': '17/07/2025'}], preservar_datas=True)

    def test_particoes_validadas_antes_de_importar_e_removidas_no_fim(self):
        rows = [{**self.row('12/2025'), 'Produto': 'Água', 'Caixa Física': '2'},
                {**self.row('01/2026'), 'Produto': 'Limão', 'Caixa Física': '3'}]
        with particionar_historico(list(rows[0]), rows) as parts:
            self.assertEqual([1, 1], [p[2] for p in parts])
            with open(parts[0][1], encoding='utf-8', newline='') as handle:
                reader = csv.DictReader(handle, delimiter=';')
                restored = preparar_mensal(reader.fieldnames, reader, preservar_datas=True)['rows'][0]
                self.assertEqual('Água', restored['Produto'])
                self.assertEqual('2', restored['Caixa Física'])
            paths = [Path(p[1]) for p in parts]
            self.assertTrue(all(p.exists() for p in paths))
        self.assertFalse(any(p.exists() for p in paths))
        with self.assertRaises(ValueError):
            with particionar_historico(list(rows[0]), rows + [self.row('invalido')]):
                self.fail('Nao deve liberar particoes de um historico invalido')

    def test_multiplos_meses_e_virada_do_ano(self):
        rows = [self.row('12/2025'), self.row('01/2026'), self.row('12/2025')]
        result = preparar_mensal(list(rows[0]), rows)
        self.assertEqual(3, len(result['rows']))  # Linhas iguais podem ser legitimas.
        self.assertEqual([(dt.date(2025, 12, 1), dt.date(2026, 1, 1)),
                          (dt.date(2026, 1, 1), dt.date(2026, 2, 1))], result['periodos'])

    def test_rejeita_vazio_incompleto_e_competencia_invalida(self):
        for rows in [[], [self.row('')], [self.row('13/2026')],
                     [{**self.row(), 'Quantidade': None}], [{**self.row(), None: ['extra']}]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                preparar_mensal(list(self.row()), rows)
        with self.assertRaises(ValueError):
            preparar_mensal(['Data'], [self.row()])

    def test_snapshot_assinatura_por_conteudo_e_limpeza(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.csv'
            path.write_text('teste')
            os.utime(path, (1000, 1000))
            with snapshot_estavel(path) as (snapshot, first, _):
                self.assertEqual('teste', Path(snapshot).read_text())
            self.assertFalse(Path(snapshot).exists())
            os.utime(path, (2000, 2000))
            with snapshot_estavel(path) as (_, second, _):
                self.assertEqual(first, second)
            path.write_text('outro')
            with self.assertRaises(ValueError):
                with snapshot_estavel(path):
                    pass

    def test_snapshot_recusa_arquivo_alterado_durante_copia(self):
        import shutil
        original = shutil.copyfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.csv'
            path.write_text('teste')
            os.utime(path, (1000, 1000))
            def copy(source, target):
                original(source, target)
                path.write_text('mudou durante leitura')
            with mock.patch('sellout_auto.shutil.copyfile', side_effect=copy), self.assertRaises(ValueError):
                with snapshot_estavel(path):
                    pass


class PersistenciaMensalTest(unittest.TestCase):
    """Executa a funcao real sem startup do monolito ou acesso ao banco operacional."""
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'server.py'
        tree = ast.parse(source.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == '_vendas_importar_csv_para_cache')
        self.conn, self.cur = mock.Mock(), mock.Mock()
        self.conn.cursor.return_value = self.cur
        self.cur.fetchone.side_effect = [(1,), None, (2,), (1,)]
        self.env = dict(os=os, datetime=dt, get_conn=lambda: self.conn,
            _as_str=lambda x: str(x or ''), _as_int=lambda x, default=0: int(x or default),
            _as_float=lambda x, default=0.: float(x or default),
            _vendas_importacao_meta=lambda *a: ('original', {}),
            _vendas_db_upsert_import_meta=mock.Mock(),
            _vendas_import_regras_carregar=lambda: {},
            _vendas_import_colunas_efetivas=lambda *a: [],
            _vendas_import_reter_colunas=lambda row, cols: row,
            _vendas_grupo_deve_descartar=lambda *a: False,
            _vendas_normalizar_linha=lambda raw: {'quantidade': raw['Quantidade']},
            _vendas_grupo_normalizado=lambda *a: 'PET',
            _vendas_texto_sem_acentos=lambda x: x,
            _parse_data_br=lambda x: None,
            _vendas_bonificacoes_cache_limpar=mock.Mock(),
            _vendas_mix_embalagens_cache_limpar=mock.Mock(),
            _vendas_relatorio_cache_limpar=mock.Mock(),
            _vendas_db_fetch_import=lambda key: {'id': key},
        )
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), self.env)
        row = SelloutMensalTest().row()
        self.mensal = preparar_mensal(list(row), [row, row])
        self.mensal['meta'] = dict(source_signature='sha256', source_path='smb-montado',
            source_name='SELLOUT_M.CSV', source_size=100, source_mtime=dt.datetime(2026, 9, 9))
        self.path = str(source)

    def run_import(self):
        return self.env['_vendas_importar_csv_para_cache'](self.path, mensal=self.mensal)

    def test_atualiza_so_mes_presente_com_meta_no_mesmo_commit(self):
        self.assertEqual({'id': 'sellout-mensal-continuo'}, self.run_import())
        deletes = [c for c in self.cur.execute.call_args_list if c.args[0].startswith('DELETE')]
        self.assertEqual(1, len(deletes))
        self.assertEqual(('sellout-mensal-continuo', dt.date(2026, 9, 1), dt.date(2026, 10, 1)), deletes[0].args[1])
        inserted = self.cur.executemany.call_args.args[1]
        self.assertEqual(2, len(inserted))
        self.assertEqual('09/2026 (mensal)', inserted[0][2])
        self.conn.commit.assert_called_once()
        self.env['_vendas_db_upsert_import_meta'].assert_not_called()

    def test_repeticao_nao_insere_nem_apaga(self):
        self.cur.fetchone.side_effect = [(1,), ('sha256',), (1,)]
        self.assertIsNone(self.run_import())
        self.cur.executemany.assert_not_called()
        self.conn.commit.assert_not_called()
        self.assertFalse(any(c.args[0].startswith('DELETE') for c in self.cur.execute.call_args_list))

    def test_falha_na_gravacao_reverte_mes_e_preserva_metadados(self):
        self.cur.executemany.side_effect = RuntimeError('banco indisponivel')
        with self.assertRaises(RuntimeError):
            self.run_import()
        self.conn.rollback.assert_called_once()
        self.conn.commit.assert_not_called()
        self.env['_vendas_db_upsert_import_meta'].assert_not_called()
        self.conn.close.assert_called_once()

    def test_historico_so_acrescenta_meses_ausentes_sem_apagar(self):
        self.mensal['somente_ausentes'] = True
        self.cur.fetchone.side_effect = [(1,), ('fingerprint-atual',), (7719,), (1,)]
        self.cur.fetchall.return_value = [(2026, 8)]
        self.mensal['rows'][0]['_data_real'] = dt.date(2026, 9, 17)
        self.run_import()
        self.assertFalse(any(c.args[0].startswith('DELETE') for c in self.cur.execute.call_args_list))
        inserted = self.cur.executemany.call_args.args[1]
        self.assertEqual(dt.date(2026, 9, 17), inserted[0][1])
        self.assertEqual('17/09/2026', inserted[0][2])
        updates = [c.args[0] for c in self.cur.execute.call_args_list if 'UPDATE vendas_relatorios_importados SET' in c.args[0]]
        self.assertEqual(1, len(updates))
        self.assertNotIn('source_signature=', updates[0])
        self.assertTrue(any('INSERT INTO vendas_sellout_historico' in c.args[0] for c in self.cur.execute.call_args_list))
        self.conn.commit.assert_called_once()

    def test_historico_repetido_preserva_mes_existente(self):
        self.mensal['somente_ausentes'] = True
        self.cur.fetchone.side_effect = [(1,), ('fingerprint-atual',), (1,)]
        self.cur.fetchall.return_value = [(2026, 9)]
        self.assertIsNone(self.run_import())
        self.cur.executemany.assert_not_called()
        self.conn.commit.assert_not_called()

    def test_outro_worker_com_lock_impede_importacao_concorrente(self):
        self.cur.fetchone.side_effect = [(0,), (0,)]
        self.assertIsNone(self.run_import())
        self.cur.executemany.assert_not_called()
        self.conn.commit.assert_not_called()


class ConsultaMensalTest(unittest.TestCase):
    def test_meses_do_banco_tem_ano_e_mes_reais(self):
        source = Path(__file__).resolve().parents[1] / 'server.py'
        tree = ast.parse(source.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_vendas_meses_disponiveis_db')
        conn = mock.Mock()
        conn.cursor.return_value.fetchall.return_value = [(202506,), (202512,), (202601,), (202609,)]
        env = dict(get_conn=lambda: conn, _vendas_relatorio_cache_chave=lambda *args: args,
                   _vendas_relatorio_cache_obter=lambda key: None, _vendas_relatorio_cache_guardar=mock.Mock())
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), env)
        self.assertEqual(['2025-06', '2025-12', '2026-01', '2026-09'], env['_vendas_meses_disponiveis_db']('sellout-mensal-continuo'))

    def test_nova_assinatura_invalida_projecoes_em_outros_processos(self):
        source = Path(__file__).resolve().parents[1] / 'server.py'
        tree = ast.parse(source.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == '_vendas_relatorio_cache_chave')
        fetch = mock.Mock(return_value={'source_signature': 'primeira'})
        env = dict(_as_str=lambda x: str(x or ''), _vendas_db_fetch_import=fetch)
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), env)
        key = env['_vendas_relatorio_cache_chave']
        first = key('resumo', 'sellout-mensal-continuo')
        fetch.return_value = {'source_signature': 'segunda'}
        self.assertNotEqual(first, key('resumo', 'sellout-mensal-continuo'))
        before_history = key('resumo', 'sellout-mensal-continuo')
        fetch.return_value['rows_importadas'] = 20000
        self.assertNotEqual(before_history, key('resumo', 'sellout-mensal-continuo'))
        self.assertEqual(key('resumo', 'legado'), key('resumo', 'legado'))

    def test_consultas_mensais_geram_projecao_sem_processamento_manual(self):
        source = Path(__file__).resolve().parents[1] / 'server.py'
        tree = ast.parse(source.read_text())
        names = ['_vendas_cache_bonificacoes_carregar', '_vendas_cache_mix_embalagens_carregar']
        for name in names:
            function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
            conn = mock.Mock()
            conn.cursor.return_value.fetchall.return_value = []
            env = dict(_as_str=str, get_conn=lambda: conn,
                _vendas_bonificacoes_cache_load=lambda key: None,
                _vendas_mix_embalagens_cache_load=lambda key: None,
                _vendas_bonificacoes_cache_carregar_rows_db=lambda key: [],
                _vendas_bonificacoes_cache_carregar_rows_mes_db=mock.Mock(return_value=[]),
                _vendas_meses_disponiveis_db=lambda key: ['2025-06', '2026-09'],
                _vendas_bonificacoes_normalizar_mes=lambda mes, *args: mes or '2026-09',
                _vendas_relatorio_cache_chave=lambda *args, **kwargs: args,
                _vendas_relatorio_cache_obter=lambda key: None,
                _vendas_relatorio_cache_guardar=mock.Mock(),
                _vendas_bonificacoes_cache_processar=lambda *args: {'months': {}},
                _vendas_mix_embalagens_cache_processar=lambda *args: {'months': {}})
            exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), env)
            with self.subTest(name=name):
                result = env[name]({'id': 'sellout-mensal-continuo'}, {}, {}, allow_rebuild=False)
                self.assertEqual({}, result['months'])
                if name == '_vendas_cache_bonificacoes_carregar':
                    self.assertEqual(['2025-06', '2026-09'], result['months_order'])
                    env['_vendas_bonificacoes_cache_carregar_rows_mes_db'].assert_called_once_with('sellout-mensal-continuo', '2026-09', somente_resumo=True)
                    env[name]({'id': 'sellout-mensal-continuo'}, {}, {}, allow_rebuild=False, mes='2025-06')
                    env['_vendas_bonificacoes_cache_carregar_rows_mes_db'].assert_called_with('sellout-mensal-continuo', '2025-06', somente_resumo=True)
                self.assertIsNone(env[name]({'id': 'legado'}, {}, {}, allow_rebuild=False))


class AgendaELeituraManualTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(__file__).resolve().parents[1] / 'server.py'
        cls.tree = ast.parse(cls.source.read_text())

    def functions(self, names, env):
        nodes = [node for node in self.tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        for node in nodes:
            node.decorator_list = []
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(self.source), 'exec'), env)
        return env

    def test_agenda_diaria_as_oito_sem_leitura_imediata_apos_horario(self):
        zone = ZoneInfo('America/Sao_Paulo')
        for now, expected in ((dt.datetime(2026, 9, 11, 7, 59, tzinfo=zone), dt.datetime(2026, 9, 11, 8, tzinfo=zone)),
                              (dt.datetime(2026, 9, 11, 9, tzinfo=zone), dt.datetime(2026, 9, 12, 8, tzinfo=zone)),
                              (dt.datetime(2026, 12, 31, 23, tzinfo=zone), dt.datetime(2027, 1, 1, 8, tzinfo=zone))):
            self.assertEqual(expected, proxima_leitura_diaria(now))

    def test_loop_aguarda_oito_e_nao_repete_em_quinze_minutos(self):
        class StopLoop(BaseException):
            pass
        zone = ZoneInfo('America/Sao_Paulo')
        clock = mock.Mock()
        clock.datetime.now.side_effect = [dt.datetime(2026, 9, 11, 7, 59, tzinfo=zone),
            dt.datetime(2026, 9, 11, 7, 59, tzinfo=zone), dt.datetime(2026, 9, 11, 8, tzinfo=zone),
            dt.datetime(2026, 9, 11, 8, 1, tzinfo=zone), dt.datetime(2026, 9, 11, 8, 16, tzinfo=zone)]
        importer = mock.Mock()
        def sleep(seconds):
            if clock.datetime.now.call_count == 2:
                importer.assert_not_called()
            else:
                raise StopLoop()
        env = self.functions(['_vendas_sellout_mensal_loop'], dict(datetime=clock, ZoneInfo=ZoneInfo,
            proxima_leitura_diaria=proxima_leitura_diaria, time=SimpleNamespace(sleep=sleep),
            _vendas_sellout_mensal_importar=importer, app=mock.Mock()))
        with self.assertRaises(StopLoop):
            env['_vendas_sellout_mensal_loop']()
        importer.assert_called_once_with()

    def folder_env(self):
        return self.functions(['_vendas_diario_importar_pasta'], dict(
            _VENDAS_DIARIO_IMPORT_LOCK=threading.Lock(), VENDAS_DIARIO_TXT_DIR='txt',
            VENDAS_DIARIO_PDF_DIR='pdf', VENDAS_DIARIO_DIR='pastas', os=os,
            discover_txt_files=lambda _: ['vendas.txt'],
            _descobrir_arquivos_por_extensao=lambda *args: ['carga.pdf'],
            _vendas_diario_importar_arquivo=mock.Mock(return_value={'status':'importado'}),
            parse_cargas_pdf=lambda _: [{'pagina':1}],
            _vendas_diario_importar_carga_pdf_arquivo=mock.Mock(return_value={'status':'importado'}),
            _vendas_diario_unificar_cards_semelhantes=lambda: {},
            _vendas_sellout_mensal_importar=mock.Mock(return_value={'status':'ja_importado'}),
            _as_str=lambda value: str(value or ''), app=mock.Mock()))

    def test_varredura_periodica_txt_pdf_nao_dispara_sellout(self):
        env = self.folder_env()
        result = env['_vendas_diario_importar_pasta']()
        env['_vendas_sellout_mensal_importar'].assert_not_called()
        self.assertEqual(2, result['arquivos'])

    def test_leitura_manual_inclui_sellout_sem_depender_da_janela(self):
        env = self.folder_env()
        result = env['_vendas_diario_importar_pasta'](incluir_sellout=True)
        env['_vendas_sellout_mensal_importar'].assert_called_once_with()
        self.assertEqual(3, result['arquivos'])
        self.assertEqual('ja_importado', result['sellout']['status'])
        self.assertEqual({'txt','pdf','sellout'}, {item['tipo'] for item in result['resultados']})

    def test_falha_do_sellout_nao_interrompe_txt_pdf(self):
        env = self.folder_env()
        env['_vendas_sellout_mensal_importar'].side_effect = OSError('Arquivo indisponivel')
        result = env['_vendas_diario_importar_pasta'](incluir_sellout=True)
        self.assertEqual('erro', result['sellout']['status'])
        self.assertEqual(2, sum(item['status']=='importado' for item in result['resultados']))
        self.assertFalse(env['_VENDAS_DIARIO_IMPORT_LOCK'].locked())

    def test_rota_do_botao_inclui_sellout(self):
        importer = mock.Mock(return_value={'processando':False})
        env = self.functions(['vendas_diario_importar_api'], dict(
            request=SimpleNamespace(files={}), jsonify=lambda result: result,
            _vendas_diario_importar_pasta=importer))
        self.assertEqual(({'processando':False},200), env['vendas_diario_importar_api']())
        importer.assert_called_once_with(incluir_sellout=True)

    def test_retorno_mensal_distingue_atualizacao_repeticao_e_concorrencia(self):
        entry = {'id':'sellout-mensal-continuo', 'rows_importadas':10, 'status':'pronto', 'source_signature':'hash|regras'}
        for saved, previous, status in ((entry, entry, 'importado'), (None, entry, 'ja_importado'), (None, {}, 'processando')):
            snapshot = mock.MagicMock()
            snapshot.return_value.__enter__.return_value = ('temporario.csv', 'hash', SimpleNamespace(st_size=100, st_mtime=1000))
            env = self.functions(['_vendas_sellout_mensal_importar'], dict(os=os, datetime=dt,
                _carregar_vendas_config=lambda: {'habilitado':True, 'active_cache_id':'sellout-mensal-continuo'},
                snapshot_estavel=snapshot, _vendas_relatorio_dict_rows=lambda _: ([], []),
                preparar_mensal=lambda *args: {}, _vendas_import_regras_assinatura=lambda: 'regras',
                _vendas_importar_csv_para_cache=mock.Mock(return_value=saved),
                _vendas_db_fetch_import=lambda _: previous, _vendas_cache_set_active=mock.Mock(), app=mock.Mock()))
            self.assertEqual(status, env['_vendas_sellout_mensal_importar']()['status'])
            if status != 'importado':
                env['_vendas_cache_set_active'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
