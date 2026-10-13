"""Filtro real do mix sobre linhas SQL sinteticas, sem startup ou escritas."""
import ast
from copy import deepcopy
from pathlib import Path
import unittest
from unittest import mock

from flask import Flask, jsonify, request
from vendas_report_test_support import load_sales_server


class MixGruposTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = load_sales_server()

    def setUp(self):
        self.s._vendas_relatorio_cache_limpar()
        self.rows = [dict(cliente_norm='A', cliente='Mercado A', cidade='Cidade',
                          numero_nf=str(i), vendedor_key='VENDEDOR', grupo_norm=grupo, itens_agrupados=1)
                     for i, grupo in enumerate(['Pet2L', 'Astuba 2L', 'Pet600Ml', 'Pet200Ml',
                                               'Agua s/ gas', 'Água c/ gás', 'Grf600Ml', 'Grf200Ml'])]
        self.rows.append(dict(cliente_norm='B', cliente='Mercado B', cidade='Cidade',
                              numero_nf='9', vendedor_key='VENDEDOR', grupo_norm='Grf600Ml', itens_agrupados=1))
        self.cursor = mock.Mock()
        self.cursor.fetchall.side_effect = lambda: deepcopy(self.rows)
        self.s.get_conn.return_value.cursor.return_value = self.cursor
        self.patches = [mock.patch.object(self.s, '_vendas_meses_disponiveis_db', return_value=['2026-09']),
                        mock.patch.object(self.s, '_vendas_periodo_opcoes', return_value=([], []))]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def payload(self, grupos=None, cliente=''):
        return self.s._vendas_mix_embalagens_payload({'id': 'mix-test'}, {}, {},
            data_inicio='2026-09-01', data_fim='2026-10-02', filtro_vendedor='VENDEDOR',
            filtro_cliente=cliente, filtro_grupos=grupos)

    def test_all_six_groups_merge_astuba_and_water(self):
        result = self.payload()
        self.assertEqual(6, result['clientes'][0]['qtd_grupos'])
        self.assertEqual(8, result['clientes'][0]['itens'])
        self.assertEqual(8, result['clientes'][0]['notas'])
        self.assertEqual(2, result['resumo_geral']['pdvs'])
        self.assertNotIn('ASTUBA', result['clientes'][0]['grupos_lista'])
        self.assertEqual(1, result['clientes'][0]['grupos'].count('ÁGUA'))
        self.assertEqual(6, len(result['grupos_disponiveis']))
        self.assertEqual(result['clientes'], self.payload(result['grupos_disponiveis'])['clientes'])

    def test_single_groups_and_combined_customer(self):
        for group in ['PET 2L', 'Água']:
            with self.subTest(group=group):
                result = self.payload([group], 'A')
                self.assertEqual(1, result['resumo_geral']['pdvs'])
                self.assertEqual(1, result['detalhe_pdv']['qtd_grupos'])
                self.assertEqual(2, result['detalhe_pdv']['itens'])
                self.assertEqual(2, result['detalhe_pdv']['notas'])
                self.assertEqual([group.upper()], result['detalhe_pdv']['grupos'])

    def test_returnables_can_be_excluded_independently(self):
        all_groups = self.payload()['grupos_disponiveis']
        for excluded in [{'600 ml retornável'}, {'200 ml retornável'}, {'600 ml retornável', '200 ml retornável'}]:
            with self.subTest(excluded=excluded):
                result = self.payload([g for g in all_groups if g not in excluded])
                first = next(c for c in result['clientes'] if c['chave'] == 'A')
                self.assertEqual(6 - len(excluded), first['qtd_grupos'])
                self.assertEqual(8 - len(excluded), first['itens'])
                for group in excluded:
                    self.assertNotIn(group.upper(), first['grupos'])
                for group in {'600 ml retornável', '200 ml retornável'} - excluded:
                    self.assertIn(group.upper(), first['grupos'])
                self.assertEqual(1 if '600 ml retornável' in excluded else 2, result['resumo_geral']['pdvs'])
                # A filtered-out customer stays selectable, without contributing to totals.
                self.assertEqual({'A', 'B'}, {c['chave'] for c in result['clientes_disponiveis']})

    def test_portfolio_denominator_survives_customer_and_group_filters_and_updates(self):
        total = {'value':400}
        with mock.patch.object(self.s.vendas_pdvs, 'ler_totais', side_effect=lambda connect: [
                {'vendedor_key':'VENDEDOR','total':total['value']}]), \
             mock.patch.object(self.s.vendas_pdvs, 'revisao', side_effect=lambda connect: total['value']):
            for groups, customer in [(None,''), (['PET 2L'],'A')]:
                result = self.payload(groups,customer)
                self.assertEqual(400,result['resumo_geral']['total_carteira'])
                occupied = [f for f in result['resumo_faixas'] if f['pdvs']]
                self.assertTrue(all(f['percentual'] == .25 for f in occupied))
            total['value'] = 800
            result = self.payload()
            self.assertEqual(800,result['resumo_geral']['total_carteira'])
            self.assertEqual(.12,result['resumo_faixas'][0]['percentual'])

    def test_empty_selection_and_cache_restore(self):
        all_rows = self.payload()['clientes']
        empty = self.payload([])
        self.assertEqual([], empty['clientes'])
        self.assertEqual(0, empty['resumo_geral']['pdvs'])
        self.assertTrue(all(f['pdvs'] == 0 for f in empty['resumo_faixas']))
        self.assertEqual(all_rows, self.payload()['clientes'])
        self.assertEqual([], self.payload(['PET 2L'], 'B')['clientes'])

    def test_http_filter_and_cache_do_not_mix_selections(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'server.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'relatorio_vendas')
        node.decorator_list = []
        self.s.__dict__.update(request=request, jsonify=jsonify)
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<sales-route>', 'exec'), self.s.__dict__)
        self.s._vendas_obter_cache_ativo.return_value = ({'id': 'mix-test'}, {}, {})
        app = Flask(__name__)
        app.add_url_rule('/report', view_func=self.s.relatorio_vendas)
        with mock.patch.object(self.s, '_vendas_cabecalho_resumo', return_value=[]):
            client = app.test_client()
            for selection, expected in [(None, 2), ('PET 2L', 1), ('', 0), (None, 2), ('Água', 1)]:
                query = dict(tipo_relatorio='grupos_embalagem', data_inicio='2026-09-01', data_fim='2026-10-02')
                if selection is not None:
                    query['grupos'] = selection
                response = client.get('/report', query_string=query)
                self.assertEqual(200, response.status_code, response.json)
                self.assertEqual(expected, response.json['resumo_geral']['pdvs'])


if __name__ == '__main__':
    unittest.main()
