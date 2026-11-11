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
    page.wait_for_function("document.querySelectorAll('#custoProdutoBody tr').length===4")
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
    row.locator('[data-custo=preco_provisorio]').fill('3')
    assert row.locator('[data-custo=preco_provisorio]').input_value()=='3'
    assert not row.locator('[data-custo=preco_provisorio]').is_disabled()
    assert '5,0000' in page.locator('#custoProdutoCalculo').inner_text()
    page.get_by_role('button',name='Salvar fórmula',exact=True).click()
    page.wait_for_function("!document.querySelector('#custoProdutoLista').classList.contains('hidden')")
    page.get_by_role('button',name='Criar xarope composto por sabor',exact=True).click()
    assert page.locator('#custoProdutoDadosComposto').is_visible()
    page.locator('#custoProdutoCompostoNome').fill('Limao')
    page.locator('#custoProdutoCompostoBaseLitros').fill('100')
    page.locator('#custoProdutoCompostoRendimento').fill('500')
    assert page.locator('#custoProdutoCompostoDose').input_value()=='200'
    assert 'proporção é automática' in page.locator('#custoProdutoDadosComposto').inner_text().lower()
    row=page.locator('#custoProdutoItens tr').first
    row.locator('[data-custo=produto_id]').select_option('4')
    row.locator('[data-custo=quantidade]').fill('.000001')
    # Sem NF-e, o proprio campo exibido como preco usado aceita o valor e o
    # sincroniza com o valor provisorio persistido na formula.
    assert row.locator('[data-custo=preco_unitario]').get_attribute('readonly') is None
    row.locator('[data-custo=preco_unitario]').fill('.000001')
    assert row.locator('[data-custo=preco_unitario]').input_value()=='0.000001'
    provisional_value=row.locator('[data-custo=preco_provisorio]').input_value()
    assert float(provisional_value)==.000001,f'preco provisorio nao sincronizado: {provisional_value!r}'
    assert not row.locator('[data-custo=preco_provisorio]').is_disabled()
    page.get_by_role('button',name='Salvar fórmula',exact=True).click()
    page.wait_for_function("!document.querySelector('#custoProdutoLista').classList.contains('hidden')")
    assert 'Limao' in page.locator('#custoProdutoCompostosBody').inner_text()
    page.locator('#custoProdutoGrupo').select_option('PET')
    page.locator('#custoProdutoBusca').fill('uva')
    page.get_by_role('button',name='Cadastrar fórmula',exact=True).click()
    assert page.locator('#custoProdutoItens tr').count()==0
    page.locator('#custoProdutoCompostoSelect').select_option(label='Limao')
    assert page.locator('#custoProdutoDose').input_value()=='200'
    assert page.locator('#custoProdutoVolume').input_value()=='2000'
    page.locator('#custoProdutoUnidadesPacote').fill('6')
    assert page.locator('#custoProdutoQuantidadeTitulo').inner_text()=='Quantidade / garrafa'
    page.get_by_role('button',name='Adicionar item',exact=True).click()
    row=page.locator('#custoProdutoItens tr').first
    row.locator('[data-custo=produto_id]').select_option('8')
    assert row.locator('[data-custo=quantidade]').input_value()=='1'
    row.locator('[data-custo=produto_id]').select_option('7')
    assert 'NF-e 11' in row.locator('[data-custo=produto_id] option:checked').inner_text()
    row.locator('[data-custo=unidade]').select_option('l')
    row.locator('[data-custo=quantidade]').fill('.004')
    assert row.locator('[data-custo=preco_unitario]').input_value()=='20'
    assert '1.040,0000' in page.locator('#custoProdutoCalculo').inner_text()
    assert '2,0800' in page.locator('#custoProdutoCalculo').inner_text()
    page.get_by_role('button',name='Salvar fórmula',exact=True).click()
    page.wait_for_function("!document.querySelector('#custoProdutoLista').classList.contains('hidden')")
    assert '2,0800' in page.locator('#custoProdutoBody').inner_text()
    page.get_by_role('button',name='Editar fórmula',exact=True).click(force=True)
    assert page.locator('#custoProdutoDose').input_value()=='200'
    assert page.locator('#custoProdutoItens [data-custo=produto_id]').input_value()=='7'
    aviso_preco=page.locator('#custoProdutoAviso').inner_text()
    assert 'referência fiscal válida' in aviso_preco and 'prioridade' in aviso_preco
    # Outra pessoa atualiza o composto do sabor enquanto o editor esta aberto.
    data=fixture.data();composto=next(x for x in data['xaropes_compostos'] if x['nome']=='Limao')
    response=fixture.client.put(f"/api/custo-produto/xaropes-compostos/{composto['id']}",headers=fixture.headers,json={
      'revisao':composto['revisao'],'xarope_revisao':data['xarope']['revisao'],'nome':'Limao',
      'xarope_base_litros':100,'rendimento_litros':250,'dose_litros_1000':999999,
      'itens':[{'produto_id':4,'unidade':'un','quantidade':'.000001','preco_provisorio':'.000001'}]})
    assert response.status_code==200
    page.get_by_role('button',name='Salvar fórmula',exact=True).click()
    page.wait_for_function("document.querySelector('#custoProdutoMensagem').textContent.includes('xarope composto foi alterado')")
    assert page.locator('#custoProdutoEditor').is_visible()
    page.get_by_role('button',name='Cancelar',exact=True).click()
    page.wait_for_function("document.querySelector('#custoProdutoCompostosBody').textContent.includes('2,0000')")
    assert '4,0800' in page.locator('#custoProdutoBody').inner_text()
    page.set_viewport_size({'width':390,'height':844})
    page.evaluate('editarCustoProduto(1)')
    page.wait_for_function("!document.querySelector('#custoProdutoEditor').classList.contains('hidden')")
    assert page.locator('#custoProdutoDose').is_visible()
    page.get_by_role('button',name='Remover item',exact=True).click()
    assert page.locator('#custoProdutoItens tr').count()==0
    page.get_by_role('button',name='Salvar fórmula',exact=True).click()
    page.wait_for_function("!document.querySelector('#custoProdutoLista').classList.contains('hidden')")
    assert '4,0000' in page.locator('#custoProdutoBody').inner_text()
    page.set_viewport_size({'width':1440,'height':1000})
    # Embalagens sem conversao conhecida exigem a capacidade, mantendo o preco automatico.
    fixture.purchase(30,'Concentrado','250','2026-03-01','BB')
    page.evaluate('carregarCustoProduto()')
    page.evaluate('editarCustoProduto(1)')
    page.get_by_role('button',name='Adicionar item',exact=True).click()
    row=page.locator('#custoProdutoItens tr').first
    row.locator('[data-custo=produto_id]').select_option('7')
    row.locator('[data-custo=quantidade]').fill('.004')
    assert row.locator('[data-custo=preco_unitario]').input_value()==''
    row.locator('[data-custo=fator_compra]').fill('25')
    assert row.locator('[data-custo=preco_unitario]').input_value()=='10'
    page.get_by_role('button',name='Salvar fórmula',exact=True).click()
    page.wait_for_function("!document.querySelector('#custoProdutoLista').classList.contains('hidden')")
    assert '4,0400' in page.locator('#custoProdutoBody').inner_text()
    # Navegacao real pelo hash e dashboard somente com o custo mais recente.
    page.evaluate("location.hash='custoProdutoDashboard'")
    page.wait_for_function("document.querySelectorAll('#custoDashboardProdutos .custo-dashboard-card--produto').length===1")
    assert page.locator('.section.activeSection').count()==1
    assert page.locator('#custoProduto').is_hidden()
    assert 'Xarope base' in page.locator('#custoDashboardTopo').inner_text()
    assert 'Limao' in page.locator('#custoDashboardTopo').inner_text()
    assert 'Uva PET 2 L' in page.locator('#custoDashboardProdutos').inner_text()
    assert '24,2400' in page.locator('#custoDashboardProdutos').inner_text()
    assert 'Unidade sem rateio' in page.locator('#custoDashboardProdutos').inner_text()
    assert 'Itens de embalagem: por garrafa · pacote · 1.000 L' in page.locator('#custoDashboardProdutos').inner_text()
    assert 'Concentrado' in page.locator('#custoDashboardProdutos').inner_text()
    assert page.locator('#custoDashboardProduto').count()==0
    assert page.locator('#custoDashboardVisao').count()==0
    assert page.locator('#custoDashboardAno').count()==0
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
    page.wait_for_function("!custoProdutoState.carregando")
    page.evaluate('carregarCustoProduto()')
    page.wait_for_function("custoProdutoState.insumos.find(item=>item.id===6)?.ultima_compra?.nota==='32'")
    page.get_by_role('button',name='Cadastrar / editar base de xarope',exact=True).click()
    acucar_preco=page.locator('#custoProdutoItens [data-custo=preco_unitario]').input_value()
    assert acucar_preco=='1.56',acucar_preco
    assert 'XML · NF-e 32' in page.locator('#custoProdutoItens').inner_text()
    page.get_by_role('button',name='Cancelar',exact=True).click()
    # Formula sem NF-e usa valor provisorio e inclui agua quente no custo.
    page.locator('#custoProdutoGrupo').select_option('PET')
    page.locator('#custoProdutoBusca').fill('laranja')
    page.get_by_role('button',name='Cadastrar fórmula',exact=True).click()
    page.locator('#custoProdutoCompostoSelect').select_option(label='Limao')
    assert page.locator('#custoProdutoDose').input_value()=='400'
    page.locator('#custoProdutoUnidadesPacote').fill('12')
    page.locator('#custoProdutoAguaQuenteLitros').fill('10')
    page.locator('#custoProdutoAguaQuenteValor').fill('.2')
    page.get_by_role('button',name='Adicionar item',exact=True).click()
    row=page.locator('#custoProdutoItens tr').first
    row.locator('[data-custo=produto_id]').select_option('9')
    row.locator('[data-custo=unidade]').select_option('l')
    row.locator('[data-custo=quantidade]').fill('.0004')
    row.locator('[data-custo=preco_provisorio]').fill('3')
    assert row.locator('[data-custo=preco_unitario]').input_value()=='3'
    assert 'Valor provisório informado' in row.inner_text()
    assert 'Água quente: R$ 2,0000' in page.locator('#custoProdutoCalculo').inner_text()
    page.get_by_role('button',name='Salvar fórmula',exact=True).click()
    page.wait_for_function("!document.querySelector('#custoProdutoLista').classList.contains('hidden')")
    page.get_by_role('button',name='Editar fórmula',exact=True).click()
    assert page.locator('#custoProdutoAguaQuenteLitros').input_value()=='10'
    assert page.locator('#custoProdutoAguaQuenteValor').input_value()=='0.2'
    assert page.locator('#custoProdutoItens [data-custo=preco_provisorio]').input_value()=='3'
    page.get_by_role('button',name='Cancelar',exact=True).click()
    page.once('dialog',lambda dialog: dialog.accept())
    page.get_by_role('button',name='Excluir fórmula',exact=True).click()
    page.wait_for_function("document.querySelector('#custoProdutoStatus').textContent.includes('dados fiscais foram mantidos')")
    assert 'Sem fórmula' in page.locator('#custoProdutoBody').inner_text()
    assert page.get_by_role('button',name='Cadastrar fórmula',exact=True).is_visible()
    page.once('dialog',lambda dialog: dialog.accept())
    page.get_by_role('button',name='Remover da lista',exact=True).click()
    page.wait_for_function("document.querySelector('#custoProdutoStatus').textContent.includes('removido da lista de produção')")
    assert 'Laranja PET 200 ML' not in page.locator('#custoProdutoBody').inner_text()
    page.get_by_label('Mostrar itens removidos').check()
    assert 'Fora da lista de produção' in page.locator('#custoProdutoBody').inner_text()
    page.get_by_role('button',name='Restaurar na lista',exact=True).click()
    page.wait_for_function("document.querySelector('#custoProdutoStatus').textContent.includes('restaurado na lista')")
    assert 'Sem fórmula' in page.locator('#custoProdutoBody').inner_text()
    # Rateio padrao em Config alimenta o detalhamento por unidade e pacote.
    c=sqlite3.connect(fixture.path)
    c.executemany('INSERT INTO abastecimentos VALUES(?,?,?,?,?,?)',[
      (1,120,18,'abastecido','2026-09-01','2026-09-02'),
      (2,180,22,'abastecido','2026-09-10','2026-09-11')])
    c.commit();c.close()
    page.evaluate("location.hash='config:custos_producao'")
    page.wait_for_function("!document.querySelector('#configViewCustosProducao').classList.contains('hidden') && !document.querySelector('#custoRateioCampos').disabled")
    page.locator('#custoRateioVolume').fill('10000')
    page.locator('#custoRateioCapacidadeHora').fill('2500')
    assert page.locator('#custoRateioHorasSemanais').input_value()=='44'
    page.get_by_role('button',name='Adicionar custo',exact=True).click()
    rateio=page.locator('#custoRateioItens tr').first
    rateio.locator('[data-rateio=categoria]').select_option('mao_obra')
    rateio.locator('[data-rateio=descricao]').fill('Folha da producao')
    rateio.locator('[data-rateio=tipo]').select_option('mensal')
    rateio.locator('[data-rateio=valor]').fill('3000')
    page.get_by_role('button',name='Adicionar custo',exact=True).click()
    caldeira=page.locator('#custoRateioItens tr').nth(1)
    caldeira.locator('[data-rateio=categoria]').select_option('caldeira')
    caldeira.locator('[data-rateio=descricao]').fill('Lenha da caldeira')
    caldeira.locator('[data-rateio=tipo]').select_option('hora')
    caldeira.locator('[data-rateio=valor]').fill('250')
    page.get_by_role('button',name='Adicionar custo',exact=True).click()
    combustivel=page.locator('#custoRateioItens tr').nth(2)
    combustivel.locator('[data-rateio=descricao]').fill('Combustivel da producao')
    combustivel.locator('[data-rateio=tipo]').select_option('abastecimentos')
    assert combustivel.locator('[data-rateio=categoria]').input_value()=='combustivel'
    assert combustivel.locator('[data-rateio=categoria]').is_disabled()
    assert combustivel.locator('[data-rateio=valor]').is_disabled()
    page.get_by_role('button',name='Salvar rateio',exact=True).click()
    page.wait_for_function("document.querySelector('#custoRateioStatus').textContent.includes('Rateio salvo')")
    page.evaluate("location.hash='custoProdutoDashboard'")
    page.wait_for_function("document.querySelector('#custoDashboardRateio').textContent.includes('Folha da producao')")
    assert 'Uva PET 2 L' in page.locator('#custoDashboardProdutos').inner_text()
    assert 'Folha da producao' in page.locator('#custoDashboardRateio').inner_text()
    assert '0,3000' in page.locator('#custoDashboardRateio').inner_text()
    assert 'Lenha da caldeira' in page.locator('#custoDashboardRateio').inner_text()
    assert '0,1000' in page.locator('#custoDashboardRateio').inner_text()
    assert 'Combustivel da producao' in page.locator('#custoDashboardRateio').inner_text()
    assert '0,0300' in page.locator('#custoDashboardRateio').inner_text()
    assert '2 abastecimentos' in page.locator('#custoDashboardRateio').inner_text()
    assert '0,8600' in page.locator('#custoDashboardProdutos').inner_text()
    assert 'Unidade com rateio' in page.locator('#custoDashboardProdutos').inner_text()
    # O relatorio usa o mesmo snapshot do dashboard, separa por sabor e explicita a origem fiscal.
    page.evaluate("location.hash='relatorios:custo_produto'")
    page.wait_for_function("document.querySelector('#relatorioCustoProdutoConteudo')?.textContent.includes('Fórmula Uva')")
    relatorio=page.locator('#relatorioCustoProdutoConteudo').inner_text()
    assert 'Ingredientes do xarope base' in relatorio
    assert 'Ingredientes específicos de Uva' in relatorio
    assert 'Combustivel da producao' in relatorio
    assert '2 abastecimentos' in relatorio
    assert 'Uva PET 2 L' in relatorio
    assert 'XML / NF-e' in relatorio
    assert 'NF 32' in relatorio
    assert 'Valor na compra' in relatorio
    assert 'Conversão' in relatorio
    assert 'Direto / 1.000 L' in relatorio
    assert 'Fechamento:' in relatorio
    assert 'Componentes do custo' in relatorio
    assert 'Itens de embalagem por unidade pronta' in relatorio
    assert 'Total / litro' in relatorio
    assert 'Pacote sem / com rateio' in relatorio
    page.locator('#relatorioCustoProdutoGrupo').select_option('PET')
    page.locator('#relatorioCustoProdutoBusca').fill('uva')
    assert page.locator('#relatorioCustoProdutoConteudo .custo-relatorio-produto').count()==1
    fixture.purchase(40,'Tampa','54.25','2026-09-22','ML')
    page.evaluate("location.hash='custoProduto'")
    page.wait_for_function("!custoProdutoState.carregando")
    page.evaluate('carregarCustoProduto()')
    page.wait_for_function("custoProdutoState.insumos.find(item=>item.id===8)?.ultima_compra?.nota==='40'")
    conversao_ml=page.evaluate("precoCompraCusto({produto_id:8,unidade:'un',quantidade:'1',fator_compra:'',unidade_compra:'',preco_provisorio:''})")
    assert abs(conversao_ml['preco']-.05425)<1e-9,conversao_ml
    assert conversao_ml['automatico'] is True
    assert not errors,errors
    browser.close()
    print('OK: formulas, NF-e/provisorio, agua quente, pacote, rateio/combustivel, dashboard, relatorio e celular.')
finally:fixture.doCleanups()
