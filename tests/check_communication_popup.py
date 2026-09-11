import re
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1] / 'apps/riob/source'
html=(root/'RioBranco.html').read_text()
html=re.sub(r'<script\b[^>]*>.*?</script>','',html,flags=re.S)
html=re.sub(r'<link\b[^>]*>','',html)
script=(root/'script.js').read_text()
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/opt/google/chrome/chrome',headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.route('**/*',lambda r:r.fulfill(body=html,content_type='text/html'))
    page.goto('http://communication.test')
    page.add_style_tag(path=str(root/'style.css'))
    page.add_script_tag(content=script)
    page.evaluate('''() => {
      window.onload=null;
      initSipClient=async()=>true;
      apiFetch=async(url)=>({ok:true,json:async()=>url.includes('/conversa') ? [] : {por_contato:[],total:0}});
      cacheUsuarios=[{id:1,nome:'Pessoa atual',login:'pessoa'},{id:2,nome:'Contato Chat',login:'chat',sip_ramal:'1002'},{id:3,nome:'Contato Telefone',login:'telefone',sip_ramal:'1003'}];
      chatState.usuarioId='1';
      sipState.me={sip_habilitado:true};
      sipState.ua={};sipState.isRegistered=true;
    }''')
    page.locator('#chatFab').click()
    page.wait_for_timeout(100)
    assert page.locator('#chatWidget').is_visible()
    assert page.locator('#chatContatosLista .chat-contato').count()==2
    assert not page.locator('#chatSipCallBtn').is_visible()
    assert page.locator('#chatWidget button',has_text='Minimizar').count()==1
    page.locator('#chatTexto').fill('Rascunho humano')
    page.locator('#communicationTabIa').click()
    assert page.locator('#chatContatoAtualNome').inner_text()=='I.A-Rio'
    assert not page.locator('.chat-sidebar').is_visible()
    page.locator('#chatTexto').fill('Rascunho IA')
    page.locator('[data-communication-ia=agent]').click()
    assert page.locator('#agentIaInput').is_visible()
    assert not page.locator('#chatTexto').is_visible()
    page.locator('#communicationTabTelefonia').click()
    assert page.locator('#chatSipCallBtn').is_visible()
    page.locator('#communicationPhoneContact').select_option('3')
    assert page.evaluate('chatState.phoneContactId')=='3'
    page.locator('#communicationTabChat').click()
    assert page.locator('#chatTexto').input_value()=='Rascunho humano'
    assert page.evaluate('chatState.contatoId')=='2'
    page.locator('#communicationTabIa').click()
    page.locator('[data-communication-ia=conversa]').click()
    assert page.locator('#chatTexto').input_value()=='Rascunho IA'
    page.evaluate('''() => {
      window.testCall={isEstablished:()=>true,isEnded:()=>false,isInProgress:()=>false,on:()=>{},terminate:()=>{throw new Error('Chamada encerrada indevidamente')}};
      sipState.currentSession=window.testCall;
      sipState.currentDirection='outgoing';
      atualizarEstadoSipChat();
    }''')
    page.locator('#communicationTabTelefonia').click()
    page.locator('#chatWidget button',has_text='Minimizar').click()
    assert not page.locator('#chatWidget').is_visible()
    assert page.evaluate('sipState.currentSession===window.testCall')
    page.locator('#chatFab').click()
    assert page.locator('#chatSipHangupMainBtn').is_visible()
    page.locator('#communicationTabChat').click()
    assert page.evaluate('sipState.currentSession===window.testCall')
    assert page.locator('#communicationCallBadge').is_visible()
    page.evaluate("showTab('agentia')")
    assert page.locator('#agentIaInput').is_visible()
    for width in [1440,390,320]:
        page.set_viewport_size({'width':width,'height':900})
        for tab in ['chat','ia','telefonia']:
            page.evaluate('(tab)=>setCommunicationTab(tab)',tab)
            page.wait_for_timeout(60)
            bounds=page.locator('#chatWidget').bounding_box()
            assert bounds['x']>=0 and bounds['x']+bounds['width']<=width,(width,tab,bounds)
            assert page.locator('#chatWidget button',has_text='Minimizar').is_visible()
            if width==390:page.screenshot(path='/tmp/communication-'+tab+'.png')
    # A chamada recebida abre os controles no mesmo popup.
    page.evaluate("_sipBindSession(window.testCall, 'incoming', 'Ramal 1003')")
    page.wait_for_timeout(100)
    assert page.locator('#communicationPhonePanel').is_visible()
    assert page.locator('#chatWidget').is_visible()
    # Uma resposta de chat atrasada nao invade a conversa com a IA.
    page.evaluate("setCommunicationTab('chat')")
    page.evaluate("""() => {
      const original=apiFetch;
      apiFetch=async(url)=>url.includes('/conversa') ? new Promise(resolve=>window.resolveLateChat=resolve) : original(url);
      window.pendingChat=carregarChat();
    }""")
    page.evaluate("setCommunicationTab('ia', 'conversa')")
    page.evaluate("""() => window.resolveLateChat({ok:true,json:async()=>[{mensagem:'Mensagem atrasada',remetente_id:2}]})""")
    page.wait_for_timeout(100)
    assert 'Mensagem atrasada' not in page.locator('#chatMensagens').inner_text()
    assert not errors,errors
    print('OK: chat, IA, Agent, telefonia, drafts, active call, minimize, legacy shortcut, desktop/mobile.')
    browser.close()
