"""Browser fixtures: no production database, imports, calls or backups."""
import json
import re
import sys
from pathlib import Path
from unittest import mock

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as portal


def clean_html(path):
    html = path.read_text()
    return re.sub(r'<(?:script\b[^>]*>.*?</script|link\b[^>]*)>', '', html, flags=re.S)


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/opt/google/chrome/chrome', headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    html = clean_html(ROOT / 'apps/riob/source/RioBranco.html')
    page.route('**/*', lambda route: route.fulfill(body=html, content_type='text/html'))
    page.goto('http://menu.test')
    page.add_style_tag(path=str(ROOT / 'apps/riob/source/style.css'))
    page.add_script_tag(path=str(ROOT / 'apps/riob/source/script.js'))
    page.evaluate('''() => {
      window.onload = null;
      window.testRequests=[];
      usuarioLogado={id:42,perfil:'usuario'};
      ensureProdutosEstoqueCache=async()=>{
        estoqueState.cadastroProdutos=[{id:7,nome_produto:'Produto teste',codigo_barras:'777',
          quantidade_atual:130,pallet_meta:{unidades_por_pallet:100,unidades_por_volume:10}}];
      };
      _saldoProdutoCadastroAtual=()=>130;
      apiFetch=async(url,options={})=>{
        window.testRequests.push([url,options.method || 'GET']);
        return {ok:true,json:async()=>url.includes('orcamentos/relatorio') ? {
          total:51,pagina:url.includes('pagina=2')?2:1,limite:50,valor_real:500,
          orcamentos:[{id:1,codigo:'ORC-2026-000001',data_ref:'2026-09-10',cliente_nome:'Cliente <b>teste</b>',cidade:'Cidade',vendedor_nome:'Pessoa',valor_bruto:110,valor_liquido:90,valor_real:100}]
        } : []};
      };
      openEstoqueView(null,'contagem');
    }''')
    page.wait_for_function("document.querySelector('#estoqueContagemBody tr[data-id]')")
    assert page.locator('#estoqueViewContagem').is_visible()
    assert not page.locator('#estoqueViewAcerto').is_visible()
    assert page.locator('[data-total]').inner_text() == 'Nao contado'
    page.locator('#estoqueContagemBody input[aria-label=pallets]').fill('1')
    page.locator('#estoqueContagemBody input[aria-label=volumes]').fill('2')
    page.locator('#estoqueContagemBody input[aria-label=unidades]').fill('3')
    assert page.locator('[data-total]').inner_text() == '123'
    assert page.locator('[data-diferenca]').inner_text() == '-7'
    page.locator('#estoqueContagemBusca').fill('inexistente')
    page.locator('#estoqueContagemBusca').fill('')
    assert page.locator('#estoqueContagemBody input[aria-label=pallets]').input_value() == '1'
    with page.expect_download() as download:
        page.get_by_role('button', name='Exportar contagem CSV').click()
    csv = Path(download.value.path()).read_text(encoding='utf-8-sig')
    assert '"123";"-7"' in csv
    page.locator('#estoqueContagemBody input[aria-label=unidades]').fill('-1')
    assert page.locator('[data-total]').inner_text() == 'Quantidade invalida'
    assert all(method == 'GET' for _, method in page.evaluate('window.testRequests'))
    page.evaluate("openRelatoriosView(null,'orcamentos')")
    page.wait_for_function("document.querySelector('#relOrcBody').textContent.includes('ORC-2026')")
    assert page.locator('#relatoriosViewOrcamentos').is_visible()
    assert not page.locator('#relatoriosViewEstoqueComprometido').is_visible()
    assert page.locator('#relOrcBody b').count() == 0
    assert page.locator('#relOrcAnterior').is_disabled()
    page.locator('#relOrcProxima').click()
    page.wait_for_function('relatorioOrcamentosPagina === 2')
    assert page.locator('#relOrcProxima').is_disabled()
    page.screenshot(path='/tmp/menu-orcamentos.png')
    assert not errors, errors

    # Split backup links select exactly the intended existing panel.
    html = clean_html(ROOT / 'apps/tecnologia/source/index.html')
    page.goto('http://menu.test/tecnologia')
    tech_script = (ROOT / 'apps/tecnologia/source/app.js').read_text()
    page.evaluate('(source)=>{new Function(source)}', tech_script)
    function = tech_script[tech_script.index('  function setView('):tech_script.index('  function openDevice(')]
    page.add_script_tag(content='const $=s=>document.querySelector(s), $$=s=>Array.from(document.querySelectorAll(s)); const loadBackups=()=>{},loadHistory=()=>{},loadLinkUsageReport=()=>{};'+function)
    for section in ('visao','planos','agentes'):
        page.evaluate('(section)=>setView("backup-"+section)', section)
        for element in page.locator('[data-backup-sections]').all():
            assert ('hidden' not in element.get_attribute('class').split()) == (element.get_attribute('data-backup-sections') == section)

    # Actual portal template and CSS, with desktop and compact menu behavior.
    keys = ('riob','riob-email','riob-xml','automacao','chamados','tecnologia','zap')
    apps = [portal.normalize_app(json.loads((ROOT/'apps'/key/'app.json').read_text())) for key in keys]
    with portal.app.test_request_context(), mock.patch.object(portal,'configured_client_id',return_value='rio-branco'):
        menu = portal.menu_sections(apps, {'id':1,'nome':'Administrador','perfil':'admin'})
        header = portal.render_template('_topbar.html', menu=menu, usuario={'id':1,'nome':'Administrador','perfil':'admin'}, topbar_title='NanotechSoft')
    html = '<!doctype html><html><head><meta charset="utf-8"></head><body class="theme-rio_branco">'+header+'</body></html>'
    page.goto('http://menu.test/header')
    page.add_style_tag(path=str(ROOT/'static/style.css'))
    page.add_script_tag(path=str(ROOT/'static/app.js'))
    page.evaluate("document.dispatchEvent(new Event('DOMContentLoaded'))")
    page.wait_for_timeout(300)
    assert page.locator('[data-menu-section]').count() == 10
    for width in (1440,390):
        page.set_viewport_size({'width':width,'height':1000})
        page.wait_for_timeout(200)
        if page.locator('[data-menu-toggle]').is_visible():
            page.locator('[data-menu-toggle]').click()
        assert page.locator('[data-menu]').is_visible()
        assert page.locator('[data-logout]:visible').count() >= 1
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=f'/tmp/menu-header-{width}.png')
    assert not errors, errors
    print('OK: contagem, CSV, divergencias, relatorio paginado, visoes de backup e menu desktop/mobile.')
    browser.close()
