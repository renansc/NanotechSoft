"""Formulas por 1000 litros, xarope compartilhado e custos por ultima compra."""
import json
import calendar
import datetime as dt
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

from flask import Blueprint, jsonify, request
from custo_produto_compras import carregar_compras, hoje, precificar_item, ultimas_compras
from custo_diario import ensure_custo_diario_schema, register_custo_diario


def ensure_custo_produto_schema(cur):
    ensure_custo_diario_schema(cur)
    cur.execute('''CREATE TABLE IF NOT EXISTS custo_produto_formulas (
        produto_id INT PRIMARY KEY,
        volume_ml DECIMAL(12,3) NOT NULL,
        itens_json LONGTEXT NOT NULL,
        revisao INT NOT NULL DEFAULT 1,
        atualizado_por VARCHAR(180) NOT NULL,
        atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute("SHOW COLUMNS FROM custo_produto_formulas LIKE 'xarope_litros'")
    if not cur.fetchone():
        cur.execute('ALTER TABLE custo_produto_formulas ADD COLUMN xarope_litros DECIMAL(12,3) NULL')
    cur.execute('''CREATE TABLE IF NOT EXISTS custo_produto_xarope (
        id INT PRIMARY KEY, rendimento_litros DECIMAL(12,3) NULL,
        itens_json LONGTEXT NOT NULL, revisao INT NOT NULL DEFAULT 0,
        atualizado_por VARCHAR(180) NOT NULL DEFAULT '',
        atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute("INSERT IGNORE INTO custo_produto_xarope (id,itens_json) VALUES (1,'[]')")


def numero(value, campo, minimo=Decimal('0'), maximo=Decimal('999999999.999999')):
    try:
        result = Decimal(str(value).strip().replace(',', '.'))
        if (not result.is_finite() or result < minimo or result > maximo
                or result != result.quantize(Decimal('.000001'))):
            raise ValueError()
        return result
    except (ValueError, InvalidOperation):
        raise ValueError(f'{campo}: informe um numero entre {minimo} e {maximo}, com ate seis casas decimais.')


def validar_itens(entries, catalogo, minimo=0):
    if not isinstance(entries, list) or not minimo <= len(entries) <= 100:
        raise ValueError(f'Cadastre de {minimo} a 100 itens na formula.')
    items = []
    vistos = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Item da formula invalido.')
        pid = entry.get('produto_id')
        if isinstance(pid, bool) or not str(pid).isdigit() or int(pid) not in catalogo:
            raise ValueError('Selecione um produto ativo do cadastro para cada item.')
        pid = int(pid)
        if pid in vistos:
            raise ValueError('Produto repetido: consolide a quantidade em um unico item.')
        vistos.add(pid)
        nome = catalogo[pid]['nome_produto']
        unidade = str(entry.get('unidade') or '').strip().lower()
        if unidade not in {'kg', 'g', 'l', 'ml', 'un'}:
            raise ValueError('Unidade do item deve ser kg, g, l, ml ou un.')
        fator = entry.get('fator_compra')
        fator = str(numero(fator, 'Quantidade por embalagem', Decimal('.000001'))) if fator not in (None, '') else None
        items.append({'produto_id': pid, 'nome': nome, 'unidade': unidade,
                      'quantidade': str(numero(entry.get('quantidade'), f'Quantidade de {nome}', Decimal('.000001'))),
                      'fator_compra': fator, 'unidade_compra': str(entry.get('unidade_compra') or '').strip().upper()[:30]})
    return items


def litros(value, campo):
    result = numero(value, campo, Decimal('.001'), Decimal('1000000'))
    if result != result.quantize(Decimal('.001')):
        raise ValueError(f'{campo}: use ate tres casas decimais.')
    return result


def validar_formula(data, catalogo):
    if not isinstance(data, dict):
        raise ValueError('Formula invalida.')
    return (litros(data.get('volume_ml'), 'Volume da garrafa em ml'),
            validar_itens(data.get('itens'), catalogo))


def custo_itens(items):
    return sum((Decimal(i['quantidade']) * Decimal(i['preco_unitario']) for i in items), Decimal(0))


def rounded(value):
    with localcontext() as ctx:
        ctx.prec = 50
        return float(value.quantize(Decimal('.000001'), rounding=ROUND_HALF_UP))


def calcular_formula(volume, items, xarope=None, dose=0):
    with localcontext() as ctx:
        ctx.prec = 50
        adicionais = custo_itens(items)
        base = (custo_itens(xarope['itens']) * Decimal(str(dose)) / Decimal(str(xarope['rendimento_litros']))) if xarope else Decimal(0)
        total = adicionais + base
        return {'custo_1000_litros': rounded(total), 'custo_litro': rounded(total / 1000),
                'custo_unidade': rounded(total * Decimal(str(volume)) / 1000000),
                'custo_xarope': rounded(base), 'custo_itens': rounded(adicionais),
                'unidades_1000_litros': rounded(Decimal(1000000) / Decimal(str(volume))),
                'itens_sem_custo': sum(Decimal(i['preco_unitario']) == 0 for i in items + (xarope['itens'] if xarope else []))}


def volume_sugerido(produto):
    texto = ' '.join(str(produto.get(k) or '') for k in ('nome_produto', 'produto_base_nome')).upper()
    volumes = set()
    for valor, unidade in re.findall(r'(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(ML|L|LT|LITROS?)\b', texto):
        volumes.add(Decimal(valor.replace(',', '.')) * (1 if unidade == 'ML' else 1000))
    return float(next(iter(volumes))) if len(volumes) == 1 else None


def register_custo_produto(app, services):
    bp = Blueprint('custo_produto', __name__)

    @bp.before_request
    def authorize():
        if not request.headers.get('X-Usuario-Id', '').isdigit() or int(request.headers['X-Usuario-Id']) <= 0:
            return jsonify(erro='Sessao do portal necessaria.'), 401
        grants = set(request.headers.get('X-Usuario-Recursos', '').split(','))
        resource = 'custo_produto_dashboard' if request.path.endswith('/dashboard') else 'custo_produto'
        if request.headers.get('X-Usuario-Perfil') != 'admin' and not grants.intersection({'*', resource}):
            return jsonify(erro='Custo do produto nao liberado para este usuario.'), 403

    def catalogo(cur):
        cur.execute('SELECT id, nome_produto, unidade, grupo_estoque FROM estoque_produtos WHERE ativo=1 ORDER BY nome_produto,id')
        return {r['id']: r for r in cur.fetchall()}

    def itens_publicos(raw, catalog, purchases):
        items = json.loads(raw or '[]')
        for item in items:
            product = catalog.get(item.get('produto_id'))
            item['vinculo_valido'] = product is not None
            if product:
                item['nome'] = product['nome_produto']
        return [precificar_item(i, purchases) for i in items]

    def xarope_cur(cur, catalog, purchases, lock=False):
        cur.execute('SELECT * FROM custo_produto_xarope WHERE id=1' + (' FOR UPDATE' if lock else ''))
        row = cur.fetchone() or {}
        items = itens_publicos(row.get('itens_json'), catalog, purchases)
        rendimento = row.get('rendimento_litros')
        valido = bool(items and rendimento and all(i['vinculo_valido'] for i in items))
        precificado = valido and all(i['preco_unitario'] is not None for i in items)
        return {'itens': items, 'precificado': precificado, 'rendimento_litros': float(rendimento) if rendimento else None,
                'revisao': row.get('revisao', 0), 'valido': valido,
                'custo_lote': rounded(custo_itens(items)) if precificado else None,
                'custo_litro': rounded(custo_itens(items) / Decimal(str(rendimento))) if precificado else None,
                'atualizado_por': row.get('atualizado_por', ''), 'atualizado_em': str(row.get('atualizado_em') or '')}

    def products(cur, catalog, xarope, purchases, pid=None):
        cur.execute('''SELECT p.id produto_id, p.nome_produto, p.produto_base_nome, p.grupo_estoque,
            f.volume_ml, f.itens_json, f.revisao, f.atualizado_por, f.atualizado_em, f.xarope_litros
            FROM estoque_produtos p LEFT JOIN custo_produto_formulas f ON f.produto_id=p.id
            WHERE p.ativo=1 AND UPPER(TRIM(p.grupo_estoque)) IN ('PET','GFA')'''
            + (' AND p.id=%s' if pid is not None else '') + ' ORDER BY p.grupo_estoque,p.nome_produto,p.id',
            (pid,) if pid is not None else ())
        result = []
        for row in cur.fetchall():
            items = itens_publicos(row['itens_json'], catalog, purchases)
            volume = float(row['volume_ml']) if row['volume_ml'] else volume_sugerido(row)
            dose = row.get('xarope_litros')
            pendencias = []
            if not xarope['valido']: pendencias.append('Cadastre ou revise a base de xarope.')
            elif not xarope['precificado']: pendencias.append('Xarope: ha ingredientes sem preco de compra ou conversao de unidade.')
            for item in items:
                if item['pendencia_preco']: pendencias.append(item['nome'] + ': ' + item['pendencia_preco'])
            if not dose: pendencias.append('Informe os litros de xarope por 1000 litros de bebida.')
            if any(not i['vinculo_valido'] for i in items): pendencias.append('Vincule os itens a produtos ativos do cadastro.')
            result.append({'produto_id': row['produto_id'], 'nome_produto': row['nome_produto'],
                           'grupo_estoque': row['grupo_estoque'], 'volume_ml': volume,
                           'xarope_litros': float(dose) if dose else None,
                           'revisao': row['revisao'] or 0, 'itens': items, 'pendencias': pendencias,
                           'atualizado_por': row['atualizado_por'] or '', 'atualizado_em': str(row['atualizado_em'] or ''),
                           'calculo': calcular_formula(volume, items, xarope, dose) if row['revisao'] and volume and not pendencias else None})
        return result

    def compras(cur, reference=None, history=None):
        return ultimas_compras(history if history is not None else services.get('compras', carregar_compras)(cur), reference or hoje())

    def snapshot(cur, reference=None):
        catalog = catalogo(cur)
        purchases = compras(cur, reference)
        base = xarope_cur(cur, catalog, purchases)
        return {'produtos': products(cur, catalog, base, purchases),
                'insumos': [{**p, 'ultima_compra': purchases.get(p['id'])} for p in catalog.values()],
                'xarope': base, 'base_litros': 1000}

    @bp.get('/api/custo-produto/dashboard')
    def dashboard():
        today = hoje()
        try:
            year = int(request.args.get('ano', today.year))
            if not 2000 <= year <= today.year: raise ValueError()
        except (ValueError, TypeError):
            return jsonify(erro='Informe um ano entre 2000 e o ano atual.'), 400
        conn = services['get_conn'](); cur = conn.cursor(dictionary=True)
        try:
            catalog = catalogo(cur)
            history = services.get('compras', carregar_compras)(cur)
            current_prices = compras(cur, today, history)
            current_base = xarope_cur(cur, catalog, current_prices)
            current = products(cur, catalog, current_base, current_prices)
            months = []
            monthly = {p['produto_id']: [] for p in current}
            # Meses anteriores usam a formula ATUAL com precos disponiveis no fechamento.
            for month in range(1, (today.month if year == today.year else 12) + 1):
                end = min(today, dt.date(year, month, calendar.monthrange(year,month)[1]))
                key = f'{year:04d}-{month:02d}'
                months.append(key)
                prices = compras(cur, end, history)
                base = xarope_cur(cur, catalog, prices)
                for product in products(cur, catalog, base, prices):
                    monthly[product['produto_id']].append({'mes':key,'calculo':product['calculo'],'pendencias':product['pendencias']})
            return jsonify(ano=year, data_referencia=today.isoformat(), meses=months,
                metodologia='Formula atual com a ultima compra de fornecedor disponivel ate cada mes. Nao representa formulas historicas de producao.',
                produtos=[{'produto_id':p['produto_id'],'nome_produto':p['nome_produto'],'grupo_estoque':p['grupo_estoque'],
                           'volume_ml':p['volume_ml'],'atual':p['calculo'],'pendencias':p['pendencias'],
                           'mensal':monthly[p['produto_id']]} for p in current])
        finally:
            cur.close(); conn.close()

    @bp.get('/api/custo-produto')
    def listar():
        conn = services['get_conn'](); cur = conn.cursor(dictionary=True)
        try:
            return jsonify(snapshot(cur))
        finally:
            cur.close(); conn.close()

    def revisao(data, key='revisao'):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError('Reabra a formula para obter sua revisao atual.')
        return value

    @bp.put('/api/custo-produto/xarope')
    @bp.put('/api/custo-produto/<int:pid>')
    def salvar(pid=None):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(erro='Formula invalida.'), 400
        conn = services['get_conn'](); cur = conn.cursor(dictionary=True)
        try:
            revision = revisao(data)
            catalog = catalogo(cur)
            # Lock compartilhado serializa alteracoes da base e das formulas.
            purchases = compras(cur)
            base = xarope_cur(cur, catalog, purchases, lock=True)
            actor = str(services['actor']())[:180]
            if pid is None:
                if revision != base['revisao']:
                    return jsonify(erro='O xarope foi alterado por outro usuario. Cancele e reabra.'), 409
                rendimento = litros(data.get('rendimento_litros'), 'Rendimento do xarope em litros')
                items = validar_itens(data.get('itens'), catalog, minimo=1)
                cur.execute('''UPDATE custo_produto_xarope SET rendimento_litros=%s, itens_json=%s,
                    revisao=revisao+1, atualizado_por=%s, atualizado_em=CURRENT_TIMESTAMP WHERE id=1''',
                    (rendimento, json.dumps(items, ensure_ascii=False), actor))
                result = snapshot(cur)
            else:
                volume, items = validar_formula(data, catalog)
                dose = litros(data.get('xarope_litros'), 'Litros de xarope por 1000 litros de bebida')
                if not base['valido']:
                    raise ValueError('Cadastre uma base de xarope com produtos ativos antes de salvar o produto.')
                if revisao(data, 'xarope_revisao') != base['revisao']:
                    return jsonify(erro='O xarope foi alterado. Cancele e reabra para conferir o custo atual.'), 409
                cur.execute("SELECT id FROM estoque_produtos WHERE id=%s AND ativo=1 AND UPPER(TRIM(grupo_estoque)) IN ('PET','GFA') FOR UPDATE", (pid,))
                if not cur.fetchone():
                    return jsonify(erro='Produto PET ou retornavel ativo nao encontrado.'), 404
                cur.execute('SELECT revisao FROM custo_produto_formulas WHERE produto_id=%s FOR UPDATE', (pid,))
                previous = cur.fetchone()
                if revision != (previous['revisao'] if previous else 0):
                    return jsonify(erro='A formula foi alterada por outro usuario. Cancele e reabra para conferir a versao atual.'), 409
                if previous:
                    cur.execute('''UPDATE custo_produto_formulas SET volume_ml=%s, itens_json=%s, xarope_litros=%s,
                        revisao=revisao+1, atualizado_por=%s, atualizado_em=CURRENT_TIMESTAMP WHERE produto_id=%s''',
                        (volume, json.dumps(items, ensure_ascii=False), dose, actor, pid))
                else:
                    cur.execute('''INSERT INTO custo_produto_formulas
                        (produto_id,volume_ml,itens_json,xarope_litros,atualizado_por) VALUES (%s,%s,%s,%s,%s)''',
                        (pid, volume, json.dumps(items, ensure_ascii=False), dose, actor))
                result = products(cur, catalog, base, purchases, pid)[0]
            conn.commit()
            return jsonify(result)
        except ValueError as exc:
            conn.rollback()
            return jsonify(erro=str(exc)), 400
        except Exception:
            conn.rollback()
            app.logger.exception('Falha ao salvar formula de custo')
            return jsonify(erro='Nao foi possivel salvar a formula. Tente novamente.'), 500
        finally:
            conn.rollback(); cur.close(); conn.close()

    app.register_blueprint(bp)
    register_custo_diario(app, {**services, 'snapshot':snapshot})
