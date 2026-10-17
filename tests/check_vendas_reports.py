import re
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1] / 'apps/riob/source'
html=re.sub(r'<script\b[^>]*>.*?</script>','',(root/'RioBranco.html').read_text(),flags=re.S)
html=re.sub(r'<link\b[^>]*>','',html)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/opt/google/chrome/chrome',headless=True,args=['--no-sandbox'])
 page=browser.new_page(viewport={'width':1440,'height':1000})
 page.route('**/*',lambda r:r.fulfill(body=html,content_type='text/html'))
 page.goto('http://sales.test')
 page.add_style_tag(path=str(root/'style.css'))
 page.add_script_tag(content=(root/'script.js').read_text())
 page.evaluate('''() => {
 window.onload=null;
 document.querySelectorAll('.section').forEach(el => el.style.display='none');
 document.getElementById('vendas').style.display='block';
 window.salesUrls=[];
 apiFetch=async(url)=>{salesUrls.push(url); return {ok:true,json:async()=>({
 filtros:Object.fromEntries(new URL(url,location.origin).searchParams), arquivo:{nome:'SELLOUT-2026-09.csv'}, meses_disponiveis:['2026-09'], mes_atual:'2026-09',
 cabecalho_resumo:[{nome:'RioB (valor total)',valor_venda:1050},{nome:'CLT',valor_venda:150},{nome:'Autônomos',valor_venda:900}]
 })}};
 }''')
 for tab,mode in [('Bonificacoes','bonificacoes'),('Mix','grupos_embalagem'),('PrecoMedio','variacao_preco'),('Diario','diario'),('Anual','percentual_vendas_anual')]:
  page.evaluate('salesUrls=[]')
  page.locator('#vendasRelTab'+tab).click()
  page.wait_for_function("salesUrls.length > 0 && document.getElementById('vendasRelTotaisPadrao').textContent.includes('RioB (valor total)')")
  if tab == 'PrecoMedio':
   assert page.locator('#vendasViewRelatorioVariacao').is_visible()
  opened_url=page.evaluate('salesUrls.at(-1)')
  assert ('/api/vendas/diario/relatorio?' in opened_url if mode == 'diario' else 'tipo_relatorio='+mode in opened_url), opened_url
  assert page.locator('#vendasRelTotaisPadrao').is_visible() == (tab != 'Mix')
  if tab in ('Bonificacoes', 'Diario'):
   assert page.locator('#vendasRelTotaisPadrao').evaluate("el => el.parentElement.id") == 'vendasRelatorioHeader'
   assert not page.locator('#vendasRelArquivoInfo').is_visible()
   resumo_id = '#vendasRelResumoCards' if tab == 'Bonificacoes' else '#vendasDiaResumo'
   assert 'PERÍODO' not in page.locator(resumo_id).inner_text().upper()
   ids = ['vendasPeriodoInicio', 'vendasPeriodoFim'] + (
    ['vendasRelMes', 'vendasRelVendedor', 'vendasRelCliente'] if tab == 'Bonificacoes'
    else ['vendasDiaVendedor', 'vendasDiaCliente'])
   boxes = [page.locator('#'+id).bounding_box() for id in ids]
   controle = '.vendas-bonificacoes-controle button' if tab == 'Bonificacoes' else '.vendas-diario-controle button'
   boxes += [page.locator(controle).nth(i).bounding_box() for i in range(page.locator(controle).count())]
   assert max(b['y']+b['height'] for b in boxes)-min(b['y']+b['height'] for b in boxes)<3, boxes
  page.locator('#vendasPeriodoInicio').fill('2026-09-30')
  page.locator('#vendasPeriodoFim').fill('2026-10-02')
  page.locator('#vendasPeriodoFim').blur()
  url=page.evaluate('salesUrls.at(-1)')
  assert 'data_inicio=2026-09-30' in url and 'data_fim=2026-10-02' in url and 'mes=' not in url, url
  if mode == 'diario':
   assert '/api/vendas/diario/relatorio?' in url, url
  else:
   assert 'tipo_relatorio='+mode in url, url
 page.evaluate("openVendasView(null, 'relatorio_diario')")
 assert page.locator('#vendasViewRelatorioDiario').is_visible()
 assert not page.locator('#vendasViewRelatorioAnual').is_visible()
 assert not page.locator('#vendasDiarioWorkflow').is_visible()
 page.evaluate('carregarDashboardVendasDiario()')
 assert page.evaluate('salesUrls.at(-1)') == '/api/vendas/diario/dashboard'
 assert page.locator('#dashVendasDiarioDataInicio').count() == 0
 tabs=page.locator('#vendasRelatorioTabs').bounding_box()
 totals=page.locator('#vendasRelTotaisPadrao').bounding_box()
 assert totals['x'] >= tabs['x']+tabs['width']
 assert totals['y'] < tabs['y']+tabs['height']
 assert page.locator('#vendasRelatorioHeader h2').count()==0
 # Exercise packaging filters and modal with synthetic seller/customer data.
 page.evaluate("""() => {
 apiFetch=async url => {
   salesUrls.push(url);
   const params=new URL(url, location.origin).searchParams;
   const vendedores=params.getAll('vendedor').filter(Boolean);
   const cliente=params.get('cliente') || '';
   const clientes=[{chave:'A',cliente:'Mercado A',cidade:'Cidade',vendedor:'Vendedor A',qtd_grupos:1,grupos_lista:'PET 2L'},
                   {chave:'B',cliente:'Mercado B',cidade:'Cidade',vendedor:'Vendedor A',qtd_grupos:1,grupos_lista:'PET 600ml'}];
   return {ok:true,json:async()=>({arquivo:{nome:'SELLOUT.csv'},
     mes_atual:params.has('data_inicio') || params.has('data_fim') ? '' : '2026-09',
     grupos_disponiveis:['PET 2L','PET 600 ml','PET 200 ml','Água','600 ml retornável','200 ml retornável'],
     filtros:{...Object.fromEntries(params),vendedor:vendedores.length===1 ? vendedores[0] : '',vendedores:params.has('vendedor') ? vendedores : null,grupos:params.has('grupos') ? params.get('grupos').split(',').filter(Boolean) : null},
     vendedores:[{chave:'VENDEDOR A',nome:'Vendedor A'},{chave:'VENDEDOR B',nome:'Vendedor B'},{chave:'VENDEDOR C',nome:'Vendedor C'}],
     clientes:cliente ? clientes.filter(c=>c.chave===cliente) : clientes,
     clientes_disponiveis:clientes, detalhe_pdv:clientes.find(c=>c.chave===cliente),
     resumo_geral:{pdvs:2},resumo_faixas:[{faixa:'2 grupos',pdvs:1,percentual:50},{faixa:'1 grupo',pdvs:1,percentual:50}]
   })};
 };
 }""")
 page.locator('#vendasRelTabMix').click()
 assert not page.locator('#vendasRelTotaisPadrao').is_visible()
 assert page.locator('#vendasMixMes').count() == 0
 assert not page.locator('#vendasMixVerPdvs').is_visible()
 assert not page.locator('#vendasMixPdvsDialog').is_visible()
 page.locator('#vendasMixVendedoresBtn').click()
 page.get_by_label('Vendedor C',exact=True).uncheck()
 page.get_by_role('button',name='Aplicar vendedores',exact=True).click()
 assert page.locator('#vendasMixVerPdvs').is_visible()
 assert page.locator('#vendasMixVendedoresBtn').inner_text()=='Vendedores (2)'
 assert page.evaluate("new URL(salesUrls.at(-1), location.origin).searchParams.getAll('vendedor')") == ['VENDEDOR A','VENDEDOR B']
 assert 'mes=' not in page.evaluate('salesUrls.at(-1)')
 boxes=[page.locator('#'+id).bounding_box() for id in ['vendasPeriodoInicio','vendasPeriodoFim','vendasMixVendedoresBtn','vendasMixCliente','vendasMixGruposBtn','vendasMixVerPdvs']]
 assert max(b['y']+b['height'] for b in boxes)-min(b['y']+b['height'] for b in boxes)<3, boxes
 summary=page.locator('.vendas-mix-resumo').bounding_box()
 view=page.locator('#vendasViewRelatorioMix').bounding_box()
 assert abs(summary['width']-view['width'])<2
 assert page.locator('#vendasMixResumoCards').bounding_box()['y'] > summary['y']+summary['height']
 page.locator('#vendasMixVerPdvs').click()
 assert page.locator('#vendasMixPdvsDialog').is_visible()
 assert '30/09/2026 a 02/10/2026' in page.locator('#vendasMixPdvsContexto').inner_text()
 before=page.evaluate('salesUrls.length')
 page.locator('#vendasMixClientesBody button').first.click()
 assert 'PET 2L' in page.locator('#vendasMixDetalheBody').inner_text()
 assert page.locator('#vendasMixClientesBody tr').count()==2
 assert page.locator('#vendasMixCliente').input_value()==''
 assert page.evaluate('salesUrls.length')==before
 page.keyboard.press('Escape')
 assert not page.locator('#vendasMixPdvsDialog').is_visible()
 assert page.locator('#vendasMixVerPdvs').evaluate('(el)=>el===document.activeElement')
 page.locator('#vendasMixCliente').select_option('A')
 page.locator('#vendasMixVendedoresBtn').click()
 page.get_by_label('Vendedor A',exact=True).uncheck()
 page.get_by_role('button',name='Aplicar vendedores',exact=True).click()
 assert page.locator('#vendasMixCliente').input_value()==''
 assert 'cliente=' not in page.evaluate('salesUrls.at(-1)')
 # Group selection combines with the PDV and dates and persists after reopening.
 page.locator('#vendasMixCliente').select_option('A')
 page.locator('#vendasMixGruposBtn').click()
 page.get_by_label('600 ml retornável',exact=True).uncheck()
 page.get_by_label('200 ml retornável',exact=True).uncheck()
 page.get_by_role('button',name='Aplicar grupos',exact=True).click()
 assert page.locator('#vendasMixCliente').input_value()=='A'
 params=page.evaluate("Object.fromEntries(new URL(salesUrls.at(-1), location.origin).searchParams)")
 assert params['grupos']=='PET 2L,PET 600 ml,PET 200 ml,Água', params
 assert params['cliente']=='A' and params['data_inicio']=='2026-09-30', params
 assert page.locator('#vendasMixGruposBtn').inner_text()=='Grupos (4)'
 page.locator('#vendasMixGruposBtn').click()
 assert not page.get_by_label('600 ml retornável',exact=True).is_checked()
 assert page.get_by_label('Água',exact=True).is_checked()
 page.get_by_role('button',name='Desmarcar todos',exact=True).click()
 page.get_by_role('button',name='Aplicar grupos',exact=True).click()
 assert page.locator('#vendasMixGruposResumo').inner_text()=='Grupos: nenhum.'
 assert page.evaluate("new URL(salesUrls.at(-1), location.origin).searchParams.get('grupos')") == ''
 page.locator('#vendasMixGruposBtn').click()
 page.get_by_role('button',name='Selecionar todos',exact=True).click()
 page.get_by_role('button',name='Aplicar grupos',exact=True).click()
 assert page.evaluate("new URL(salesUrls.at(-1), location.origin).searchParams.has('grupos')") is False
 page.locator('#vendasRelCabecalho').get_by_role('button',name='Limpar filtros',exact=True).click()
 assert not page.locator('#vendasMixVerPdvs').is_visible()
 assert page.locator('#vendasPeriodoInicio').input_value()=='2026-09-01'
 assert page.locator('#vendasPeriodoFim').input_value()=='2026-09-30'
 page.set_viewport_size({'width':390,'height':844})
 assert page.locator('#vendasPeriodoFim').is_visible()
 assert page.evaluate("document.getElementById('vendasRelatorioHeader').scrollWidth <= document.getElementById('vendasRelatorioHeader').clientWidth")
 assert page.evaluate("document.getElementById('vendasRelCabecalho').scrollWidth <= document.getElementById('vendasRelCabecalho').clientWidth")
 page.locator('#vendasMixVendedoresBtn').click()
 page.get_by_label('Vendedor B',exact=True).uncheck()
 page.get_by_label('Vendedor C',exact=True).uncheck()
 page.get_by_role('button',name='Aplicar vendedores',exact=True).click()
 page.locator('#vendasMixVerPdvs').click()
 modal=page.locator('#vendasMixPdvsDialog').bounding_box()
 assert modal['x']>=0 and modal['x']+modal['width']<=390
 page.locator('#vendasMixPdvsDialog').get_by_role('button',name='Fechar',exact=True).click()
 assert not page.locator('#vendasMixPdvsDialog').is_visible()
 browser.close()
 print('OK: cinco abas, cabecalhos compactos, periodo entre meses, filtros em linha, resumos, popup de PDVs e celular')
