"""Conferencia de inventario, ajustes auditaveis e relatorio de divergencias."""
import datetime as dt
from decimal import Decimal, InvalidOperation
from functools import wraps
from io import BytesIO
from xml.sax.saxutils import escape

from flask import Blueprint, jsonify, request, send_file
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def ensure_contagem_schema(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS estoque_contagens (
        id INT AUTO_INCREMENT PRIMARY KEY,
        usuario_id INT NOT NULL, usuario VARCHAR(180) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'conferida',
        observacao VARCHAR(1000) NOT NULL DEFAULT '',
        criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finalizado_em DATETIME NULL,
        INDEX (finalizado_em), INDEX (usuario_id)
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS estoque_contagem_resultados (
        id INT AUTO_INCREMENT PRIMARY KEY, contagem_id INT NOT NULL,
        produto_id INT NOT NULL, produto_key VARCHAR(255) NOT NULL,
        nome_produto VARCHAR(255) NOT NULL, codigo_barras VARCHAR(120) NOT NULL DEFAULT '',
        codigo_produto_nfe VARCHAR(120) NOT NULL DEFAULT '',
        saldo_antes DECIMAL(12,3) NOT NULL, quantidade_contada DECIMAL(12,3) NOT NULL,
        pallets DECIMAL(12,3) NOT NULL, volumes DECIMAL(12,3) NOT NULL, unidades DECIMAL(12,3) NOT NULL,
        por_pallet DECIMAL(12,3) NOT NULL, por_volume DECIMAL(12,3) NOT NULL,
        diferenca DECIMAL(12,3) NOT NULL, desperdicio DECIMAL(12,3) NOT NULL,
        sobra DECIMAL(12,3) NOT NULL, movimento_id INT NULL,
        UNIQUE KEY (contagem_id, produto_id), INDEX (produto_id), INDEX (contagem_id)
    )''')


def quantidade(value, integer=False):
    try:
        result = Decimal(str(value if value not in (None, '') else 0))
        if not result.is_finite() or result < 0 or result > Decimal('999999999.999'):
            raise ValueError()
        if result != result.quantize(Decimal('.001')) or (integer and result != result.to_integral_value()):
            raise ValueError()
        return result
    except (ValueError, InvalidOperation):
        raise ValueError('Quantidades devem ser positivas ou zero, com ate tres casas decimais; pallets e embalagens devem ser inteiros.')


def calcular_item(product, counted):
    pallets = quantidade(counted.get('pallets'), True)
    volumes = quantidade(counted.get('volumes'), True)
    units = quantidade(counted.get('unidades'))
    pp, pv = quantidade(product['por_pallet']), quantidade(product['por_volume'])
    if (pallets and not pp) or (volumes and not pv):
        raise ValueError('Produto sem capacidade cadastrada para pallets ou embalagens. Conte em unidades.')
    total = quantidade(pallets * pp + volumes * pv + units)
    before = Decimal(str(product['saldo']))
    delta = (total - before).quantize(Decimal('.001'))
    return {**product, 'pallets':pallets, 'volumes':volumes, 'unidades':units,
            'saldo_antes':before, 'quantidade_contada':total, 'diferenca':delta,
            'desperdicio':max(-delta, Decimal(0)), 'sobra':max(delta, Decimal(0))}


def publico(value):
    if isinstance(value, dict):
        return {k:publico(v) for k,v in value.items()}
    if isinstance(value, list):
        return [publico(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def resumo(items):
    return {'produtos':len(items),
            'desperdicio':float(sum(Decimal(str(i['desperdicio'])) for i in items)),
            'sobra':float(sum(Decimal(str(i['sobra'])) for i in items)),
            'produtos_com_sobra':sum(Decimal(str(i['sobra'])) > 0 for i in items)}


def register_estoque_contagem(app, services):
    bp = Blueprint('estoque_contagem', __name__)
    connect, snapshot = services['get_conn'], services['snapshot']

    def access(resource):
        def decorate(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if not request.headers.get('X-Usuario-Id', '').isdigit() or int(request.headers['X-Usuario-Id']) <= 0:
                    return jsonify(erro='Sessao do portal necessaria.'), 401
                grants = set(request.headers.get('X-Usuario-Recursos', '').split(','))
                if request.headers.get('X-Usuario-Perfil') != 'admin' and '*' not in grants and resource not in grants:
                    return jsonify(erro='Funcao nao liberada para este usuario.'), 403
                return fn(*args, **kwargs)
            return wrapped
        return decorate

    def fetch(cur, cid):
        cur.execute('SELECT * FROM estoque_contagens WHERE id=%s', (cid,))
        head = cur.fetchone()
        if not head:
            raise ValueError('Contagem nao encontrada.')
        cur.execute('SELECT * FROM estoque_contagem_resultados WHERE contagem_id=%s ORDER BY nome_produto, id', (cid,))
        items = cur.fetchall()
        return publico({**head, 'itens':items, 'resumo':resumo(items)})

    @bp.post('/api/estoque/contagens/conferir')
    @access('estoque_contagem_finalizar')
    def conferir():
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(erro='Dados de contagem invalidos.'), 400
        entries = data.get('itens')
        if not isinstance(entries, list) or not 1 <= len(entries) <= 1000:
            return jsonify(erro='Informe de 1 a 1000 produtos contados.'), 400
        conn = connect(); cur = conn.cursor(dictionary=True)
        try:
            ids = []
            for item in entries:
                if not isinstance(item, dict) or not str(item.get('produto_id', '')).isdigit():
                    raise ValueError('Produto invalido.')
                if all(item.get(k) in (None, '') for k in ('pallets','volumes','unidades')):
                    raise ValueError('Produto sem contagem. Informe zero para saldo fisico zero.')
                ids.append(int(item['produto_id']))
            if len(set(ids)) != len(ids):
                raise ValueError('Produto repetido na contagem.')
            products = snapshot(cur, ids)
            if len(products) != len(ids):
                raise ValueError('Produto removido ou indisponivel. Reabra a contagem.')
            results = [calcular_item(products[pid], item) for pid,item in zip(ids,entries)]
            if len({item['produto_key'] for item in results}) != len(results):
                raise ValueError('Dois cadastros representam o mesmo produto consolidado. Conte apenas uma vez.')
            note = str(data.get('observacao') or '').strip()
            if len(note) > 1000:
                raise ValueError('Observacao deve ter ate 1000 caracteres.')
            cur.execute('INSERT INTO estoque_contagens (usuario_id, usuario, observacao) VALUES (%s,%s,%s)',
                        (int(request.headers['X-Usuario-Id']), services['actor'](), note))
            cid = cur.lastrowid
            for item in results:
                fields = ('produto_id','produto_key','nome_produto','codigo_barras','codigo_produto_nfe',
                          'saldo_antes','quantidade_contada','pallets','volumes','unidades','por_pallet','por_volume',
                          'diferenca','desperdicio','sobra')
                cur.execute('INSERT INTO estoque_contagem_resultados (contagem_id,'+','.join(fields)+') VALUES ('+','.join(['%s']*16)+')',
                            (cid, *(item[k] for k in fields)))
            result = fetch(cur,cid)
            conn.commit()
            return jsonify(result), 201
        except ValueError as exc:
            conn.rollback(); return jsonify(erro=str(exc)), 400
        except Exception:
            conn.rollback()
            app.logger.exception('Falha ao preparar conferencia de estoque')
            return jsonify(erro='Nao foi possivel preparar a conferencia. Nenhum saldo foi alterado.'), 500
        finally:
            cur.close(); conn.close()

    @bp.post('/api/estoque/contagens/<int:cid>/finalizar')
    @access('estoque_contagem_finalizar')
    def finalizar(cid):
        conn = connect(); cur = conn.cursor(dictionary=True)
        try:
            conn.start_transaction(isolation_level='REPEATABLE READ')
            cur.execute('SELECT * FROM estoque_contagens WHERE id=%s FOR UPDATE', (cid,))
            head = cur.fetchone()
            if not head:
                return jsonify(erro='Contagem nao encontrada.'), 404
            if head['usuario_id'] != int(request.headers['X-Usuario-Id']) and request.headers.get('X-Usuario-Perfil') != 'admin':
                return jsonify(erro='Somente o responsavel ou administrador pode finalizar esta contagem.'), 403
            if head['status'] == 'finalizada':
                return jsonify(fetch(cur,cid))
            cur.execute('SELECT * FROM estoque_contagem_resultados WHERE contagem_id=%s ORDER BY produto_id', (cid,))
            items = cur.fetchall()
            # Bloqueia registros e intervalos de insercao ate o commit. Os demais
            # fluxos usam o mesmo livro de movimentos, inclusive os legados.
            cur.execute('SELECT id FROM estoque_movimentos ORDER BY id FOR UPDATE')
            cur.fetchall()
            products = snapshot(cur, [item['produto_id'] for item in items], lock=True)
            for item in items:
                product = products.get(item['produto_id'])
                if (not product or product['produto_key'] != item['produto_key']
                        or Decimal(str(product['saldo'])) != Decimal(str(item['saldo_antes']))
                        or quantidade(product['por_pallet']) != quantidade(item['por_pallet'])
                        or quantidade(product['por_volume']) != quantidade(item['por_volume'])):
                    conn.rollback()
                    return jsonify(erro='Estoque ou cadastro mudou depois da conferencia. Feche o popup e confira novamente.'), 409
            for item in items:
                delta = Decimal(str(item['diferenca']))
                if not delta:
                    continue
                cur.execute('''INSERT INTO estoque_movimentos
                    (codigo_barras,codigo_produto_nfe,numero_nota,nome_produto,quantidade,valor_unitario,
                     tipo_movimento,origem_setor,destino_setor,referencia_tipo,referencia_id,usuario_registro)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'Contagem de estoque','Almoxarifado','contagem_estoque',%s,%s)''',
                    (item['codigo_barras'],item['codigo_produto_nfe'],f'CONTAGEM-{cid}',item['nome_produto'],
                     abs(delta),products[item['produto_id']].get('valor_unitario',0),
                     'entrada' if delta > 0 else 'saida',item['id'],services['actor']()))
                cur.execute('UPDATE estoque_contagem_resultados SET movimento_id=%s WHERE id=%s', (cur.lastrowid,item['id']))
            cur.execute("UPDATE estoque_contagens SET status='finalizada', finalizado_em=NOW() WHERE id=%s", (cid,))
            result = fetch(cur,cid)
            conn.commit()
        except Exception:
            conn.rollback()
            app.logger.exception('Falha ao finalizar contagem de estoque; transacao revertida')
            return jsonify(erro='Nao foi possivel finalizar. Os ajustes foram revertidos; tente novamente.'), 500
        finally:
            cur.close(); conn.close()
        try:
            services['after_commit']([item['produto_id'] for item in items], services['actor']())
        except Exception:
            app.logger.exception('Contagem finalizada; falha ao verificar estoque minimo')
            result['aviso'] = 'Contagem salva. Nao foi possivel verificar compras por estoque minimo.'
        return jsonify(result)

    def report(paginate=True):
        clauses = ["c.status='finalizada'"]; args = []
        for key, sign in (('inicio','>='), ('fim','<')):
            raw = request.args.get(key)
            if raw:
                day = dt.date.fromisoformat(raw)
                if key == 'fim': day += dt.timedelta(days=1)
                clauses.append('c.finalizado_em '+sign+' %s'); args.append(day)
        if request.args.get('inicio') and request.args.get('fim') and request.args['inicio'] > request.args['fim']:
            raise ValueError('Data final anterior a inicial.')
        query = request.args.get('q','').strip()
        if query:
            clauses.append('(i.nome_produto LIKE %s OR i.codigo_barras LIKE %s OR i.codigo_produto_nfe LIKE %s OR c.usuario LIKE %s)')
            args.extend(['%'+query+'%']*4)
        kind = request.args.get('tipo','')
        if kind not in ('','desperdicio','sobra','sem_diferenca'):
            raise ValueError('Tipo de divergencia invalido.')
        if kind:
            clauses.append({'desperdicio':'i.desperdicio>0','sobra':'i.sobra>0','sem_diferenca':'i.diferenca=0'}[kind])
        page = max(1, int(request.args.get('pagina',1)))
        limit = 50
        conn = connect(); cur = conn.cursor(dictionary=True)
        base = ' FROM estoque_contagem_resultados i JOIN estoque_contagens c ON c.id=i.contagem_id WHERE '+' AND '.join(clauses)
        try:
            cur.execute('SELECT COUNT(*) total, COALESCE(SUM(i.desperdicio),0) desperdicio, COALESCE(SUM(i.sobra),0) sobra'+base, tuple(args))
            totals = cur.fetchone()
            sql = 'SELECT i.*, c.usuario, c.finalizado_em, c.observacao'+base+' ORDER BY c.finalizado_em DESC,i.id DESC'
            cur.execute(sql + (' LIMIT %s OFFSET %s' if paginate else ''), (*args,limit,(page-1)*limit) if paginate else tuple(args))
            return publico({'itens':cur.fetchall(), 'resumo':totals, 'pagina':page, 'limite':limit})
        finally:
            cur.close(); conn.close()

    @bp.get('/api/estoque/contagens/relatorio')
    @access('estoque_contagem_relatorio')
    def relatorio():
        try: return jsonify(report())
        except (ValueError, OverflowError): return jsonify(erro='Filtros invalidos.'), 400

    @bp.get('/api/estoque/contagens/relatorio/pdf')
    @access('estoque_contagem_relatorio')
    def pdf():
        # O PDF usa uma consulta sem paginacao, com os mesmos filtros do relatorio.
        try:
            rows = report(paginate=False)
        except (ValueError, OverflowError): return jsonify(erro='Filtros invalidos.'), 400
        output=BytesIO(); styles=getSampleStyleSheet()
        doc=SimpleDocTemplate(output,pagesize=landscape(A4),leftMargin=24,rightMargin=24)
        elements=[Paragraph('Contagem de estoque: desperdicio e possiveis erros',styles['Title']),Spacer(1,12),
            Paragraph(f"Desperdicio: {rows['resumo']['desperdicio']} uni | Sobras: {rows['resumo']['sobra']} uni",styles['Normal']),Spacer(1,12)]
        table=[['Contagem / Data','Produto','Saldo','Contado','Desperdicio','Sobra','Responsavel']]
        for item in rows['itens']:
            table.append([Paragraph(escape(str(v)),styles['Normal']) for v in (f"#{item['contagem_id']} / {item['finalizado_em']}",item['nome_produto'],item['saldo_antes'],item['quantidade_contada'],item['desperdicio'],item['sobra'],item['usuario'])])
        rendered=Table(table,colWidths=[130,180,55,55,65,55,150],repeatRows=1)
        rendered.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.lightgrey),('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),.3,colors.grey)]))
        elements.append(rendered); doc.build(elements); output.seek(0)
        return send_file(output,mimetype='application/pdf',download_name='contagens-estoque.pdf')

    app.register_blueprint(bp)
