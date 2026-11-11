"""Formulas por 1000 litros, xaropes base/compostos e custos por ultima compra."""
import datetime as dt
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

from flask import Blueprint, jsonify, request
from custo_produto_compras import carregar_compras, hoje, normalizar, precificar_item, ultimas_compras
from custo_diario import ensure_custo_diario_schema, register_custo_diario

RATEIO_CATEGORIAS = ('mao_obra', 'impostos', 'energia', 'caldeira', 'combustivel', 'agua', 'outros')
RATEIO_TIPOS = ('mensal', 'mensal_horas', 'abastecimentos', 'hora', 'litro', 'percentual')


def sabor_apresentacao(value):
    text = normalizar(value)
    flavors = (
        ('LARANJINHA', ('LARANJINHA',)),
        ('LIMAO', ('LIMAO', 'SODA')),
        ('FRAMBOESA', ('FRAMBOESA',)),
        ('ABACAXI', ('ABACAXI',)),
        ('LARANJA', ('LARANJA',)),
        ('GUARANA', ('GUARANA',)),
        ('TUBAINA', ('TUBAINA', 'TUBARIO')),
        ('CITRUS', ('CITRUS',)),
        ('ASTUBA', ('ASTUBA',)),
        ('UVA', ('UVA',)),
        ('COLA', ('COLA',)),
    )
    return next((name for name, aliases in flavors if any(re.search(rf'\b{alias}\b', text) for alias in aliases)), '')


def volume_apresentacao(value):
    text = normalizar(value).replace(',', '.')
    if re.search(r'(?<!\d)2\s*(?:L|LT|LITRO|LITROS)\b|\b6\s*X\s*2(?:\s*(?:L|LT|LITRO|LITROS))?\b', text):
        return 2000
    for volume in (600, 200):
        if re.search(rf'(?<!\d){volume}\s*ML\b', text):
            return volume
    return None


def tipo_embalagem(product):
    text = normalizar(' '.join(str(product.get(key) or '') for key in ('nome_produto', 'grupo_estoque')))
    if 'PREFORMA' in text:
        return 'preforma'
    if 'TAMPA' in text:
        return 'tampa'
    if re.search(r'\b(?:ROT|ROTULO|ROTULOS|BOOB|BOPP|BOOP|SLEEVE)\b', text):
        return 'rotulo'
    return 'outro'


def cor_embalagem(product):
    text = normalizar(product.get('nome_produto'))
    return next((color for color in ('VERDE', 'CRISTAL', 'VERMELHA', 'AMARELO', 'AZUL') if color in text), '')


def ensure_custo_produto_schema(cur):
    ensure_custo_diario_schema(cur)
    cur.execute('''CREATE TABLE IF NOT EXISTS custo_produto_formulas (
        produto_id INT PRIMARY KEY,
        volume_ml DECIMAL(12,3) NOT NULL,
        agua_quente_litros DECIMAL(12,3) NULL,
        agua_quente_valor_litro DECIMAL(18,6) NULL,
        itens_json LONGTEXT NOT NULL,
        revisao INT NOT NULL DEFAULT 1,
        atualizado_por VARCHAR(180) NOT NULL,
        atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute("SHOW COLUMNS FROM custo_produto_formulas LIKE 'xarope_litros'")
    if not cur.fetchone():
        cur.execute('ALTER TABLE custo_produto_formulas ADD COLUMN xarope_litros DECIMAL(12,3) NULL')
    for coluna, definicao in (
        ('xarope_composto_id', 'INT NULL'),
        ('agua_quente_litros', 'DECIMAL(12,3) NULL'),
        ('agua_quente_valor_litro', 'DECIMAL(18,6) NULL'),
        ('unidades_pacote', 'INT NULL'),
    ):
        cur.execute(f"SHOW COLUMNS FROM custo_produto_formulas LIKE '{coluna}'")
        if not cur.fetchone():
            cur.execute(f'ALTER TABLE custo_produto_formulas ADD COLUMN {coluna} {definicao}')
    cur.execute('''CREATE TABLE IF NOT EXISTS custo_produto_exclusoes (
        produto_id INT PRIMARY KEY,
        excluido_por VARCHAR(180) NOT NULL,
        excluido_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS custo_produto_xarope (
        id INT PRIMARY KEY, rendimento_litros DECIMAL(12,3) NULL,
        itens_json LONGTEXT NOT NULL, revisao INT NOT NULL DEFAULT 0,
        atualizado_por VARCHAR(180) NOT NULL DEFAULT '',
        atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute("INSERT IGNORE INTO custo_produto_xarope (id,itens_json) VALUES (1,'[]')")
    cur.execute('''CREATE TABLE IF NOT EXISTS custo_produto_xaropes_compostos (
        id INT AUTO_INCREMENT PRIMARY KEY, nome VARCHAR(180) NOT NULL,
        xarope_base_litros DECIMAL(12,3) NOT NULL,
        rendimento_litros DECIMAL(12,3) NOT NULL,
        dose_litros_1000 DECIMAL(12,3) NOT NULL,
        itens_json LONGTEXT NOT NULL, revisao INT NOT NULL DEFAULT 1,
        atualizado_por VARCHAR(180) NOT NULL,
        atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_custo_produto_xarope_composto_nome (nome)
    )''')
    cur.execute("SHOW COLUMNS FROM custo_produto_xaropes_compostos LIKE 'dose_litros_1000'")
    if not cur.fetchone():
        cur.execute('ALTER TABLE custo_produto_xaropes_compostos ADD COLUMN dose_litros_1000 DECIMAL(12,3) NULL AFTER rendimento_litros')
    cur.execute('''CREATE TABLE IF NOT EXISTS custo_produto_rateio (
        id TINYINT PRIMARY KEY, volume_mensal_litros DECIMAL(18,3) NULL,
        capacidade_litros_hora DECIMAL(18,3) NULL,
        horas_semanais DECIMAL(10,3) NULL DEFAULT 44,
        itens_json LONGTEXT NOT NULL, revisao INT NOT NULL DEFAULT 0,
        atualizado_por VARCHAR(180) NOT NULL DEFAULT '',
        atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute("SHOW COLUMNS FROM custo_produto_rateio LIKE 'capacidade_litros_hora'")
    if not cur.fetchone():
        cur.execute('ALTER TABLE custo_produto_rateio ADD COLUMN capacidade_litros_hora DECIMAL(18,3) NULL AFTER volume_mensal_litros')
    cur.execute("SHOW COLUMNS FROM custo_produto_rateio LIKE 'horas_semanais'")
    if not cur.fetchone():
        cur.execute('ALTER TABLE custo_produto_rateio ADD COLUMN horas_semanais DECIMAL(10,3) NULL DEFAULT 44 AFTER capacidade_litros_hora')
    cur.execute("INSERT IGNORE INTO custo_produto_rateio (id,itens_json) VALUES (1,'[]')")
    cur.execute('''CREATE TABLE IF NOT EXISTS custo_produto_sped_itens (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        identidade CHAR(64) NOT NULL,
        empresa_cnpj VARCHAR(20) NOT NULL,
        periodo CHAR(7) NOT NULL,
        chave_documento VARCHAR(60) NOT NULL DEFAULT '',
        numero_nota VARCHAR(60) NOT NULL DEFAULT '',
        item_numero VARCHAR(30) NOT NULL DEFAULT '',
        data_emissao DATE NOT NULL,
        fornecedor_cnpj VARCHAR(20) NOT NULL DEFAULT '',
        fornecedor_nome VARCHAR(255) NOT NULL DEFAULT '',
        codigo_produto VARCHAR(120) NOT NULL DEFAULT '',
        descricao_produto VARCHAR(255) NOT NULL DEFAULT '',
        unidade VARCHAR(30) NOT NULL DEFAULT '',
        quantidade DECIMAL(18,6) NOT NULL,
        valor_item DECIMAL(18,6) NOT NULL,
        valor_desconto DECIMAL(18,6) NOT NULL DEFAULT 0,
        cfop VARCHAR(10) NOT NULL DEFAULT '',
        arquivo_origem VARCHAR(255) NOT NULL DEFAULT '',
        importado_por VARCHAR(180) NOT NULL DEFAULT '',
        atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uq_custo_produto_sped_identidade (identidade),
        KEY idx_custo_produto_sped_periodo (empresa_cnpj,periodo),
        KEY idx_custo_produto_sped_produto (codigo_produto,descricao_produto),
        KEY idx_custo_produto_sped_data (data_emissao)
    )''')


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
        preco_provisorio = entry.get('preco_provisorio')
        preco_provisorio = (str(numero(preco_provisorio, f'Valor provisorio de {nome}', Decimal('.000001')))
                             if preco_provisorio not in (None, '') else None)
        items.append({'produto_id': pid, 'nome': nome, 'unidade': unidade,
                      'quantidade': str(numero(entry.get('quantidade'), f'Quantidade de {nome}', Decimal('.000001'))),
                      'fator_compra': fator, 'unidade_compra': str(entry.get('unidade_compra') or '').strip().upper()[:30],
                      'preco_provisorio': preco_provisorio})
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


def inteiro_positivo(value, campo):
    result = numero(value, campo, Decimal('1'), Decimal('1000000'))
    if result != result.quantize(Decimal('1')):
        raise ValueError(f'{campo}: informe um numero inteiro positivo.')
    return int(result)


def validar_rateio(data):
    if not isinstance(data, dict):
        raise ValueError('Configuracao de rateio invalida.')
    entries = data.get('itens')
    if not isinstance(entries, list) or len(entries) > 100:
        raise ValueError('Cadastre ate 100 custos indiretos.')
    items = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Custo indireto invalido.')
        descricao = str(entry.get('descricao') or '').strip()
        if not descricao or len(descricao) > 180:
            raise ValueError('Descricao do custo: informe um texto de ate 180 caracteres.')
        categoria = str(entry.get('categoria') or '')
        tipo = str(entry.get('tipo') or '')
        if categoria not in RATEIO_CATEGORIAS:
            raise ValueError('Categoria de custo indireto invalida.')
        if tipo not in RATEIO_TIPOS:
            raise ValueError('Forma de rateio invalida.')
        if tipo == 'abastecimentos':
            if categoria != 'combustivel':
                raise ValueError('Abastecimentos lancados devem usar a categoria Combustivel.')
            valor = Decimal(0)
        else:
            maximo = Decimal('1000') if tipo == 'percentual' else Decimal('999999999.999999')
            valor = numero(entry.get('valor'), f'Valor de {descricao}', Decimal('.000001'), maximo)
        items.append({'descricao': descricao, 'categoria': categoria, 'tipo': tipo, 'valor': str(valor)})
    volume_value = data.get('volume_mensal_litros')
    volume = litros(volume_value, 'Volume mensal de referencia') if volume_value not in (None, '') else None
    capacidade_value = data.get('capacidade_litros_hora')
    capacidade = (litros(capacidade_value, 'Capacidade produtiva por hora')
                  if capacidade_value not in (None, '') else None)
    horas_value = data.get('horas_semanais')
    horas = (numero(horas_value, 'Horas trabalhadas por semana', Decimal('.001'), Decimal('168'))
             if horas_value not in (None, '') else Decimal('44'))
    if any(item['tipo'] in {'mensal', 'abastecimentos'} for item in items) and volume is None:
        raise ValueError('Informe o volume mensal de referencia para ratear os custos mensais.')
    if any(item['tipo'] in {'hora', 'mensal_horas'} for item in items) and capacidade is None:
        raise ValueError('Informe a capacidade produtiva em litros por hora para converter os custos horarios.')
    return volume, capacidade, horas, items


def nome_xarope(value):
    nome = str(value or '').strip()
    if not nome or len(nome) > 180:
        raise ValueError('Nome do xarope composto: informe o sabor em ate 180 caracteres.')
    return nome


def validar_agua_quente(data):
    quantidade = data.get('agua_quente_litros')
    valor = data.get('agua_quente_valor_litro')
    if quantidade in (None, '') and valor in (None, ''):
        return Decimal(0), Decimal(0)
    if quantidade in (None, '') or valor in (None, ''):
        raise ValueError('Agua quente: informe a quantidade em litros e o valor por litro.')
    return (litros(quantidade, 'Quantidade de agua quente em litros'),
            numero(valor, 'Valor da agua quente por litro', Decimal('.000001')))


def custo_itens(items):
    return sum((Decimal(i['quantidade']) * Decimal(i['preco_unitario']) for i in items), Decimal(0))


def rounded(value):
    with localcontext() as ctx:
        ctx.prec = 50
        return float(value.quantize(Decimal('.000001'), rounding=ROUND_HALF_UP))


def calcular_rateio(rateio, custo_direto):
    componentes = {categoria: Decimal(0) for categoria in RATEIO_CATEGORIAS}
    if not rateio:
        return componentes
    volume = Decimal(str(rateio.get('volume_mensal_litros') or 0))
    capacidade = Decimal(str(rateio.get('capacidade_litros_hora') or 0))
    horas_semanais = Decimal(str(rateio.get('horas_semanais') or 44))
    horas_mensais = horas_semanais * Decimal(52) / Decimal(12)
    for item in rateio.get('itens') or []:
        valor = Decimal(str(item['valor']))
        if item['tipo'] in {'mensal', 'abastecimentos'}:
            parcela = valor * Decimal(1000) / volume if volume else Decimal(0)
        elif item['tipo'] == 'mensal_horas':
            parcela = (valor * Decimal(1000) / horas_mensais / capacidade
                       if horas_mensais and capacidade else Decimal(0))
        elif item['tipo'] == 'hora':
            parcela = valor * Decimal(1000) / capacidade if capacidade else Decimal(0)
        elif item['tipo'] == 'litro':
            parcela = valor * Decimal(1000)
        else:
            parcela = custo_direto * valor / Decimal(100)
        componentes[item['categoria']] += parcela
    return componentes


def calcular_formula(volume, items, xarope=None, dose=0, agua_quente_litros=0,
                     agua_quente_valor_litro=0, rateio=None, unidades_pacote=None):
    with localcontext() as ctx:
        ctx.prec = 50
        embalagem_unidade = custo_itens(items)
        lote_xarope = Decimal(str(xarope.get('custo_lote_exato', 0))) if xarope else Decimal(0)
        # A receita do sabor informa o custo do lote e quantos litros de bebida
        # pronta ele rende. O custo por 1.000 L e derivado desse rendimento; nao
        # existe uma segunda "dose" manual para multiplicar o mesmo lote.
        base = (lote_xarope * Decimal(1000) / Decimal(str(xarope['rendimento_litros']))) if xarope else Decimal(0)
        agua_quente = Decimal(str(agua_quente_litros or 0)) * Decimal(str(agua_quente_valor_litro or 0))
        escala_unidade = Decimal(str(volume)) / Decimal(1000000)
        unidades_1000 = Decimal(1) / escala_unidade
        embalagem_1000 = embalagem_unidade * unidades_1000
        direto = embalagem_1000 + base + agua_quente
        indiretos = calcular_rateio(rateio, direto)
        total_indireto = sum(indiretos.values(), Decimal(0))
        total = direto + total_indireto
        pacote = Decimal(str(unidades_pacote)) if unidades_pacote else None
        componentes_1000 = {'xarope': base, 'embalagem': embalagem_1000, 'agua_quente': agua_quente,
                            **indiretos}
        componentes_unidade = {key: rounded(value * escala_unidade)
                               for key, value in componentes_1000.items()}
        componentes_pacote = ({key: rounded(value * escala_unidade * pacote)
                               for key, value in componentes_1000.items()} if pacote else None)
        return {'custo_1000_litros': rounded(total), 'custo_litro': rounded(total / 1000),
                'custo_unidade': rounded(total * escala_unidade),
                'custo_pacote': rounded(total * escala_unidade * pacote) if pacote else None,
                'custo_1000_litros_sem_rateio': rounded(direto),
                'custo_litro_sem_rateio': rounded(direto / 1000),
                'custo_unidade_sem_rateio': rounded(direto * escala_unidade),
                'custo_pacote_sem_rateio': rounded(direto * escala_unidade * pacote) if pacote else None,
                'unidades_pacote': int(pacote) if pacote else None,
                'custo_direto_1000_litros': rounded(direto),
                'custo_indireto_1000_litros': rounded(total_indireto),
                'custo_xarope': rounded(base),
                'custo_itens': rounded(embalagem_1000),
                'custo_itens_unidade': rounded(embalagem_unidade),
                'custo_itens_1000_litros': rounded(embalagem_1000),
                'custo_agua_quente': rounded(agua_quente),
                'componentes_1000_litros': {key: rounded(value) for key, value in componentes_1000.items()},
                'componentes_unidade': componentes_unidade,
                'componentes_pacote': componentes_pacote,
                'itens_unidade': [{'produto_id': item.get('produto_id'), 'nome': item.get('nome'),
                                   'unidade': item.get('unidade'), 'quantidade': item.get('quantidade'),
                                   'preco_unitario': item.get('preco_unitario'),
                                   'custo_unidade': rounded(Decimal(item['quantidade'])
                                                            * Decimal(item['preco_unitario'])),
                                   'custo_pacote': (rounded(Decimal(item['quantidade'])
                                                             * Decimal(item['preco_unitario']) * pacote)
                                                     if pacote else None),
                                   'custo_1000_litros': rounded(Decimal(item['quantidade'])
                                                                * Decimal(item['preco_unitario']) * unidades_1000)}
                                  for item in items],
                'unidades_1000_litros': rounded(unidades_1000),
                'itens_sem_custo': (sum(Decimal(i['preco_unitario']) == 0 for i in items)
                                    + (xarope.get('itens_sem_custo', 0) if xarope else 0))}


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
        cur.execute('''SELECT id, nome_produto, produto_base_nome, descricao_sped, unidade, grupo_estoque,
            fator_embalagem_padrao FROM estoque_produtos WHERE ativo=1 ORDER BY nome_produto,id''')
        return {r['id']: r for r in cur.fetchall()}

    def itens_publicos(raw, catalog, purchases):
        items = json.loads(raw or '[]')
        for item in items:
            product = catalog.get(item.get('produto_id'))
            item['vinculo_valido'] = product is not None
            if product:
                item['nome'] = product['nome_produto']
        result = [precificar_item(i, purchases) for i in items]
        for item in result:
            item['custo_formula'] = (rounded(Decimal(str(item['quantidade']))
                                             * Decimal(str(item['preco_unitario'])))
                                     if item.get('preco_unitario') is not None else None)
        return result

    def sugestoes_pet(rows, catalog):
        def item_limpo(item, product_id=None):
            product = catalog.get(product_id or item.get('produto_id'))
            return {'produto_id': product['id'], 'nome': product['nome_produto'],
                    'unidade': item.get('unidade') or 'un', 'quantidade': item.get('quantidade') or '1',
                    'fator_compra': None, 'unidade_compra': '', 'preco_provisorio': None}

        def candidato(tipo, target_flavor, target_volume, source_product):
            candidates = []
            source_color = cor_embalagem(source_product)
            for product in catalog.values():
                if tipo_embalagem(product) != tipo or volume_apresentacao(product['nome_produto']) != target_volume:
                    continue
                if tipo == 'rotulo' and sabor_apresentacao(product['nome_produto']) != target_flavor:
                    continue
                color = cor_embalagem(product)
                color_score = 1 if source_color and color == source_color else 0
                candidates.append((color_score, product))
            if not candidates:
                return None
            candidates.sort(key=lambda entry: (entry[0], -entry[1]['id']), reverse=True)
            if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
                return None
            return candidates[0][1]

        sources = [row for row in rows if not row.get('excluido_custo')
                   and str(row.get('grupo_estoque') or '').strip().upper() == 'PET'
                   and row.get('revisao') and row.get('xarope_composto_id') and row.get('itens')]
        for target in rows:
            if target.get('excluido_custo') or target.get('revisao') or str(target.get('grupo_estoque') or '').strip().upper() != 'PET':
                continue
            target_flavor = sabor_apresentacao(target.get('nome_produto'))
            target_volume = volume_apresentacao(target.get('nome_produto')) or target.get('volume_ml')
            same_flavor = [source for source in sources
                           if sabor_apresentacao(source.get('nome_produto')) == target_flavor]
            compound_ids = {source.get('xarope_composto_id') for source in same_flavor}
            if not target_flavor or target_volume not in {200, 600, 2000} or len(compound_ids) != 1:
                continue
            source = sorted(same_flavor, key=lambda row: (row.get('revisao') or 0, row['produto_id']), reverse=True)[0]
            suggested_items = []
            valid = True
            for item in source['itens']:
                source_product = catalog.get(item.get('produto_id'))
                if not source_product:
                    valid = False
                    break
                kind = tipo_embalagem(source_product)
                if kind == 'tampa':
                    product = source_product
                elif kind == 'outro':
                    valid = False
                    break
                else:
                    product = candidato(kind, target_flavor, int(target_volume), source_product)
                if not product:
                    valid = False
                    break
                suggested_items.append(item_limpo(item, product['id']))
            if valid and suggested_items:
                target['sugestao_formula'] = {
                    'origem_produto_id': source['produto_id'],
                    'origem_produto_nome': source['nome_produto'],
                    'xarope_composto_id': source['xarope_composto_id'],
                    'xarope_composto_revisao': source.get('xarope_composto_revisao'),
                    'volume_ml': int(target_volume),
                    'unidades_pacote': target.get('unidades_pacote'),
                    'itens': suggested_items,
                }
        return rows

    def combustivel_lancado_cur(cur):
        cur.execute('''SELECT
                SUBSTR(CAST(COALESCE(data_abastecimento,data_liberacao) AS CHAR),1,7) periodo,
                COUNT(*) registros,
                COALESCE(SUM(valor),0) valor_total,
                COALESCE(SUM(quantidade_litros),0) litros_combustivel
            FROM abastecimentos
            WHERE LOWER(COALESCE(status,''))='abastecido' AND valor>0
            GROUP BY periodo ORDER BY periodo DESC LIMIT 1''')
        row = cur.fetchone() or {}
        return {'periodo': row.get('periodo') or None,
                'registros': int(row.get('registros') or 0),
                'valor_total': float(row.get('valor_total') or 0),
                'litros_combustivel': float(row.get('litros_combustivel') or 0)}

    def rateio_cur(cur, lock=False):
        cur.execute('SELECT * FROM custo_produto_rateio WHERE id=1' + (' FOR UPDATE' if lock else ''))
        row = cur.fetchone() or {}
        items = json.loads(row.get('itens_json') or '[]')
        combustivel = combustivel_lancado_cur(cur) if any(i.get('tipo') == 'abastecimentos' for i in items) else None
        if combustivel:
            for item in items:
                if item.get('tipo') == 'abastecimentos':
                    item.update({'valor': str(combustivel['valor_total']), 'automatico': True,
                                 'periodo_referencia': combustivel['periodo'],
                                 'registros_origem': combustivel['registros'],
                                 'litros_combustivel': combustivel['litros_combustivel'],
                                 'fonte': 'abastecimentos'})
        return {'volume_mensal_litros': (float(row['volume_mensal_litros'])
                                         if row.get('volume_mensal_litros') else None),
                'capacidade_litros_hora': (float(row['capacidade_litros_hora'])
                                           if row.get('capacidade_litros_hora') else None),
                'horas_semanais': (float(row['horas_semanais'])
                                    if row.get('horas_semanais') else 44),
                'itens': items,
                'combustivel_lancado': combustivel,
                'revisao': row.get('revisao', 0),
                'atualizado_por': row.get('atualizado_por', ''),
                'atualizado_em': str(row.get('atualizado_em') or '')}

    def xarope_cur(cur, catalog, purchases, lock=False):
        cur.execute('SELECT * FROM custo_produto_xarope WHERE id=1' + (' FOR UPDATE' if lock else ''))
        row = cur.fetchone() or {}
        items = itens_publicos(row.get('itens_json'), catalog, purchases)
        rendimento = row.get('rendimento_litros')
        valido = bool(items and rendimento and all(i['vinculo_valido'] for i in items))
        precificado = valido and all(i['preco_unitario'] is not None for i in items)
        lote = custo_itens(items) if precificado else None
        return {'itens': items, 'precificado': precificado, 'rendimento_litros': float(rendimento) if rendimento else None,
                'revisao': row.get('revisao', 0), 'valido': valido,
                'custo_lote': rounded(lote) if lote is not None else None,
                'custo_lote_exato': str(lote) if lote is not None else None,
                'custo_litro': rounded(lote / Decimal(str(rendimento))) if lote is not None else None,
                'itens_sem_custo': sum(Decimal(i['preco_unitario']) == 0 for i in items if i['preco_unitario'] is not None),
                'atualizado_por': row.get('atualizado_por', ''), 'atualizado_em': str(row.get('atualizado_em') or '')}

    def xaropes_compostos_cur(cur, catalog, purchases, base, cid=None, lock=False):
        sql = 'SELECT * FROM custo_produto_xaropes_compostos'
        args = ()
        if cid is not None:
            sql += ' WHERE id=%s'; args = (cid,)
        sql += ' ORDER BY nome,id'
        if lock: sql += ' FOR UPDATE'
        cur.execute(sql, args)
        result = []
        for row in cur.fetchall():
            items = itens_publicos(row.get('itens_json'), catalog, purchases)
            rendimento = row.get('rendimento_litros')
            base_litros = row.get('xarope_base_litros')
            vinculos = all(i['vinculo_valido'] for i in items)
            valido = bool(row.get('nome') and items and rendimento and base_litros and base['valido'] and vinculos)
            precificado = valido and base['precificado'] and all(i['preco_unitario'] is not None for i in items)
            base_por_1000 = (Decimal(str(base_litros)) * Decimal(1000) / Decimal(str(rendimento))
                             if base_litros and rendimento else None)
            lote = None
            custo_base_lote = None
            custo_sabor_lote = None
            if precificado:
                custo_base_lote = (Decimal(base['custo_lote_exato']) * Decimal(str(base_litros))
                                    / Decimal(str(base['rendimento_litros'])))
                custo_sabor_lote = custo_itens(items)
                lote = custo_base_lote + custo_sabor_lote
            pendencias = []
            if not base['valido']: pendencias.append('Cadastre ou revise o xarope base.')
            elif not base['precificado']: pendencias.append('Xarope base com ingrediente sem preco ou conversao.')
            if not items: pendencias.append('Informe os ingredientes do sabor.')
            if not vinculos: pendencias.append('Vincule os ingredientes a produtos ativos.')
            for item in items:
                if item['pendencia_preco']: pendencias.append(item['nome'] + ': ' + item['pendencia_preco'])
            result.append({'id': row['id'], 'nome': row['nome'], 'xarope_base_litros': float(base_litros),
                           'rendimento_litros': float(rendimento),
                           'rendimento_bebida_litros': float(rendimento),
                           'xarope_base_litros_1000': rounded(base_por_1000) if base_por_1000 else None,
                           # Compatibilidade: o campo antigo passa a expor a
                           # proporcao derivada de base, nunca a dose digitada.
                           'dose_litros_1000': rounded(base_por_1000) if base_por_1000 else None,
                           'itens': items,
                           'revisao': row.get('revisao', 0), 'valido': valido, 'precificado': precificado,
                           'custo_lote': rounded(lote) if lote is not None else None,
                           'custo_lote_exato': str(lote) if lote is not None else None,
                           'custo_base_lote': rounded(custo_base_lote) if custo_base_lote is not None else None,
                           'custo_itens_sabor_lote': rounded(custo_sabor_lote) if custo_sabor_lote is not None else None,
                           'custo_sabor_sem_base_litro_bebida': (rounded(custo_sabor_lote / Decimal(str(rendimento)))
                                                                 if custo_sabor_lote is not None else None),
                           'custo_com_base_litro_bebida': (rounded(lote / Decimal(str(rendimento)))
                                                           if lote is not None else None),
                           'custo_litro': rounded(lote / Decimal(str(rendimento))) if lote is not None else None,
                           'custo_1000_litros': rounded(lote * Decimal(1000) / Decimal(str(rendimento))) if lote is not None else None,
                           'itens_sem_custo': (base.get('itens_sem_custo', 0)
                                              + sum(Decimal(i['preco_unitario']) == 0 for i in items if i['preco_unitario'] is not None)),
                           'pendencias': pendencias, 'xarope_revisao': base['revisao'],
                           'atualizado_por': row.get('atualizado_por', ''),
                           'atualizado_em': str(row.get('atualizado_em') or '')})
        return result

    def products(cur, catalog, xarope, compostos, purchases, rateio, pid=None):
        cur.execute('''SELECT p.id produto_id, p.nome_produto, p.produto_base_nome, p.grupo_estoque,
            p.fator_embalagem_padrao,
            f.volume_ml, f.itens_json, f.revisao, f.atualizado_por, f.atualizado_em, f.xarope_litros,
            f.xarope_composto_id, f.agua_quente_litros, f.agua_quente_valor_litro, f.unidades_pacote,
            CASE WHEN e.produto_id IS NULL THEN 0 ELSE 1 END excluido_custo,
            e.excluido_por, e.excluido_em
            FROM estoque_produtos p LEFT JOIN custo_produto_formulas f ON f.produto_id=p.id
            LEFT JOIN custo_produto_exclusoes e ON e.produto_id=p.id
            WHERE p.ativo=1 AND UPPER(TRIM(p.grupo_estoque)) IN ('AGUA','PET','GFA')'''
            + (' AND p.id=%s' if pid is not None else '') + ' ORDER BY p.grupo_estoque,p.nome_produto,p.id',
            (pid,) if pid is not None else ())
        result = []
        compostos_por_id = {x['id']: x for x in compostos}
        for row in cur.fetchall():
            grupo = str(row.get('grupo_estoque') or '').strip().upper()
            usa_xarope = grupo != 'AGUA'
            items = itens_publicos(row['itens_json'], catalog, purchases)
            volume = float(row['volume_ml']) if row['volume_ml'] else volume_sugerido(row)
            pacote = row.get('unidades_pacote')
            fator_sugerido = Decimal(str(row.get('fator_embalagem_padrao') or 0))
            if not pacote and fator_sugerido > 1 and fator_sugerido == fator_sugerido.quantize(Decimal('1')):
                pacote = int(fator_sugerido)
            agua_quente_litros = row.get('agua_quente_litros') or 0
            agua_quente_valor_litro = row.get('agua_quente_valor_litro') or 0
            composto = compostos_por_id.get(row.get('xarope_composto_id')) if usa_xarope else None
            dose = composto['xarope_base_litros_1000'] if composto and usa_xarope else 0
            pendencias = []
            if usa_xarope:
                if row.get('xarope_composto_id') is None: pendencias.append('Selecione o xarope composto deste sabor.')
                elif not composto: pendencias.append('O xarope composto selecionado nao esta disponivel.')
                elif not composto['valido']: pendencias.extend(composto['pendencias'] or ['Revise o xarope composto.'])
                elif not composto['precificado']: pendencias.extend(composto['pendencias'] or ['Xarope composto sem custo completo.'])
            for item in items:
                if item['pendencia_preco']: pendencias.append(item['nome'] + ': ' + item['pendencia_preco'])
            if any(not i['vinculo_valido'] for i in items): pendencias.append('Vincule os itens a produtos ativos do cadastro.')
            result.append({'produto_id': row['produto_id'], 'nome_produto': row['nome_produto'],
                           'grupo_estoque': row['grupo_estoque'], 'volume_ml': volume,
                           'usa_xarope': usa_xarope,
                           'unidades_pacote': int(pacote) if pacote else None,
                           'xarope_composto_id': row.get('xarope_composto_id'),
                           'xarope_composto_nome': composto['nome'] if composto else None,
                           'xarope_composto_revisao': composto['revisao'] if composto else None,
                           'xarope_composto': composto,
                           'xarope_litros': float(dose) if dose else None,
                           'agua_quente_litros': float(agua_quente_litros),
                           'agua_quente_valor_litro': float(agua_quente_valor_litro),
                           'excluido_custo': bool(row.get('excluido_custo')),
                           'excluido_por': row.get('excluido_por') or '',
                           'excluido_em': str(row.get('excluido_em') or ''),
                           'revisao': row['revisao'] or 0, 'itens': items, 'pendencias': pendencias,
                           'atualizado_por': row['atualizado_por'] or '', 'atualizado_em': str(row['atualizado_em'] or ''),
                           'calculo': calcular_formula(volume, items, composto, dose, agua_quente_litros,
                                                       agua_quente_valor_litro, rateio, pacote)
                           if row['revisao'] and volume and not pendencias else None})
        return sugestoes_pet(result, catalog)

    def compras(cur, reference=None, history=None):
        return ultimas_compras(history if history is not None else services.get('compras', carregar_compras)(cur), reference or hoje())

    def snapshot(cur, reference=None, incluir_rateio=True):
        catalog = catalogo(cur)
        purchases = compras(cur, reference)
        base = xarope_cur(cur, catalog, purchases)
        compostos = xaropes_compostos_cur(cur, catalog, purchases, base)
        rateio = rateio_cur(cur)
        return {'produtos': products(cur, catalog, base, compostos, purchases, rateio if incluir_rateio else None),
                'insumos': [{**p, 'ultima_compra': purchases.get(p['id'])} for p in catalog.values()],
                'xarope': base, 'xaropes_compostos': compostos, 'rateio': rateio, 'base_litros': 1000}

    def texto_sped(value, limit):
        return str(value or '').strip()[:limit]

    def cfop_compra_sped(value):
        code = re.sub(r'\D', '', str(value or ''))
        if len(code) != 4 or code[0] not in {'1', '2', '3'}:
            return ''
        suffix = code[1:]
        excluded = {
            '151','152','153','154','155','156','157','158','159',
            '201','202','208','209','410','411','412','413',
            '503','504','505','506','507','508','509',
            '553','554','555','556','557','558','559',
            '660','661','662','663','664','665','666','910','911',
        }
        return '' if suffix in excluded else code

    @bp.post('/api/custo-produto/sped')
    def importar_referencias_sped():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get('itens'), list):
            return jsonify(erro='Resumo SPED invalido.'), 400
        if len(data['itens']) > 25000:
            return jsonify(erro='Envie no maximo 25.000 itens SPED por periodo.'), 400
        empresa_cnpj = re.sub(r'\D', '', texto_sped(data.get('empresa_cnpj'), 20))
        periodo = texto_sped(data.get('periodo'), 7)
        if not 8 <= len(empresa_cnpj) <= 20 or not re.fullmatch(r'\d{4}-\d{2}', periodo):
            return jsonify(erro='Empresa ou periodo do SPED invalido.'), 400
        arquivo = texto_sped(data.get('arquivo'), 255)
        actor = str(services['actor']())[:180]
        rows = []
        identities = set()
        discarded = 0
        try:
            for raw in data['itens']:
                if not isinstance(raw, dict):
                    discarded += 1
                    continue
                cfop = cfop_compra_sped(raw.get('cfop'))
                if not cfop:
                    discarded += 1
                    continue
                try:
                    issue_date = dt.date.fromisoformat(texto_sped(raw.get('data_emissao'), 10))
                    quantity = numero(raw.get('quantidade'), 'Quantidade SPED', Decimal('.000001'))
                    item_value = numero(raw.get('valor_item'), 'Valor do item SPED')
                    discount = numero(raw.get('valor_desconto') or 0, 'Desconto do item SPED')
                    if discount > item_value:
                        raise ValueError('Desconto do item SPED maior que o valor do item.')
                except (ValueError, TypeError):
                    discarded += 1
                    continue
                document_key = re.sub(r'\D', '', texto_sped(raw.get('chave_documento'), 60))
                note = texto_sped(raw.get('numero_nota'), 60)
                item_number = texto_sped(raw.get('item_numero'), 30)
                supplier_tax_id = re.sub(r'\D', '', texto_sped(raw.get('fornecedor_cnpj'), 20))
                supplier_name = texto_sped(raw.get('fornecedor_nome'), 255)
                product_code = texto_sped(raw.get('codigo_produto'), 120)
                product_name = texto_sped(raw.get('descricao_produto'), 255)
                source_unit = texto_sped(raw.get('unidade'), 30).upper()
                identity_source = '|'.join((empresa_cnpj, document_key or note, issue_date.isoformat(),
                                            item_number, supplier_tax_id, product_code, product_name))
                identity = hashlib.sha256(identity_source.encode('utf-8')).hexdigest()
                if identity in identities:
                    discarded += 1
                    continue
                identities.add(identity)
                rows.append((identity, empresa_cnpj, periodo, document_key, note, item_number,
                             issue_date.isoformat(), supplier_tax_id, supplier_name, product_code,
                             product_name, source_unit, quantity, item_value, discount, cfop,
                             arquivo, actor))
        except ValueError as exc:
            return jsonify(erro=str(exc)), 400

        conn = services['get_conn'](); cur = conn.cursor(dictionary=True)
        try:
            cur.execute('DELETE FROM custo_produto_sped_itens WHERE empresa_cnpj=%s AND periodo=%s',
                        (empresa_cnpj, periodo))
            removed = cur.rowcount if getattr(cur, 'rowcount', None) is not None else 0
            sql = '''INSERT INTO custo_produto_sped_itens
                (identidade,empresa_cnpj,periodo,chave_documento,numero_nota,item_numero,
                 data_emissao,fornecedor_cnpj,fornecedor_nome,codigo_produto,descricao_produto,
                 unidade,quantidade,valor_item,valor_desconto,cfop,arquivo_origem,importado_por)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)'''
            for row in rows:
                cur.execute(sql, row)
            conn.commit()
            return jsonify(ok=True, periodo=periodo, itens_recebidos=len(data['itens']),
                           itens_gravados=len(rows), itens_descartados=discarded,
                           itens_substituidos=max(0, int(removed or 0)))
        except Exception:
            conn.rollback()
            app.logger.exception('Falha ao importar referencias de custo do SPED')
            return jsonify(erro='Nao foi possivel sincronizar as referencias SPED.'), 500
        finally:
            conn.rollback(); cur.close(); conn.close()

    @bp.get('/api/custo-produto/dashboard')
    def dashboard():
        today = hoje()
        conn = services['get_conn'](); cur = conn.cursor(dictionary=True)
        try:
            catalog = catalogo(cur)
            history = services.get('compras', carregar_compras)(cur)
            current_prices = compras(cur, today, history)
            current_base = xarope_cur(cur, catalog, current_prices)
            current_compostos = xaropes_compostos_cur(cur, catalog, current_prices, current_base)
            rateio = rateio_cur(cur)
            current = [p for p in products(cur, catalog, current_base, current_compostos, current_prices, rateio)
                       if p['revisao'] and not p['excluido_custo']]
            return jsonify(data_referencia=today.isoformat(), rateio=rateio,
                metodologia='Formula e rateio atuais com a ultima compra fiscal disponivel em NF-e ou SPED; no mesmo dia a NF-e confirmada tem prioridade; sem referencia utilizavel, usa o valor provisorio atual.',
                xarope_base={'rendimento_litros': current_base.get('rendimento_litros'),
                             'custo_lote': current_base.get('custo_lote'),
                             'custo_litro': current_base.get('custo_litro'),
                             'itens': current_base.get('itens') or [],
                             'valido': current_base.get('valido'),
                             'precificado': current_base.get('precificado'),
                             'pendencias': current_base.get('pendencias') or []},
                sabores=[{'id':x['id'], 'nome':x['nome'], 'rendimento_litros':x['rendimento_litros'],
                          'rendimento_bebida_litros':x['rendimento_bebida_litros'],
                          'xarope_base_litros_1000':x['xarope_base_litros_1000'],
                          'custo_litro':x['custo_litro'], 'custo_1000_litros':x['custo_1000_litros'],
                          'custo_base_lote':x['custo_base_lote'],
                          'custo_itens_sabor_lote':x['custo_itens_sabor_lote'],
                          'custo_sabor_sem_base_litro_bebida':x['custo_sabor_sem_base_litro_bebida'],
                          'custo_com_base_litro_bebida':x['custo_com_base_litro_bebida'],
                          'itens':x['itens'], 'precificado':x['precificado'],
                          'pendencias':x['pendencias']} for x in current_compostos],
                produtos=[{'produto_id':p['produto_id'],'nome_produto':p['nome_produto'],'grupo_estoque':p['grupo_estoque'],
                           'volume_ml':p['volume_ml'],'atual':p['calculo'],'pendencias':p['pendencias'],
                           'itens':p['itens'],
                           'unidades_pacote':p['unidades_pacote'],
                           'xarope_composto_nome':p['xarope_composto_nome']} for p in current])
        finally:
            cur.close(); conn.close()

    @bp.get('/api/custo-produto')
    def listar():
        conn = services['get_conn'](); cur = conn.cursor(dictionary=True)
        try:
            return jsonify(snapshot(cur))
        finally:
            cur.close(); conn.close()

    @bp.delete('/api/custo-produto/produtos/<int:pid>')
    def excluir_produto_lista(pid):
        conn = services['get_conn'](); cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT id FROM estoque_produtos WHERE id=%s AND ativo=1 AND UPPER(TRIM(grupo_estoque)) IN ('AGUA','PET','GFA') FOR UPDATE", (pid,))
            if not cur.fetchone():
                return jsonify(erro='Produto de agua, PET ou retornavel ativo nao encontrado.'), 404
            cur.execute('SELECT produto_id FROM custo_produto_exclusoes WHERE produto_id=%s FOR UPDATE', (pid,))
            if not cur.fetchone():
                cur.execute('INSERT INTO custo_produto_exclusoes (produto_id,excluido_por) VALUES (%s,%s)',
                            (pid, str(services['actor']())[:180]))
            conn.commit()
            return jsonify(ok=True, produto_id=pid, excluido_custo=True)
        except Exception:
            conn.rollback()
            app.logger.exception('Falha ao remover produto da lista de custos')
            return jsonify(erro='Nao foi possivel remover o produto da lista. Tente novamente.'), 500
        finally:
            conn.rollback(); cur.close(); conn.close()

    @bp.post('/api/custo-produto/produtos/<int:pid>/restaurar')
    def restaurar_produto_lista(pid):
        conn = services['get_conn'](); cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT id FROM estoque_produtos WHERE id=%s AND ativo=1 AND UPPER(TRIM(grupo_estoque)) IN ('AGUA','PET','GFA') FOR UPDATE", (pid,))
            if not cur.fetchone():
                return jsonify(erro='Produto de agua, PET ou retornavel ativo nao encontrado.'), 404
            cur.execute('DELETE FROM custo_produto_exclusoes WHERE produto_id=%s', (pid,))
            conn.commit()
            return jsonify(ok=True, produto_id=pid, excluido_custo=False)
        except Exception:
            conn.rollback()
            app.logger.exception('Falha ao restaurar produto na lista de custos')
            return jsonify(erro='Nao foi possivel restaurar o produto na lista. Tente novamente.'), 500
        finally:
            conn.rollback(); cur.close(); conn.close()

    @bp.get('/api/custo-produto/rateio')
    def listar_rateio():
        conn = services['get_conn'](); cur = conn.cursor(dictionary=True)
        try:
            return jsonify(rateio_cur(cur))
        finally:
            cur.close(); conn.close()

    def revisao(data, key='revisao'):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError('Reabra a formula para obter sua revisao atual.')
        return value

    @bp.put('/api/custo-produto/rateio')
    def salvar_rateio():
        data = request.get_json(silent=True)
        conn = services['get_conn'](); cur = conn.cursor(dictionary=True)
        try:
            revision = revisao(data or {})
            volume, capacidade, horas, items = validar_rateio(data)
            previous = rateio_cur(cur, lock=True)
            if revision != previous['revisao']:
                return jsonify(erro='Os custos indiretos foram alterados por outro usuario. Reabra antes de salvar.'), 409
            actor = str(services['actor']())[:180]
            cur.execute('''UPDATE custo_produto_rateio SET volume_mensal_litros=%s,capacidade_litros_hora=%s,horas_semanais=%s,itens_json=%s,
                revisao=revisao+1,atualizado_por=%s,atualizado_em=CURRENT_TIMESTAMP WHERE id=1''',
                (volume, capacidade, horas, json.dumps(items, ensure_ascii=False), actor))
            result = rateio_cur(cur)
            conn.commit()
            return jsonify(result)
        except ValueError as exc:
            conn.rollback(); return jsonify(erro=str(exc)), 400
        except Exception:
            conn.rollback(); app.logger.exception('Falha ao salvar rateio de custos')
            return jsonify(erro='Nao foi possivel salvar os custos indiretos. Tente novamente.'), 500
        finally:
            conn.rollback(); cur.close(); conn.close()

    @bp.post('/api/custo-produto/xaropes-compostos')
    @bp.put('/api/custo-produto/xaropes-compostos/<int:cid>')
    def salvar_xarope_composto(cid=None):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(erro='Formula invalida.'), 400
        conn = services['get_conn'](); cur = conn.cursor(dictionary=True)
        try:
            revision = revisao(data)
            catalog = catalogo(cur); purchases = compras(cur)
            base = xarope_cur(cur, catalog, purchases, lock=True)
            if not base['valido']:
                raise ValueError('Cadastre um xarope base valido antes do xarope composto.')
            if revisao(data, 'xarope_revisao') != base['revisao']:
                return jsonify(erro='O xarope base foi alterado. Cancele e reabra para conferir a receita.'), 409
            nome = nome_xarope(data.get('nome'))
            base_litros = litros(data.get('xarope_base_litros'), 'Quantidade de xarope base no composto')
            rendimento = litros(data.get('rendimento_litros'), 'Rendimento do xarope composto')
            # Campo legado mantido no banco por compatibilidade. A proporcao e
            # sempre derivada: base usada no lote * 1000 / bebida produzida.
            dose = base_litros * Decimal(1000) / rendimento
            items = validar_itens(data.get('itens'), catalog, minimo=1)
            cur.execute('SELECT id FROM custo_produto_xaropes_compostos WHERE LOWER(TRIM(nome))=LOWER(TRIM(%s)) AND id<>%s',
                        (nome, cid or 0))
            if cur.fetchone():
                raise ValueError('Ja existe um xarope composto com esse nome.')
            actor = str(services['actor']())[:180]
            if cid is None:
                if revision != 0:
                    return jsonify(erro='Reabra o cadastro para criar o xarope composto.'), 409
                cur.execute('''INSERT INTO custo_produto_xaropes_compostos
                    (nome,xarope_base_litros,rendimento_litros,dose_litros_1000,itens_json,atualizado_por)
                    VALUES (%s,%s,%s,%s,%s,%s)''',
                    (nome, base_litros, rendimento, dose, json.dumps(items, ensure_ascii=False), actor))
            else:
                previous = xaropes_compostos_cur(cur, catalog, purchases, base, cid, lock=True)
                if not previous:
                    return jsonify(erro='Xarope composto nao encontrado.'), 404
                if revision != previous[0]['revisao']:
                    return jsonify(erro='O xarope composto foi alterado por outro usuario. Cancele e reabra.'), 409
                cur.execute('''UPDATE custo_produto_xaropes_compostos SET nome=%s,xarope_base_litros=%s,
                    rendimento_litros=%s,dose_litros_1000=%s,itens_json=%s,revisao=revisao+1,
                    atualizado_por=%s,atualizado_em=CURRENT_TIMESTAMP WHERE id=%s''',
                    (nome, base_litros, rendimento, dose, json.dumps(items, ensure_ascii=False), actor, cid))
            result = snapshot(cur)
            conn.commit()
            return jsonify(result)
        except ValueError as exc:
            conn.rollback(); return jsonify(erro=str(exc)), 400
        except Exception:
            conn.rollback(); app.logger.exception('Falha ao salvar xarope composto')
            return jsonify(erro='Nao foi possivel salvar o xarope composto. Tente novamente.'), 500
        finally:
            conn.rollback(); cur.close(); conn.close()

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
                unidades_pacote = inteiro_positivo(data.get('unidades_pacote'), 'Unidades por pacote')
                agua_quente_litros, agua_quente_valor_litro = validar_agua_quente(data)
                cur.execute("SELECT id,UPPER(TRIM(grupo_estoque)) grupo FROM estoque_produtos WHERE id=%s AND ativo=1 AND UPPER(TRIM(grupo_estoque)) IN ('AGUA','PET','GFA') FOR UPDATE", (pid,))
                produto = cur.fetchone()
                if not produto:
                    return jsonify(erro='Produto de agua, PET ou retornavel ativo nao encontrado.'), 404
                agua = produto['grupo'] == 'AGUA'
                composto_id = None
                dose = Decimal(0)
                if not agua:
                    composto_id = data.get('xarope_composto_id')
                    if isinstance(composto_id, bool) or not str(composto_id).isdigit():
                        raise ValueError('Selecione o xarope composto do sabor.')
                    composto_id = int(composto_id)
                    compostos = xaropes_compostos_cur(cur, catalog, purchases, base, composto_id, lock=True)
                    if not compostos:
                        raise ValueError('Selecione um xarope composto disponivel.')
                    composto = compostos[0]
                    if not composto['valido']:
                        raise ValueError('Revise o xarope composto antes de salvar o produto.')
                    if revisao(data, 'xarope_composto_revisao') != composto['revisao']:
                        return jsonify(erro='O xarope composto foi alterado. Cancele e reabra para conferir o custo atual.'), 409
                    dose = Decimal(str(composto['dose_litros_1000']))
                cur.execute('SELECT revisao FROM custo_produto_formulas WHERE produto_id=%s FOR UPDATE', (pid,))
                previous = cur.fetchone()
                if revision != (previous['revisao'] if previous else 0):
                    return jsonify(erro='A formula foi alterada por outro usuario. Cancele e reabra para conferir a versao atual.'), 409
                if previous:
                    cur.execute('''UPDATE custo_produto_formulas SET volume_ml=%s, itens_json=%s, xarope_litros=%s,
                        xarope_composto_id=%s,
                        agua_quente_litros=%s, agua_quente_valor_litro=%s, unidades_pacote=%s,
                        revisao=revisao+1, atualizado_por=%s, atualizado_em=CURRENT_TIMESTAMP WHERE produto_id=%s''',
                        (volume, json.dumps(items, ensure_ascii=False), dose, composto_id, agua_quente_litros,
                         agua_quente_valor_litro, unidades_pacote, actor, pid))
                else:
                    cur.execute('''INSERT INTO custo_produto_formulas
                        (produto_id,volume_ml,itens_json,xarope_litros,xarope_composto_id,agua_quente_litros,
                         agua_quente_valor_litro,unidades_pacote,atualizado_por) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                        (pid, volume, json.dumps(items, ensure_ascii=False), dose, composto_id, agua_quente_litros,
                         agua_quente_valor_litro, unidades_pacote, actor))
                todos_compostos = xaropes_compostos_cur(cur, catalog, purchases, base)
                rateio = rateio_cur(cur)
                result = products(cur, catalog, base, todos_compostos, purchases, rateio, pid)[0]
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

    @bp.delete('/api/custo-produto/<int:pid>')
    def excluir_formula(pid):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(erro='Informe a revisao atual da formula.'), 400
        conn = services['get_conn'](); cur = conn.cursor(dictionary=True)
        try:
            revision = revisao(data)
            cur.execute("SELECT id FROM estoque_produtos WHERE id=%s AND ativo=1 AND UPPER(TRIM(grupo_estoque)) IN ('AGUA','PET','GFA') FOR UPDATE", (pid,))
            if not cur.fetchone():
                return jsonify(erro='Produto de agua, PET ou retornavel ativo nao encontrado.'), 404
            cur.execute('SELECT revisao FROM custo_produto_formulas WHERE produto_id=%s FOR UPDATE', (pid,))
            previous = cur.fetchone()
            if not previous:
                return jsonify(erro='Formula nao cadastrada para este produto.'), 404
            if revision != previous['revisao']:
                return jsonify(erro='A formula foi alterada por outro usuario. Reabra a lista antes de excluir.'), 409
            cur.execute('DELETE FROM custo_produto_formulas WHERE produto_id=%s', (pid,))
            conn.commit()
            return jsonify(ok=True, produto_id=pid)
        except ValueError as exc:
            conn.rollback()
            return jsonify(erro=str(exc)), 400
        except Exception:
            conn.rollback()
            app.logger.exception('Falha ao excluir formula de custo')
            return jsonify(erro='Nao foi possivel excluir a formula. Tente novamente.'), 500
        finally:
            conn.rollback(); cur.close(); conn.close()

    app.register_blueprint(bp)
    register_custo_diario(app, {**services,
        'snapshot':lambda cur, reference=None: snapshot(cur, reference, incluir_rateio=False)})
