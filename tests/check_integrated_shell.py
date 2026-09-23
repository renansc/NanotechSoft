"""Browser regression: real proxy/blueprints, synthetic rows, no business writes."""
import sys
from pathlib import Path
from urllib.parse import urlsplit
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from tests.test_riob_xml_proxy import RiobXmlProxyTests
import app as portal
import legacy_services

fixture = RiobXmlProxyTests()
fixture.setUp()
fixture.permissions = {'riob-xml': {'*'}, 'riob-email': {'operacao', 'backup'}}

try:
    with sync_playwright() as p, mock.patch.object(legacy_services, '_storage_used_bytes', return_value=0), mock.patch.object(legacy_services, '_email_accounts', return_value=[]):
        browser = p.chromium.launch(executable_path='/opt/google/chrome/chrome', headless=True, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            url = urlsplit(route.request.url)
            path = url.path + ('?' + url.query if url.query else '')
            assert route.request.method == 'GET', 'Fixture never submits writes'
            if url.path.startswith('/static/'):
                source = ROOT / url.path.lstrip('/')
                route.fulfill(body=source.read_bytes(), content_type='text/css' if source.suffix == '.css' else 'application/javascript')
            elif url.path == '/config':
                with portal.app.test_request_context(path):
                    body = portal.render_template('config.html', **fixture.context(), themes=portal.THEMES,
                                                  client_config={'source': {'path': 'fixture'}, 'clients': [], 'catalog': []}, deployment={'readOnly': False}, can_manage_logo=fixture.user['perfil'] == 'admin')
                route.fulfill(body=body, content_type='text/html')
            elif url.path.startswith('/api/'):
                route.fulfill(body='{}', content_type='application/json')
            else:
                response = fixture.client.get(path, headers={'Sec-Fetch-Dest': route.request.headers.get('sec-fetch-dest', 'document')})
                route.fulfill(body=response.data, status=response.status_code,
                              headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length', 'set-cookie')})

        page.route('**/*', respond)
        for width in (1440, 390, 320):
            page.set_viewport_size({'width': width, 'height': 1000})
            page.goto('http://shell.test/apps/riob-xml/riob/estoque')
            page.locator('.topbar-logout').wait_for(state='visible')
            frame = page.frame_locator('#riobIntegratedFrame')
            assert frame.locator('nav').count() == 0
            assert frame.get_by_role('heading', name='Estoque', exact=False).count() == 1
            frame.locator('input[name=q]').fill('PET')
            frame.get_by_role('button', name='Buscar').click()
            page.wait_for_url('**/estoque?q=PET')
            assert page.locator('.topo h1').inner_text() == 'Rio Branco'
            assert page.locator('#riobIntegratedFrame').count() == 1
            assert page.frame_locator('#riobIntegratedFrame').locator('input[name=q]').input_value() == 'PET'
            for locator in ('.user-settings-link', '.topbar-user-name', '.topbar-logo', '.topbar-logout'):
                box = page.locator(locator).bounding_box()
                assert box and box['x'] >= 0 and box['x'] + box['width'] <= width + 1, (width, locator, box)
            title = page.locator('.topo h1')
            assert title.evaluate('e => e.scrollWidth <= e.clientWidth'), (width, 'deploy title clipped')
            if page.locator('[data-menu-toggle]').is_visible():
                page.locator('[data-menu-toggle]').click()
            section = page.locator('[data-menu-section=gestao]')
            section.hover()
            page.locator('[data-menu] a[href="/apps/riob-email/riob/emails"]').click()
            page.wait_for_url('**/emails')
            assert page.locator('.topo h1').inner_text() == 'Rio Branco'
            assert page.frame_locator('#riobIntegratedFrame').locator('header,nav').count() == 0
            page.locator('.user-settings-link').click()
            page.wait_for_url('**/config#minha-conta')
            assert page.locator('.topo h1').inner_text() == 'Rio Branco'
            assert page.locator('.topbar-user-name').inner_text() == 'Pessoa teste'
            assert page.locator('[data-config-view]:visible').count() == 1
            page.goto('http://shell.test/config#temas')
            assert page.locator('[data-config-view]:visible').evaluate_all("els => els.every(e => e.dataset.configView === 'temas')")
            page.goto('http://shell.test/config#minha-conta')
        fixture.user['perfil'] = 'admin'
        page.reload()
        for task in ('minha-conta', 'temas', 'logo', 'usuarios', 'clientes', 'backup'):
            page.goto('http://shell.test/config#' + task)
            page.locator('[data-config-view="' + task + '"]').first.wait_for(state='visible')
            assert page.locator('[data-config-view]:visible').evaluate_all('(els, task) => els.every(e => e.dataset.configView === task)', task)
        page.goto('http://shell.test/config#minha-conta')
        assert not errors, errors
        page.screenshot(path='/tmp/nanotech-shell-mobile.png')
        browser.close()
        print('OK: estoque, filtro GET, menu Email, Minha conta; cabecalho unico em 1440/390/320px.')
finally:
    fixture.doCleanups()
