"""Carrega funcoes reais sem startup, imports operacionais ou acesso ao banco."""
import ast
import datetime
from decimal import Decimal
import os
from pathlib import Path
import re
import threading
import time
import types
import unicodedata
from functools import lru_cache
from unittest import mock


def load_sales_server():
    path = Path(__file__).resolve().parents[1] / 'server.py'
    tree = ast.parse(path.read_text())
    names = {
        '_vendas_vendedor_excluido', '_vendas_sql_vendedores_validos', '_vendas_texto_sem_acentos',
        '_normalizar_chave_texto', '_vendas_tipo_vendedor', '_vendas_sql_campos_financeiros',
        '_vendas_sql_categoria_preco_medio_expr', '_vendas_sql_periodo_where', '_vendas_mes_subtrair',
        '_vendas_validar_periodo', '_vendas_cabecalho_resumo', '_vendas_periodo_opcoes',
        '_vendas_bonificacoes_payload', '_vendas_bonificacoes_normalizar_mes', '_vendas_meses_disponiveis_db',
        '_vendas_bonificacoes_agrupar_rows', '_vendas_bonificacoes_resumo_grupos',
        '_vendas_row_financeiro_ajustado', '_vendas_mes_chave', '_vendas_row_eh_devolucao',
        '_vendas_coletar_relatorio_variacao_preco_sql', '_vendas_lista_resumida',
        '_vendas_mix_embalagens_payload', '_vendas_mix_embalagens_grupo_label', '_vendas_mix_embalagens_grupo_relatorio',
        '_vendas_mix_embalagens_cliente_inicial', '_vendas_mix_embalagens_cliente_acumular',
        '_vendas_mix_embalagens_cliente_publico', '_vendas_mix_embalagens_bucket', '_vendas_mix_embalagens_resumo',
        '_coletar_relatorio_vendas_preco_medio', '_vendas_sql_tab_venda_expr',
        '_vendas_relatorio_publico_totais', '_vendas_relatorio_empty_totais',
        '_vendas_formatar_lista_precos', '_vendas_preco_medio_categoria_ordem', '_fmt_money_br',
        '_as_int', '_as_float', '_as_str', '_as_bool', '_fmt_date', '_fmt_dt',
        '_parse_data_br', '_vendas_tab_venda_normalizada', '_vendas_row_tab_venda',
        '_vendas_row_eh_bonificacao', '_vendas_litros_para_hectolitros',
        '_vendas_row_hectolitros', '_vendas_comparativo_anual',
        '_vendas_rows_filtradas_base', '_vendas_publicar_opcoes_relatorio',
        '_vendas_anual_consultar_sql', '_vendas_anual_filtro_sql', '_vendas_anual_ranking_sql', '_vendas_anual_vendas_sql', '_coletar_relatorio_vendas_percentual_vendas_anual',
        '_vendas_cache_entry_publico', '_vendas_relatorio_cache_chave',
        '_vendas_relatorio_cache_obter', '_vendas_relatorio_cache_guardar',
        '_vendas_relatorio_cache_limpar',
    }
    nodes = [node for node in tree.body if (
        isinstance(node, ast.FunctionDef) and node.name in names
    ) or (
        isinstance(node, ast.Assign) and any(isinstance(t, ast.Name)
            and (t.id.startswith('_VENDAS_RELATORIO_CACHE') or t.id == '_VENDAS_AUTONOMOS_NORMALIZADOS') for t in node.targets)
    )]
    import vendas_pdvs
    server = types.ModuleType('sales_test_server')
    server.__dict__.update(datetime=datetime, Decimal=Decimal, os=os, re=re, threading=threading,
        time=time, unicodedata=unicodedata, lru_cache=lru_cache, __file__=str(path), get_conn=mock.Mock(),
        _vendas_bonificacoes_cache_path=lambda key: '',
        vendas_pdvs=types.SimpleNamespace(MIX_TYPES=vendas_pdvs.MIX_TYPES, revisao=lambda connect: (),
            ler_totais=lambda connect: [], base_carteira=vendas_pdvs.base_carteira, resumo_carteira=lambda *args, **kwargs: vendas_pdvs.resumo_carteira(*args, **kwargs)),
        _vendas_obter_cache_ativo=mock.Mock(), _vendas_db_fetch_import=mock.Mock())
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), server.__dict__)
    return server
