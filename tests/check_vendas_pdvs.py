"""Tela real, API sintetica: importar, conferir, atualizar e consultar percentuais."""
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1] / 'apps/riob/source'
html = re.sub(r'<script\b[^>]*>.*?</script>', '', (ROOT/'RioBranco.html').read_text(), flags=re.S)
html = re.sub(r'<link\b[^>]*>', '', html)
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/opt/google/chrome/chrome',headless=True,args=['--no-sandbox'])
    page = browser.new_page(viewport={'width':1440,'height':1000})
    page.route('**/*', lambda route: route.fulfill(body=html,content_type='text/html'))
    page.goto('http://pdvs.test')
    page.add_style_tag(path=str(ROOT/'style.css'))
    page.add_script_tag(content=(ROOT/'script.js').read_text())
    page.add_script_tag(content=(ROOT/'vendas_pdvs.js').read_text())
    page.evaluate('''() => {
      window.onload = null;
      window.pdvsSaved = null;
      apiFetch = async (url, options = {}) => {
        const vendedor = {chave:'006 - VINICIUS',codigo:'006',nome:'VINICIUS'};
        let data = {vendedores:[vendedor],totais:pdvsSaved ? [{vendedor_key:vendedor.chave,total:400,importacao_id:1}] : []};
        if (url.endsWith('/conferir')) data = {...data, itens:[{vendedor_key:vendedor.chave,total:408,com_compra_pdf:335}],texto:'PDF de conferencia'};
        else if (options.method === 'POST') { pdvsSaved = JSON.parse(options.body.get('itens')); data = {atualizados:1}; }
        return {ok:true,json:async()=>data};
      };
      openVendasView(null,'pdvs_totais');
    }''')
    assert page.locator('#pdvsTotais').is_visible()
    assert not page.locator('#vendas').is_visible()
    page.locator('#pdvsArquivo').set_input_files({'name':'teste.pdf','mimeType':'application/pdf','buffer':b'%PDF-test'})
    page.get_by_role('button',name='Ler PDF e conferir').click()
    assert page.locator('#pdvsConferencia').is_visible()
    assert page.get_by_label('Total de PDVs',exact=True).input_value() == '408'
    assert '335' in page.locator('#pdvsConferenciaBody').inner_text()
    page.get_by_label('Total de PDVs',exact=True).fill('400')
    page.get_by_role('button',name='Confirmar e atualizar totais').click()
    page.wait_for_function("document.getElementById('pdvsStatus').textContent.includes('1 totais atualizados')")
    assert page.evaluate('pdvsSaved[0].total') == '400'
    assert '400' in page.locator('#pdvsAtuais').inner_text()
    assert not page.locator('#pdvsConferencia').is_visible()
    page.evaluate('''() => {
      showTab('vendas');
      document.getElementById('vendasViewRelatorioMix').classList.remove('hidden');
      document.getElementById('vendasMixResumoCards').innerHTML = _renderCardsVendasResumo(_vendasResumoMixEmbalagensCards({pdvs:8,total_carteira:400}));
      _vendasRenderMixEmbalagensFaixas([{faixa:'6',pdvs:8,percentual:2},{faixa:'5',pdvs:0,percentual:null}]);
    }''')
    assert '2,00%' in page.locator('#vendasMixFaixasBody').inner_text()
    assert 'Pendente' in page.locator('#vendasMixFaixasBody').inner_text()
    assert 'pdvs com venda' in page.locator('#vendasMixResumoCards').inner_text().lower(), page.locator('#vendasMixResumoCards').inner_text()
    assert '400' in page.locator('#vendasMixResumoCards').inner_text()
    page.evaluate("""() => {
      document.getElementById('vendasMixResumoCards').innerHTML = _renderCardsVendasResumo(
        _vendasResumoMixEmbalagensCards({pdvs:3396,total_carteira:null,total_carteira_importada:4297,
          carteiras_pendentes:['012 - NORIVAL VIGNOTO'],aviso_carteira:'Carteira parcial: falta Norival.'}));
    }""")
    cards = page.locator('#vendasMixResumoCards').inner_text().lower()
    assert '4.297' in cards and 'parcial' in cards
    assert 'Pendente' not in page.locator('#vendasMixResumoCards').inner_text()
    assert 'Norival' in page.locator('#vendasMixCarteiraInfo').inner_text()
    page.evaluate("openVendasView(null,'pdvs_totais')")
    page.set_viewport_size({'width':390,'height':844})
    assert page.get_by_role('button',name='Ler PDF e conferir').is_visible()
    assert page.locator('#pdvsTotais').evaluate('(el) => el.scrollWidth <= el.clientWidth')
    browser.close()
print('OK: Dados, PDF, conferencia editavel, salvar, carteira 400, 2%, pendencia e celular')
