"""Navegador real: layout anual, ranking, vendedor/cliente e popup paginado."""
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]/'apps/riob/source'
html=re.sub(r'<script\b[^>]*>.*?</script>','',(ROOT/'RioBranco.html').read_text(),flags=re.S)
html=re.sub(r'<link\b[^>]*>','',html)
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/opt/google/chrome/chrome',headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]
    page.on('pageerror',lambda error: errors.append(str(error)))
    page.route('**/*',lambda route:route.fulfill(body=html,content_type='text/html'))
    page.goto('http://sales.test')
    page.add_style_tag(path=str(ROOT/'style.css'))
    page.add_script_tag(content=(ROOT/'script.js').read_text())
    page.evaluate('''() => {
      window.onload=null;
      document.querySelectorAll('.section').forEach(el=>el.style.display='none');
      document.getElementById('vendas').style.display='block';
      window.urls=[]; window.fail=false; window.empty=false; window.denied=false;
      window.pause=false; window.pending=[]; window.revision='1';
      window.nanotechMenuAllowed=()=>!denied;
      window.payload=params=>{
        const seller=params.get('vendedor') || '', client=params.get('cliente') || '';
        const cs=(seller==='S1' ? ['A','B'] : seller==='S2' ? ['A','C'] : ['A','B','C']);
        const entity=(chave,nome,diff,tipo)=>({chave,nome,tipo,total_atual:100+diff,total_anterior:100,
          diferenca_volume:diff,variacao_percentual:diff,movimento:diff<0?'decrescimo':'acrescimo',venda_atual:1000,venda_anterior:1200});
        const ranking=empty ? [] : seller ? cs.filter(c=>!client || c===client).map((c,i)=>entity(c,'Cliente '+c,-10+i*3,'cliente')) :
          [entity('S2','Vendedor 2',-5,'vendedor'),entity('S1','Vendedor 1',-20,'vendedor'),entity('S3','Vendedor 3',5,'vendedor')];
        return {filtros:Object.fromEntries(params),ano_atual:2026,ano_anterior:2025,cache:{id:'base',updated_at:revision},
          vendedores:[{chave:'S1',nome:'Vendedor 1'},{chave:'S2',nome:'Vendedor 2'},{chave:'S3',nome:'Vendedor 3'}],
          clientes_disponiveis:cs.map(chave=>({chave,cliente:'Cliente '+chave})),
          cabecalho_resumo:[{nome:'RioB (valor total)',valor_venda:12345678},{nome:'CLT',valor_venda:7000000},{nome:'Autônomos',valor_venda:5345678}],
          resumo_geral:{total_atual:90,total_anterior:100,diferenca_volume:-10,variacao_percentual:-10,movimento:'decrescimo'},
          comparativo_mensal:[{mes:1,label:'Jan',volume_atual:90,volume_anterior:100,diferenca_volume:-10,variacao_percentual:-10,movimento:'decrescimo'}],
          ranking,ranking_tipo:seller?'cliente':'vendedor',pagina:Number(params.get('pagina') || 1),tem_proxima:params.get('pagina')!=='2',
          vendas:params.get('detalhe')==='1' ? [{data:'2026-01-10',numero_nf:params.get('pagina')==='2'?'200':'100',vendedor:seller,produto:'COLA',volume:2,valor_venda:100}] : []};
      };
      apiFetch=async url=>{
        urls.push(url); const params=new URL(url,location.origin).searchParams;
        if (pause) return new Promise(resolve=>pending.push({params,resolve}));
        return {ok:!fail,json:async()=>fail ? {erro:'Falha de teste'} : payload(params)};
      };
    }''')
    def ready():
        page.wait_for_function("vendasState.anualConsulta !== null && !document.getElementById('vendasAnualCliente').disabled")
    def load():
        page.evaluate('carregarRelatorioVendasAnual()')
    def names():
        return page.locator('#vendasAnualRankBody tr td:nth-child(2)').all_text_contents()
    def clients():
        return page.locator('#vendasAnualCliente option').evaluate_all('(els)=>els.map(e=>e.value)')
    def popup():
        page.locator('#vendasAnualRankBody tr').first.click()
        page.wait_for_function("document.getElementById('vendasAnualDialogBody').textContent.includes('COLA')")
    page.locator('#vendasRelTabAnual').click();ready()
    assert names()==['Vendedor 1','Vendedor 2','Vendedor 3']
    assert clients()==['','A','B','C']
    for width in [1440,1280]:
        page.set_viewport_size({'width':width,'height':1000})
        tabs=page.locator('#vendasRelatorioTabs').bounding_box(); totals=page.locator('#vendasRelTotaisPadrao').bounding_box()
        assert abs((tabs['y']+tabs['height']/2)-(totals['y']+totals['height']/2))<2
        controls=[page.locator('#'+id).bounding_box() for id in ['vendasPeriodoInicio','vendasPeriodoFim','vendasAnualVendedor','vendasAnualCliente']]
        assert max(b['y']+b['height'] for b in controls)-min(b['y']+b['height'] for b in controls)<2
    assert not page.locator('.vendas-periodo-extra').first.is_visible()
    assert page.locator('#vendas').get_by_role('button',name='Limpar filtros',exact=True).filter(visible=True).count()==1
    count=page.evaluate('urls.length'); snapshot=page.evaluate('JSON.stringify(vendasState.anualConsulta.data)')
    page.locator('#vendasAnualRankOrdem').select_option('menor_perda')
    assert names()==['Vendedor 3','Vendedor 2','Vendedor 1']
    page.locator('#vendasAnualRankOrdem').select_option('maior_perda')
    assert page.evaluate('urls.length')==count
    assert page.evaluate('JSON.stringify(vendasState.anualConsulta.data)')==snapshot
    popup()
    params=parse_qs(urlsplit(page.evaluate('urls.at(-1)')).query)
    assert params['vendedor']==['S1'] and 'cliente' not in params and params['detalhe']==['1']
    assert 'Vendedor 1' in page.locator('#vendasAnualDialogTitulo').inner_text()
    page.locator('#vendasAnualPaginaProxima').click()
    page.wait_for_function("document.getElementById('vendasAnualPaginaInfo').textContent==='Página 2'")
    assert '200' in page.locator('#vendasAnualDialogBody').inner_text()
    assert page.locator('#vendasAnualPaginaProxima').is_disabled()
    page.keyboard.press('Escape')
    page.locator('#vendasAnualVendedor').select_option('S1');ready()
    assert clients()==['','A','B'];assert names()==['Cliente A','Cliente B']
    assert page.locator('#vendasAnualRankTitulo').inner_text()=='Ranking de clientes'
    page.locator('#vendasAnualCliente').select_option('B');ready()
    assert names()==['Cliente B']
    page.locator('#vendasAnualVendedor').select_option('S2');ready()
    assert page.locator('#vendasAnualCliente').input_value()==''
    assert clients()==['','A','C'] and names()==['Cliente A','Cliente C']
    params=parse_qs(urlsplit(page.evaluate('urls.at(-1)')).query)
    assert 'cliente' not in params
    page.evaluate("document.getElementById('vendasPeriodoInicio').value='2025-01-01'; document.getElementById('vendasPeriodoFim').value='2026-09-30'")
    load();popup()
    params=parse_qs(urlsplit(page.evaluate('urls.at(-1)')).query)
    assert params['vendedor']==['S2'] and params['cliente']==['A']
    assert params['data_inicio']==['2025-01-01'] and params['data_fim']==['2026-09-30']
    page.screenshot(path='/tmp/vendas-anual-popup.png')
    page.keyboard.press('Escape')
    # Respostas antigas não podem reabrir popup nem recolocar a carteira anterior.
    page.evaluate('''() => {pause=true; window.oldLoad=carregarRelatorioVendasAnual();
      document.getElementById('vendasAnualVendedor').value='S1';window.newLoad=carregarRelatorioVendasAnual();}''')
    assert page.locator('#vendasAnualRankBody').inner_text()==''
    assert page.locator('#vendasAnualCliente').is_disabled()
    page.evaluate('''async()=>{pending[1].resolve({ok:true,json:async()=>payload(pending[1].params)});await newLoad;
      pending[0].resolve({ok:true,json:async()=>payload(pending[0].params)});await oldLoad;pause=false;pending=[];}''')
    assert clients()==['','A','B']
    page.evaluate('() => {pause=true;window.oldPopup=abrirVendasAnualPopup(0);}')
    page.keyboard.press('Escape')
    page.evaluate('''async()=>{pending.forEach(i=>i.resolve({ok:true,json:async()=>payload(i.params)}));await oldPopup;pause=false;pending=[];}''')
    assert not page.locator('#vendasAnualDialog').is_visible()
    assert page.locator('#vendasAnualDialogBody').inner_text()==''
    # Uma nova importação impede misturar resumo anterior e vendas novas.
    page.evaluate("revision='2'")
    page.evaluate('abrirVendasAnualPopup(0)')
    assert 'base mudou' in page.locator('#vendasAnualDialogStatus').inner_text()
    assert page.locator('#vendasAnualDialogBody').inner_text()==''
    page.keyboard.press('Escape')
    page.evaluate('fail=true');load()
    assert 'Falha de teste' in page.locator('#vendasAnualStatus').inner_text()
    assert page.locator('#vendasAnualRankBody').inner_text()==''
    page.evaluate('fail=false; empty=true');load()
    assert 'Nenhuma venda' in page.locator('#vendasAnualRankBody').inner_text()
    page.evaluate('empty=false; denied=true; urls=[]');load()
    assert page.evaluate('urls.length')==0
    assert 'não liberado' in page.locator('#vendasAnualStatus').inner_text()
    page.evaluate('denied=false; limparFiltrosRelatorioVendasAnual()');ready()
    assert page.locator('#vendasAnualVendedor').input_value()==''
    assert page.locator('#vendasAnualCliente').input_value()==''
    assert page.locator('#vendasPeriodoInicio').input_value()=='' and page.locator('#vendasPeriodoFim').input_value()==''
    assert clients()==['','A','B','C'] and page.locator('#vendasAnualRankTitulo').inner_text()=='Ranking de vendedores'
    page.screenshot(path='/tmp/vendas-anual-desktop.png')
    page.set_viewport_size({'width':390,'height':844})
    for id in ['vendasRelatorioHeader','vendasRelCabecalho']:
        assert page.locator('#'+id).evaluate('(el)=>el.scrollWidth<=el.clientWidth'),id
    popup()
    box=page.locator('#vendasAnualDialog').bounding_box()
    assert box['x']>=0 and box['x']+box['width']<=390
    page.screenshot(path='/tmp/vendas-anual-mobile.png')
    page.keyboard.press('Escape')
    assert not errors,errors
    browser.close()
    print('OK: anual desktop/celular, ranking vendedor/cliente, filtros, popup, paginação, falhas, acessos e concorrência')
