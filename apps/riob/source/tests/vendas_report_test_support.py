"""Carrega funcoes reais sem startup, imports operacionais ou acesso ao banco."""
import ast
import datetime
import os
from pathlib import Path
import re
import threading
import time
import types
from unittest import mock


def load_sales_server():
    path = Path(__file__).resolve().parents[1] / 'server.py'
    tree = ast.parse(path.read_text())
    names = {
        '_as_int', '_as_float', '_as_str', '_as_bool', '_fmt_date', '_fmt_dt',
        '_parse_data_br', '_vendas_tab_venda_normalizada', '_vendas_row_tab_venda',
        '_vendas_row_eh_bonificacao', '_vendas_litros_para_hectolitros',
        '_vendas_row_hectolitros', '_vendas_comparativo_anual',
        '_vendas_rows_filtradas_base', '_vendas_publicar_opcoes_relatorio',
        '_vendas_anual_consultar_sql', '_coletar_relatorio_vendas_percentual_vendas_anual',
        '_vendas_cache_entry_publico', '_vendas_relatorio_cache_chave',
        '_vendas_relatorio_cache_obter', '_vendas_relatorio_cache_guardar',
        '_vendas_relatorio_cache_limpar',
    }
    nodes = [node for node in tree.body if (
        isinstance(node, ast.FunctionDef) and node.name in names
    ) or (
        isinstance(node, ast.Assign) and any(isinstance(t, ast.Name)
            and t.id.startswith('_VENDAS_RELATORIO_CACHE') for t in node.targets)
    )]
    server = types.ModuleType('sales_test_server')
    server.__dict__.update(datetime=datetime, os=os, re=re, threading=threading,
        time=time, __file__=str(path), get_conn=mock.Mock(),
        _vendas_bonificacoes_cache_path=lambda key: '',
        _vendas_obter_cache_ativo=mock.Mock(), _vendas_db_fetch_import=mock.Mock())
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), server.__dict__)
    return server
