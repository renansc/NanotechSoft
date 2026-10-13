"""Carteira atual por vendedor, importada de PDF com conferencia explicita."""
import io
import json
import re
import unicodedata
from flask import Blueprint, jsonify, request
from pypdf import PdfReader

RESOURCE = 'vendas_pdvs'
MAX_BYTES = 10 * 1024 * 1024
MIX_TYPES = {'mix_embalagens', 'mixembalagens', 'tipos_embalagem', 'tipo_embalagem_pdv',
             'embalagens_mix', 'grupos_embalagem', 'gruposembalagem', 'dashboard_vendas', 'dashboard_vendas_painel'}


def ensure_pdvs_schema(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS vendas_pdvs_importacoes (
        id BIGINT AUTO_INCREMENT PRIMARY KEY, arquivo VARCHAR(255) NOT NULL,
        pdf MEDIUMBLOB NOT NULL, alteracoes LONGTEXT NOT NULL, usuario VARCHAR(180) NOT NULL,
        criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
    cur.execute('''CREATE TABLE IF NOT EXISTS vendas_pdvs_totais (
        vendedor_codigo VARCHAR(30) PRIMARY KEY, vendedor_key VARCHAR(255) NOT NULL,
        total INT UNSIGNED NOT NULL,
        importacao_id BIGINT NOT NULL, atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')


def ler_totais(connect):
    conn = connect(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT vendedor_key,total,importacao_id,atualizado_em FROM vendas_pdvs_totais ORDER BY vendedor_key')
        return cur.fetchall() or []
    finally:
        cur.close(); conn.close()


def revisao(connect):
    return tuple((r['vendedor_key'], r['total'], r['importacao_id']) for r in ler_totais(connect))


def identidade(key):
    match = re.match(r'^(\d+)\s*-', str(key).strip())
    return str(int(match[1])) if match else str(key).upper()


def base_carteira(totais, vendedores, filtro=''):
    saved = {identidade(r['vendedor_key']): int(r['total']) for r in totais}
    required = {identidade(v['chave']): v['chave'] for v in vendedores}
    required.update({identidade(r['vendedor_key']): r['vendedor_key'] for r in totais})
    if filtro:
        required = {identidade(filtro): filtro}
    missing = sorted(required[k] for k in required if k not in saved)
    total = None if missing or not required else sum(saved[k] for k in required)
    return total, missing


def resumo_carteira(totais, vendedores, filtro=''):
    """Separa o total importado da carteira completa usada como denominador.

    A soma parcial continua visivel, mas ``total_carteira`` fica nulo enquanto
    faltar qualquer vendedor do escopo. Codigos equivalentes sao deduplicados
    para que variacoes de grafia do nome nao somem a mesma carteira duas vezes.
    """
    totais = list(totais or [])
    vendedores = list(vendedores or [])
    salvos = {
        identidade(row.get('vendedor_key')): int(row.get('total') or 0)
        for row in totais
        if isinstance(row, dict) and row.get('vendedor_key') not in (None, '')
    }
    filtro_id = identidade(filtro) if filtro else ''
    if filtro_id:
        total_importado = salvos.get(filtro_id)
    else:
        total_importado = sum(salvos.values()) if salvos else None
    total_carteira, faltantes = base_carteira(totais, vendedores, filtro)
    return {
        'total_carteira': total_carteira,
        'total_carteira_importada': total_importado,
        'carteiras_pendentes': faltantes,
    }


def normalizar(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', str(value or ''))
                           if not unicodedata.combining(c)).upper().split())


def interpretar_texto(text, vendedores):
    """Reconhece a coluna Total Clientes do relatorio de cobertura por vendedor.

    Nunca conta clientes ou usa o ultimo numero de uma linha com varias colunas.
    A selecao do vendedor e a quantidade sao conferidas pelo operador.
    """
    if 'COBERTURA' not in normalizar(text) or 'C/COMPRA' not in normalizar(text):
        raise ValueError('Use o relatorio COBERTURA VENDEDOR/SUPERV., com Total Clientes e Clientes C/Compra.')
    candidates = []
    by_code = {identidade(v['chave']): v for v in vendedores}
    integer = r'(\d{1,3}(?:\.\d{3})+|\d+)'
    row_pattern = r'^\s*(\d+)\s+(.+?)\s{2,}' + integer + r'\s+' + integer + r'\s+' + integer + r'\s+\d+[,.]\d+'
    for raw in text.splitlines():
        match = re.match(row_pattern, raw)
        if not match:
            continue
        code, name, total, bought, negative = match.groups()
        seller = by_code.get(str(int(code)))
        if not seller:
            continue  # Linhas de cidades nao correspondem aos codigos de vendedores.
        total, bought, negative = [int(n.replace('.', '')) for n in (total, bought, negative)]
        if total != bought + negative:
            raise ValueError('Total inconsistente na linha de ' + name.strip())
        candidates.append({'vendedor_key': seller['chave'], 'total': total,
                           'com_compra_pdf': bought, 'origem': raw.strip()})
    if not candidates:
        raise ValueError('Nenhum codigo de vendedor do PDF corresponde a base de vendas.')
    return candidates


def validar_itens(items, vendedores):
    allowed = {v['chave'].upper(): v['chave'].upper() for v in vendedores}
    if not isinstance(items, list) or not 1 <= len(items) <= 500:
        raise ValueError('Confira de 1 a 500 vendedores.')
    result = []; seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Linha invalida.')
        key = str(item.get('vendedor_key') or '').upper()
        total = item.get('total')
        if key not in allowed:
            raise ValueError('Selecione um vendedor da base de vendas.')
        if identidade(key) in seen:
            raise ValueError('Vendedor repetido: mantenha uma unica linha com seu total.')
        if isinstance(total, bool) or not re.fullmatch(r'\d+', str(total)) or not 0 <= int(total) <= 10000000:
            raise ValueError('Informe uma quantidade inteira entre 0 e 10.000.000.')
        seen.add(identidade(key)); result.append({'vendedor_key': key, 'total': int(total)})
    return result


def ler_pdf(upload):
    if not upload or not upload.filename.lower().endswith('.pdf'):
        raise ValueError('Selecione um PDF.')
    data = upload.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or not data.startswith(b'%PDF-'):
        raise ValueError('Envie um PDF valido de ate 10 MB.')
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted or len(reader.pages) > 100:
            raise ValueError()
        text = '\n'.join(page.extract_text(extraction_mode='layout') or '' for page in reader.pages)
    except Exception as exc:
        raise ValueError('PDF ilegivel, protegido ou com mais de 100 paginas.') from exc
    if not text.strip():
        raise ValueError('O PDF nao contem texto selecionavel. Exporte o relatorio em PDF com texto.')
    return data, text


def register_pdvs(app, services):
    bp = Blueprint('vendas_pdvs', __name__)
    connect = services['get_conn']

    @bp.before_request
    def authorize():
        uid = request.headers.get('X-Usuario-Id', '')
        if not uid.isdigit() or int(uid) <= 0:
            return jsonify(erro='Sessao do portal necessaria.'), 401
        grants = set(request.headers.get('X-Usuario-Recursos', '').split(','))
        if request.headers.get('X-Usuario-Perfil') != 'admin' and not grants.intersection({'*', RESOURCE}):
            return jsonify(erro='Totais de PDVs nao liberados para este usuario.'), 403

    @bp.get('/api/vendas/pdvs-totais')
    def listar():
        return jsonify(totais=ler_totais(connect), vendedores=services['vendedores']())

    @bp.post('/api/vendas/pdvs-totais/conferir')
    def conferir():
        try:
            _, text = ler_pdf(request.files.get('arquivo'))
            sellers = services['vendedores']()
            return jsonify(itens=interpretar_texto(text, sellers), texto=text[:60000],
                           vendedores=sellers, totais=ler_totais(connect))
        except ValueError as exc:
            return jsonify(erro=str(exc)), 400

    @bp.post('/api/vendas/pdvs-totais')
    def salvar():
        try:
            upload = request.files.get('arquivo')
            pdf, text = ler_pdf(upload)
            sellers = services['vendedores']()
            interpretar_texto(text, sellers)
            items = validar_itens(json.loads(request.form.get('itens', 'null')), sellers)
            previous = json.loads(request.form.get('anteriores', 'null'))
            if not isinstance(previous, dict):
                raise ValueError('Reabra a conferencia antes de salvar.')
        except (ValueError, TypeError) as exc:
            return jsonify(erro=str(exc)), 400
        conn = connect(); cur = conn.cursor(dictionary=True)
        try:
            # Ordenacao e bloqueio da carteira inteira serializam importacoes concorrentes.
            cur.execute('SELECT vendedor_key,total,importacao_id FROM vendas_pdvs_totais ORDER BY vendedor_key FOR UPDATE')
            saved = {identidade(r['vendedor_key']): r for r in cur.fetchall()}
            changes = []
            for item in items:
                old = saved.get(identidade(item['vendedor_key']))
                if previous.get(old['vendedor_key'] if old else item['vendedor_key']) != (old['importacao_id'] if old else None):
                    conn.rollback()
                    return jsonify(erro='Os totais mudaram durante a conferencia. Leia o PDF novamente.'), 409
                changes.append({**item, 'anterior': old['total'] if old else None})
            cur.execute('INSERT INTO vendas_pdvs_importacoes (arquivo,pdf,alteracoes,usuario) VALUES (%s,%s,%s,%s)',
                        (upload.filename.replace('\\','/').split('/')[-1][:255], pdf, json.dumps(changes), services['actor']()[:180]))
            import_id = cur.lastrowid
            for item in items:
                cur.execute('''INSERT INTO vendas_pdvs_totais (vendedor_codigo,vendedor_key,total,importacao_id) VALUES (%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE vendedor_key=VALUES(vendedor_key),total=VALUES(total),importacao_id=VALUES(importacao_id),atualizado_em=NOW()''',
                            (identidade(item['vendedor_key']), item['vendedor_key'], item['total'], import_id))
            conn.commit()
        except Exception:
            conn.rollback(); app.logger.exception('Falha ao salvar totais de PDVs')
            return jsonify(erro='Nao foi possivel salvar. Nenhum total foi atualizado.'), 500
        finally:
            cur.close(); conn.close()
        services['invalidate']()
        return jsonify(importacao_id=import_id, atualizados=len(items))

    app.register_blueprint(bp)
