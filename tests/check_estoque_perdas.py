"""Formulario real com API sintetica; nenhuma baixa em banco operacional."""
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root=Path(__file__).resolve().parents[1]/'apps/riob/source'
html=re.sub(r'<script\b[^>]*>.*?</script>','',(root/'RioBranco.html').read_text(),flags=re.S)
html=re.sub(r'<link\b[^>]*>','',html)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/opt/google/chrome/chrome',headless=True,args=['--no-sandbox'])
 page=browser.new_page(viewport={'width':1440,'height':1000})
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.route('**/*',lambda r:r.fulfill(body=html,content_type='text/html'))
 page.goto('http://loss.test')
 page.add_style_tag(path=str(root/'style.css'))
 page.add_script_tag(path=str(root/'script.js'))
 page.add_script_tag(path=str(root/'estoque_perdas.js'))
 page.evaluate('''() => {
  window.onload=null;
  document.querySelectorAll('.section').forEach(el=>el.classList.remove('active'));
  window.lossRequests=[];window.lossMoves=0;window.lossConflict=true;window.lossPreview=null;
  apiFetch=async(url,options={})=>{
   lossRequests.push([url,options]);
   let data={},status=200;
   if(url.endsWith('/perdas/produtos')) data={hoje:'2026-10-01',motivos:{avaria:'Avaria',desperdicio:'Desperdício'},produtos:[{produto_id:1,produto_key:'1',nome_produto:'Produto teste',codigo_produto_nfe:'123',saldo:100,por_pallet:10,por_volume:2,unidade:'UN'}]};
   else if(url.endsWith('/perdas/conferir')) {
    const payload=JSON.parse(options.body);const amount=Number(payload.pallets)*10+Number(payload.volumes)*2+Number(payload.unidades);
    data=lossPreview={...payload,id:1,nome_produto:'Produto teste',quantidade:amount,saldo_antes:100,saldo_depois:100-amount,unidade:'UN'};
   } else if(url.endsWith('/finalizar')) {
    if(lossConflict){status=409;data={erro:'Estoque mudou. Volte e confira novamente.'};lossConflict=false;}
    else {lossMoves++;data={...lossPreview,status:'finalizada'};}
   } else if(url.includes('/api/estoque/perdas?')) data={itens:lossMoves?[{...lossPreview,usuario:'Operador',finalizado_em:'2026-10-01T10:00:00'}]:[],total:lossMoves,totais_unidade:lossMoves?[{unidade:'UN',quantidade:lossPreview.quantidade}]:[],pagina:1,limite:50};
   return {ok:status===200,status,json:async()=>data};
  };
  openEstoqueView(null,'perdas');
 }''')
 expect(page.locator('#estoqueViewPerdas')).to_be_visible()
 expect(page.locator('#estoqueViewContagem')).not_to_be_visible()
 expect(page.locator('#estoqueViewConferir')).not_to_be_visible()
 expect(page.locator('#perdaNova')).to_be_enabled()
 page.locator('#perdaNova').click()
 page.locator('#perdaProduto').select_option('1')
 page.locator('#perdaVolumes').fill('2')
 page.locator('#perdaUnidades').fill('1')
 page.locator('#perdaMotivo').select_option('avaria')
 page.locator('#perdaJustificativa').fill('Quebra na armazenagem <img src=x onerror=alert(1)>')
 page.locator('#perdaConferir').click()
 expect(page.locator('#perdaConferencia')).to_be_visible()
 expect(page.locator('#perdaConferenciaTexto')).to_contain_text('baixar 5 UN')
 assert page.evaluate('lossMoves')==0
 page.locator('#perdaConfirmar').click()
 expect(page.locator('#perdaStatus')).to_contain_text('Estoque mudou')
 assert page.evaluate('lossMoves')==0
 page.locator('#perdaVoltar').click()
 page.locator('#perdaConferir').click()
 expect(page.locator('#perdaConferencia')).to_be_visible()
 page.locator('#perdaConfirmar').click()
 expect(page.locator('#perdaStatus')).to_contain_text('Baixa #1 confirmada')
 expect(page.locator('#perdaFormulario')).not_to_be_visible()
 expect(page.locator('#perdaHistoricoBody')).to_contain_text('Quebra na armazenagem <img')
 assert page.locator('#perdaHistoricoBody img').count()==0
 assert page.evaluate('lossMoves')==1
 page.locator('#perdaInicio').fill('2026-09-01')
 page.locator('#perdaFim').fill('2026-10-01')
 page.locator('#perdaBusca').fill('Produto teste')
 page.get_by_role('button',name='Filtrar',exact=True).click()
 assert page.evaluate("lossRequests.at(-1)[0].includes('inicio=2026-09-01')")
 page.set_viewport_size({'width':390,'height':844})
 page.locator('#perdaNova').click()
 expect(page.locator('#perdaJustificativa')).to_be_visible()
 assert page.evaluate("document.getElementById('perdaCampos').scrollWidth <= document.getElementById('perdaCampos').clientWidth")
 page.locator('#perdaFormulario button',has_text='Cancelar').click()
 assert page.evaluate('lossMoves')==1
 assert not errors,errors
 browser.close()
 print('OK: navegacao, formulario, conversao, conflito, confirmacao, historico, filtros, XSS e celular')
