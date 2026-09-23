"""Fluxo real do navegador com APIs sinteticas, sem alterar estoque operacional."""
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1] / 'apps/riob/source'

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/opt/google/chrome/chrome', headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    html = re.sub(r'<(?:script\b[^>]*>.*?</script|link\b[^>]*)>', '', (ROOT/'RioBranco.html').read_text(), flags=re.S)
    page.route('**/*', lambda route: route.fulfill(body=html, content_type='text/html'))
    page.goto('http://contagem.test')
    page.add_style_tag(path=str(ROOT/'style.css'))
    for script in ('script.js', 'estoque_contagem.js'):
        page.add_script_tag(path=str(ROOT/script))
    page.evaluate('''() => {
      window.onload=null; window.testRequests=[]; window.testConflict=false;
      usuarioLogado={id:42,perfil:'usuario'};
      window.testItems=[
        {produto_id:7,nome_produto:'Produto <b>teste</b>',saldo_antes:131,quantidade_contada:123,diferenca:-8,desperdicio:8,sobra:0,por_pallet:100,por_volume:10},
        {produto_id:8,nome_produto:'Produto sobra',saldo_antes:130,quantidade_contada:135,diferenca:5,desperdicio:0,sobra:5,por_pallet:100,por_volume:10}
      ];
      ensureProdutosEstoqueCache=async()=>{
        estoqueState.cadastroProdutos=[7,8,9,10,11].map(id=>({id,nome_produto:'Produto '+id,codigo_barras:String(id),
          grupo_estoque:({7:'GFA',8:'PET',9:'OUTROS',10:'AGUA',11:'PERSONALIZADO'})[id],
          estoque_area:id===11?'ALMOXARIFADO_GERAL':'PRODUCAO',
          estoque_subgrupo:id===9?'MATERIA_PRIMA':id===11?'GERAL':'PRODUTOS',
          grupo_nome:id===11?'Material <b>teste</b>':null,
          quantidade_atual:130,pallet_meta:{unidades_por_pallet:id===9?0:100,unidades_por_volume:id===9?0:10,rotulo_volume:id===7?'caixas':'pacotes'}}));
      };
      _saldoProdutoCadastroAtual=()=>130;
      apiFetch=async(url,options={})=>{
        testRequests.push([url,options.method || 'GET',options.body && JSON.parse(options.body)]);
        let data=[]; let ok=true;
        if(url.includes('/contagens/')){
          data={id:21,status:'conferida',itens:testItems,resumo:{desperdicio:8,sobra:5}};
          if(url.endsWith('/finalizar')){
            await new Promise(r=>setTimeout(r,80));
            data.status='finalizada';
            if(testConflict){ok=false;data={erro:'Estoque ou cadastro mudou depois da conferencia. Feche o popup e confira novamente.'};}
          }
          if(url.includes('/relatorio')) data={
            itens:testItems.map(i=>({...i,contagem_id:21,finalizado_em:'2026-09-11T08:30:00',usuario:'Operador',observacao:'Turno <b>1</b>'})),
            resumo:{total:51,desperdicio:8,sobra:5},pagina:url.includes('pagina=2')?2:1,limite:50};
        }
        return {ok,status:ok?200:409,json:async()=>data};
      };
      openEstoqueView(null,'contagem');
    }''')
    page.wait_for_function("document.querySelectorAll('#estoqueContagemBody tr[data-id]').length === 5")
    groups=page.locator('#estoqueContagemBody .estoque-group-row').all_text_contents()
    assert groups==['Produção — Produtos','Retornavel','PET','AGUA','Produção — Matéria-prima','Outros','Almoxarifado geral','Material <b>teste</b>'],groups
    assert page.locator('#estoqueContagemBody .estoque-group-row b').count()==0
    assert '1 pallet e 3 cx' in page.locator('tr[data-id="7"] .estoque-saldo-logistica').inner_text()
    assert page.locator('tr[data-id="7"] input[aria-label="volumes"]').get_attribute('title')=='Caixas (CX)'
    assert page.locator('tr[data-id="8"] input[aria-label="volumes"]').get_attribute('title')=='Pacotes (PCT)'
    assert page.locator('tr[data-id="9"] input[aria-label="pallets"]').is_disabled()
    assert page.locator('tr[data-id="9"] input[aria-label="volumes"]').is_disabled()
    page.locator('#estoqueContagemFinalizar').click()
    assert 'Informe ao menos' in page.locator('#estoqueContagemStatus').inner_text()
    for field,value in [('pallets','1'),('volumes','2'),('unidades','3')]:
        page.locator(f'tr[data-id="7"] input[aria-label="{field}"]').fill(value)
    page.locator('tr[data-id="8"] input[aria-label="unidades"]').fill('135')
    assert page.locator('tr[data-id="7"] [data-total] .estoque-saldo-logistica').inner_text()=='1 pallet e 2 cx'
    assert page.locator('tr[data-id="7"] [data-total] .estoque-saldo-unidades').inner_text()=='Total: 123 uni'
    assert page.locator('tr[data-id="8"] [data-total] .estoque-saldo-logistica').inner_text()=='1 pallet e 3 pacotes'
    page.locator('#estoqueContagemObservacao').fill('Turno 1')
    page.locator('#estoqueContagemBusca').fill('Produto 7')
    assert page.locator('#estoqueContagemBody .estoque-group-row').all_text_contents()==['Produção — Produtos','Retornavel']
    page.locator('#estoqueContagemBusca').fill('')
    assert page.locator('tr[data-id="8"] input[aria-label="unidades"]').input_value()=='135'
    page.locator('#estoqueContagemBusca').fill('Produto 7')
    page.locator('#estoqueContagemFinalizar').click()
    popup=page.locator('#contagemConferenciaModal')
    assert popup.is_visible()
    assert page.locator('#contagemConferenciaBody tr[data-produto-id]').count()==2
    assert page.locator('#contagemConferenciaBody .estoque-group-row').all_text_contents()==['Produção — Produtos','Retornavel','PET']
    assert page.locator('#contagemConferenciaBody b').count()==0
    assert '131' in page.locator('#contagemConferenciaBody').inner_text()
    assert page.locator('#contagemConferenciaBody tr[data-produto-id]').first.locator('.estoque-saldo-logistica').all_text_contents()==['1 pallet e 3 cx','1 pallet e 2 cx']
    assert 'Possivel erro de contagem' in page.locator('#contagemConferenciaBody').inner_text()
    assert '3 nao preenchido' in page.locator('#contagemConferenciaResumo').inner_text()
    requests=page.evaluate('testRequests')
    preview=[r for r in requests if r[0].endswith('/conferir')][-1]
    assert [i['produto_id'] for i in preview[2]['itens']]==[7,8]
    assert preview[2]['observacao']=='Turno 1'
    assert not any(r[0].endswith('/finalizar') for r in requests)
    for width in (1440,390):
        page.set_viewport_size({'width':width,'height':1000})
        assert popup.is_visible()
        box=page.locator('#contagemConferenciaModal .vendas-diario-modal-content').bounding_box()
        assert box['x']>=0 and box['x']+box['width']<=width+1, box
    page.locator('#contagemConferenciaVoltar').click()
    assert not popup.is_visible()
    page.locator('#estoqueContagemFinalizar').click()
    # Conflito preserva a contagem e exige nova conferencia.
    page.evaluate('testConflict=true')
    popup.get_by_role('button',name='Confirmar e ajustar estoque').click()
    page.wait_for_function("document.querySelector('#contagemConferenciaStatus').textContent.includes('mudou')")
    assert popup.is_visible()
    assert not page.evaluate('!!contagemEstoque.finalizada')
    page.locator('#contagemConferenciaVoltar').click()
    page.evaluate('testConflict=false')
    page.locator('#estoqueContagemFinalizar').click()
    page.evaluate('confirmarFinalizacaoContagem(); confirmarFinalizacaoContagem();')
    page.wait_for_function('contagemEstoque.finalizada === 21')
    assert not popup.is_visible()
    assert page.locator('#estoqueContagemFinalizar').is_disabled()
    assert page.locator('#estoqueContagemObservacao').is_disabled()
    assert page.locator('tr[data-id="7"] input[aria-label="unidades"]').is_disabled()
    assert 'desperdicio 8' in page.locator('#estoqueContagemIndicadores').inner_text()
    assert len([r for r in page.evaluate('testRequests') if r[0].endswith('/finalizar')])==2
    page.get_by_role('button',name='Nova contagem',exact=True).click()
    assert page.locator('#estoqueContagemObservacao').input_value()==''
    assert not page.locator('#estoqueContagemObservacao').is_disabled()
    page.evaluate("openRelatoriosView(null,'contagens')")
    page.wait_for_function("document.querySelector('#relContBody').textContent.includes('Operador')")
    assert page.locator('#relatoriosViewContagens').is_visible()
    assert not page.locator('#relatoriosViewOrcamentos').is_visible()
    assert page.locator('#relContBody b').count()==0
    assert page.locator('#relContAnterior').is_disabled()
    page.locator('#relContProxima').click()
    page.wait_for_function('relatorioContagensPagina === 2')
    assert page.locator('#relContProxima').is_disabled()
    page.locator('#relContTipo').select_option('desperdicio')
    page.evaluate("window.open=(url)=>window.pdfUrl=url; imprimirRelatorioContagens()")
    assert 'tipo=desperdicio' in page.evaluate('pdfUrl')
    assert not errors,errors
    browser.close()
    print('OK: popup desktop/mobile, saldo atualizado, campos vazios, conflito, confirmacao unica e relatorio.')
