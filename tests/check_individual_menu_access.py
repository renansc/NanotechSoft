"""Real Config UI, synthetic accounts and saved choices; no live business writes."""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright
import app as portal
import menu_access

keys=['riob','automacao','tecnologia','chamados','riob-email','riob-xml','zap']
apps=[portal.normalize_app(json.loads((ROOT/'apps'/key/'app.json').read_text())) for key in keys]
admin={'id':1,'nome':'Administrador teste','perfil':'admin'}
user={'id':42,'nome':'Pessoa teste','login':'pessoa','perfil':'usuario','ativo':True,
      'permissoes':{key:['*'] for key in keys},'permissoes_menu':{}}
key=menu_access.resource_key('/apps/tecnologia#backup-agentes')
saved=[]
with mock.patch.object(portal,'configured_client_id',return_value='rio-branco'),mock.patch.object(portal,'list_apps',return_value=apps),sync_playwright() as p:
    catalog=portal.permission_catalog()
    context=dict(usuario=admin,config={'tema':'rio_branco'},themes=portal.THEMES,deploy_name='Rio Branco',
                 menu=portal.menu_sections(apps,admin),system_config=portal.system_manifest()['config_groups']['sistema'],
                 can_manage_logo=True,show_portal=False,deployment={'readOnly':False},
                 client_config={'source':{'path':'fixture'},'clients':[],'catalog':[]})
    browser=p.chromium.launch(executable_path='/opt/google/chrome/chrome',headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def respond(route):
        url=urlsplit(route.request.url)
        if url.path.startswith('/static/'):
            source=ROOT/url.path.lstrip('/')
            route.fulfill(body=source.read_bytes(),content_type='text/css' if source.suffix=='.css' else 'application/javascript')
        elif url.path.startswith('/api/usuarios'):
            if route.request.method=='PUT':
                payload=route.request.post_data_json;saved.append(payload)
                user['permissoes_menu']=payload['permissoes_menu']
                user['permissoes']=payload['permissoes']
            route.fulfill(json={'usuarios':[user],'catalogo_acessos':catalog,'nanostore_perfis':[]})
        elif url.path=='/config':
            with portal.app.test_request_context('/config'):
                body=portal.render_template('config.html',**context)
            route.fulfill(body=body,content_type='text/html')
        else:route.fulfill(json={})
    page.route('**/*',respond)
    for width in (1920,1440,768,390):
        page.set_viewport_size({'width':width,'height':1000})
        page.goto('http://menu.test/config#usuarios')
        choices=page.locator('input[data-access-menu]')
        page.wait_for_function('document.querySelectorAll("input[data-access-menu]").length>100')
        assert choices.count()==sum(len(a['menus']) for a in catalog)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),(width,'horizontal overflow')
        panel=page.locator('[data-user-admin]').bounding_box()
        assert panel['width'] >= width-50,(width,'panel does not fill page',panel)
        checkbox=choices.first.bounding_box()
        assert checkbox['width']==18,(width,'checkbox stretched')
        page.screenshot(path=f'/tmp/nanotech-users-layout-{width}.png')
        search=page.locator('[data-user-menu-search]');search.fill('Instalar agentes')
        assert page.locator('[data-user-permissions-list] > fieldset:visible').count()==1
        target=page.locator('input[data-access-menu="'+key+'"]')
        target.uncheck()
        page.get_by_role('button',name='Salvar usuario',exact=True).click()
        page.wait_for_function('document.querySelector("#userAdminMsg").textContent.includes("salvo")')
        assert saved[-1]['permissoes_menu']['tecnologia'][key] is False
        assert saved[-1]['permissoes']['tecnologia']==['*']
        page.reload();target.wait_for();assert not target.is_checked()
        other=menu_access.resource_key('/apps/tecnologia#backup-planos')
        assert page.locator('input[data-access-menu="'+other+'"]').is_checked()
        page.screenshot(path=f'/tmp/nanotech-menu-access-{width}.png',full_page=True)
    # Global fragment guard must also reject direct hash entry and browser history.
    state=[{'url':'/apps/tecnologia#backup-planos','allowed':True}, {'url':'/apps/tecnologia#backup-agentes','allowed':False}]
    page.unroute('**/*');page.route('**/*',lambda r:r.fulfill(body='<main class="content">Tarefa</main><script id="menuAccessState" type="application/json">'+json.dumps(state)+'</script>',content_type='text/html'))
    page.goto('http://menu.test/apps/tecnologia#backup-agentes')
    page.add_style_tag(path=str(ROOT/'static/style.css'));page.add_script_tag(path=str(ROOT/'static/menu-access.js'))
    assert not page.locator('main').is_visible()
    page.evaluate("location.hash='#backup-planos'")
    page.locator('main').wait_for(state='visible')
    page.go_back();page.locator('#menuAccessDenied').wait_for(state='visible')
    assert not page.locator('main').is_visible()
    # RioB has direct body sections instead of a main.content wrapper.
    upstream=mock.MagicMock()
    upstream.__enter__.return_value=mock.Mock(status=200,headers={'Content-Type':'text/html'},
        read=lambda:b'<html><head></head><body><section class="section">Cadastro</section></body></html>')
    riob_key=menu_access.resource_key('/apps/riob#cadastros:veiculos')
    with portal.app.test_request_context('/apps/riob/embed'),mock.patch.object(portal,'current_user_or_logout',return_value={'id':42,'perfil':'usuario'}),mock.patch.object(portal,'get_user_permissions',return_value={'riob':{'*','!'+riob_key}}),mock.patch.object(portal,'RIOB_BASE_URL','http://riob.test'),mock.patch.object(portal,'open_riob_request',return_value=upstream),mock.patch.object(portal,'apply_standalone_theme',side_effect=lambda text:text):
        embedded=portal.riob_proxy_response(embedded=True).get_data(as_text=True)
    page.unroute('**/*')
    def embedded_route(route):
        if '/static/menu-access.js' in route.request.url:
            route.fulfill(body=(ROOT/'static/menu-access.js').read_bytes(),content_type='application/javascript')
        else:route.fulfill(body=embedded,content_type='text/html')
    page.route('**/*',embedded_route)
    page.goto('http://menu.test/apps/riob/embed#cadastros:veiculos')
    assert not page.locator('.section').is_visible()
    page.evaluate("history.pushState(null,'','#dashboard')")
    assert page.locator('.section').is_visible()
    page.evaluate("history.replaceState(null,'','#cadastros:veiculos')")
    assert not page.locator('.section').is_visible()
    assert not errors,errors
    print(f'OK: {sum(len(a["menus"]) for a in catalog)} itens, busca, bloqueio individual, gravacao e recarga em desktop/celular; hash direto bloqueado.')
    browser.close()
