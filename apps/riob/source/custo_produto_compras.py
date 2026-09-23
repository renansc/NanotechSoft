"""Referencias de custo nas NF-e de fornecedores, sem alterar notas ou estoque."""
import datetime as dt
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

TZ = ZoneInfo('America/Sao_Paulo')


def hoje():
    return dt.datetime.now(TZ).date()


def normalizar(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', str(value or '')) if not unicodedata.combining(c)).upper().split())


def codigo_chave(value):
    # Mesmo formato de _codigo_produto_chave do cadastro de estoque.
    raw = str(value or '').strip().upper()
    return (raw.lstrip('0') or '0') if re.fullmatch(r'\d+', raw) else re.sub(r'\s+', '', raw)


def unidade(value):
    raw = normalizar(value).replace('.', '')
    return {'KGS':'KG','QUILO':'KG','QUILOGRAMA':'KG','GR':'G','LT':'L','LTS':'L','LITRO':'L','LITROS':'L',
            'UND':'UN','UNID':'UN','UNIDADE':'UN','UNIDADES':'UN','PC':'UN','PCA':'UN','PCS':'UN','PEC':'UN',
            'MI':'MIL','MILH':'MIL','MILHEIRO':'MIL','TON':'T','TO':'T','TONELADA':'T'}.get(raw,raw)


# Unidade normalizada -> dimensao e quantidade na unidade base (kg, litro, unidade).
UNIDADES = {'KG':('massa',Decimal(1)), 'G':('massa',Decimal('.001')),
            'T':('massa',Decimal(1000)), 'L':('volume',Decimal(1)), 'ML':('volume',Decimal('.001')),
            'M3':('volume',Decimal(1000)), 'UN':('pecas',Decimal(1)), 'MIL':('pecas',Decimal(1000))}


def fator_automatico(origem, destino):
    source, target = UNIDADES.get(unidade(origem)), UNIDADES.get(unidade(destino))
    if source and target and source[0] == target[0]:
        return source[1] / target[1]
    return None


def data_compra(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value).strip().replace('Z','+00:00'))
        return parsed.astimezone(TZ).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (ValueError, TypeError):
        return None


def carregar_compras(cur):
    """Reaproveita o mapeamento XML/estoque, inclusive apos renomear o cadastro."""
    cur.execute('SELECT id,nome_produto,codigo_barras,codigo_produto_nfe,unidade,fator_embalagem_padrao FROM estoque_produtos WHERE ativo=1')
    products = cur.fetchall()
    catalog = {p['id']: p for p in products}
    names, codes, bars = {}, {}, {}
    for p in products:
        for index, key in ((names,normalizar(p['nome_produto'])),(codes,codigo_chave(p['codigo_produto_nfe'])),(bars,normalizar(p['codigo_barras']))):
            if key: index.setdefault(key,set()).add(p['id'])
    cur.execute("SELECT produto_id,codigo_norm FROM estoque_produto_codigos WHERE ativo=1 AND origem_tipo='nfe_entrada'")
    typed = {}
    active_ids = {p['id'] for p in products}
    for row in cur.fetchall():
        if row['produto_id'] in active_ids:
            typed.setdefault(codigo_chave(row['codigo_norm']),set()).add(row['produto_id'])
    cur.execute("SELECT nota_key FROM estoque_xml_descartes WHERE status='descartado'")
    discarded = {r['nota_key'] for r in cur.fetchall()}
    cur.execute('''SELECT x.id,x.chave_nfe,x.numero_nota,x.serie,x.emitente_cnpj,x.emitente_nome,
        x.data_emissao,x.natureza_operacao,x.cfop,x.codigo_produto,x.descricao_produto,
        x.unidade,x.quantidade,x.valor_unitario,x.dados_json,
        e.nome_produto nome_confirmado,e.codigo_barras barras_confirmado,e.codigo_produto_nfe codigo_confirmado
        FROM importar_xml_estoque_itens x
        LEFT JOIN estoque_movimentos e ON e.referencia_tipo='importar_xml' AND e.referencia_id=x.id AND e.tipo_movimento='entrada'
        WHERE x.tipo_movimento='ENTRADA_ESTOQUE' AND x.padrao_detectado='ENTRADA_FORNECEDOR'
        ORDER BY x.id''')
    rows = cur.fetchall()

    def fornecedor_codigo(row):
        cnpj = re.sub(r'\D', '', row.get('emitente_cnpj') or '')
        code = codigo_chave(row.get('codigo_produto'))
        return (cnpj, code) if cnpj and code else None

    def confirmado(row):
        candidates = names.get(normalizar(row.get('nome_confirmado')),set())
        if len(candidates) != 1: candidates = bars.get(normalizar(row.get('barras_confirmado')),set())
        if len(candidates) != 1: candidates = codes.get(codigo_chave(row.get('codigo_confirmado')),set())
        return candidates

    def nota_key(row):
        return re.sub(r'\D','',row.get('chave_nfe') or '') or '|'.join(['sem-chave',row.get('emitente_cnpj') or '',row.get('numero_nota') or '',row.get('serie') or ''])

    # Notas posteriores reutilizam a escolha feita na entrada de estoque para
    # o mesmo fornecedor/codigo. Nao confundir codigos iguais de fornecedores.
    mappings, descriptions, source_units = {}, {}, {}
    for row in rows:
        if not row.get('nome_confirmado') or nota_key(row) in discarded: continue
        candidates = confirmado(row)
        scope = fornecedor_codigo(row)
        if len(candidates) == 1:
            if scope: mappings.setdefault(scope,set()).update(candidates)
            signature = (codigo_chave(row.get('codigo_produto')), normalizar(row.get('descricao_produto')))
            if all(signature): descriptions.setdefault(signature,set()).update(candidates)
            source_units.setdefault(next(iter(candidates)),set()).add(unidade(row.get('unidade')))

    result, seen = [], set()
    for row in rows:
        key = nota_key(row)
        nature = normalizar(row.get('natureza_operacao'))
        cfop = str(row.get('cfop') or '')
        venda_ordem = cfop in {'5923','6923'} and 'VENDA A ORDEM' in nature
        if key in discarded or any(word in nature for word in ('TRANSFER','DEVOL','BONIFIC','COMODATO','DOACAO')):
            continue
        if 'REMESS' in nature and not venda_ordem: continue
        if cfop[-3:] in {'910','911','912','915','916','917','918','919','920','921','922','923','924','925'} and not venda_ordem:
            continue
        date = data_compra(row.get('data_emissao'))
        if not date: continue
        candidates = set()
        if row.get('nome_confirmado'):
            candidates = confirmado(row)
            linkage = 'Entrada de estoque confirmada'
        elif fornecedor_codigo(row) in mappings:
            candidates = mappings[fornecedor_codigo(row)]
            linkage = 'Fornecedor e codigo XML vinculados pelo estoque'
        else:
            candidates = typed.get(codigo_chave(row.get('codigo_produto')),set())
            linkage = 'Codigo NF-e do cadastro'
            if len(candidates) != 1:
                signature = (codigo_chave(row.get('codigo_produto')), normalizar(row.get('descricao_produto')))
                if signature in descriptions:
                    candidates = descriptions[signature]
                    linkage = 'Codigo e descricao XML vinculados pelo estoque'
                else:
                    candidates = names.get(normalizar(row.get('descricao_produto')),set())
                    linkage = 'Descricao XML correspondente ao cadastro'
        if len(candidates) != 1: continue
        try:
            quantity = Decimal(str(row['quantidade']))
            price = Decimal(str(row['valor_unitario']))
            if not quantity.is_finite() or quantity <= 0 or not price.is_finite() or price < 0: continue
        except (InvalidOperation,TypeError): continue
        try: detail = json.loads(row.get('dados_json') or '{}')
        except (ValueError,TypeError): detail = {}
        seq = detail.get('nItem') or detail.get('item_seq') if isinstance(detail,dict) else None
        identity = (key,str(seq)) if seq else (key,str(row.get('codigo_produto')),str(row.get('descricao_produto')),str(quantity),str(price),row.get('unidade'))
        if identity in seen: continue
        seen.add(identity)
        pid = next(iter(candidates))
        source_unit = unidade(row.get('unidade'))
        product = catalog[pid]
        conversion = None
        # Reutiliza uma capacidade ja cadastrada somente quando a unidade de
        # compra coincide com a unica apresentacao confirmada no estoque.
        capacity = Decimal(str(product.get('fator_embalagem_padrao') or 1))
        target_unit = unidade(product.get('unidade'))
        if (source_units.get(pid) == {source_unit} and target_unit in UNIDADES
                and fator_automatico(source_unit,target_unit) is None
                and capacity.is_finite() and capacity > 1):
            conversion = {'unidade':target_unit,'quantidade':str(capacity)}
        result.append({'produto_id':pid, 'preco':str(price), 'unidade_compra':source_unit,
                       'data_compra':date.isoformat(), 'nota':row['numero_nota'], 'fornecedor':row['emitente_nome'],
                       'compra_id':row['id'], 'origem':'XML de entrada no estoque', 'vinculo':linkage,
                       'codigo_xml':row.get('codigo_produto'), 'descricao_xml':row.get('descricao_produto'),
                       'conversao_estoque':conversion})
    return result


def ultimas_compras(history, reference):
    result = {}
    for row in history:
        date = data_compra(row['data_compra'])
        if not date or date.date() > reference: continue
        key = row['produto_id']
        previous = result.get(key)
        if previous is None or (date, row['compra_id']) > (data_compra(previous['data_compra']),previous['compra_id']):
            result[key] = row
    return result


def precificar_item(item, purchases):
    """Nunca aceita preco enviado pelo navegador nem usa compra futura."""
    out = {**item,'preco_unitario':None,'compra':None,'pendencia_preco':''}
    purchase = purchases.get(item.get('produto_id'))
    if not purchase:
        out['pendencia_preco'] = 'Sem compra de fornecedor vinculada ao produto.'
        return out
    out['compra'] = {k:v for k,v in purchase.items() if k not in {'produto_id','preco'}}
    out['compra']['preco_compra'] = purchase['preco']
    factor = fator_automatico(purchase['unidade_compra'],item.get('unidade'))
    if factor is None and unidade(item.get('unidade_compra')) == purchase['unidade_compra']:
        try:
            factor = Decimal(str(item.get('fator_compra')))
            if not factor.is_finite() or factor <= 0: factor = None
        except (InvalidOperation,TypeError): factor = None
    if factor is None and not item.get('fator_compra') and purchase.get('conversao_estoque'):
        conversion = purchase['conversao_estoque']
        target_factor = fator_automatico(conversion['unidade'],item.get('unidade'))
        if target_factor is not None:
            factor = Decimal(conversion['quantidade']) * target_factor
    if factor is None:
        out['pendencia_preco'] = f"Informe a quantidade em {item.get('unidade')} por {purchase['unidade_compra'] or 'unidade de compra'} da nota."
        return out
    price = Decimal(purchase['preco'])
    if price <= 0:
        out['pendencia_preco'] = 'Ultima compra sem preco positivo; revise a nota.'
        return out
    out['preco_unitario'] = str(price / factor)
    out['fator_aplicado'] = str(factor)
    return out
