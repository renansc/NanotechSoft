#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Importador XML para homologação - Estoque + Abastecimentos

Reconhece automaticamente:
1) XML de estoque / NF-e comum
   - entrada de estoque por transferência interna: emitente e destinatário com mesmo nome normalizado
     ou mesma raiz de CNPJ
   - saída de estoque: emitente parece ser empresa própria e destinatário é cliente/terceiro
   - entrada de fornecedor: destinatário parece ser empresa própria e emitente é terceiro

2) XML de posto / abastecimento
   - detecta produto combustível por NCM/CFOP/comb/descANP ou texto DIESEL/GASOLINA/ETANOL
   - extrai placa, KM final, valor total, litros e combustível usado

Instalar:
    pip install flask werkzeug

Rodar:
    python3 importador_xml_homologacao.py

Acessar:
    http://127.0.0.1:5001
"""

import html
import io
import csv
import os
import re
import sqlite3
import uuid
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from unicodedata import normalize
from flask import Flask, request, redirect, url_for, render_template_string, flash, send_file, Response
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads_xml_homologacao"
DB_PATH = BASE_DIR / "homologacao_xml.sqlite3"
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = "troque-esta-chave"

EMPRESA_PADRAO_NOME = "BEBIDAS WHITE RIVER LTDA"
EMPRESA_PADRAO_RAIZ_CNPJ = "20984401"  # primeiros 8 dígitos do CNPJ


# Controle simples de progresso da importação.
# Mantido em memória para homologação/local.
IMPORT_PROGRESS = {}
IMPORT_PROGRESS_LOCK = threading.Lock()


def set_progress(job_id, **kwargs):
    with IMPORT_PROGRESS_LOCK:
        dados = IMPORT_PROGRESS.setdefault(job_id, {})
        dados.update(kwargs)


def get_progress(job_id):
    with IMPORT_PROGRESS_LOCK:
        return dict(IMPORT_PROGRESS.get(job_id, {}))



# ---------------- BANCO ----------------

def conectar():
    con = sqlite3.connect(DB_PATH, timeout=60, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA busy_timeout=60000")
    return con


def criar_banco():
    con = conectar()
    cur = con.cursor()
    cur.execute("BEGIN IMMEDIATE")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS configuracao_empresa (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        nome_empresa TEXT,
        raiz_cnpj TEXT,
        cnpjs_proprios TEXT,
        atualizado_em TEXT
    )
    """)

    cur.execute("""
    INSERT OR IGNORE INTO configuracao_empresa
    (id, nome_empresa, raiz_cnpj, cnpjs_proprios, atualizado_em)
    VALUES (1, ?, ?, ?, ?)
    """, (
        EMPRESA_PADRAO_NOME,
        EMPRESA_PADRAO_RAIZ_CNPJ,
        "20984401000130\n20984401000211",
        datetime.now().isoformat(timespec="seconds")
    ))

    cur.execute("""
    CREATE TABLE IF NOT EXISTS arquivos_importados (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome_arquivo TEXT,
        caminho TEXT,
        tipo_detectado TEXT,
        status TEXT,
        erro TEXT,
        data_upload TEXT,
        data_importacao TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS estoque_itens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        arquivo_id INTEGER,
        arquivo_origem TEXT,

        tipo_movimento TEXT,
        padrao_detectado TEXT,
        motivo_classificacao TEXT,

        chave_nfe TEXT,
        numero_nota TEXT,
        serie TEXT,
        data_emissao TEXT,
        natureza_operacao TEXT,
        cfop TEXT,

        emitente_cnpj TEXT,
        emitente_nome TEXT,
        destinatario_cnpj TEXT,
        destinatario_nome TEXT,

        codigo_produto TEXT,
        descricao_produto TEXT,
        ncm TEXT,
        unidade TEXT,
        quantidade REAL,
        valor_unitario REAL,
        valor_total_item REAL,
        valor_total_nota REAL,

        criado_em TEXT,
        dados_json TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS abastecimentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        arquivo_id INTEGER,
        arquivo_origem TEXT,

        posto_cnpj TEXT,
        posto_nome TEXT,
        empresa_cnpj TEXT,
        empresa_nome TEXT,

        chave_nfe TEXT,
        numero_nota TEXT,
        serie TEXT,
        data_emissao TEXT,

        placa TEXT,
        km_final REAL,
        motorista TEXT,
        combustivel TEXT,
        litros REAL,
        valor_unitario REAL,
        valor_total REAL,
        valor_produto REAL,
        desconto REAL,

        n_bico TEXT,
        n_bomba TEXT,
        n_tanque TEXT,
        encerrante_inicial REAL,
        encerrante_final REAL,

        texto_complementar TEXT,
        criado_em TEXT,
        dados_json TEXT
    )
    """)

    cur.execute("COMMIT")
    con.close()


# ---------------- UTILIDADES ----------------

def so_num(valor):
    return re.sub(r"\D", "", valor or "")


def raiz_cnpj(cnpj):
    c = so_num(cnpj)
    return c[:8] if len(c) >= 8 else c


def normalizar_nome(txt):
    txt = txt or ""
    txt = html.unescape(txt)
    txt = normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")
    txt = re.sub(r"[^A-Z0-9 ]+", " ", txt.upper())
    txt = re.sub(r"\b(LTDA|ME|EPP|EIRELI|S A|SA|COMERCIO|INDUSTRIA)\b", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def to_float(valor):
    if valor is None:
        return None
    v = str(valor).strip()
    if not v:
        return None
    v = v.replace("R$", "").replace(" ", "")
    # 3.040.335,660 -> 3040335.660
    if "," in v and "." in v:
        if v.rfind(",") > v.rfind("."):
            v = v.replace(".", "").replace(",", ".")
        else:
            v = v.replace(",", "")
    else:
        v = v.replace(",", ".")
    try:
        return float(v)
    except Exception:
        return None


def fmt_cnpj(cnpj):
    c = so_num(cnpj)
    if len(c) != 14:
        return cnpj or ""
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


def obter_config(con):
    row = con.execute("SELECT * FROM configuracao_empresa WHERE id = 1").fetchone()
    cnpjs = set()
    if row and row["cnpjs_proprios"]:
        for linha in row["cnpjs_proprios"].splitlines():
            c = so_num(linha)
            if c:
                cnpjs.add(c)
    return {
        "nome_empresa": row["nome_empresa"] if row else EMPRESA_PADRAO_NOME,
        "nome_norm": normalizar_nome(row["nome_empresa"] if row else EMPRESA_PADRAO_NOME),
        "raiz_cnpj": so_num(row["raiz_cnpj"] if row else EMPRESA_PADRAO_RAIZ_CNPJ),
        "cnpjs_proprios": cnpjs,
    }


# ---------------- XML/NFE ----------------

def tag_sem_ns(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag


def child_text(elem, tag):
    if elem is None:
        return ""
    for ch in list(elem):
        if tag_sem_ns(ch.tag) == tag:
            return (ch.text or "").strip()
    return ""


def first(root, tag):
    for elem in root.iter():
        if tag_sem_ns(elem.tag) == tag:
            return elem
    return None


def all_tags(root, tag):
    return [e for e in root.iter() if tag_sem_ns(e.tag) == tag]


def chave_nfe(root):
    inf = first(root, "infNFe")
    if inf is not None:
        chave = inf.attrib.get("Id", "").replace("NFe", "")
        if chave:
            return chave
    ch = first(root, "chNFe")
    return (ch.text or "").strip() if ch is not None else ""


def parse_nfe(path):
    root = ET.parse(path).getroot()
    ide = first(root, "ide")
    emit = first(root, "emit")
    dest = first(root, "dest")
    total = first(root, "ICMSTot")
    infadic = first(root, "infAdic")

    infcpl = child_text(infadic, "infCpl")
    infcpl = html.unescape(infcpl or "")

    cab = {
        "chave_nfe": chave_nfe(root),
        "numero_nota": child_text(ide, "nNF"),
        "serie": child_text(ide, "serie"),
        "data_emissao": child_text(ide, "dhEmi") or child_text(ide, "dEmi"),
        "natureza_operacao": child_text(ide, "natOp"),
        "tpNF": child_text(ide, "tpNF"),
        "emitente_cnpj": so_num(child_text(emit, "CNPJ") or child_text(emit, "CPF")),
        "emitente_nome": child_text(emit, "xNome"),
        "destinatario_cnpj": so_num(child_text(dest, "CNPJ") or child_text(dest, "CPF")),
        "destinatario_nome": child_text(dest, "xNome"),
        "valor_total_nota": to_float(child_text(total, "vNF")),
        "valor_produtos": to_float(child_text(total, "vProd")),
        "valor_desconto": to_float(child_text(total, "vDesc")),
        "infCpl": infcpl,
    }

    itens = []
    for det in all_tags(root, "det"):
        prod = None
        imposto = None
        for ch in list(det):
            if tag_sem_ns(ch.tag) == "prod":
                prod = ch
            elif tag_sem_ns(ch.tag) == "imposto":
                imposto = ch
        if prod is None:
            continue
        comb = None
        encerrante = None
        for e in prod.iter():
            if tag_sem_ns(e.tag) == "comb":
                comb = e
            elif tag_sem_ns(e.tag) == "encerrante":
                encerrante = e

        itens.append({
            "nItem": det.attrib.get("nItem", ""),
            "codigo_produto": child_text(prod, "cProd"),
            "descricao_produto": child_text(prod, "xProd"),
            "ncm": child_text(prod, "NCM"),
            "cfop": child_text(prod, "CFOP"),
            "unidade": child_text(prod, "uCom"),
            "quantidade": to_float(child_text(prod, "qCom")),
            "valor_unitario": to_float(child_text(prod, "vUnCom")),
            "valor_total_item": to_float(child_text(prod, "vProd")),
            "desc_anp": child_text(comb, "descANP"),
            "codigo_anp": child_text(comb, "cProdANP"),
            "n_bico": child_text(encerrante, "nBico"),
            "n_bomba": child_text(encerrante, "nBomba"),
            "n_tanque": child_text(encerrante, "nTanque"),
            "enc_ini": to_float(child_text(encerrante, "vEncIni")),
            "enc_fin": to_float(child_text(encerrante, "vEncFin")),
        })
    return cab, itens


def eh_combustivel(cab, itens):
    texto = " ".join([
        cab.get("natureza_operacao", ""),
        cab.get("infCpl", ""),
        " ".join(i.get("descricao_produto", "") for i in itens),
        " ".join(i.get("desc_anp", "") for i in itens),
    ]).upper()
    if any(p in texto for p in ["DIESEL", "GASOLINA", "ETANOL", "ARLA", "OLEO DIESEL", "COMBUST"]):
        return True
    if any(i.get("codigo_anp") or i.get("ncm") in ("27101921", "27101259", "22071090") for i in itens):
        return True
    if "PLACA" in texto and "KM" in texto:
        return True
    return False


def extrair_regex(texto, padroes):
    for p in padroes:
        m = re.search(p, texto, flags=re.I | re.S)
        if m:
            return m.group(1).strip()
    return ""


def extrair_abastecimento(cab, itens):
    texto = cab.get("infCpl", "") or ""
    texto_dec = html.unescape(texto)
    texto_limpo = re.sub(r"\s+", " ", texto_dec).strip()

    placa = extrair_regex(texto_limpo, [
        r"PLACA\s*[:\-]?\s*([A-Z]{3}[\- ]?[0-9][A-Z0-9][0-9]{2})",
        r"PLACA\s*[:\-]?\s*([A-Z0-9\-]{7,8})",
    ]).upper().replace(" ", "")

    km = extrair_regex(texto_limpo, [
        r"KM\s*[:\-]?\s*([0-9\.]+(?:,[0-9]+)?)",
        r"KM FINAL\s*[:\-]?\s*([0-9\.]+(?:,[0-9]+)?)",
    ])

    motorista = extrair_regex(texto_limpo, [
        r"MOTORISTA\s*[:\-]?\s*([^|]+)",
    ])

    enc_ini_txt = extrair_regex(texto_limpo, [
        r"Enc\.\s*Inicial\s*[:\-]?\s*([0-9\.]+(?:,[0-9]+)?)",
        r"vEncIni\s*[:\-]?\s*([0-9\.]+(?:,[0-9]+)?)",
    ])
    enc_fin_txt = extrair_regex(texto_limpo, [
        r"Enc\.\s*Final\s*[:\-]?\s*([0-9\.]+(?:,[0-9]+)?)",
        r"vEncFin\s*[:\-]?\s*([0-9\.]+(?:,[0-9]+)?)",
    ])

    item = itens[0] if itens else {}
    combustivel = item.get("desc_anp") or item.get("descricao_produto") or ""

    return {
        "posto_cnpj": cab["emitente_cnpj"],
        "posto_nome": cab["emitente_nome"],
        "empresa_cnpj": cab["destinatario_cnpj"],
        "empresa_nome": cab["destinatario_nome"],
        "chave_nfe": cab["chave_nfe"],
        "numero_nota": cab["numero_nota"],
        "serie": cab["serie"],
        "data_emissao": cab["data_emissao"],
        "placa": placa,
        "km_final": to_float(km),
        "motorista": motorista,
        "combustivel": combustivel,
        "litros": item.get("quantidade"),
        "valor_unitario": item.get("valor_unitario"),
        "valor_total": cab.get("valor_total_nota") or item.get("valor_total_item"),
        "valor_produto": item.get("valor_total_item"),
        "desconto": cab.get("valor_desconto"),
        "n_bico": item.get("n_bico") or extrair_regex(texto_limpo, [r"nBico\s*[:\-]?\s*([0-9]+)", r"Bico\s*[:\-]?\s*([0-9]+)"]),
        "n_bomba": item.get("n_bomba") or extrair_regex(texto_limpo, [r"nBomba\s*[:\-]?\s*([0-9]+)"]),
        "n_tanque": item.get("n_tanque") or extrair_regex(texto_limpo, [r"nTanque\s*[:\-]?\s*([0-9]+)"]),
        "encerrante_inicial": item.get("enc_ini") or to_float(enc_ini_txt),
        "encerrante_final": item.get("enc_fin") or to_float(enc_fin_txt),
        "texto_complementar": texto_limpo,
    }


def classificar_estoque(cab, config):
    emit_cnpj = cab["emitente_cnpj"]
    dest_cnpj = cab["destinatario_cnpj"]
    emit_nome = normalizar_nome(cab["emitente_nome"])
    dest_nome = normalizar_nome(cab["destinatario_nome"])
    empresa_nome = config["nome_norm"]
    raiz = config["raiz_cnpj"]
    cnpjs = config["cnpjs_proprios"]

    emit_proprio = emit_cnpj in cnpjs or (raiz and raiz_cnpj(emit_cnpj) == raiz) or (empresa_nome and emit_nome == empresa_nome)
    dest_proprio = dest_cnpj in cnpjs or (raiz and raiz_cnpj(dest_cnpj) == raiz) or (empresa_nome and dest_nome == empresa_nome)

    mesma_empresa_nome = emit_nome and dest_nome and emit_nome == dest_nome
    mesma_raiz = raiz_cnpj(emit_cnpj) and raiz_cnpj(emit_cnpj) == raiz_cnpj(dest_cnpj)

    if mesma_empresa_nome or mesma_raiz or (emit_proprio and dest_proprio):
        return "ENTRADA_ESTOQUE", "TRANSFERENCIA_INTERNA", "CNPJ diferente, mas nome/raiz identifica a mesma empresa. Tratado como entrada de estoque para o destino."

    if emit_proprio and not dest_proprio:
        return "SAIDA_ESTOQUE", "SAIDA_CLIENTE", "Emitente é empresa própria e destinatário é cliente/terceiro."

    if not emit_proprio and dest_proprio:
        return "ENTRADA_ESTOQUE", "ENTRADA_FORNECEDOR", "Destinatário é empresa própria e emitente é fornecedor/terceiro."

    return "INDEFINIDO", "INDEFINIDO", "Não foi possível relacionar emitente/destinatário com a empresa configurada."


# ---------------- IMPORTAÇÃO ----------------

def importar_xml(path, nome_arquivo):
    con = conectar()
    cur = con.cursor()
    config = obter_config(con)

    try:
        cab, itens = parse_nfe(path)
        tipo_detectado = "ABASTECIMENTO" if eh_combustivel(cab, itens) else "ESTOQUE"

        cur.execute("BEGIN IMMEDIATE")
        cur.execute("""
            INSERT INTO arquivos_importados
            (nome_arquivo, caminho, tipo_detectado, status, erro, data_upload, data_importacao)
            VALUES (?, ?, ?, 'PROCESSANDO', NULL, ?, ?)
        """, (nome_arquivo, str(path), tipo_detectado, datetime.now().isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds")))
        arquivo_id = cur.lastrowid

        if tipo_detectado == "ABASTECIMENTO":
            ab = extrair_abastecimento(cab, itens)
            cur.execute("""
                INSERT INTO abastecimentos (
                    arquivo_id, arquivo_origem,
                    posto_cnpj, posto_nome, empresa_cnpj, empresa_nome,
                    chave_nfe, numero_nota, serie, data_emissao,
                    placa, km_final, motorista, combustivel, litros,
                    valor_unitario, valor_total, valor_produto, desconto,
                    n_bico, n_bomba, n_tanque, encerrante_inicial, encerrante_final,
                    texto_complementar, criado_em, dados_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                arquivo_id, nome_arquivo,
                ab["posto_cnpj"], ab["posto_nome"], ab["empresa_cnpj"], ab["empresa_nome"],
                ab["chave_nfe"], ab["numero_nota"], ab["serie"], ab["data_emissao"],
                ab["placa"], ab["km_final"], ab["motorista"], ab["combustivel"], ab["litros"],
                ab["valor_unitario"], ab["valor_total"], ab["valor_produto"], ab["desconto"],
                ab["n_bico"], ab["n_bomba"], ab["n_tanque"], ab["encerrante_inicial"], ab["encerrante_final"],
                ab["texto_complementar"], datetime.now().isoformat(timespec="seconds"),
                str({"cab": cab, "itens": itens})
            ))
            total_registros = 1

        else:
            tipo_mov, padrao, motivo = classificar_estoque(cab, config)
            total_registros = 0
            for item in itens:
                cur.execute("""
                    INSERT INTO estoque_itens (
                        arquivo_id, arquivo_origem,
                        tipo_movimento, padrao_detectado, motivo_classificacao,
                        chave_nfe, numero_nota, serie, data_emissao, natureza_operacao, cfop,
                        emitente_cnpj, emitente_nome, destinatario_cnpj, destinatario_nome,
                        codigo_produto, descricao_produto, ncm, unidade, quantidade,
                        valor_unitario, valor_total_item, valor_total_nota,
                        criado_em, dados_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    arquivo_id, nome_arquivo,
                    tipo_mov, padrao, motivo,
                    cab["chave_nfe"], cab["numero_nota"], cab["serie"], cab["data_emissao"], cab["natureza_operacao"], item["cfop"],
                    cab["emitente_cnpj"], cab["emitente_nome"], cab["destinatario_cnpj"], cab["destinatario_nome"],
                    item["codigo_produto"], item["descricao_produto"], item["ncm"], item["unidade"], item["quantidade"],
                    item["valor_unitario"], item["valor_total_item"], cab["valor_total_nota"],
                    datetime.now().isoformat(timespec="seconds"), str(item)
                ))
                total_registros += 1

        cur.execute("UPDATE arquivos_importados SET status = 'IMPORTADO', erro = NULL WHERE id = ?", (arquivo_id,))
        cur.execute("COMMIT")
        return True, tipo_detectado, total_registros, ""

    except Exception as e:
        try:
            cur.execute("ROLLBACK")
        except Exception:
            pass
        return False, "ERRO", 0, str(e)
    finally:
        con.close()


# ---------------- HTML ----------------

BASE_HTML = """
<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<title>Homologação XML</title>
<style>
body { font-family: Arial, sans-serif; background:#f3f3f3; margin:30px; }
.box { background:white; padding:20px; border-radius:10px; max-width:1400px; margin:auto; }
a { color:#0b63ce; text-decoration:none; margin-right:14px; }
input, textarea, select, button { padding:8px; margin:5px 0; max-width:800px; width:100%; box-sizing:border-box; }
button { background:#0b63ce; color:white; border:0; border-radius:6px; cursor:pointer; }
table { border-collapse:collapse; width:100%; margin-top:15px; }
th, td { border:1px solid #ddd; padding:8px; font-size:14px; vertical-align:top; }
th { background:#eee; }
.msg { background:#e8f5e9; padding:10px; border-radius:6px; margin:10px 0; }
.erro { background:#ffebee; }
.badge { display:inline-block; padding:4px 7px; border-radius:5px; background:#eee; }
.abast { background:#bbdefb; }
.entrada { background:#c8e6c9; }
.saida { background:#ffe0b2; }
.grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
@media(max-width: 900px){ .grid{grid-template-columns:1fr;} }
.small { color:#555; font-size:13px; }

.progress-wrap {
    width:100%;
    max-width:800px;
    height:28px;
    background:#ddd;
    border-radius:10px;
    overflow:hidden;
    margin:12px 0;
}
.progress-bar {
    width:0%;
    height:28px;
    line-height:28px;
    text-align:center;
    color:white;
    background:linear-gradient(90deg, #0b63ce, #2d9b56);
    transition:width .35s ease;
    font-weight:bold;
}
.spinner {
    display:none;
    width:22px;
    height:22px;
    border:4px solid #ddd;
    border-top:4px solid #0b63ce;
    border-radius:50%;
    animation:spin 1s linear infinite;
    vertical-align:middle;
    margin-right:8px;
}
@keyframes spin {
    from { transform:rotate(0deg); }
    to { transform:rotate(360deg); }
}
.status-card {
    display:none;
    background:#f8f8f8;
    border:1px solid #ddd;
    border-radius:8px;
    padding:12px;
    margin-top:15px;
    max-width:850px;
}
.status-line { margin:6px 0; }
</style>
</head>
<body>
<div class="box">
<a href="/">Importar XML</a>
<a href="/estoque">Estoque</a>
<a href="/abastecimentos">Abastecimentos</a>
<a href="/arquivos">Arquivos</a>
<a href="/config">Configuração</a>
<a href="/baixar-banco">Baixar SQLite</a>
<a href="/gestoremails">GestorDeEmailsRioBranco</a>
<hr>
{% with mensagens = get_flashed_messages(with_categories=true) %}
{% if mensagens %}
{% for categoria, msg in mensagens %}
<div class="msg {{ 'erro' if categoria == 'erro' else '' }}">{{ msg }}</div>
{% endfor %}
{% endif %}
{% endwith %}
{{ conteudo|safe }}
</div>
</body>
</html>
"""


def pagina(conteudo):
    return render_template_string(BASE_HTML, conteudo=conteudo)


# ---------------- ROTAS ----------------

@app.route("/", methods=["GET", "POST"])
def index():
    # Compatibilidade com importação normal sem JavaScript.
    if request.method == "POST":
        arquivos = [a for a in request.files.getlist("xmls") if a and a.filename.lower().endswith(".xml")]
        if not arquivos:
            flash("Selecione um ou mais XMLs.", "erro")
            return redirect(url_for("index"))

        ok = erro = estoque = abast = regs = 0
        mensagens_erro = []

        for arq in arquivos:
            nome = secure_filename(arq.filename)
            caminho = UPLOAD_DIR / f"{uuid.uuid4().hex}_{nome}"
            arq.save(caminho)
            sucesso, tipo, total, msg = importar_xml(caminho, nome)
            if sucesso:
                ok += 1
                regs += total
                if tipo == "ABASTECIMENTO":
                    abast += 1
                else:
                    estoque += 1
            else:
                erro += 1
                mensagens_erro.append(f"{nome}: {msg}")

        flash(f"Importação concluída: {ok} XML(s) importado(s), {regs} registro(s), {estoque} estoque, {abast} abastecimento(s), {erro} erro(s).")
        for m in mensagens_erro[:5]:
            flash(m, "erro")
        return redirect(url_for("arquivos"))

    return pagina("""
    <h2>Importador XML para homologação</h2>
    <p>Este importador reconhece automaticamente XML de estoque e XML de posto/abastecimento.</p>

    <form id="form-importacao" method="post" enctype="multipart/form-data">
        <label>Selecione vários XMLs:</label><br>
        <input id="xmls" type="file" name="xmls" accept=".xml" multiple required><br><br>
        <button id="btn-importar" type="submit">Importar XMLs</button>
    </form>

    <div id="status-card" class="status-card">
        <div class="status-line">
            <span id="spinner" class="spinner"></span>
            <b id="status_text">Aguardando...</b>
        </div>

        <div class="progress-wrap">
            <div id="progress_bar" class="progress-bar">0%</div>
        </div>

        <div class="status-line">
            <b>Processados:</b> <span id="processed">0</span> /
            <span id="total">0</span>
        </div>

        <div class="status-line">
            <b>Arquivo atual:</b> <span id="arquivo_atual">-</span>
        </div>

        <div class="status-line">
            <b>Estoque:</b> <span id="estoque_count">0</span> |
            <b>Abastecimentos:</b> <span id="abast_count">0</span> |
            <b>Registros:</b> <span id="regs_count">0</span> |
            <b>Erros:</b> <span id="erro_count">0</span>
        </div>

        <div id="fim_links" style="display:none; margin-top:12px;">
            <a href="/arquivos">Ver arquivos importados</a>
            <a href="/estoque">Ver estoque</a>
            <a href="/abastecimentos">Ver abastecimentos</a>
        </div>
    </div>

    <p class="small">
    Para estoque: importa itens, CFOP, quantidades e valores. Para posto: extrai placa, KM final, litros, combustível e valor total.
    </p>

    <script>
    const form = document.getElementById("form-importacao");
    const btn = document.getElementById("btn-importar");
    const card = document.getElementById("status-card");
    const spinner = document.getElementById("spinner");
    const statusText = document.getElementById("status_text");
    const progressBar = document.getElementById("progress_bar");
    const processed = document.getElementById("processed");
    const total = document.getElementById("total");
    const arquivoAtual = document.getElementById("arquivo_atual");
    const estoqueCount = document.getElementById("estoque_count");
    const abastCount = document.getElementById("abast_count");
    const regsCount = document.getElementById("regs_count");
    const erroCount = document.getElementById("erro_count");
    const fimLinks = document.getElementById("fim_links");

    function atualizarTela(d) {
        const pct = d.percentual || 0;
        progressBar.style.width = pct + "%";
        progressBar.textContent = pct + "%";

        processed.textContent = d.processados || 0;
        total.textContent = d.total || 0;
        arquivoAtual.textContent = d.arquivo_atual || "-";
        estoqueCount.textContent = d.estoque || 0;
        abastCount.textContent = d.abastecimentos || 0;
        regsCount.textContent = d.registros || 0;
        erroCount.textContent = d.erros || 0;
        statusText.textContent = d.mensagem || "Processando...";

        if (d.finalizado) {
            spinner.style.display = "none";
            btn.disabled = false;
            btn.textContent = "Importar XMLs";
            fimLinks.style.display = "block";
        }
    }

    async function acompanhar(jobId) {
        const timer = setInterval(async () => {
            try {
                const resp = await fetch("/status-importacao/" + jobId);
                const data = await resp.json();
                atualizarTela(data);

                if (data.finalizado) {
                    clearInterval(timer);
                }
            } catch (e) {
                console.log(e);
            }
        }, 600);
    }

    form.addEventListener("submit", async function(e) {
        e.preventDefault();

        const files = document.getElementById("xmls").files;
        if (!files.length) {
            alert("Selecione um ou mais XMLs.");
            return;
        }

        card.style.display = "block";
        spinner.style.display = "inline-block";
        fimLinks.style.display = "none";
        btn.disabled = true;
        btn.textContent = "Importando...";
        statusText.textContent = "Enviando arquivos...";
        progressBar.style.width = "0%";
        progressBar.textContent = "0%";

        const formData = new FormData(form);

        try {
            const resp = await fetch("/importar-com-progresso", {
                method: "POST",
                body: formData
            });

            const data = await resp.json();

            if (!data.ok) {
                statusText.textContent = data.erro || "Erro ao iniciar importação.";
                spinner.style.display = "none";
                btn.disabled = false;
                btn.textContent = "Importar XMLs";
                return;
            }

            acompanhar(data.job_id);

        } catch (err) {
            statusText.textContent = "Erro ao enviar: " + err;
            spinner.style.display = "none";
            btn.disabled = false;
            btn.textContent = "Importar XMLs";
        }
    });
    </script>
    """)


@app.route("/importar-com-progresso", methods=["POST"])
def importar_com_progresso():
    arquivos = [a for a in request.files.getlist("xmls") if a and a.filename.lower().endswith(".xml")]
    if not arquivos:
        return {"ok": False, "erro": "Selecione um ou mais XMLs."}, 400

    job_id = uuid.uuid4().hex

    arquivos_salvos = []
    for arq in arquivos:
        nome = secure_filename(arq.filename)
        caminho = UPLOAD_DIR / f"{uuid.uuid4().hex}_{nome}"
        arq.save(caminho)
        arquivos_salvos.append((nome, str(caminho)))

    set_progress(
        job_id,
        total=len(arquivos_salvos),
        processados=0,
        percentual=0,
        arquivo_atual="-",
        estoque=0,
        abastecimentos=0,
        registros=0,
        erros=0,
        mensagem="Iniciando importação...",
        finalizado=False
    )

    thread = threading.Thread(
        target=processar_importacao_em_background,
        args=(job_id, arquivos_salvos),
        daemon=True
    )
    thread.start()

    return {"ok": True, "job_id": job_id}


@app.route("/status-importacao/<job_id>")
def status_importacao(job_id):
    dados = get_progress(job_id)
    if not dados:
        return {"ok": False, "erro": "Importação não encontrada."}, 404
    dados["ok"] = True
    return dados


def processar_importacao_em_background(job_id, arquivos_salvos):
    ok = erro = estoque = abast = regs = 0
    total = len(arquivos_salvos)

    for idx, (nome, caminho_str) in enumerate(arquivos_salvos, start=1):
        caminho = Path(caminho_str)

        set_progress(
            job_id,
            arquivo_atual=nome,
            mensagem=f"Importando {idx} de {total}: {nome}",
            processados=idx - 1,
            percentual=int(((idx - 1) / total) * 100) if total else 0
        )

        sucesso, tipo, total_regs, msg = importar_xml(caminho, nome)

        if sucesso:
            ok += 1
            regs += total_regs
            if tipo == "ABASTECIMENTO":
                abast += 1
            else:
                estoque += 1
        else:
            erro += 1

        set_progress(
            job_id,
            processados=idx,
            percentual=int((idx / total) * 100) if total else 100,
            estoque=estoque,
            abastecimentos=abast,
            registros=regs,
            erros=erro,
            mensagem=f"Processado {idx} de {total}"
        )

        time.sleep(0.05)

    set_progress(
        job_id,
        percentual=100,
        processados=total,
        arquivo_atual="-",
        estoque=estoque,
        abastecimentos=abast,
        registros=regs,
        erros=erro,
        mensagem=f"Importação concluída: {ok} XML(s), {regs} registro(s), {erro} erro(s).",
        finalizado=True
    )



@app.route("/config", methods=["GET", "POST"])
def config():
    con = conectar()
    if request.method == "POST":
        nome = request.form.get("nome_empresa", "")
        raiz = so_num(request.form.get("raiz_cnpj", ""))[:8]
        cnpjs = request.form.get("cnpjs_proprios", "")
        con.execute("BEGIN IMMEDIATE")
        con.execute("""
            UPDATE configuracao_empresa
            SET nome_empresa=?, raiz_cnpj=?, cnpjs_proprios=?, atualizado_em=?
            WHERE id=1
        """, (nome, raiz, cnpjs, datetime.now().isoformat(timespec="seconds")))
        con.execute("COMMIT")
        flash("Configuração salva.")
        return redirect(url_for("config"))

    row = con.execute("SELECT * FROM configuracao_empresa WHERE id=1").fetchone()
    con.close()
    return pagina(f"""
    <h2>Configuração da empresa</h2>
    <form method="post">
        <label>Nome principal da empresa</label>
        <input name="nome_empresa" value="{row['nome_empresa'] or ''}">
        <label>Raiz do CNPJ, primeiros 8 dígitos</label>
        <input name="raiz_cnpj" value="{row['raiz_cnpj'] or ''}">
        <label>CNPJs próprios, um por linha</label>
        <textarea name="cnpjs_proprios" rows="6">{row['cnpjs_proprios'] or ''}</textarea>
        <button type="submit">Salvar configuração</button>
    </form>
    """)


@app.route("/arquivos")
def arquivos():
    con = conectar()
    rows = con.execute("SELECT * FROM arquivos_importados ORDER BY id DESC LIMIT 500").fetchall()
    con.close()
    html_rows = ""
    for r in rows:
        badge = "abast" if r["tipo_detectado"] == "ABASTECIMENTO" else "entrada"
        html_rows += f"""
        <tr>
            <td>{r['id']}</td><td>{r['nome_arquivo']}</td>
            <td><span class="badge {badge}">{r['tipo_detectado']}</span></td>
            <td>{r['status']}</td><td>{r['erro'] or ''}</td><td>{r['data_importacao'] or ''}</td>
        </tr>
        """
    return pagina(f"""
    <h2>Arquivos importados</h2>
    <table><tr><th>ID</th><th>Arquivo</th><th>Tipo detectado</th><th>Status</th><th>Erro</th><th>Data</th></tr>{html_rows}</table>
    """)


@app.route("/estoque")
def estoque():
    q = request.args.get("q", "").strip()
    where = ""
    params = []
    if q:
        where = "WHERE descricao_produto LIKE ? OR codigo_produto LIKE ? OR numero_nota LIKE ? OR emitente_nome LIKE ? OR destinatario_nome LIKE ?"
        params = [f"%{q}%"] * 5
    con = conectar()
    rows = con.execute(f"""
        SELECT * FROM estoque_itens
        {where}
        ORDER BY id DESC
        LIMIT 1000
    """, params).fetchall()
    con.close()
    trs = ""
    for r in rows:
        cls = "entrada" if "ENTRADA" in (r["tipo_movimento"] or "") else "saida"
        trs += f"""
        <tr>
            <td>{r['id']}</td><td><span class="badge {cls}">{r['tipo_movimento']}</span><br>{r['padrao_detectado']}</td>
            <td>{r['numero_nota']}</td><td>{r['data_emissao']}</td>
            <td>{fmt_cnpj(r['emitente_cnpj'])}<br>{r['emitente_nome']}</td>
            <td>{fmt_cnpj(r['destinatario_cnpj'])}<br>{r['destinatario_nome']}</td>
            <td>{r['codigo_produto']}</td><td>{r['descricao_produto']}</td>
            <td>{r['cfop']}</td><td>{r['quantidade']}</td><td>{r['unidade']}</td>
            <td>{r['valor_unitario']}</td><td>{r['valor_total_item']}</td>
        </tr>
        """
    return pagina(f"""
    <h2>Itens de estoque</h2>
    <form method="get"><input name="q" value="{q}" placeholder="Buscar produto, nota, empresa..."><button type="submit">Buscar</button></form>
    <p><a href="/estoque/exportar">Exportar CSV</a></p>
    <table>
    <tr><th>ID</th><th>Movimento</th><th>Nota</th><th>Emissão</th><th>Emitente</th><th>Destinatário</th><th>Código</th><th>Produto</th><th>CFOP</th><th>Qtd</th><th>Un</th><th>Vlr Unit</th><th>Vlr Item</th></tr>
    {trs}</table>
    """)


@app.route("/abastecimentos")
def abastecimentos():
    q = request.args.get("q", "").strip()
    where = ""
    params = []
    if q:
        where = "WHERE placa LIKE ? OR posto_nome LIKE ? OR combustivel LIKE ? OR numero_nota LIKE ? OR motorista LIKE ?"
        params = [f"%{q}%"] * 5
    con = conectar()
    rows = con.execute(f"""
        SELECT * FROM abastecimentos
        {where}
        ORDER BY id DESC
        LIMIT 1000
    """, params).fetchall()
    con.close()
    trs = ""
    for r in rows:
        trs += f"""
        <tr>
            <td>{r['id']}</td><td>{r['numero_nota']}</td><td>{r['data_emissao']}</td>
            <td>{r['posto_nome']}<br>{fmt_cnpj(r['posto_cnpj'])}</td>
            <td><b>{r['placa'] or ''}</b></td><td>{r['km_final'] or ''}</td><td>{r['motorista'] or ''}</td>
            <td>{r['combustivel'] or ''}</td><td>{r['litros'] or ''}</td><td>{r['valor_unitario'] or ''}</td><td>{r['valor_total'] or ''}</td>
            <td>{r['n_bico'] or ''}</td><td>{r['encerrante_final'] or ''}</td>
        </tr>
        """
    return pagina(f"""
    <h2>Abastecimentos / XML de posto</h2>
    <form method="get"><input name="q" value="{q}" placeholder="Buscar placa, posto, combustível, nota..."><button type="submit">Buscar</button></form>
    <p><a href="/abastecimentos/exportar">Exportar CSV</a></p>
    <table>
    <tr><th>ID</th><th>Nota</th><th>Emissão</th><th>Posto</th><th>Placa</th><th>KM final</th><th>Motorista</th><th>Combustível</th><th>Litros</th><th>Vlr Unit</th><th>Valor total</th><th>Bico</th><th>Enc. final</th></tr>
    {trs}</table>
    """)


def exportar_tabela(tabela, nome):
    con = conectar()
    rows = con.execute(f"SELECT * FROM {tabela} ORDER BY id DESC").fetchall()
    con.close()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    if rows:
        writer.writerow(rows[0].keys())
        for r in rows:
            writer.writerow([r[k] for k in r.keys()])
    data = output.getvalue()
    output.close()
    return Response(data, mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={nome}.csv"})


@app.route("/estoque/exportar")
def exportar_estoque():
    return exportar_tabela("estoque_itens", "estoque_itens")


@app.route("/abastecimentos/exportar")
def exportar_abastecimentos():
    return exportar_tabela("abastecimentos", "abastecimentos")


@app.route("/baixar-banco")
def baixar_banco():
    if not DB_PATH.exists():
        flash("Banco ainda não foi criado.", "erro")
        return redirect(url_for("index"))
    return send_file(DB_PATH, as_attachment=True)

@app.route("/gestoremails")
def gestoremails():
    return redirect("/apps/riob-email/riob/")

if __name__ == "__main__":
    criar_banco()
    print("Servidor iniciado em http://127.0.0.1:5001")
    print(f"Banco SQLite: {DB_PATH}")
    # Este importador roda na porta 5001.
    # O Gestor de E-mails roda na porta 5000.
    # threaded=True é necessário para a barra consultar o progresso durante a importação.
    app.run(
        host=os.environ.get("APP_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5001")),
        debug=False,
        threaded=True,
    )
