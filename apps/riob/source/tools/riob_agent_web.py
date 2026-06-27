#!/usr/bin/env python3
"""App web independente do assistente operacional RioBranco."""

from __future__ import annotations

import argparse
import contextvars
import datetime
import html
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import webbrowser
from collections import Counter
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import ssl
import urllib.error
import urllib.request
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests

import types

try:
    import mysql.connector
except Exception:  # pragma: no cover - optional dependency in local test env
    mysql = types.SimpleNamespace(
        connector=types.SimpleNamespace(
            connect=None,
        )
    )


ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "server.py").exists() and Path("/srv/riob/server.py").exists():
    ROOT = Path("/srv/riob")
AGENT = ROOT / "riob-agent.sh"
TOOLS_DIR = ROOT / "tools" if (ROOT / "tools").exists() else Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from riob_context import build_environment_inventory, build_repo_context, build_repo_manifest, build_system_overview, build_task_brief, format_environment_inventory, format_repo_context, format_repo_manifest, format_repo_sources, format_system_overview, format_task_brief, system_overview_actions

COMMAND_TIMEOUT = 1800
OUTPUT_LIMIT = 24000
LLM_HISTORY_LIMIT = 12
LLM_MAX_TOKENS = 2000

_current_request_headers_var = contextvars.ContextVar("current_request_headers", default={})

FRETE_STATUS = {
    "chegada": "Chegada na empresa",
    "descarregado": "Descarregado Aguardando Carga",
    "liberado": "Liberado para Carregar",
    "carregando": "Carregando",
    "carregado": "Carregado Liberado P Viajem",
    "entregando": "Entregando",
    "retornando": "Retornando",
    "paradoVasio": "Parado (vazio)",
    "paradoCarregado": "Parado (carregado)",
}

DEVOLUCAO_ITEMS = {
    "c24": ["c24", "cx24", "cx 24", "caixa 24", "caixas 24", "fardo 24"],
    "c48": ["c48", "cx48", "cx 48", "caixa 48", "caixas 48", "fardo 48"],
    "pet2l": [
        "pet2l", "pet 2l", "pet 2 l", "pet 2", "pet2", "2l", "2 litros", "2l pet", "2 litros pet",
        "garrafa 2l", "garrafa 2 litros",
    ],
    "pet600": ["pet600", "pet 600", "pc600", "pc 600", "600ml", "600 ml", "600 pet", "garrafa 600", "garrafa 600 ml"],
    "pet200": ["pet200", "pet 200", "200ml", "200 ml", "200 pet", "garrafa 200", "garrafa 200 ml", "garrafinha 200"],
    "agua_com_gas": ["agua com gas", "agua c gas", "agua c/gas", "com gas", "comgas", "cg"],
    "agua_sem_gas": ["agua sem gas", "agua s gas", "agua s/gas", "sem gas", "semgas", "sg"],
    "cx_600": ["cx600", "cx 600", "caixa 600", "caixas 600", "caixa de 600", "fardo 600"],
}

DEVOLUCAO_QUANTITY_QUALIFIERS = {
    "dz",
    "duzia",
    "duzias",
    "uni",
    "und",
    "unidade",
    "unidades",
    "pacote",
    "pacotes",
    "pct",
    "pcts",
}

DEVOLUCAO_NUMBER_WORDS = {
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "três": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "catorze": 14,
    "quatorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezessete": 17,
    "dezoito": 18,
    "dezenove": 19,
    "vinte": 20,
}

DEVOLUCAO_OBS_MARKERS = {
    "obs",
    "observacao",
    "observacoes",
    "observação",
    "observações",
}

DEVOLUCAO_WORDS = {
    "devolucao",
    "devolocao",
    "devolucoes",
    "devolocoes",
    "devolução",
    "devoluções",
}

DEVOLUCAO_ACTION_WORDS = {
    "lancar",
    "lanca",
    "lançar",
    "lança",
    "registrar",
    "registra",
    "criar",
    "nova",
}

_pending_devolucao_confirmations: dict[str, dict] = {}


def set_current_request_headers(headers: dict[str, str]):
    return _current_request_headers_var.set(dict(headers or {}))


def reset_current_request_headers(token) -> None:
    _current_request_headers_var.reset(token)


def current_request_headers() -> dict[str, str]:
    return dict(_current_request_headers_var.get({}) or {})


def _agent_db_config() -> dict[str, object]:
    def _env(name: str, default: str = "") -> str:
        value = os.environ.get(name)
        return value if value is not None and str(value).strip() else default

    def _env_int(name: str, default: int) -> int:
        try:
            raw = os.environ.get(name)
            return int(raw) if raw is not None and str(raw).strip() else int(default)
        except Exception:
            return int(default)

    return {
        "host": _env("DB_HOST", "db"),
        "user": _env("DB_USER", "riobranco"),
        "password": _env("DB_PASSWORD", "riobranco123"),
        "database": _env("DB_NAME", "riobranco"),
        "port": _env_int("DB_PORT", 3306),
    }


def _agent_db_connect():
    return mysql.connector.connect(**_agent_db_config())


AGENT_FRETE_SELECT_SQL = """
    SELECT
        f.id,
        f.nome,
        f.cidade,
        f.data_carga,
        f.status,
        f.motorista_id,
        f.entregador_id,
        f.colaborador_motorista_id,
        f.colaborador_entregador_id,
        f.veiculo_id,
        f.carga_id,
        f.observacao,
        f.km_atual,
        f.peso,
        f.qtd_entregas,
        f.created_at,
        f.updated_at,
        f.finalizado_em,
        f.arquivado,
        cm.nome AS colaborador_motorista_nome,
        ce.nome AS colaborador_entregador_nome,
        m.nome AS motorista_nome,
        e.nome AS entregador_nome,
        v.nome AS veiculo_nome,
        v.placa AS veiculo_placa,
        c.nome AS carga_nome,
        c.cidade AS carga_cidade,
        c.rota AS carga_rota,
        c.veiculo_numero AS carga_veiculo_numero,
        c.origem_csv AS carga_origem_csv,
        c.registros_importados AS carga_registros_importados,
        c.clientes_distintos AS carga_clientes_distintos,
        c.quantidade_total AS carga_quantidade_total,
        c.litros_total AS carga_litros_total,
        c.peso_total AS carga_peso_total,
        c.valor_total AS carga_valor_total,
        c.atualizado_em AS carga_atualizado_em,
        cil.carga_cidades AS carga_cidades,
        COALESCE(f.veiculo_id, vr.id) AS veiculo_id_resolvido,
        COALESCE(v.nome, vr.nome) AS veiculo_nome_resolvido,
        COALESCE(v.placa, vr.placa) AS veiculo_placa_resolvida
    FROM fretes f
    LEFT JOIN colaboradores cm ON f.colaborador_motorista_id = cm.id
    LEFT JOIN colaboradores ce ON f.colaborador_entregador_id = ce.id
    LEFT JOIN motoristas m ON f.motorista_id = m.id
    LEFT JOIN motoristas e ON f.entregador_id = e.id
    LEFT JOIN veiculos v ON f.veiculo_id = v.id
    LEFT JOIN cargas c ON f.carga_id = c.id
    LEFT JOIN (
        SELECT x.carga_id, GROUP_CONCAT(x.cidade ORDER BY x.primeira_linha SEPARATOR ' - ') AS carga_cidades
        FROM (
            SELECT carga_id, cidade, MIN(linha_num) AS primeira_linha
            FROM cargas_import_linhas
            WHERE TRIM(COALESCE(cidade, '')) <> ''
            GROUP BY carga_id, cidade
        ) x
        GROUP BY x.carga_id
    ) cil ON cil.carga_id = c.id
    LEFT JOIN veiculos vr ON TRIM(COALESCE(vr.nome, '')) = TRIM(COALESCE(c.veiculo_numero, ''))
        OR TRIM(COALESCE(vr.placa, '')) = TRIM(COALESCE(c.veiculo_numero, ''))
"""


def _pending_devolucao_key() -> str:
    headers = current_request_headers()
    usuario_id = str(headers.get("X-Usuario-Id") or "").strip()
    if usuario_id:
        return f"id:{usuario_id}"
    login = normalize(str(headers.get("X-Usuario-Login") or ""))
    if login:
        return f"login:{login}"
    return "anon"


def _get_pending_devolucao_confirmation() -> dict:
    return _pending_devolucao_confirmations.get(_pending_devolucao_key()) or {}


def _set_pending_devolucao_confirmation(ctx: dict) -> None:
    key = _pending_devolucao_key()
    if ctx:
        _pending_devolucao_confirmations[key] = ctx
    else:
        _pending_devolucao_confirmations.pop(key, None)


OPTIONS = {
    "status": {
        "title": "Status geral",
        "summary": "Mostra a situacao do Git, os containers app/proxy e o ultimo backup encontrado.",
        "details": (
            "Use quando quiser saber se existe alteracao pendente, se o sistema esta rodando "
            "e qual foi o ultimo backup SQL salvo."
        ),
        "command": ["status"],
        "safe": True,
        "needs_message": False,
    },
    "backup": {
        "title": "Backup SQL",
        "summary": "Gera um dump do banco pelo endpoint interno /api/backup.",
        "details": (
            "Ele salva o arquivo em backupsSql/. E a primeira coisa recomendada antes de "
            "deploy, update ou sincronizacao."
        ),
        "command": ["backup"],
        "safe": True,
        "needs_message": False,
    },
    "git": {
        "title": "Enviar para o Git",
        "summary": "Faz stage seguro, commit e push para a branch atual.",
        "details": (
            "O stage ignora .env, backups, certificados, relatorios e dados locais de camera. "
            "Precisa de uma mensagem curta de commit."
        ),
        "command": ["-y", "git", "-m"],
        "safe": False,
        "needs_message": True,
    },
    "ship": {
        "title": "Fluxo completo",
        "summary": "Executa backup, commit, push e deploy local em sequencia.",
        "details": (
            "E o atalho do dia a dia depois de uma mudanca pronta. Precisa de mensagem de commit "
            "e deve ser usado com atencao porque publica e reinicia app/proxy."
        ),
        "command": ["-y", "ship", "-m"],
        "safe": False,
        "needs_message": True,
    },
    "deploy": {
        "title": "Deploy local",
        "summary": "Gera backup e sobe app/proxy com build.",
        "details": (
            "Usa ./up.sh por baixo, sem derrubar o banco. Ao final tenta validar /api/status."
        ),
        "command": ["deploy"],
        "safe": False,
        "needs_message": False,
    },
    "update": {
        "title": "Atualizar do GitHub",
        "summary": "Gera backup, faz git pull e aplica deploy via update.sh.",
        "details": (
            "Use em uma VM que precisa receber a versao mais nova da branch atual."
        ),
        "command": ["update"],
        "safe": False,
        "needs_message": False,
    },
    "logs": {
        "title": "Logs",
        "summary": "Mostra as ultimas linhas dos containers app e proxy.",
        "details": "Bom para investigar erro depois de deploy, tela quebrada ou API sem resposta.",
        "command": ["logs", "--tail", "200", "app", "proxy"],
        "safe": True,
        "needs_message": False,
    },
    "doctor": {
        "title": "Diagnostico",
        "summary": "Confere Git, Docker, .env, compose e ultimo backup.",
        "details": "Use quando algo basico parece fora do lugar antes de mexer no sistema.",
        "command": ["doctor"],
        "safe": True,
        "needs_message": False,
    },
    "brief": {
        "title": "Brief do pedido",
        "summary": "Gera um brief curto com arquivos provaveis, fluxo e validacao sugerida.",
        "details": (
            "Use quando quiser analisar um pedido antes de editar. "
            "O resultado aponta o caminho mais curto para trabalhar com mais coerencia."
        ),
        "command": ["brief"],
        "safe": True,
        "needs_message": True,
    },
    "validate": {
        "title": "Validacao rapida",
        "summary": "Executa compileall, unittest e pip check.",
        "details": "Use depois de mudar codigo para confirmar que o baseline continua saudavel.",
        "command": ["validate"],
        "safe": True,
        "needs_message": False,
    },
    "sync-homolog": {
        "title": "Sincronizar homologacao",
        "summary": "Executa o fluxo producao -> homologacao.",
        "details": (
            "E uma acao forte: valida RB_CERT_BOOTSTRAP=0, faz backup local, baixa dump da "
            "producao e pode sincronizar volumes conforme RB_SYNC_*."
        ),
        "command": ["-y", "sync-homolog"],
        "safe": False,
        "needs_message": False,
    },
}


HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RioBranco Agent</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #eef2f6;
      --panel: #ffffff;
      --ink: #15202b;
      --muted: #607085;
      --line: #d6dde7;
      --accent: #176a73;
      --accent-2: #b64f33;
      --soft: #e6f3f4;
      --warn: #fff2df;
      --code: #101827;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font: 15px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
    }
    aside {
      background: #16242f;
      color: #f6fbff;
      padding: 22px;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }
    h1 {
      margin: 0;
      font-size: 22px;
      font-weight: 760;
      letter-spacing: 0;
    }
    .subtitle {
      color: #b8c6d3;
      margin: 6px 0 0;
      font-size: 13px;
    }
    .option-grid {
      display: grid;
      gap: 8px;
    }
    .side-button {
      border: 1px solid rgba(255,255,255,.13);
      color: #f6fbff;
      background: rgba(255,255,255,.06);
      border-radius: 8px;
      padding: 10px 11px;
      text-align: left;
      cursor: pointer;
      font: inherit;
      min-height: 42px;
    }
    .side-button:hover { background: rgba(255,255,255,.11); }
    .side-button.active {
      border-color: #7fd1d7;
      background: rgba(127,209,215,.18);
      box-shadow: inset 3px 0 0 #7fd1d7;
    }
    .hint {
      border-top: 1px solid rgba(255,255,255,.12);
      padding-top: 14px;
      color: #b8c6d3;
      font-size: 13px;
    }
    main {
      display: grid;
      grid-template-rows: auto auto minmax(0, 1fr) auto;
      min-width: 0;
    }
    .topbar {
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      padding: 16px 22px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .topbar strong { font-size: 16px; }
    .status-pill {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 6px 10px;
      color: var(--muted);
      background: #f8fafc;
      font-size: 13px;
      white-space: nowrap;
    }
    .chat {
      overflow: auto;
      padding: 22px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .message {
      max-width: 920px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 13px 14px;
      background: var(--panel);
      white-space: pre-wrap;
    }
    .message.user {
      align-self: flex-end;
      background: var(--soft);
      border-color: #c1dde0;
      max-width: 760px;
    }
    .message.agent { align-self: flex-start; }
    .message.running { border-color: #d4a856; background: var(--warn); }
    .workspace {
      background: #f8fafc;
      border-bottom: 1px solid var(--line);
      padding: 14px 22px;
      display: grid;
      gap: 12px;
    }
    .workspace-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .workspace-head h2 {
      margin: 0;
      font-size: 15px;
      letter-spacing: 0;
    }
    .workspace-meta {
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }
    .card-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
      gap: 10px;
      max-height: 270px;
      overflow: auto;
      padding-right: 2px;
    }
    .frete-card {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 11px;
      cursor: pointer;
      text-align: left;
      font: inherit;
      display: grid;
      gap: 7px;
      min-height: 132px;
    }
    .frete-card:hover { border-color: #9ab7c1; }
    .frete-card.selected {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(23,106,115,.12);
    }
    .frete-title {
      font-weight: 720;
      overflow-wrap: anywhere;
    }
    .frete-row {
      color: var(--muted);
      font-size: 13px;
    }
    .frete-status {
      width: max-content;
      max-width: 100%;
      border-radius: 999px;
      padding: 4px 8px;
      background: #e8edf5;
      color: #283747;
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .selected-card {
      border: 1px solid #b8cbd4;
      background: #fff;
      border-radius: 8px;
      padding: 12px;
      display: none;
      gap: 8px;
    }
    .selected-card.visible { display: grid; }
    .selected-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }
    button.action {
      border: 1px solid var(--accent);
      color: #fff;
      background: var(--accent);
      border-radius: 8px;
      padding: 8px 10px;
      cursor: pointer;
      font: inherit;
    }
    button.action.secondary {
      background: #fff;
      color: var(--accent);
    }
    button.action.danger {
      border-color: var(--accent-2);
      background: var(--accent-2);
    }
    pre {
      margin: 12px 0 0;
      padding: 12px;
      border-radius: 8px;
      background: var(--code);
      color: #dfe7ef;
      overflow: auto;
      max-height: 360px;
      font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      white-space: pre-wrap;
    }
    form {
      background: var(--panel);
      border-top: 1px solid var(--line);
      padding: 14px 22px 18px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
    }
    textarea {
      width: 100%;
      min-height: 48px;
      max-height: 150px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      font: inherit;
    }
    .send {
      border: 0;
      border-radius: 8px;
      background: var(--ink);
      color: white;
      padding: 0 18px;
      font: inherit;
      cursor: pointer;
      min-width: 92px;
    }
    .send:disabled, button:disabled {
      opacity: .58;
      cursor: wait;
    }
    @media (max-width: 820px) {
      .app { grid-template-columns: 1fr; }
      aside { min-height: auto; }
      main { min-height: 70vh; }
      form { grid-template-columns: 1fr; }
      .send { min-height: 44px; }
      .workspace-head { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <div>
        <h1>RioBranco Agent</h1>
        <p class="subtitle">Pergunte, entenda e execute rotinas de operacao.</p>
      </div>
      <div class="option-grid" id="quickOptions"></div>
      <div class="hint">
        Exemplos:<br>
        "listar cargas"<br>
        "mover status para carregado caminhao 13"<br>
        "o que faz deploy?"<br>
        "enviar para o git"
      </div>
    </aside>
    <main>
      <div class="topbar">
        <strong>Conversa operacional</strong>
        <span class="status-pill" id="statusPill">pronto</span>
      </div>
      <section class="workspace" id="workspace">
        <div class="workspace-head">
          <h2 id="workspaceTitle">Operacao do sistema</h2>
          <span class="workspace-meta" id="workspaceMeta">nenhum card carregado</span>
        </div>
        <div class="selected-card" id="selectedCard"></div>
        <div class="card-grid" id="cardGrid"></div>
      </section>
      <section class="chat" id="chat"></section>
      <form id="form">
        <textarea id="message" placeholder="Pergunte o que quer fazer..."></textarea>
        <button class="send" id="send" type="submit">Enviar</button>
      </form>
    </main>
  </div>
  <script>
    const chat = document.getElementById('chat');
    const form = document.getElementById('form');
    const input = document.getElementById('message');
    const send = document.getElementById('send');
    const pill = document.getElementById('statusPill');
    const quick = document.getElementById('quickOptions');
    const workspaceTitle = document.getElementById('workspaceTitle');
    const workspaceMeta = document.getElementById('workspaceMeta');
    const cardGrid = document.getElementById('cardGrid');
    const selectedCard = document.getElementById('selectedCard');
    let activeMenu = '';
    let workspaceCards = [];
    let selectedFreteId = null;

    const options = [
      ['kanban', 'Kanban / Cargas'],
      ['status', 'Status'],
      ['backup', 'Backup'],
      ['brief', 'Brief'],
      ['validate', 'Validacao'],
      ['git', 'Git'],
      ['ship', 'Fluxo completo'],
      ['deploy', 'Deploy'],
      ['update', 'Update'],
      ['logs', 'Logs'],
      ['doctor', 'Diagnostico']
    ];

    function setBusy(busy) {
      send.disabled = busy;
      pill.textContent = busy ? 'executando...' : 'pronto';
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[ch]));
    }

    function setActiveMenu(name) {
      activeMenu = name || '';
      document.querySelectorAll('.side-button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.option === activeMenu);
      });
    }

    function selectedCardHtml(card) {
      if (!card) return '';
      const statuses = [
        ['chegada', 'Chegada'],
        ['descarregado', 'Descarregado'],
        ['liberado', 'Liberado'],
        ['carregando', 'Carregando'],
        ['carregado', 'Carregado'],
        ['entregando', 'Entregando'],
        ['retornando', 'Retornando']
      ];
      const buttons = statuses.map(([status, label]) => {
        const disabled = status === card.status ? 'disabled' : '';
        return `<button class="action secondary" data-move-status="${escapeHtml(status)}" ${disabled}>${escapeHtml(label)}</button>`;
      }).join('');
      return `
        <div class="frete-title">#${escapeHtml(card.id)} ${escapeHtml(card.title)}</div>
        <div class="frete-row">Status atual: ${escapeHtml(card.status_label)} | Caminhao: ${escapeHtml(card.vehicle)} ${card.plate ? '| Placa: ' + escapeHtml(card.plate) : ''}</div>
        <div class="frete-row">Motorista: ${escapeHtml(card.driver)} | Entregador: ${escapeHtml(card.helper)}</div>
        <div class="frete-row">Carga: ${escapeHtml(card.load)} ${card.date ? '| Data: ' + escapeHtml(card.date) : ''}</div>
        <div class="selected-actions">${buttons}</div>
      `;
    }

    function selectFreteCard(id) {
      selectedFreteId = Number(id);
      const card = workspaceCards.find(item => Number(item.id) === selectedFreteId);
      document.querySelectorAll('.frete-card').forEach(el => {
        el.classList.toggle('selected', Number(el.dataset.id) === selectedFreteId);
      });
      if (!card) {
        selectedCard.classList.remove('visible');
        selectedCard.innerHTML = '';
        return;
      }
      selectedCard.innerHTML = selectedCardHtml(card);
      selectedCard.classList.add('visible');
      selectedCard.querySelectorAll('[data-move-status]').forEach(btn => {
        btn.onclick = () => {
          const status = btn.dataset.moveStatus;
          addMessage('user', `mover frete ${card.id} para ${btn.textContent}`);
          sendChat({action: 'move_frete', frete_id: card.id, status, confirmed: true});
        };
      });
    }

    function renderWorkspace(data) {
      if (!data) return;
      if (data.active) setActiveMenu(data.active);
      if (data.title) workspaceTitle.textContent = data.title;
      if (data.meta) workspaceMeta.textContent = data.meta;
      if (!Array.isArray(data.cards)) return;
      workspaceCards = data.cards;
      cardGrid.innerHTML = '';
      if (!workspaceCards.length) {
        cardGrid.innerHTML = '<div class="frete-row">Nenhum card encontrado.</div>';
        selectedCard.classList.remove('visible');
        selectedCard.innerHTML = '';
        return;
      }
      workspaceCards.forEach(card => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'frete-card';
        btn.dataset.id = card.id;
        btn.innerHTML = `
          <div class="frete-title">#${escapeHtml(card.id)} ${escapeHtml(card.title)}</div>
          <div class="frete-status">${escapeHtml(card.status_label)}</div>
          <div class="frete-row">Caminhao: ${escapeHtml(card.vehicle)} ${card.plate ? '| ' + escapeHtml(card.plate) : ''}</div>
          <div class="frete-row">Motorista: ${escapeHtml(card.driver)}</div>
          <div class="frete-row">Carga: ${escapeHtml(card.load)}</div>
        `;
        btn.onclick = () => selectFreteCard(card.id);
        cardGrid.appendChild(btn);
      });
      const preferred = data.selected_id || selectedFreteId || workspaceCards[0].id;
      selectFreteCard(preferred);
    }

    function addMessage(role, text, actions, output, running) {
      const box = document.createElement('div');
      box.className = 'message ' + role + (running ? ' running' : '');
      box.textContent = text || '';
      if (actions && actions.length) {
        const row = document.createElement('div');
        row.className = 'actions';
        actions.forEach(action => {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'action' + (action.kind === 'secondary' ? ' secondary' : '') + (action.danger ? ' danger' : '');
          btn.textContent = action.label;
          btn.onclick = () => handleAction(action);
          row.appendChild(btn);
        });
        box.appendChild(row);
      }
      if (output) {
        const pre = document.createElement('pre');
        pre.textContent = output;
        box.appendChild(pre);
      }
      chat.appendChild(box);
      chat.scrollTop = chat.scrollHeight;
      return box;
    }

    async function sendChat(payload) {
      setBusy(true);
      try {
        const response = await fetch('/api/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (data.workspace) renderWorkspace(data.workspace);
        addMessage('agent', data.reply, data.actions || [], data.output || '', false);
      } catch (err) {
        addMessage('agent', 'Nao consegui falar com o app local: ' + err.message);
      } finally {
        setBusy(false);
        input.focus();
      }
    }

    function handleAction(action) {
      if (action.name === 'brief') {
        const task = window.prompt('Descreva o pedido para eu analisar:');
        if (!task) return;
        addMessage('user', action.label + ' - ' + task);
        sendChat({action: action.name, message: task, confirmed: true});
        return;
      }
      if (action.needsMessage) {
        const message = window.prompt('Mensagem do commit:');
        if (!message) return;
        addMessage('user', action.label + ' - ' + message);
        sendChat({action: action.name, commit_message: message, confirmed: true});
        return;
      }
      addMessage('user', action.label);
      sendChat({...action, action: action.name, confirmed: true});
    }

    options.forEach(([name, label]) => {
      const btn = document.createElement('button');
      btn.className = 'side-button';
      btn.dataset.option = name;
      btn.type = 'button';
      btn.textContent = label;
      btn.onclick = () => {
        setActiveMenu(name);
        addMessage('user', 'explicar ' + label);
        sendChat({message: name === 'kanban' ? 'listar cargas do kanban' : 'explicar ' + name});
      };
      quick.appendChild(btn);
    });

    form.addEventListener('submit', event => {
      event.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      addMessage('user', text);
      sendChat({message: text});
    });

    addMessage('agent',
      'Oi. Eu sou o assistente operacional do RioBranco. Pergunte algo como "listar cargas", "mover status para carregado caminhao 13", "analisar pedido", "o que faz backup?" ou "enviar para o git". Eu explico antes de mexer em qualquer coisa importante.',
      [
        {name: 'refresh_fretes', label: 'Listar cargas'},
        {name: 'status', label: 'Executar status'},
        {name: 'brief', label: 'Analisar pedido'},
        {name: 'backup', label: 'Gerar backup'},
        {name: 'validate', label: 'Validar baseline', kind: 'secondary'},
        {name: 'doctor', label: 'Rodar diagnostico', kind: 'secondary'}
      ]
    );
  </script>
</body>
</html>
"""


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower().strip()


def _as_str(value: object) -> str:
    return str(value or "").strip()


def _as_int(value: object, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(str(value).strip())
    except Exception:
        return int(default)


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(str(value).strip())
    except Exception:
        return float(default)


def _as_float_br(value: object, default: float = 0.0) -> float:
    text = _as_str(value).replace(" ", "")
    if not text:
        return float(default)
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "." in text and re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
        text = text.replace(".", "")
    elif "," in text:
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", text):
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except Exception:
        return float(default)


def _fmt_decimal_br(value: object, decimals: int = 3) -> str:
    number = _as_float_br(value, 0.0)
    rendered = f"{number:,.{max(0, int(decimals))}f}"
    return rendered.replace(",", "_").replace(".", ",").replace("_", ".")


def load_env(path: Path = ROOT / ".env") -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        values[key.strip()] = value
    return values


def system_base_urls() -> list[str]:
    env = load_env()
    urls = []
    app_port = env.get("APP_PORT") or os.environ.get("APP_PORT") or "8080"
    urls.append(f"http://127.0.0.1:{app_port}")
    https_port = env.get("RB_HTTPS_PORT", "8443")
    http_port = env.get("RB_HTTP_PORT", "80")
    urls.extend([
        f"https://127.0.0.1:{https_port}",
        f"http://127.0.0.1:{http_port}",
    ])
    configured = (env.get("RB_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if configured:
        urls.append(configured)
    unique = []
    for url in urls:
        if url and url not in unique:
            unique.append(url)
    return unique


def system_api(method: str, path: str, payload: dict | None = None, timeout: int = 20):
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request_headers = current_request_headers()
    for key in ("X-Usuario-Id", "X-Usuario-Login", "X-Usuario-Nome", "X-Usuario-Logado"):
        value = request_headers.get(key)
        if value:
            headers[key] = value

    context = ssl._create_unverified_context()
    errors = []
    for base in system_base_urls():
        url = base.rstrip("/") + path
        req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
                raw = response.read().decode("utf-8", errors="replace")
                if not raw:
                    return {}
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except Exception:
                data = {"erro": raw or str(exc)}
            raise RuntimeError(data.get("erro") or f"HTTP {exc.code}")
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Nao consegui conectar na aplicacao RioBranco. " + " | ".join(errors[-2:]))


def status_label(status: str) -> str:
    return FRETE_STATUS.get(str(status or ""), str(status or "-"))


def frete_title(frete: dict) -> str:
    vehicle = str(frete.get("veiculo_nome") or frete.get("carga_veiculo_numero") or "").strip()
    carga = str(frete.get("carga_nome") or "").strip()
    nome = str(frete.get("nome") or "").strip()
    parts = [part for part in [vehicle and f"Caminhao {vehicle}", carga, nome] if part]
    return " - ".join(parts) or f"Frete #{frete.get('id')}"


def frete_card(frete: dict) -> dict:
    return {
        "id": frete.get("id"),
        "title": frete_title(frete),
        "status": str(frete.get("status") or ""),
        "status_label": status_label(frete.get("status")),
        "vehicle": str(frete.get("veiculo_nome") or frete.get("carga_veiculo_numero") or "-"),
        "plate": str(frete.get("veiculo_placa") or ""),
        "driver": str(frete.get("colaborador_motorista_nome") or frete.get("motorista_nome") or "-"),
        "helper": str(frete.get("colaborador_entregador_nome") or frete.get("entregador_nome") or "-"),
        "load": str(frete.get("carga_nome") or "-"),
        "city": str(frete.get("cidade") or frete.get("carga_cidade") or ""),
        "date": str(frete.get("data_carga") or ""),
        "weight": frete.get("peso"),
        "deliveries": frete.get("qtd_entregas"),
        "raw": frete,
    }


def list_fretes(filter_text: str = "") -> list[dict]:
    rows = system_api("GET", "/api/fretes")
    if not isinstance(rows, list):
        return []
    query = normalize(filter_text)
    cards = [frete_card(item) for item in rows]
    if query:
        filtered_cards = []
        for card in cards:
            raw = card.get("raw") if isinstance(card.get("raw"), dict) else {}
            haystack = normalize(" ".join([
                str(card.get("id") or ""),
                card.get("title") or "",
                card.get("vehicle") or "",
                card.get("plate") or "",
                card.get("driver") or "",
                card.get("load") or "",
                card.get("status_label") or "",
                card.get("city") or "",
                _as_str(raw.get("cidade")),
                _as_str(raw.get("carga_cidade")),
                _as_str(raw.get("carga_rota")),
                _as_str(raw.get("carga_cidades")),
            ]))
            if query in haystack:
                filtered_cards.append(card)
        cards = filtered_cards
    return cards


def detect_frete_status(text: str) -> str | None:
    words = normalize(text)
    aliases = {
        "parado carregado": "paradoCarregado",
        "paradocarregado": "paradoCarregado",
        "parado vazio": "paradoVasio",
        "parado vasio": "paradoVasio",
        "paradovasio": "paradoVasio",
        "descarga": "descarregado",
        "descarregado": "descarregado",
        "liberado": "liberado",
        "carregando": "carregando",
        "carregado": "carregado",
        "entregando": "entregando",
        "retornando": "retornando",
        "chegada": "chegada",
    }
    for alias, status in aliases.items():
        if alias in words:
            return status
    return None


def extract_frete_query(text: str, status: str | None = None) -> str:
    words = normalize(text)
    if status:
        words = words.replace(normalize(status_label(status)), " ")
        words = words.replace(normalize(status), " ")
    words = re.sub(r"\b(mover|mova|alterar|altera|trocar|troca|status|para|pro|pra|frete|carga|card|kanban|caminhao|camiao|veiculo)\b", " ", words)
    words = re.sub(r"\s+", " ", words).strip()
    return words


def find_frete(query: str) -> tuple[dict | None, list[dict]]:
    cards = list_fretes()
    q = normalize(query)
    if not q:
        return None, cards[:8]
    exact_id = re.search(r"\b(\d+)\b", q)
    is_vehicle_query = bool(re.search(r"\b(caminhao|camiao|veiculo)\b", q))
    if exact_id and not is_vehicle_query:
        number = exact_id.group(1)
        for card in cards:
            if str(card.get("id")) == number:
                return card, []
    scored = []
    for card in cards:
        raw = card.get("raw") or {}
        haystacks = [
            str(card.get("id") or ""),
            card.get("title") or "",
            card.get("vehicle") or "",
            card.get("plate") or "",
            card.get("load") or "",
            str(raw.get("carga_veiculo_numero") or ""),
            str(raw.get("carga_id") or ""),
            str(raw.get("veiculo_id") or ""),
        ]
        full = normalize(" ".join(haystacks))
        score = 0
        if exact_id:
            number = exact_id.group(1)
            if is_vehicle_query:
                if normalize(str(card.get("vehicle") or "")) == number:
                    score += 100
                if normalize(str(raw.get("carga_veiculo_numero") or "")) == number:
                    score += 95
                if str(card.get("id")) == number:
                    score += 50
            else:
                if str(card.get("id")) == number:
                    score += 100
                if normalize(str(card.get("vehicle") or "")) == number:
                    score += 90
                if normalize(str(raw.get("carga_veiculo_numero") or "")) == number:
                    score += 85
        if q and q in full:
            score += 50
        for token in q.split():
            if token and token in full:
                score += 5
        if score:
            scored.append((score, card))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return None, []
    best_score = scored[0][0]
    best = [card for score, card in scored if score == best_score]
    if exact_id and len(best) > 1:
        number = exact_id.group(1)
        vehicle_matches = [
            card for card in best
            if normalize(str(card.get("vehicle") or "")) == number
            or normalize(str((card.get("raw") or {}).get("carga_veiculo_numero") or "")) == number
        ]
        if vehicle_matches:
            vehicle_matches.sort(key=lambda card: int(card.get("id") or 0), reverse=True)
            return vehicle_matches[0], []
    if len(best) == 1:
        return best[0], []
    return None, best[:8]


def move_frete_status(frete_id: int, status: str) -> dict:
    data = system_api("PUT", f"/api/fretes/{int(frete_id)}", {"status": status})
    frete = data.get("frete") if isinstance(data, dict) else None
    if not frete:
        raise RuntimeError("A API nao retornou o frete atualizado.")
    return frete_card(frete)


def list_colaboradores() -> list[dict]:
    rows = system_api("GET", "/api/colaboradores")
    return rows if isinstance(rows, list) else []


def get_logged_usuario() -> dict | None:
    try:
        data = system_api("GET", "/api/me")
        if isinstance(data, dict):
            usuario = data.get("usuario")
            if isinstance(usuario, dict):
                return usuario
    except Exception:
        pass

    # Fallback to headers forwarded from the current request if /api/me is unavailable.
    request_headers = current_request_headers()
    usuario_id = request_headers.get("X-Usuario-Id")
    if usuario_id and usuario_id.isdigit():
        return {
            "id": int(usuario_id),
            "login": request_headers.get("X-Usuario-Login", ""),
            "nome": request_headers.get("X-Usuario-Nome", ""),
        }
    return None


def find_logged_conferente() -> dict | None:
    usuario = get_logged_usuario()
    if not usuario:
        return None

    colaborador_id = int(usuario.get("id") or 0)
    login_normalizado = normalize(str(usuario.get("login") or ""))
    nome_normalizado = normalize(str(usuario.get("nome") or ""))

    for item in list_colaboradores():
        if int(item.get("is_conferente") or 0) != 1:
            continue
        if int(item.get("usuario_id") or 0) == colaborador_id:
            return item
        if login_normalizado and normalize(str(item.get("login") or "")) == login_normalizado:
            return item
        if nome_normalizado and normalize(str(item.get("nome") or "")) == nome_normalizado:
            return item
    return None


def find_conferente(query: str) -> tuple[dict | None, list[dict]]:
    colaboradores = [
        item for item in list_colaboradores()
        if int(item.get("is_conferente") or 0) == 1
    ]
    q = normalize(query)
    if not q:
        return None, colaboradores[:8]
    exact_id = re.search(r"\b(\d+)\b", q)
    if exact_id:
        number = exact_id.group(1)
        for item in colaboradores:
            if str(item.get("id")) == number:
                return item, []
    scored: list[tuple[int, dict]] = []
    for item in colaboradores:
        full = normalize(" ".join([str(item.get("id") or ""), str(item.get("nome") or "")]))
        score = 0
        if q and q in full:
            score += 50
        for token in q.split():
            if token and token in full:
                score += 5
        if score:
            scored.append((score, item))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return None, []
    best_score = scored[0][0]
    best = [item for score, item in scored if score == best_score]
    if len(best) == 1:
        return best[0], []
    return None, best[:8]


def _devolucao_tokens(text: str) -> list[dict]:
    normalized = normalize(text)
    return [
        {"value": match.group(0), "start": match.start(), "end": match.end()}
        for match in re.finditer(r"-?\d+(?![a-z0-9/])|[a-z0-9/]+", normalized)
    ]


def _devolucao_alias_tokens() -> list[tuple[str, list[str]]]:
    aliases: list[tuple[str, list[str]]] = []
    for key, names in DEVOLUCAO_ITEMS.items():
        for alias in names:
            parts = [tok["value"] for tok in _devolucao_tokens(alias)]
            if parts:
                aliases.append((key, parts))
    aliases.sort(key=lambda item: len(item[1]), reverse=True)
    return aliases


def _match_devolucao_alias(tokens: list[dict], index: int) -> tuple[str | None, int]:
    values = [tok["value"] for tok in tokens]
    for key, parts in _devolucao_alias_tokens():
        window = values[index:index + len(parts)]
        if window == parts:
            return key, len(parts)
        if len(window) == len(parts) and sorted(window) == sorted(parts):
            return key, len(parts)
    return None, 0


def _is_int_token(value: str) -> bool:
    return bool(re.fullmatch(r"-?\d+", value or ""))


def _devolucao_qty_value(value: str) -> int | None:
    token = normalize(value)
    if not token:
        return None
    if _is_int_token(token):
        try:
            return int(token)
        except Exception:
            return None
    return DEVOLUCAO_NUMBER_WORDS.get(token)


def _is_devolucao_stop_token(tokens: list[dict], index: int) -> bool:
    if index >= len(tokens):
        return True
    value = tokens[index]["value"]
    if value in {"conferente", "frete", "carga", "card", "kanban", "caminhao", "camiao", "veiculo"}:
        return True
    key, _ = _match_devolucao_alias(tokens, index)
    return bool(key)


def _is_devolucao_locator_number(tokens: list[dict], index: int) -> bool:
    if index <= 0:
        return False
    return tokens[index - 1]["value"] in {"frete", "carga", "card", "kanban", "caminhao", "camiao", "veiculo"}


def parse_devolucao_mentions(message: str) -> dict:
    text = re.sub(r"(?<!\w)-\s+(\d+)", r"-\1", normalize(message))
    tokens = _devolucao_tokens(text)
    items = {key: 0 for key in DEVOLUCAO_ITEMS}
    obs = {f"obs_{key}": "" for key in DEVOLUCAO_ITEMS}
    consumed = [False] * len(tokens)
    spans: list[tuple[int, int]] = []

    def capture_obs(start_idx: int) -> tuple[str, int]:
        if start_idx >= len(tokens):
            return "", start_idx
        first_value = str(tokens[start_idx]["value"])
        if _is_devolucao_stop_token(tokens, start_idx):
            return "", start_idx
        if _devolucao_qty_value(first_value) is not None and not first_value.startswith("-"):
            return "", start_idx

        obs_start = start_idx
        if first_value in DEVOLUCAO_OBS_MARKERS:
            obs_start += 1
            if obs_start >= len(tokens):
                return "", start_idx + 1
        end_idx = obs_start
        while end_idx < len(tokens):
            if _is_devolucao_stop_token(tokens, end_idx):
                break
            if _devolucao_qty_value(tokens[end_idx]["value"]) is not None and not str(tokens[end_idx]["value"]).startswith("-"):
                break
            end_idx += 1
        if end_idx <= obs_start:
            return "", start_idx
        obs_text = text[tokens[obs_start]["start"]:tokens[end_idx - 1]["end"]].strip()
        obs_text = re.sub(r"^-+", "", obs_text).strip()
        return obs_text, end_idx

    i = 0
    while i < len(tokens):
        if consumed[i]:
            i += 1
            continue

        value = tokens[i]["value"]
        qty_value = _devolucao_qty_value(value)
        if qty_value is not None and not value.startswith("-") and not _is_devolucao_locator_number(tokens, i):
            alias_start = i + 1
            key, alias_len = _match_devolucao_alias(tokens, alias_start)
            if not key:
                while alias_start < len(tokens) and tokens[alias_start]["value"] in DEVOLUCAO_QUANTITY_QUALIFIERS:
                    alias_start += 1
                key, alias_len = _match_devolucao_alias(tokens, alias_start)
            if key:
                items[key] = qty_value
                for idx in range(i, min(len(tokens), alias_start + alias_len)):
                    consumed[idx] = True
                obs_text, obs_end = capture_obs(alias_start + alias_len)
                if obs_text:
                    obs[f"obs_{key}"] = obs_text
                    for idx in range(alias_start + alias_len, obs_end):
                        consumed[idx] = True
                end_idx = obs_end if obs_text else alias_start + alias_len
                spans.append((tokens[i]["start"], tokens[end_idx - 1]["end"]))
                i = end_idx
                continue

        key, alias_len = _match_devolucao_alias(tokens, i)
        if key:
            qty_idx = i + alias_len
            qty_value = _devolucao_qty_value(tokens[qty_idx]["value"]) if qty_idx < len(tokens) else None
            if qty_idx < len(tokens) and qty_value is not None and not tokens[qty_idx]["value"].startswith("-"):
                items[key] = qty_value
                end_idx = qty_idx + 1
                if end_idx < len(tokens) and tokens[end_idx]["value"] in DEVOLUCAO_QUANTITY_QUALIFIERS:
                    next_idx = end_idx + 1
                    if next_idx >= len(tokens) or _is_devolucao_stop_token(tokens, next_idx) or (next_idx < len(tokens) and str(tokens[next_idx]["value"]).startswith("-")):
                        end_idx = next_idx
                for idx in range(i, end_idx):
                    consumed[idx] = True
                obs_text, obs_end = capture_obs(end_idx)
                if obs_text:
                    obs[f"obs_{key}"] = obs_text
                    for idx in range(end_idx, obs_end):
                        consumed[idx] = True
                end_idx = obs_end if obs_text else end_idx
                spans.append((tokens[i]["start"], tokens[end_idx - 1]["end"]))
                i = end_idx
                continue

            qualifier_idx = qty_idx
            if qualifier_idx < len(tokens) and tokens[qualifier_idx]["value"] in DEVOLUCAO_QUANTITY_QUALIFIERS:
                next_qty = qualifier_idx + 1
                next_qty_value = _devolucao_qty_value(tokens[next_qty]["value"]) if next_qty < len(tokens) else None
                if next_qty < len(tokens) and next_qty_value is not None and not tokens[next_qty]["value"].startswith("-"):
                    items[key] = next_qty_value
                    for idx in range(i, next_qty + 1):
                        consumed[idx] = True
                    obs_text, obs_end = capture_obs(next_qty + 1)
                    if obs_text:
                        obs[f"obs_{key}"] = obs_text
                        for idx in range(next_qty + 1, obs_end):
                            consumed[idx] = True
                    end_idx = obs_end if obs_text else next_qty + 1
                    spans.append((tokens[i]["start"], tokens[end_idx - 1]["end"]))
                    i = end_idx
                    continue

        i += 1

    cleaned = text
    for start, end in sorted(spans, reverse=True):
        cleaned = cleaned[:start] + " " + cleaned[end:]
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return {"items": items, "obs": obs, "cleaned": cleaned}


def extract_devolucao_items(message: str) -> dict[str, int]:
    return parse_devolucao_mentions(message)["items"]


def strip_devolucao_items(text: str) -> str:
    return parse_devolucao_mentions(text)["cleaned"]


def extract_conferente_query(message: str) -> str:
    text = normalize(message)
    match = re.search(r"\bconferente\s+(.+)$", text)
    if not match:
        return ""
    query = strip_devolucao_items(match.group(1))
    query = re.sub(r"\b(frete|carga|card|kanban|caminhao|camiao|veiculo)\b.*$", " ", query)
    return re.sub(r"\s+", " ", query).strip()


def extract_devolucao_frete_query(message: str) -> str:
    text = normalize(message)
    text = re.sub(r"\bconferente\s+.+$", " ", text)
    text = strip_devolucao_items(text)
    text = re.sub(
        r"\b(lancar|lanca|lançar|lança|registrar|registra|criar|nova|novo|devolucao|devolocao|devolucoes|devolocoes|devolução|devoluções|dz|duzia|duzias|uni|und|unidade|unidades|do|da|de|para|com)\b",
        " ",
        text,
    )
    text = re.sub(r"[,:;]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_devolucao_frete_id(message: str) -> int | None:
    text = normalize(message)
    match = re.search(r"\b(?:frete|id)\s+(\d+)\b", text)
    return int(match.group(1)) if match else None


def _normalized_has_term(normalized: str, term: str) -> bool:
    term_norm = normalize(term)
    if not term_norm:
        return False
    return re.search(rf"\b{re.escape(term_norm)}\b", normalized) is not None


def is_devolucao_message(normalized: str) -> bool:
    return any(_normalized_has_term(normalized, word) for word in DEVOLUCAO_WORDS)


def is_devolucao_create_message(normalized: str) -> bool:
    return is_devolucao_message(normalized) and any(_normalized_has_term(normalized, word) for word in DEVOLUCAO_ACTION_WORDS)


def list_devolucoes_response() -> dict:
    rows = system_api("GET", "/api/devolucoes")
    rows = rows if isinstance(rows, list) else []
    lines = [f"Encontrei {len(rows)} devolucao(oes)."]
    for item in rows[:10]:
        total = sum(int(item.get(key) or 0) for key in DEVOLUCAO_ITEMS)
        lines.append(
            f"#{item.get('id')} - {item.get('frete_nome') or '-'} | "
            f"{item.get('conferente_nome') or '-'} | total itens: {total}"
        )
    if len(rows) > 10:
        lines.append(f"... e mais {len(rows) - 10}.")
    return {"reply": "\n".join(lines), "devolucoes_updated": True}


def create_devolucao_response(message: str) -> dict:
    # Check if this is a frete ID confirmation message (e.g., "frete 106" or "id 106")
    confirmed_frete_id = extract_devolucao_frete_id(message)
    pending_confirmation = _get_pending_devolucao_confirmation()
    if confirmed_frete_id and pending_confirmation:
        # User is confirming a pending devolucao with a specific frete
        ctx = pending_confirmation
        if ctx.get("card") and ctx["card"]["id"] == confirmed_frete_id:
            # Frete ID matches the pending confirmation, proceed with execution
            _set_pending_devolucao_confirmation({})
            return _execute_devolucao_creation(
                items=ctx["items"],
                obs=ctx["obs"],
                card=ctx["card"],
                conferente=ctx["conferente"],
                alternatives=ctx["alternatives"],
            )
        else:
            # Try to find the confirmed frete
            frete_query = f"frete {confirmed_frete_id}"
            card, alternatives = find_frete(frete_query)
            if card:
                _set_pending_devolucao_confirmation({})
                return _execute_devolucao_creation(
                    items=ctx["items"],
                    obs=ctx["obs"],
                    card=card,
                    conferente=ctx["conferente"],
                    alternatives=alternatives,
                )

    # Not a confirmation, treat as new devolucao request
    _set_pending_devolucao_confirmation({})

    parsed = parse_devolucao_mentions(message)
    items = parsed["items"]
    obs = parsed["obs"]
    if not any(value > 0 for value in items.values()):
        return {
            "reply": (
                "Para lancar devolucao, informe ao menos uma quantidade.\n"
                "Exemplo: lancar devolucao caminhao 13 c24 2 pet2l 1 conferente Joao"
            )
        }

    conferente_query = extract_conferente_query(message)
    if conferente_query:
        conferente, conferentes_alt = find_conferente(conferente_query)
    else:
        conferente = find_logged_conferente()
        conferentes_alt = [
            item for item in list_colaboradores()
            if int(item.get("is_conferente") or 0) == 1
        ][:8]

    if not conferente:
        nomes = ", ".join(str(item.get("nome") or item.get("id")) for item in conferentes_alt[:6])
        return {
            "reply": (
                "Preciso identificar um conferente para lancar a devolucao."
                + (f" Encontrei: {nomes}." if nomes else "")
                + "\nExemplo: lancar devolucao caminhao 13 c24 2 conferente Maria"
            )
        }

    frete_id = extract_devolucao_frete_id(message) or 0
    if frete_id:
        frete_query = f"frete {frete_id}"
        card, alternatives = find_frete(frete_query)
    else:
        frete_query = extract_devolucao_frete_query(message)
        card, alternatives = find_frete(frete_query)

    if not card:
        return {
            "reply": "Nao consegui identificar o frete da devolucao. Informe o numero do caminhao, id do frete ou nome da carga.",
            "workspace": fretes_workspace(alternatives or list_fretes(frete_query), title="Cards encontrados"),
        }

    if not frete_id and any(word in normalize(message) for word in ["caminhao", "camiao", "veiculo"]):
        # Store context for confirmation and return confirmation request
        _set_pending_devolucao_confirmation({
            "items": items,
            "obs": obs,
            "card": card,
            "conferente": conferente,
            "alternatives": alternatives,
        })
        return {
            "reply": (
                f"Encontrei o frete #{card['id']} para \"{card['title']}\". "
                "Como um caminhão pode ter vários fretes, confirme o id do frete antes de lançar a devolução. "
                f"Use: \"frete {card['id']}\""
            ),
            "workspace": fretes_workspace([card] + alternatives, selected_id=card["id"]),
        }

    return _execute_devolucao_creation(
        items=items,
        obs=obs,
        card=card,
        conferente=conferente,
        alternatives=alternatives,
    )


def _execute_devolucao_creation(items: dict, obs: dict, card: dict, conferente: dict, alternatives: list) -> dict:
    """Execute the actual devolucao creation with provided parameters."""
    raw = card.get("raw") or {}
    payload = {
        "frete_id": card["id"],
        "veiculo_id": raw.get("veiculo_id") or raw.get("carga_veiculo_id"),
        "colaborador_conferente_id": conferente.get("id"),
        **items,
        **obs,
    }
    created = system_api("POST", "/api/devolucoes", payload)
    devolucao_id = created.get("id") if isinstance(created, dict) else None
    resumo_partes = []
    for key, value in items.items():
        if value > 0:
            obs_key = f"obs_{key}"
            detalhe = f" ({obs[obs_key]})" if obs.get(obs_key) else ""
            resumo_partes.append(f"{key}={value}{detalhe}")
    resumo = ", ".join(resumo_partes)
    return {
        "reply": (
            f"Lancei a devolucao #{devolucao_id or '-'} para frete #{card['id']} \"{card['title']}\" "
            f"com conferente {conferente.get('nome') or conferente.get('id')} ({resumo})."
        ),
        "workspace": fretes_workspace(list_fretes(), selected_id=card["id"]),
        "devolucoes_updated": True,
        "actions": [
            {"name": "list_devolucoes", "label": "Listar devolucoes"},
            {"name": "refresh_fretes", "label": "Atualizar kanban", "kind": "secondary"},
        ],
    }


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def html_response(handler: BaseHTTPRequestHandler) -> None:
    body = HTML.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def actions_for(option: str, include_secondary: bool = True) -> list[dict]:
    info = OPTIONS[option]
    primary = {
        "name": option,
        "label": "Executar " + info["title"].lower(),
        "danger": not info["safe"],
        "needsMessage": info["needs_message"],
    }
    actions = [primary]
    if include_secondary:
        actions.append({"name": "status", "label": "Ver status antes", "kind": "secondary"})
    return actions


def _clean_action_name(value: object) -> str:
    return normalize(str(value or "")).replace("-", "_").replace(" ", "_")


def _normalize_agent_action(action: object) -> dict | None:
    if isinstance(action, str):
        name = action.strip()
        if not name:
            return None
        action = {"name": name}
    if not isinstance(action, dict):
        return None

    name = str(action.get("name") or action.get("action") or "").strip()
    if not name:
        return None

    normalized = _clean_action_name(name)
    output_name = normalized
    if normalized == "list_fretes" or normalized in {"kanban", "cargas", "carga"}:
        output_name = "refresh_fretes"
    elif normalized == "list_devolucoes":
        output_name = "list_devolucoes"
    elif normalized == "sync_homolog":
        output_name = "sync-homolog"
    elif normalized in {"brief", "validate", "status", "backup", "git", "ship", "deploy", "update", "logs", "doctor", "refresh_fretes", "move_frete"}:
        output_name = normalized
    else:
        return None

    label = str(action.get("label") or action.get("title") or "").strip()
    if not label:
        if output_name == "refresh_fretes":
            label = "Listar cargas"
        elif output_name == "list_devolucoes":
            label = "Listar devolucoes"
        elif output_name in OPTIONS:
            label = "Executar " + OPTIONS[output_name]["title"].lower()
        elif output_name == "move_frete":
            label = "Mover frete"

    normalized_action = {"name": output_name, "label": label or output_name.replace("_", " ").title()}
    if action.get("kind") in {"secondary", "primary"}:
        normalized_action["kind"] = action["kind"]
    if action.get("danger"):
        normalized_action["danger"] = True
    if action.get("needsMessage") or action.get("needs_message"):
        normalized_action["needsMessage"] = True
    return normalized_action


def _suggest_agent_actions(text: str, reply: str = "") -> list[dict]:
    combined = f"{text or ''} {reply or ''}"
    option = detect_option(combined)
    if option == "kanban":
        return [
            {"name": "refresh_fretes", "label": "Listar cargas"},
            {"name": "status", "label": "Ver status antes", "kind": "secondary"},
        ]
    if option == "brief":
        return actions_for("brief", include_secondary=False)
    if option == "validate":
        return actions_for("validate", include_secondary=False)
    if option == "status":
        return actions_for("status", include_secondary=False)
    if option == "backup":
        return actions_for("backup", include_secondary=False)
    if option == "git":
        return actions_for("git", include_secondary=False)
    if option == "ship":
        return actions_for("ship", include_secondary=False)
    if option == "deploy":
        return actions_for("deploy", include_secondary=False)
    if option == "update":
        return actions_for("update", include_secondary=False)
    if option == "logs":
        return actions_for("logs", include_secondary=False)
    if option == "doctor":
        return actions_for("doctor", include_secondary=False)
    if option == "sync-homolog":
        return actions_for("sync-homolog", include_secondary=False)
    return []


def _agent_merge_actions(*groups: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for group in groups:
        for action in group or []:
            normalized = _normalize_agent_action(action)
            if not normalized:
                continue
            key = normalized.get("name", "")
            if key in seen:
                continue
            seen.add(key)
            merged.append(normalized)
    return merged[:3]


def option_text(option: str) -> str:
    info = OPTIONS[option]
    risk = "Leitura/consulta." if info["safe"] else "Altera estado do sistema."
    return (
        f"{info['title']}\n\n"
        f"{info['summary']}\n\n"
        f"{info['details']}\n\n"
        f"Tipo: {risk}"
    )


def all_options_text() -> str:
    lines = ["Estas sao as opcoes que eu conheco:\n"]
    lines.append("- Kanban / Cargas: lista os cards de frete e permite mover status.")
    lines.append("- Devolucoes: lista e lanca devolucoes vinculadas a um frete.")
    for key, info in OPTIONS.items():
        lines.append(f"- {info['title']}: {info['summary']}")
    lines.append("\nVoce pode perguntar 'listar cargas', 'mover status para carregado caminhao 13' ou 'executar status'.")
    return "\n".join(lines)


def fretes_workspace(cards: list[dict], selected_id=None, title: str = "Kanban / Cargas") -> dict:
    public_cards = [
        {key: value for key, value in card.items() if key != "raw"}
        for card in cards
    ]
    return {
        "active": "kanban",
        "title": title,
        "meta": f"{len(public_cards)} card(s)",
        "cards": public_cards,
        "selected_id": selected_id,
    }


def list_fretes_response(filter_text: str = "") -> dict:
    cards = list_fretes(filter_text)
    if filter_text:
        reply = f"Encontrei {len(cards)} card(s) para \"{filter_text}\". Clique em um card para deixar ele visivel e mover status pelos botoes."
    else:
        reply = f"Listei {len(cards)} card(s) do kanban. Clique em um card para ver detalhes e acoes."
    return {
        "reply": reply,
        "workspace": fretes_workspace(cards),
        "actions": [
            {"name": "refresh_fretes", "label": "Atualizar lista"},
            {"name": "status", "label": "Ver status geral", "kind": "secondary"},
        ],
    }


def move_frete_prepare_response(message: str) -> dict:
    status = detect_frete_status(message)
    if not status:
        return {
            "reply": "Para mover um card, diga o status de destino. Exemplo: mover status para carregado caminhao 13.",
            "workspace": fretes_workspace(list_fretes()),
        }
    query = extract_frete_query(message, status)
    card, alternatives = find_frete(query)
    if not card:
        reply = "Nao consegui identificar um unico card."
        if alternatives:
            reply += " Selecione um dos cards abaixo ou especifique melhor, por exemplo pelo numero do caminhao."
        else:
            reply += " Tente informar o numero do caminhao, id do frete ou nome da carga."
        return {
            "reply": reply,
            "workspace": fretes_workspace(alternatives or list_fretes(query), title="Cards encontrados"),
        }
    updated = move_frete_status(int(card["id"]), status)
    cards = list_fretes()
    return {
        "reply": f"Movi \"{updated['title']}\" para {updated['status_label']}.",
        "workspace": fretes_workspace(cards, selected_id=updated["id"]),
        "actions": [{"name": "refresh_fretes", "label": "Atualizar kanban"}],
    }


def detect_option(text: str) -> str | None:
    words = normalize(text)
    if any(word in words for word in ["brief", "analisar", "analise", "planejar", "plano", "contexto", "arquivos", "revisar"]):
        return "brief"
    if any(word in words for word in ["validar", "validacao", "testar", "checar"]):
        return "validate"
    if "kanban" in words or "carga" in words or "frete" in words or "caminhao" in words or "card" in words:
        return "kanban"
    if "sync" in words or "homolog" in words:
        return "sync-homolog"
    if "ship" in words or "fluxo completo" in words or "tudo" in words:
        return "ship"
    if "backup" in words or "bkp" in words:
        return "backup"
    if "status" in words or "situacao" in words or "estado" in words:
        return "status"
    if "doctor" in words or "diagnost" in words or "verificar" in words:
        return "doctor"
    if "log" in words:
        return "logs"
    if "deploy" in words or "subir" in words or "rebuild" in words:
        return "deploy"
    if "update" in words or "atualizar" in words or "pull" in words:
        return "update"
    if "git" in words or "commit" in words or "push" in words or "github" in words:
        return "git"
    return None


def wants_execution(text: str) -> bool:
    words = normalize(text)
    return bool(re.search(r"\b(execut|rodar|fazer|gerar|criar|enviar|subir|atualizar|deployar|listar|mostrar|ver|mover|alterar|trocar)\w*", words))


def extract_commit_message(text: str) -> str:
    match = re.search(r"(?:mensagem|commit)\s*[:=-]\s*(.+)$", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip().strip('"').strip("'")
    return ""


def build_command(action: str, commit_message: str = "") -> list[str]:
    if action not in OPTIONS:
        raise ValueError("acao desconhecida")
    info = OPTIONS[action]
    command = [str(AGENT), *info["command"]]
    if info["needs_message"]:
        if not commit_message:
            raise ValueError("essa acao precisa de uma mensagem de commit")
        command.append(commit_message)
    return command


def run_agent(action: str, commit_message: str = "") -> dict:
    started = time.monotonic()
    command = build_command(action, commit_message)
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=COMMAND_TIMEOUT,
        check=False,
    )
    elapsed = time.monotonic() - started
    output = (result.stdout or "") + (result.stderr or "")
    if len(output) > OUTPUT_LIMIT:
        output = output[-OUTPUT_LIMIT:]
        output = "[saida cortada para mostrar o final]\n" + output
    status = "concluido" if result.returncode == 0 else f"falhou com codigo {result.returncode}"
    return {
        "reply": f"{OPTIONS[action]['title']} {status} em {elapsed:.1f}s.",
        "output": output.strip(),
        "returncode": result.returncode,
    }


def _agent_llm_provider() -> str:
    return (os.environ.get("RB_AGENT_LLM_PROVIDER") or "auto").strip().lower()


def _agent_llm_enabled() -> bool:
    return _agent_llm_provider() not in {"0", "false", "off", "none", "disabled"}


def _agent_llm_url() -> str:
    return (os.environ.get("RB_AGENT_OLLAMA_URL") or "http://127.0.0.1:11434").strip().rstrip("/")


def _agent_llm_model() -> str:
    return (os.environ.get("RB_AGENT_OLLAMA_MODEL") or os.environ.get("OLLAMA_MODEL") or "llama3.1:8b").strip()


def _agent_project_name() -> str:
    return (os.environ.get("RB_PROJECT_NAME") or "RioBranco").strip() or "RioBranco"


def _agent_company_name() -> str:
    return (os.environ.get("RB_COMPANY_NAME") or "RioBranco").strip() or "RioBranco"


def _agent_internal_ip() -> str:
    explicit = (os.environ.get("RB_INTERNAL_IP") or "").strip()
    if explicit:
        return explicit
    public_base_url = (os.environ.get("RB_PUBLIC_BASE_URL") or "").strip()
    if public_base_url:
        host = urlparse(public_base_url).hostname or ""
        if host:
            return host
    server_name = (os.environ.get("RB_SERVER_NAME") or "").strip()
    if server_name:
        return server_name
    return ""


@lru_cache(maxsize=1)
def _agent_company_cnpj() -> str:
    explicit = (os.environ.get("RB_COMPANY_CNPJ") or "").strip()
    if explicit:
        return explicit

    pattern = re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}")
    for rel_path in ("server.py", "docs/AI_CONTEXT.md", "docs/README.md"):
        path = ROOT / rel_path
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        match = pattern.search(text)
        if match:
            return match.group(0)
    return ""


def _agent_project_context() -> dict[str, str]:
    return {
        "project_name": _agent_project_name(),
        "company_name": _agent_company_name(),
        "company_cnpj": _agent_company_cnpj(),
        "internal_ip": _agent_internal_ip(),
        "public_base_url": (os.environ.get("RB_PUBLIC_BASE_URL") or "").strip(),
        "server_name": (os.environ.get("RB_SERVER_NAME") or "").strip(),
        "db_name": (os.environ.get("RB_DB_NAME") or "riobranco").strip() or "riobranco",
        "freepbx_host": (os.environ.get("RB_FREEPBX_HOST") or "").strip(),
    }


def _agent_project_context_text() -> str:
    ctx = _agent_project_context()
    lines = [
        f"Projeto: {ctx['project_name']}",
        f"Empresa: {ctx['company_name']}",
    ]
    if ctx["company_cnpj"]:
        lines.append(f"CNPJ: {ctx['company_cnpj']}")
    if ctx["internal_ip"]:
        lines.append(f"IP interno do ambiente: {ctx['internal_ip']}")
    if ctx["public_base_url"]:
        lines.append(f"Base URL publica: {ctx['public_base_url']}")
    if ctx["server_name"]:
        lines.append(f"Server name: {ctx['server_name']}")
    if ctx["db_name"]:
        lines.append(f"Banco principal: {ctx['db_name']}")
    if ctx["freepbx_host"]:
        lines.append(f"FreePBX: {ctx['freepbx_host']}")
    return "\n".join(f"- {line}" for line in lines)


def _agent_llm_timeout() -> float:
    raw = (os.environ.get("RB_AGENT_OLLAMA_TIMEOUT") or "90").strip()
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 90.0


def _agent_web_enabled() -> bool:
    return (os.environ.get("RB_AGENT_WEB_ENABLED") or "1").strip().lower() not in {"0", "false", "no", "off"}


def _agent_web_timeout() -> float:
    raw = (os.environ.get("RB_AGENT_WEB_TIMEOUT") or "12").strip()
    try:
        return max(3.0, float(raw))
    except ValueError:
        return 12.0


def _agent_web_budget() -> float:
    raw = (os.environ.get("RB_AGENT_WEB_BUDGET") or "20").strip()
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 20.0


def _agent_llm_history_messages(history: object) -> list[dict]:
    if not isinstance(history, list):
        return []
    messages: list[dict] = []
    for item in history[-LLM_HISTORY_LIMIT:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or item.get("text") or "").strip()
        if role not in {"user", "assistant", "system"} or not content:
            continue
        messages.append({"role": role, "content": content[:LLM_MAX_TOKENS]})
    return messages


def _chat_mode(payload: dict | None) -> str:
    if isinstance(payload, dict):
        explicit = normalize(str(payload.get("chat_mode") or payload.get("mode") or ""))
        if explicit in {"ia", "agent"}:
            return explicit
        persona = normalize(str(payload.get("persona_name") or ""))
        if persona in {"ia-rio", "i.a-rio", "ia rio", "i a rio", "iario"}:
            return "ia"
    return "agent"


def _prefer_llm_first_for_operational_query(message: str, chat_mode: str) -> bool:
    if normalize(chat_mode or "") != "ia":
        return False
    normalized = normalize(message)
    if not normalized:
        return False
    return any(
        term in normalized
        for term in (
            "frete", "fretes", "carga", "cargas", "kanban",
            "devolucao", "devolucoes", "caminhao", "caminhoes", "camiao",
        )
    )


def _agent_llm_system_prompt(persona_name: str = "", chat_mode: str = "agent") -> str:
    statuses = ", ".join(sorted(FRETE_STATUS.keys()))
    persona = str(persona_name or "").strip()
    mode = normalize(chat_mode or "agent")
    intro = "Voce e o Agent IA do sistema RioBranco, embutido no chat da aplicacao."
    if persona:
        intro = f"Voce atende pelo nome {persona}, um membro da equipe RioBranco."
    if mode == "ia":
        return (
            intro + " "
            "Seu papel aqui e de I.A-Rio com acesso amplo ao contexto do sistema. "
            "Fale como uma pessoa da equipe, de forma objetiva e cordial.\n\n"
            "Use o mapa do repositorio, o contexto local, as consultas estruturadas e o inventario do ambiente como fonte primaria.\n"
            "Quando a pergunta for sobre o aplicativo, banco, estoque, fretes, NF-e, infraestrutura, arquivos, funcoes, rotas, modulos ou dados, "
            "responda com base nesses dados locais antes de improvisar.\n"
            "Se uma informacao nao estiver disponivel no codigo, nos docs ou nas consultas locais, diga isso claramente.\n"
            "Nao redirecione a conversa para um menu de rotinas operacionais quando a pergunta for informativa.\n"
            "Quando usar informacoes vindas do contexto local do repositorio, cite ao final os arquivos usados como fonte.\n\n"
            "Voce tambem pode disparar acoes estruturadas quando o usuario pedir execucao clara de uma rotina.\n"
            "Acoes disponiveis:\n"
            "- status, backup, git, ship, deploy, update, logs, doctor, brief, validate, sync-homolog\n"
            "- list_fretes, move_frete, list_devolucoes\n\n"
            "Regras:\n"
            "- Para perguntas informativas, retorne JSON com type=\"reply\".\n"
            "- So retorne type=\"action\" quando o usuario pedir execucao clara.\n"
            "- Para consultas de frete/kanban em que voce precise listar cards filtrados, use action=\"list_fretes\" com query ou filter.\n"
            "- Nao invente nomes de recursos, ids, saldos ou mensagens de commit.\n"
            "- Status de frete aceitos: " + statuses + ".\n\n"
            "Formato de resposta estrito:\n"
            '{"type":"reply","reply":"..."}\n'
            '{"type":"action","action":"status"}\n'
            '{"type":"action","action":"list_fretes","query":"londrina 48 entregas"}\n'
            '{"type":"action","action":"move_frete","frete_id":123,"status":"carregado"}\n'
        )
    if persona:
        intro = intro + " Fale como uma pessoa da equipe, de forma objetiva e cordial."
    return (
        intro + " "
        "Responda sempre em portugues do Brasil, com objetividade.\n\n"
        "Use o mapa do repositorio e o contexto local como fonte primaria para fatos sobre o sistema.\n"
        "Quando houver duvida, consulte primeiro os arquivos do repositorio antes de improvisar.\n"
        "Quando usar informacoes vindas do contexto local do repositorio, cite ao final os arquivos usados como fonte.\n\n"
        "Quando a pergunta for sobre funcionamento da aplicacao, planejamento, execucao, caminhos, arquivos, variaveis ou dados do projeto, "
        "trate o repositorio como fonte primaria e responda de forma especifica com base no contexto local.\n"
        "Se a resposta nao estiver no codigo ou nos docs do repositorio, diga que nao encontrou a informacao localmente.\n\n"
        "Seu trabalho tem dois modos:\n"
        "1. Conversar, explicar funcionalidades e orientar o usuario.\n"
        "2. Executar rotinas do sistema quando o usuario pedir claramente.\n\n"
        "Acoes disponiveis:\n"
        "- status, backup, git, ship, deploy, update, logs, doctor, brief, validate, sync-homolog\n"
        "- list_fretes, move_frete, list_devolucoes\n\n"
        "Regras:\n"
        "- Se o usuario pedir para executar uma rotina, retorne JSON com type=\"action\".\n"
        "- Se o usuario pedir apenas explicacao ou conversa, retorne JSON com type=\"reply\".\n"
        "- Se faltar informacao para uma acao, faca uma pergunta curta em reply.\n"
        "- Para git e ship, inclua commit_message somente se o usuario forneceu uma mensagem.\n"
        "- Para listar cards de frete com filtro, use action=\"list_fretes\" com query ou filter.\n"
        "- Para move_frete, use frete_id e status quando eles estiverem claros.\n"
        "- Status de frete aceitos: " + statuses + ".\n"
        "- Nao invente nomes de recursos, ids ou mensagens de commit.\n\n"
        "Formato de resposta estrito:\n"
        '{"type":"reply","reply":"..."}\n'
        '{"type":"action","action":"status"}\n'
        '{"type":"action","action":"list_fretes","query":"londrina 48 entregas"}\n'
        '{"type":"action","action":"move_frete","frete_id":123,"status":"carregado"}\n'
    )


def _agent_repo_context_message(message: str) -> str:
    context = build_repo_context(message)
    text = format_repo_context(context)
    if not text:
        return ""
    return (
        "Contexto local encontrado no repositorio pela busca automatica:\n"
        f"{text}\n\n"
        "Use este contexto como fonte primaria para fatos sobre o projeto, ambiente, CNPJ, IP, URLs e configuracoes.\n"
        "Ao responder, cite os arquivos que suportaram o fato."
    )


def _agent_repo_manifest_message() -> str:
    manifest = build_repo_manifest()
    text = format_repo_manifest(manifest)
    if not text:
        return ""
    return (
        "Mapa completo do repositorio, para consulta primaria:\n"
        f"{text}\n\n"
        "Use este mapa para localizar modulos, rotas, funcoes e docs antes de responder."
    )


def _agent_environment_context_message() -> str:
    inventory = build_environment_inventory()
    text = format_environment_inventory(inventory)
    if not text:
        return ""
    return (
        "Inventario de ambiente, VM, banco, SO, Docker e diretorios operacionais:\n"
        f"{text}\n\n"
        "Use este inventario como fonte primaria para perguntas sobre infraestrutura, runtime, volumes, banco e sistema operacional."
    )


def _agent_repo_facts(message: str) -> dict:
    context = build_repo_context(message)
    text = format_repo_context(context)
    joined = text.lower()
    facts = {
        "project_name": "",
        "company_name": "",
        "company_cnpj": "",
        "internal_ip": "",
        "public_base_url": "",
        "server_name": "",
        "context": context,
    }

    if not text:
        return facts

    def clean(value: str) -> str:
        value = str(value or "").strip()
        return value if value and value not in {"-", "--"} else ""

    match = re.search(r"rb_project_name[ \t]*=[ \t]*([^\s|\n]+)", text, re.IGNORECASE)
    if match:
        facts["project_name"] = clean(match.group(1))

    match = re.search(r"rb_company_name[ \t]*=[ \t]*([^\s|\n]+)", text, re.IGNORECASE)
    if match:
        facts["company_name"] = clean(match.group(1))

    match = re.search(r"(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", text)
    if match:
        facts["company_cnpj"] = match.group(1).strip()

    match = re.search(r"rb_internal_ip[ \t]*=[ \t]*([^\s|\n]+)", text, re.IGNORECASE)
    if match:
        facts["internal_ip"] = clean(match.group(1))

    match = re.search(r"rb_public_base_url[ \t]*=[ \t]*(https?://[^\s|\n]+)", text, re.IGNORECASE)
    if match:
        facts["public_base_url"] = clean(match.group(1))
        try:
            facts["internal_ip"] = facts["internal_ip"] or (urlparse(facts["public_base_url"]).hostname or "")
        except Exception:
            pass

    match = re.search(r"rb_server_name[ \t]*=[ \t]*([^\s|\n]+)", text, re.IGNORECASE)
    if match:
        facts["server_name"] = clean(match.group(1))
        facts["internal_ip"] = facts["internal_ip"] or facts["server_name"]

    return facts


def _agent_system_overview_reply(message: str) -> dict | None:
    normalized = normalize(message)
    if not normalized:
        return None

    broad_phrases = (
        "como funciona",
        "visao geral",
        "visão geral",
        "resumo do sistema",
        "mapa do sistema",
        "quais modulos",
        "quais modulos tem",
        "quais sao os modulos",
        "quais são os módulos",
        "entender tudo",
        "tudo sobre o sistema",
        "como o sistema e organizado",
        "como o sistema é organizado",
        "arquitetura do sistema",
        "estrutura do sistema",
    )
    if not any(phrase in normalized for phrase in broad_phrases):
        return None

    overview = build_system_overview()
    text = format_system_overview(overview)
    if not text:
        return None

    reply = (
        text
        + "\n\nSe quiser, eu posso aprofundar um modulo especifico como NF-e, fretes, estoque, vendas, chat, deploy ou integracoes."
    )
    result = {"reply": reply, "actions": system_overview_actions()}
    sources = overview.get("sources") or []
    if sources:
        result["reply"] = f"{result['reply']}\n\nFontes: " + ", ".join(sources[:6])
    return result


@lru_cache(maxsize=1)
def _compose_services_snapshot() -> list[dict[str, str]]:
    compose_path = ROOT / "docker-compose.yml"
    try:
        text = compose_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    services: list[dict[str, str]] = []
    in_services = False
    current: dict[str, str] | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not in_services:
            if re.match(r"^services:\s*$", line):
                in_services = True
            continue

        if re.match(r"^[A-Za-z0-9_-]+:\s*$", line):
            break

        match_service = re.match(r"^\s{2}([A-Za-z0-9_-]+):\s*$", line)
        if match_service:
            current = {"service": match_service.group(1), "container_name": ""}
            services.append(current)
            continue

        if current is None:
            continue

        match_container = re.match(r"^\s{4}container_name:\s*([^\s#]+)", line)
        if match_container:
            current["container_name"] = match_container.group(1).strip().strip("'\"")

    return services


def _agent_environment_local_reply(message: str) -> dict | None:
    normalized = normalize(message)
    if not normalized:
        return None

    env_terms = {"so", "sistema operacional", "linux", "docker", "container", "containers", "servico", "servicos", "compose", "banco", "database", "db", "vm", "esxi", "vcenter", "infra", "ambiente", "host", "volume", "volumes", "runtime"}

    def _has_term(term: str) -> bool:
        term = normalize(term)
        if not term:
            return False
        return re.search(rf"\b{re.escape(term)}\b", normalized) is not None

    if not any(_has_term(term) for term in env_terms):
        return None

    inventory = build_environment_inventory()
    runtime = inventory.get("runtime") or {}
    environment = inventory.get("environment") or {}
    data_dirs = inventory.get("data_dirs") or []

    reply_parts: list[str] = []

    if any(_has_term(term) for term in {"so", "sistema operacional", "linux", "runtime", "container"}):
        os_release = runtime.get("os_release") or {}
        os_desc = os_release.get("PRETTY_NAME") or runtime.get("platform") or "ambiente de runtime desconhecido"
        reply_parts.append(
            f"O runtime atual esta em {os_desc}, no host {runtime.get('hostname') or 'desconhecido'}, usando Python {runtime.get('python') or 'desconhecido'}."
        )

    if any(_has_term(term) for term in {"container", "containers", "servico", "servicos", "compose", "docker"}):
        services = _compose_services_snapshot()
        if services:
            principais = [item for item in services if item.get("service") in {"app", "proxy", "db"}]
            relevantes = principais or services[:4]
            nomes_servicos = ", ".join(f"`{item.get('service')}`" for item in relevantes if item.get("service"))
            nomes_containers = ", ".join(
                f"`{item.get('container_name')}`" for item in relevantes if item.get("container_name")
            )
            extra = [item.get("service") for item in services if item.get("service") not in {"app", "proxy", "db"}]
            reply = f"No Docker Compose, os serviços principais da aplicacao sao {nomes_servicos}."
            if nomes_containers:
                reply += f" Os containers nomeados sao {nomes_containers}."
            if extra:
                reply += f" Tambem existem serviços auxiliares como {', '.join(f'`{name}`' for name in extra[:3] if name)}."
            reply_parts.append(reply)

    if any(_has_term(term) for term in {"banco", "database", "db"}):
        db_name = environment.get("RB_DB_NAME") or "riobranco"
        db_user = environment.get("RB_DB_USER") or "riobranco"
        reply_parts.append(
            f"O banco principal e MariaDB, com base {db_name}, usuario {db_user} e bootstrap via `sql/init_riobranco.sql`."
        )

    if any(_has_term(term) for term in {"vm", "esxi", "vcenter"}):
        esxi_host = environment.get("ESXI_HOST") or ""
        vsphere_path = environment.get("RB_VSPHERE_CLIENT_PATH") or "./esxi"
        if esxi_host:
            reply_parts.append(
                f"A parte de VM/infra aponta para ESXi/vCenter em {esxi_host}, com cliente local em {vsphere_path}."
            )
        else:
            reply_parts.append(f"A parte de VM/infra usa o cliente local em {vsphere_path}.")

    if any(_has_term(term) for term in {"volume", "volumes", "storage", "arquivos", "diretorio", "diretorios", "dados"}):
        if data_dirs:
            resumo = []
            for item in data_dirs[:4]:
                path = item.get("path") or ""
                samples = item.get("samples") or []
                resumo.append(f"{path} ({', '.join(samples[:3])})" if samples else path)
            reply_parts.append(f"Os diretórios operacionais relevantes incluem: {', '.join(resumo)}.")

    if not reply_parts:
        return None

    reply = " ".join(reply_parts)
    sources = [
        "docker-compose.yml",
        ".env",
        ".env.example",
        "sql/init_riobranco.sql",
        "esxi/README.md",
    ]
    return {"reply": f"{reply}\n\nFontes: " + ", ".join(sources)}


def _agent_data_lookup_reply(message: str) -> dict | None:
    normalized = normalize(message)
    if not normalized:
        return None

    count_terms = {"quantos", "quantas", "quantidade", "total", "numero", "número", "tem cadastrado", "tem cadastrados", "cadastrado", "cadastrados"}
    list_terms = {"listar", "lista", "mostra", "mostrar", "quais", "exibir", "relacionar", "ver", "apresentar"}

    entity_map = [
        ("veiculos", ["veiculo", "veiculos", "caminhao", "caminhoes", "caminhão", "caminhões"], "veiculo", ["id", "nome", "placa", "modelo"]),
        ("motoristas", ["motorista", "motoristas"], "motorista", ["id", "nome", "is_motorista", "is_entregador", "is_ajudante"]),
        ("colaboradores", ["colaborador", "colaboradores", "funcionario", "funcionarios", "funcionário", "funcionários"], "colaborador", ["id", "nome", "login", "cpf"]),
        ("cargas", ["carga", "cargas", "frete", "fretes"], "carga/frete", ["id", "nome", "cidade", "veiculo_numero"]),
        ("devolucoes", ["devolucao", "devolucoes", "devolução", "devoluções"], "devolução", ["id", "frete_id", "veiculo_id", "created_at"]),
        ("abastecimentos", ["abastecimento", "abastecimentos"], "abastecimento", ["id", "veiculo_id", "km", "status"]),
        ("usuarios", ["usuario", "usuarios", "usuário", "usuários"], "usuário", ["id", "nome", "login", "ativo"]),
        ("conferentes", ["conferente", "conferentes"], "conferente", ["id", "nome"]),
    ]

    def _has_word(term: str) -> bool:
        term_norm = normalize(term)
        if not term_norm:
            return False
        return re.search(rf"\b{re.escape(term_norm)}\b", normalized) is not None

    wants_count = any(_has_word(term) for term in count_terms)
    wants_list = any(_has_word(term) for term in list_terms)
    if not wants_count and not wants_list:
        return None

    matched = None
    for table, terms, label, fields in entity_map:
        if any(_has_word(term) for term in terms):
            matched = (table, label, fields)
            break
    if not matched:
        return None

    table, label, fields = matched
    if wants_list and table in {"cargas", "devolucoes"}:
        db_hint_terms = {
            "cadastro",
            "cadastrado",
            "cadastrados",
            "registrado",
            "registrados",
            "registro",
            "registros",
            "tabela",
            "tabelas",
            "banco",
            "bancos",
            "base",
            "bases",
        }
        if not any(_has_word(term) for term in db_hint_terms):
            return None

    try:
        conn = _agent_db_connect()
    except Exception:
        return None

    try:
        cur = conn.cursor(dictionary=True)
        if wants_count and not wants_list:
            cur.execute(f"SELECT COUNT(*) AS total FROM {table}")
            row = cur.fetchone() or {}
            total = int(row.get("total") or 0)
            reply = f"Existem {total} {label}{'s' if total != 1 and not label.endswith('s') else ''} cadastrados."
        else:
            cur.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT 10")
            rows = cur.fetchall() or []
            total = None
            if wants_count:
                cur.execute(f"SELECT COUNT(*) AS total FROM {table}")
                row = cur.fetchone() or {}
                total = int(row.get("total") or 0)
            if rows:
                samples = []
                for row in rows[:5]:
                    pieces = [str(row.get(field) or "").strip() for field in fields if str(row.get(field) or "").strip()]
                    samples.append(" / ".join(pieces) if pieces else f"id {row.get('id')}")
                prefix = f"Existem {total} {label}{'s' if total != 1 and not label.endswith('s') else ''} cadastrados. " if total is not None else ""
                reply = prefix + "Exemplos recentes: " + "; ".join(samples)
            else:
                reply = f"Nao encontrei registros em {table}."
    except Exception:
        return None
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    sources = ["server.py", "sql/init_riobranco.sql", "docs/API_E_DADOS.md"]
    return {"reply": f"{reply}\n\nFontes: " + ", ".join(sources)}


def _agent_frete_status_lookup_reply(message: str) -> dict | None:
    normalized = normalize(message)
    if not normalized:
        return None

    count_terms = {
        "quantos",
        "quantas",
        "quantidade",
        "total",
        "numero",
        "número",
        "qtd",
        "contagem",
    }
    status_terms = {
        "carregando",
        "carregado",
        "descarregado",
        "liberado",
        "entregando",
        "retornando",
        "chegada",
        "parado vazio",
        "parado vasio",
        "parado carregado",
    }
    query_terms = {
        "qual",
        "quais",
        "quem",
        "esta",
        "estao",
        "está",
        "estão",
        "no",
        "na",
        "nos",
        "nas",
        "de",
        "da",
        "do",
        "das",
        "dos",
        "para",
        "pra",
        "pro",
        "por",
        "rota",
        "rotas",
        "status",
        "caminhao",
        "caminhoes",
        "camiao",
        "veiculo",
        "veiculos",
        "carga",
        "cargas",
        "frete",
        "fretes",
        "em",
        "andamento",
        "momento",
        "agora",
        "carregar",
        "liberado",
        "liberados",
        "liberada",
        "liberadas",
    }

    status = None
    for term in status_terms:
        if term in normalized:
            status = "carregando" if term == "carregando" else term.replace(" ", "")
            break

    if status is None:
        return None

    wants_count = any(term in normalized for term in count_terms)
    route_hint = normalized
    for term in status_terms:
        route_hint = route_hint.replace(term, " ")
    for term in query_terms:
        route_hint = re.sub(rf"\b{re.escape(normalize(term))}\b", " ", route_hint)
    route_hint = re.sub(r"[^\w\s-]+", " ", route_hint)
    route_hint = re.sub(r"\s+", " ", route_hint).strip()
    stop_tokens = {normalize(term) for term in query_terms} | {normalize(term) for term in status_terms} | {normalize(term) for term in count_terms}
    route_hint = " ".join(token for token in route_hint.split() if len(token) >= 4 and token not in stop_tokens).strip()

    has_operational_word = status is not None or any(
        word in normalized
        for word in (
            "caminhao",
            "caminhoes",
            "camiao",
            "veiculo",
            "frete",
            "carga",
            "rota",
            "carregando",
            "carregado",
            "status",
        )
    )
    if not has_operational_word:
        return None

    try:
        conn = _agent_db_connect()
    except Exception:
        return None

    try:
        cur = conn.cursor(dictionary=True)
        base_from_sql = AGENT_FRETE_SELECT_SQL.split("FROM", 1)[1]
        where_sql = " WHERE LOWER(TRIM(COALESCE(f.status, ''))) = %s"
        params: list[object] = [status]
        if route_hint:
            route_tokens = [token for token in route_hint.split() if token]
            for token in route_tokens or [route_hint]:
                like = f"%{token}%"
                where_sql += (
                    " AND ("
                    "LOWER(COALESCE(c.rota, '')) LIKE %s OR "
                    "LOWER(COALESCE(c.cidade, '')) LIKE %s OR "
                    "LOWER(COALESCE(f.nome, '')) LIKE %s OR "
                    "LOWER(COALESCE(c.veiculo_numero, '')) LIKE %s OR "
                    "LOWER(COALESCE(v.nome, '')) LIKE %s OR "
                    "LOWER(COALESCE(v.placa, '')) LIKE %s"
                    ")"
                )
                params.extend([like] * 6)

        if wants_count:
            count_sql = "SELECT COUNT(DISTINCT COALESCE(f.veiculo_id, vr.id, f.id)) AS total FROM " + base_from_sql + where_sql
            cur.execute(count_sql, params)
            row = cur.fetchone() or {}
            total = _as_int(row.get("total"), 0)
            status_phrase = {
                "liberado": "liberados para carregar",
                "carregando": "carregando",
                "carregado": "carregados",
                "descarregado": "descarregados",
                "chegada": "na chegada",
                "entregando": "entregando",
                "retornando": "retornando",
                "paradoVasio": "parados vazios",
                "paradoCarregado": "parados carregados",
            }.get(status, status_label(status).lower())
            reply = f"Existem {total} caminhões {status_phrase}."
            if route_hint:
                reply += f" Filtro aplicado: {route_hint}."
            reply += "\n\nFontes: server.py, sql/init_riobranco.sql"
            return {"reply": reply, "actions": [{"name": "refresh_fretes", "label": "Atualizar kanban"}]}

        sql = AGENT_FRETE_SELECT_SQL + where_sql + " ORDER BY f.created_at DESC, f.id DESC LIMIT 8"
        cur.execute(sql, params)
        rows = cur.fetchall() or []
    except Exception:
        return None
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    if not rows:
        if route_hint:
            reply = f"Nao encontrei nenhum frete em {status_label(status).lower()} para a rota '{route_hint}'."
        else:
            reply = f"Nao encontrei nenhum frete em {status_label(status).lower()} no momento."
        return {
            "reply": f"{reply}\n\nFontes: server.py, sql/init_riobranco.sql",
            "actions": [{"name": "refresh_fretes", "label": "Atualizar kanban"}],
        }

    lines = []
    for row in rows[:5]:
        vehicle = _as_str(row.get("veiculo_nome_resolvido") if row.get("veiculo_nome_resolvido") is not None else row.get("veiculo_nome"))
        plate = _as_str(row.get("veiculo_placa_resolvida") if row.get("veiculo_placa_resolvida") is not None else row.get("veiculo_placa"))
        carga_nome = _as_str(row.get("carga_nome"))
        rota = _as_str(row.get("carga_rota") or row.get("carga_cidade") or row.get("cidade"))
        cidade = _as_str(row.get("carga_cidade") or row.get("cidade"))
        partes = [
            f"Frete #{_as_int(row.get('id'), 0)}",
            f"Caminhao {vehicle}" if vehicle else "Caminhao desconhecido",
            f"Placa {plate}" if plate else "",
            f"Carga {carga_nome}" if carga_nome else "",
            f"Rota {rota}" if rota else "",
            f"Cidade {cidade}" if cidade and cidade != rota else "",
        ]
        lines.append(" - ".join([part for part in partes if part]))

    if len(lines) == 1:
        reply = f"Encontrei o caminhao em {status_label(status).lower()}: {lines[0]}."
    else:
        reply = f"Encontrei {len(lines)} fretes em {status_label(status).lower()}:\n- " + "\n- ".join(lines)
    if route_hint:
        reply += f"\n\nFiltro aplicado: {route_hint}"
    reply += "\n\nFontes: server.py, sql/init_riobranco.sql"
    return {"reply": reply, "actions": [{"name": "refresh_fretes", "label": "Atualizar kanban"}]}


def _frete_numeric_lookup_request(message: str, normalized: str) -> dict | None:
    if not any(term in normalized for term in ("caminhao", "caminhoes", "camiao", "veiculo", "veiculos", "frete", "fretes", "carga", "cargas", "kanban", "card", "cards")):
        return None

    patterns = [
        ("km_atual", (r"\bkm\s+atual\b", r"\bquilometragem\b", r"\bkm\b")),
        ("peso", (r"\bpeso\s+total\b", r"\bpeso\b")),
        ("qtd_entregas", (r"\bqtd\s+entregas\b", r"\bquantidade\s+de\s+entregas\b", r"\bentregas\b")),
    ]
    for field, field_patterns in patterns:
        for field_pattern in field_patterns:
            for pattern in (
                field_pattern + r"[^\d]*(\d[\d.,]*)",
                r"(\d[\d.,]*)[^\d]*(?:" + field_pattern + r")",
            ):
                match = re.search(pattern, normalized)
                if not match:
                    continue
                raw_value = match.group(1)
                if field in {"km_atual", "qtd_entregas"}:
                    value = _as_int(round(_as_float_br(raw_value, 0.0)), 0)
                    return {
                        "field": field,
                        "value": value,
                        "label": "KM atual" if field == "km_atual" else "Entregas",
                        "display": str(value),
                    }
                return {
                    "field": field,
                    "value": _as_float_br(raw_value, 0.0),
                    "label": "peso",
                    "display": _fmt_decimal_br(raw_value, 0),
                }
    return None


def _frete_lookup_tokens(normalized: str, request: dict | None = None) -> list[str]:
    words = normalized
    ignored_terms = {
        "a", "agora", "as", "card", "cards", "caminhao", "caminhoes", "camiao", "carga", "cargas",
        "com", "da", "das", "de", "do", "dos", "e", "em", "entrega", "entregas", "esta", "estao",
        "frete", "fretes", "kanban", "na", "no", "nos", "para", "peso", "por", "pra", "pro", "qual",
        "quais", "que", "rota", "rotas", "tem", "vai", "veiculo", "veiculos",
    }
    if request:
        field = _as_str(request.get("field"))
        if field == "km_atual":
            words = re.sub(r"\bkm\s+atual\b|\bquilometragem\b|\bkm\b", " ", words)
        elif field == "peso":
            words = re.sub(r"\bpeso\s+total\b|\bpeso\b", " ", words)
        elif field == "qtd_entregas":
            words = re.sub(r"\bqtd\s+entregas\b|\bquantidade\s+de\s+entregas\b|\bentregas\b", " ", words)
        display = _as_str(request.get("display"))
        if display:
            words = re.sub(rf"\b{re.escape(normalize(display))}\b", " ", words)
    words = re.sub(r"\b\d[\d.,]*\b", " ", words)
    words = re.sub(r"[^\w\s-]+", " ", words)
    words = re.sub(r"\s+", " ", words).strip()
    return [token for token in words.split() if len(token) >= 3 and token not in ignored_terms]


def _agent_frete_card_lookup_reply(message: str) -> dict | None:
    normalized = normalize(message)
    if not normalized:
        return None

    request = _frete_numeric_lookup_request(message, normalized)
    if not request:
        return None

    try:
        cards = list_fretes()
    except Exception:
        return None
    if not cards:
        return {
            "reply": "Nao encontrei cards de frete no kanban para consultar agora.\n\nFontes: server.py, /api/fretes",
            "actions": [{"name": "refresh_fretes", "label": "Atualizar kanban"}],
        }

    matches: list[dict] = []
    field = _as_str(request.get("field"))
    target_value = request.get("value")
    for card in cards:
        raw = card.get("raw") if isinstance(card.get("raw"), dict) else {}
        if field == "km_atual":
            if _as_int(raw.get("km_atual"), 0) == _as_int(target_value, -1):
                matches.append(card)
            continue
        if field == "qtd_entregas":
            delivery_values = [
                raw.get("qtd_entregas"),
                card.get("deliveries"),
            ]
            if any(_as_int(value, -1) == _as_int(target_value, -2) for value in delivery_values):
                matches.append(card)
            continue
        if field == "peso":
            weight_values = [
                raw.get("peso"),
                raw.get("carga_peso_total"),
                card.get("weight"),
            ]
            if any(abs(_as_float_br(value, -999999.0) - _as_float_br(target_value, 0.0)) <= 0.001 for value in weight_values):
                matches.append(card)

    lookup_tokens = _frete_lookup_tokens(normalized, request)
    if lookup_tokens:
        token_matches = []
        for card in matches:
            raw = card.get("raw") if isinstance(card.get("raw"), dict) else {}
            haystack = normalize(" ".join([
                _as_str(card.get("title")),
                _as_str(card.get("vehicle")),
                _as_str(card.get("plate")),
                _as_str(card.get("load")),
                _as_str(card.get("city")),
                _as_str(raw.get("nome")),
                _as_str(raw.get("cidade")),
                _as_str(raw.get("carga_nome")),
                _as_str(raw.get("carga_cidade")),
                _as_str(raw.get("carga_rota")),
                _as_str(raw.get("carga_cidades")),
                _as_str(raw.get("veiculo_nome")),
                _as_str(raw.get("veiculo_nome_resolvido")),
            ]))
            if all(token in haystack for token in lookup_tokens):
                token_matches.append(card)
        matches = token_matches

    source_label = f"{_as_str(request.get('label'))} {request.get('display')}"
    if not matches:
        source_suffix = f" para {' '.join(lookup_tokens)}" if lookup_tokens else ""
        return {
            "reply": f"Nao encontrei nenhum caminhao no kanban com {source_label}{source_suffix}.\n\nFontes: server.py, /api/fretes",
            "actions": [{"name": "refresh_fretes", "label": "Atualizar kanban"}],
            "workspace": fretes_workspace(cards),
        }

    def _card_line(card: dict) -> str:
        raw = card.get("raw") if isinstance(card.get("raw"), dict) else {}
        vehicle = _as_str(card.get("vehicle")) or "-"
        plate = _as_str(card.get("plate"))
        carga = _as_str(card.get("load")) or _as_str(raw.get("carga_nome")) or "-"
        status = _as_str(card.get("status_label")) or _as_str(card.get("status")) or "-"
        km_atual = _as_int(raw.get("km_atual"), 0)
        peso = raw.get("carga_peso_total") if raw.get("carga_peso_total") not in (None, "", 0, 0.0) else raw.get("peso")
        entregas = _as_int(raw.get("qtd_entregas"), _as_int(card.get("deliveries"), 0))
        return (
            f"Frete #{_as_int(card.get('id'), 0)} | Caminhao {vehicle}"
            + (f" | Placa {plate}" if plate else "")
            + f" | Status {status} | Carga {carga} | KM atual {km_atual} | Peso {_fmt_decimal_br(peso, 0)} | Entregas {entregas}"
        )

    if len(matches) == 1:
        card = matches[0]
        reply = f"O caminhao com {source_label} e: {_card_line(card)}."
        if lookup_tokens:
            reply = f"O caminhao com {source_label} para {' '.join(lookup_tokens)} e: {_card_line(card)}."
        return {
            "reply": f"{reply}\n\nFontes: server.py, /api/fretes",
            "workspace": fretes_workspace(matches, selected_id=card["id"]),
            "actions": [{"name": "refresh_fretes", "label": "Atualizar kanban"}],
        }

    lines = [_card_line(card) for card in matches[:8]]
    prefix = f"Encontrei {len(matches)} card(s) com {source_label}"
    if lookup_tokens:
        prefix += f" para {' '.join(lookup_tokens)}"
    return {
        "reply": (
            prefix + ":\n- "
            + "\n- ".join(lines)
            + "\n\nFontes: server.py, /api/fretes"
        ),
        "workspace": fretes_workspace(matches, selected_id=matches[0]["id"], title="Cards encontrados"),
        "actions": [{"name": "refresh_fretes", "label": "Atualizar kanban"}],
    }


def _agent_module_context_reply(action: str) -> dict | None:
    action = str(action or "").strip()
    module_queries = {
        "module_base": "base da aplicacao server.py RioBranco.html script.js style.css docker-compose.yml Dockerfile",
        "module_ops": "operacao deploy backup status update logs doctor up.sh down.sh update.sh docs/OPERACAO_E_DEPLOY.md",
        "module_fretes": "fretes kanban cargas status mover frete dashboards.html server.py docs/DIAGRAMAS_E_PROCESSOS.md",
        "module_devolucoes": "devolucoes fotos anexos app_data/FotosDevolucoes app_data/ChatAnexos server.py docs/OPERACAO_E_DEPLOY.md",
        "module_nfe": "estoque nfe dfe ocr xml pdf portal receita server.py nfe_ws.py docs/NFE_RECEITA_E_INTEGRACAO.md docs/API_E_DADOS.md",
        "module_vendas": "vendas relatorios csv importacao vendas-cache server.py docs/README.md docs/API_E_DADOS.md",
        "module_chat": "chat ia-rio agent tools/riob_agent_web.py tools/riob_context.py docs/AI_CONTEXT.md",
        "module_sip": "sip cameras freepbx monitoramento server.py docs/ARQUITETURA_SISTEMA.md docs/README.md",
    }
    labels = {
        "module_base": "Base da aplicacao",
        "module_ops": "Operacao e deploy",
        "module_fretes": "Fretes e kanban",
        "module_devolucoes": "Devolucoes e anexos",
        "module_nfe": "Estoque e NF-e",
        "module_vendas": "Vendas e relatorios",
        "module_chat": "Chat e I.A-Rio",
        "module_sip": "SIP, cameras e monitoramento",
    }
    query = module_queries.get(action)
    if not query:
        return None

    context = build_repo_context(query, max_files=8)
    text = format_repo_context(context)
    reply_parts = [f"{labels.get(action, action)}:"]
    if text:
        reply_parts.append(text)
    else:
        reply_parts.append("Nao encontrei trechos suficientes no repositorio para detalhar este modulo.")

    sources = format_repo_sources(context)
    if sources:
        reply_parts.append("")
        reply_parts.append(sources)

    reply_parts.append("")
    reply_parts.append("Se quiser, eu posso aprofundar um fluxo especifico desse modulo.")
    return {"reply": "\n".join(reply_parts).strip(), "actions": system_overview_actions()}


def _agent_attach_repo_sources(result: dict | None, message: str) -> dict | None:
    if not isinstance(result, dict):
        return result
    reply = str(result.get("reply") or "").strip()
    if not reply:
        return result
    context = build_repo_context(message)
    sources = format_repo_sources(context)
    if not sources:
        return result
    if "fonte:" in reply.lower() or "fontes:" in reply.lower():
        return result
    updated = dict(result)
    updated["reply"] = f"{reply}\n\n{sources}"
    return updated


def _web_headers() -> dict[str, str]:
    return {
        "User-Agent": "RioBranco-IA/1.0 (+internal-docs-search)",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }


TECH_DOC_SOURCES = {
    "python": {"label": "Python", "domains": ["docs.python.org"], "docs_url": "https://docs.python.org/3/"},
    "flask": {"label": "Flask", "domains": ["flask.palletsprojects.com", "palletsprojects.com"], "docs_url": "https://flask.palletsprojects.com/"},
    "mariadb": {"label": "MariaDB", "domains": ["mariadb.com"], "docs_url": "https://mariadb.com/kb/en/documentation/"},
    "mysql": {"label": "MySQL", "domains": ["dev.mysql.com", "mysql.com"], "docs_url": "https://dev.mysql.com/doc/"},
    "mysql connector": {"label": "MySQL Connector/Python", "domains": ["dev.mysql.com"], "docs_url": "https://dev.mysql.com/doc/connector-python/en/"},
    "docker": {"label": "Docker", "domains": ["docs.docker.com", "docker.com"], "docs_url": "https://docs.docker.com/"},
    "nginx": {"label": "Nginx", "domains": ["nginx.org"], "docs_url": "https://nginx.org/en/docs/"},
    "ollama": {"label": "Ollama", "domains": ["docs.ollama.com", "ollama.com"], "docs_url": "https://docs.ollama.com/"},
    "firebird": {"label": "Firebird", "domains": ["firebirdsql.org"], "docs_url": "https://firebirdsql.org/en/documentation/"},
    "windows": {"label": "Windows", "domains": ["learn.microsoft.com", "support.microsoft.com"], "docs_url": "https://learn.microsoft.com/windows/"},
    "microsoft": {"label": "Microsoft", "domains": ["learn.microsoft.com", "support.microsoft.com"], "docs_url": "https://learn.microsoft.com/"},
    "azure": {"label": "Azure", "domains": ["learn.microsoft.com", "azure.microsoft.com"], "docs_url": "https://learn.microsoft.com/azure/"},
    "document intelligence": {"label": "Azure Document Intelligence", "domains": ["learn.microsoft.com"], "docs_url": "https://learn.microsoft.com/azure/ai-services/document-intelligence/"},
    "vmware": {"label": "VMware", "domains": ["developer.broadcom.com", "docs.vmware.com"], "docs_url": "https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/"},
    "pyvmomi": {"label": "pyVmomi", "domains": ["developer.broadcom.com", "github.com/vmware/pyvmomi"], "docs_url": "https://github.com/vmware/pyvmomi"},
    "freepbx": {"label": "FreePBX", "domains": ["freepbx.org", "sangoma.com"], "docs_url": "https://www.freepbx.org/documentation/"},
    "asterisk": {"label": "Asterisk", "domains": ["docs.asterisk.org", "asterisk.org"], "docs_url": "https://docs.asterisk.org/"},
    "javascript": {"label": "JavaScript", "domains": ["developer.mozilla.org"], "docs_url": "https://developer.mozilla.org/en-US/docs/Web/JavaScript"},
    "html": {"label": "HTML", "domains": ["developer.mozilla.org"], "docs_url": "https://developer.mozilla.org/en-US/docs/Web/HTML"},
    "css": {"label": "CSS", "domains": ["developer.mozilla.org"], "docs_url": "https://developer.mozilla.org/en-US/docs/Web/CSS"},
    "requests": {"label": "Requests", "domains": ["requests.readthedocs.io"], "docs_url": "https://requests.readthedocs.io/"},
    "paramiko": {"label": "Paramiko", "domains": ["docs.paramiko.org"], "docs_url": "https://docs.paramiko.org/"},
    "reportlab": {"label": "ReportLab", "domains": ["docs.reportlab.com", "reportlab.com"], "docs_url": "https://docs.reportlab.com/"},
    "cryptography": {"label": "cryptography", "domains": ["cryptography.io"], "docs_url": "https://cryptography.io/en/latest/"},
    "lxml": {"label": "lxml", "domains": ["lxml.de"], "docs_url": "https://lxml.de/"},
    "signxml": {"label": "SignXML", "domains": ["xml-security.github.io", "github.com/XML-Security/signxml"], "docs_url": "https://xml-security.github.io/signxml/"},
    "pillow": {"label": "Pillow", "domains": ["pillow.readthedocs.io"], "docs_url": "https://pillow.readthedocs.io/"},
    "pil": {"label": "Pillow", "domains": ["pillow.readthedocs.io"], "docs_url": "https://pillow.readthedocs.io/"},
    "pytesseract": {"label": "pytesseract", "domains": ["pypi.org", "github.com/madmaze/pytesseract"], "docs_url": "https://github.com/madmaze/pytesseract"},
    "tesseract": {"label": "Tesseract OCR", "domains": ["tesseract-ocr.github.io", "github.com/tesseract-ocr/tesseract"], "docs_url": "https://tesseract-ocr.github.io/"},
    "rapidocr": {"label": "RapidOCR", "domains": ["rapidai.github.io", "github.com/RapidAI/RapidOCR"], "docs_url": "https://github.com/RapidAI/RapidOCR"},
    "onnxruntime": {"label": "ONNX Runtime", "domains": ["onnxruntime.ai", "github.com/microsoft/onnxruntime"], "docs_url": "https://onnxruntime.ai/docs/"},
}


def _html_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", value or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _extract_title_and_description(html: str) -> tuple[str, str]:
    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html or "")
    title = _html_text(title_match.group(1)) if title_match else ""
    meta_match = re.search(
        r'(?is)<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\'](.*?)["\']',
        html or "",
    )
    description = _html_text(meta_match.group(1)) if meta_match else ""
    if not description:
        description = _html_text(html or "")[:400]
    return title[:200], description[:500]


def _http_get_text(url: str, timeout: float | None = None) -> str:
    response = requests.get(url, headers=_web_headers(), timeout=timeout or _agent_web_timeout())
    response.raise_for_status()
    response.encoding = response.encoding or response.apparent_encoding or "utf-8"
    return response.text


def _agent_detect_doc_technologies(message: str) -> list[dict]:
    normalized = normalize(message)
    detected: list[dict] = []
    seen: set[str] = set()
    for alias, info in TECH_DOC_SOURCES.items():
        alias_norm = normalize(alias)
        if not alias_norm:
            continue
        if re.search(rf"\b{re.escape(alias_norm)}\b", normalized):
            key = info["label"]
            if key in seen:
                continue
            seen.add(key)
            detected.append(info)
    return detected


def _build_docs_search_query(message: str, technologies: list[dict]) -> str:
    query = str(message or "").strip()
    domains: list[str] = []
    for info in technologies:
        for domain in info.get("domains", []):
            if domain not in domains:
                domains.append(domain)
    if not domains:
        return query
    if len(domains) == 1:
        return f"{query} site:{domains[0]}".strip()
    domain_filter = " OR ".join(f"site:{domain}" for domain in domains[:4])
    return f"{query} ({domain_filter})".strip()


def _duckduckgo_search(query: str, limit: int = 5) -> list[dict]:
    html = _http_get_text(f"https://duckduckgo.com/html/?q={requests.utils.quote(query)}")
    matches = re.findall(
        r'(?is)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?(?:<a[^>]+class="result__snippet"[^>]*>|<div[^>]+class="result__snippet"[^>]*>)(.*?)(?:</a>|</div>)',
        html,
    )
    results: list[dict] = []
    for href, title_html, snippet_html in matches:
        url = href
        parsed = urlparse(href)
        if parsed.netloc.endswith("duckduckgo.com"):
            target = parse_qs(parsed.query).get("uddg")
            if target:
                url = unquote(target[0])
        results.append({
            "title": _html_text(title_html)[:200],
            "url": url,
            "snippet": _html_text(snippet_html)[:300],
        })
        if len(results) >= limit:
            break
    return results


def _docs_need_deep_answer(message: str) -> bool:
    normalized = normalize(message)
    return any(
        term in normalized
        for term in (
            "como ",
            " como",
            "how ",
            "subir",
            "rodar",
            "executar",
            "iniciar",
            "configurar",
            "instalar",
            "setup",
            "passo",
            "tutorial",
            "exemplo",
            "servidor",
            "producao",
            "produção",
        )
    )


def _extract_page_highlights(html: str, limit: int = 3) -> list[str]:
    highlights: list[str] = []
    seen: set[str] = set()
    for _tag, chunk in re.findall(r"(?is)<(h1|h2|h3|p|li)[^>]*>(.*?)</\1>", html or ""):
        text = _html_text(chunk)
        normalized = normalize(text)
        is_short_command = bool(_extract_command_candidates(text))
        if len(text) < 25 and not is_short_command:
            continue
        if normalized in seen:
            continue
        if normalized.startswith(("skip to", "on this page", "navigation", "table of contents")):
            continue
        seen.add(normalized)
        highlights.append(text[:280])
        if len(highlights) >= limit:
            break
    return highlights


def _extract_fragment_scope(html: str, url: str) -> str:
    fragment = _as_str(urlparse(url).fragment)
    if not fragment:
        return html
    id_patterns = [f'id="{fragment}"', f"id='{fragment}'", f'href="#{fragment}"', f"href='#{fragment}'"]
    start = -1
    for pattern in id_patterns:
        start = html.find(pattern)
        if start >= 0:
            break
    if start < 0:
        return html
    scoped = html[start:start + 6000]
    next_section = re.search(r"(?is)<(?:section|h1|h2|h3)\b[^>]*id=[\"'][^\"']+[\"']", scoped[200:])
    if next_section:
        scoped = scoped[:200 + next_section.start()]
    return scoped


def _url_matches_technologies(url: str, technologies: list[dict]) -> bool:
    if not url or not technologies:
        return False
    host = (urlparse(url).netloc or "").lower()
    for info in technologies:
        for domain in info.get("domains", []):
            domain = _as_str(domain).lower()
            if domain and (host == domain or host.endswith("." + domain)):
                return True
    return False


def _prioritize_doc_results(results: list[dict], technologies: list[dict]) -> list[dict]:
    def _priority(item: dict) -> tuple[int, int, int]:
        url = _as_str(item.get("url"))
        path = (urlparse(url).path or "").lower()
        official = 0 if _url_matches_technologies(url, technologies) else 1
        docs_hint = 0 if any(token in path for token in ("/docs", "/doc", "documentation", "tutorial", "guide")) else 1
        snippet_hint = 0 if _as_str(item.get("snippet")) else 1
        return (official, docs_hint, snippet_hint)

    return sorted(results, key=_priority)


def _fetch_web_page_summary(url: str) -> dict | None:
    html = _http_get_text(url)
    title, description = _extract_title_and_description(html)
    scoped_html = _extract_fragment_scope(html, url)
    highlights = _extract_page_highlights(scoped_html)
    if not title and not description and not highlights:
        return None
    return {
        "title": title,
        "description": description,
        "highlights": highlights,
        "url": url,
    }


def _web_time_left(deadline: float | None) -> float:
    if deadline is None:
        return _agent_web_timeout()
    return max(0.25, deadline - time.monotonic())


def _known_doc_candidate_urls(message: str, technologies: list[dict]) -> list[tuple[str, str]]:
    normalized = normalize(message)
    urls: list[tuple[str, str]] = []
    labels = {_as_str(info.get("label")) for info in technologies}
    if "Python" in labels and "http" in normalized and "servidor" in normalized:
        urls.append(("Python", "https://docs.python.org/3/library/http.server.html"))
    if "Python" in labels and "http.server" in normalized:
        urls.append(("Python", "https://docs.python.org/3/library/http.server.html"))
    if "Flask" in labels and ("servidor" in normalized or "server" in normalized or "run" in normalized):
        urls.append(("Flask", "https://flask.palletsprojects.com/cli/#run-the-development-server"))
    return urls


def _try_known_doc_candidates(message: str, technologies: list[dict], deadline: float | None = None) -> dict | None:
    for label, url in _known_doc_candidate_urls(message, technologies):
        if deadline is not None and time.monotonic() >= deadline:
            break
        try:
            page = _fetch_web_page_summary(url)
        except Exception:
            page = None
        if page:
            return _format_doc_page_reply(label, page, fontes=url)
    return None


def _extract_command_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    starters = {"python", "flask", "docker", "ollama", "gunicorn", "uvicorn", "pip", "npm", "node", "git", "curl", "mysql", "firebird", "isql"}
    stop_tokens = {"to", "for", "instead", "because", "which", "that", "from", "with", "where", "when", "by", "warning", "command"}
    allowed_pattern = re.compile(r"^[a-z0-9_./:=:-]+$", re.I)
    for raw_line in text.replace("|", "\n").splitlines():
        line = _as_str(raw_line)
        if not line:
            continue
        line = re.sub(r"^[^a-z0-9$-]+", "", line, flags=re.I)
        if line.startswith("$"):
            line = line[1:].strip()
        tokens = re.findall(r"[A-Za-z0-9_./:=:-]+", line)
        for idx, token in enumerate(tokens):
            if token.lower() not in starters:
                continue
            command_tokens = [token]
            for next_token in tokens[idx + 1:]:
                lowered = next_token.lower()
                if lowered in stop_tokens and len(command_tokens) >= 2:
                    break
                if not allowed_pattern.match(next_token):
                    break
                command_tokens.append(next_token)
            candidate = " ".join(command_tokens).strip(" .,:;")
            candidate = re.sub(r"\s+command$", "", candidate, flags=re.I)
            if len(command_tokens) < 2 or len(candidate) < 6:
                continue
            key = normalize(candidate)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
    return candidates


def _doc_observation(highlights: list[str]) -> str:
    for item in highlights:
        normalized = normalize(item)
        if any(term in normalized for term in ("do not", "nao ", "não ", "warning", "production", "producao", "porta", "port ")):
            return item
    return ""


def _format_doc_page_reply(label: str, page: dict | None, fallback_title: str = "", fallback_summary: str = "", fontes: str = "") -> dict | None:
    if not page and not fallback_title and not fallback_summary:
        return None
    page = page or {}
    title = _as_str(page.get("title")) or _as_str(fallback_title)
    description = _as_str(page.get("description")) or _as_str(fallback_summary)
    highlights = [item for item in (page.get("highlights") or []) if _as_str(item)]
    highlight_commands = _extract_command_candidates("\n".join(highlights))
    description_commands = _extract_command_candidates(description)
    commands = highlight_commands + [cmd for cmd in description_commands if normalize(cmd) not in {normalize(item) for item in highlight_commands}]
    commands = sorted(commands, key=lambda item: (len(item.split()), len(item)))
    observation = _doc_observation(highlights)
    url = _as_str(page.get("url"))
    lines: list[str] = []
    if label:
        lines.append(f"Na documentacao oficial de {label}:")
    elif title:
        lines.append(f"Na documentacao web encontrei {title}:")
    if commands:
        lines.append(f"Comando: `{commands[0]}`")
        if len(commands) > 1:
            lines.append(f"Exemplo: `{commands[1]}`")
    if description and (not commands or normalize(description) not in {normalize(item) for item in highlights}):
        lines.append(f"Resumo: {description}")
    if observation:
        lines.append(f"Observacao: {observation}")
    elif highlights:
        lines.append(f"Detalhe: {highlights[0]}")
    if title and not commands:
        lines.insert(1 if lines else 0, f"Referencia: {title}")
    source_line = fontes or url
    return {"reply": "\n".join(lines) + f"\n\nFontes web: {source_line}"}


def _docs_query_terms(message: str) -> list[str]:
    translations = {
        "comando": ["cli", "-m"],
        "python": ["library"],
        "http": ["http.server", "http", "server"],
        "subir": ["run", "start", "server", "development"],
        "rodar": ["run", "start"],
        "iniciar": ["start", "run"],
        "executar": ["run", "start"],
        "servidor": ["server", "wsgi", "web"],
        "web": ["web", "server"],
        "configurar": ["config", "configure", "configuration"],
        "instalar": ["install", "installation", "setup"],
        "deploy": ["deploy", "deployment", "production"],
        "producao": ["production", "deploy", "wsgi"],
        "produção": ["production", "deploy", "wsgi"],
        "exemplo": ["example", "quickstart", "tutorial"],
        "tutorial": ["tutorial", "quickstart", "example"],
    }
    stopwords = {
        "consultar",
        "consulte",
        "internet",
        "documentacao",
        "documentacao",
        "docs",
        "oficial",
        "na",
        "no",
        "de",
        "do",
        "da",
        "das",
        "dos",
        "um",
        "uma",
        "o",
        "a",
        "e",
        "como",
    }
    tokens = re.findall(r"[a-z0-9]+", normalize(message))
    terms: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in stopwords or len(token) < 2:
            continue
        for value in [token, *translations.get(token, [])]:
            if value in seen:
                continue
            seen.add(value)
            terms.append(value)
    return terms[:12]


def _score_terms_in_text(text: str, terms: list[str]) -> int:
    haystack = normalize(text)
    score = 0
    for term in terms:
        term_norm = normalize(term)
        if not term_norm:
            continue
        if term_norm in haystack:
            score += 2 if len(term_norm) > 4 else 1
    return score


def _extract_links(html: str, base_url: str) -> list[dict]:
    links: list[dict] = []
    seen: set[str] = set()
    for href, text_html in re.findall(r'(?is)<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html or ""):
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        text = _html_text(text_html)
        links.append({
            "url": url,
            "text": text[:200],
        })
    return links


def _page_relevance_score(page: dict, terms: list[str]) -> int:
    text_parts = [
        _as_str(page.get("title")),
        _as_str(page.get("description")),
        " ".join(_as_str(item) for item in page.get("highlights") or []),
        _as_str(page.get("url")),
    ]
    return _score_terms_in_text(" ".join(part for part in text_parts if part), terms)


def _find_internal_docs_summary(message: str, technologies: list[dict], max_depth: int = 2, deadline: float | None = None) -> dict | None:
    terms = _docs_query_terms(message)
    if not technologies or not terms:
        return None
    for info in technologies[:2]:
        if deadline is not None and time.monotonic() >= deadline:
            break
        docs_url = _as_str(info.get("docs_url"))
        if not docs_url:
            continue
        queue: list[tuple[int, str]] = [(0, docs_url)]
        visited: set[str] = set()
        best_page: dict | None = None
        best_score = 0
        while queue:
            if deadline is not None and time.monotonic() >= deadline:
                break
            depth, current_url = queue.pop(0)
            if current_url in visited:
                continue
            visited.add(current_url)
            try:
                html_text = _http_get_text(current_url)
            except Exception:
                continue

            if depth > 0:
                page = _fetch_web_page_summary(current_url)
                if page:
                    page["label"] = _as_str(info.get("label"))
                    score = _page_relevance_score(page, terms)
                    if score > best_score:
                        best_page = page
                        best_score = score

            if depth >= max_depth:
                continue

            links = _extract_links(html_text, current_url)
            scored: list[tuple[int, str]] = []
            for link in links:
                target_url = _as_str(link.get("url"))
                if not target_url or target_url in visited:
                    continue
                if not _url_matches_technologies(target_url, [info]):
                    continue
                haystack = f"{_as_str(link.get('text'))} {urlparse(target_url).path}"
                score = _score_terms_in_text(haystack, terms)
                if score <= 0:
                    continue
                scored.append((score, target_url))
            scored.sort(key=lambda item: (-item[0], len(item[1])))
            for _score, target_url in scored[:6]:
                queue.append((depth + 1, target_url))
        if best_page is not None:
            return best_page
    return None


def _direct_docs_reply(technologies: list[dict]) -> dict | None:
    refs = []
    for info in technologies[:4]:
        url = _as_str(info.get("docs_url"))
        if not url:
            continue
        refs.append(f"{info.get('label')}: {url}")
    if not refs:
        return None
    labels = ", ".join(_as_str(info.get("label")) for info in technologies[:4] if _as_str(info.get("label")))
    reply = f"Encontrei as referencias oficiais de documentacao para {labels}."
    reply += " Links principais: " + "; ".join(refs) + "."
    return {"reply": f"{reply}\n\nFontes web: " + ", ".join(_as_str(info.get("docs_url")) for info in technologies[:4] if _as_str(info.get("docs_url")))}


def _wikipedia_summary(query: str) -> dict | None:
    search_url = (
        "https://pt.wikipedia.org/w/api.php?action=opensearch&limit=1&namespace=0&format=json&search="
        + requests.utils.quote(query)
    )
    data = requests.get(search_url, headers=_web_headers(), timeout=_agent_web_timeout()).json()
    titles = data[1] if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list) else []
    urls = data[3] if isinstance(data, list) and len(data) > 3 and isinstance(data[3], list) else []
    if not titles:
        return None
    title = str(titles[0] or "").strip()
    url = str(urls[0] or "").strip()
    if not title:
        return None
    summary_url = "https://pt.wikipedia.org/api/rest_v1/page/summary/" + requests.utils.quote(title)
    payload = requests.get(summary_url, headers=_web_headers(), timeout=_agent_web_timeout()).json()
    extract = _as_str(payload.get("extract"))
    return {"title": title, "url": url, "snippet": extract[:500]}


def _agent_web_lookup_reply(message: str, chat_mode: str = "ia") -> dict | None:
    if not _agent_web_enabled():
        return None

    normalized = normalize(message)
    if not normalized:
        return None

    explicit_url_match = re.search(r"https?://[^\s]+", message, re.I)
    asks_web = any(
        term in normalized
        for term in (
            "internet",
            "web",
            "site oficial",
            "documentacao",
            "documentacao oficial",
            "docs",
            "manual",
            "wiki",
            "wikipedia",
            "pesquise",
            "pesquisar",
            "procure",
            "consultar na internet",
            "consulte na internet",
        )
    )
    if not explicit_url_match and not asks_web:
        return None

    try:
        deadline = time.monotonic() + _agent_web_budget()
        technologies = _agent_detect_doc_technologies(message)
        deep_answer = _docs_need_deep_answer(message)
        if explicit_url_match:
            url = explicit_url_match.group(0)
            page = _fetch_web_page_summary(url)
            if not page:
                return None
            return _format_doc_page_reply("", page, fontes=url)

        if "wiki" in normalized or "wikipedia" in normalized:
            wiki = _wikipedia_summary(message)
            if wiki:
                reply = f"Na wiki encontrei {wiki['title']}."
                if wiki.get("snippet"):
                    reply += f" Resumo: {wiki['snippet']}"
                return {"reply": f"{reply}\n\nFontes web: {wiki['url']}"}

        direct_docs = _direct_docs_reply(technologies)
        if direct_docs is not None and not deep_answer:
            return direct_docs

        if direct_docs is not None and deep_answer:
            quick_candidate = _try_known_doc_candidates(message, technologies, deadline)
            if quick_candidate:
                return quick_candidate
            internal_page = _find_internal_docs_summary(message, technologies, deadline=deadline)
            if internal_page:
                return _format_doc_page_reply(_as_str(internal_page.get("label")), internal_page)

        if time.monotonic() >= deadline:
            return direct_docs

        search_query = _build_docs_search_query(message, technologies) if technologies else message
        results = _duckduckgo_search(search_query, limit=4)
        if results:
            results = _prioritize_doc_results(results, technologies)
            top = results[0]
            page = None
            top_url = _as_str(top.get("url"))
            if top_url:
                try:
                    page = _fetch_web_page_summary(top_url)
                except Exception:
                    page = None
            fontes = ", ".join(item.get("url") or "" for item in results[:3] if item.get("url"))
            label = ", ".join(info.get("label") or "" for info in technologies if info.get("label"))
            return _format_doc_page_reply(
                label,
                page,
                fallback_title=_as_str(top.get("title")) or top_url,
                fallback_summary=_as_str(top.get("snippet")),
                fontes=fontes,
            )

        if direct_docs is not None:
            for info in technologies[:2]:
                docs_url = _as_str(info.get("docs_url"))
                if not docs_url:
                    continue
                try:
                    page = _fetch_web_page_summary(docs_url)
                except Exception:
                    page = None
                if not page:
                    continue
                return _format_doc_page_reply(_as_str(info.get("label")), page, fontes=docs_url)

        return direct_docs
    except Exception:
        return None


def _agent_web_intent(message: str, chat_mode: str = "ia") -> bool:
    if not _agent_web_enabled():
        return False
    normalized = normalize(message)
    if not normalized:
        return False
    if re.search(r"https?://[^\s]+", message or "", re.I):
        return True
    return any(
        term in normalized
        for term in (
            "internet",
            "web",
            "site oficial",
            "documentacao",
            "documentacao oficial",
            "docs",
            "manual",
            "wiki",
            "wikipedia",
            "pesquise",
            "pesquisar",
            "procure",
            "consultar na internet",
            "consulte na internet",
        )
    )


def _agent_storage_context_reply(message: str) -> dict | None:
    normalized = normalize(message)
    if not normalized:
        return None
    storage_terms = ("foto", "fotos", "anexo", "anexos", "upload", "uploads", "pasta", "diretorio", "armazen", "armazenadas", "arquivo", "arquivos")
    if not any(word in normalized for word in storage_terms):
        return None

    server_text = ""
    compose_text = ""
    docs_text = ""
    try:
        server_text = (ROOT / "server.py").read_text(encoding="utf-8", errors="ignore")
    except Exception:
        pass
    try:
        compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8", errors="ignore")
    except Exception:
        pass
    try:
        docs_text = (ROOT / "docs/OPERACAO_E_DEPLOY.md").read_text(encoding="utf-8", errors="ignore")
    except Exception:
        pass

    def extract(pattern: str, text: str) -> str:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        return str(match.group(1)).strip() if match else ""

    def _strip_quotes(value: str) -> str:
        return value.strip().strip('"').strip("'")

    container_root = ""
    match = re.search(r"^\s*RB_DATA_DIR:\s*([^\s#]+)", compose_text, re.IGNORECASE | re.MULTILINE)
    if match:
        container_root = _strip_quotes(match.group(1))
    if not container_root:
        container_root = extract(r'DATA_ROOT\s*=\s*os\.environ\.get\("RB_DATA_DIR",\s*([A-Z_]+)\)', server_text)
        if container_root == "BASE_DIR":
            container_root = "/data/app"
    if not container_root:
        container_root = "/data/app"

    host_volume = "app_data"
    if "app_data:/data/app" not in compose_text.replace(" ", ""):
        host_volume = ""

    fotos_dir = extract(r'FOTOS_DIR\s*=\s*os\.path\.join\([^,]+,\s*"([^"]+)"\)', server_text) or "FotosDevolucoes"
    chat_dir = extract(r'CHAT_ATTACHMENTS_DIR\s*=\s*os\.path\.join\([^,]+,\s*"([^"]+)"\)', server_text) or "ChatAnexos"
    vendas_dir = extract(r'VENDAS_UPLOADS_DIR\s*=\s*os\.path\.join\([^,]+,\s*"([^"]+)"\)', server_text) or "uploads"
    req_dir = extract(r'REQ_ABAST_DIR\s*=\s*os\.path\.join\([^,]+,\s*"([^"]+)"\)', server_text) or "RequisicoesAbastecimento"

    if "foto" in normalized or "devolu" in normalized:
        reply = (
            f"As fotos de devolucao ficam em `{container_root}/{fotos_dir}` dentro do container, "
            f"com subpastas `devolucao_<id>`."
        )
    elif "anexo" in normalized:
        reply = f"Os anexos do chat ficam em `{container_root}/{chat_dir}`."
    elif "upload" in normalized:
        reply = f"Os uploads da area de vendas ficam em `{container_root}/vendas-cache/{vendas_dir}`."
    elif "requis" in normalized:
        reply = f"As requisicoes de abastecimento ficam em `{container_root}/{req_dir}`."
    else:
        reply = (
            f"O sistema armazena arquivos em `{container_root}` e subpastas como `{fotos_dir}`, "
            f"`{chat_dir}`, `{req_dir}` e `vendas-cache/{vendas_dir}`."
        )

    if host_volume:
        reply += f" No host Docker isso persiste no volume `{host_volume}`."
    if any(word in normalized for word in ("deploy", "subir", "build", "rebuild", "reiniciar")):
        reply += " Nao precisa de deploy para consultar isso; so se voce mudar o codigo ou a configuracao dessas rotinas."

    result = {"reply": reply}
    return _agent_attach_repo_sources(result, message)


def _devolucao_total_items(row: dict) -> int:
    return sum(_as_int(row.get(key), 0) for key in DEVOLUCAO_ITEMS)


def _devolucao_items_preview(row: dict) -> str:
    parts = []
    for key in DEVOLUCAO_ITEMS:
        qty = _as_int(row.get(key), 0)
        if qty > 0:
            parts.append(f"{key}={qty}")
    return ", ".join(parts) if parts else "sem itens informados"


def _message_wants_gap_analysis(normalized: str) -> bool:
    return any(
        term in normalized
        for term in (
            "nao tem",
            "sem devolucao",
            "sem devolucoes",
            "sem lancamento",
            "sem lancamentos",
            "falta devolucao",
            "faltando devolucao",
            "pendente de devolucao",
            "pendentes de devolucao",
            "nao possui",
            "nao possuem",
        )
    )


def _agent_devolucao_lookup_reply(message: str) -> dict | None:
    normalized = normalize(message)
    if not normalized or not is_devolucao_message(normalized) or is_devolucao_create_message(normalized):
        return None

    frete_id = extract_devolucao_frete_id(message) or 0
    wants_missing = _message_wants_gap_analysis(normalized)
    wants_analytics = _message_wants_analytics(normalized) or (_message_time_request(normalized) is not None)
    wants_lookup = _message_wants_listing(normalized) or _message_wants_count_or_summary(normalized) or any(
        term in normalized for term in (
            "lancamento",
            "lancamentos",
            "tem de devolucao",
            "tem de devolução",
            "tem devolucao",
            "tem devolução",
            "existe devolucao",
            "existe devolução",
            "o que tem",
        )
    )
    vehicle_query = any(term in normalized for term in ("caminhao", "camiao", "veiculo"))
    conferente_query = "conferente" in normalized
    wants_lookup = wants_lookup or wants_missing or wants_analytics or vehicle_query or conferente_query or (frete_id > 0)
    if not wants_lookup:
        return None

    try:
        rows = system_api("GET", "/api/devolucoes")
    except Exception:
        return None
    rows = rows if isinstance(rows, list) else []

    numbers = _extract_message_numbers(message)
    ignored_terms = set(DEVOLUCAO_WORDS) | DEVOLUCAO_ACTION_WORDS | {
        "listar", "lista", "mostrar", "mostra", "ver", "qual", "quais", "que", "tem", "o", "os", "as", "a",
        "de", "da", "do", "das", "dos", "para", "com", "lancamento", "lancamentos", "lançamento", "lançamentos",
        "caminhao", "caminhoes", "camiao", "veiculo", "veiculos", "frete", "conferente", "agora",
        "nao", "sem", "falta", "faltando", "pendente", "pendentes", "possui", "possuem",
        "lancada", "lancadas", "lancado", "lancados", "registrada", "registradas", "registrado", "registrados",
    }
    hint_tokens = _message_hint_tokens(message, ignored_terms)

    semantic = _summarize_semantic_business_analysis("devolucoes", rows, normalized)
    if semantic and not vehicle_query and not conferente_query and frete_id <= 0:
        return {"reply": f"{semantic}\n\nFontes: server.py, /api/devolucoes"}

    if wants_missing:
        try:
            frete_rows = system_api("GET", "/api/fretes")
        except Exception:
            frete_rows = []
        frete_rows = frete_rows if isinstance(frete_rows, list) else []
        cards = [frete_card(item) for item in frete_rows if isinstance(item, dict)]
        devolucao_frete_ids = {
            _as_int(row.get("frete_id"), 0)
            for row in rows
            if isinstance(row, dict) and _as_int(row.get("frete_id"), 0) > 0
        }

        filtered_cards = cards
        if frete_id > 0:
            filtered_cards = [card for card in filtered_cards if _as_int(card.get("id"), 0) == frete_id]
        elif vehicle_query and numbers:
            target = str(numbers[0])
            vehicle_cards = []
            for card in filtered_cards:
                raw = card.get("raw") or {}
                vehicle_text = normalize(" ".join([
                    _as_str(card.get("vehicle")),
                    _as_str(card.get("plate")),
                    str(_as_int(raw.get("veiculo_id"), 0)),
                    _as_str(raw.get("carga_veiculo_numero")),
                    str(_as_int(card.get("id"), 0)),
                ]))
                if re.search(rf"\b{re.escape(target)}\b", vehicle_text):
                    vehicle_cards.append(card)
            filtered_cards = vehicle_cards
        elif hint_tokens:
            hinted_cards = []
            for card in filtered_cards:
                raw = card.get("raw") or {}
                haystack = normalize(" ".join([
                    str(_as_int(card.get("id"), 0)),
                    _as_str(card.get("title")),
                    _as_str(card.get("vehicle")),
                    _as_str(card.get("plate")),
                    _as_str(card.get("load")),
                    _as_str(card.get("city")),
                    _as_str(raw.get("nome")),
                    _as_str(raw.get("carga_nome")),
                    _as_str(raw.get("carga_cidade")),
                    _as_str(raw.get("carga_rota")),
                    _as_str(raw.get("carga_veiculo_numero")),
                ]))
                if all(token in haystack for token in hint_tokens):
                    hinted_cards.append(card)
            filtered_cards = hinted_cards

        if vehicle_query and numbers and not filtered_cards:
            target = str(numbers[0])
            return {
                "reply": f"Nao encontrei fretes atuais para o caminhao {target} comparar com devolucoes.\n\nFontes: server.py, /api/fretes, /api/devolucoes"
            }

        if frete_id > 0 and not filtered_cards:
            return {
                "reply": f"Nao encontrei o frete {frete_id} no kanban atual para comparar com devolucoes.\n\nFontes: server.py, /api/fretes, /api/devolucoes"
            }

        missing_cards = [
            card for card in filtered_cards
            if _as_int(card.get("id"), 0) > 0 and _as_int(card.get("id"), 0) not in devolucao_frete_ids
        ]

        if not missing_cards:
            if vehicle_query and numbers:
                target = str(numbers[0])
                reply = f"Nao encontrei frete sem devolucao lancada para o caminhao {target}."
            elif frete_id > 0:
                reply = f"O frete {frete_id} ja tem devolucao lancada."
            else:
                reply = "Nao encontrei caminhao sem devolucao lancada no momento."
            return {
                "reply": f"{reply}\n\nFontes: server.py, /api/fretes, /api/devolucoes",
                "actions": [
                    {"name": "refresh_fretes", "label": "Atualizar kanban"},
                    {"name": "list_devolucoes", "label": "Listar devolucoes", "kind": "secondary"},
                ],
            }

        lines = [f"Encontrei {len(missing_cards)} frete(s) sem devolucao lancada."]
        for card in missing_cards[:8]:
            lines.append(
                f"Frete #{_as_int(card.get('id'), 0)} | "
                f"Caminhao {_as_str(card.get('vehicle')) or '-'} | "
                f"Status {_as_str(card.get('status_label')) or '-'} | "
                f"Carga {_as_str(card.get('load')) or '-'}"
            )
        if len(missing_cards) > 8:
            lines.append(f"... e mais {len(missing_cards) - 8}.")
        return {
            "reply": "\n".join(lines) + "\n\nFontes: server.py, /api/fretes, /api/devolucoes",
            "workspace": fretes_workspace(missing_cards, selected_id=missing_cards[0]["id"], title="Fretes sem devolucao"),
            "actions": [
                {"name": "list_devolucoes", "label": "Listar devolucoes"},
                {"name": "refresh_fretes", "label": "Atualizar kanban", "kind": "secondary"},
            ],
        }

    matches = rows
    if frete_id:
        matches = [row for row in matches if _as_int(row.get("frete_id"), 0) == frete_id]

    if vehicle_query and numbers:
        target = str(numbers[0])
        vehicle_matches = []
        for row in matches:
            vehicle_text = normalize(" ".join([
                _as_str(row.get("veiculo_nome")),
                str(_as_int(row.get("veiculo_id"), 0)),
            ]))
            if re.search(rf"\b{re.escape(target)}\b", vehicle_text):
                vehicle_matches.append(row)
        matches = vehicle_matches

    if conferente_query and hint_tokens:
        filtered = []
        for row in matches:
            conferente_text = normalize(_as_str(row.get("conferente_nome")))
            if all(token in conferente_text for token in hint_tokens):
                filtered.append(row)
        matches = filtered
    elif hint_tokens:
        filtered = []
        for row in matches:
            haystack = normalize(" ".join([
                _as_str(row.get("frete_nome")),
                _as_str(row.get("veiculo_nome")),
                _as_str(row.get("conferente_nome")),
                str(_as_int(row.get("id"), 0)),
                str(_as_int(row.get("frete_id"), 0)),
                str(_as_int(row.get("veiculo_id"), 0)),
            ]))
            if all(token in haystack for token in hint_tokens):
                filtered.append(row)
        matches = filtered

    if vehicle_query and numbers and not matches:
        target = str(numbers[0])
        return {
            "reply": f"Nao encontrei lancamentos de devolucao para o caminhao {target}.\n\nFontes: server.py, /api/devolucoes"
        }

    if frete_id and not matches:
        return {
            "reply": f"Nao encontrei lancamentos de devolucao para o frete {frete_id}.\n\nFontes: server.py, /api/devolucoes"
        }

    if not matches:
        return None

    label = "devolucao(oes)"
    if vehicle_query and numbers:
        label = f"devolucao(oes) para o caminhao {numbers[0]}"
    elif frete_id:
        label = f"devolucao(oes) para o frete {frete_id}"

    lines = [f"Encontrei {len(matches)} {label}."]
    for row in matches[:8]:
        frete_nome = _as_str(row.get("frete_nome")) or "-"
        conferente = _as_str(row.get("conferente_nome")) or "-"
        total = _devolucao_total_items(row)
        items = _devolucao_items_preview(row)
        fotos = "sim" if row.get("tem_fotos") or row.get("fotos") else "nao"
        lines.append(
            f"#{_as_int(row.get('id'), 0)} - frete #{_as_int(row.get('frete_id'), 0)} {frete_nome} | "
            f"conferente {conferente} | total itens: {total} | {items} | fotos: {fotos}"
        )
    if len(matches) > 8:
        lines.append(f"... e mais {len(matches) - 8}.")
    return {"reply": "\n".join(lines) + "\n\nFontes: server.py, /api/devolucoes"}


def _agent_backup_dir() -> Path:
    env = load_env()
    configured = env.get("RB_DB_BACKUP_PATH") or os.environ.get("RB_DB_BACKUP_PATH") or "./backupsSql"
    path = Path(configured)
    if not path.is_absolute():
        path = ROOT / path
    return path


def _agent_latest_backup_file(patterns: tuple[str, ...] = ("*.sql", "*.sql.gz", "*.tar.gz")) -> Path | None:
    directory = _agent_backup_dir()
    if not directory.exists():
        return None
    backups: list[Path] = []
    for pattern in patterns:
        backups.extend(directory.glob(pattern))
    if not backups:
        return None
    return max(backups, key=lambda item: item.stat().st_mtime)


def _agent_backup_local_reply(message: str) -> dict | None:
    normalized = normalize(message)
    if not normalized:
        return None

    info_terms = (
        "ultimo backup",
        "último backup",
        "qual backup",
        "backup salvo",
        "backup encontrado",
        "tem backup",
        "onde fica o backup",
        "onde estao os backups",
        "onde estão os backups",
    )
    if not any(term in normalized for term in info_terms):
        return None

    backup_dir = _agent_backup_dir()
    last = _agent_latest_backup_file()
    if not last:
        reply = f"Nao encontrei backup salvo em `{backup_dir}`."
    else:
        try:
            relative = last.relative_to(ROOT)
            label = str(relative)
        except ValueError:
            label = str(last)
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last.stat().st_mtime))
        reply = f"O ultimo backup encontrado e `{label}`, salvo em {when}."
    reply += f" Diretorio configurado: `{backup_dir}`."
    return {"reply": f"{reply}\n\nFontes: tools/riob_agent.py, .env, backupsSql"}


def _extract_message_numbers(message: str) -> list[int]:
    normalized = normalize(message)
    return [int(value) for value in re.findall(r"\b\d+\b", normalized or "")]


def _message_hint_tokens(message: str, ignored_terms: set[str]) -> list[str]:
    normalized = normalize(message)
    for term in ignored_terms:
        normalized = re.sub(rf"\b{re.escape(normalize(term))}\b", " ", normalized)
    normalized = re.sub(r"[^\w\s-]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return [token for token in normalized.split() if len(token) >= 3]


def _resolve_vehicle_id_for_message(message: str) -> tuple[int, dict | None]:
    try:
        rows = system_api("GET", "/api/dashboard_frota")
    except Exception:
        return 0, None
    if not isinstance(rows, list):
        return 0, None

    numbers = _extract_message_numbers(message)
    if numbers:
        for number in numbers:
            for row in rows:
                veiculo_id = _as_int(row.get("veiculo_id") or row.get("id"), 0)
                vehicle_text = normalize(" ".join([
                    _as_str(row.get("veiculo_nome")),
                    _as_str(row.get("placa")),
                    _as_str(row.get("modelo")),
                    str(veiculo_id),
                ]))
                if re.search(rf"\b{number}\b", vehicle_text):
                    return veiculo_id, row

    tokens = _message_hint_tokens(message, {
        "mostrar",
        "mostra",
        "listar",
        "lista",
        "ver",
        "detalhes",
        "detalhe",
        "historico",
        "histórico",
        "frota",
        "veiculo",
        "veiculos",
        "caminhao",
        "caminhoes",
        "caminhão",
        "caminhões",
        "do",
        "da",
        "de",
        "qual",
        "quais",
    })
    best_row = None
    best_score = 0
    for row in rows:
        veiculo_id = _as_int(row.get("veiculo_id") or row.get("id"), 0)
        vehicle_text = normalize(" ".join([
            _as_str(row.get("veiculo_nome")),
            _as_str(row.get("placa")),
            _as_str(row.get("modelo")),
            str(veiculo_id),
        ]))
        score = 0
        for token in tokens:
            if token in vehicle_text:
                score += 1
        if score > best_score:
            best_score = score
            best_row = row
    if best_row and best_score > 0:
        return _as_int(best_row.get("veiculo_id") or best_row.get("id"), 0), best_row
    return 0, None


def _resolve_chat_contact_for_message(message: str) -> tuple[int, dict | None]:
    usuario = get_logged_usuario() or {}
    usuario_id = _as_int(usuario.get("id"), 0)

    for number in _extract_message_numbers(message):
        if number > 0 and number != usuario_id:
            return number, {"id": number}

    tokens = _message_hint_tokens(message, {
        "mostrar",
        "mostra",
        "listar",
        "lista",
        "ver",
        "conversa",
        "conversa",
        "mensagem",
        "mensagens",
        "chat",
        "historico",
        "histórico",
        "com",
        "do",
        "da",
        "de",
        "usuario",
        "usuário",
        "contato",
        "meu",
        "minha",
    })
    if not tokens:
        return 0, None

    try:
        rows = system_api("GET", "/api/usuarios")
    except Exception:
        return 0, None
    if not isinstance(rows, list):
        return 0, None

    best_row = None
    best_score = 0
    for row in rows:
        row_id = _as_int(row.get("id"), 0)
        if row_id <= 0 or row_id == usuario_id:
            continue
        user_text = normalize(" ".join([
            _as_str(row.get("nome")),
            _as_str(row.get("login")),
            str(row_id),
        ]))
        score = 0
        for token in tokens:
            if token in user_text:
                score += 1
        if score > best_score:
            best_score = score
            best_row = row
    if best_row and best_score > 0:
        return _as_int(best_row.get("id"), 0), best_row
    return 0, None


READ_ONLY_MODULES = [
    {
        "name": "status_api",
        "label": "status geral do sistema",
        "keywords": ["status do sistema", "status geral do sistema", "saude do sistema", "saúde do sistema", "status da api"],
        "path": "/api/status",
        "fields": ["api", "database", "esxi", "monitor_apps", "cameras", "sip", "nfe", "usuario_logado"],
    },
    {
        "name": "usuario_logado",
        "label": "usuario logado",
        "keywords": ["quem esta logado", "quem está logado", "usuario logado", "usuário logado", "meus dados", "meu usuario", "meu usuário"],
        "path": "/api/me",
        "fields": ["ok", "usuario"],
    },
    {
        "name": "sip_config",
        "label": "configuracao SIP",
        "keywords": ["sip", "freepbx", "ramal", "telefonia", "pabx"],
        "path": "/api/sip/config",
        "fields": ["habilitado", "modo_ativo", "freepbx", "setevoip_direto"],
    },
    {
        "name": "nfe_config",
        "label": "configuracao NF-e",
        "keywords": ["nfe config", "configuracao nfe", "configuração nfe", "df-e", "dfe", "sefaz", "nota fiscal"],
        "path": "/api/nfe/config",
        "fields": ["ambiente", "cnpj_emitente", "uf_emitente", "manifestar_automaticamente"],
    },
    {
        "name": "dashboard",
        "label": "dashboard geral",
        "keywords": ["dashboard geral", "painel geral", "dashboard do sistema"],
        "path": "/api/dashboard",
        "fields": ["fretes", "estoque", "devolucoes", "vendas", "frota"],
    },
    {
        "name": "dashboard_estoque",
        "label": "dashboard de estoque",
        "keywords": ["dashboard estoque", "painel estoque", "indicadores estoque"],
        "path": "/api/dashboard_estoque",
        "fields": ["cards", "resumo", "top_produtos", "total_itens"],
    },
    {
        "name": "estoque_movimentos",
        "label": "movimentos de estoque",
        "keywords": ["movimento de estoque", "movimentos de estoque", "historico de estoque", "histórico de estoque", "lancamentos de estoque", "lançamentos de estoque"],
        "path": "/api/estoque",
        "fields": ["id", "tipo", "nome_produto", "quantidade", "data_movimento"],
    },
    {
        "name": "estoque_produtos",
        "label": "produtos de estoque",
        "keywords": ["produto de estoque", "produtos de estoque", "cadastro de produtos", "itens de estoque", "sku", "skus"],
        "path": "/api/estoque/produtos",
        "fields": ["id", "nome_produto", "codigo_produto_nfe", "codigo_barras", "grupo_estoque"],
    },
    {
        "name": "estoque_conferencias",
        "label": "conferencias de estoque",
        "keywords": ["conferencia de estoque", "conferencias de estoque", "conferência de estoque", "conferências de estoque", "nfes pendentes", "conferencias pendentes"],
        "path": "/api/estoque/conferencias",
        "fields": ["id", "status", "numero_nota", "emitente_nome", "total_itens"],
    },
    {
        "name": "pontos_venda",
        "label": "pontos de venda",
        "keywords": ["ponto de venda", "pontos de venda", "pdv", "clientes da rota", "visitas da rota", "mais visitas", "rota mais visitada", "rota teve mais visitas"],
        "path": "/api/pontos_venda",
        "fields": ["id", "vendedor", "cliente", "rota", "visita_periodicidade", "dia_semana"],
    },
    {
        "name": "pontos_venda_relatorio",
        "label": "relatorio de pontos de venda",
        "keywords": ["relatorio pontos de venda", "relatório pontos de venda", "agenda de visitas", "visitas da semana"],
        "path": "/api/pontos_venda/relatorio",
        "fields": ["resumo", "itens", "por_dia", "semana_inicio", "semana_fim"],
    },
    {
        "name": "comissao_lancamentos",
        "label": "lancamentos de comissao",
        "keywords": ["comissao", "comissão", "lancamentos de comissao", "lançamentos de comissão", "rota comissao"],
        "path": "/api/comissao/lancamentos",
        "fields": ["id", "cod_vendedor", "motorista", "entregador", "rota", "total_comissao"],
    },
    {
        "name": "comissao_cadastros",
        "label": "cadastros de comissao",
        "keywords": ["cadastros de comissao", "cadastros comissão", "vendedores comissao", "entregadores comissao"],
        "path": "/api/comissao/cadastros",
        "fields": ["id", "codigo", "nome", "funcao", "ativo"],
    },
    {
        "name": "comissao_cidades",
        "label": "rotas da comissao",
        "keywords": ["cidades da comissao", "rotas da comissao", "rotas comissão"],
        "path": "/api/comissao/cidades",
        "fields": ["id", "rota"],
    },
    {
        "name": "comissao_relatorios",
        "label": "relatorios de comissao",
        "keywords": ["relatorio de comissao", "relatório de comissão", "fechamento de comissao", "fechamento comissão", "refugo na comissao", "maior refugo na comissao", "entregador refugo"],
        "path": "/api/comissao/relatorios",
        "fields": ["resumo", "totais", "itens"],
    },
    {
        "name": "vendas_dashboard",
        "label": "dashboard de vendas",
        "keywords": ["dashboard de vendas", "painel de vendas", "indicadores de vendas", "vendas agora", "vendedor mais cresceu", "vendedor mais caiu", "cresceu nas vendas", "caiu nas vendas", "mes passado nas vendas", "este mes nas vendas", "comparar vendas", "vendedor mais perdeu valor", "cliente mais perdeu valor", "perdeu valor nas vendas"],
        "path": "/api/vendas/dashboard",
        "fields": ["resumo", "cards", "top_clientes", "top_vendedores"],
    },
    {
        "name": "dashboard_vendas_painel",
        "label": "painel consolidado de vendas",
        "keywords": ["dashboard_vendas", "painel consolidado vendas", "painel consolidado de vendas", "dashboard vendas painel"],
        "path": "/api/dashboard_vendas",
        "fields": ["resumo", "cards", "top_clientes", "top_vendedores"],
    },
    {
        "name": "vendas_config",
        "label": "configuracao de vendas",
        "keywords": ["configuracao vendas", "configuração vendas", "fonte vendas", "cache vendas"],
        "path": "/api/vendas/config",
        "fields": ["config", "fonte", "imports", "regras_importacao"],
    },
    {
        "name": "vendas_relatorio",
        "label": "relatorio de vendas",
        "keywords": ["relatorio de vendas", "relatório de vendas", "bonificacoes", "bonificações", "variacao de preco", "variação de preço", "mix embalagens"],
        "path": "/api/vendas/relatorio",
        "fields": ["resumo", "itens", "cards", "totais"],
    },
    {
        "name": "abastecimentos",
        "label": "abastecimentos",
        "keywords": ["abastecimento", "abastecimentos", "abasteceu", "combustivel", "combustível", "posto", "postos"],
        "path": "/api/abastecimentos",
        "fields": ["id", "veiculo_nome", "placa", "km", "posto", "combustivel_tipo", "status"],
    },
    {
        "name": "manutencoes",
        "label": "manutencoes",
        "keywords": ["manutencao", "manutenção", "manutencoes", "manutenções", "oficina"],
        "path": "/api/manutencoes",
        "fields": ["id", "veiculo_nome", "placa", "tipo", "km", "valor", "data_registro"],
    },
    {
        "name": "trocas_oleo",
        "label": "trocas de oleo",
        "keywords": ["troca de oleo", "trocas de oleo", "óleo", "oleo motor"],
        "path": "/api/trocas_oleo",
        "fields": ["id", "veiculo_nome", "placa", "tipo", "km", "data_registro"],
    },
    {
        "name": "trocas_pneu",
        "label": "trocas de pneu",
        "keywords": ["troca de pneu", "trocas de pneu", "pneu", "pneus", "rodizio de pneu", "rodízio de pneu"],
        "path": "/api/trocas_pneu",
        "fields": ["id", "veiculo_nome", "placa", "marca", "km", "quantidade", "localizacao"],
    },
    {
        "name": "lavagens",
        "label": "lavagens",
        "keywords": ["lavagem", "lavagens", "lavar caminhao", "lavar caminhão"],
        "path": "/api/lavagens",
        "fields": ["id", "veiculo_nome", "placa", "data_lavagem", "km", "local", "valor"],
    },
    {
        "name": "dashboard_frota",
        "label": "dashboard da frota",
        "keywords": ["dashboard da frota", "dashboard frota", "painel da frota", "painel frota", "gestao de frota", "gestão de frota"],
        "path": "/api/dashboard_frota",
        "fields": ["veiculo_nome", "placa", "frete_status", "falta_manut_km", "falta_oleo_km", "alerta"],
    },
    {
        "name": "frota_resumo",
        "label": "resumo da frota",
        "keywords": ["resumo da frota", "frota resumo", "km da frota", "status da frota", "custo por km", "custo/km", "pior custo por km"],
        "path": "/api/frota_resumo",
        "fields": ["id", "nome", "placa", "km_atual", "falta_manut_km", "falta_oleo_km"],
    },
    {
        "name": "frota_historico",
        "label": "historico da frota",
        "keywords": ["historico do caminhao", "histórico do caminhão", "historico do veiculo", "histórico do veículo", "historico da frota"],
        "path_builder": "frota_historico",
        "fields": ["veiculo", "frete_atual", "resumo", "historico"],
    },
    {
        "name": "carga_detalhes",
        "label": "detalhes da carga",
        "keywords": ["detalhes da carga", "detalhe da carga", "detalhes do frete", "detalhe do frete"],
        "path_builder": "carga_detalhes",
        "fields": ["carga", "frete", "estoque", "resumo"],
    },
    {
        "name": "chat_conversa",
        "label": "conversa do chat",
        "keywords": ["conversa com", "mensagens com", "chat com", "historico do chat", "histórico do chat"],
        "path_builder": "chat_conversa",
        "fields": ["id", "remetente_nome", "destinatario_nome", "mensagem", "data_envio"],
    },
    {
        "name": "usuarios_chat_unread",
        "label": "mensagens nao lidas do chat",
        "keywords": ["mensagens nao lidas", "mensagens não lidas", "chat nao lido", "chat não lido", "unread chat"],
        "path_builder": "chat_unread",
        "fields": ["total", "por_contato"],
    },
]


def _message_wants_count_or_summary(normalized: str) -> bool:
    return any(
        term in normalized
        for term in (
            "quantos",
            "quantas",
            "quantidade",
            "total",
            "resumo",
            "estatistica",
            "estatisticas",
            "estatístico",
            "estatísticos",
            "analise",
            "análise",
            "como esta",
            "como está",
            "situacao",
            "situação",
            "status",
        )
    )


def _message_wants_analytics(normalized: str) -> bool:
    if _message_wants_count_or_summary(normalized):
        return True
    if any(term in normalized for term in ("ranking", "top", "distribuicao", "distribuição")):
        return True
    if any(term in normalized for term in ("caiu", "queda", "recu", "diminuiu", "piorou", "cresceu", "variacao", "variação", "comparar", "periodo anterior")):
        return True
    return bool(re.search(r"\b(qual|quais)\b.*\b(mais|menos|maior|maiores|menor|menores)\b", normalized))


def _message_wants_listing(normalized: str) -> bool:
    return any(term in normalized for term in ("listar", "lista", "mostrar", "mostra", "ver", "quais", "ultimos", "últimos", "recentes", "detalhes"))


def _read_only_module_match(message: str) -> dict | None:
    normalized = normalize(message)
    if not normalized:
        return None
    best = None
    best_score = 0
    for item in READ_ONLY_MODULES:
        score = 0
        for keyword in item.get("keywords", []):
            if normalize(keyword) in normalized:
                score = max(score, len(normalize(keyword)))
        if score > best_score:
            best = item
            best_score = score
    return best


def _read_only_module_path(item: dict, message: str) -> str | None:
    builder = item.get("path_builder")
    if builder == "chat_unread":
        usuario = get_logged_usuario()
        usuario_id = _as_int((usuario or {}).get("id"), 0)
        if usuario_id <= 0:
            return None
        return f"/api/chat/unread?usuario_id={usuario_id}"
    if builder == "chat_conversa":
        usuario = get_logged_usuario()
        usuario_id = _as_int((usuario or {}).get("id"), 0)
        contato_id, _ = _resolve_chat_contact_for_message(message)
        if usuario_id <= 0 or contato_id <= 0:
            return None
        return f"/api/chat/conversa?usuario_id={usuario_id}&contato_id={contato_id}&limit=50"
    if builder == "frota_historico":
        veiculo_id, _ = _resolve_vehicle_id_for_message(message)
        if veiculo_id <= 0:
            return None
        return f"/api/frota_historico/{veiculo_id}"
    if builder == "carga_detalhes":
        ids = _extract_message_numbers(message)
        if not ids:
            return None
        return f"/api/cargas/{ids[0]}/detalhes"
    return _as_str(item.get("path"))


def _read_only_module_missing_reply(item: dict) -> dict | None:
    builder = item.get("path_builder")
    if builder == "chat_unread":
        return {"reply": "Para consultar mensagens nao lidas do chat, preciso de um usuario logado nesta sessao.\n\nFontes: server.py, /api/chat/unread"}
    if builder == "chat_conversa":
        return {"reply": "Para abrir uma conversa do chat, preciso de um usuario logado e do contato informado por nome ou id.\n\nFontes: server.py, /api/chat/conversa"}
    if builder == "frota_historico":
        return {"reply": "Para consultar o historico da frota, informe o numero do caminhao ou o id do veiculo.\n\nFontes: server.py, /api/frota_historico/<veiculo_id>, /api/dashboard_frota"}
    if builder == "carga_detalhes":
        return {"reply": "Para consultar detalhes da carga, informe o id da carga ou do frete.\n\nFontes: server.py, /api/cargas/<carga_id>/detalhes"}
    return None


def _scalar_preview(value: object) -> str:
    if isinstance(value, bool):
        return "sim" if value else "nao"
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return _as_str(value)


def _record_preview(row: dict, fields: list[str]) -> str:
    parts: list[str] = []
    for field in fields:
        value = row.get(field)
        text = _scalar_preview(value)
        if text:
            parts.append(f"{field}={text}")
    if not parts and row:
        for key in list(row.keys())[:4]:
            text = _scalar_preview(row.get(key))
            if text:
                parts.append(f"{key}={text}")
    return ", ".join(parts)


def _summarize_frequency_field(field: str, rows: list[dict], heading: str, limit: int = 3) -> str | None:
    counts: Counter[str] = Counter()
    for row in rows:
        value = row.get(field)
        if isinstance(value, bool):
            label = "sim" if value else "nao"
        else:
            label = _as_str(value)
        if label:
            counts[label] += 1
    if not counts:
        return None
    pieces = [f"{name} ({count})" for name, count in counts.most_common(limit)]
    return f"- {heading}: " + "; ".join(pieces)


def _numeric_values(rows: list[dict], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(field)
        if isinstance(value, bool) or value in (None, ""):
            continue
        try:
            values.append(float(str(value).strip()))
        except Exception:
            continue
    return values


def _summarize_numeric_field(field: str, rows: list[dict], heading: str) -> str | None:
    values = _numeric_values(rows, field)
    if not values:
        return None
    if field in {"km", "km_atual", "falta_manut_km", "falta_oleo_km"}:
        return f"- {heading}: minimo {min(values):.0f}, maximo {max(values):.0f}"
    total = sum(values)
    media = total / len(values)
    return f"- {heading}: total {total:.2f}, media {media:.2f}"


def _analytics_field_preferences(normalized: str) -> list[tuple[str, str]]:
    aliases = [
        ("status", "Distribuicao por status", ("status", "situação", "situacao")),
        ("frete_status", "Distribuicao por status de frete", ("frete status", "status do frete", "status")),
        ("posto", "Ranking por posto", ("posto", "postos", "abasteceu")),
        ("combustivel_tipo", "Distribuicao por combustivel", ("combustivel", "combustível", "diesel", "gasolina", "etanol")),
        ("rota", "Ranking por rota", ("rota", "rotas", "cidade", "cidades")),
        ("cliente", "Ranking por cliente", ("cliente", "clientes", "pdv")),
        ("vendedor", "Ranking por vendedor", ("vendedor", "vendedores")),
        ("motorista", "Ranking por motorista", ("motorista", "motoristas")),
        ("entregador", "Ranking por entregador", ("entregador", "entregadores")),
        ("veiculo_nome", "Ranking por veiculo", ("veiculo", "veículos", "veiculos", "caminhao", "caminhões", "caminhoes")),
        ("tipo", "Distribuicao por tipo", ("tipo", "tipos")),
        ("funcao", "Distribuicao por funcao", ("funcao", "função", "funcoes", "funções")),
        ("visita_periodicidade", "Distribuicao por periodicidade", ("periodicidade", "frequencia", "frequência")),
        ("dia_semana", "Distribuicao por dia da semana", ("dia da semana", "semana", "dia")),
        ("local", "Distribuicao por local", ("local", "locais")),
    ]
    preferred: list[tuple[str, str]] = []
    for field, heading, terms in aliases:
        if any(normalize(term) in normalized for term in terms):
            preferred.append((field, heading))
    return preferred


def _comparative_category_label(field: str) -> str:
    return {
        "status": "status",
        "frete_status": "status de frete",
        "posto": "posto",
        "combustivel_tipo": "combustivel",
        "rota": "rota",
        "vendedor": "vendedor",
        "cliente": "cliente",
        "motorista": "motorista",
        "entregador": "entregador",
        "veiculo_nome": "veiculo",
        "tipo": "tipo",
        "funcao": "funcao",
        "visita_periodicidade": "periodicidade",
        "dia_semana": "dia da semana",
        "local": "local",
    }.get(field, field)


def _parse_row_datetime(value: object) -> datetime.datetime | None:
    text = _as_str(value)
    if not text:
        return None
    patterns = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    )
    for pattern in patterns:
        try:
            return datetime.datetime.strptime(text, pattern)
        except Exception:
            continue
    return None


def _row_datetime_value(row: dict) -> datetime.datetime | None:
    for field in (
        "data_registro",
        "data_envio",
        "data_abastecimento",
        "data_lavagem",
        "criado_em",
        "atualizado_em",
        "data_faturamento",
        "data_saida",
        "data_chegada",
        "data_base",
    ):
        parsed = _parse_row_datetime(row.get(field))
        if parsed is not None:
            return parsed
    return None


PORTUGUESE_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def _parse_message_date(text: str, fallback_year: int | None = None) -> datetime.date | None:
    raw = _as_str(text)
    if not raw:
        return None
    patterns = (
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
    )
    for pattern in patterns:
        try:
            return datetime.datetime.strptime(raw, pattern).date()
        except Exception:
            continue
    short_match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})", raw)
    if short_match and fallback_year is not None:
        day = int(short_match.group(1))
        month = int(short_match.group(2))
        try:
            return datetime.date(fallback_year, month, day)
        except Exception:
            return None
    return None


def _month_bounds(year: int, month: int) -> tuple[datetime.date, datetime.date]:
    start = datetime.date(year, month, 1)
    end = datetime.date(year + 1, 1, 1) if month == 12 else datetime.date(year, month + 1, 1)
    return start, end


def _month_number_from_name(text: str) -> int | None:
    return PORTUGUESE_MONTHS.get(_as_str(text).lower())


def _month_number_from_alias(text: str) -> int | None:
    key = normalize(_as_str(text))
    aliases = {
        "jan": 1,
        "janeiro": 1,
        "fev": 2,
        "fevereiro": 2,
        "mar": 3,
        "marco": 3,
        "abr": 4,
        "abril": 4,
        "mai": 5,
        "maio": 5,
        "jun": 6,
        "junho": 6,
        "jul": 7,
        "julho": 7,
        "ago": 8,
        "agosto": 8,
        "set": 9,
        "setembro": 9,
        "out": 10,
        "outubro": 10,
        "nov": 11,
        "novembro": 11,
        "dez": 12,
        "dezembro": 12,
    }
    return aliases.get(key)


def _sales_month_request(normalized: str) -> dict | None:
    today = datetime.date.today()
    month_pattern = r"(jan(?:eiro)?|fev(?:ereiro)?|mar(?:co)?|abr(?:il)?|mai(?:o)?|jun(?:ho)?|jul(?:ho)?|ago(?:sto)?|set(?:embro)?|out(?:ubro)?|nov(?:embro)?|dez(?:embro)?)"
    month_year = re.search(rf"\b{month_pattern}\s+de\s+(\d{{4}})\b", normalized)
    if month_year:
        return {
            "month": _month_number_from_alias(month_year.group(1)),
            "year": _as_int(month_year.group(2), 0),
            "label": f"{month_year.group(1)} de {month_year.group(2)}",
        }

    month_only = re.search(rf"\b{month_pattern}\b", normalized)
    if month_only:
        return {
            "month": _month_number_from_alias(month_only.group(1)),
            "year": None,
            "label": month_only.group(1),
        }

    if any(term in normalized for term in ("mes passado", "mes anterior", "ultimo mes", "mes retrasado")):
        if "retrasado" in normalized:
            ref = today.replace(day=1) - datetime.timedelta(days=1)
            ref = ref.replace(day=1) - datetime.timedelta(days=1)
        else:
            ref = today.replace(day=1) - datetime.timedelta(days=1)
        return {
            "month": ref.month,
            "year": ref.year,
            "label": "mes passado" if "retrasado" not in normalized else "mes retrasado",
        }
    if any(term in normalized for term in ("este mes", "esse mes", "mes atual")):
        return {
            "month": today.month,
            "year": today.year,
            "label": "este mes",
        }
    return None


def _previous_month_bounds(today: datetime.date) -> tuple[datetime.date, datetime.date]:
    if today.month == 1:
        return _month_bounds(today.year - 1, 12)
    return _month_bounds(today.year, today.month - 1)


def _semester_bounds(year: int, semester: int) -> tuple[datetime.date, datetime.date]:
    if semester == 1:
        return datetime.date(year, 1, 1), datetime.date(year, 7, 1)
    return datetime.date(year, 7, 1), datetime.date(year + 1, 1, 1)


def _business_day_window(today: datetime.date, days: int) -> tuple[datetime.date, datetime.date]:
    days = max(1, days)
    selected: list[datetime.date] = []
    cursor = today
    while len(selected) < days:
        if cursor.weekday() < 5:
            selected.append(cursor)
        cursor -= datetime.timedelta(days=1)
    start = min(selected)
    end = max(selected) + datetime.timedelta(days=1)
    return start, end


def _last_quarter_bounds(today: datetime.date) -> tuple[datetime.date, datetime.date]:
    current_quarter = ((today.month - 1) // 3) + 1
    if current_quarter == 1:
        year = today.year - 1
        quarter = 4
    else:
        year = today.year
        quarter = current_quarter - 1
    start_month = ((quarter - 1) * 3) + 1
    start = datetime.date(year, start_month, 1)
    end = datetime.date(year + 1, 1, 1) if start_month == 10 else datetime.date(year, start_month + 3, 1)
    return start, end


def _message_time_request(normalized: str) -> dict | None:
    today = datetime.date.today()
    semester = re.search(r"\b(primeiro|segundo)\s+semestre(?:\s+de\s+(\d{4}))?\b", normalized)
    if semester:
        semester_number = 1 if semester.group(1) == "primeiro" else 2
        year = _as_int(semester.group(2), today.year)
        start, end = _semester_bounds(year, semester_number)
        return {
            "mode": "range",
            "label": f"{semester.group(1)} semestre de {year}",
            "start": start,
            "end": end,
        }

    rolling_compare = re.search(
        r"\bultimos?\s+(\d+)\s+dias?(?:\s+corridos)?\s+(?:vs|versus|comparado com)\s+(?:(\d+)\s+dias?\s+)?anteriores\b",
        normalized,
    )
    if rolling_compare:
        days_a = max(1, int(rolling_compare.group(1)))
        days_b = max(1, int(rolling_compare.group(2) or rolling_compare.group(1)))
        start_a = today - datetime.timedelta(days=days_a - 1)
        end_a = today + datetime.timedelta(days=1)
        end_b = start_a
        start_b = end_b - datetime.timedelta(days=days_b)
        return {
            "mode": "compare",
            "label_a": f"ultimos {days_a} dias",
            "label_b": f"{days_b} dias anteriores",
            "start_a": start_a,
            "end_a": end_a,
            "start_b": start_b,
            "end_b": end_b,
        }
    rolling_previous = re.search(r"\bultimos?\s+(\d+)\s+dias?(?:\s+corridos)?\b.*\bperiodo anterior\b", normalized)
    if rolling_previous:
        days = max(1, int(rolling_previous.group(1)))
        start_a = today - datetime.timedelta(days=days - 1)
        end_a = today + datetime.timedelta(days=1)
        end_b = start_a
        start_b = end_b - datetime.timedelta(days=days)
        return {
            "mode": "compare",
            "label_a": f"ultimos {days} dias",
            "label_b": "periodo anterior",
            "start_a": start_a,
            "end_a": end_a,
            "start_b": start_b,
            "end_b": end_b,
        }

    if "mesmo periodo do ano passado" in normalized:
        if "este ano" in normalized:
            start_a = datetime.date(today.year, 1, 1)
            end_a = today + datetime.timedelta(days=1)
            start_b = datetime.date(today.year - 1, 1, 1)
            end_b = start_b + (end_a - start_a)
            return {
                "mode": "compare",
                "label_a": "este ano",
                "label_b": "mesmo periodo do ano passado",
                "start_a": start_a,
                "end_a": end_a,
                "start_b": start_b,
                "end_b": end_b,
            }
        start_a = today.replace(day=1)
        end_a = today + datetime.timedelta(days=1)
        start_b = datetime.date(today.year - 1, today.month, 1)
        end_b = start_b + (end_a - start_a)
        return {
            "mode": "compare",
            "label_a": "este mes",
            "label_b": "mesmo periodo do ano passado",
            "start_a": start_a,
            "end_a": end_a,
            "start_b": start_b,
            "end_b": end_b,
        }

    month_phase = re.search(
        r"\b(inicio|comeco|fim)\s+(?:de|do|da)\s+([a-z]+)(?:\s+de\s+(\d{4}))?\b",
        normalized,
    )
    if month_phase:
        phase = month_phase.group(1)
        month = _month_number_from_name(month_phase.group(2))
        year = _as_int(month_phase.group(3), today.year)
        if month is not None:
            month_start, month_end = _month_bounds(year, month)
            if phase in ("inicio", "comeco"):
                start = month_start
                end = min(month_end, month_start + datetime.timedelta(days=10))
                label = f"inicio de {month_phase.group(2)}/{year}"
            else:
                end = month_end
                start = max(month_start, month_end - datetime.timedelta(days=10))
                label = f"fim de {month_phase.group(2)}/{year}"
            return {
                "mode": "range",
                "label": label,
                "start": start,
                "end": end,
            }

    if "fim do mes passado" in normalized or "final do mes passado" in normalized:
        month_start, month_end = _previous_month_bounds(today)
        return {
            "mode": "range",
            "label": "fim do mes passado",
            "start": max(month_start, month_end - datetime.timedelta(days=10)),
            "end": month_end,
        }

    business_days = re.search(r"\bultimos?\s+(\d+)\s+dias?\s+uteis\b", normalized)
    if business_days:
        days = max(1, int(business_days.group(1)))
        start, end = _business_day_window(today, days)
        return {
            "mode": "range",
            "label": f"ultimos {days} dias uteis",
            "start": start,
            "end": end,
            "weekdays_only": True,
        }

    natural_range = re.search(
        r"\b(?:de|entre)\s+(\d{1,2})\s+(?:a|ate|e)\s+(\d{1,2})\s+de\s+([a-z]+)(?:\s+de\s+(\d{4}))?\b",
        normalized,
    )
    if natural_range:
        day_a = int(natural_range.group(1))
        day_b = int(natural_range.group(2))
        month = _month_number_from_name(natural_range.group(3))
        year = _as_int(natural_range.group(4), today.year)
        if month is not None:
            try:
                start = datetime.date(year, month, day_a)
                end = datetime.date(year, month, day_b)
            except Exception:
                start = None
                end = None
            if start is not None and end is not None:
                if end < start:
                    start, end = end, start
                return {
                    "mode": "range",
                    "label": f"de {start.strftime('%d/%m/%Y')} a {end.strftime('%d/%m/%Y')}",
                    "start": start,
                    "end": end + datetime.timedelta(days=1),
                }

    fortnight = re.search(
        r"\b(primeira|segunda)\s+quinzena\s+de\s+([a-z]+)(?:\s+de\s+(\d{4}))?\b",
        normalized,
    )
    if fortnight:
        half = fortnight.group(1)
        month = _month_number_from_name(fortnight.group(2))
        year = _as_int(fortnight.group(3), today.year)
        if month is not None:
            month_start, month_end = _month_bounds(year, month)
            if half == "primeira":
                start = month_start
                end = min(month_end, month_start + datetime.timedelta(days=15))
            else:
                start = month_start + datetime.timedelta(days=15)
                end = month_end
            return {
                "mode": "range",
                "label": f"{half} quinzena de {fortnight.group(2)}/{year}",
                "start": start,
                "end": end,
            }

    explicit_range = re.search(
        r"\b(?:de|entre)\s+(\d{1,2}[/-]\d{1,2}(?:[/-]\d{4})?|\d{4}-\d{2}-\d{2})\s+(?:a|ate|e)\s+(\d{1,2}[/-]\d{1,2}(?:[/-]\d{4})?|\d{4}-\d{2}-\d{2})\b",
        normalized,
    )
    if explicit_range:
        start = _parse_message_date(explicit_range.group(1), fallback_year=today.year)
        end = _parse_message_date(explicit_range.group(2), fallback_year=today.year)
        if start is not None and end is not None:
            if end < start:
                start, end = end, start
            return {
                "mode": "range",
                "label": f"de {start.strftime('%d/%m/%Y')} a {end.strftime('%d/%m/%Y')}",
                "start": start,
                "end": end + datetime.timedelta(days=1),
            }
    if "hoje" in normalized and "ontem" in normalized:
        yesterday = today - datetime.timedelta(days=1)
        return {
            "mode": "compare",
            "label_a": "hoje",
            "label_b": "ontem",
            "start_a": today,
            "end_a": today + datetime.timedelta(days=1),
            "start_b": yesterday,
            "end_b": today,
        }
    if "ano passado" in normalized and "este ano" in normalized:
        start_a = datetime.date(today.year, 1, 1)
        end_a = datetime.date(today.year + 1, 1, 1)
        start_b = datetime.date(today.year - 1, 1, 1)
        end_b = start_a
        return {
            "mode": "compare",
            "label_a": "este ano",
            "label_b": "ano passado",
            "start_a": start_a,
            "end_a": end_a,
            "start_b": start_b,
            "end_b": end_b,
        }
    if any(term in normalized for term in ("este mes", "esse mes", "mes atual")) and "mes passado" in normalized:
        start_a = today.replace(day=1)
        end_a = (start_a + datetime.timedelta(days=32)).replace(day=1)
        start_b = (start_a - datetime.timedelta(days=1)).replace(day=1)
        end_b = start_a
        return {
            "mode": "compare",
            "label_a": "este mes",
            "label_b": "mes passado",
            "start_a": start_a,
            "end_a": end_a,
            "start_b": start_b,
            "end_b": end_b,
        }
    if "semana retrasada" in normalized:
        start_current_week = today - datetime.timedelta(days=today.weekday())
        start_two_weeks_ago = start_current_week - datetime.timedelta(days=14)
        start_last_week = start_current_week - datetime.timedelta(days=7)
        return {
            "mode": "range",
            "label": "semana retrasada",
            "start": start_two_weeks_ago,
            "end": start_last_week,
        }
    if "semana passada" in normalized:
        start_current_week = today - datetime.timedelta(days=today.weekday())
        start_last_week = start_current_week - datetime.timedelta(days=7)
        return {
            "mode": "range",
            "label": "semana passada",
            "start": start_last_week,
            "end": start_current_week,
        }
    if "trimestre passado" in normalized:
        start, end = _last_quarter_bounds(today)
        return {
            "mode": "range",
            "label": "trimestre passado",
            "start": start,
            "end": end,
        }
    if any(term in normalized for term in ("ultimo trimestre", "ultimos 3 meses", "ultimos tres meses")):
        start = today - datetime.timedelta(days=89)
        return {
            "mode": "range",
            "label": "ultimo trimestre",
            "start": start,
            "end": today + datetime.timedelta(days=1),
        }
    match = re.search(r"\bultimos?\s+(\d+)\s+dias?\b", normalized)
    if match:
        days = max(1, int(match.group(1)))
        start = today - datetime.timedelta(days=days - 1)
        return {
            "mode": "range",
            "label": f"ultimos {days} dias",
            "start": start,
            "end": today + datetime.timedelta(days=1),
        }
    return None


def _rows_for_period(rows: list[dict], start: datetime.date, end: datetime.date, weekdays_only: bool = False) -> list[dict]:
    selected: list[dict] = []
    for row in rows:
        dt = _row_datetime_value(row)
        if dt is None:
            continue
        day = dt.date()
        if weekdays_only and day.weekday() >= 5:
            continue
        if start <= day < end:
            selected.append(row)
    return selected


def _top_category_for_rows(rows: list[dict], normalized: str) -> tuple[str, str, int] | None:
    candidates = _analytics_field_preferences(normalized) + [
        ("posto", "posto"),
        ("rota", "rota"),
        ("vendedor", "vendedor"),
        ("cliente", "cliente"),
        ("veiculo_nome", "veiculo"),
        ("motorista", "motorista"),
        ("entregador", "entregador"),
        ("status", "status"),
        ("combustivel_tipo", "combustivel"),
        ("tipo_movimento", "tipo de movimento"),
        ("origem_setor", "origem"),
        ("destino_setor", "destino"),
    ]
    seen: set[str] = set()
    for field, _heading in candidates:
        if field in seen:
            continue
        seen.add(field)
        counts: Counter[str] = Counter()
        for row in rows:
            value = _as_str(row.get(field))
            if value:
                counts[value] += 1
        if counts:
            name, count = counts.most_common(1)[0]
            return field, _comparative_category_label(field), count
    return None


def _movement_signed_quantity(row: dict) -> float:
    raw_type = _as_str(row.get("tipo_movimento")) or _as_str(row.get("tipo"))
    movement_type = normalize(raw_type)
    quantity = _as_float(row.get("quantidade"), 0.0)
    magnitude = abs(quantity)
    if any(term in movement_type for term in ("saida", "baixa", "consumo", "perda", "ajuste negativo")):
        return -magnitude
    if any(term in movement_type for term in ("entrada", "retorno", "ajuste positivo")):
        return magnitude
    return quantity


def _devolucao_metric_value(row: dict) -> float:
    structured_total = sum(_as_float(row.get(key), 0.0) for key in DEVOLUCAO_ITEMS)
    if structured_total > 0:
        return structured_total
    loose_total = (
        _as_float(row.get("dev_gf"), 0.0)
        + _as_float(row.get("dev_pet"), 0.0)
        + _as_float(row.get("quantidade"), 0.0)
    )
    return loose_total if loose_total > 0 else 1.0


def _aggregate_group_metric(rows: list[dict], field: str, metric_getter) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        key = _as_str(row.get(field))
        if not key:
            continue
        totals[key] = totals.get(key, 0.0) + float(metric_getter(row))
    return totals


def _business_group_candidates(normalized: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    if any(term in normalized for term in ("produto", "produtos", "item", "itens")):
        candidates.extend([("nome_produto", "produto")])
    if any(term in normalized for term in ("cliente", "clientes", "pdv")):
        candidates.extend([("cliente", "cliente"), ("nome_cliente", "cliente")])
    if "rota" in normalized:
        candidates.append(("rota", "rota"))
    if any(term in normalized for term in ("frete", "carga")):
        candidates.extend([("frete_nome", "frete"), ("carga_nome", "carga")])
    if "entregador" in normalized:
        candidates.append(("entregador", "entregador"))
    if "conferente" in normalized:
        candidates.append(("conferente_nome", "conferente"))
    if any(term in normalized for term in ("veiculo", "veiculos", "caminhao", "caminhoes")):
        candidates.append(("veiculo_nome", "veiculo"))
    candidates.extend(
        [
            ("nome_produto", "produto"),
            ("cliente", "cliente"),
            ("nome_cliente", "cliente"),
            ("rota", "rota"),
            ("frete_nome", "frete"),
            ("carga_nome", "carga"),
            ("entregador", "entregador"),
            ("conferente_nome", "conferente"),
            ("veiculo_nome", "veiculo"),
        ]
    )
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for field, label in candidates:
        if field in seen:
            continue
        seen.add(field)
        unique.append((field, label))
    return unique


def _summarize_semantic_business_analysis(label: str, rows: list[dict], normalized: str) -> str | None:
    request = _message_time_request(normalized)
    wants_drop = any(term in normalized for term in ("caiu", "queda", "recu", "diminuiu", "despencou"))
    wants_worse = any(term in normalized for term in ("piorou", "pior", "perdeu"))
    wants_more = bool(re.search(r"\b(mais|maior|top)\b", normalized))

    if request and request["mode"] == "compare":
        dated_rows = [row for row in rows if _row_datetime_value(row) is not None]
        if not dated_rows:
            return None
        rows_a = _rows_for_period(
            dated_rows,
            request["start_a"],
            request["end_a"],
            weekdays_only=bool(request.get("weekdays_only")),
        )
        rows_b = _rows_for_period(
            dated_rows,
            request["start_b"],
            request["end_b"],
            weekdays_only=bool(request.get("weekdays_only")),
        )

        if ("produto" in normalized or "item" in normalized) and (wants_drop or wants_worse):
            current = _aggregate_group_metric(rows_a, "nome_produto", _movement_signed_quantity)
            previous = _aggregate_group_metric(rows_b, "nome_produto", _movement_signed_quantity)
            products = set(current) | set(previous)
            if not products:
                return None
            ranked = sorted(
                ((name, current.get(name, 0.0) - previous.get(name, 0.0), current.get(name, 0.0), previous.get(name, 0.0)) for name in products),
                key=lambda item: item[1],
            )
            name, delta, current_value, previous_value = ranked[0]
            if delta >= 0:
                return (
                    f"Nao encontrei produto com queda em {label} entre {request['label_a']} e {request['label_b']}. "
                    f"O menor delta foi {name} com {delta:+.2f}."
                )
            return (
                f"O produto que mais caiu em {label} foi {name}: "
                f"{request['label_a']} = {current_value:.2f}; {request['label_b']} = {previous_value:.2f}; "
                f"variacao = {delta:+.2f}."
            )

        if "rota" in normalized and (wants_drop or wants_worse):
            current = _aggregate_group_metric(rows_a, "rota", lambda row: 1.0)
            previous = _aggregate_group_metric(rows_b, "rota", lambda row: 1.0)
            routes = set(current) | set(previous)
            if not routes:
                return None
            ranked = sorted(
                ((name, current.get(name, 0.0) - previous.get(name, 0.0), current.get(name, 0.0), previous.get(name, 0.0)) for name in routes),
                key=lambda item: item[1],
            )
            name, delta, current_value, previous_value = ranked[0]
            if delta >= 0:
                return (
                    f"Nao encontrei rota que piorou em {label} entre {request['label_a']} e {request['label_b']}. "
                    f"O menor delta foi {name} com {delta:+.0f}."
                )
            return (
                f"A rota que mais piorou em {label} foi {name}: "
                f"{request['label_a']} = {current_value:.0f}; {request['label_b']} = {previous_value:.0f}; "
                f"variacao = {delta:+.0f}."
            )

    if "devolu" in normalized and wants_more:
        selected_rows = rows
        if request:
            dated_rows = [row for row in rows if _row_datetime_value(row) is not None]
            if dated_rows:
                if request["mode"] == "compare":
                    selected_rows = _rows_for_period(
                        dated_rows,
                        request["start_a"],
                        request["end_a"],
                        weekdays_only=bool(request.get("weekdays_only")),
                    )
                else:
                    selected_rows = _rows_for_period(
                        dated_rows,
                        request["start"],
                        request["end"],
                        weekdays_only=bool(request.get("weekdays_only")),
                    )
        for field, label_name in _business_group_candidates(normalized):
            totals = _aggregate_group_metric(selected_rows, field, _devolucao_metric_value)
            if not totals:
                continue
            name, total = max(totals.items(), key=lambda item: item[1])
            period_label = request["label_a"] if request and request["mode"] == "compare" else request["label"] if request else "no conjunto atual"
            return f"O {label_name} com mais devolucao em {period_label} foi {name}, com {total:.2f} item(ns)."

    return None


def _summarize_api_list_time_window(label: str, rows: list[dict], normalized: str) -> str | None:
    request = _message_time_request(normalized)
    if not request:
        return None
    dated_rows = [row for row in rows if _row_datetime_value(row) is not None]
    if not dated_rows:
        return None

    if request["mode"] == "compare":
        rows_a = _rows_for_period(
            dated_rows,
            request["start_a"],
            request["end_a"],
            weekdays_only=bool(request.get("weekdays_only")),
        )
        rows_b = _rows_for_period(
            dated_rows,
            request["start_b"],
            request["end_b"],
            weekdays_only=bool(request.get("weekdays_only")),
        )
        delta = len(rows_a) - len(rows_b)
        reply = (
            f"Comparativo temporal de {label}: {request['label_a']} = {len(rows_a)} registro(s); "
            f"{request['label_b']} = {len(rows_b)} registro(s); variacao = {delta:+d}."
        )
        top = _top_category_for_rows(rows_a, normalized)
        if top:
            _field, entity, count = top
            name = Counter(_as_str(row.get(_field)) for row in rows_a if _as_str(row.get(_field))).most_common(1)[0][0]
            reply += f" Destaque em {request['label_a']}: {entity} {name} ({count})."
        return reply

    rows_range = _rows_for_period(
        dated_rows,
        request["start"],
        request["end"],
        weekdays_only=bool(request.get("weekdays_only")),
    )
    reply = f"Encontrei {len(rows_range)} registro(s) em {label} nos {request['label']}."
    top = _top_category_for_rows(rows_range, normalized)
    if top:
        field, entity, count = top
        name = Counter(_as_str(row.get(field)) for row in rows_range if _as_str(row.get(field))).most_common(1)[0][0]
        reply += f" Maior concentracao por {entity}: {name} ({count})."
    return reply


def _summarize_api_list_comparison(label: str, rows: list[dict], normalized: str) -> str | None:
    wants_more = bool(re.search(r"\b(mais|maior|maiores|top)\b", normalized))
    wants_less = bool(re.search(r"\b(menos|menor|menores)\b", normalized))
    if not wants_more and not wants_less:
        return None

    candidates = _analytics_field_preferences(normalized) + [
        ("posto", "Ranking por posto"),
        ("rota", "Ranking por rota"),
        ("vendedor", "Ranking por vendedor"),
        ("cliente", "Ranking por cliente"),
        ("veiculo_nome", "Ranking por veiculo"),
        ("motorista", "Ranking por motorista"),
        ("entregador", "Ranking por entregador"),
        ("status", "Distribuicao por status"),
        ("combustivel_tipo", "Distribuicao por combustivel"),
    ]
    seen: set[str] = set()
    for field, _heading in candidates:
        if field in seen:
            continue
        seen.add(field)
        counts: Counter[str] = Counter()
        for row in rows:
            value = _as_str(row.get(field))
            if value:
                counts[value] += 1
        if not counts:
            continue
        ordered = counts.most_common()
        chosen_name, chosen_count = ordered[-1] if wants_less else ordered[0]
        entity = _comparative_category_label(field)
        direction = "menos" if wants_less else "mais"
        return f"O {entity} com {direction} ocorrencias em {label} e {chosen_name}, com {chosen_count} registro(s)."
    return None


def _summarize_api_list_analytics(label: str, rows: list[dict], normalized: str) -> list[str]:
    semantic = _summarize_semantic_business_analysis(label, rows, normalized)
    if semantic:
        return [semantic]

    time_window = _summarize_api_list_time_window(label, rows, normalized)
    if time_window:
        return [time_window]

    comparison = _summarize_api_list_comparison(label, rows, normalized)
    if comparison:
        return [comparison]

    lines = [f"Resumo estatistico de {label}:"]
    lines.append(f"- total de registros: {len(rows)}")

    preferences = _analytics_field_preferences(normalized)
    fallback_fields = [
        ("status", "Distribuicao por status"),
        ("frete_status", "Distribuicao por status de frete"),
        ("posto", "Ranking por posto"),
        ("combustivel_tipo", "Distribuicao por combustivel"),
        ("rota", "Ranking por rota"),
        ("vendedor", "Ranking por vendedor"),
        ("cliente", "Ranking por cliente"),
        ("motorista", "Ranking por motorista"),
        ("entregador", "Ranking por entregador"),
        ("veiculo_nome", "Ranking por veiculo"),
        ("tipo", "Distribuicao por tipo"),
        ("funcao", "Distribuicao por funcao"),
        ("visita_periodicidade", "Distribuicao por periodicidade"),
        ("dia_semana", "Distribuicao por dia da semana"),
        ("local", "Distribuicao por local"),
    ]

    seen_fields: set[str] = set()
    categorical_added = 0
    for field, heading in preferences + fallback_fields:
        if field in seen_fields:
            continue
        seen_fields.add(field)
        summary = _summarize_frequency_field(field, rows, heading)
        if summary:
            lines.append(summary)
            categorical_added += 1
        if categorical_added >= 2:
            break

    numeric_fields = [
        ("valor", "Valor"),
        ("quantidade", "Quantidade"),
        ("total_comissao", "Comissao"),
        ("total_itens", "Itens"),
        ("km", "KM"),
    ]
    numeric_added = 0
    for field, heading in numeric_fields:
        summary = _summarize_numeric_field(field, rows, heading)
        if summary:
            lines.append(summary)
            numeric_added += 1
        if numeric_added >= 2:
            break

    if len(lines) == 2:
        previews = []
        for row in rows[:3]:
            preview = _record_preview(row, list(rows[0].keys())[:4])
            if preview:
                previews.append(preview)
        if previews:
            lines.append("- amostra: " + " | ".join(previews))
    return lines


def _summarize_api_dict(label: str, payload: dict, fields: list[str]) -> str:
    lines = [f"Resumo de {label}:"]
    added = 0
    for field in fields:
        value = payload.get(field)
        if isinstance(value, list):
            lines.append(f"- {field}: {len(value)} item(ns)")
            added += 1
        elif isinstance(value, dict):
            subkeys = ", ".join(list(value.keys())[:6])
            lines.append(f"- {field}: chaves {subkeys or 'sem detalhes'}")
            added += 1
        else:
            text = _scalar_preview(value)
            if text:
                lines.append(f"- {field}: {text}")
                added += 1
    if not added:
        keys = ", ".join(list(payload.keys())[:10])
        lines.append(f"- chaves disponiveis: {keys or 'nenhuma'}")
    return "\n".join(lines)


def _summarize_api_list(label: str, rows: list[object], fields: list[str], normalized: str) -> str:
    total = len(rows)
    if total == 0:
        return f"Nao encontrei registros em {label}."

    lines = [f"Encontrei {total} registro(s) em {label}."]
    wants_count = _message_wants_count_or_summary(normalized)
    wants_analytics = _message_wants_analytics(normalized) or (_message_time_request(normalized) is not None)
    wants_list = _message_wants_listing(normalized) or (not wants_count and not wants_analytics)

    dict_rows = [row for row in rows if isinstance(row, dict)]
    if wants_analytics and dict_rows:
        lines = _summarize_api_list_analytics(label, dict_rows, normalized)
    if wants_list and dict_rows:
        previews = []
        for row in dict_rows[:5]:
            preview = _record_preview(row, fields)
            if preview:
                previews.append(preview)
        if previews:
            lines.append("Exemplos recentes:")
            lines.extend(f"- {item}" for item in previews)
    return "\n".join(lines)


def _summarize_status_api(payload: dict) -> str:
    lines = ["Status geral do sistema:"]
    lines.append(f"- API: {'ok' if payload.get('api') else 'falha'}")
    lines.append(f"- Banco: {'ok' if payload.get('database') else 'falha'}")
    esxi = payload.get("esxi") or {}
    if isinstance(esxi, dict):
        host = _as_str(esxi.get("host")) or "-"
        lines.append(f"- ESXi: {'online' if esxi.get('online') else 'offline'} ({host})")
    cameras = payload.get("cameras") or []
    if isinstance(cameras, list) and cameras:
        online = sum(1 for item in cameras if isinstance(item, dict) and item.get("online"))
        lines.append(f"- Cameras: {online}/{len(cameras)} online")
    monitor_apps = payload.get("monitor_apps") or {}
    if isinstance(monitor_apps, dict) and monitor_apps:
        ativos = sum(1 for item in monitor_apps.values() if isinstance(item, dict) and item.get("running"))
        lines.append(f"- Apps de monitor: {ativos}/{len(monitor_apps)} ativas")
    sip = payload.get("sip") or {}
    if isinstance(sip, dict):
        if "habilitado" in sip:
            lines.append(f"- SIP: {'habilitado' if sip.get('habilitado') else 'desabilitado'}")
        elif sip:
            lines.append(f"- SIP: chaves {', '.join(list(sip.keys())[:4])}")
    nfe = payload.get("nfe") or {}
    if isinstance(nfe, dict):
        if "habilitado" in nfe:
            lines.append(f"- NF-e: {'habilitado' if nfe.get('habilitado') else 'desabilitado'}")
        elif nfe:
            lines.append(f"- NF-e: chaves {', '.join(list(nfe.keys())[:4])}")
    usuario = payload.get("usuario_logado") or {}
    if isinstance(usuario, dict) and (_as_str(usuario.get("nome")) or _as_str(usuario.get("login"))):
        lines.append(f"- Usuario logado: {_as_str(usuario.get('nome')) or _as_str(usuario.get('login'))}")
    return "\n".join(lines)


def _summarize_logged_user(payload: dict) -> str:
    usuario = payload.get("usuario") if isinstance(payload, dict) else None
    if not isinstance(usuario, dict):
        return "Nao encontrei um usuario logado nesta sessao."
    nome = _as_str(usuario.get("nome")) or "-"
    login = _as_str(usuario.get("login")) or "-"
    codigo = _scalar_preview(usuario.get("id")) or "-"
    return (
        "Usuario logado atual:\n"
        f"- id: {codigo}\n"
        f"- nome: {nome}\n"
        f"- login: {login}"
    )


def _summarize_dashboard_frota(rows: list[object], normalized: str) -> str:
    dict_rows = [row for row in rows if isinstance(row, dict)]
    if not dict_rows:
        return "Nao encontrei dados no dashboard da frota."
    alertas = [row for row in dict_rows if row.get("alerta")]
    lines = [
        f"Encontrei {len(dict_rows)} veiculo(s) no dashboard da frota.",
        f"Com alerta agora: {len(alertas)}.",
    ]
    wants_list = _message_wants_listing(normalized) or "dashboard" in normalized or "painel" in normalized
    if wants_list:
        preview_rows = alertas[:5] if alertas else dict_rows[:5]
        lines.append("Resumo:")
        for row in preview_rows:
            nome = _as_str(row.get("veiculo_nome")) or f"Veiculo #{_as_int(row.get('veiculo_id'), 0)}"
            placa = _as_str(row.get("placa"))
            status = _as_str(row.get("frete_status")) or "sem frete"
            falta_manut = _as_int(row.get("falta_manut_km"), 0)
            falta_oleo = _as_int(row.get("falta_oleo_km"), 0)
            label = f"{nome} ({placa})" if placa else nome
            lines.append(f"- {label}: frete {status}, falta manut {falta_manut} km, falta oleo {falta_oleo} km")
    return "\n".join(lines)


def _summarize_chat_conversa(rows: list[object]) -> str:
    dict_rows = [row for row in rows if isinstance(row, dict)]
    if not dict_rows:
        return "Nao encontrei mensagens nessa conversa."
    contato = None
    for row in dict_rows:
        contato = _as_str(row.get("remetente_nome")) or _as_str(row.get("destinatario_nome"))
        if contato:
            break
    lines = [f"Encontrei {len(dict_rows)} mensagem(ns) na conversa" + (f" com {contato}." if contato else ".")]
    lines.append("Mensagens recentes:")
    for row in dict_rows[-5:]:
        remetente = _as_str(row.get("remetente_nome")) or "Usuario"
        mensagem = _as_str(row.get("mensagem")) or "(sem texto)"
        data_envio = _as_str(row.get("data_envio"))
        prefix = f"{remetente}"
        if data_envio:
            prefix += f" em {data_envio}"
        lines.append(f"- {prefix}: {mensagem}")
    return "\n".join(lines)


def _summarize_chat_conversa_temporal(rows: list[object], normalized: str) -> str | None:
    dict_rows = [row for row in rows if isinstance(row, dict)]
    request = _message_time_request(normalized)
    if not dict_rows or not request:
        return None
    dated_rows = [row for row in dict_rows if _row_datetime_value(row) is not None]
    if not dated_rows:
        return None
    if request["mode"] == "compare":
        rows_a = _rows_for_period(dated_rows, request["start_a"], request["end_a"])
        rows_b = _rows_for_period(dated_rows, request["start_b"], request["end_b"])
        return (
            f"Comparativo temporal da conversa: {request['label_a']} = {len(rows_a)} mensagem(ns); "
            f"{request['label_b']} = {len(rows_b)} mensagem(ns); variacao = {len(rows_a) - len(rows_b):+d}."
        )
    rows_range = _rows_for_period(dated_rows, request["start"], request["end"])
    return f"Encontrei {len(rows_range)} mensagem(ns) na conversa nos {request['label']}."


def _summarize_chat_unread(payload: dict) -> str:
    total = _as_int(payload.get("total_mensagens_nao_lidas") or payload.get("total"), 0)
    conversas = _as_int(payload.get("total_conversas_com_nao_lidas"), 0)
    por_contato = payload.get("por_contato") if isinstance(payload.get("por_contato"), list) else []
    top = None
    if por_contato:
        top = max(
            [row for row in por_contato if isinstance(row, dict)],
            key=lambda row: _as_int(row.get("total"), 0),
            default=None,
        )
    lines = [
        "Resumo de mensagens nao lidas do chat:",
        f"- total de mensagens nao lidas: {total}",
        f"- conversas com nao lidas: {conversas}",
    ]
    if isinstance(top, dict):
        lines.append(
            f"- contato com mais nao lidas: {_as_str(top.get('remetente_nome')) or 'usuario ' + str(_as_int(top.get('remetente_id'), 0))} "
            f"com {_as_int(top.get('total'), 0)} mensagem(ns)"
        )
    return "\n".join(lines)


def _summarize_carga_detalhes(payload: dict) -> str:
    carga = payload.get("carga") if isinstance(payload, dict) else {}
    resumo = payload.get("resumo") if isinstance(payload, dict) else {}
    estoque = payload.get("estoque") if isinstance(payload, dict) else {}
    frete = payload.get("frete") if isinstance(payload, dict) else {}
    if not isinstance(carga, dict):
        return "Nao encontrei detalhes dessa carga."
    nome = _as_str(carga.get("nome")) or f"Carga #{_as_int(carga.get('id'), 0)}"
    rota = _as_str(carga.get("rota")) or _as_str(carga.get("cidade"))
    veiculo = _as_str(carga.get("veiculo_numero"))
    lines = [f"Detalhes de {nome}:"]
    if rota:
        lines.append(f"- rota/cidade: {rota}")
    if veiculo:
        lines.append(f"- caminhao: {veiculo}")
    if isinstance(frete, dict) and frete:
        status = _as_str(frete.get("status"))
        if status:
            lines.append(f"- status do frete: {status}")
    if isinstance(resumo, dict):
        lines.append(f"- linhas importadas: {_as_int(resumo.get('linhas'), 0)}")
        lines.append(f"- itens de estoque: {_as_int(resumo.get('itens_estoque'), 0)}")
    if isinstance(estoque, dict):
        lines.append(f"- estoque baixado: {'sim' if estoque.get('baixado') else 'nao'}")
    return "\n".join(lines)


def _summarize_frota_historico(payload: dict) -> str:
    veiculo = payload.get("veiculo") if isinstance(payload, dict) else {}
    resumo = payload.get("resumo") if isinstance(payload, dict) else {}
    frete = payload.get("frete_atual") if isinstance(payload, dict) else {}
    historico = payload.get("historico") if isinstance(payload, dict) else {}
    if not isinstance(veiculo, dict):
        return "Nao encontrei historico desse veiculo."
    nome = _as_str(veiculo.get("nome")) or f"Veiculo #{_as_int(veiculo.get('id'), 0)}"
    placa = _as_str(veiculo.get("placa"))
    label = f"{nome} ({placa})" if placa else nome
    lines = [f"Historico da frota para {label}:"]
    if isinstance(frete, dict) and _as_str(frete.get("status")):
        lines.append(f"- frete atual: {_as_str(frete.get('status'))} - {_as_str(frete.get('carga_nome')) or _as_str(frete.get('nome'))}")
    if isinstance(resumo, dict):
        lines.append(f"- KM atual: {_as_int(resumo.get('km_atual'), 0)}")
        lines.append(f"- falta manutencao: {_as_int(resumo.get('falta_manut_km'), 0)} km")
        lines.append(f"- falta oleo: {_as_int(resumo.get('falta_oleo_km'), 0)} km")
        lines.append(f"- manutencoes: {_as_int(resumo.get('manut_count'), 0)}")
        lines.append(f"- abastecimentos: {_as_int(resumo.get('abastecimentos_count'), 0)}")
    if isinstance(historico, dict):
        manutencoes = historico.get("manutencoes") or []
        trocas_oleo = historico.get("trocas_oleo") or []
        if manutencoes:
            ultima = manutencoes[0] if isinstance(manutencoes[0], dict) else {}
            lines.append(f"- ultima manutencao: {_as_str(ultima.get('tipo')) or '-'} em {_as_int(ultima.get('km'), 0)} km")
        if trocas_oleo:
            ultima = trocas_oleo[0] if isinstance(trocas_oleo[0], dict) else {}
            lines.append(f"- ultima troca de oleo: {_as_str(ultima.get('tipo')) or '-'} em {_as_int(ultima.get('km'), 0)} km")
    return "\n".join(lines)


def _fmt_money(value: object) -> str:
    return f"R$ {_as_float(value, 0.0):.2f}"


def _top_row_by(rows: list[object], field: str) -> dict | None:
    dict_rows = [row for row in rows if isinstance(row, dict)]
    if not dict_rows:
        return None
    return max(dict_rows, key=lambda row: _as_float(row.get(field), 0.0))


def _summarize_frota_resumo(rows: list[object], normalized: str) -> str:
    dict_rows = [row for row in rows if isinstance(row, dict)]
    if not dict_rows:
        return "Nao encontrei dados no resumo da frota."

    vencidos_manut = [row for row in dict_rows if _as_int(row.get("falta_manut_km"), 0) <= 0]
    vencidos_oleo = [row for row in dict_rows if _as_int(row.get("falta_oleo_km"), 0) <= 0]
    maior_km = _top_row_by(dict_rows, "km_atual") or {}
    maior_custo = _top_row_by(dict_rows, "custo_total") or {}

    if any(term in normalized for term in ("qual", "mais", "maior", "pior", "atrasad", "vencid")):
        if "manutenc" in normalized:
            pior = min(dict_rows, key=lambda row: _as_int(row.get("falta_manut_km"), 0))
            return (
                f"O veiculo com manutencao mais critica agora e {_as_str(pior.get('nome')) or '-'} "
                f"com falta de {_as_int(pior.get('falta_manut_km'), 0)} km para manutencao."
            )
        if "oleo" in normalized:
            pior = min(dict_rows, key=lambda row: _as_int(row.get("falta_oleo_km"), 0))
            return (
                f"O veiculo com troca de oleo mais critica agora e {_as_str(pior.get('nome')) or '-'} "
                f"com falta de {_as_int(pior.get('falta_oleo_km'), 0)} km para oleo."
            )
        if "custo" in normalized and "km" in normalized and any(term in normalized for term in ("piorou", "pior", "mais", "maior")):
            ranked = []
            for row in dict_rows:
                km_atual = _as_float(row.get("km_atual"), 0.0)
                custo_total = _as_float(row.get("custo_total"), 0.0)
                if km_atual <= 0 or custo_total <= 0:
                    continue
                ranked.append((row, custo_total / km_atual))
            if ranked:
                pior, ratio = max(ranked, key=lambda item: item[1])
                return (
                    f"O veiculo com pior custo por km agora e {_as_str(pior.get('nome')) or '-'} "
                    f"com {_fmt_money(ratio)} por km."
                )

    lines = [
        "Resumo estatistico da frota:",
        f"- total de veiculos: {len(dict_rows)}",
        f"- manutencao no limite ou vencida: {len(vencidos_manut)}",
        f"- troca de oleo no limite ou vencida: {len(vencidos_oleo)}",
    ]
    if _as_str(maior_km.get("nome")):
        lines.append(
            f"- maior KM atual: {_as_str(maior_km.get('nome'))} com {_as_int(maior_km.get('km_atual'), 0)} km"
        )
    if _as_float(maior_custo.get("custo_total"), 0.0) > 0:
        lines.append(
            f"- maior custo acumulado: {_as_str(maior_custo.get('nome')) or 'veiculo'} com {_fmt_money(maior_custo.get('custo_total'))}"
        )

    wants_list = _message_wants_listing(normalized) or "detalhe" in normalized
    if wants_list and (vencidos_manut or vencidos_oleo):
        lines.append("Pendencias principais:")
        for row in (vencidos_manut[:3] if vencidos_manut else dict_rows[:3]):
            lines.append(
                f"- {_as_str(row.get('nome')) or '-'}: falta manut {_as_int(row.get('falta_manut_km'), 0)} km, "
                f"falta oleo {_as_int(row.get('falta_oleo_km'), 0)} km"
            )
    return "\n".join(lines)


def _summarize_comissao_relatorios(payload: dict, normalized: str) -> str:
    resumo = payload.get("resumo_geral") if isinstance(payload.get("resumo_geral"), dict) else {}
    vendedores = payload.get("total_vendedores") if isinstance(payload.get("total_vendedores"), list) else []
    entregadores = payload.get("total_entregadores") if isinstance(payload.get("total_entregadores"), list) else []
    refugo = payload.get("total_refugo") if isinstance(payload.get("total_refugo"), list) else []
    acucar = payload.get("total_acucar") if isinstance(payload.get("total_acucar"), list) else []

    top_vendedor = _top_row_by(vendedores, "comissao_total") or {}
    top_entregador = _top_row_by(entregadores, "comissao_total") or {}
    top_usina = _top_row_by(acucar, "comissao") or {}
    top_refugo = None
    if refugo:
        top_refugo = max(
            [row for row in refugo if isinstance(row, dict)],
            key=lambda row: _as_float(row.get("dev_gf"), 0.0) + _as_float(row.get("dev_pet"), 0.0),
            default=None,
        )

    if ("refugo" in normalized or "devolu" in normalized) and "entregador" in normalized and isinstance(top_refugo, dict):
        total_refugo = _as_float(top_refugo.get("dev_gf"), 0.0) + _as_float(top_refugo.get("dev_pet"), 0.0)
        return (
            f"O entregador com maior refugo foi {_as_str(top_refugo.get('entregador')) or '-'} "
            f"com {total_refugo:.2f} item(ns)."
        )

    lines = [
        "Resumo estatistico dos relatorios de comissao:",
        f"- total de lancamentos: {_as_int(resumo.get('total_lancamentos'), 0)}",
        f"- base vendedor total: {_fmt_money(resumo.get('base_vendedor_total'))}",
        f"- comissao vendedor total: {_fmt_money(resumo.get('comissao_vendedor_total'))}",
        f"- comissao entregador total: {_fmt_money(resumo.get('comissao_entregador_total'))}",
    ]
    if _as_str(top_vendedor.get("nome")) or _as_int(top_vendedor.get("codigo"), 0) > 0:
        lines.append(
            f"- maior comissao de vendedor: {_as_str(top_vendedor.get('nome')) or 'codigo ' + str(_as_int(top_vendedor.get('codigo'), 0))} "
            f"com {_fmt_money(top_vendedor.get('comissao_total'))}"
        )
    if _as_str(top_entregador.get("nome")):
        lines.append(
            f"- maior comissao de entregador: {_as_str(top_entregador.get('nome'))} com {_fmt_money(top_entregador.get('comissao_total'))}"
        )
    if _as_str(top_usina.get("usina")):
        lines.append(
            f"- maior comissao de acucar/usina: {_as_str(top_usina.get('usina'))} com {_fmt_money(top_usina.get('comissao'))}"
        )
    if ("refugo" in normalized or "devolu" in normalized) and isinstance(top_refugo, dict):
        total_refugo = _as_float(top_refugo.get("dev_gf"), 0.0) + _as_float(top_refugo.get("dev_pet"), 0.0)
        lines.append(f"- maior refugo: {_as_str(top_refugo.get('entregador'))} com {total_refugo:.2f}")
    return "\n".join(lines)


def _summarize_vendas_dashboard(payload: dict, normalized: str) -> str:
    resumo = payload.get("resumo_geral") if isinstance(payload.get("resumo_geral"), dict) else {}
    vendedores = payload.get("vendedores") if isinstance(payload.get("vendedores"), list) else []
    top_atual = _top_row_by(vendedores, "ultimo_valor_liquido") or _top_row_by(vendedores, "total_valor_liquido") or {}
    mes_atual = _as_str(payload.get("mes_atual"))
    mes_anterior = _as_str(payload.get("mes_anterior"))

    if vendedores and "vendedor" in normalized:
        if "cresc" in normalized or "subiu" in normalized or "aument" in normalized:
            top_growth = max(vendedores, key=lambda row: _as_float(row.get("delta_ultimo_mes"), 0.0))
            delta = _as_float(top_growth.get("delta_ultimo_mes"), 0.0)
            return (
                f"O vendedor que mais cresceu foi {_as_str(top_growth.get('nome')) or '-'} "
                f"com variacao de {_fmt_money(delta)} no ultimo mes."
            )
        if "caiu" in normalized or "queda" in normalized or "recu" in normalized:
            top_drop = min(vendedores, key=lambda row: _as_float(row.get("delta_ultimo_mes"), 0.0))
            delta = _as_float(top_drop.get("delta_ultimo_mes"), 0.0)
            return (
                f"O vendedor que mais caiu foi {_as_str(top_drop.get('nome')) or '-'} "
                f"com variacao de {_fmt_money(delta)} no ultimo mes."
            )
        if any(term in normalized for term in ("perdeu valor", "mais perdeu", "perdeu mais", "perda de valor")):
            top_loss = min(vendedores, key=lambda row: _as_float(row.get("delta_ultimo_mes"), 0.0))
            delta = _as_float(top_loss.get("delta_ultimo_mes"), 0.0)
            return (
                f"O vendedor que mais perdeu valor foi {_as_str(top_loss.get('nome')) or '-'} "
                f"com variacao de {_fmt_money(delta)} no ultimo mes."
            )
    if "cliente" in normalized:
        candidate_lists = [
            payload.get("clientes"),
            payload.get("top_clientes"),
        ]
        client_rows = []
        for items in candidate_lists:
            if isinstance(items, list):
                client_rows = [row for row in items if isinstance(row, dict)]
                if client_rows:
                    break
        if client_rows and any(term in normalized for term in ("perdeu valor", "mais perdeu", "perdeu mais", "queda", "caiu")):
            metric_fields = ("delta_ultimo_mes", "variacao_valor", "delta_valor")
            def _client_delta(row: dict) -> float:
                for field in metric_fields:
                    value = row.get(field)
                    if value not in (None, ""):
                        return _as_float(value, 0.0)
                return 0.0
            top_loss = min(client_rows, key=_client_delta)
            delta = _client_delta(top_loss)
            client_name = _as_str(top_loss.get("cliente")) or _as_str(top_loss.get("nome"))
            return (
                f"O cliente que mais perdeu valor foi {client_name or '-'} "
                f"com variacao de {_fmt_money(delta)} no periodo."
            )
    if "vendeu" in normalized or "vendeu mais" in normalized or "maior venda" in normalized:
        return (
            f"O vendedor com maior venda/liquido no periodo atual e {_as_str(top_atual.get('nome')) or '-'} "
            f"com {_fmt_money(top_atual.get('ultimo_valor_liquido') or top_atual.get('total_valor_liquido'))}."
        )
    if any(term in normalized for term in ("este mes", "esse mes", "mes atual")) and "mes passado" in normalized:
        return (
            f"Comparativo de vendas: este mes ({mes_atual or '-'}) = {_fmt_money(resumo.get('valor_atual'))}; "
            f"mes passado ({mes_anterior or '-'}) = {_fmt_money(resumo.get('valor_anterior'))}; "
            f"variacao = {_fmt_money(resumo.get('variacao_valor'))} / {_as_float(resumo.get('variacao_percentual'), 0.0):.2f}%."
        )

    lines = [
        "Resumo estatistico do dashboard de vendas:",
        f"- vendedores analisados: {_as_int(resumo.get('vendedores'), len(vendedores))}",
        f"- meses analisados: {_as_int(resumo.get('meses'), len(payload.get('meses_disponiveis') or []))}",
        f"- valor atual: {_fmt_money(resumo.get('valor_atual'))}" + (f" ({mes_atual})" if mes_atual else ""),
        f"- valor anterior: {_fmt_money(resumo.get('valor_anterior'))}" + (f" ({mes_anterior})" if mes_anterior else ""),
        f"- variacao do ultimo mes: {_fmt_money(resumo.get('variacao_valor'))} / {_as_float(resumo.get('variacao_percentual'), 0.0):.2f}%",
        f"- vendedores que cresceram: {_as_int(resumo.get('cresceu'), 0)} | caíram: {_as_int(resumo.get('caiu'), 0)} | estaveis: {_as_int(resumo.get('estavel'), 0)}",
    ]
    if _as_str(top_atual.get("nome")):
        lines.append(
            f"- melhor vendedor no periodo atual: {_as_str(top_atual.get('nome'))} com {_fmt_money(top_atual.get('ultimo_valor_liquido') or top_atual.get('total_valor_liquido'))}"
        )
    return "\n".join(lines)


def _summarize_vendas_painel(payload: dict) -> str:
    bon = payload.get("bonificacoes") if isinstance(payload.get("bonificacoes"), dict) else {}
    var = payload.get("variacao_preco") if isinstance(payload.get("variacao_preco"), dict) else {}
    mensal = payload.get("mensal") if isinstance(payload.get("mensal"), dict) else {}

    bon_totais = bon.get("totais") if isinstance(bon.get("totais"), dict) else bon.get("resumo_geral") if isinstance(bon.get("resumo_geral"), dict) else {}
    var_resumo = var.get("resumo_geral") if isinstance(var.get("resumo_geral"), dict) else {}
    mensal_resumo = mensal.get("resumo_geral") if isinstance(mensal.get("resumo_geral"), dict) else {}

    lines = ["Resumo estatistico do painel consolidado de vendas:"]
    if bon_totais:
        lines.append(
            f"- bonificacao/financeiro: venda {_fmt_money(bon_totais.get('valor_venda'))}, "
            f"bonificacao {_fmt_money(bon_totais.get('bonificacao'))}, liquido {_fmt_money(bon_totais.get('valor_liquido'))}"
        )
    if var_resumo:
        lines.append(
            f"- variacao de preco: {_as_int(var_resumo.get('itens') or var_resumo.get('quantidade_variacoes'), 0)} ocorrencia(s)"
        )
    if mensal_resumo:
        lines.append(
            f"- painel mensal: venda {_fmt_money(mensal_resumo.get('valor_venda'))}, liquido {_fmt_money(mensal_resumo.get('valor_liquido'))}"
        )
    if len(lines) == 1:
        linhas_aux = []
        for key in ("bonificacoes", "variacao_preco", "mensal"):
            if isinstance(payload.get(key), dict):
                linhas_aux.append(key)
        lines.append("- blocos disponiveis: " + ", ".join(linhas_aux or ["nenhum"]))
    return "\n".join(lines)


def _summarize_vendas_relatorio(payload: dict) -> str:
    relatorio_tipo = _as_str(payload.get("relatorio_tipo")) or "vendas"
    totais = payload.get("totais") if isinstance(payload.get("totais"), dict) else payload.get("resumo_geral") if isinstance(payload.get("resumo_geral"), dict) else {}
    vendedores = payload.get("vendedores") if isinstance(payload.get("vendedores"), list) else []
    grupos = payload.get("resumo_grupos") if isinstance(payload.get("resumo_grupos"), list) else payload.get("grupos") if isinstance(payload.get("grupos"), list) else []
    detalhes = payload.get("detalhes_vendedor") if isinstance(payload.get("detalhes_vendedor"), list) else []

    lines = [f"Resumo estatistico do relatorio de vendas ({relatorio_tipo}):"]
    if totais:
        if any(key in totais for key in ("valor_venda", "bonificacao", "valor_liquido")):
            lines.append(
                f"- totais: venda {_fmt_money(totais.get('valor_venda'))}, devolvido {_fmt_money(totais.get('valor_devolvido'))}, "
                f"bonificacao {_fmt_money(totais.get('bonificacao'))}, liquido {_fmt_money(totais.get('valor_liquido'))}"
            )
        if any(key in totais for key in ("clientes", "notas", "itens", "vendedores")):
            lines.append(
                f"- volume de registros: vendedores {_as_int(totais.get('vendedores'), 0)}, clientes {_as_int(totais.get('clientes'), 0)}, "
                f"notas {_as_int(totais.get('notas'), 0)}, itens {_as_int(totais.get('itens'), 0)}"
            )
    top_vendedor = _top_row_by(vendedores, "valor_liquido") or _top_row_by(vendedores, "bonificacao") or _top_row_by(vendedores, "total_valor_liquido") or {}
    if _as_str(top_vendedor.get("nome")):
        metric = top_vendedor.get("valor_liquido")
        if metric in (None, ""):
            metric = top_vendedor.get("bonificacao")
        if metric in (None, ""):
            metric = top_vendedor.get("total_valor_liquido")
        lines.append(f"- vendedor destaque: {_as_str(top_vendedor.get('nome'))} com {_fmt_money(metric)}")
    top_grupo = _top_row_by(grupos, "valor_liquido") or _top_row_by(grupos, "bonificacao") or _top_row_by(grupos, "volumes_cliente") or {}
    if isinstance(top_grupo, dict) and top_grupo:
        nome_grupo = _as_str(top_grupo.get("grupo")) or _as_str(top_grupo.get("categoria")) or _as_str(top_grupo.get("nome"))
        if nome_grupo:
            if any(key in top_grupo for key in ("valor_liquido", "bonificacao")):
                lines.append(f"- grupo destaque: {nome_grupo} com {_fmt_money(top_grupo.get('valor_liquido') or top_grupo.get('bonificacao'))}")
            elif top_grupo.get("volumes_cliente") not in (None, ""):
                lines.append(f"- grupo destaque: {nome_grupo} com {_as_float(top_grupo.get('volumes_cliente'), 0.0):.2f} hl")
    if detalhes:
        lines.append(f"- detalhes individuais disponiveis: {len(detalhes)}")
    return "\n".join(lines)


def _summarize_special_module(item: dict, payload: object, normalized: str) -> str | None:
    name = _as_str(item.get("name"))
    if name == "status_api" and isinstance(payload, dict):
        return _summarize_status_api(payload)
    if name == "usuario_logado" and isinstance(payload, dict):
        return _summarize_logged_user(payload)
    if name == "dashboard_frota" and isinstance(payload, list):
        return _summarize_dashboard_frota(payload, normalized)
    if name == "frota_resumo" and isinstance(payload, list):
        return _summarize_frota_resumo(payload, normalized)
    if name == "chat_conversa" and isinstance(payload, list):
        return _summarize_chat_conversa_temporal(payload, normalized) or _summarize_chat_conversa(payload)
    if name == "usuarios_chat_unread" and isinstance(payload, dict):
        return _summarize_chat_unread(payload)
    if name == "carga_detalhes" and isinstance(payload, dict):
        return _summarize_carga_detalhes(payload)
    if name == "frota_historico" and isinstance(payload, dict):
        return _summarize_frota_historico(payload)
    if name == "comissao_relatorios" and isinstance(payload, dict):
        return _summarize_comissao_relatorios(payload, normalized)
    if name == "vendas_dashboard" and isinstance(payload, dict):
        return _summarize_vendas_dashboard(payload, normalized)
    if name == "dashboard_vendas_painel" and isinstance(payload, dict):
        return _summarize_vendas_painel(payload)
    if name == "vendas_relatorio" and isinstance(payload, dict):
        return _summarize_vendas_relatorio(payload)
    return None


def _agent_broad_system_read_reply(message: str) -> dict | None:
    normalized = normalize(message)
    if not normalized:
        return None

    item = _read_only_module_match(message)
    if not item:
        return None

    path = _read_only_module_path(item, message)
    if not path:
        return _read_only_module_missing_reply(item)

    try:
        payload = system_api("GET", path)
    except Exception:
        return None

    label = _as_str(item.get("label")) or _as_str(item.get("name")) or "dados do sistema"
    fields = item.get("fields") or []
    special = _summarize_special_module(item, payload, normalized)
    if special:
        reply = special
    elif isinstance(payload, list):
        reply = _summarize_api_list(label, payload, fields, normalized)
    elif isinstance(payload, dict):
        reply = _summarize_api_dict(label, payload, fields)
    else:
        reply = f"Consultei {label}, mas a resposta veio em formato inesperado."

    source_path = _as_str(item.get("path")) or path
    return {"reply": f"{reply}\n\nFontes: server.py, {source_path}"}


def _agent_frota_maintenance_reply(message: str) -> dict | None:
    normalized = normalize(message)
    if not normalized:
        return None

    maintenance_terms = (
        "manutenc",
        "troca de oleo",
        "oleo",
        "frota",
        "falta para manutencao",
        "falta_manut",
        "falta manut",
        "falta_oleo",
        "falta oleo",
        "gestao de frota",
    )
    if not any(term in normalized for term in maintenance_terms):
        return None
    if "custo" in normalized and "km" in normalized:
        return None

    wants_exact_zero = (
        ("igual a zero" in normalized or " zerado" in normalized or " zerada" in normalized or " zero" in normalized)
        and "falta" in normalized
    )
    wants_overdue = wants_exact_zero or any(term in normalized for term in ("atrasad", "vencid", "abaixo de zero", "menor que zero"))
    wants_manut = any(term in normalized for term in ("manutenc", "falta para manutencao", "falta_manut", "falta manut"))
    wants_oleo = any(term in normalized for term in ("oleo", "falta_oleo", "falta oleo"))
    structured_read_words = ("dashboard", "painel", "historico", "histórico", "detalhe", "detalhes", "resumo")
    if (_message_wants_listing(normalized) or any(term in normalized for term in structured_read_words)) and not wants_overdue:
        return None
    if not wants_manut and not wants_oleo:
        wants_manut = True
        wants_oleo = True

    try:
        rows = system_api("GET", "/api/frota_resumo")
    except Exception:
        return None

    if not isinstance(rows, list) or not rows:
        return {"reply": "Nao encontrei dados de gestao de frota no momento.\n\nFontes: server.py, /api/frota_resumo"}

    wants_direct_top = bool(re.search(r"\b(qual|quais)\b", normalized)) and any(
        term in normalized for term in ("mais", "maior", "pior", "atrasad", "vencid")
    )
    if wants_direct_top:
        if wants_manut and rows:
            pior = min(rows, key=lambda row: _as_int((row or {}).get("falta_manut_km"), 0))
            return {
                "reply": (
                    f"O veiculo com manutencao mais critica agora e {_as_str((pior or {}).get('nome')) or '-'} "
                    f"com falta de {_as_int((pior or {}).get('falta_manut_km'), 0)} km para manutencao.\n\n"
                    "Fontes: server.py, /api/frota_resumo"
                )
            }
        if wants_oleo and rows:
            pior = min(rows, key=lambda row: _as_int((row or {}).get("falta_oleo_km"), 0))
            return {
                "reply": (
                    f"O veiculo com troca de oleo mais critica agora e {_as_str((pior or {}).get('nome')) or '-'} "
                    f"com falta de {_as_int((pior or {}).get('falta_oleo_km'), 0)} km para oleo.\n\n"
                    "Fontes: server.py, /api/frota_resumo"
                )
            }

    matches: list[dict] = []
    for row in rows:
        falta_manut = _as_int(row.get("falta_manut_km"), 0)
        falta_oleo = _as_int(row.get("falta_oleo_km"), 0)
        issues: list[str] = []

        if wants_manut:
            if wants_exact_zero and falta_manut == 0:
                issues.append("manutencao no limite (0 km)")
            elif wants_overdue and falta_manut <= 0:
                issues.append(f"manutencao vencida ({falta_manut} km)")
            elif not wants_overdue:
                issues.append(f"falta manutencao: {falta_manut} km")

        if wants_oleo:
            if wants_exact_zero and falta_oleo == 0:
                issues.append("troca de oleo no limite (0 km)")
            elif wants_overdue and falta_oleo <= 0:
                issues.append(f"troca de oleo vencida ({falta_oleo} km)")
            elif not wants_overdue:
                issues.append(f"falta oleo: {falta_oleo} km")

        if issues:
            matches.append({
                "row": row,
                "issues": issues,
            })

    if not matches:
        if wants_exact_zero:
            reply = "Nao encontrei veiculos com os campos de falta de manutencao/oleo zerados."
        elif wants_overdue:
            reply = "Nao encontrei veiculos com manutencao atrasada ou troca de oleo vencida no momento."
        else:
            reply = "Nao encontrei pendencias relevantes de manutencao/oleo na frota agora."
        return {"reply": f"{reply}\n\nFontes: server.py, /api/frota_resumo"}

    lines: list[str] = []
    for item in matches[:5]:
        row = item["row"]
        nome = _as_str(row.get("nome")) or f"Veiculo #{_as_int(row.get('id'), 0)}"
        placa = _as_str(row.get("placa"))
        km_atual = _as_int(row.get("km_atual"), 0)
        label = f"{nome} ({placa})" if placa else nome
        lines.append(f"{label} - KM atual {km_atual} - " + " | ".join(item["issues"]))

    if wants_exact_zero:
        intro = f"Encontrei {len(matches)} veiculo(s) com campo de falta no limite exato:"
    elif wants_overdue:
        intro = f"Encontrei {len(matches)} veiculo(s) com manutencao/oleo no limite ou vencidos:"
    else:
        intro = f"Resumo de {len(matches)} veiculo(s) na gestao de frota:"

    reply = intro + "\n- " + "\n- ".join(lines)
    return {"reply": f"{reply}\n\nFontes: server.py, /api/frota_resumo"}


def _agent_stock_lookup_reply(message: str) -> dict | None:
    normalized = normalize(message)
    if not normalized:
        return None

    stock_terms = {
        "estoque",
        "saldo",
        "saldos",
        "inventario",
        "inventario",
        "posicao de estoque",
        "posicao do estoque",
        "tenho em estoque",
        "ha em estoque",
        "tem em estoque",
    }
    if not any(term in normalized for term in stock_terms):
        return None

    try:
        payload = system_api("GET", "/api/estoque/saldo")
    except Exception:
        return None

    rows = payload.get("rows") if isinstance(payload, dict) else None
    meta = payload.get("meta") if isinstance(payload, dict) else None
    rows = rows if isinstance(rows, list) else []
    meta = meta if isinstance(meta, dict) else {}
    if not rows:
        return {"reply": "Nao encontrei saldo de estoque no momento.\n\nFontes: server.py, /api/estoque/saldo"}

    wants_more = bool(re.search(r"\b(mais|maior|maiores|top)\b", normalized))
    wants_less = bool(re.search(r"\b(menos|menor|menores)\b", normalized))
    wants_product_ranking = any(term in normalized for term in ("produto", "produtos", "item", "itens", "ranking"))
    if (wants_more or wants_less) and wants_product_ranking:
        ranked = sorted(rows, key=lambda item: _as_float(item.get("quantidade_atual"), 0.0), reverse=not wants_less)
        ranked = [item for item in ranked if _as_str(item.get("nome_produto"))]
        if ranked:
            best = ranked[0]
            if wants_less:
                reply = (
                    f"O produto com menor saldo agora e {_as_str(best.get('nome_produto')) or '-'} "
                    f"com {_as_float(best.get('quantidade_atual'), 0.0):.3f} unidades base."
                )
            else:
                reply = (
                    f"O produto com maior saldo agora e {_as_str(best.get('nome_produto')) or '-'} "
                    f"com {_as_float(best.get('quantidade_atual'), 0.0):.3f} unidades base."
                )
            if len(ranked) > 1 and ("top" in normalized or "ranking" in normalized or "produtos" in normalized):
                extras = ranked[:5]
                reply += " Ranking atual: " + "; ".join(
                    f"{_as_str(item.get('nome_produto')) or '-'} ({_as_float(item.get('quantidade_atual'), 0.0):.3f})"
                    for item in extras
                ) + "."
            return {"reply": f"{reply}\n\nFontes: server.py, /api/estoque/saldo"}

    hint = normalized
    for term in stock_terms:
        hint = hint.replace(normalize(term), " ")
    for term in (
        "quanto", "quantos", "quantidade", "tenho", "tem", "temos", "agora", "momento",
        "qual", "quais", "do", "da", "de", "em", "no", "na", "produto", "produtos",
        "item", "itens", "meu", "nosso", "atual", "atuais",
    ):
        hint = re.sub(rf"\b{re.escape(normalize(term))}\b", " ", hint)
    hint = re.sub(r"[^\w\s-]+", " ", hint)
    hint = re.sub(r"\s+", " ", hint).strip()
    hint_tokens = [token for token in hint.split() if len(token) >= 3]

    if hint_tokens:
        matches = []
        for row in rows:
            haystack = normalize(" ".join([
                _as_str(row.get("nome_produto")),
                _as_str(row.get("produto_base_nome")),
                _as_str(row.get("codigo_produto_nfe")),
                _as_str(row.get("codigo_barras")),
                _as_str(row.get("grupo_estoque")),
            ]))
            if all(token in haystack for token in hint_tokens):
                matches.append(row)
        matches.sort(key=lambda item: _as_float(item.get("quantidade_atual"), 0.0), reverse=True)
        if matches:
            if len(matches) == 1:
                item = matches[0]
                reply = (
                    f"No momento, {_as_str(item.get('nome_produto')) or 'esse produto'} tem "
                    f"{_as_float(item.get('quantidade_atual'), 0.0):.3f} unidades base em estoque, "
                    f"com {_as_float(item.get('quantidade_comprometida'), 0.0):.3f} comprometidas."
                )
            else:
                lines = []
                for item in matches[:5]:
                    lines.append(
                        f"{_as_str(item.get('nome_produto')) or '-'}: "
                        f"{_as_float(item.get('quantidade_atual'), 0.0):.3f} em estoque"
                    )
                reply = "Encontrei estes saldos de estoque:\n- " + "\n- ".join(lines)
            return {"reply": f"{reply}\n\nFontes: server.py, /api/estoque/saldo"}

    total_atual = round(sum(_as_float(row.get("quantidade_atual"), 0.0) for row in rows), 3)
    total_comprometido = round(sum(_as_float(row.get("quantidade_comprometida"), 0.0) for row in rows), 3)
    total_skus = sum(1 for row in rows if _as_float(row.get("quantidade_atual"), 0.0) != 0)
    top_items = sorted(rows, key=lambda item: _as_float(item.get("quantidade_atual"), 0.0), reverse=True)[:5]
    top_text = "; ".join(
        f"{_as_str(item.get('nome_produto')) or '-'} ({_as_float(item.get('quantidade_atual'), 0.0):.3f})"
        for item in top_items
        if _as_float(item.get("quantidade_atual"), 0.0) > 0
    )
    reply = (
        f"No momento, o estoque consolidado soma {total_atual:.3f} unidades base, "
        f"distribuidas em {total_skus} produtos com saldo, com {total_comprometido:.3f} unidades comprometidas."
    )
    if top_text:
        reply += f" Maiores saldos agora: {top_text}."
    if meta.get("data_referencia"):
        reply += f" Data de referencia: {meta.get('data_referencia')}."
    return {"reply": f"{reply}\n\nFontes: server.py, /api/estoque/saldo"}


def _sales_packaging_category(product_name: object, group_name: object = "") -> str:
    text = normalize(_as_str(product_name)).upper().strip()
    group_text = normalize(_as_str(group_name)).upper().strip()
    combined = " ".join(part for part in (group_text, text) if part).strip()
    if re.search(r"\b001004\b", combined) or "PET2L" in combined or re.search(r"\bPET\s*2L\b", combined):
        return "PET 2L"
    if re.search(r"\b001005\b", combined) or "PET600" in combined or re.search(r"\bPET\s*600\b", combined):
        return "PET 600ML"
    if re.search(r"\b001006\b", combined) or "PET200" in combined or re.search(r"\bPET\s*200\b", combined):
        return "PET 200ML"
    if not text:
        return "SEM EMBALAGEM"

    text = re.sub(r"[\-/_,;:()[\]{}|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    packaging = ""
    if re.search(r"\bRETORN", text) or re.search(r"\bVIDRO\b", text):
        packaging = "RETORNAVEL"
    elif re.search(r"\bPET\b", text) or re.search(r"\bDESCART", text) or re.search(r"\bDESC\b", text):
        packaging = "PET"

    size = ""
    match = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(ML|L|LT|KG|G|GR|GRS|GRA)\b", text)
    if match:
        value = match.group(1).replace(",", ".")
        unit = match.group(2)
        if unit == "LT":
            unit = "L"
        if value.endswith(".0"):
            value = value[:-2]
        size = f"{value}{unit}"
    else:
        match = re.search(r"\b(\d+)\s*X\s*(\d+(?:[.,]\d+)?)\s*(ML|L|LT|KG|G|GR|GRS|GRA)\b", text)
        if match:
            amount = match.group(1)
            value = match.group(2).replace(",", ".")
            unit = match.group(3)
            if unit == "LT":
                unit = "L"
            if value.endswith(".0"):
                value = value[:-2]
            size = f"{amount}X{value}{unit}"
        elif re.search(r"\b6X2(?:LT)?\b", text) or re.search(r"\b2L(?:T|ITRO|ITROS)?\b", text):
            size = "2L"

    parts = [part for part in (packaging, size) if part]
    return " ".join(parts) if parts else text


def _sales_group_code(value: object) -> str:
    digits = re.sub(r"\D+", "", _as_str(value))
    return digits[:6] if len(digits) >= 6 else ""


def _sales_group_aliases(group_code: str, label: str, category: str) -> list[str]:
    label_text = _as_str(label)
    normalized_label = normalize(label_text)
    spaced_label = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", label_text)
    spaced_label = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", spaced_label)
    normalized_spaced = normalize(spaced_label)
    compact_label = normalized_label.replace(" ", "")
    compact_spaced = normalized_spaced.replace(" ", "")
    prefix_size_match = re.match(r"([a-z]+)\s*(\d+(?:[.,]\d+)?)\s*([a-z]+)", normalized_spaced)

    aliases = {
        group_code,
        f"{group_code[:3]}.{group_code[3:]}",
        normalized_label,
        normalized_spaced,
        compact_label,
        compact_spaced,
    }

    size_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(ml|l|lt)", normalized_spaced)
    size_alias = ""
    if size_match:
        raw_value = size_match.group(1).replace(",", ".")
        unit = "l" if size_match.group(2) == "lt" else size_match.group(2)
        if raw_value.endswith(".0"):
            raw_value = raw_value[:-2]
        size_alias = f"{raw_value}{unit}"
        aliases.add(size_alias)
        aliases.add(f"{raw_value} {unit}")
    if prefix_size_match:
        prefix = prefix_size_match.group(1)
        value = prefix_size_match.group(2).replace(",", ".")
        if value.endswith(".0"):
            value = value[:-2]
        aliases.add(f"{prefix}{value}")
        aliases.add(f"{prefix} {value}")

    label_key = compact_label or compact_spaced
    category_norm = normalize(category)
    if label_key.startswith("grf"):
        aliases.update({
            f"grf {size_alias}".strip(),
            f"garrafa {size_alias}".strip(),
            f"garrafa {raw_value if size_match else ''} {unit if size_match else ''}".strip(),
            f"garrafas {size_alias}".strip(),
            f"retornavel {size_alias}".strip(),
            f"retornavel {raw_value if size_match else ''} {unit if size_match else ''}".strip(),
        })
    elif label_key.startswith("pet"):
        aliases.update({
            f"pet {size_alias}".strip(),
            f"garrafa pet {size_alias}".strip(),
            f"garrafas pet {size_alias}".strip(),
            f"pet {raw_value if size_match else ''} {unit if size_match else ''}".strip(),
        })
    elif "agua" in label_key or "agua" in category_norm:
        aliases.update({
            "agua",
            "agua sem gas",
            "agua sem gás",
            "garrafa agua",
        })

    cleaned = []
    seen: set[str] = set()
    for alias in aliases:
        alias_norm = normalize(alias)
        alias_norm = re.sub(r"\s+", " ", alias_norm).strip()
        if alias_norm and alias_norm not in seen:
            seen.add(alias_norm)
            cleaned.append(alias_norm)
    return cleaned


@lru_cache(maxsize=1)
def _sales_group_catalog() -> list[dict[str, str | list[str]]]:
    config_path = ROOT / "Relatorios" / "config-rel-vendas"
    if not config_path.exists():
        return []

    catalog: list[dict[str, str | list[str]]] = []
    current_category = ""
    for raw_line in config_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        section_match = re.match(r"\[categoria\s+(.+?)\]", line, flags=re.IGNORECASE)
        if section_match:
            current_category = normalize(section_match.group(1))
            continue
        group_match = re.match(r"^(\d{3})\.(\d{3})\s+(.+)$", line)
        if not group_match:
            continue
        group_code = f"{group_match.group(1)}{group_match.group(2)}"
        label = _as_str(group_match.group(3))
        aliases = _sales_group_aliases(group_code, label, current_category)
        catalog.append({
            "key": normalize(label).replace(" ", "") or group_code,
            "label": f"grupo {group_match.group(1)}.{group_match.group(2)} {label}",
            "group_code": group_code,
            "category": current_category,
            "aliases": aliases,
        })
    return catalog


def _sales_product_alias(message: str) -> dict[str, str] | None:
    normalized = normalize(message)
    for entry in _sales_group_catalog():
        aliases = entry.get("aliases")
        if not isinstance(aliases, list):
            continue
        for alias in aliases:
            if alias and re.search(rf"\b{re.escape(alias)}\b", normalized):
                return {
                    "key": _as_str(entry.get("key")),
                    "label": _as_str(entry.get("label")),
                    "group_code": _as_str(entry.get("group_code")),
                    "category": _as_str(entry.get("category")),
                }
    return None


def _sales_row_matches_product(row: dict, product_request: dict[str, str]) -> bool:
    expected_group = _as_str(product_request.get("group_code"))
    if expected_group:
        for field in ("grupo_norm", "grupo_raw", "produto"):
            if _sales_group_code(row.get(field)) == expected_group:
                return True

    expected_category = _as_str(product_request.get("category"))
    if expected_category:
        category = _sales_packaging_category(row.get("produto"), row.get("grupo_norm"))
        if normalize(category) == normalize(expected_category):
            return True
    return False


def _sales_row_metric(row: dict) -> float:
    quantity = _as_float(row.get("quantidade"), 0.0)
    if quantity > 0:
        return quantity
    physical_box = _as_float(row.get("caixa_fisica"), 0.0)
    if physical_box > 0:
        return physical_box
    boxes = _as_float(row.get("caixas"), 0.0)
    if boxes > 0:
        return boxes
    liters = _as_float(row.get("litros"), 0.0)
    if liters > 0:
        return liters
    return 0.0


def _sales_row_is_bonus_or_return(row: dict) -> bool:
    operation = normalize(_as_str(row.get("tipo_operacao")))
    condition = _as_str(row.get("condicao")).upper()
    tab_sale = _as_int(row.get("tab_venda"), 0)
    if tab_sale == 91 or operation == "bon" or condition == "O":
        return True
    if "dev" in operation or condition in {"D", "R"}:
        return True
    if _as_float(row.get("valor_devolvido"), 0.0) > 0:
        return True
    if _as_float(row.get("quantidade_devolvida"), 0.0) > 0:
        return True
    if _as_float(row.get("litro_devolvido"), 0.0) > 0:
        return True
    if _as_float(row.get("caixa_devolvida"), 0.0) > 0:
        return True
    return False


def _sales_mix_bucket(qtd_groups: object) -> str:
    qty = max(0, _as_int(qtd_groups, 0))
    if qty >= 6:
        return "6"
    if qty <= 1:
        return "1"
    return str(qty)


def _sales_bucket_value(token: str) -> str | None:
    value = normalize(token)
    mapping = {
        "1": "1",
        "um": "1",
        "uma": "1",
        "primeiro": "1",
        "primeira": "1",
        "2": "2",
        "dois": "2",
        "duas": "2",
        "segundo": "2",
        "segunda": "2",
        "3": "3",
        "tres": "3",
        "terceiro": "3",
        "terceira": "3",
        "4": "4",
        "quatro": "4",
        "quarto": "4",
        "quarta": "4",
        "5": "5",
        "cinco": "5",
        "quinto": "5",
        "quinta": "5",
        "6": "6",
        "seis": "6",
        "sexto": "6",
        "sexta": "6",
    }
    return mapping.get(value)


def _sales_faixa_request(normalized: str) -> str | None:
    token_pattern = r"(?:[1-6]|um|uma|dois|duas|tres|quatro|cinco|seis|primeir[ao]|segund[ao]|terceir[ao]|quart[ao]|quint[ao]|sext[ao])"
    patterns = (
        rf"\b(?:faixa|mix|classe|bucket|nivel)\s*(?:n(?:ivel)?\.?\s*)?({token_pattern})\b",
        rf"\b({token_pattern})\s*(?:a|o)?\s*(?:faixa|mix|classe|bucket|nivel)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            bucket = _sales_bucket_value(match.group(1))
            if bucket:
                return bucket
    return None


def _sales_quantity_metric_request(normalized: str) -> tuple[str, str, str]:
    if any(term in normalized for term in ("hectolitro", "hectolitros", "hl")):
        return "liters", "litros", "hl"
    if any(term in normalized for term in ("litro", "litros")):
        return "liters", "litros", "litros"
    if any(term in normalized for term in ("caixa", "caixas", "cx")):
        return "boxes", "caixas", "caixas"
    return "quantity", "quantidade", "quantidade"


def _sales_period_resolve(cur, import_id: str, month_request: dict | None) -> tuple[datetime.date, datetime.date, str] | None:
    if month_request:
        target_year = month_request.get("year")
        target_month = _as_int(month_request.get("month"), 0)
        if not target_month:
            return None
        if target_year is None:
            cur.execute("""
                SELECT MAX(YEAR(data_ref)) AS ano
                FROM vendas_relatorio_itens
                WHERE import_id=%s AND data_ref IS NOT NULL AND MONTH(data_ref)=%s
            """, (import_id, target_month))
            target_year = _as_int((cur.fetchone() or {}).get("ano"), 0)
        if not target_year:
            return None
        start, end = _month_bounds(int(target_year), target_month)
        return start, end, start.strftime("%m/%Y")

    cur.execute("""
        SELECT MAX(data_ref) AS data_max
        FROM vendas_relatorio_itens
        WHERE import_id=%s AND data_ref IS NOT NULL
    """, (import_id,))
    max_row = cur.fetchone() or {}
    latest = max_row.get("data_max")
    latest_date = None
    if isinstance(latest, datetime.datetime):
        latest_date = latest.date()
    elif isinstance(latest, datetime.date):
        latest_date = latest
    else:
        latest_date = _parse_message_date(_as_str(latest))
    if latest_date is None:
        return None
    start, end = _month_bounds(latest_date.year, latest_date.month)
    return start, end, start.strftime("%m/%Y")


def _agent_sales_mix_client_lookup_reply(message: str) -> dict | None:
    normalized = normalize(message)
    if not normalized:
        return None

    faixa = _sales_faixa_request(normalized)
    if not faixa:
        return None

    has_client_term = any(term in normalized for term in ("cliente", "clientes", "pdv", "pdvs", "comprador", "compradores", "consumidor", "consumidores"))
    wants_list = _message_wants_listing(normalized) or any(term in normalized for term in ("na faixa", "da faixa", "faixa ", "mix ", "classe "))
    wants_quantity = any(term in normalized for term in ("compra", "compram", "comprou", "quantidade", "volume", "litro", "litros", "caixa", "caixas"))
    wants_ranking = bool(re.search(r"\b(qual|quais|quem|top|mais|maior|ranking|lider|lidera|campeao)\b", normalized))
    if not wants_list and not wants_quantity and not wants_ranking:
        if len(normalized.split()) <= 4:
            wants_list = True
        else:
            return None
    if wants_quantity and not wants_ranking and not wants_list:
        wants_ranking = True
    if not has_client_term and not (wants_list or wants_quantity or wants_ranking):
        return None
    metric_key, metric_label, metric_unit = _sales_quantity_metric_request(normalized)
    month_request = _sales_month_request(normalized)

    conn = None
    cur = None
    try:
        conn = _agent_db_connect()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT id
            FROM vendas_relatorios_importados
            WHERE ativo=1
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
        """)
        active = cur.fetchone() or {}
        import_id = _as_str(active.get("id"))
        if not import_id:
            return {"reply": "Nao encontrei um cache ativo de vendas para consultar clientes por faixa.\n\nFontes: server.py, vendas_relatorios_importados"}

        period = _sales_period_resolve(cur, import_id, month_request)
        if not period:
            label = month_request.get("label") if isinstance(month_request, dict) else "o periodo pedido"
            return {
                "reply": f"Nao encontrei dados de vendas para {label or 'o periodo pedido'} ao consultar clientes por faixa.\n\nFontes: server.py, vendas_relatorio_itens"
            }
        start, end, period_label = period

        cur.execute("""
            SELECT
                cliente,
                cliente_norm,
                numero_nf,
                grupo_raw,
                grupo_norm,
                categoria_norm,
                produto,
                quantidade,
                litros,
                caixas,
                caixa_fisica,
                valor_devolvido,
                quantidade_devolvida,
                litro_devolvido,
                caixa_devolvida,
                tipo_operacao,
                condicao,
                tab_venda
            FROM vendas_relatorio_itens
            WHERE import_id=%s
              AND data_ref IS NOT NULL
              AND data_ref >= %s
              AND data_ref < %s
        """, (import_id, start, end))
        rows = cur.fetchall() or []
    except Exception as exc:
        faixa_label = f"faixa {faixa}" if faixa else "a faixa pedida"
        return {
            "reply": (
                f"Reconheci a consulta de clientes na {faixa_label}, mas nao consegui acessar o cache/banco agora "
                f"({_as_str(exc) or 'falha desconhecida'}).\n\n"
                "Fontes: server.py, vendas_relatorio_itens, vendas_relatorios_importados"
            )
        }
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    customers: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or _sales_row_is_bonus_or_return(row):
            continue
        customer_key = _as_str(row.get("cliente_norm")) or normalize(_as_str(row.get("cliente"))) or "sem cliente"
        customer_name = _as_str(row.get("cliente")) or customer_key.upper()
        entry = customers.setdefault(customer_key, {
            "cliente": customer_name,
            "grupos": set(),
            "quantidade": 0.0,
            "litros": 0.0,
            "caixas": 0.0,
            "notas": set(),
            "itens": 0,
        })
        group_value = _as_str(row.get("grupo_norm")) or _as_str(row.get("categoria_norm")) or _as_str(row.get("grupo_raw")) or _as_str(row.get("produto"))
        if group_value:
            entry["grupos"].add(group_value)
        entry["quantidade"] += _as_float(row.get("quantidade"), 0.0)
        entry["litros"] += _as_float(row.get("litros"), 0.0)
        caixas = _as_float(row.get("caixa_fisica"), 0.0)
        if caixas <= 0:
            caixas = _as_float(row.get("caixas"), 0.0)
        entry["caixas"] += caixas
        numero_nf = _as_str(row.get("numero_nf"))
        if numero_nf:
            entry["notas"].add(numero_nf)
        entry["itens"] += 1

    ranked: list[dict] = []
    for entry in customers.values():
        qtd_groups = len(entry.get("grupos") or set())
        faixa_grupos = _sales_mix_bucket(qtd_groups)
        if faixa_grupos != faixa:
            continue
        metric_value = _as_float(entry.get(metric_key if metric_key != "boxes" else "caixas"), 0.0)
        if metric_key == "liters":
            metric_value = round(metric_value / 100.0, 3) if metric_unit == "hl" else round(metric_value, 3)
        else:
            metric_value = round(metric_value, 3)
        ranked.append({
            "cliente": _as_str(entry.get("cliente")) or "SEM CLIENTE",
            "faixa": faixa_grupos,
            "qtd_grupos": qtd_groups,
            "metric": metric_value,
            "notas": len(entry.get("notas") or set()),
            "itens": _as_int(entry.get("itens"), 0),
        })

    ranked.sort(key=lambda item: (-_as_float(item.get("metric"), 0.0), _as_str(item.get("cliente"))))
    if not ranked:
        return {
            "reply": f"Nao encontrei clientes na faixa {faixa} com compras registradas em {period_label}.\n\nFontes: server.py, vendas_relatorio_itens"
        }

    if wants_list and not wants_quantity and not wants_ranking:
        preview = ", ".join(
            f"{_as_str(item.get('cliente'))} ({_as_int(item.get('qtd_grupos'), 0)} grupos)"
            for item in ranked[:10]
        )
        total_clientes = len(ranked)
        return {
            "reply": (
                f"Encontrei {total_clientes} cliente(s) na faixa {faixa} em {period_label}. "
                f"Primeiros resultados: {preview}.\n\n"
                "Fontes: server.py, vendas_relatorio_itens, vendas_relatorios_importados"
            )
        }

    best = ranked[0]
    preview = ", ".join(
        f"{_as_str(item.get('cliente'))} ({_as_float(item.get('metric'), 0.0):.3f} {metric_unit})"
        for item in ranked[:3]
    )
    return {
        "reply": (
            f"Em {period_label}, o cliente da faixa {faixa} com maior {metric_label} comprada foi "
            f"{_as_str(best.get('cliente'))}, com {_as_float(best.get('metric'), 0.0):.3f} {metric_unit}. "
            f"Ele apareceu com {_as_int(best.get('qtd_grupos'), 0)} grupo(s), {_as_int(best.get('notas'), 0)} nota(s) "
            f"e {_as_int(best.get('itens'), 0)} lancamento(s). Top 3: {preview}.\n\n"
            "Fontes: server.py, vendas_relatorio_itens, vendas_relatorios_importados"
        )
    }


def _agent_sales_lookup_reply(message: str) -> dict | None:
    normalized = normalize(message)
    if not normalized:
        return None

    if any(term in normalized for term in ("estoque", "saldo", "inventario", "inventário")):
        return None

    product_alias = _sales_product_alias(message)
    if not product_alias:
        return None

    month_request = _sales_month_request(normalized)
    has_sales_term = any(term in normalized for term in ("venda", "vendas", "vendeu", "vendido", "garrafa", "garrafas", "produto", "produtos"))
    has_seller_term = any(term in normalized for term in ("vendedor", "vendedores"))
    wants_ranking = bool(re.search(r"\b(qual|quais|quem|top|mais|maior|ranking|lider|lidera|campeao)\b", normalized))
    if not wants_ranking and not has_seller_term:
        return None

    product_label = _as_str(product_alias.get("label"))

    conn = None
    cur = None
    try:
        conn = _agent_db_connect()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT id
            FROM vendas_relatorios_importados
            WHERE ativo=1
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
        """)
        active = cur.fetchone() or {}
        import_id = _as_str(active.get("id"))
        if not import_id:
            return {"reply": "Nao encontrei um cache ativo de vendas para consultar esse ranking.\n\nFontes: server.py, vendas_relatorios_importados"}

        period = _sales_period_resolve(cur, import_id, month_request)
        if not period:
            period_label = month_request.get("label") if isinstance(month_request, dict) else "o periodo mais recente"
            return {
                "reply": f"Nao encontrei dados de vendas para {product_label} em {period_label or 'o periodo pedido'}.\n\nFontes: server.py, vendas_relatorio_itens"
            }
        start, end, period_label = period
        cur.execute("""
            SELECT
                vendedor_nome,
                vendedor_key,
                produto,
                grupo_raw,
                grupo_norm,
                quantidade,
                caixa_fisica,
                caixas,
                litros,
                valor_devolvido,
                quantidade_devolvida,
                litro_devolvido,
                caixa_devolvida,
                tipo_operacao,
                condicao,
                tab_venda
            FROM vendas_relatorio_itens
            WHERE import_id=%s
              AND data_ref IS NOT NULL
              AND data_ref >= %s
              AND data_ref < %s
        """, (import_id, start, end))
        rows = cur.fetchall() or []
    except Exception as exc:
        month_label = month_request.get("label") or "esse periodo"
        return {
            "reply": (
                f"Reconheci a consulta de vendas para {product_label} em {month_label}, "
                f"mas nao consegui acessar o cache/banco agora ({_as_str(exc) or 'falha desconhecida'}).\n\n"
                "Fontes: server.py, vendas_relatorio_itens, vendas_relatorios_importados"
            )
        }
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    totals: dict[str, float] = {}
    launches: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict) or _sales_row_is_bonus_or_return(row):
            continue
        if not _sales_row_matches_product(row, product_alias):
            continue
        seller = _as_str(row.get("vendedor_nome")) or _as_str(row.get("vendedor_key")) or "SEM VENDEDOR"
        metric = _sales_row_metric(row)
        if metric <= 0:
            continue
        totals[seller] = totals.get(seller, 0.0) + metric
        launches[seller] = launches.get(seller, 0) + 1

    month_label = period_label or start.strftime("%m/%Y")
    if not totals:
        return {
            "reply": f"Nao encontrei vendas de {product_label} em {month_label} para montar o ranking por vendedor.\n\nFontes: server.py, vendas_relatorio_itens"
        }

    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    best_name, best_total = ranked[0]
    top_preview = ", ".join(f"{name} ({total:.3f})" for name, total in ranked[:3])
    return {
        "reply": (
            f"Considerando a quantidade vendida no relatorio, o vendedor que mais vendeu {product_label} em {month_label} "
            f"foi {best_name}, com {best_total:.3f}. Lancamentos considerados: {launches.get(best_name, 0)}. "
            f"Top 3: {top_preview}.\n\nFontes: server.py, vendas_relatorio_itens, vendas_relatorios_importados"
        )
    }


def _agent_local_context_reply(message: str) -> dict | None:
    normalized = normalize(message)
    if not normalized:
        return None

    storage_reply = _agent_storage_context_reply(message)
    if storage_reply is not None:
        return storage_reply

    backup_reply = _agent_backup_local_reply(message)
    if backup_reply is not None:
        return backup_reply

    devolucao_reply = _agent_devolucao_lookup_reply(message)
    if devolucao_reply is not None:
        return devolucao_reply

    frete_card_reply = _agent_frete_card_lookup_reply(message)
    if frete_card_reply is not None:
        return frete_card_reply

    frete_status_reply = _agent_frete_status_lookup_reply(message)
    if frete_status_reply is not None:
        return frete_status_reply

    frota_reply = _agent_frota_maintenance_reply(message)
    if frota_reply is not None:
        return frota_reply

    sales_mix_reply = _agent_sales_mix_client_lookup_reply(message)
    if sales_mix_reply is not None:
        return sales_mix_reply

    sales_reply = _agent_sales_lookup_reply(message)
    if sales_reply is not None:
        return sales_reply

    broad_read_reply = _agent_broad_system_read_reply(message)
    if broad_read_reply is not None:
        return broad_read_reply

    data_reply = _agent_data_lookup_reply(message)
    if data_reply is not None:
        return data_reply

    stock_reply = _agent_stock_lookup_reply(message)
    if stock_reply is not None:
        return stock_reply

    env_reply = _agent_environment_local_reply(message)
    if env_reply is not None:
        return env_reply

    overview_reply = _agent_system_overview_reply(message)
    if overview_reply is not None:
        return overview_reply

    repo_facts = _agent_repo_facts(message)
    ctx = _agent_project_context()
    ctx["project_name"] = repo_facts.get("project_name") or ctx["project_name"]
    ctx["company_name"] = repo_facts.get("company_name") or ctx["company_name"]
    ctx["company_cnpj"] = repo_facts.get("company_cnpj") or ctx["company_cnpj"]
    ctx["internal_ip"] = repo_facts.get("internal_ip") or ctx["internal_ip"]
    ctx["public_base_url"] = repo_facts.get("public_base_url") or ctx["public_base_url"]
    ctx["server_name"] = repo_facts.get("server_name") or ctx["server_name"]
    needs_ip = any(
        phrase in normalized
        for phrase in (
            "qual meu ip",
            "qual e meu ip",
            "meu ip interno",
            "ip interno",
            "ip local",
            "endereco interno",
            "qual o ip",
        )
    )
    needs_cnpj = "cnpj" in normalized
    needs_company = any(
        phrase in normalized
        for phrase in (
            "nome da empresa",
            "razao social",
            "empresa do projeto",
            "nome do projeto",
            "qual o nome do projeto",
            "como se chama o projeto",
        )
    )

    if not (needs_ip or needs_cnpj or needs_company):
        return None

    reply_parts = []
    if needs_company:
        reply_parts.append(
            f"O projeto se chama {ctx['project_name']} e a empresa identificada no contexto e {ctx['company_name']}."
        )
    if needs_cnpj and ctx["company_cnpj"]:
        reply_parts.append(f"O CNPJ encontrado no codigo do projeto e {ctx['company_cnpj']}.")
    if needs_ip and ctx["internal_ip"]:
        reply_parts.append(f"O IP interno do ambiente e {ctx['internal_ip']}.")
    if ctx["public_base_url"] and needs_ip:
        reply_parts.append(f"A base URL publica configurada e {ctx['public_base_url']}.")

    if not reply_parts:
        return None

    result = {"reply": " ".join(reply_parts)}
    if repo_facts.get("context"):
        sources = format_repo_sources(repo_facts["context"])
        if sources and "fontes:" not in result["reply"].lower():
            result["reply"] = f"{result['reply']}\n\n{sources}"
    return result


def _agent_llm_request(messages: list[dict]) -> str | None:
    if not _agent_llm_enabled():
        return None

    provider = _agent_llm_provider()
    if provider not in {"auto", "ollama"}:
        return None

    payload = {
        "model": _agent_llm_model(),
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": _agent_llm_temperature(),
        },
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{_agent_llm_url()}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_agent_llm_timeout()) as response:
        raw = response.read().decode("utf-8", errors="replace")
    data = json.loads(raw or "{}")
    message = data.get("message") if isinstance(data, dict) else None
    if isinstance(message, dict):
        content = str(message.get("content") or "").strip()
        if content:
            return content
    return None


def _agent_llm_request_stream(messages: list[dict]):
    if not _agent_llm_enabled():
        return

    provider = _agent_llm_provider()
    if provider not in {"auto", "ollama"}:
        return

    payload = {
        "model": _agent_llm_model(),
        "messages": messages,
        "stream": True,
        "format": "json",
        "options": {
            "temperature": _agent_llm_temperature(),
        },
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{_agent_llm_url()}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    def _iter():
        with urllib.request.urlopen(request, timeout=_agent_llm_timeout()) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                message = data.get("message")
                if isinstance(message, dict):
                    chunk = str(message.get("content") or "")
                    if chunk:
                        yield {"type": "delta", "chunk": chunk}
                if data.get("done"):
                    yield {"type": "done", "raw": data}
                    return

    return _iter()


def _agent_llm_temperature() -> float:
    raw = (os.environ.get("RB_AGENT_OLLAMA_TEMPERATURE") or "0.2").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.2


def _agent_llm_parse_response(content: str) -> dict | None:
    text = (content or "").strip()
    if not text:
        return None

    candidate = text
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)

    parsed = None
    try:
        parsed = json.loads(candidate)
    except Exception:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(candidate[start : end + 1])
            except Exception:
                parsed = None

    if isinstance(parsed, dict):
        return parsed
    return {"type": "reply", "reply": text}


def _agent_llm_extract_reply_preview(content: str) -> str:
    text = content or ""
    marker = '"reply"'
    start = text.find(marker)
    if start == -1:
        return ""
    idx = start + len(marker)
    while idx < len(text) and text[idx].isspace():
        idx += 1
    if idx >= len(text) or text[idx] != ":":
        return ""
    idx += 1
    while idx < len(text) and text[idx].isspace():
        idx += 1
    if idx >= len(text) or text[idx] != '"':
        return ""
    idx += 1
    out = []
    escaped = False
    while idx < len(text):
        ch = text[idx]
        if escaped:
            if ch == "n":
                out.append("\n")
            elif ch == "t":
                out.append("\t")
            elif ch == "r":
                out.append("\r")
            elif ch == "b":
                out.append("\b")
            elif ch == "f":
                out.append("\f")
            elif ch == "u" and idx + 4 < len(text):
                hex_value = text[idx + 1:idx + 5]
                if re.fullmatch(r"[0-9a-fA-F]{4}", hex_value):
                    out.append(chr(int(hex_value, 16)))
                    idx += 4
                else:
                    out.append(ch)
            else:
                out.append(ch)
            escaped = False
        else:
            if ch == "\\":
                escaped = True
            elif ch == '"':
                break
            else:
                out.append(ch)
        idx += 1
    return "".join(out).strip()


def _agent_llm_finish_response(payload: dict, message: str, content: str) -> dict | None:
    parsed = _agent_llm_parse_response(content)
    if not parsed:
        return None

    action = str(parsed.get("action") or "").strip()
    reply = str(parsed.get("reply") or parsed.get("message") or parsed.get("content") or "").strip()

    if action:
        executed = _agent_llm_execute_action(action, parsed, message, payload)
        if executed is not None:
            return executed
        if not reply and action in OPTIONS:
            reply = option_text(action)

    if reply or parsed.get("actions"):
        explicit_actions = parsed.get("actions")
        if isinstance(explicit_actions, list):
            actions = _agent_merge_actions(explicit_actions, _suggest_agent_actions(message, reply))
        else:
            actions = _suggest_agent_actions(message, reply)
        result = {"reply": reply or "Tudo certo."}
        if actions:
            result["actions"] = actions
        workspace = parsed.get("workspace")
        if isinstance(workspace, dict):
            result["workspace"] = workspace
        return result

    return None


def _agent_llm_execute_action(action: str, parsed: dict, message: str, payload: dict) -> dict | None:
    normalized_action = str(action or "").strip()
    if not normalized_action:
        return None

    module_reply = _agent_module_context_reply(normalized_action)
    if module_reply is not None:
        return module_reply

    if normalized_action in {"kanban", "refresh_fretes"}:
        query = str(parsed.get("query") or parsed.get("filter") or "").strip()
        if not query:
            query = extract_frete_query(message)
        return list_fretes_response(query)

    if normalized_action == "list_fretes":
        query = str(parsed.get("query") or parsed.get("filter") or "").strip()
        if not query:
            query = extract_frete_query(message)
        return list_fretes_response(query)

    if normalized_action == "move_frete":
        frete_id = _as_int(parsed.get("frete_id") or payload.get("frete_id"), 0)
        status = str(parsed.get("status") or payload.get("status") or "").strip()
        if frete_id > 0 and status in FRETE_STATUS:
            updated = move_frete_status(int(frete_id), status)
            cards = list_fretes()
            return {
                "reply": f"Movi \"{updated['title']}\" para {updated['status_label']}.",
                "workspace": fretes_workspace(cards, selected_id=updated["id"]),
                "actions": [{"name": "refresh_fretes", "label": "Atualizar kanban"}],
            }
        return move_frete_prepare_response(message)

    if normalized_action == "list_devolucoes":
        return list_devolucoes_response()

    if normalized_action in OPTIONS:
        commit_message = str(
            parsed.get("commit_message")
            or payload.get("commit_message")
            or extract_commit_message(message)
            or ""
        ).strip()
        if OPTIONS[normalized_action]["needs_message"] and not commit_message:
            return {
                "reply": option_text(normalized_action) + "\n\nPara executar, preciso da mensagem do commit.",
                "actions": actions_for(normalized_action, include_secondary=False),
            }
        return run_agent(normalized_action, commit_message)

    return None


def _handle_chat_with_llm(payload: dict) -> dict | None:
    message = str(payload.get("message") or "").strip()
    if not message:
        return None
    persona_name = str(payload.get("persona_name") or "").strip()
    chat_mode = _chat_mode(payload)
    normalized = normalize(message)
    prefer_llm_first = _prefer_llm_first_for_operational_query(message, chat_mode)

    if chat_mode != "ia" and any(word in normalized for word in ["frete", "fretes", "carga", "cargas", "kanban", "devolucao", "devolucoes", "caminhao"]):
        if any(word in normalized for word in ["listar", "mostrar", "ver", "abrir", "mover", "alterar", "trocar", "lancar", "lançar", "registrar"]):
            return None

    if not prefer_llm_first:
        storage_reply = _agent_storage_context_reply(message)
        if storage_reply is not None:
            return storage_reply

        data_reply = _agent_data_lookup_reply(message)
        if data_reply is not None:
            return data_reply

        env_reply = _agent_environment_local_reply(message)
        if env_reply is not None:
            return env_reply

        overview_reply = _agent_system_overview_reply(message)
        if overview_reply is not None:
            return overview_reply

    history = _agent_llm_history_messages(payload.get("history"))
    messages = [{"role": "system", "content": _agent_llm_system_prompt(persona_name, chat_mode)}]
    env_context = _agent_environment_context_message()
    if env_context:
        messages.append({"role": "system", "content": env_context})
    repo_manifest = _agent_repo_manifest_message()
    if repo_manifest:
        messages.append({"role": "system", "content": repo_manifest})
    repo_context = _agent_repo_context_message(message)
    if repo_context:
        messages.append({"role": "system", "content": repo_context})
    messages.extend(history)
    messages.append({"role": "user", "content": message[:LLM_MAX_TOKENS]})

    try:
        content = _agent_llm_request(messages)
    except Exception:
        return None
    if not content:
        return None
    return _agent_attach_repo_sources(_agent_llm_finish_response(payload, message, content), message)


def _handle_chat_with_llm_stream(payload: dict):
    message = str(payload.get("message") or "").strip()
    if not message:
        yield {"type": "final", "reply": "Me diga o que voce quer fazer."}
        return
    persona_name = str(payload.get("persona_name") or "").strip()
    chat_mode = _chat_mode(payload)
    prefer_llm_first = _prefer_llm_first_for_operational_query(message, chat_mode)

    if _agent_web_intent(message, chat_mode):
        web_result = _agent_web_lookup_reply(message, chat_mode)
        if web_result is not None:
            yield {"type": "status", "reply": "Pesquisando na web..."}
            yield {"type": "final", **web_result}
            return
        yield {"type": "status", "reply": "Pesquisando na web..."}
        yield {"type": "final", **_web_no_answer_reply(message)}
        return

    if not prefer_llm_first:
        storage_reply = _agent_storage_context_reply(message)
        if storage_reply is not None:
            yield {"type": "status", "reply": "Pensando..."}
            yield {"type": "final", **storage_reply}
            return

        frete_status_reply = _agent_frete_status_lookup_reply(message)
        if frete_status_reply is not None:
            yield {"type": "status", "reply": "Pensando..."}
            yield {"type": "final", **frete_status_reply}
            return

        data_reply = _agent_data_lookup_reply(message)
        if data_reply is not None:
            yield {"type": "status", "reply": "Pensando..."}
            yield {"type": "final", **data_reply}
            return

        env_reply = _agent_environment_local_reply(message)
        if env_reply is not None:
            yield {"type": "status", "reply": "Pensando..."}
            yield {"type": "final", **env_reply}
            return

        overview_reply = _agent_system_overview_reply(message)
        if overview_reply is not None:
            yield {"type": "status", "reply": "Pensando..."}
            yield {"type": "final", **overview_reply}
            return

        local_reply = _agent_local_context_reply(message)
        if local_reply is not None:
            yield {"type": "status", "reply": "Pensando..."}
            yield {"type": "final", **local_reply}
            return

    history = _agent_llm_history_messages(payload.get("history"))
    messages = [{"role": "system", "content": _agent_llm_system_prompt(persona_name, chat_mode)}]
    env_context = _agent_environment_context_message()
    if env_context:
        messages.append({"role": "system", "content": env_context})
    repo_manifest = _agent_repo_manifest_message()
    if repo_manifest:
        messages.append({"role": "system", "content": repo_manifest})
    repo_context = _agent_repo_context_message(message)
    if repo_context:
        messages.append({"role": "system", "content": repo_context})
    messages.extend(history)
    messages.append({"role": "user", "content": message[:LLM_MAX_TOKENS]})

    yield {"type": "status", "reply": "Pensando..."}

    content = ""
    try:
        stream = _agent_llm_request_stream(messages)
        if stream is None:
            result = _handle_chat_with_llm(payload) or _agent_local_context_reply(message)
            if result is None:
                web_result = _agent_web_lookup_reply(message, chat_mode)
                result = web_result if web_result is not None else (_ia_no_answer_reply(message) if chat_mode == "ia" else _handle_chat_legacy(payload))
            result = _agent_attach_repo_sources(result, message)
            yield {"type": "final", **result}
            return
        for event in stream:
            if event.get("type") == "delta":
                content += str(event.get("chunk") or "")
                preview = _agent_llm_extract_reply_preview(content)
                if preview:
                    yield {"type": "delta", "reply": preview}
            elif event.get("type") == "done":
                break
    except Exception:
        result = _handle_chat_with_llm(payload) or _agent_local_context_reply(message)
        if result is None:
            web_result = _agent_web_lookup_reply(message, chat_mode)
            result = web_result if web_result is not None else (_ia_no_answer_reply(message) if chat_mode == "ia" else _handle_chat_legacy(payload))
        result = _agent_attach_repo_sources(result, message)
        yield {"type": "final", **result}
        return

    result = _agent_llm_finish_response(payload, message, content)
    if result is None:
        result = _agent_local_context_reply(message)
        if result is None:
            web_result = _agent_web_lookup_reply(message, chat_mode)
            result = web_result if web_result is not None else (_ia_no_answer_reply(message) if chat_mode == "ia" else _handle_chat_legacy(payload))
    result = _agent_attach_repo_sources(result, message)
    yield {"type": "final", **result}


def _handle_chat_legacy(payload: dict) -> dict:
    action = (payload.get("action") or "").strip()
    message = (payload.get("message") or "").strip()
    commit_message = (payload.get("commit_message") or extract_commit_message(message)).strip()

    if action:
        module_reply = _agent_module_context_reply(action)
        if module_reply is not None:
            return module_reply
        if action in {"refresh_fretes", "list_fretes"}:
            return list_fretes_response()
        if action == "list_devolucoes":
            return list_devolucoes_response()
        if action == "move_frete":
            frete_id = payload.get("frete_id")
            status = payload.get("status")
            if not frete_id or status not in FRETE_STATUS:
                return {"reply": "Faltou o frete ou o status de destino para mover o card."}
            updated = move_frete_status(int(frete_id), status)
            cards = list_fretes()
            return {
                "reply": f"Movi \"{updated['title']}\" para {updated['status_label']}.",
                "workspace": fretes_workspace(cards, selected_id=updated["id"]),
                "actions": [{"name": "refresh_fretes", "label": "Atualizar kanban"}],
            }
        if action not in OPTIONS:
            return {"reply": "Nao conheco essa acao. Pergunte 'quais opcoes existem?'."}
        if OPTIONS[action]["needs_message"] and not commit_message:
            return {
                "reply": option_text(action) + "\n\nPara executar, preciso da mensagem do commit.",
                "actions": actions_for(action, include_secondary=False),
            }
        return run_agent(action, commit_message)

    normalized = normalize(message)
    if not normalized:
        return {"reply": "Me diga o que voce quer fazer: status, backup, git, deploy, update, logs ou diagnostico."}

    if _get_pending_devolucao_confirmation() and extract_devolucao_frete_id(message):
        return create_devolucao_response(message)

    if "opcao" in normalized or "opcoes" in normalized or "ajuda" in normalized or "menu" in normalized:
        return {
            "reply": all_options_text(),
            "actions": [
                {"name": "status", "label": "Executar status"},
                {"name": "backup", "label": "Gerar backup"},
                {"name": "doctor", "label": "Rodar diagnostico", "kind": "secondary"},
            ],
        }

    if is_devolucao_message(normalized):
        if is_devolucao_create_message(normalized):
            return create_devolucao_response(message)
        if any(word in normalized for word in ["listar", "mostrar", "ver", "abrir"]):
            return list_devolucoes_response()
        return {
            "reply": (
                "Devolucoes\n\n"
                "Posso listar devolucoes ou lancar uma devolucao vinculada a um frete.\n\n"
                "Exemplos:\n"
                "- listar devolucoes\n"
                "- lancar devolucao caminhao 13 c24 2 pet2l 1 conferente Joao\n"
                "- registrar devolucao frete 137 agua sem gas 3 conferente Maria"
            ),
                "actions": [{"name": "list_devolucoes", "label": "Listar devolucoes"}],
        }

    local_reply = _agent_local_context_reply(message)
    if local_reply is not None:
        return local_reply

    frete_status_reply = _agent_frete_status_lookup_reply(message)
    if frete_status_reply is not None:
        return frete_status_reply

    if any(word in normalized for word in ["kanban", "card", "cards", "carga", "cargas", "frete", "fretes", "caminhao"]):
        if any(word in normalized for word in ["mover", "mova", "alterar", "trocar", "status"]):
            return move_frete_prepare_response(message)
        if any(word in normalized for word in ["listar", "mostrar", "ver", "abrir", "carregar"]):
            query = re.sub(r"\b(listar|mostrar|ver|abrir|carregar|agora|cargas|carga|fretes|frete|kanban|card|cards|do|da|de)\b", " ", normalized)
            query = re.sub(r"\s+", " ", query).strip()
            return list_fretes_response(query)
        return {
            "reply": (
                "Kanban / Cargas\n\n"
                "Eu posso listar os cards de frete do kanban e mover um card para outro status.\n\n"
                "Exemplos:\n"
                "- listar cargas\n"
                "- mostrar caminhao 13\n"
                "- mover status para carregado caminhao 13\n"
                "- mover frete 137 para carregando"
            ),
            "workspace": fretes_workspace(list_fretes()),
            "actions": [{"name": "refresh_fretes", "label": "Listar cards agora"}],
        }

    option = detect_option(message)
    if not option:
        return {
            "reply": (
                "Ainda nao entendi qual rotina voce quer. Posso explicar ou executar: "
                "status, backup, git, fluxo completo, deploy, update, logs, diagnostico e sync homologacao."
            ),
            "actions": [
                {"name": "status", "label": "Executar status"},
                {"name": "backup", "label": "Gerar backup"},
                {"name": "brief", "label": "Analisar pedido"},
                {"name": "logs", "label": "Ver logs", "kind": "secondary"},
            ],
        }

    if option in {"brief", "validate"}:
        return run_agent(option, message)

    if wants_execution(message):
        if option == "kanban":
            return list_fretes_response()
        if OPTIONS[option]["needs_message"] and not commit_message:
            return {
                "reply": option_text(option) + "\n\nPara executar, clique no botao e informe a mensagem do commit.",
                "actions": actions_for(option, include_secondary=True),
            }
        return run_agent(option, commit_message)

    if option == "kanban":
        return {
            "reply": (
                "Kanban / Cargas\n\n"
                "Lista os cards do kanban de fretes/cargas e permite mover status pelo comando informado. "
                "Quando voce seleciona um card, ele fica visivel acima da conversa com botoes de acao."
            ),
            "workspace": fretes_workspace(list_fretes()),
            "actions": [{"name": "refresh_fretes", "label": "Listar cards agora"}],
        }

    return {"reply": option_text(option), "actions": actions_for(option, include_secondary=True)}


def _ia_no_answer_reply(message: str) -> dict:
    return _agent_attach_repo_sources({
        "reply": (
            "Nao encontrei essa informacao de forma estruturada no sistema nem no contexto local agora. "
            "Se voce especificar o modulo, tabela, produto, rota, tela ou funcao, eu faco uma pesquisa mais direta."
        )
    }, message) or {"reply": "Nao encontrei essa informacao de forma estruturada no sistema nem no contexto local agora."}


def _web_no_answer_reply(message: str) -> dict:
    return {"reply": "Nao consegui consultar a documentacao web agora, mas mantive a pergunta no modo informativo e nao executei nenhuma rotina.\n\nFontes web: consulta externa indisponivel"}


def handle_chat(payload: dict) -> dict:
    action = (payload.get("action") or "").strip()
    chat_mode = _chat_mode(payload)
    message = str(payload.get("message") or "")
    if not action:
        if _prefer_llm_first_for_operational_query(message, chat_mode):
            llm_result = _handle_chat_with_llm(payload)
            if llm_result is not None:
                return llm_result
        local_reply = _agent_local_context_reply(message)
        if local_reply is not None:
            return local_reply
        if _agent_web_intent(message, chat_mode):
            web_result = _agent_web_lookup_reply(message, chat_mode)
            if web_result is not None:
                return web_result
            return _web_no_answer_reply(message)
        llm_result = _handle_chat_with_llm(payload)
        if llm_result is not None:
            return llm_result
        if chat_mode == "ia":
            web_result = _agent_web_lookup_reply(message, chat_mode)
            if web_result is not None:
                return web_result
            return _ia_no_answer_reply(message)
    return _handle_chat_legacy(payload)


def handle_chat_stream(payload: dict):
    action = (payload.get("action") or "").strip()
    if action:
        yield {"type": "final", **handle_chat(payload)}
        return
    yield from _handle_chat_with_llm_stream(payload)


class AgentWebHandler(BaseHTTPRequestHandler):
    server_version = "RioBrancoAgent/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[riob-agent-web] " + fmt % args + "\n")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            html_response(self)
            return
        if path == "/api/health":
            json_response(self, 200, {"ok": True})
            return
        json_response(self, 404, {"erro": "rota nao encontrada"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/chat":
            json_response(self, 404, {"erro": "rota nao encontrada"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8") or "{}")
            token = set_current_request_headers({k: v for k, v in self.headers.items()})
            try:
                json_response(self, 200, handle_chat(payload))
            finally:
                reset_current_request_headers(token)
        except subprocess.TimeoutExpired:
            json_response(self, 500, {"reply": "O comando demorou demais e foi interrompido."})
        except Exception as exc:
            json_response(self, 500, {"reply": f"Erro no assistente: {exc}"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="App web independente do RioBranco Agent.")
    parser.add_argument("--host", default="127.0.0.1", help="host do servidor local")
    parser.add_argument("--port", default=8765, type=int, help="porta do servidor local")
    parser.add_argument("--open", action="store_true", help="abre o navegador automaticamente")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), AgentWebHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"[riob-agent-web] aberto em {url}", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[riob-agent-web] encerrado", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
