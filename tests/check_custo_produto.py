"""Navegador com API real do modulo e banco SQLite sintetico; sem dados operacionais."""
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'apps/riob/source'))
sys.path.insert(0,str(ROOT/'apps/riob/source/tests'))
import app as portal
from test_custo_produto import CustoProdutoTests
fixture=CustoProdutoTests();fixture.setUp()
SOURCE=ROOT/'apps/riob/source'
try:
 with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/opt/google/chrome/chrome',headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda error: errors.append(str(error)))
    html=re.sub(r'<(?:script\b[^>]*>.*?</script|link\b[^>]*)>','',(SOURCE/'RioBranco.html').read_text(),flags=re.S)
    def respond(route):
        path=urlsplit(route.request.url).path
        if path.startswith('/api/custo-produto'):
            resp=fixture.client.open(path + ('?' + urlsplit(route.request.url).query if urlsplit(route.request.url).query else ''),method=route.request.method,data=route.request.post_data,
                headers={**fixture.headers,'X-Usuario-Recursos':'custo_produto,custo_produto_dashboard','Content-Type':'application/json'})
            route.fulfill(body=resp.data,status=resp.status_code,content_type='application/json')
        else: route.fulfill(body=html,content_type='text/html')
    page.route('**/*',respond)
    page.goto('http://custo.test/#custoProduto')
    page.add_style_tag(path=str(SOURCE/'style.css'))
    for script in ('script.js','gestao_processos_compras.js','custo_produto.js','custo_diario.js'):page.add_script_tag(path=str(SOURCE/script))
    page.evaluate('window.onload=null')
    page.add_script_tag(content=portal.riob_hash_bridge_script().replace('<script>','').replace('</script>',''))
    page.evaluate("window.dispatchEvent(new Event('hashchange'))")
    page.wait_for_function("document.querySelectorAll('#custoProdutoBody tr').length===3")
    assert page.locator('.section.activeSection').count()==1
    page.get_by_role('button',name='Cadastrar / editar base de xarope',exact=True).click()
    assert page.locator('#custoProdutoDadosXarope').is_visible()
    assert not page.locator('#custoProdutoDadosGarrafa').is_visible()
    page.locator('#custoProdutoRendimento').fill('100')
    row=page.locator('#custoProdutoItens tr').first
    assert row.locator('[data-custo=produto_id]').input_value()=='6'
    row.locator('[data-custo=quantidade]').fill('100')
    assert row.locator('[data-custo=preco_unitario]').get_attribute('readonly') is not None
    assert row.locator('[data-custo=preco_unitario]').input_value()=='5'
    assert '5,0000' in page.locator('#custoProdutoCalculo').inner_text()
    page.get_by_role('button',name='Salvar fórmula',exact=True).click()
    page.wait_for_function("!document.querySelector('#custoProdutoLista').classList.contains('hidden')")
    page.locator('#custoProdutoGrupo').select_option('PET')
    page.locator('#custoProdutoBusca').fill('uva')
    page.get_by_role('button',name='Cadastrar fórmula',exact=True).click()
    assert page.locator('#custoProdutoItens tr').count()==0
    page.locator('#custoProdutoDose').fill('200')
    assert page.locator('#custoProdutoVolume').input_value()=='2000'
    page.get_by_role('button',name='Adicionar item',exact=True).click()
    row=page.locator('#custoProdutoItens tr').first
    row.locator('[data-custo=produto_id]').select_option('7')
    row.locator('[data-custo=unidade]').select_option('l')
    row.locator('[data-custo=quantidade]').fill('2')
    assert row.locator('[data-custo=preco_unitario]').input_value()=='20'
    assert '1.040,0000' in page.locator('#custoProdutoCalculo').inner_text()
    assert '2,0800' in page.locator('#custoProdutoCalculo').inner_text()
    page.get_by_role('button',name='Salvar fórmula',exact=True).click()
    page.wait_for_function("!document.querySelector('#custoProdutoLista').classList.contains('hidden')")
    assert '2,0800' in page.locator('#custoProdutoBody').inner_text()
    page.get_by_role('button',name='Editar fórmula',exact=True).click()
    assert page.locator('#custoProdutoDose').input_value()=='200'
    assert page.locator('#custoProdutoItens [data-custo=produto_id]').input_value()=='7'
    assert 'XMLs de entrada' in page.locator('#custoProdutoAviso').inner_text()
    # Outra pessoa atualiza o xarope enquanto o editor esta aberto.
    response=fixture.client.put('/api/custo-produto/xarope',headers=fixture.headers,json={'revisao':2,
      'rendimento_litros':50,'itens':[{'produto_id':6,'unidade':'kg','quantidade':100,'preco_unitario':3}]})
    assert response.status_code==200
    page.get_by_role('button',name='Salvar fórmula',exact=True).click()
    page.wait_for_function("document.querySelector('#custoProdutoMensagem').textContent.includes('xarope foi alterado')")
    assert page.locator('#custoProdutoEditor').is_visible()
    page.get_by_role('button',name='Cancelar',exact=True).click()
    page.wait_for_function("document.querySelector('#custoProdutoBaseResumo').textContent.includes('10,0000')")
    assert '4,0800' in page.locator('#custoProdutoBody').inner_text()
    page.set_viewport_size({'width':390,'height':844})
    page.get_by_role('button',name='Editar fórmula',exact=True).click()
    assert page.locator('#custoProdutoDose').is_visible()
    page.get_by_role('button',name='Remover item',exact=True).click()
    assert page.locator('#custoProdutoItens tr').count()==0
    page.get_by_role('button',name='Salvar fórmula',exact=True).click()
    page.wait_for_function("!document.querySelector('#custoProdutoLista').classList.contains('hidden')")
    assert '4,0000' in page.locator('#custoProdutoBody').inner_text()
    # Embalagens sem conversao conhecida exigem a capacidade, mantendo o preco automatico.
    fixture.purchase(30,'Concentrado','250','2026-03-01','BB')
    page.evaluate('carregarCustoProduto()')
    page.get_by_role('button',name='Editar fórmula',exact=True).click()
    page.get_by_role('button',name='Adicionar item',exact=True).click()
    row=page.locator('#custoProdutoItens tr').first
    row.locator('[data-custo=produto_id]').select_option('7')
    row.locator('[data-custo=quantidade]').fill('2')
    assert row.locator('[data-custo=preco_unitario]').input_value()==''
    row.locator('[data-custo=fator_compra]').fill('25')
    assert row.locator('[data-custo=preco_unitario]').input_value()=='10'
    page.get_by_role('button',name='Salvar fórmula',exact=True).click()
    page.wait_for_function("!document.querySelector('#custoProdutoLista').classList.contains('hidden')")
    assert '4,0400' in page.locator('#custoProdutoBody').inner_text()
    # Navegacao real pelo hash e dashboard com serie de precos por mes.
    page.locator('#custoDashboardVisao').evaluate("e=>e.value='mensal'")
    page.evaluate("location.hash='custoProdutoDashboard'")
    page.locator('#custoDashboardVisao').select_option('mensal')
    page.wait_for_function("document.querySelectorAll('#custoDashboardBody tr').length===3")
    assert page.locator('.section.activeSection').count()==1
    assert page.locator('#custoProduto').is_hidden()
    page.locator('#custoDashboardProduto').select_option('1')
    assert page.locator('#custoDashboardGrafico svg').count()==1
    assert '4,0400' in page.locator('#custoDashboardBody').inner_text()
    assert '3,2800' in page.locator('#custoDashboardBody').inner_text()
    page.locator('#custoDashboardAno').select_option('2025')
    page.wait_for_function("document.querySelector('#custoDashboardHead').textContent.includes('12/2025')")
    assert '4,0400' in page.locator('#custoDashboardBody').inner_text()
    assert page.locator('#custoDashboardGrafico svg rect').evaluate_all('es=>es.every(e=>Number(e.getAttribute("height"))===0)')
    # Capacidades do cadastro e unidade TO do XML aparecem ao selecionar o acucar.
    fixture.purchase(31,'Acucar','75','2026-09-21','SC')
    c=sqlite3.connect(fixture.path)
    c.execute("UPDATE estoque_produtos SET fator_embalagem_padrao=50 WHERE id=6")
    c.execute("INSERT INTO estoque_movimentos VALUES(1,'importar_xml',31,'entrada','Acucar','','')")
    c.commit();c.close()
    page.evaluate("location.hash='custoProduto'")
    page.evaluate('carregarCustoProduto()')
    page.get_by_role('button',name='Cadastrar / editar base de xarope',exact=True).click()
    row=page.locator('#custoProdutoItens tr').first
    assert row.locator('[data-custo=preco_unitario]').input_value()=='1.5'
    assert 'Cadastro de estoque: 50 kg/SC' in row.inner_text()
    page.get_by_role('button',name='Cancelar',exact=True).click()
    fixture.purchase(32,'Acucar','1560','2026-09-22','TO')
    page.evaluate('carregarCustoProduto()')
    page.get_by_role('button',name='Cadastrar / editar base de xarope',exact=True).click()
    assert page.locator('#custoProdutoItens [data-custo=preco_unitario]').input_value()=='1.56'
    assert 'XML · NF-e 32' in page.locator('#custoProdutoItens').inner_text()
    assert not errors,errors
    browser.close()
    print('OK: cadastro, ultima compra, conversao, xarope, dose, persistencia, conflito, dashboard mensal e celular.')
finally:fixture.doCleanups()
