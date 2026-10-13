"""Tela real com dados sintéticos: cidade/produto, PDVs, acessos e concorrência."""
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1] / 'apps/riob/source'
html = re.sub(r'<script\b[^>]*>.*?</script>', '', (ROOT / 'RioBranco.html').read_text(), flags=re.S)
html = re.sub(r'<link\b[^>]*>', '', html)
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/opt/google/chrome/chrome', headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width':1440, 'height':1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/*', lambda route: route.fulfill(body=html, content_type='text/html'))
    page.goto('http://sales.test')
    page.add_style_tag(path=str(ROOT / 'style.css'))
    page.add_script_tag(content=(ROOT / 'script.js').read_text())
    page.evaluate('''() => {
      window.onload=null;
      document.querySelectorAll('.section').forEach(el=>el.style.display='none');
      document.getElementById('vendas').style.display='block';
      window.urls=[]; window.denied=[]; window.fail=''; window.empty=false;
      window.pause=false; window.pending=[];
      window.nanotechMenuAllowed=url=>!denied.some(tipo=>url.endsWith('#vendas:'+tipo));
      window.payload=params=>{
        const detail=params.get('detalhe')==='1', medio=params.get('tipo_relatorio')==='preco_medio';
        const filtros=Object.fromEntries(params);
        if (!filtros.data_inicio && !filtros.data_fim) Object.assign(filtros,{data_inicio:'2026-09-01',data_fim:'2026-09-30'});
        return {filtros,cache:{id:'test',updated_at:'v1'}, arquivo:{nome:params.get('vendedor') || 'SELLOUT teste'},
          vendedores:[{chave:'A',nome:'Vendedor A'},{chave:'B',nome:'Vendedor B'}], grupos_disponiveis:['PET 2L','Astuba 2L'],
          cabecalho_resumo:[{nome:'RioB (valor total)',valor_venda:12345678},{nome:'CLT',valor_venda:7000000},{nome:'Autônomos',valor_venda:5345678}],
          resumo_geral:{cidades:1,produtos:1,pdvs:4,preco_min:0,preco_max:10},
          linhas:empty ? [] : [{cidade:'LONDRINA',produto:'COLA PET 2L',grupo:'PET 2L',pdvs:4,...(medio ? (detail ? {preco_medio:7}: {}) : {preco_min:0,preco_max:10})}],
          pdvs:detail && !empty ? ['Mercado 10','Mercado 2','Água','Vazio'].map((nome,i)=>({chave:String(i),nome,
            ...(medio ? {preco_medio:[10,2,0,null][i]} : {preco_min:[9,1,0,null][i],preco_max:[10,2,0,null][i]})})) : []};
      };
      apiFetch=async url=>{
        urls.push(url); const params=new URL(url,location.origin).searchParams;
        if(pause) return new Promise(resolve=>pending.push({params,resolve}));
        const invalid=params.get('data_inicio')>params.get('data_fim') && params.has('data_fim');
        const failed=invalid || params.get('tipo_relatorio')===fail;
        return {ok:!failed,json:async()=>failed ? {erro:'Falha de teste'} : payload(params)};
      };
    }''')
    def load():
        page.evaluate('carregarRelatorioPrecosVendas()')
    def open_popup():
        page.locator('#vendasPrecosBody tr').first.click()
        page.wait_for_function("document.getElementById('vendasPrecosPdvsBody').textContent.includes('Mercado')")
    def names():
        return page.locator('#vendasPrecosPdvsBody tr td:first-child').all_text_contents()
    page.locator('#vendasRelTabPrecoMedio').click()
    page.wait_for_function("document.getElementById('vendasPrecosBody').textContent.includes('LONDRINA')")
    assert page.locator('#vendasVarMes').count() == 0
    assert not page.locator('.vendas-periodo-extra').first.is_visible()
    assert page.locator('#vendasViewRelatorioPrecoMedio').count() == 0
    assert page.locator('#vendasPeriodoInicio').input_value() == '2026-09-01'
    assert page.locator('#vendasPrecosHead th').all_text_contents() == ['Cidade','Produto','Mínimo','Máximo','PDVs']
    # Submenu/totais, filtros e resumo em suas respectivas linhas de desktop.
    for width in [1440,1280]:
        page.set_viewport_size({'width':width,'height':1000})
        tabs=page.locator('#vendasRelatorioTabs').bounding_box()
        totals=page.locator('#vendasRelTotaisPadrao').bounding_box()
        assert abs((tabs['y']+tabs['height']/2)-(totals['y']+totals['height']/2)) < 2
        assert totals['x'] >= tabs['x']+tabs['width']
        controls=[page.locator('#'+i).bounding_box() for i in ['vendasPeriodoInicio','vendasPeriodoFim','vendasVarVendedor','vendasPrecosGrupo']]
        assert max(b['y']+b['height'] for b in controls)-min(b['y']+b['height'] for b in controls)<2
        assert page.locator('#vendasPrecosResumo').bounding_box()['height'] < 35
    page.locator('#vendasVarVendedor').select_option('A')
    page.locator('#vendasPrecosGrupo').select_option('PET 2L')
    page.evaluate("document.getElementById('vendasPeriodoInicio').value='2026-08-15'; document.getElementById('vendasPeriodoFim').value='2026-09-20'")
    load(); open_popup()
    calls=page.evaluate('urls.slice(-2)')
    params=[parse_qs(urlsplit(url).query) for url in calls]
    assert {v.pop('tipo_relatorio')[0] for v in params} == {'preco_medio','variacao_preco'}
    assert params[0] == params[1]
    assert params[0] == {'visao':['precos_cidade'],'detalhe':['1'],'cidade':['LONDRINA'],'produto':['COLA PET 2L'],'grupo':['PET 2L'],
                        'vendedor':['A'],'data_inicio':['2026-08-15'],'data_fim':['2026-09-20']}
    assert '7,00' in page.locator('#vendasPrecosPdvsResumo').inner_text()
    count=page.evaluate('urls.length')
    snapshot=page.evaluate('JSON.stringify(vendasState.precosPdvs)')
    assert names()==['Água','Mercado 2','Mercado 10','Vazio']
    page.locator('#vendasPrecosPdvsOrdem').select_option('preco_medio')
    assert names()==['Água','Mercado 2','Mercado 10','Vazio']
    page.locator('#vendasPrecosPdvsDirecao').select_option('desc')
    assert names()==['Mercado 10','Mercado 2','Água','Vazio']
    assert page.evaluate('urls.length')==count
    assert page.evaluate('JSON.stringify(vendasState.precosPdvs)')==snapshot
    page.screenshot(path='/tmp/preco-cidade-popup-desktop.png')
    page.keyboard.press('Escape')
    assert not page.locator('#vendasPrecosPdvsDialog').is_visible()
    # Resposta antiga não substitui o vendedor atual.
    page.evaluate('''() => {pause=true; window.oldLoad=carregarRelatorioPrecosVendas();
      document.getElementById('vendasVarVendedor').value='B'; window.newLoad=carregarRelatorioPrecosVendas();}''')
    assert page.locator('#vendasPrecosBody').inner_text()==''
    page.evaluate('''async()=>{
      pending[1].resolve({ok:true,json:async()=>payload(pending[1].params)}); await newLoad;
      pending[0].resolve({ok:true,json:async()=>payload(pending[0].params)}); await oldLoad;
      pause=false; pending=[];
    }''')
    assert page.locator('#vendasVarVendedor').input_value()=='B'
    # Fechar/alterar filtros durante a consulta não reabre nem restaura PDVs antigos.
    page.evaluate('() => {pause=true; window.oldPopup=abrirPdvsPrecosVendas(0);}')
    page.keyboard.press('Escape')
    page.evaluate('''async()=>{pending.forEach(item=>item.resolve({ok:true,json:async()=>payload(item.params)}));
      await oldPopup; pause=false; pending=[];}''')
    assert not page.locator('#vendasPrecosPdvsDialog').is_visible()
    assert page.locator('#vendasPrecosPdvsBody').inner_text()==''
    # Falha parcial mantém apenas a consulta bem sucedida.
    page.evaluate("fail='preco_medio'"); open_popup()
    assert page.locator('#vendasPrecosPdvsHead th').all_text_contents()==['PDV','Mínimo','Máximo']
    assert 'Falha de teste' in page.locator('#vendasPrecosPdvsStatus').inner_text()
    page.keyboard.press('Escape'); page.evaluate("fail='variacao_preco'"); load()
    assert page.locator('#vendasPrecosBody').inner_text()==''
    assert 'Falha de teste' in page.locator('#vendasPrecosStatus').inner_text()
    page.evaluate("fail=''; empty=true"); load()
    assert 'Nenhum preço' in page.locator('#vendasPrecosBody').inner_text()
    page.evaluate('empty=false')
    for deny,allow,columns in [('preco_medio','variacao_preco',['PDV','Mínimo','Máximo']),
                               ('variacao_preco','preco_medio',['PDV','Preço médio'])]:
        page.evaluate('(d)=>{denied=[d]; urls=[]}',deny)
        load(); open_popup()
        assert page.locator('#vendasPrecosPdvsHead th').all_text_contents()==columns
        assert all(parse_qs(urlsplit(url).query)['tipo_relatorio']==[allow] for url in page.evaluate('urls'))
        page.keyboard.press('Escape')
    page.evaluate("denied=['preco_medio','variacao_preco']; urls=[]")
    load(); assert page.evaluate('urls.length')==0
    page.evaluate('denied=[]; limparFiltrosRelatorioPrecoMedioVendas()')
    page.wait_for_function("document.getElementById('vendasPrecosBody').textContent.includes('LONDRINA')")
    assert page.locator('#vendasVarVendedor').input_value()==''
    assert page.locator('#vendasPrecosGrupo').input_value()==''
    assert page.locator('#vendasPeriodoInicio').input_value()=='2026-09-01'
    page.screenshot(path='/tmp/preco-cidade-desktop.png')
    page.set_viewport_size({'width':390,'height':844})
    for name in ['vendasRelatorioHeader','vendasRelCabecalho']:
        assert page.locator('#'+name).evaluate('(el)=>el.scrollWidth<=el.clientWidth'), name
    open_popup()
    box=page.locator('#vendasPrecosPdvsDialog').bounding_box()
    assert box['x']>=0 and box['x']+box['width']<=390
    page.screenshot(path='/tmp/preco-cidade-mobile.png')
    page.keyboard.press('Escape')
    # Conteúdo importado é texto, não HTML executável.
    page.evaluate('''() => {const original=payload; payload=params=>{const data=original(params);
      data.linhas[0].produto='<img src=x onerror="window.injected=true">'; return data;};}''')
    load()
    assert page.locator('#vendasPrecosBody img').count()==0
    assert not page.evaluate('window.injected || false')
    assert not errors, errors
    browser.close()
    print('OK: layout desktop/celular, filtros, popup, ordenação, acessos, falhas, respostas antigas e escape HTML')
