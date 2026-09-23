"""Inventory navigation statically; never starts apps or calls business routes."""
import ast
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import menu_access
SOURCES = ['app.py', 'apps/riob/source/server.py', 'apps/riob/source/legacy_services.py',
           'apps/riob/source/gestao_processos_compras.py', 'apps/riob/source/estoque_contagem.py',
           'apps/automacao/source/app.py', 'apps/zap/source/app/routes.py']
ACTIVE = ['riob', 'riob-email', 'riob-xml', 'automacao', 'chamados', 'tecnologia', 'zap']


def menu_entries():
    rows=[]
    for key in ACTIVE:
        manifest=json.loads((ROOT/'apps'/key/'app.json').read_text())
        profile=manifest['menu_profiles']['rio-branco']
        for kind in ('menu_groups','config_groups'):
            for group, entries in profile[kind].items():
                rows.extend(dict(app=key,grupo=group,nome=e['nome'],url=e['url'],recurso=e.get('recurso','*')) for e in entries)
    return rows


def access_catalog_rows():
    rows = []
    for key in [*ACTIVE, 'sistema']:
        path = ROOT/'portal.app.json' if key == 'sistema' else ROOT/'apps'/key/'app.json'
        manifest = json.loads(path.read_text())
        for entry in menu_access.entries(manifest, 'rio-branco'):
            rows.append(dict(app=key, categorias=' / '.join(entry['grupos']), nome=entry['nome'],
                             url=entry['url'], recurso_menu=entry['key'],
                             recurso_herdado=entry['recurso'] or '',
                             restricao='administrador' if entry['admin_only'] else 'individual'))
    return rows


def routes():
    for filename in SOURCES:
        tree=ast.parse((ROOT/filename).read_text())
        for node in ast.walk(tree):
            if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)): continue
            for decorator in node.decorator_list:
                if not isinstance(decorator,ast.Call) or not isinstance(decorator.func,ast.Attribute): continue
                method=decorator.func.attr
                if method not in ('route','get','post','put','patch','delete') or not decorator.args: continue
                if not isinstance(decorator.args[0],ast.Constant): continue
                path=decorator.args[0].value
                if filename.endswith('legacy_services.py'):
                    path=('/importar-xml' if ast.unparse(decorator.func.value)=='XML_BP' else '/gestor-emails')+path
                methods=next((ast.literal_eval(k.value) for k in decorator.keywords if k.arg=='methods'),['GET'] if method=='route' else [method.upper()])
                yield dict(arquivo=filename,linha=node.lineno,funcao=node.name,metodos=','.join(methods),rota=path)


def owner(row):
    file,path=row['arquivo'],row['rota']
    if file=='app.py':
        for app in ['nanoponto','nanostore','gpsmusical','bpa','tatoo','financeiro']:
            if path.startswith('/apps/'+app) or (app=='financeiro' and path.startswith('/api/finance')):
                return 'fora_do_contrato','Modulo desativado no Rio Branco'
        for key in ['chamados','tecnologia']:
            if path.startswith('/apps/'+key):
                if key=='chamados':
                    view='agenda' if '/agenda' in path else 'documentos' if '/documents' in path else 'historico' if '/similar' in path else 'chamados'
                    return 'acao_da_tela','/apps/chamados?view='+view
                view='backup-planos' if '/backup/' in path else 'config' if '/alerts/' in path else 'equipamentos' if any(x in path for x in ['/devices','/discovery']) else 'historico' if '/history' in path else 'ocupacao-link' if '/link-usage' in path else 'dashboard'
                return 'acao_da_tela','/apps/tecnologia#'+view
        if path.startswith('/api/usuarios') or path.startswith('/api/config'):return 'acao_da_tela','/config'
        if path.startswith('/api/backup'):return 'acao_da_tela','/config'
        if path.startswith('/apps/') or path.startswith('/workflow/'):return 'infraestrutura','Proxy/menu do modulo; destino depende do parametro'
        if path in ['/','/config'] or path.startswith('/cloud/'):return 'infraestrutura','Entrada do cliente / Configurar'
        return 'infraestrutura','Sessao unica, contrato, catalogo ou verificacao de saude'
    if 'automacao' in file:
        if 'documentacao' in path:dest='/documentacao'
        elif 'sensores' in path:dest='/sensores/drivers'
        elif 'maquinas' in path:dest='/maquinas'
        elif 'setor' in path:dest='/setores'
        elif 'historico' in path:dest='/historico'
        elif 'alarmes' in path:dest='/alarmes'
        elif 'tempo-real' in path:dest='/tempo-real'
        elif 'motor' in path or 'leitura' in path or 'ultima' in path:dest='/motores'
        else:dest='/'
        return 'acao_da_tela','/apps/automacao'+dest
    if '/zap/' in file:
        if path.startswith(('/login','/logout','/webhooks','/integrations/','/public/')):return 'integracao','Sessao/WhatsApp/Google; nao e pagina de menu'
        if path.startswith(('/settings','/api/settings','/api/config','/api/users','/api/database','/api/integrations','/api/reminders')):dest='/settings'
        elif path.startswith(('/calendar','/agenda','/api/agenda')):dest='/calendar'
        elif path.startswith('/docs'):dest='/docs'
        else:dest=''
        return 'acao_da_tela','/apps/zap'+dest
    if path.startswith('/importar-xml'):
        suffix=path.removeprefix('/importar-xml').strip('/').split('/')[0]
        dest=suffix if suffix in ['estoque','abastecimentos','arquivos','config'] else ''
        return 'acao_da_tela','/apps/riob-xml/riob'+('/'+dest if dest else '')
    if path.startswith('/gestor-emails'):
        suffix=path.removeprefix('/gestor-emails').strip('/').split('/')[0]
        dest={'importar-historico-xml':'historico','recuperar-conteudo':'recuperar','download':'anexos','email':'emails'}.get(suffix,suffix)
        if dest in ['','importar','status-importacao']:return 'acao_da_tela','/apps/riob-email/riob/?painel=resumo'
        return 'acao_da_tela','/apps/riob-email/riob/'+dest
    if path.startswith('/monitor/'):
        return ('fora_do_contrato','Modulo desativado no Rio Branco') if not path.startswith('/monitor/automacao') else ('acao_da_tela','/apps/riob#monitor:automacao')
    if path.startswith('/docs'):return 'acao_da_tela','/apps/riob/docs/'
    if not path.startswith('/api/'):return 'infraestrutura','Shell RioB ou arquivo estatico'
    resource=path.split('/')[2]
    by_resource={
        'dashboard':'dashboard','dashboard_estoque':'dashboard:estoque','dashboard_vendas':'dashboard:vendas_anual',
        'dashboard_frota':'dashboard:frota','dashboard_processos':'dashboard:processos','dashboard_compras':'dashboard:compras',
        'status':'config:status','monitor_boot':'monitor:automacao','backup':'config:backup','logs_exclusoes':'config:logs',
        'sip':'config:sip','nfe':'config:nfe','app':'config:status','ca':'config:sip','certs.p12':'config:sip','certs.pfx':'config:sip',
        'fretes':'fretes','estoque':'estoque:posicao','abastecimentos':'gestaofrota:abastecimento','manutencoes':'gestaofrota:manutencao',
        'devolucoes':'devolucoes','pontos_venda':'vendas:pontosvenda','comissao':'comissao','vendas':'vendas:relatorio',
        'escala':'gestaofrota:escala','cargas':'gestaofrota:cargas','trocas_oleo':'gestaofrota:oleo','trocas_pneu':'gestaofrota:pneu',
        'lavagens':'gestaofrota:lavagem','frota_relatorio':'gestaofrota:relatorios','frota_resumo':'gestaofrota:lista','frota_historico':'gestaofrota:lista',
        'relatorio':'gestaofrota:escala','processos-internos':'processos','compras':'workflow:compras',
    }
    if resource in ['me','chat','agent']:return 'acao_contextual','Minha conta / balao Comunicacao (Chat, IA e Telefonia)'
    if resource=='<tabela>':return 'acao_contextual','Cadastro > Colaboradores/Veiculos/Cargas; escala usa os mesmos registros'
    if resource not in by_resource:return 'sem_associacao',''
    dest=by_resource[resource]
    # More specific tasks override their operational family.
    overrides={'/api/estoque/contagens/relatorio':'relatorios:contagens','/api/estoque/contagens/':'estoque:contagem',
      '/api/vendas/orcamentos/relatorio':'relatorios:orcamentos','/api/vendas/orcamentos':'vendas:orcamento',
      '/api/vendas/diario/cargas-semana':'relatorios:cargas_semana','/api/vendas/diario':'workflow:vendas_diario',
      '/api/compras/relatorio':'relatorios:compras','/api/compras/fornecedores':'cadastros:compras_fornecedores',
      '/api/compras/previsao':'compras:previsao','/api/processos-internos/relatorio':'relatorios:processos',
      '/api/processos-internos/tipos':'cadastros:processos_tipos'}
    for prefix,value in sorted(overrides.items(),key=lambda item:-len(item[0])):
        if path.startswith(prefix):dest=value;break
    return 'acao_da_tela','/apps/riob#'+dest


def inventory():
    result=[]
    for row in routes():
        kind,dest=owner(row)
        result.append({**row,'tipo':kind,'acesso':dest})
    return result


def main():
    rows=inventory()
    target=ROOT/'docs/AUDITORIA_ROTAS_RIO_BRANCO.csv'
    with target.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    catalog = access_catalog_rows()
    with (ROOT/'docs/MAPA_ACESSOS_MENU.csv').open('w', newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(catalog[0]));writer.writeheader();writer.writerows(catalog)
    frontend=ROOT/'apps/riob/source'
    html=(frontend/'RioBranco.html').read_text()
    js='\n'.join(p.read_text() for p in frontend.glob('*.js'))
    handlers=re.findall(r'on(?:click|change|submit|input)="([^"]+)"',html)
    functions=sorted({n for code in handlers for n in re.findall(r'(?<![.\w])([A-Za-z_$][\w$]*)\s*\(',code) if n!='if'})
    missing=[name for name in functions if not re.search(r'(?:function\s+'+re.escape(name)+r'\s*\(|\b'+re.escape(name)+r'\s*=)',js)]
    print(json.dumps({'rotas':len(rows),'classificacao':dict(Counter(r['tipo'] for r in rows)),
      'atalhos':len(menu_entries()),'controles_menu':len(catalog),'eventos_html':len(handlers),'funcoes_html':len(functions),'funcoes_ausentes':missing},ensure_ascii=False))
    unknown=[row for row in rows if row['tipo']=='sem_associacao'];print('Sem associacao:',unknown)
    return bool(unknown or missing)

if __name__=='__main__':raise SystemExit(main())
