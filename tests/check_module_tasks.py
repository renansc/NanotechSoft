"""Complete portal HTML/CSS/JS; synthetic GET responses, no live probes/writes."""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright
from tests.test_module_tasks import context,automation_page,KEYS
import app as portal
import menu_access

with sync_playwright() as p, mock.patch.object(portal,'configured_client_id',return_value='rio-branco'), mock.patch.object(portal,'current_theme_key',return_value='rio_branco'), mock.patch.object(portal,'get_config',return_value={'tema':'rio_branco'}):
    browser=p.chromium.launch(executable_path='/opt/google/chrome/chrome',headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]
    requests=[]
    tech_resources=['*']
    page.on('pageerror',lambda error:errors.append(str(error)))
    def route_request(route):
        url=urlsplit(route.request.url)
        path=url.path
        requests.append(path)
        assert route.request.method=='GET' or (path=='/apps/tecnologia/api/network/scan' and route.request.method=='POST'), 'No business writes in browser fixture'
        if '/api/' in path:
            data={}
            if '/tecnologia/api/' in path:
                with portal.app.test_request_context(path,method=route.request.method), mock.patch.object(portal,'allowed_app_keys',return_value=set(KEYS)), mock.patch.object(portal,'current_user_or_logout',return_value={'id':42,'perfil':'usuario'}), mock.patch.object(portal,'get_user_permissions',return_value={'tecnologia':set(tech_resources)}):
                    denied=portal.enforce_app_permission()
                assert denied is None, (path,'Tela consultou API sem permissao')
            if path.endswith('/overview'):
                data={'devices':[{'id':7,'nome':'Link teste','tipo':'INTERNET','host':'192.0.2.1','ativo':True,'ultimaMetrica':{'status':'ONLINE'}}],
                      'speed':{'downloadMbps':100,'uploadMbps':50},
                      'linkUsage':{'usagePct':20,'direction':'download','contributors':[{'name':'Estacao teste','host':'192.0.2.2','downloadMbps':20,'uploadMbps':2}]}}
            elif path.endswith('/network'):
                data={'scanAvailable':True,'scanSubnets':['192.168.200.0/24'],'devices':[{'id':7,'nome':'Servidor de arquivos','tipo':'SERVIDOR','host':'192.0.2.7','ativo':True,
                      'ultimaMetrica':{'status':'ONLINE','checkedAt':'2026-09-23T12:00:00Z',
                      'macAddresses':['AA:BB:CC:DD:EE:FF'],'macSource':'ARP',
                      'macObservations':[{'host':'192.0.2.7','mac':'AA:BB:CC:DD:EE:FF','interface':'eno2'}],
                      'telemetry':{'downloadMbps':12.5,'uploadMbps':2.25}}}]}
            elif path.endswith('/network/scan'):
                data={'subnet':'192.168.200.0/24','checkedAt':'2026-09-23T12:00:00Z','devices':[
                    {'ip':'192.168.200.201','mac':'AA:BB:CC:DD:EE:01','name':'<img src=x onerror=alert(1)>'},
                    {'ip':'192.168.200.202','mac':'','name':''}]}
            elif '/network/7' in path:
                data={'date':'2026-09-23','downloadBytes':1048576,'uploadBytes':1048576,'totalBytes':2097152,
                      'measuredFrom':'2026-09-23T03:01:00Z','measuredUntil':'2026-09-23T12:00:00Z'}
            elif path.endswith('/backup/jobs'):
                data={'jobs':[{'id':9,'name':'Plano teste','machine':'Maquina teste','active':True,'health':'ONLINE','times':['08:00'],'databaseType':'FILES','sourcePaths':['/dados']}],
                      'executions':[{'jobName':'Plano teste','status':'SUCCESS','completedAt':'2026-09-15T12:00:00Z','tiers':['diario'],'sizeBytes':1024,'message':'Execucao teste'}]}
            elif path.endswith('/history'):data={'metrics':[{'checkedAt':'2026-09-15T12:00:00Z','status':'ONLINE','message':'Amostra teste','latencyMs':5,'lossPct':0}]}
            elif path.endswith('/speed-history'):data={'metrics':[{'checkedAt':'2026-09-15T12:00:00Z','status':'OK','downloadMbps':100,'uploadMbps':50}]}
            elif path.endswith('/bootstrap'):
                data={'categories':['TI'],'priorities':['MEDIA'],'statuses':['ABERTO'],'interventionTypes':['DIAGNOSTICO'],'users':[],'devices':[],'currentUser':{'id':42},'summary':{'open':0,'inProgress':0,'resolved':0,'minutesSpent':0}}
            elif path.endswith('/tickets'):data={'tickets':[]}
            elif path.endswith('/documents'):data={'documents':[]}
            route.fulfill(json=data);return
        if path.startswith('/static/'):
            f=ROOT/path.lstrip('/')
            route.fulfill(body=f.read_bytes(),content_type='image/svg+xml' if f.suffix=='.svg' else 'text/css' if f.suffix=='.css' else 'text/javascript');return
        key=path.split('/')[2]
        suffix=path.removeprefix('/apps/'+key).strip('/')
        if key in ('tecnologia','chamados') and suffix:
            f=ROOT/'apps'/key/'source'/suffix
            route.fulfill(body=f.read_bytes(),content_type='image/svg+xml' if f.suffix=='.svg' else 'text/css' if f.suffix=='.css' else 'text/javascript');return
        with portal.app.test_request_context(path+('?' + url.query if url.query else '')):
            if key=='automacao':
                style,body=portal.extract_automacao_page(automation_page('/'+suffix))
                active=portal.automacao_active_page(suffix)
            else:
                raw=(ROOT/'apps'/key/'source/index.html').read_text()
                if key=='tecnologia':
                    with mock.patch.object(portal,'get_user_permissions',return_value={'tecnologia':set(tech_resources)}):
                        resources=portal.allowed_resources_for_app({'id':42,'perfil':'usuario'},'tecnologia')
                    raw=raw.replace('class="techApp"','class="techApp" data-resources=\''+json.dumps(resources)+'\'')
                active,body=portal.extract_static_app_integrated(raw,key)
                style=''
            ctx=context()
            if key=='tecnologia' and menu_access.has_overrides(tech_resources):
                user={'id':42,'perfil':'usuario','nome':'Pessoa teste'}
                manifest=portal.menu_manifest('tecnologia')
                with mock.patch.object(portal,'get_user_permissions',return_value={'tecnologia':set(tech_resources)}):
                    ctx=context(user)
                    ctx['menu_access_state']=portal.menu_access_state(user,[manifest])
            html=portal.render_template('integrated_app.html',app_nome=key,app_style=style,app_content=body,active_page=active,**ctx)
        route.fulfill(body=html,content_type='text/html')
    page.route('**/*',route_request)
    total=0
    for width in (1440,390):
        page.set_viewport_size({'width':width,'height':1000})
        for key in KEYS:
            profile=json.loads((ROOT/'apps'/key/'app.json').read_text())['menu_profiles']['rio-branco']
            urls={e['url'] for kind in ('menu_groups','config_groups') for entries in profile[kind].values() for e in entries if e['url'].startswith('/apps/')}
            for url in sorted(urls):
                page.goto('http://tasks.test'+url)
                page.locator('.topbar-logout').wait_for(state='visible')
                assert page.locator('#mainMenu').count()==1
                assert page.locator('.techHero,.techTabs,.ticketHero,.ticketTabs,.sidebar').count()==0
                assert page.locator('.topo h1').inner_text()=='Rio Branco'
                if key!='automacao':
                    cls='.techView' if key=='tecnologia' else '.ticketView'
                    selected=urlsplit(url).fragment if key=='tecnologia' else urlsplit(url).query.split('=')[1]
                    if selected.startswith('backup-'):selected='backup'
                    page.locator(cls+'[data-page="'+selected+'"]').wait_for(state='visible')
                    assert page.locator(cls+':visible').count()==1,(url,'mixed tasks')
                    if key=='tecnologia':
                        assert page.locator('#probeAll').is_visible()==(selected=='dashboard')
                        assert page.locator('#testAlertEmail').is_visible()==(selected=='config')
                        if urlsplit(url).fragment.startswith('backup-'):
                            part=urlsplit(url).fragment.removeprefix('backup-')
                            assert page.locator('[data-backup-sections]:visible').evaluate_all('(els,part)=>els.every(e=>e.dataset.backupSections.split(" ").includes(part))',part)
                    else:assert page.locator('#newTicketButton').is_visible()==(selected=='chamados')
                else:
                    assert page.locator('.automacao-content > h1').count()==1
                    assert page.locator('.topo').evaluate('e=>Math.round(e.getBoundingClientRect().height)')==64
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),(url,width,'horizontal overflow')
                total+=1
        page.goto('http://tasks.test/apps/chamados?view=dashboard')
        page.get_by_role('button',name='Consultar soluções').click()
        page.wait_for_url('**view=historico')
        page.go_back()
        page.locator('.ticketView[data-page=dashboard]').wait_for(state='visible')
        page.goto('http://tasks.test/apps/tecnologia#equipamentos')
        page.get_by_role('button',name='Adicionar equipamento').click()
        page.locator('#deviceModal').wait_for(state='visible')
        page.locator('#cancelDevice').click()
        assert page.evaluate('scrollX')==0,(width,'header scrolled outside viewport')
        page.screenshot(path=f'/tmp/nanotech-tasks-{width}.png')
        tech_resources=['rede']
        requests.clear()
        page.goto('http://tasks.test/apps/tecnologia?fixture=rede-only#rede')
        page.get_by_role('button',name='Servidor de arquivos').click()
        page.locator('#networkUsage').get_by_text('2,0 MB').wait_for()
        assert 'AA:BB:CC:DD:EE:FF' in page.locator('#networkDetails').inner_text()
        assert 'Cache ARP do servidor' in page.locator('#networkDetails').inner_text()
        assert '12,500 Mbps' in page.locator('#networkDetails').inner_text()
        assert '2,250 Mbps' in page.locator('#networkDetails').inner_text()
        assert page.locator('#networkGrid img').evaluate_all('(imgs)=>imgs.every(i=>i.complete && i.naturalWidth>0)')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=f'/tmp/nanotech-network-popup-{width}.png')
        page.keyboard.press('Escape')
        assert not page.locator('#networkDialog').is_visible()
        assert '/apps/tecnologia/api/overview' not in requests
        page.locator('#networkSearch').fill('ausente')
        assert page.locator('#networkGrid button').count()==0
        page.locator('#networkSearch').fill('192.0.2.7')
        assert page.locator('#networkGrid button').count()==1
        page.screenshot(path=f'/tmp/nanotech-network-{width}.png')
        assert not page.locator('#openNetworkScan').is_visible(), page.locator('#openNetworkScan').evaluate('(el)=>({html:el.outerHTML,resources:document.querySelector(".techApp").dataset.resources,display:getComputedStyle(el).display})')
        tech_resources=['rede','rede_scan']
        requests.clear()
        page.goto('http://tasks.test/apps/tecnologia?fixture=rede-scan#rede')
        page.locator('#openNetworkScan').wait_for(state='visible')
        assert '/apps/tecnologia/api/network/scan' not in requests
        page.locator('#openNetworkScan').click()
        page.locator('#networkScanResults tr').first.wait_for()
        assert page.locator('#networkScanResults tr').count()==2
        assert page.locator('#networkScanResults img').count()==0
        assert 'Não disponível' in page.locator('#networkScanResults').inner_text()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('#networkScanDialog').evaluate('(el)=>el.scrollWidth <= el.clientWidth')
        page.screenshot(path=f'/tmp/nanotech-network-scan-{width}.png')
        page.keyboard.press('Escape')
        assert not page.locator('#networkScanDialog').is_visible()
        for resource,url in [('dashboard','#monitor-link'),('backup','#backup-planos'),('backup','#backup-visao'),('historico','#historico')]:
            tech_resources=[resource]
            requests.clear()
            page.goto('http://tasks.test/apps/tecnologia?fixture-resource='+resource+url)
            if resource=='dashboard':
                page.locator('#linkConsumersTable').get_by_text('Estacao teste').wait_for()
                assert page.locator('#linkDownload').inner_text()=='100,0 Mbps'
                assert not page.locator('#alertConfigForm').is_visible()
            elif url=='#backup-planos':
                page.locator('#backupTable').get_by_text('Plano teste').wait_for()
                page.get_by_role('button',name='Forçar backup',exact=True).wait_for()
                page.get_by_role('button',name='Editar',exact=True).click()
                assert page.locator('#backupName').input_value()=='Plano teste'
                page.locator('#cancelBackup').click()
            elif url=='#backup-visao':page.locator('#backupRunsTable').get_by_text('Execucao teste').wait_for()
            else:
                page.locator('#historyTable').get_by_text('Amostra teste').wait_for()
                assert '/apps/tecnologia/api/history' in requests
                assert '/apps/tecnologia/api/speed-history' in requests
            if resource=='backup':assert '/apps/tecnologia/api/overview' not in requests
            page.evaluate("location.hash='#config'")
            page.wait_for_function("document.querySelectorAll('.techView:not(.hidden)').length===0")
        tech_resources=['*']
    # A single checked item must load its real screen and dependencies without '*'.
    entries=menu_access.entries(portal.menu_manifest('tecnologia'),'rio-branco')
    for entry in entries:
        tech_resources=[entry['key']]
        target=urlsplit(entry['url'])
        page.goto('http://tasks.test'+target.path+'?fixture-item='+entry['key']+'#'+target.fragment)
        selected=urlsplit(entry['url']).fragment or 'dashboard'
        if selected.startswith('backup-'):selected='backup'
        page.locator('.techView[data-page="'+selected+'"]').wait_for(state='visible')
        assert not page.locator('#menuAccessDenied').is_visible(),entry['url']
        if selected=='rede':page.locator('#networkGrid button').wait_for()
        elif selected=='backup':page.locator('#backupTable').get_by_text('Plano teste').wait_for(state='attached')
        else:page.wait_for_function('document.querySelector("#monitorState").textContent.includes("Coleta")')
        sibling=next(row for row in entries if row['key']!=entry['key'])
        page.evaluate('(url)=>location.hash=new URL(url,location.origin).hash',sibling['url'])
        page.locator('#menuAccessDenied').wait_for(state='visible')
        assert not page.locator('.content').is_visible()
    assert not errors,errors
    print(f'OK: {total} paginas por tarefa; menu unico, acoes contextualizadas, historico do navegador e popup preservados.')
    browser.close()
