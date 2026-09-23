"""Fluxo diario no navegador com API Flask real e banco sintetico."""
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'apps/riob/source'),str(ROOT/'apps/riob/source/tests')]
import app as portal
from test_custo_diario import CustoDiarioTests
f=CustoDiarioTests();f.setUp()
try:
 with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/opt/google/chrome/chrome',headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    source=ROOT/'apps/riob/source'
    html=re.sub(r'<(?:script\b[^>]*>.*?</script|link\b[^>]*)>','',(source/'RioBranco.html').read_text(),flags=re.S)
    def route(r):
        url=urlsplit(r.request.url)
        if url.path.startswith('/api/custo-'):
            resp=f.client.open(url.path+('?'+url.query if url.query else ''),method=r.request.method,data=r.request.post_data,
              headers={**f.headers,'X-Usuario-Recursos':'custo_diario,custo_produto_dashboard','Content-Type':'application/json'})
            r.fulfill(body=resp.data,status=resp.status_code,content_type='application/json')
        else:r.fulfill(body=html,content_type='text/html')
    page.route('**/*',route);page.goto('http://dia.test/#custoDiario')
    page.add_style_tag(path=str(source/'style.css'))
    for js in ['script.js','gestao_processos_compras.js','custo_produto.js','custo_diario.js']:page.add_script_tag(path=str(source/js))
    page.evaluate("window.onload=null;document.getElementById('custoDiaData').value='2026-09-22';document.getElementById('custoDiaDashData').value='2026-09-22'")
    page.add_script_tag(content=portal.riob_hash_bridge_script().replace('<script>','').replace('</script>',''))
    page.evaluate("window.dispatchEvent(new Event('hashchange'))")
    page.wait_for_function("!document.querySelector('#custoDiaCampos').disabled")
    assert page.locator('#custoDiario').is_visible()
    page.get_by_role('button',name='Adicionar produção',exact=True).click()
    row=page.locator('#custoDiaproducao tr').first
    row.locator('[data-dia=produto_id]').select_option('1')
    assert row.locator('[data-dia=volume_ml]').input_value()=='2000'
    row.locator('[data-dia=embalagens]').fill('500');row.locator('[data-dia=por_pacote]').fill('6')
    page.get_by_role('button',name='Adicionar despesa',exact=True).click()
    row=page.locator('#custoDiadespesas tr').first
    row.locator('[data-dia=grupo]').select_option('PET');row.locator('[data-dia=setor]').fill('Produção')
    row.locator('[data-dia=descricao]').fill('Pessoal do dia');row.locator('[data-dia=valor]').fill('100')
    page.get_by_role('button',name='Apurar e salvar dia',exact=True).click()
    page.wait_for_function("document.querySelector('#custoDiaStatus').textContent.includes('Dia salvo')")
    assert '640,0000' in page.locator('#custoDiaStatus').inner_text()
    # A falta finalizada apos salvar o dia aparece automaticamente ao abrir o dashboard.
    f.sql("INSERT INTO estoque_contagens VALUES(1,'finalizada','2026-09-22 09:00:00'); INSERT INTO estoque_contagem_resultados VALUES(1,1,1,'Uva PET',10);")
    page.evaluate("location.hash='custoProdutoDashboard'")
    page.wait_for_function("document.querySelector('#custoDiaDashResultado').textContent.includes('Estoque / PET')")
    assert page.locator('#custoDashboardMensal').is_hidden()
    assert '650,8000' in page.locator('#custoDiaDashResultado').inner_text()
    assert '7,8096' in page.locator('#custoDiaDashResultado').inner_text()
    page.locator('#custoDiaDashUnidade').select_option('litros')
    page.locator('#custoDiaDashGrupo').select_option('PET')
    assert '0,6508' in page.locator('#custoDiaDashResultado').inner_text()
    page.set_viewport_size({'width':390,'height':844})
    page.evaluate("location.hash='custoDiario'")
    page.evaluate('carregarCustoDiario()')
    page.wait_for_function("document.querySelector('#custoDiaContagens').textContent.includes('#1')")
    assert page.locator('#custoDiaproducao [data-dia=embalagens]').input_value()=='500'
    assert page.get_by_role('button',name='Adicionar desperdício',exact=True).count()==0
    # Conflito preserva o rascunho.
    payload=f.payload();payload['revisao']=1;assert f.save(payload).status_code==200
    page.locator('#custoDiadespesas [data-dia=valor]').fill('120')
    page.get_by_role('button',name='Apurar e salvar dia',exact=True).click()
    page.wait_for_function("document.querySelector('#custoDiaStatus').textContent.includes('outro usuario')")
    assert page.locator('#custoDiadespesas [data-dia=valor]').input_value()=='120'
    assert not errors,errors
    print('OK: custo diario, producao, pessoal, garrafa/pacote/litro, contagem automatica, revisao e celular.')
    browser.close()
finally:f.doCleanups()
