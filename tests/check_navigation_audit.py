"""Exercise every RioB menu destination without network or database writes."""
import json
import re
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as portal

manifest = json.loads((ROOT/'apps/riob/app.json').read_text())['menu_profiles']['rio-branco']
urls = list(dict.fromkeys(e['url'] for kind in ('menu_groups','config_groups') for es in manifest[kind].values() for e in es if e['url'].startswith('/apps/riob#')))
html = (ROOT/'apps/riob/source/RioBranco.html').read_text()
html = re.sub(r'<(?:script\b[^>]*>.*?</script|link\b[^>]*)>', '', html, flags=re.S)
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/opt/google/chrome/chrome', headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width':1440,'height':1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/*', lambda route: route.fulfill(body=html, content_type='text/html'))
    page.goto('http://navigation.test/apps/riob/embed')
    page.add_style_tag(path=str(ROOT/'apps/riob/source/style.css'))
    page.add_script_tag(path=str(ROOT/'apps/riob/source/script.js'))
    page.add_script_tag(path=str(ROOT/'apps/riob/source/gestao_processos_compras.js'))
    page.add_script_tag(path=str(ROOT/'apps/riob/source/estoque_contagem.js'))
    page.add_script_tag(path=str(ROOT/'apps/riob/source/custo_produto.js'))
    page.add_script_tag(path=str(ROOT/'apps/riob/source/custo_diario.js'))
    page.evaluate("""() => {
      window.onload=null;
      usuarioLogado={id:42,perfil:'admin'};
      for (const name of Object.keys(window)) {
        if (/^(carregar|recarregar|renderDashboard|atualizarDash|verificarStatus|ensureProdutos|limparProdutoEstoqueCadastro)/.test(name) && typeof window[name]==='function') window[name]=async()=>[];
      }
      window.apiFetch=async()=>({ok:true,json:async()=>[],headers:new Headers()});
      window.fetch=window.apiFetch;
      window.setInterval=()=>0;
      window.toggleChatPopup=async()=>{};
    }""")
    bridge = portal.riob_hash_bridge_script().removeprefix('\n<script>').removesuffix('</script>\n')
    page.add_script_tag(content=bridge)
    expected = {'custoDiario':'custoDiario','custoProdutoDashboard':'custoProdutoDashboard','custoProduto':'custoProduto','dashboard':'dashboard','cadastros':'cadastros','relatorios':'relatorios','estoque':'estoque','config':'config','vendas':'vendas','comissao':'comissao','gestaofrota':'gestaofrota','processos':'processosInternos','compras':'comprasGestao','fretes':'fretes','devolucoes':'devolucoes','monitor':'monitor'}
    visited=[]
    for url in urls + list(reversed(urls)):
        fragment=url.split('#',1)[1]
        section,_,view=fragment.partition(':')
        target=expected.get(section)
        if section=='workflow': target={'vendas_diario':'vendasDiarioWorkflow','vendas_diario_importar':'vendasDiarioImportarWorkflow','compras':'comprasGestao'}[view]
        if section=='vendas' and view.startswith('pontosvenda'): target='pontosvenda'
        if section=='gestaofrota' and view in ('cargas','escala'): target='cargas'
        page.evaluate("fragment=>{history.replaceState(null,'','#'+fragment);window.dispatchEvent(new Event('hashchange'));}",fragment)
        page.wait_for_timeout(20)
        active=page.locator('.section.activeSection').evaluate_all('es=>es.map(e=>e.id)')
        assert active==[target], (url,active,target)
        state_fields={'config':'__configView','cadastros':'__cadastrosView','relatorios':'__relatoriosView'}
        if section in state_fields:
            assert page.evaluate('field=>window[field]',state_fields[section])==view,url
        if section=='gestaofrota' and view in ('manutencao','oleo','pneu','abastecimento','lavagem'):
            assert page.evaluate('window.__gestaoRegistroView')==view,url
        if section=='vendas' and view.startswith('pontosvenda'):
            assert page.evaluate('window.__pontosVendaView')=={'pontosvenda':'cadastro','pontosvenda_relatorio':'relatorio','pontosvenda_importar':'importar'}[view],url
        # Every family has one visible task; summaries and detail rows of the
        # selected report belong to that same task.
        for family in ['#dashboard > .dash-view','#relatorios > div[id^=relatoriosView], #relatorios > #vendasDiarioCargasSemana','#cadastros > .cadastro-view','#gestaofrota > .dash-view','#comissao > .dash-view','#config > div[id^="configView"]','#pontosvenda > div[id^="pontosVendaView"]','#vendas > .dash-view']:
            ids=page.locator(family).evaluate_all('es=>es.filter(e=>e.getClientRects().length && getComputedStyle(e).visibility!=="hidden").map(e=>e.id)')
            expected_count=1 if family.startswith('#'+target+' >') else 0
            assert len(ids)==expected_count,(url,family,ids)
        if fragment=='comissao': assert page.locator('#comissaoViewLancamento').is_visible()
        if fragment=='vendas:relatorio': assert page.locator('#vendasViewRelatorio').is_visible()
        if fragment=='relatorios:cargas_semana':
            assert page.locator('#vendasDiarioCargasSemana').is_visible()
            assert not page.locator('#vendasDiarioWorkflow').is_visible()
        if fragment=='config:status': assert not page.get_by_role('button',name='Gerar Backup SQL',exact=True).is_visible()
        if fragment in ('config:vendas','config:base_vendas'): assert page.locator('#vendasConfigResumo').is_visible()
        visited.append(fragment)
    assert not errors,errors
    print(f'OK: {len(urls)} destinos RioB, {len(visited)} transicoes, uma tarefa por tela.')
    browser.close()
