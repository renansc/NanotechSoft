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


def tokens_descricao(value):
    stop = {'A', 'AO', 'AOS', 'AS', 'COM', 'DA', 'DAS', 'DE', 'DO', 'DOS', 'E', 'EM', 'O', 'OS', 'PARA', 'POR'}
    return {token for token in re.findall(r'[A-Z0-9]+', normalizar(value)) if len(token) > 1 and token not in stop}


def descricao_compativel_unica(value, product_tokens):
    source = tokens_descricao(value)
    if len(source) < 3:
        return set()
    ranked = []
    for product_id, target in product_tokens:
        common = source & target
        if len(common) >= 3:
            containment = len(common) / min(len(source), len(target))
            similarity = len(common) / len(source | target)
            if containment >= .85 and similarity >= .60:
                ranked.append((containment + similarity, product_id))
        elif len(target) == 1:
            # Cadastros manuais podem usar somente o nome tecnico do insumo,
            # enquanto o 0200/C170 acrescenta classe ou modelo. Aceita esse
            # caso apenas para uma palavra longa, inteira e unica no catalogo;
            # nomes curtos ou mais de um candidato continuam sem vinculo.
            token = next(iter(target))
            if len(token) >= 6 and token in source:
                ranked.append((1.25, product_id))
    ranked.sort(reverse=True)
    if not ranked or (len(ranked) > 1 and ranked[0][0] - ranked[1][0] < .15):
        return set()
    return {ranked[0][1]}


def tipo_embalagem(value):
    text = normalizar(value)
    if re.search(r'\b(?:ROT|ROTULO|ROTULOS|BOOB|BOOP|BOPP|SLEEVE)\b', text):
        return 'rotulo'
    if 'PREFORMA' in text:
        return 'preforma'
    if 'TAMPA' in text:
        return 'tampa'
    return ''


def embalagem_compativel(product, source_description):
    target_type = tipo_embalagem(' '.join(str(product.get(key) or '')
                                          for key in ('nome_produto', 'grupo_estoque')))
    return not target_type or tipo_embalagem(source_description) == target_type


def assinatura_rotulo(value):
    text = normalizar(value).replace(',', '.')
    if tipo_embalagem(text) != 'rotulo':
        return None
    flavors = (
        ('LARANJA', ('LARANJA',)), ('FRAMBOESA', ('FRAMBOESA',)),
        ('ABACAXI', ('ABACAXI',)), ('GUARANA', ('GUARANA',)),
        ('TUBAINA', ('TUBAINA', 'TUBARIO')), ('LIMAO', ('LIMAO', 'SODA', 'SODINHA')),
        ('UVA', ('UVA',)), ('COLA', ('COLA',)), ('CITRUS', ('CITRUS',)),
    )
    flavor = next((name for name, aliases in flavors if any(re.search(rf'\b{alias}\b', text) for alias in aliases)), '')
    volume = next((size for size in (200, 600, 2000)
                   if re.search(rf'(?<!\d){size}\s*ML\b', text)), None)
    if volume is None and re.search(r'(?<!\d)2\s*(?:L|LT|LITRO|LITROS)\b', text):
        volume = 2000
    if volume is None:
        dimension = re.search(r'(?<!\d)(\d+(?:[.,]\d+)?)\s*X\s*\d', text)
        if dimension:
            pitch = Decimal(dimension.group(1).replace(',', '.'))
            volume = next((size for expected, size in (
                (Decimal('33.5'), 2000), (Decimal('23'), 600), (Decimal('16.6'), 200)
            ) if abs(pitch - expected) <= Decimal('.2')), None)
    return (flavor, volume) if flavor and volume else None


def assinatura_preforma(value):
    text = normalizar(value).replace(',', '.')
    if tipo_embalagem(text) != 'preforma':
        return None
    color = next((name for name, aliases in (
        ('VERDE', ('VERDE',)), ('CRISTAL', ('CRISTAL', 'TRANSPARENTE')),
        ('AZUL', ('AZUL',)),
    ) if any(re.search(rf'\b{alias}\b', text) for alias in aliases)), '')
    volume = next((size for size in (200, 600, 2000)
                   if re.search(rf'(?<!\d){size}\s*ML\b', text)), None)
    if volume is None and re.search(r'(?<!\d)2\s*(?:L|LT|LITRO|LITROS)\b', text):
        volume = 2000
    if volume is None:
        weight_match = re.search(r'(?<!\d)(\d+(?:\.\d+)?)\s*(?:G|GR)\b', text)
        if weight_match:
            weight = Decimal(weight_match.group(1))
            if Decimal('14') <= weight <= Decimal('18'):
                volume = 200
            elif Decimal('20') <= weight <= Decimal('30'):
                volume = 600
            elif Decimal('38') <= weight <= Decimal('50'):
                volume = 2000
    return (color, volume) if color and volume else None


def codigo_chave(value):
    # Mesmo formato de _codigo_produto_chave do cadastro de estoque.
    raw = str(value or '').strip().upper()
    return (raw.lstrip('0') or '0') if re.fullmatch(r'\d+', raw) else re.sub(r'\s+', '', raw)


def unidade(value):
    raw = normalizar(value).replace('.', '')
    return {'KGS':'KG','QUILO':'KG','QUILOGRAMA':'KG','GR':'G','LT':'L','LTS':'L','LITRO':'L','LITROS':'L',
            'UND':'UN','UNID':'UN','UNIDADE':'UN','UNIDADES':'UN','PC':'UN','PCA':'UN','PCS':'UN','PEC':'UN',
            'MT':'M','MTS':'M','METRO':'M','METROS':'M',
            'MI':'MIL','MILH':'MIL','MILHEIRO':'MIL','TON':'T','TO':'T','TONELADA':'T',
            # Codigos 0190 confirmados nos EFD da Rio Branco. Bases antigas
            # guardaram o codigo em vez da descricao da unidade.
            '1':'KG','4':'UN','22':'SC','28':'MIL','68':'MIL','429':'MIL'}.get(raw,raw)


# Unidade normalizada -> dimensao e quantidade na unidade base (kg, litro, unidade).
UNIDADES = {'KG':('massa',Decimal(1)), 'G':('massa',Decimal('.001')),
            'T':('massa',Decimal(1000)), 'L':('volume',Decimal(1)), 'ML':('volume',Decimal('.001')),
            'M3':('volume',Decimal(1000)), 'UN':('pecas',Decimal(1)), 'MIL':('pecas',Decimal(1000))}


def fator_automatico(origem, destino):
    source, target = UNIDADES.get(unidade(origem)), UNIDADES.get(unidade(destino))
    if source and target and source[0] == target[0]:
        return source[1] / target[1]
    return None


def fator_item(purchase, item):
    """Converte a unidade da NF-e, incluindo ML usado como milheiro de pecas."""
    factor = fator_automatico(purchase['unidade_compra'], item.get('unidade'))
    descricao = normalizar(' '.join(str(purchase.get(key) or '')
                                    for key in ('descricao_xml', 'codigo_xml')))
    if (factor is None and unidade(purchase.get('unidade_compra')) == 'ML'
            and unidade(item.get('unidade')) == 'UN'
            and any(word in descricao for word in ('TAMPA', 'ROTULO', 'PREFORMA', 'GARRAFA', 'ROLHA'))):
        # Alguns fornecedores abreviam milheiro como ML, embora ML tambem seja
        # mililitro. A descricao de uma peca elimina a ambiguidade.
        return Decimal(1000)
    if (factor is None and unidade(purchase.get('unidade_compra')) == 'M'
            and unidade(item.get('unidade')) == 'UN' and tipo_embalagem(descricao) == 'rotulo'):
        dimension = re.search(r'(?<!\d)(\d+(?:[.,]\d+)?)\s*X\s*\d', descricao)
        if dimension:
            pitch_cm = Decimal(dimension.group(1).replace(',', '.'))
            if pitch_cm > 0:
                return Decimal(100) / pitch_cm
    return factor


def data_compra(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value).strip().replace('Z','+00:00'))
        return parsed.astimezone(TZ).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (ValueError, TypeError):
        return None


def carregar_compras(cur):
    """Reaproveita o mapeamento XML/estoque, inclusive apos renomear o cadastro."""
    cur.execute('SELECT id,nome_produto,codigo_barras,codigo_produto_nfe,descricao_sped,unidade,grupo_estoque,fator_embalagem_padrao FROM estoque_produtos WHERE ativo=1')
    products = cur.fetchall()
    catalog = {p['id']: p for p in products}
    product_tokens = [(p['id'], tokens_descricao(p.get('nome_produto'))) for p in products]
    compatible_descriptions = {}
    label_signatures = {}
    preform_signatures = {}
    for product in products:
        signature = assinatura_rotulo(product.get('nome_produto'))
        if signature:
            label_signatures.setdefault(signature, set()).add(product['id'])
        signature = assinatura_preforma(product.get('nome_produto'))
        if signature:
            preform_signatures.setdefault(signature, set()).add(product['id'])
    names, sped_descriptions, codes, bars = {}, {}, {}, {}
    for p in products:
        sped_key = normalizar(p.get('descricao_sped'))
        if sped_key:
            sped_descriptions.setdefault(sped_key,set()).add(p['id'])
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
        if not embalagem_compativel(product, row.get('descricao_produto')):
            continue
        conversion = None
        # Reutiliza uma capacidade ja cadastrada somente quando a unidade de
        # compra coincide com a unica apresentacao confirmada no estoque.
        capacity = Decimal(str(product.get('fator_embalagem_padrao') or 1))
        target_unit = unidade(product.get('unidade'))
        grupo = normalizar(product.get('grupo_estoque'))
        capacity_unit = ('UN' if target_unit not in UNIDADES
                         and any(word in grupo for word in ('PREFORMA','TAMPA','ROTULO','EMBALAGEM','GARRAFA'))
                         else target_unit)
        if (source_units.get(pid) == {source_unit} and capacity_unit in UNIDADES
                and fator_automatico(source_unit,capacity_unit) is None
                and capacity.is_finite() and capacity > 1):
            conversion = {'unidade':capacity_unit,'quantidade':str(capacity)}
        result.append({'produto_id':pid, 'preco':str(price), 'unidade_compra':source_unit,
                       'data_compra':date.isoformat(), 'nota':row['numero_nota'], 'fornecedor':row['emitente_nome'],
                       'compra_id':row['id'], 'origem':'XML de entrada no estoque', 'vinculo':linkage,
                       'fonte':'nfe', 'prioridade':2,
                       'codigo_xml':row.get('codigo_produto'), 'descricao_xml':row.get('descricao_produto'),
                       'conversao_estoque':conversion})

    cur.execute('''SELECT id,empresa_cnpj,periodo,chave_documento,numero_nota,item_numero,
        data_emissao,fornecedor_cnpj,fornecedor_nome,codigo_produto,descricao_produto,
        unidade,quantidade,valor_item,valor_desconto,cfop
        FROM custo_produto_sped_itens ORDER BY id''')
    for row in cur.fetchall():
        date = data_compra(row.get('data_emissao'))
        if not date:
            continue
        scope = (re.sub(r'\D', '', row.get('fornecedor_cnpj') or ''), codigo_chave(row.get('codigo_produto')))
        signature = (codigo_chave(row.get('codigo_produto')), normalizar(row.get('descricao_produto')))
        candidates = mappings.get(scope, set()) if all(scope) else set()
        linkage = 'Fornecedor e codigo SPED vinculados pelo estoque'
        if len(candidates) != 1:
            candidates = typed.get(codigo_chave(row.get('codigo_produto')), set())
            linkage = 'Codigo NF-e do cadastro encontrado no SPED'
        if len(candidates) != 1 and all(signature) and signature in descriptions:
            candidates = descriptions[signature]
            linkage = 'Codigo e descricao SPED vinculados pelo estoque'
        description_key = normalizar(row.get('descricao_produto'))
        if len(candidates) != 1 and description_key in sped_descriptions:
            candidates = sped_descriptions[description_key]
            linkage = 'Descricao SPED informada no cadastro do produto'
            if len(candidates) != 1:
                # O cadastro/API impede duplicidade. Se houver legado alterado
                # diretamente no banco, nao escolha um produto por heuristica.
                continue
        if len(candidates) != 1:
            candidates = names.get(normalizar(row.get('descricao_produto')), set())
            linkage = 'Descricao SPED correspondente ao cadastro'
        if len(candidates) != 1:
            description_key = normalizar(row.get('descricao_produto'))
            if description_key not in compatible_descriptions:
                compatible_descriptions[description_key] = descricao_compativel_unica(description_key, product_tokens)
            candidates = compatible_descriptions[description_key]
            linkage = 'Descricao SPED compativel e nao ambigua com o cadastro manual'
        if len(candidates) != 1:
            candidates = label_signatures.get(assinatura_rotulo(row.get('descricao_produto')), set())
            linkage = 'Rotulo SPED vinculado por sabor e volume sem ambiguidade'
        if len(candidates) != 1:
            candidates = preform_signatures.get(assinatura_preforma(row.get('descricao_produto')), set())
            linkage = 'Preforma SPED vinculada por cor e apresentacao sem ambiguidade'
        if len(candidates) != 1:
            continue
        try:
            quantity = Decimal(str(row.get('quantidade')))
            value = Decimal(str(row.get('valor_item')))
            discount = Decimal(str(row.get('valor_desconto') or 0))
            price = (value - discount) / quantity
            if not quantity.is_finite() or quantity <= 0 or not price.is_finite() or price < 0:
                continue
        except (InvalidOperation, TypeError, ZeroDivisionError):
            continue
        pid = next(iter(candidates))
        if not embalagem_compativel(catalog[pid], row.get('descricao_produto')):
            continue
        source_unit = unidade(row.get('unidade'))
        result.append({'produto_id':pid, 'preco':str(price), 'unidade_compra':source_unit,
                       'data_compra':date.isoformat(), 'nota':row.get('numero_nota'),
                       'fornecedor':row.get('fornecedor_nome'), 'compra_id':row['id'],
                       'origem':'SPED Fiscal', 'vinculo':linkage, 'fonte':'sped', 'prioridade':1,
                       'codigo_xml':row.get('codigo_produto'), 'descricao_xml':row.get('descricao_produto'),
                       'cfop':row.get('cfop'), 'periodo_sped':row.get('periodo'),
                       'conversao_estoque':None})
    return result


def ultimas_compras(history, reference):
    result = {}
    for row in history:
        date = data_compra(row['data_compra'])
        if not date or date.date() > reference: continue
        key = row['produto_id']
        previous = result.get(key)
        order = (date, int(row.get('prioridade') or 0), row['compra_id'])
        previous_order = ((data_compra(previous['data_compra']), int(previous.get('prioridade') or 0), previous['compra_id'])
                          if previous else None)
        if previous is None or order > previous_order:
            result[key] = row
    return result


def precificar_item(item, purchases):
    """Usa a NF-e elegivel e, enquanto ela nao existe, o valor provisorio autorizado."""
    out = {**item,'preco_unitario':None,'compra':None,'pendencia_preco':'','fonte_preco':None}
    try:
        provisional = Decimal(str(item.get('preco_provisorio')))
        if not provisional.is_finite() or provisional <= 0: provisional = None
    except (InvalidOperation,TypeError):
        provisional = None

    def fallback(message):
        if provisional is None:
            out['pendencia_preco'] = message
        else:
            out['preco_unitario'] = str(provisional)
            out['fonte_preco'] = 'provisorio'
            out['aviso_preco'] = message
        return out

    purchase = purchases.get(item.get('produto_id'))
    if not purchase:
        return fallback('Sem compra de fornecedor vinculada ao produto.')
    out['compra'] = {k:v for k,v in purchase.items() if k not in {'produto_id','preco','prioridade'}}
    out['compra']['preco_compra'] = purchase['preco']
    factor = fator_item(purchase, item)
    if factor is None and (not item.get('unidade_compra')
                           or unidade(item.get('unidade_compra')) == purchase['unidade_compra']):
        try:
            factor = Decimal(str(item.get('fator_compra')))
            if not factor.is_finite() or factor <= 0: factor = None
        except (InvalidOperation,TypeError): factor = None
        if factor is not None and not item.get('unidade_compra'):
            out['unidade_compra'] = purchase['unidade_compra']
    if factor is None and not item.get('fator_compra') and purchase.get('conversao_estoque'):
        conversion = purchase['conversao_estoque']
        target_factor = fator_automatico(conversion['unidade'],item.get('unidade'))
        if target_factor is not None:
            factor = Decimal(conversion['quantidade']) * target_factor
    if factor is None:
        return fallback(f"Informe a quantidade em {item.get('unidade')} por {purchase['unidade_compra'] or 'unidade de compra'} da nota.")
    price = Decimal(purchase['preco'])
    if price <= 0:
        return fallback('Ultima compra sem preco positivo; revise a nota.')
    out['preco_unitario'] = str(price / factor)
    out['fator_aplicado'] = str(factor)
    out['fonte_preco'] = 'sped' if purchase.get('fonte') == 'sped' else 'nfe'
    return out
