"""Baixas justificadas por perda no mesmo livro de movimentos do estoque."""
import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request
from estoque_contagem import calcular_item, publico, quantidade


MOTIVOS = {
    'desperdicio': 'Desperdício', 'avaria': 'Avaria', 'quebra': 'Quebra',
    'vencimento': 'Vencimento', 'extravio': 'Extravio', 'outros': 'Outros',
}


def hoje():
    return dt.datetime.now(ZoneInfo('America/Sao_Paulo')).date()


def ensure_perdas_schema(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS estoque_perdas (
        id INT AUTO_INCREMENT PRIMARY KEY,
        status VARCHAR(20) NOT NULL DEFAULT 'conferida',
        produto_id INT NOT NULL, produto_key VARCHAR(255) NOT NULL,
        nome_produto VARCHAR(255) NOT NULL,
        codigo_barras VARCHAR(120) NOT NULL DEFAULT '',
        codigo_produto_nfe VARCHAR(120) NOT NULL DEFAULT '',
        unidade VARCHAR(30) NOT NULL, grupo_estoque VARCHAR(80) NOT NULL DEFAULT '',
        data_ocorrencia DATE NOT NULL, motivo VARCHAR(30) NOT NULL,
        justificativa VARCHAR(1000) NOT NULL,
        pallets DECIMAL(12,3) NOT NULL, volumes DECIMAL(12,3) NOT NULL,
        unidades DECIMAL(12,3) NOT NULL, por_pallet DECIMAL(12,3) NOT NULL,
        por_volume DECIMAL(12,3) NOT NULL, quantidade DECIMAL(12,3) NOT NULL,
        saldo_antes DECIMAL(12,3) NOT NULL, saldo_depois DECIMAL(12,3) NOT NULL,
        usuario_id INT NOT NULL, usuario VARCHAR(180) NOT NULL,
        criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finalizado_em DATETIME NULL, movimento_id INT NULL,
        INDEX (data_ocorrencia), INDEX (produto_id), INDEX (status)
    )''')


def register_estoque_perdas(app, services):
    bp = Blueprint('estoque_perdas', __name__)
    connect, snapshot = services['get_conn'], services['snapshot']

    @bp.before_request
    def authorize():
        uid = request.headers.get('X-Usuario-Id', '')
        if not uid.isdigit() or int(uid) <= 0:
            return jsonify(erro='Sessao do portal necessaria.'), 401
        grants = set(request.headers.get('X-Usuario-Recursos', '').split(','))
        if request.headers.get('X-Usuario-Perfil') != 'admin' and not grants.intersection({'*', 'estoque_perdas'}):
            return jsonify(erro='Baixas por perda nao liberadas para este usuario.'), 403

    def fetch(cur, pid, lock=False):
        cur.execute('SELECT * FROM estoque_perdas WHERE id=%s' + (' FOR UPDATE' if lock else ''), (pid,))
        return cur.fetchone()

    @bp.get('/api/estoque/perdas/produtos')
    def produtos():
        conn = connect(); cur = conn.cursor(dictionary=True)
        try:
            cur.execute('SELECT id FROM estoque_produtos WHERE ativo=1 ORDER BY id')
            ids = [p['id'] for p in cur.fetchall()]
            products = snapshot(cur, ids) if ids else {}
            # Cadastros equivalentes compartilham saldo: selecionar uma vez.
            canonical = {}
            for product in products.values():
                canonical.setdefault(product['produto_key'], product)
            return jsonify(publico({'produtos':sorted(canonical.values(), key=lambda p:p['nome_produto']),
                                    'motivos':MOTIVOS, 'hoje':hoje()}))
        finally:
            cur.close(); conn.close()

    @bp.post('/api/estoque/perdas/conferir')
    def conferir():
        data = request.get_json(silent=True)
        try:
            if not isinstance(data, dict):
                raise ValueError('Informe os dados da perda.')
            pid = data.get('produto_id')
            if isinstance(pid, bool) or not str(pid).isdigit() or int(pid) <= 0:
                raise ValueError('Selecione um produto ativo.')
            day = dt.date.fromisoformat(str(data.get('data_ocorrencia', '')))
            if not dt.date(2000, 1, 1) <= day <= hoje():
                raise ValueError('Data da ocorrencia deve estar entre 2000 e hoje.')
            reason = data.get('motivo')
            if not isinstance(reason, str) or reason not in MOTIVOS:
                raise ValueError('Selecione o motivo da baixa.')
            note = data.get('justificativa')
            if not isinstance(note, str) or not 3 <= len(note.strip()) <= 1000:
                raise ValueError('Informe a justificativa, entre 3 e 1000 caracteres.')
        except (ValueError, TypeError) as exc:
            return jsonify(erro=str(exc) if isinstance(exc, ValueError) else 'Dados invalidos.'), 400
        conn = connect(); cur = conn.cursor(dictionary=True)
        try:
            product = snapshot(cur, [int(pid)]).get(int(pid))
            if not product:
                raise ValueError('Produto removido ou indisponivel.')
            conversion = calcular_item(product, data)
            amount = conversion['quantidade_contada']
            before = conversion['saldo_antes']
            if amount <= 0:
                raise ValueError('Informe uma quantidade maior que zero para a perda.')
            if amount > before:
                raise ValueError('A perda supera o saldo atual. Confira o produto e a quantidade.')
            record = {**product, **{k:conversion[k] for k in ('pallets','volumes','unidades','por_pallet','por_volume')},
                      'unidade':product.get('unidade') or 'UN', 'grupo_estoque':product.get('grupo_estoque') or '',
                      'data_ocorrencia':day, 'motivo':reason, 'justificativa':note.strip(),
                      'quantidade':amount, 'saldo_antes':before, 'saldo_depois':before-amount,
                      'usuario_id':int(request.headers['X-Usuario-Id']), 'usuario':services['actor']()}
            fields = ('produto_id','produto_key','nome_produto','codigo_barras','codigo_produto_nfe',
                      'unidade','grupo_estoque','data_ocorrencia','motivo','justificativa',
                      'pallets','volumes','unidades','por_pallet','por_volume','quantidade',
                      'saldo_antes','saldo_depois','usuario_id','usuario')
            cur.execute('INSERT INTO estoque_perdas ('+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',
                        tuple(record[k] for k in fields))
            result = fetch(cur, cur.lastrowid)
            conn.commit()
            return jsonify(publico(result)), 201
        except ValueError as exc:
            conn.rollback(); return jsonify(erro=str(exc)), 400
        except Exception:
            conn.rollback(); app.logger.exception('Falha ao conferir baixa por perda')
            return jsonify(erro='Nao foi possivel conferir a perda. Nenhum saldo foi alterado.'), 500
        finally:
            cur.close(); conn.close()

    @bp.post('/api/estoque/perdas/<int:pid>/finalizar')
    def finalizar(pid):
        conn = connect(); cur = conn.cursor(dictionary=True)
        try:
            conn.start_transaction(isolation_level='REPEATABLE READ')
            item = fetch(cur, pid, lock=True)
            if not item:
                return jsonify(erro='Baixa nao encontrada.'), 404
            if item['usuario_id'] != int(request.headers['X-Usuario-Id']) and request.headers.get('X-Usuario-Perfil') != 'admin':
                return jsonify(erro='Somente o responsavel ou administrador pode confirmar esta baixa.'), 403
            if item['status'] == 'finalizada':
                return jsonify(publico(item))
            # Mesma serializacao usada na contagem, abrangendo movimentos legados.
            cur.execute('SELECT id FROM estoque_movimentos ORDER BY id FOR UPDATE')
            cur.fetchall()
            product = snapshot(cur, [item['produto_id']], lock=True).get(item['produto_id'])
            if (not product or product['produto_key'] != item['produto_key']
                    or Decimal(str(product['saldo'])) != Decimal(str(item['saldo_antes']))
                    or quantidade(product['por_pallet']) != quantidade(item['por_pallet'])
                    or quantidade(product['por_volume']) != quantidade(item['por_volume'])):
                conn.rollback()
                return jsonify(erro='Estoque ou embalagem mudou. Volte e confira a perda novamente.'), 409
            cur.execute('''INSERT INTO estoque_movimentos
                (codigo_barras,codigo_produto_nfe,numero_nota,nome_produto,quantidade,valor_unitario,
                 tipo_movimento,origem_setor,destino_setor,referencia_tipo,referencia_id,usuario_registro)
                VALUES (%s,%s,%s,%s,%s,%s,'saida','Estoque','Baixa por perda','perda_estoque',%s,%s)''',
                (item['codigo_barras'],item['codigo_produto_nfe'],f'PERDA-{pid}',item['nome_produto'],
                 item['quantidade'],product.get('valor_unitario',0),pid,services['actor']()))
            cur.execute("UPDATE estoque_perdas SET status='finalizada', finalizado_em=NOW(), movimento_id=%s WHERE id=%s",
                        (cur.lastrowid,pid))
            result = publico(fetch(cur,pid))
            conn.commit()
        except Exception:
            conn.rollback(); app.logger.exception('Falha ao finalizar baixa por perda; transacao revertida')
            return jsonify(erro='Nao foi possivel confirmar. A baixa foi revertida; tente novamente.'), 500
        finally:
            cur.close(); conn.close()
        try:
            services['after_commit']([item['produto_id']], services['actor']())
        except Exception:
            app.logger.exception('Perda salva; falha ao verificar estoque minimo')
            result['aviso'] = 'Baixa salva. Nao foi possivel verificar compras por estoque minimo.'
        return jsonify(result)

    @bp.get('/api/estoque/perdas')
    def listar():
        clauses = ["status='finalizada'"]; args = []
        try:
            bounds = {}
            for field, sign in (('inicio','>='),('fim','<=')):
                if request.args.get(field):
                    bounds[field] = dt.date.fromisoformat(request.args[field])
                    clauses.append('data_ocorrencia '+sign+' %s'); args.append(bounds[field])
            if len(bounds) == 2 and bounds['inicio'] > bounds['fim']:
                raise ValueError()
            reason = request.args.get('motivo','')
            if reason:
                if reason not in MOTIVOS: raise ValueError()
                clauses.append('motivo=%s'); args.append(reason)
            query = request.args.get('q','').strip()
            if query:
                clauses.append('(nome_produto LIKE %s OR codigo_produto_nfe LIKE %s OR codigo_barras LIKE %s OR justificativa LIKE %s OR usuario LIKE %s)')
                args.extend(['%'+query+'%']*5)
            page = int(request.args.get('pagina',1))
            if page < 1: raise ValueError()
        except (ValueError, TypeError):
            return jsonify(erro='Filtros invalidos. Confira datas, motivo e pagina.'), 400
        conn = connect(); cur = conn.cursor(dictionary=True)
        base = ' FROM estoque_perdas WHERE '+' AND '.join(clauses)
        try:
            cur.execute('SELECT COUNT(*) total'+base, tuple(args))
            total = cur.fetchone()['total']
            cur.execute('SELECT unidade,SUM(quantidade) quantidade'+base+' GROUP BY unidade ORDER BY unidade',tuple(args))
            summary = cur.fetchall()
            cur.execute('SELECT *'+base+' ORDER BY data_ocorrencia DESC,id DESC LIMIT %s OFFSET %s', (*args,50,(page-1)*50))
            return jsonify(publico({'itens':cur.fetchall(),'total':total,'totais_unidade':summary,'pagina':page,'limite':50}))
        finally:
            cur.close(); conn.close()

    app.register_blueprint(bp)
