const processosInternosState = { rows: [], opcoes: { tipos: [], colaboradores: [] } };
const comprasGestaoState = { rows: [], opcoes: { produtos: [], fornecedores: [], colaboradores: [] }, previsao: [], previsaoOpcoes: {}, fornecedores: [] };

const gestaoProcessoStatusLabel = { solicitado: "Solicitado", analise: "Em análise", execucao: "Em execução", aguardando: "Aguardando", concluido: "Concluído", cancelado: "Cancelado" };
const gestaoCompraStatusLabel = { solicitado: "Solicitado", cotacao: "Cotação", aprovacao: "Aprovação", pedido: "Pedido emitido", aguardando: "Aguardando entrega", recebido: "Recebido", cancelado: "Cancelado" };

function gestaoEsc(value){
  if (typeof _escHtml === "function") return _escHtml(value ?? "");
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
}

function gestaoNumero(value, casas = 3){
  return Number(value || 0).toLocaleString("pt-BR", {minimumFractionDigits: 0, maximumFractionDigits: casas});
}

function gestaoMoeda(value){
  return Number(value || 0).toLocaleString("pt-BR", {style:"currency", currency:"BRL"});
}

function gestaoFornecedorNome(row){
  return row?.nome_exibicao || row?.nome || row?.dominios || row?.emails || `Fornecedor #${row?.id || "-"}`;
}

function gestaoDataHoje(){ return new Date().toISOString().slice(0, 10); }

function gestaoSetOptions(id, rows, placeholder, valueKey = "id", labelFn = (row) => row.nome || row.nome_produto || row.id){
  const select = document.getElementById(id);
  if (!select) return;
  const atual = select.value;
  select.innerHTML = `<option value="">${gestaoEsc(placeholder)}</option>` + (rows || []).map((row) => `<option value="${gestaoEsc(row[valueKey])}">${gestaoEsc(labelFn(row))}</option>`).join("");
  if ([...select.options].some((option) => option.value === atual)) select.value = atual;
}

function gestaoResumoCards(id, cards){
  const box = document.getElementById(id);
  if (!box) return;
  box.innerHTML = cards.map((card) => `<div class="vendas-resumo-card"><span>${gestaoEsc(card.label)}</span><strong>${gestaoEsc(card.value)}</strong>${card.hint ? `<small>${gestaoEsc(card.hint)}</small>` : ""}</div>`).join("");
}

async function carregarProcessosInternos(){
  const resp = await apiFetch("/api/processos-internos");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.erro || "Falha ao carregar processos internos.");
  processosInternosState.rows = data.rows || [];
  processosInternosState.opcoes = data.opcoes || {tipos:[], colaboradores:[]};
  gestaoSetOptions("processosInternosTipoFiltro", processosInternosState.opcoes.tipos, "Todos os tipos");
  gestaoSetOptions("processoInternoTipo", processosInternosState.opcoes.tipos, "Geral");
  gestaoSetOptions("processoInternoResponsavel", processosInternosState.opcoes.colaboradores, "Sem responsável");
  renderProcessosInternosKanban();
}

function renderProcessosInternosKanban(){
  const busca = String(document.getElementById("processosInternosBusca")?.value || "").trim().toLowerCase();
  const tipo = Number(document.getElementById("processosInternosTipoFiltro")?.value || 0);
  const rows = processosInternosState.rows.filter((row) => {
    if (tipo && Number(row.tipo_id) !== tipo) return false;
    const texto = [row.titulo, row.tipo_nome, row.solicitante, row.responsavel_nome, row.descricao].join(" ").toLowerCase();
    return !busca || texto.includes(busca);
  });
  const statusIds = { solicitado:"Solicitado", analise:"Analise", execucao:"Execucao", aguardando:"Aguardando", concluido:"Concluido" };
  Object.entries(statusIds).forEach(([status, suffix]) => {
    const itens = rows.filter((row) => row.status === status);
    const count = document.getElementById(`processosCount${suffix}`);
    if (count) count.textContent = itens.length;
    const col = document.getElementById(`processosCol${suffix}`);
    if (col) col.innerHTML = itens.map((row) => processoInternoCardHtml(row)).join("") || '<div class="gestao-kanban-empty">Nenhum processo</div>';
  });
  document.querySelectorAll("[data-processo-status]").forEach((col) => {
    col.ondragover = (ev) => ev.preventDefault();
    col.ondrop = (ev) => { ev.preventDefault(); moverProcessoInterno(Number(ev.dataTransfer.getData("text/processo-id")), col.dataset.processoStatus); };
  });
  const resumo = document.getElementById("processosInternosResumo");
  if (resumo) resumo.textContent = `${rows.length} processo(s) visível(is) • ${rows.filter((row) => row.atrasado).length} atrasado(s)`;
}

function processoInternoCardHtml(row){
  return `<article class="gestao-kanban-card prioridade-${gestaoEsc(row.prioridade)} ${row.atrasado ? "is-overdue" : ""}" draggable="true" ondragstart="event.dataTransfer.setData('text/processo-id','${Number(row.id)}')" onclick="editarProcessoInterno(${Number(row.id)})">
    <div class="gestao-card-head"><span style="--tipo-cor:${gestaoEsc(row.tipo_cor || '#2563eb')}">${gestaoEsc(row.tipo_nome || "Geral")}</span><strong>${gestaoEsc(row.prioridade || "normal")}</strong></div>
    <h4>${gestaoEsc(row.titulo)}</h4><p>${gestaoEsc(row.descricao || "Sem descrição")}</p>
    <div class="gestao-card-meta"><span>${gestaoEsc(row.responsavel_nome || "Sem responsável")}</span><span>${row.prazo ? `Prazo ${gestaoEsc(row.prazo)}` : "Sem prazo"}</span></div>
  </article>`;
}

function abrirFormularioProcessoInterno(row = null){
  document.getElementById("processoInternoId").value = row?.id || "";
  document.getElementById("processoInternoTitulo").value = row?.titulo || "";
  document.getElementById("processoInternoTipo").value = row?.tipo_id || "";
  document.getElementById("processoInternoSolicitante").value = row?.solicitante || usuarioLogado?.nome || "";
  document.getElementById("processoInternoResponsavel").value = row?.responsavel_id || "";
  document.getElementById("processoInternoPrioridade").value = row?.prioridade || "normal";
  document.getElementById("processoInternoStatus").value = row?.status || "solicitado";
  document.getElementById("processoInternoDataAbertura").value = row?.data_abertura || gestaoDataHoje();
  document.getElementById("processoInternoPrazo").value = row?.prazo || "";
  document.getElementById("processoInternoDescricao").value = row?.descricao || "";
  document.getElementById("processoInternoModalTitulo").textContent = row ? "Editar processo interno" : "Novo processo interno";
  document.getElementById("processoInternoExcluirBtn").classList.toggle("hidden", !row);
  document.getElementById("processoInternoStatusMensagem").textContent = "";
  document.getElementById("processoInternoModal").classList.remove("hidden");
  document.getElementById("processoInternoTitulo").focus();
}

function editarProcessoInterno(id){ const row = processosInternosState.rows.find((item) => Number(item.id) === Number(id)); if (row) abrirFormularioProcessoInterno(row); }
function fecharFormularioProcessoInterno(){ document.getElementById("processoInternoModal")?.classList.add("hidden"); }

function processoInternoPayload(){
  return { titulo:document.getElementById("processoInternoTitulo").value, tipo_id:document.getElementById("processoInternoTipo").value || null, solicitante:document.getElementById("processoInternoSolicitante").value, responsavel_id:document.getElementById("processoInternoResponsavel").value || null, prioridade:document.getElementById("processoInternoPrioridade").value, status:document.getElementById("processoInternoStatus").value, data_abertura:document.getElementById("processoInternoDataAbertura").value, prazo:document.getElementById("processoInternoPrazo").value || null, descricao:document.getElementById("processoInternoDescricao").value };
}

async function salvarProcessoInterno(){
  const id = Number(document.getElementById("processoInternoId").value || 0);
  const status = document.getElementById("processoInternoStatusMensagem"); status.textContent = "Salvando...";
  const resp = await apiFetch(id ? `/api/processos-internos/${id}` : "/api/processos-internos", {method:id ? "PUT" : "POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(processoInternoPayload())});
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) { status.textContent = data.erro || "Falha ao salvar processo."; return; }
  fecharFormularioProcessoInterno(); await carregarProcessosInternos();
}

async function moverProcessoInterno(id, status){
  if (!id || !gestaoProcessoStatusLabel[status]) return;
  const resp = await apiFetch(`/api/processos-internos/${id}`, {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify({status})});
  if (resp.ok) await carregarProcessosInternos();
}

async function excluirProcessoInterno(){
  const id = Number(document.getElementById("processoInternoId").value || 0); if (!id || !confirm("Excluir este processo? O histórico será preservado.")) return;
  const resp = await apiFetch(`/api/processos-internos/${id}`, {method:"DELETE"}); if (resp.ok) { fecharFormularioProcessoInterno(); await carregarProcessosInternos(); }
}

function setComprasGestaoView(view){
  const next = view === "previsao" ? "previsao" : "kanban";
  window.__comprasView = next;
  document.getElementById("comprasViewKanban")?.classList.toggle("hidden", next !== "kanban");
  document.getElementById("comprasViewPrevisao")?.classList.toggle("hidden", next !== "previsao");
  document.querySelectorAll("#submenuCompras .submenu-item").forEach((item) => item.classList.toggle("active", item.dataset.comprasView === next));
  if (next === "kanban") carregarComprasKanban().catch((erro) => console.warn("kanban compras erro:", erro));
  else carregarPrevisaoCompras().catch((erro) => console.warn("previsao compras erro:", erro));
}

async function carregarComprasKanban(){
  const resp = await apiFetch("/api/compras/solicitacoes"); const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.erro || "Falha ao carregar compras.");
  comprasGestaoState.rows = data.rows || []; comprasGestaoState.opcoes = data.opcoes || {};
  preencherOpcoesCompras(); renderComprasKanban();
}

function preencherOpcoesCompras(){
  const op = comprasGestaoState.opcoes || {};
  gestaoSetOptions("compraProduto", op.produtos || [], "Compra sem produto de estoque", "id", (row) => row.produto_base_nome || row.nome_produto);
  gestaoSetOptions("compraFornecedor", op.fornecedores || [], "Fornecedor ainda não definido", "id", gestaoFornecedorNome);
  gestaoSetOptions("compraResponsavel", op.colaboradores || [], "Sem responsável");
}

function fornecedorContatoCompraAtual(){
  const fornecedorId = Number(document.getElementById("compraFornecedor")?.value || 0);
  return (comprasGestaoState.opcoes?.fornecedores || []).find((row) => Number(row.id) === fornecedorId) || null;
}

function contatoCompraLink(id, value, prefix){
  const link = document.getElementById(id);
  if (!link) return;
  const texto = String(value || "").trim();
  link.textContent = texto || "Não informado";
  if (!texto) {
    link.removeAttribute("href");
    return;
  }
  const destino = prefix === "tel:" ? texto.replace(/[^+\d]/g, "") : texto.split(/[;,\s]+/).find((item) => item.includes("@")) || texto;
  link.href = `${prefix}${destino}`;
}

function renderContatoCompra(fornecedor){
  document.getElementById("compraContatoFornecedor").textContent = gestaoFornecedorNome(fornecedor);
  document.getElementById("compraContatoRepresentante").textContent = fornecedor.representante_nome || fornecedor.contato_compras || "Não informado";
  document.getElementById("compraContatoEndereco").textContent = fornecedor.endereco || "Não informado";
  contatoCompraLink("compraContatoTelefone", fornecedor.telefone, "tel:");
  contatoCompraLink("compraContatoEmail", fornecedor.emails, "mailto:");
}

function atualizarContatoCompra(){
  const fornecedor = fornecedorContatoCompraAtual();
  const botao = document.getElementById("compraContatoBtn");
  if (botao) botao.disabled = !fornecedor;
  const painel = document.getElementById("compraContatoPainel");
  if (!fornecedor) {
    painel?.classList.add("hidden");
  } else if (painel && !painel.classList.contains("hidden")) {
    renderContatoCompra(fornecedor);
  }
}

function abrirContatoCompra(){
  const fornecedor = fornecedorContatoCompraAtual();
  if (!fornecedor) return;
  renderContatoCompra(fornecedor);
  document.getElementById("compraContatoPainel")?.classList.remove("hidden");
}

function fecharContatoCompra(){ document.getElementById("compraContatoPainel")?.classList.add("hidden"); }

function renderComprasKanban(){
  const busca = String(document.getElementById("comprasKanbanBusca")?.value || "").trim().toLowerCase();
  const rows = comprasGestaoState.rows.filter((row) => !busca || [row.titulo,row.produto_nome,row.fornecedor_nome,row.justificativa].join(" ").toLowerCase().includes(busca));
  const ids = { solicitado:"Solicitado", cotacao:"Cotacao", aprovacao:"Aprovacao", pedido:"Pedido", aguardando:"Aguardando", recebido:"Recebido" };
  Object.entries(ids).forEach(([status, suffix]) => {
    const itens = rows.filter((row) => row.status === status); const count = document.getElementById(`comprasCount${suffix}`); if (count) count.textContent = itens.length;
    const col = document.getElementById(`comprasCol${suffix}`); if (col) col.innerHTML = itens.map(compraCardHtml).join("") || '<div class="gestao-kanban-empty">Nenhuma compra</div>';
  });
  document.querySelectorAll("[data-compra-status]").forEach((col) => { col.ondragover = (ev) => ev.preventDefault(); col.ondrop = (ev) => { ev.preventDefault(); moverCompra(Number(ev.dataTransfer.getData("text/compra-id")), col.dataset.compraStatus); }; });
  const resumo = document.getElementById("comprasKanbanResumo"); if (resumo) resumo.textContent = `${rows.length} compra(s) • ${rows.filter((row) => row.atrasado).length} atrasada(s) • ${gestaoMoeda(rows.reduce((sum,row) => sum + Number(row.valor_total_previsto || 0), 0))} previsto`;
}

function compraCardHtml(row){
  return `<article class="gestao-kanban-card prioridade-${gestaoEsc(row.prioridade)} ${row.atrasado ? "is-overdue" : ""}" draggable="true" ondragstart="event.dataTransfer.setData('text/compra-id','${Number(row.id)}')" onclick="editarCompra(${Number(row.id)})"><div class="gestao-card-head"><span>${gestaoEsc(row.fornecedor_nome || "Sem fornecedor")}</span><strong>${gestaoEsc(row.prioridade || "normal")}</strong></div><h4>${gestaoEsc(row.titulo)}</h4><p>${gestaoEsc(row.produto_nome || "Compra geral")}</p><div class="gestao-card-meta"><span>${gestaoNumero(row.quantidade)} ${gestaoEsc(row.unidade || "UN")}</span><span>${gestaoMoeda(row.valor_total_previsto)}</span></div><div class="gestao-card-meta"><span>${gestaoEsc(row.responsavel_nome || "Sem responsável")}</span><span>${row.data_necessidade ? `Necessidade ${gestaoEsc(row.data_necessidade)}` : "Sem data"}</span></div></article>`;
}

function abrirFormularioCompra(row = null){
  preencherOpcoesCompras(); document.getElementById("compraId").value = row?.id || ""; document.getElementById("compraOrigem").value = row?.origem || "manual";
  document.getElementById("compraTitulo").value = row?.titulo || ""; document.getElementById("compraProduto").value = row?.produto_id || ""; document.getElementById("compraFornecedor").value = row?.fornecedor_id || ""; document.getElementById("compraQuantidade").value = row?.quantidade || ""; document.getElementById("compraUnidade").value = row?.unidade || "UN"; document.getElementById("compraValorUnitario").value = row?.valor_unitario_previsto || ""; document.getElementById("compraPrioridade").value = row?.prioridade || "normal"; document.getElementById("compraStatus").value = row?.status || "solicitado"; document.getElementById("compraSolicitante").value = row?.solicitante || usuarioLogado?.nome || ""; document.getElementById("compraResponsavel").value = row?.responsavel_id || ""; document.getElementById("compraDataNecessidade").value = row?.data_necessidade || ""; document.getElementById("compraDataPrevisaoEntrega").value = row?.data_previsao_entrega || ""; document.getElementById("compraJustificativa").value = row?.justificativa || "";
  fecharContatoCompra(); atualizarContatoCompra(); document.getElementById("compraModalTitulo").textContent = row ? "Editar compra" : "Nova compra"; document.getElementById("compraExcluirBtn").classList.toggle("hidden", !row); document.getElementById("compraStatusMensagem").textContent = ""; document.getElementById("compraModal").classList.remove("hidden"); document.getElementById("compraTitulo").focus();
}

function editarCompra(id){ const row = comprasGestaoState.rows.find((item) => Number(item.id) === Number(id)); if (row) abrirFormularioCompra(row); }
function fecharFormularioCompra(){ fecharContatoCompra(); document.getElementById("compraModal")?.classList.add("hidden"); }
function compraPayload(){ return {titulo:document.getElementById("compraTitulo").value,produto_id:document.getElementById("compraProduto").value || null,fornecedor_id:document.getElementById("compraFornecedor").value || null,quantidade:document.getElementById("compraQuantidade").value,unidade:document.getElementById("compraUnidade").value,valor_unitario_previsto:document.getElementById("compraValorUnitario").value,prioridade:document.getElementById("compraPrioridade").value,status:document.getElementById("compraStatus").value,solicitante:document.getElementById("compraSolicitante").value,responsavel_id:document.getElementById("compraResponsavel").value || null,data_necessidade:document.getElementById("compraDataNecessidade").value || null,data_previsao_entrega:document.getElementById("compraDataPrevisaoEntrega").value || null,justificativa:document.getElementById("compraJustificativa").value,origem:document.getElementById("compraOrigem").value || "manual"}; }

async function salvarCompra(){ const id=Number(document.getElementById("compraId").value||0); const status=document.getElementById("compraStatusMensagem"); status.textContent="Salvando..."; const resp=await apiFetch(id?`/api/compras/solicitacoes/${id}`:"/api/compras/solicitacoes",{method:id?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(compraPayload())}); const data=await resp.json().catch(()=>({})); if(!resp.ok){status.textContent=data.erro||"Falha ao salvar compra.";return;} fecharFormularioCompra(); await carregarComprasKanban(); }
async function moverCompra(id,status){ if(!id||!gestaoCompraStatusLabel[status])return; const resp=await apiFetch(`/api/compras/solicitacoes/${id}`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({status})}); if(resp.ok)await carregarComprasKanban(); }
async function excluirCompra(){ const id=Number(document.getElementById("compraId").value||0); if(!id||!confirm("Excluir esta compra? O histórico será preservado."))return; const resp=await apiFetch(`/api/compras/solicitacoes/${id}`,{method:"DELETE"}); if(resp.ok){fecharFormularioCompra();await carregarComprasKanban();} }

async function carregarPrevisaoCompras(){
  const resp=await apiFetch("/api/compras/previsao"); const data=await resp.json().catch(()=>({})); if(!resp.ok)throw new Error(data.erro||"Falha ao carregar previsão de compras.");
  comprasGestaoState.previsao=data.rows||[]; comprasGestaoState.previsaoOpcoes=data.opcoes||{}; comprasGestaoState.fornecedores=data.opcoes?.fornecedores||[];
  gestaoSetOptions("comprasPrevisaoGrupo",data.opcoes?.grupos||[],"Todos os grupos","codigo"); gestaoSetOptions("comprasPrevisaoProduto",data.opcoes?.produtos||[],"Todos os produtos","id",(row)=>row.nome); renderPrevisaoCompras();
}

function filtrarPrevisaoCompras(){ const grupo=document.getElementById("comprasPrevisaoGrupo")?.value||""; const produtos=(comprasGestaoState.previsaoOpcoes.produtos||[]).filter((row)=>!grupo||row.grupo_estoque===grupo); gestaoSetOptions("comprasPrevisaoProduto",produtos,"Todos os produtos","id",(row)=>row.nome); renderPrevisaoCompras(); }

function renderPrevisaoCompras(){
  const grupo=document.getElementById("comprasPrevisaoGrupo")?.value||""; const produto=Number(document.getElementById("comprasPrevisaoProduto")?.value||0); const somente=document.getElementById("comprasPrevisaoNecessidade")?.value==="com_sugestao";
  const rows=comprasGestaoState.previsao.filter((row)=>(!grupo||row.grupo_estoque===grupo)&&(!produto||Number(row.produto_id)===produto)&&(!somente||Number(row.sugestao_compra)>0));
  const body=document.getElementById("comprasPrevisaoBody"); if(body)body.innerHTML=rows.map((row)=>`<tr class="${Number(row.sugestao_compra)>0?'gestao-row-alert':''}"><td>${gestaoEsc(row.grupo_nome)}</td><td>${gestaoEsc(row.nome_produto)}</td><td>${gestaoEsc(row.fornecedor_nome||"Não definido")}</td><td>${gestaoNumero(row.quantidade_atual)}</td><td>${gestaoNumero(row.consumo_semana_atual)}</td><td>${gestaoNumero(row.consumo_mes_ano_anterior)}</td><td>${gestaoNumero(row.media_consumo_meses_recentes)}</td><td>${gestaoNumero(row.previsao_consumo_semana)}</td><td>${gestaoNumero(row.compras_abertas)}</td><td>${Number(row.prazo_entrega_dias)} dias</td><td>${gestaoNumero(row.estoque_seguranca)}</td><td><strong>${gestaoNumero(row.sugestao_compra)}</strong></td><td><button type="button" ${Number(row.sugestao_compra)<=0?'disabled':''} onclick="criarCompraDaPrevisao(${Number(row.produto_id)})">Criar compra</button></td></tr>`).join("")||'<tr><td colspan="13">Nenhum item para os filtros.</td></tr>';
  const resumo=document.getElementById("comprasPrevisaoResumo"); if(resumo)resumo.textContent=`${rows.length} item(ns) • ${rows.filter((row)=>Number(row.sugestao_compra)>0).length} com necessidade • sugestão total ${gestaoNumero(rows.reduce((sum,row)=>sum+Number(row.sugestao_compra||0),0))} unidades`;
}

async function criarCompraDaPrevisao(produtoId){
  let row=comprasGestaoState.previsao.find((item)=>Number(item.produto_id)===Number(produtoId)); if(!row)return;
  if(!comprasGestaoState.opcoes?.produtos?.length)await carregarComprasKanban();
  abrirFormularioCompra({produto_id:row.produto_id,fornecedor_id:row.fornecedor_id,quantidade:row.sugestao_compra,unidade:row.unidade||"UN",titulo:`Compra prevista - ${row.nome_produto}`,prioridade:"alta",status:"solicitado",origem:"previsao_estoque",justificativa:`Sugestão automática: consumo ${gestaoNumero(row.previsao_consumo_semana)}/semana, saldo ${gestaoNumero(row.quantidade_atual)}, compras abertas ${gestaoNumero(row.compras_abertas)} e prazo ${row.prazo_entrega_dias} dias.`});
}

async function carregarDashboardProcessos(){ const resp=await apiFetch("/api/dashboard_processos"); const data=await resp.json().catch(()=>({})); if(!resp.ok)return; const meta=data.meta||{}; gestaoResumoCards("dashProcessosCards",[{label:"Processos ativos",value:meta.total||0},{label:"Atrasados",value:meta.atrasados||0},{label:"Em execução",value:meta.por_status?.execucao||0},{label:"Aguardando",value:meta.por_status?.aguardando||0},{label:"Concluídos",value:meta.por_status?.concluido||0}]); const rows=(data.rows||[]).filter((row)=>row.atrasado||["urgente","alta"].includes(row.prioridade)).slice(0,20); document.getElementById("dashProcessosBody").innerHTML=rows.map((row)=>`<tr class="${row.atrasado?'gestao-row-alert':''}"><td>${gestaoEsc(row.titulo)}</td><td>${gestaoEsc(row.tipo_nome||"Geral")}</td><td>${gestaoEsc(gestaoProcessoStatusLabel[row.status]||row.status)}</td><td>${gestaoEsc(row.prioridade)}</td><td>${gestaoEsc(row.responsavel_nome||"-")}</td><td>${gestaoEsc(row.prazo||"-")}</td></tr>`).join("")||'<tr><td colspan="6">Nenhum processo prioritário.</td></tr>'; document.getElementById("dashProcessosInfo").textContent=`Atualizado em ${meta.atualizado_em||"agora"}`; }

async function carregarDashboardCompras(){ const resp=await apiFetch("/api/dashboard_compras"); const data=await resp.json().catch(()=>({})); if(!resp.ok)return; const meta=data.compras?.meta||{}; const pmeta=data.previsao?.meta||{}; gestaoResumoCards("dashComprasCards",[{label:"Compras abertas",value:(meta.total||0)-(meta.por_status?.recebido||0)-(meta.por_status?.cancelado||0)},{label:"Atrasadas",value:meta.atrasadas||0},{label:"Aguardando entrega",value:meta.por_status?.aguardando||0},{label:"Valor previsto",value:gestaoMoeda(meta.valor_total_previsto)},{label:"Itens a comprar",value:pmeta.itens_com_sugestao||0}]); const rows=(data.previsao?.rows||[]).filter((row)=>Number(row.sugestao_compra)>0).slice(0,20); document.getElementById("dashComprasPrevisaoBody").innerHTML=rows.map((row)=>`<tr><td>${gestaoEsc(row.grupo_nome)}</td><td>${gestaoEsc(row.nome_produto)}</td><td>${gestaoNumero(row.quantidade_atual)}</td><td>${gestaoNumero(row.previsao_consumo_semana)}</td><td>${gestaoNumero(row.compras_abertas)}</td><td><strong>${gestaoNumero(row.sugestao_compra)}</strong></td></tr>`).join("")||'<tr><td colspan="6">Nenhuma necessidade de compra calculada.</td></tr>'; document.getElementById("dashComprasInfo").textContent=`Atualizado em ${meta.atualizado_em||"agora"}`; }

function gestaoProcessosRelatorioParams(){ const p=new URLSearchParams(); [["data_inicio","relatorioProcessosDataInicio"],["data_fim","relatorioProcessosDataFim"],["status","relatorioProcessosStatus"],["tipo_id","relatorioProcessosTipo"],["responsavel_id","relatorioProcessosResponsavel"],["busca","relatorioProcessosBusca"]].forEach(([key,id])=>{const v=document.getElementById(id)?.value;if(v)p.set(key,v);}); return p; }
async function carregarRelatorioProcessos(){ const resp=await apiFetch(`/api/processos-internos/relatorio?${gestaoProcessosRelatorioParams()}`); const data=await resp.json().catch(()=>({})); if(!resp.ok)return; gestaoSetOptions("relatorioProcessosTipo",data.opcoes?.tipos||[],"Todos os tipos"); gestaoSetOptions("relatorioProcessosResponsavel",data.opcoes?.colaboradores||[],"Todos"); document.getElementById("relatorioProcessosBody").innerHTML=(data.rows||[]).map((row)=>`<tr class="${row.atrasado?'gestao-row-alert':''}"><td>${row.id}</td><td>${gestaoEsc(row.titulo)}</td><td>${gestaoEsc(row.tipo_nome||"Geral")}</td><td>${gestaoEsc(gestaoProcessoStatusLabel[row.status]||row.status)}</td><td>${gestaoEsc(row.prioridade)}</td><td>${gestaoEsc(row.responsavel_nome||"-")}</td><td>${gestaoEsc(row.prazo||"-")}</td></tr>`).join("")||'<tr><td colspan="7">Nenhum processo.</td></tr>'; document.getElementById("relatorioProcessosResumo").textContent=`${data.meta?.total||0} processo(s) • ${data.meta?.atrasados||0} atrasado(s)`; }
function abrirPdfRelatorioProcessos(){ window.open(`/api/processos-internos/relatorio/pdf?${gestaoProcessosRelatorioParams()}`,"_blank","noopener"); }

function gestaoComprasRelatorioParams(){ const p=new URLSearchParams(); [["data_inicio","relatorioComprasDataInicio"],["data_fim","relatorioComprasDataFim"],["status","relatorioComprasStatus"],["fornecedor_id","relatorioComprasFornecedor"],["produto_id","relatorioComprasProduto"],["busca","relatorioComprasBusca"]].forEach(([key,id])=>{const v=document.getElementById(id)?.value;if(v)p.set(key,v);}); return p; }
async function carregarRelatorioCompras(){ const resp=await apiFetch(`/api/compras/relatorio?${gestaoComprasRelatorioParams()}`); const data=await resp.json().catch(()=>({})); if(!resp.ok)return; gestaoSetOptions("relatorioComprasFornecedor",data.opcoes?.fornecedores||[],"Todos","id",gestaoFornecedorNome); gestaoSetOptions("relatorioComprasProduto",data.opcoes?.produtos||[],"Todos","id",(row)=>row.produto_base_nome||row.nome_produto); document.getElementById("relatorioComprasBody").innerHTML=(data.rows||[]).map((row)=>`<tr class="${row.atrasado?'gestao-row-alert':''}"><td>${row.id}</td><td>${gestaoEsc(row.titulo)}</td><td>${gestaoEsc(row.produto_nome||"-")}</td><td>${gestaoEsc(row.fornecedor_nome||"-")}</td><td>${gestaoEsc(gestaoCompraStatusLabel[row.status]||row.status)}</td><td>${gestaoNumero(row.quantidade)} ${gestaoEsc(row.unidade||"UN")}</td><td>${gestaoMoeda(row.valor_total_previsto)}</td><td>${gestaoEsc(row.data_necessidade||"-")}</td></tr>`).join("")||'<tr><td colspan="8">Nenhuma compra.</td></tr>'; document.getElementById("relatorioComprasResumo").textContent=`${data.meta?.total||0} compra(s) • ${data.meta?.atrasadas||0} atrasada(s) • ${gestaoMoeda(data.meta?.valor_total_previsto)}`; }
function abrirPdfRelatorioCompras(){ window.open(`/api/compras/relatorio/pdf?${gestaoComprasRelatorioParams()}`,"_blank","noopener"); }

async function carregarTiposProcessos(){ const resp=await apiFetch("/api/processos-internos/tipos"); const rows=await resp.json().catch(()=>[]); processosInternosState.opcoes.tipos=rows||[]; document.getElementById("processosTiposBody").innerHTML=(rows||[]).map((row)=>`<tr><td><span class="gestao-color-dot" style="background:${gestaoEsc(row.cor||'#2563eb')}"></span></td><td>${gestaoEsc(row.nome)}</td><td>${gestaoEsc(row.descricao||"-")}</td><td>${Number(row.sla_dias||0)} dias</td><td><button type="button" onclick="editarTipoProcesso(${Number(row.id)})">Editar</button><button type="button" class="btn-danger" onclick="excluirTipoProcesso(${Number(row.id)})">Excluir</button></td></tr>`).join(""); }
function novoTipoProcesso(){ document.getElementById("processoTipoId").value="";document.getElementById("processoTipoNome").value="";document.getElementById("processoTipoDescricao").value="";document.getElementById("processoTipoSla").value="7";document.getElementById("processoTipoCor").value="#2563eb";document.getElementById("processoTipoFormulario").classList.remove("hidden"); }
function editarTipoProcesso(id){ const row=processosInternosState.opcoes.tipos.find((item)=>Number(item.id)===Number(id));if(!row)return;novoTipoProcesso();document.getElementById("processoTipoId").value=row.id;document.getElementById("processoTipoNome").value=row.nome||"";document.getElementById("processoTipoDescricao").value=row.descricao||"";document.getElementById("processoTipoSla").value=row.sla_dias||0;document.getElementById("processoTipoCor").value=row.cor||"#2563eb"; }
function fecharTipoProcesso(){ document.getElementById("processoTipoFormulario")?.classList.add("hidden"); }
async function salvarTipoProcesso(){ const id=Number(document.getElementById("processoTipoId").value||0);const payload={nome:document.getElementById("processoTipoNome").value,descricao:document.getElementById("processoTipoDescricao").value,sla_dias:document.getElementById("processoTipoSla").value,cor:document.getElementById("processoTipoCor").value};const resp=await apiFetch(id?`/api/processos-internos/tipos/${id}`:"/api/processos-internos/tipos",{method:id?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const data=await resp.json().catch(()=>({}));document.getElementById("processoTipoStatus").textContent=resp.ok?"Tipo salvo.":data.erro||"Falha ao salvar.";if(resp.ok){fecharTipoProcesso();await carregarTiposProcessos();} }
async function excluirTipoProcesso(id){if(!confirm("Excluir este tipo? Processos existentes manterão o histórico."))return;const resp=await apiFetch(`/api/processos-internos/tipos/${id}`,{method:"DELETE"});if(resp.ok)await carregarTiposProcessos();}

async function carregarCadastrosCompras(){ const [fornResp,prevResp]=await Promise.all([apiFetch("/api/compras/fornecedores"),apiFetch("/api/compras/previsao")]); comprasGestaoState.fornecedores=await fornResp.json().catch(()=>[]); const prev=await prevResp.json().catch(()=>({})); comprasGestaoState.previsao=prev.rows||[]; comprasGestaoState.previsaoOpcoes=prev.opcoes||{}; renderFornecedoresCompras();renderParametrosProdutosCompras(); }
function renderFornecedoresCompras(){ document.getElementById("comprasFornecedoresBody").innerHTML=(comprasGestaoState.fornecedores||[]).map((row)=>`<tr><td>${gestaoEsc(gestaoFornecedorNome(row))}</td><td>${gestaoEsc(row.cnpj||"-")}</td><td>${gestaoEsc(row.categoria||"outros")}</td><td>${gestaoEsc(row.representante_nome||row.contato_compras||row.telefone||row.emails||"-")}</td><td>${Number(row.prazo_entrega_dias||7)} dias</td><td>${gestaoEsc(row.condicao_pagamento||"-")}</td><td><button type="button" onclick="editarFornecedorCompras(${Number(row.id)})">Editar</button><button type="button" class="btn-danger" onclick="excluirFornecedorCompras(${Number(row.id)})">Excluir</button></td></tr>`).join("")||'<tr><td colspan="7">Nenhum fornecedor.</td></tr>'; }
function novoFornecedorCompras(){["Id","Nome","Cnpj","Emails","Contato","Representante","Telefone","Endereco","PedidoMinimo","Pagamento","Observacoes"].forEach((s)=>{const el=document.getElementById(`comprasFornecedor${s}`);if(el)el.value="";});document.getElementById("comprasFornecedorCategoria").value="outros";document.getElementById("comprasFornecedorPrazo").value="7";document.getElementById("comprasFornecedorFormulario").classList.remove("hidden");}
function editarFornecedorCompras(id){const row=comprasGestaoState.fornecedores.find((item)=>Number(item.id)===Number(id));if(!row)return;novoFornecedorCompras();document.getElementById("comprasFornecedorId").value=row.id;document.getElementById("comprasFornecedorNome").value=row.nome||"";document.getElementById("comprasFornecedorCnpj").value=row.cnpj||"";document.getElementById("comprasFornecedorCategoria").value=row.categoria||"outros";document.getElementById("comprasFornecedorEmails").value=row.emails||"";document.getElementById("comprasFornecedorContato").value=row.contato_compras||"";document.getElementById("comprasFornecedorRepresentante").value=row.representante_nome||"";document.getElementById("comprasFornecedorTelefone").value=row.telefone||"";document.getElementById("comprasFornecedorEndereco").value=row.endereco||"";document.getElementById("comprasFornecedorPrazo").value=row.prazo_entrega_dias||7;document.getElementById("comprasFornecedorPedidoMinimo").value=row.pedido_minimo_valor||"";document.getElementById("comprasFornecedorPagamento").value=row.condicao_pagamento||"";document.getElementById("comprasFornecedorObservacoes").value=row.observacoes||"";}
function fecharFornecedorCompras(){document.getElementById("comprasFornecedorFormulario")?.classList.add("hidden");}
function fornecedorComprasPayload(){return{nome:document.getElementById("comprasFornecedorNome").value,cnpj:document.getElementById("comprasFornecedorCnpj").value,categoria:document.getElementById("comprasFornecedorCategoria").value,emails:document.getElementById("comprasFornecedorEmails").value,contato_compras:document.getElementById("comprasFornecedorContato").value,representante_nome:document.getElementById("comprasFornecedorRepresentante").value,telefone:document.getElementById("comprasFornecedorTelefone").value,endereco:document.getElementById("comprasFornecedorEndereco").value,prazo_entrega_dias:document.getElementById("comprasFornecedorPrazo").value,pedido_minimo_valor:document.getElementById("comprasFornecedorPedidoMinimo").value,condicao_pagamento:document.getElementById("comprasFornecedorPagamento").value,observacoes:document.getElementById("comprasFornecedorObservacoes").value};}
async function salvarFornecedorCompras(){const id=Number(document.getElementById("comprasFornecedorId").value||0);const resp=await apiFetch(id?`/api/compras/fornecedores/${id}`:"/api/compras/fornecedores",{method:id?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(fornecedorComprasPayload())});const data=await resp.json().catch(()=>({}));document.getElementById("comprasFornecedorStatus").textContent=resp.ok?"Fornecedor salvo.":data.erro||"Falha ao salvar.";if(resp.ok){fecharFornecedorCompras();await carregarCadastrosCompras();}}
async function excluirFornecedorCompras(id){if(!confirm("Desativar este fornecedor?"))return;const resp=await apiFetch(`/api/compras/fornecedores/${id}`,{method:"DELETE"});if(resp.ok)await carregarCadastrosCompras();}
function renderParametrosProdutosCompras(){const fornecedores=comprasGestaoState.fornecedores||[];document.getElementById("comprasParametrosProdutosBody").innerHTML=(comprasGestaoState.previsao||[]).map((row)=>`<tr><td>${gestaoEsc(row.grupo_nome)}</td><td>${gestaoEsc(row.nome_produto)}</td><td><select id="paramCompraFornecedor${row.produto_id}"><option value="">Não definido</option>${fornecedores.map((f)=>`<option value="${f.id}" ${Number(f.id)===Number(row.fornecedor_id)?'selected':''}>${gestaoEsc(gestaoFornecedorNome(f))}</option>`).join("")}</select></td><td><input type="number" min="0" step="0.001" id="paramCompraSeguranca${row.produto_id}" value="${Number(row.estoque_seguranca||0)}"></td><td><input type="number" min="1" id="paramCompraPrazo${row.produto_id}" value="${Number(row.prazo_entrega_dias||7)}"></td><td><input type="number" min="0" step="0.001" id="paramCompraLote${row.produto_id}" value="${Number(row.lote_minimo||0)}"></td><td><input type="number" min="0.001" step="0.001" id="paramCompraMultiplo${row.produto_id}" value="${Number(row.multiplo_compra||1)}"></td><td><button type="button" onclick="salvarParametrosProdutoCompra(${Number(row.produto_id)})">Salvar</button></td></tr>`).join("")||'<tr><td colspan="8">Nenhum insumo ou item de almoxarifado cadastrado.</td></tr>';}
async function salvarParametrosProdutoCompra(id){const payload={fornecedor_id:document.getElementById(`paramCompraFornecedor${id}`).value||null,estoque_seguranca:document.getElementById(`paramCompraSeguranca${id}`).value,prazo_entrega_dias:document.getElementById(`paramCompraPrazo${id}`).value,lote_minimo:document.getElementById(`paramCompraLote${id}`).value,multiplo_compra:document.getElementById(`paramCompraMultiplo${id}`).value};const resp=await apiFetch(`/api/compras/produtos/${id}/config`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});if(resp.ok)await carregarCadastrosCompras();}
