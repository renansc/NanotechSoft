"""Apuracao diaria por grupo, com producao boa, despesas e perdas por setor."""
import datetime as dt
import json
from decimal import Decimal, InvalidOperation, localcontext
from flask import Blueprint, jsonify, request
from custo_produto_compras import hoje, precificar_item, unidade

CATEGORIAS = {'pessoal', 'embalagem', 'agua', 'energia', 'outras'}
COMPONENTES = ('formula', 'pessoal', 'embalagem', 'agua', 'energia', 'outras', 'desperdicio')


def ensure_custo_diario_schema(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS custo_diario_lancamentos (
        data_ref DATE PRIMARY KEY, dados_json LONGTEXT NOT NULL,
        resultado_json LONGTEXT NOT NULL, revisao INT NOT NULL DEFAULT 1,
        atualizado_por VARCHAR(180) NOT NULL, atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')


def decimal(value, label, positive=False, integer=False):
    try:
        n = Decimal(str(value).replace(',', '.'))
        if not n.is_finite() or n < 0 or n > Decimal('999999999.999999') or (positive and n <= 0): raise ValueError()
        if n != n.quantize(Decimal('1') if integer else Decimal('.000001')): raise ValueError()
        return n
    except (ValueError, InvalidOperation):
        raise ValueError(f'{label}: informe um numero valido' + (' inteiro positivo.' if integer else ', com ate seis casas decimais.'))


def texto(value, label, required=True):
    if not isinstance(value, str) or len(value.strip()) > 180 or (required and not value.strip()):
        raise ValueError(f'{label}: informe um texto de ate 180 caracteres.')
    return value.strip()


def validar(data, catalog):
    if not isinstance(data, dict): raise ValueError('Lancamento invalido.')
    if data.get('perdas'): raise ValueError('Desperdicios sao obtidos das contagens finalizadas, sem lancamento manual.')
    data = {**data, 'perdas':[]}
    groups = {p['grupo_estoque'].strip().upper() for p in catalog.values()}
    result = {'producao': [], 'despesas': [], 'perdas': []}
    for key in result:
        entries = data.get(key)
        if not isinstance(entries, list) or len(entries) > 200: raise ValueError(f'{key}: informe ate 200 linhas.')
        if any(not isinstance(i, dict) for i in entries): raise ValueError('Linha invalida.')
    seen = set()
    for item in data['producao']:
        pid = item.get('produto_id')
        if isinstance(pid, bool) or not str(pid).isdigit() or int(pid) not in catalog: raise ValueError('Selecione um produto ativo na producao.')
        pid = int(pid)
        if pid in seen: raise ValueError('Consolide a producao do mesmo produto em uma linha.')
        seen.add(pid)
        result['producao'].append({'produto_id':pid,
            'embalagens':str(decimal(item.get('embalagens'),'Embalagens boas',True,True)),
            'por_pacote':str(decimal(item.get('por_pacote'),'Embalagens por pacote',True,True)),
            'volume_ml':str(decimal(item.get('volume_ml'),'Volume por embalagem em ml',True))})
    for key in ('despesas',):
        for item in data[key]:
            group = str(item.get('grupo') or '').strip().upper()
            if group and group not in groups: raise ValueError('Grupo de custo invalido.')
            row = {'grupo':group, 'setor':texto(item.get('setor'), 'Setor'),
                   'descricao':texto(item.get('descricao'),'Descricao')}
            category = item.get('categoria')
            if category not in CATEGORIAS: raise ValueError('Categoria de despesa invalida.')
            row.update(categoria=category, valor=str(decimal(item.get('valor'),'Valor da despesa')))
            result[key].append(row)
    return result


def numero(value):
    return float(value.quantize(Decimal('.000001')))


def apurar(data, products, base):
    """Rateia pela producao boa em litros. Sem denominador, conserva o gasto pendente."""
    with localcontext() as ctx:
        ctx.prec = 50
        rows = []
        for entry in data['producao']:
            p = products[entry['produto_id']]
            bottles = Decimal(entry['embalagens']); volume = Decimal(entry['volume_ml'])
            litres = bottles * volume / 1000
            parts = {key:Decimal(0) for key in COMPONENTES}
            pending = list(p.get('pendencias') or [])
            if not p.get('calculo'):
                parts['formula'] = None
                pending.append('Formula sem custo completo na data selecionada.')
            else:
                # Preserva a precisao dos itens, sem multiplicar um preco exibido arredondado.
                syrup = sum((Decimal(i['quantidade'])*Decimal(i['preco_unitario']) for i in base['itens']),Decimal(0))
                extras = sum((Decimal(i['quantidade'])*Decimal(i['preco_unitario']) for i in p['itens']),Decimal(0))
                batch = syrup / Decimal(str(base['rendimento_litros'])) * Decimal(str(p['xarope_litros'])) + extras
                parts['formula'] = batch * litres / 1000
            rows.append({**entry,'nome_produto':p['nome_produto'],'grupo':p['grupo_estoque'].strip().upper(),
                         'litros':litres,'embalagens':bottles,'pacotes':bottles/Decimal(entry['por_pacote']),
                         'componentes':parts,'pendencias':pending,'referencia_formula':p})
        unallocated = []
        for expense in data['despesas'] + [{**p,'categoria':'desperdicio'} for p in data['perdas']]:
            targets = [r for r in rows if not expense['grupo'] or r['grupo']==expense['grupo']]
            denominator = sum((r['litros'] for r in targets),Decimal(0))
            if not denominator:
                if expense['valor'] is None or Decimal(expense['valor']) > 0: unallocated.append(expense)
                continue
            for row in targets:
                category = expense['categoria']
                if expense['valor'] is None:
                    row['componentes'][category] = None
                    row['pendencias'].append('Falta de estoque sem valor: ' + expense['descricao'])
                elif row['componentes'][category] is not None:
                    row['componentes'][category] += Decimal(expense['valor']) * row['litros'] / denominator
        def resumo(items):
            totals = {k:sum((r[k] for r in items),Decimal(0)) for k in ('litros','embalagens','pacotes')}
            parts = {k:None if any(r['componentes'][k] is None for r in items) else sum((r['componentes'][k] for r in items),Decimal(0)) for k in COMPONENTES}
            total = None if any(v is None for v in parts.values()) else sum(parts.values(),Decimal(0))
            rates = {}
            for unit,denominator in totals.items():
                rates[unit] = {k:numero(v/denominator) if v is not None and denominator else None for k,v in parts.items()}
                rates[unit]['total'] = numero(total/denominator) if total is not None and denominator else None
            return {**{k:numero(v) for k,v in totals.items()}, 'componentes':{k:numero(v) if v is not None else None for k,v in parts.items()},
                    'total':numero(total) if total is not None and items else None, 'por_unidade':rates}
        groups = sorted({r['grupo'] for r in rows} | {r['grupo'] for r in unallocated if r['grupo']})
        sectors = {}
        for loss in data['perdas']:
            key = (loss['setor'],loss['unidade'])
            row = sectors.setdefault(key, {'setor':key[0],'unidade':key[1],'quantidade':Decimal(0),'valor':Decimal(0)})
            row['quantidade'] += Decimal(loss['quantidade'])
            row['valor'] = None if row['valor'] is None or loss['valor'] is None else row['valor'] + Decimal(loss['valor'])
        summary = resumo(rows)
        if unallocated:
            summary['total'] = None
            for rate in summary['por_unidade'].values(): rate['total'] = None
        return {'produtos':[{**r,**resumo([r])} for r in rows],
                'grupos':[{'grupo':g,**resumo([r for r in rows if r['grupo']==g]),
                           'pendencias':['Despesas sem producao para ratear.'] if any(e['grupo']==g for e in unallocated) else []} for g in groups],
                'resumo':summary, 'nao_rateado':unallocated,
                'desperdicios_setor':[{**s,'quantidade':numero(s['quantidade']),'valor':numero(s['valor']) if s['valor'] is not None else None} for s in sectors.values()],
                'perdas':data['perdas'],
                'referencia_xarope':base,
                'metodologia':'Producao boa informada; despesas rateadas pelos litros. Embalagem = uma garrafa; pacote = capacidade informada. Desperdicios vem das faltas em contagens finalizadas no dia, agrupadas pelo setor de estoque. Nao ha nova baixa de estoque.'}


def perdas_contagem(cur, date, snapshot, saved_products=None):
    products = {p['produto_id']:p for p in snapshot['produtos']}
    products.update(saved_products or {})
    catalog = {p['id']:p for p in snapshot['insumos']}
    prices = {p['id']:p['ultima_compra'] for p in catalog.values() if p.get('ultima_compra')}
    cur.execute('''SELECT i.id,i.contagem_id,i.produto_id,i.nome_produto,i.desperdicio,c.finalizado_em,
        p.unidade,p.grupo_estoque,g.nome grupo_nome
        FROM estoque_contagem_resultados i JOIN estoque_contagens c ON c.id=i.contagem_id
        LEFT JOIN estoque_produtos p ON p.id=i.produto_id
        LEFT JOIN estoque_grupos g ON g.codigo=p.grupo_estoque
        WHERE c.status='finalizada' AND i.desperdicio>0 AND c.finalizado_em>=%s AND c.finalizado_em<%s
        ORDER BY i.id''',(date.isoformat(),(date+dt.timedelta(days=1)).isoformat()))
    losses=[]
    for row in cur.fetchall():
        pid=row['produto_id'];group=(row['grupo_estoque'] or '').strip().upper()
        unit=unidade(row['unidade']);price=None
        if group in {'PET','GFA','AGUA'}:
            unit='UN'
            calculation=(products.get(pid) or {}).get('calculo')
            if calculation:price=calculation['custo_unidade']
        elif unit in {'KG','G','L','ML','UN'}:
            price=precificar_item({'produto_id':pid,'unidade':unit.lower()},prices)['preco_unitario']
        value=numero(Decimal(str(row['desperdicio']))*Decimal(str(price))) if price is not None else None
        losses.append({'contagem_id':row['contagem_id'],'item_id':row['id'],'produto_id':pid,
                       'descricao':row['nome_produto'],'setor':'Estoque / '+str(row['grupo_nome'] or group or 'Sem grupo'),
                       'grupo':group if group in {'PET','GFA'} else '', 'unidade':unit.lower() or 'unidade de estoque',
                       'quantidade':str(row['desperdicio']),'valor':value,'origem':'Contagem de estoque finalizada',
                       'finalizado_em':str(row['finalizado_em'])})
    return losses


def register_custo_diario(app, services):
    bp = Blueprint('custo_diario', __name__)

    @bp.before_request
    def authorize():
        uid = request.headers.get('X-Usuario-Id','')
        if not uid.isdigit() or int(uid)<=0: return jsonify(erro='Sessao do portal necessaria.'),401
        resource = 'custo_produto_dashboard' if request.path.endswith('/dashboard') else 'custo_diario'
        if request.headers.get('X-Usuario-Perfil') != 'admin' and not set(request.headers.get('X-Usuario-Recursos','').split(',')).intersection({'*',resource}):
            return jsonify(erro='Custo diario nao liberado para este usuario.'),403

    def data_ref():
        try:
            date = dt.date.fromisoformat(request.args.get('data',hoje().isoformat()))
            if date < dt.date(2000,1,1) or date > hoje(): raise ValueError()
            return date
        except (ValueError,TypeError): raise ValueError('Informe uma data entre 2000 e hoje.')

    def ler(cur,date):
        cur.execute('SELECT * FROM custo_diario_lancamentos WHERE data_ref=%s',(date.isoformat(),))
        row = cur.fetchone()
        return {'data':date.isoformat(),'revisao':row['revisao'] if row else 0,
                'dados':json.loads(row['dados_json']) if row else {'producao':[],'despesas':[],'perdas':[]},
                'resultado':json.loads(row['resultado_json']) if row else None,
                'atualizado_por':row['atualizado_por'] if row else '', 'atualizado_em':str(row['atualizado_em']) if row else ''}

    def atualizar_contagens(cur,date,result,snapshot):
        saved = result['resultado']
        references = {p['produto_id']:p['referencia_formula'] for p in saved['produtos']} if saved else {}
        losses = perdas_contagem(cur,date,snapshot,references)
        if saved or losses:
            base=saved['referencia_xarope'] if saved else snapshot['xarope']
            result['resultado']=apurar({**result['dados'],'perdas':losses},references,base)
        result['contagens']=losses
        return result

    @bp.get('/api/custo-diario')
    @bp.get('/api/custo-diario/dashboard')
    def listar():
        try: date = data_ref()
        except ValueError as exc:return jsonify(erro=str(exc)),400
        conn=services['get_conn']();cur=conn.cursor(dictionary=True)
        try:
            result=ler(cur,date)
            snapshot=services['snapshot'](cur,date)
            atualizar_contagens(cur,date,result,snapshot)
            if not request.path.endswith('/dashboard'):
                result['catalogo']=snapshot['produtos']
                for p in result['catalogo']:
                    p['por_pacote_sugerido']=services.get('pacote',lambda p:None)(p)
            return jsonify(result)
        finally:cur.close();conn.close()

    @bp.put('/api/custo-diario')
    def salvar():
        try:date=data_ref()
        except ValueError as exc:return jsonify(erro=str(exc)),400
        conn=services['get_conn']();cur=conn.cursor(dictionary=True)
        try:
            data=request.get_json(silent=True)
            if not isinstance(data,dict) or type(data.get('revisao')) is not int or data['revisao']<0: raise ValueError('Reabra o dia para obter a revisao atual.')
            # Mesmo lock da formula impede que a base mude durante a apuracao.
            cur.execute('SELECT id FROM custo_produto_xarope WHERE id=1 FOR UPDATE');cur.fetchone()
            previous=ler(cur,date)
            if previous['revisao']!=data['revisao']: return jsonify(erro='O dia foi alterado por outro usuario. Reabra antes de salvar.'),409
            snapshot=services['snapshot'](cur,date)
            catalog={p['produto_id']:p for p in snapshot['produtos']}
            entries=validar(data.get('dados'),catalog)
            losses=perdas_contagem(cur,date,snapshot)
            result=apurar({**entries,'perdas':losses},catalog,snapshot['xarope'])
            args=(json.dumps(entries,ensure_ascii=False),json.dumps(result,ensure_ascii=False),str(services['actor']())[:180],date.isoformat())
            if previous['revisao']:
                cur.execute('UPDATE custo_diario_lancamentos SET dados_json=%s,resultado_json=%s,atualizado_por=%s,revisao=revisao+1,atualizado_em=CURRENT_TIMESTAMP WHERE data_ref=%s',args)
            else:
                cur.execute('INSERT INTO custo_diario_lancamentos(dados_json,resultado_json,atualizado_por,data_ref) VALUES (%s,%s,%s,%s)',args)
            conn.commit()
            return jsonify(ler(cur,date))
        except ValueError as exc:
            conn.rollback();return jsonify(erro=str(exc)),400
        except Exception:
            conn.rollback();app.logger.exception('Falha ao apurar custo diario');return jsonify(erro='Nao foi possivel salvar o custo diario.'),500
        finally:conn.rollback();cur.close();conn.close()
    app.register_blueprint(bp)
