"""Individual menu grants derived from manifests; no database or app startup."""
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

LABELS = {'dashboards': 'Dashboard', 'workflow': 'Workflow', 'gestao': 'Gestao',
          'cadastros': 'Cadastro', 'relatorios': 'Relatorios', 'import_export': 'Dados',
          'estoque': 'Estoque', 'monitor': 'Monitor', 'config': 'Configurar',
          'docs': 'Documentos', 'vendas': 'Vendas', 'compras': 'Compras'}


def destination(url):
    parts = urlsplit(url)
    path = parts.path.rstrip('/') or '/'
    path = path.replace('/original', '', 1).replace('/apps/riob/embed', '/apps/riob')
    query = [(k, v) for k, v in parse_qsl(parts.query) if k in {'view', 'secao', 'painel', 'visao'}]
    fragment = parts.fragment
    if path == '/apps/chamados' and not any(k == 'view' for k, _ in query): query.append(('view', 'chamados'))
    if path == '/apps/zap/settings' and not any(k == 'secao' for k, _ in query): query.append(('secao', 'estados'))
    if path == '/apps/riob-email/riob' and not any(k == 'painel' for k, _ in query): query.append(('painel', 'resumo'))
    if path == '/apps/riob' and not fragment: fragment = 'dashboard'
    if path == '/config' and not fragment: fragment = 'minha-conta'
    if path == '/apps/tecnologia' and not fragment:
        fragment = 'dashboard'
    if path == '/apps/tecnologia' and fragment == 'backup':
        fragment = 'backup-visao'
    return path + ('?' + urlencode(sorted(query)) if query else '') + ('#' + fragment if fragment else '')


def resource_key(url):
    return 'menu:' + hashlib.sha256(destination(url).encode()).hexdigest()[:24]


def entries(manifest, client):
    definition = (manifest.get('menu_profiles') or {}).get(client, manifest)
    result = {}
    for kind in ('menu_groups', 'config_groups'):
        for group, items in (definition.get(kind) or {}).items():
            if manifest.get('app_key') == 'sistema' and group == 'portal' and client not in {'', 'nanotech', 'cloud'}:
                continue
            group = 'config' if kind == 'config_groups' else group
            for item in items:
                key = resource_key(item['url'])
                row = result.setdefault(key, {
                    'key': key, 'nome': item['nome'], 'url': item['url'], 'grupos': [],
                    'recurso': item.get('recurso') or item.get('permission'),
                    'admin_only': bool(item.get('admin_only')),
                    'authenticated': bool(item.get('authenticated')),
                })
                label = LABELS.get(group, group.capitalize())
                if label not in row['grupos']:
                    row['grupos'].append(label)
    return list(result.values())


def permitted(item, grants, admin=False):
    if admin:
        return True
    if item.get('admin_only'):
        return False
    key = item.get('key') or resource_key(item['url'])
    if '!' + key in grants:
        return False
    if key in grants:
        return True
    return bool(item.get('authenticated') or '*' in grants or item.get('recurso') in grants)


def has_overrides(grants):
    return any(key.startswith(('menu:', '!menu:')) for key in grants)


def zap_setting_destination(key):
    if key.startswith('WHATSAPP_'): section = 'whatsapp'
    elif key.startswith('BACKUP_'): section = 'backup'
    elif key.startswith(('GOOGLE_SHEETS_', 'GOOGLE_SERVICE_ACCOUNT_')): section = 'agenda'
    elif key.startswith('REMINDER_'): section = 'lembretes'
    else: section = 'integracoes'
    return '/apps/zap/settings?secao=' + section


def page_candidates(url, items):
    """Exact task selectors, then contextual subpages of the longest menu path."""
    target = destination(url)
    exact = [item for item in items if destination(item['url']) == target]
    if exact:
        return exact
    path = urlsplit(target).path
    candidates = [item for item in items if not urlsplit(item['url']).fragment
                  and not urlsplit(item['url']).query
                  and len(urlsplit(item['url']).path.strip('/').split('/')) > 2
                  and path.startswith(urlsplit(item['url']).path.rstrip('/') + '/')]
    if candidates:
        longest = max(len(urlsplit(item['url']).path.rstrip('/')) for item in candidates)
        return [item for item in candidates if len(urlsplit(item['url']).path.rstrip('/')) == longest]
    return []


def api_destinations(app, path, method):
    """Tasks using a route. Shared reads may serve several independently allowed tasks."""
    read = method in {'GET', 'HEAD'}
    if app == 'riob':
        p = path.removeprefix('/apps/riob/').removeprefix('api/')
        # Longest prefix wins; no inheritance from an unrelated sibling menu.
        routes = {
            'custo-diario/dashboard': ['custoProdutoDashboard'],
            'custo-diario': ['custoDiario'],
            'custo-produto/dashboard': ['custoProdutoDashboard'],
            'custo-produto': ['custoProduto'],
            'backup': ['config:backup'], 'status': ['config:status'], 'monitor_boot': ['monitor:automacao'],
            'logs_exclusoes': ['config:logs'], 'sip': ['config:sip'], 'nfe': ['config:nfe'],
            'dashboard_estoque': ['dashboard:estoque'], 'dashboard_frota': ['dashboard:frota'],
            'dashboard_processos': ['dashboard:processos'], 'dashboard_compras': ['dashboard:compras'],
            'dashboard': ['dashboard'],
            'dashboard_vendas': ['dashboard:vendas_anual','dashboard:bonificacoes','dashboard:variacao_preco','dashboard:grupos_embalagem'],
            'estoque/relatorio-comprometido': ['relatorios:estoque_comprometido'],
            'estoque/contagens/relatorio': ['relatorios:contagens'], 'estoque/contagens': ['estoque:contagem'],
            'estoque/produtos': ['cadastros:estoque_produtos'], 'estoque/grupos': ['cadastros:estoque_grupos'],
            'estoque/posicao': ['estoque:posicao'], 'estoque/movimentos': ['estoque:movimentar'],
            'estoque': ['estoque:movimentar'], 'estoque/lotes': ['estoque:rastreio'],
            'estoque/rastreabilidade': ['estoque:rastreio'],
            'estoque/movimentar': ['estoque:movimentar'], 'estoque/rastreio': ['estoque:rastreio'],
            'estoque/acerto': ['estoque:acerto'],
            'estoque/importacoes-xml': ['estoque:importar_xml_auto'],
            'estoque/nfe': ['estoque:importar_xml_bipe','estoque:importar_xml_auto'],
            'estoque/conferencias': ['estoque:importar_xml_bipe','estoque:importar_xml_auto'],
            'vendas/orcamentos/config': ['config:orcamentos'],
            'vendas/orcamentos/relatorio': ['relatorios:orcamentos'], 'vendas/orcamentos': ['vendas:orcamento'],
            'vendas/config': ['config:vendas'], 'vendas/cache': ['config:base_vendas'],
            'vendas/sellout': ['workflow:vendas_diario_importar'],
            'vendas/diario/importar': ['workflow:vendas_diario_importar'],
            'vendas/diario/cargas-semana': ['relatorios:cargas_semana'],
            'vendas/diario/dashboard': ['dashboard:vendas_diario'],
            'vendas/diario': ['workflow:vendas_diario'],
            'vendas/relatorio/preco-medio': ['vendas:preco_medio'],
            'vendas/relatorio': ['vendas:relatorio','vendas:relatorio_anual','vendas:variacao_preco','vendas:grupos_embalagem','vendas:preco_medio'],
            'vendas/dashboard': ['dashboard:vendas_anual','dashboard:bonificacoes','dashboard:variacao_preco','dashboard:grupos_embalagem'],
            'vendas/meses': ['vendas:relatorio','vendas:relatorio_anual','dashboard:vendas_anual','dashboard:vendas_diario'],
            'pontos_venda/importar_csv': ['vendas:pontosvenda_importar'],
            'pontos_venda/relatorio': ['vendas:pontosvenda_relatorio'], 'pontos_venda': ['vendas:pontosvenda'],
            'fretes': ['fretes'], 'devolucoes': ['devolucoes'],
            'comissao/lancamentos/exportar-xlsx': ['comissao:exportar'],
            'comissao/relatorios': ['comissao:relatorios'], 'comissao/cadastros': ['cadastros:comissao'],
            'comissao/cidades': ['cadastros:comissao'], 'comissao/lancamentos': ['comissao'],
            'processos-internos/relatorio': ['relatorios:processos'],
            'processos-internos/tipos': ['cadastros:processos_tipos'], 'processos-internos': ['processos'],
            'compras/relatorio': ['relatorios:compras'], 'compras/previsao': ['compras:previsao'],
            'compras/fornecedores': ['cadastros:compras_fornecedores'],
            'compras/produtos': ['cadastros:compras_fornecedores'], 'compras/solicitacoes': ['workflow:compras'],
            'abastecimentos': ['gestaofrota:abastecimento'], 'manutencoes': ['gestaofrota:manutencao'],
            'trocas_oleo': ['gestaofrota:oleo'], 'trocas_pneu': ['gestaofrota:pneu'], 'lavagens': ['gestaofrota:lavagem'],
            'frota_resumo': ['gestaofrota:lista'], 'frota_historico': ['gestaofrota:lista'],
            'frota_relatorio': ['gestaofrota:relatorios'], 'relatorio': ['gestaofrota:relatorios'],
            'veiculos': ['cadastros:veiculos'], 'colaboradores': ['cadastros:colaboradores'],
            'cargas': ['gestaofrota:cargas'], 'escala': ['gestaofrota:escala'],
        }
        for prefix in sorted(routes, key=len, reverse=True):
            if p == prefix or p.startswith(prefix + '/') or (prefix.endswith('/importar') and p.startswith(prefix + '-')):
                views = list(routes[prefix])
                if read and prefix in {'estoque/produtos', 'estoque/posicao', 'estoque/grupos'}:
                    views += ['estoque:contagem','estoque:posicao','estoque:movimentar','estoque:rastreio','estoque:acerto',
                              'estoque:importar_xml_bipe','estoque:importar_xml_auto','vendas:orcamento','compras:previsao','cadastros:estoque_produtos','dashboard:estoque']
                dependencies = {
                    'vendas/orcamentos/config': ['vendas:orcamento'],
                    'vendas/config': ['vendas:orcamento','vendas:relatorio','vendas:relatorio_anual','dashboard:vendas_anual'],
                    'processos-internos/tipos': ['processos'],
                    'compras/fornecedores': ['workflow:compras','compras:previsao'],
                    'comissao/cadastros': ['comissao','comissao:relatorios','comissao:exportar'],
                    'comissao/cidades': ['comissao','fretes','workflow:vendas_diario'],
                }
                if read: views += dependencies.get(prefix, [])
                if read and prefix in {'veiculos','colaboradores'}:
                    views += ['fretes','gestaofrota:registrar','gestaofrota:lista','gestaofrota:manutencao','gestaofrota:abastecimento','gestaofrota:oleo','gestaofrota:pneu','gestaofrota:lavagem','gestaofrota:escala','gestaofrota:cargas','comissao']
                if read and re.fullmatch(r'vendas/orcamentos/\d+/pdf', p): views += ['relatorios:orcamentos']
                if read and prefix == 'comissao/lancamentos': views += ['comissao:relatorios','comissao:exportar','dashboard:comissoes']
                if not read and prefix == 'estoque/produtos' and p.endswith('/ajuste'): views = ['estoque:acerto','cadastros:estoque_produtos']
                return ['/apps/riob#' + view for view in views]
        return []
    if app == 'tecnologia':
        prefix = '/apps/tecnologia#'
        p = path.removeprefix('/apps/tecnologia/api/')
        if p.startswith('backup/'):
            views = ['backup-visao', 'backup-planos', 'backup-agentes'] if read else ['backup-planos']
            if p in {'backup/agent-script', 'backup/windows-installer'}: views = ['backup-agentes']
        elif p == 'network' or p.startswith('network/'): views = ['rede']
        elif p.startswith('alerts/'): views = ['config']
        elif p == 'link-usage-history': views = ['ocupacao-link']
        elif p in {'history', 'speed-history'}: views = ['historico']
        elif p == 'overview': views = ['dashboard', 'monitor-link', 'equipamentos', 'historico', 'ocupacao-link', 'config', 'protocolos', 'descoberta-impressoras', 'descoberta-computadores']
        elif p == 'discover-printers': views = ['descoberta-impressoras']
        elif p == 'discover-computers': views = ['descoberta-computadores']
        elif p.startswith('devices/') and p.endswith('/print-usage'): views = ['dashboard', 'equipamentos']
        elif p.startswith('devices'): views = ['equipamentos', 'descoberta-impressoras', 'descoberta-computadores']
        elif p in {'probe', 'speed-test'}: views = ['dashboard']
        else: return []
        return [prefix + view for view in views]
    if app == 'chamados':
        p = path.removeprefix('/apps/chamados/api/')
        if p == 'bootstrap': views = ['dashboard', 'chamados', 'agenda', 'historico', 'documentos']
        elif p.startswith('agenda'): views = ['agenda']
        elif p.startswith('documents'): views = ['documentos', 'chamados', 'historico'] if read else ['documentos']
        elif p == 'similar': views = ['chamados', 'historico']
        elif p.startswith('tickets'): views = ['chamados', 'historico', 'agenda'] if read else ['chamados', 'historico']
        else: return []
        return ['/apps/chamados?view=' + view for view in views]
    if app == 'automacao':
        p = path.removeprefix('/apps/automacao').replace('/original', '', 1)
        if p.startswith(('/motor/', '/api/leitura', '/api/ultima')): suffixes = ['/motores']
        elif p.startswith('/setor/'): suffixes = ['/setores']
        elif p.startswith(('/api/maquinas', '/maquinas/')): suffixes = ['/maquinas']
        elif p.startswith(('/api/sensores/', '/sensores/drivers/')): suffixes = ['/sensores/drivers']
        elif p == '/api/tempo-real': suffixes = ['/tempo-real']
        elif p.startswith(('/static/documentos/', '/documentacao/arquivos/')): suffixes = ['/documentacao', '/documentacao/cadastrar']
        else: return []
        return ['/apps/automacao' + suffix for suffix in suffixes]
    if app in {'riob-email', 'riob-xml'}:
        p = path.split('/riob', 2)[-1].strip('/')
        if app == 'riob-email':
            mapping = {'importar':'importacao', 'importar-historico-xml':'historico',
                       'recuperar-conteudo':'recuperar', 'status-importacao':'?painel=status',
                       'download':'anexos', 'email':'emails', 'backup':'backup'}
        else:
            mapping = {'importar-com-progresso':'', 'status-importacao':'', 'estoque':'estoque'}
            if p.startswith('abastecimentos/') and not p.endswith('exportar'):
                return ['/apps/riob-xml/riob/abastecimentos?visao=revisao']
        first = p.split('/')[0]
        if first in mapping:
            return ['/apps/' + app + '/riob/' + mapping[first]]
        return []
    if app == 'zap':
        p = path.removeprefix('/apps/zap').replace('/original', '', 1)
        if p.startswith('/api/config/'):
            section = {'states':'estados','departments':'departamentos','labels':'etiquetas','quick-replies':'respostas'}.get(p.split('/')[3])
            return ['/apps/zap/settings?secao=' + section] if section else []
        if p.startswith('/api/database/'): return ['/apps/zap/settings?secao=backup']
        if p.startswith('/api/users'): return ['/apps/zap/settings?secao=usuarios']
        if p.startswith('/api/reminders'): return ['/apps/zap/settings?secao=lembretes']
        if p.startswith('/api/agenda'): return ['/apps/zap/calendar', '/apps/zap/settings?secao=agenda']
        if p.startswith('/api/integrations'): return ['/apps/zap/settings?secao=status']
        if p.startswith(('/api/tickets', '/api/messages', '/api/uploads', '/uploads/', '/api/whatsapp', '/api/dashboard')): return ['/apps/zap']
    return []
