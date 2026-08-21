/* =========================
   Gestão Financeira integrada ao NanotechSoft
   - MySQL via /apps/financeiro/api/state
   - Importação OFX
   - Conciliação: Banco↔Lançamento e Banco↔Título (AP/AR)
   - Contas a pagar/receber com etiquetas e anexos
========================= */

const FINANCE_STATE_API = "/apps/financeiro/api/state";
const FINANCEIRO_ALLOWED = Array.isArray(window.FINANCEIRO_ALLOWED) ? window.FINANCEIRO_ALLOWED : ["*"];

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

/* ---------- Estado ---------- */
let state = loadState();
let financeStateNeedsPersist = false;
let financeAiDiagState = {
  loading: false,
  loaded: false,
  error: "",
  data: null,
  lastLoadedAt: 0
};
let financeSaveQueue = Promise.resolve();
let financePersistBusy = false;
let financePersistBusyCount = 0;
let financeStateRevision = "";
let financeSyncInFlight = false;
let financeSyncPending = false;
let financeSyncTimer = null;
const FINANCE_SYNC_INTERVAL_MS = 3000;
const financeSyncChannel = typeof BroadcastChannel === "function"
  ? new BroadcastChannel("nanotechsoft-financeiro-state")
  : null;

function setFinancePersistBusy(delta){
  financePersistBusyCount = Math.max(0, financePersistBusyCount + delta);
  financePersistBusy = financePersistBusyCount > 0;
}

function announceFinanceStateChange(){
  financeSyncChannel?.postMessage({ revision: financeStateRevision });
  try{
    localStorage.setItem("nanotechsoft-financeiro-sync", `${Date.now()}:${financeStateRevision}`);
  }catch{
    // BroadcastChannel e a consulta periodica continuam ativos.
  }
}

document.addEventListener("click", (event)=>{
  if(!financePersistBusy) return;
  const interactive = event.target.closest?.("button,a,input,select,textarea,label");
  if(!interactive) return;
  event.preventDefault();
  event.stopImmediatePropagation();
}, true);

/* ---------- Util ---------- */
function uid(prefix="id"){
  return prefix + "_" + Math.random().toString(16).slice(2) + "_" + Date.now().toString(16);
}
function brl(n){
  const v = Number(n || 0);
  return v.toLocaleString("pt-BR",{style:"currency",currency:"BRL"});
}
function toISODate(d){
  const dt = new Date(d);
  const y = dt.getFullYear();
  const m = String(dt.getMonth()+1).padStart(2,"0");
  const da = String(dt.getDate()).padStart(2,"0");
  return `${y}-${m}-${da}`;
}
function formatDateTime(value){
  if(!value) return "-";
  const dt = new Date(value);
  if(Number.isNaN(dt.getTime())) return String(value);
  return dt.toLocaleString("pt-BR");
}
function parseISODate(s){
  const [y,m,d] = s.split("-").map(Number);
  return new Date(y, m-1, d);
}
function clamp(v,min,max){ return Math.max(min, Math.min(max, v)); }
function addMonthsISO(baseISO, months){
  const base = parseISODate(baseISO);
  const day = base.getDate();
  const target = new Date(base.getFullYear(), base.getMonth() + months + 1, 0);
  const finalDay = Math.min(day, target.getDate());
  return toISODate(new Date(target.getFullYear(), target.getMonth(), finalDay));
}
function splitAmount(totalValue, parts){
  const totalCents = Math.round(Number(totalValue || 0) * 100);
  const qtd = clamp(Number(parts || 1), 1, 999);
  const base = Math.floor(totalCents / qtd);
  let remainder = totalCents - (base * qtd);
  return Array.from({ length: qtd }, () => {
    const cents = base + (remainder > 0 ? 1 : 0);
    remainder = Math.max(0, remainder - 1);
    return cents / 100;
  });
}
function filePreviewSrc(anexo){
  const src = anexo?.dataUrl || anexo?.url || "";
  if(!src || !Number.isInteger(Number(anexo?.page))) return src;
  return `${src.split("#")[0]}#page=${Number(anexo.page)}`;
}
function attachmentCodeDetails(anexo){
  const rows = [];
  if(anexo?.page) rows.push(`Página ${Number(anexo.page)}${anexo.pageCount ? ` de ${Number(anexo.pageCount)}` : ""}`);
  if(anexo?.barcode) rows.push(`Linha digitável/código: ${escapeHtml(anexo.barcode)}`);
  if(anexo?.pix) rows.push(`PIX copia e cola: ${escapeHtml(anexo.pix)}`);
  return rows.length ? `<div class="attachmentCodes">${rows.map(row => `<div>${row}</div>`).join("")}</div>` : "";
}
async function requestJson(url, options={}){
  const response = await fetch(url, {
    cache: "no-store",
    headers: { Accept: "application/json", ...(options.headers || {}) },
    ...options
  });

  let payload = null;
  if(response.status !== 204){
    const text = await response.text();
    if(text){
      try{
        payload = JSON.parse(text);
      }catch{
        payload = { error: text };
      }
    }
  }

  if(!response.ok){
    const error = new Error(payload?.error || `Falha na requisição (${response.status}).`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}
function getContaNome(contaId){
  return state.contas.find(c => c.id === contaId)?.nome || "";
}
async function uploadTituloAttachment(file, titulo){
  return uploadFinanceAttachment(file, {
    data: titulo.vencimento || "",
    contaId: titulo.contaId,
    pessoa: titulo.pessoa || "",
    descricao: tituloDescricaoText(titulo)
  });
}
async function uploadFinanceAttachment(file, metadata={}){
  const formData = new FormData();
  formData.set("file", file);
  formData.set("attachmentId", uid("anx"));
  formData.set("vencimento", metadata.data || "");
  formData.set("contaNome", getContaNome(metadata.contaId));
  formData.set("pessoa", metadata.pessoa || "");
  formData.set("descricao", metadata.descricao || "");

  const payload = await requestJson("/api/finance/attachments", {
    method: "POST",
    body: formData
  });
  return payload?.attachment || null;
}
async function removeTituloAttachmentFile(anexo){
  if(!anexo?.path) return;
  const isReferenced = [
    ...(state.lancamentos || []).flatMap(item => item.anexos || []),
    ...(state.titulos || []).flatMap(item => item.anexos || [])
  ].some(item => item !== anexo && item.path === anexo.path);
  if(isReferenced) return;
  await fetch(`/api/finance/attachments?path=${encodeURIComponent(anexo.path)}`, {
    method: "DELETE",
    cache: "no-store"
  });
}
async function triggerFinanceReminders({silent=false}={}){
  const status = $("#statusAvisos");
  try{
    const payload = await requestJson("/api/finance/reminders/run", { method: "POST" });
    if(status) status.textContent = payload?.message || "Avisos processados.";
    if(!silent && payload?.message) alert(payload.message);
  }catch(err){
    if(status) status.textContent = err?.message || "Nao foi possivel processar os avisos.";
    if(!silent) alert(err?.message || "Nao foi possivel processar os avisos.");
  }
}

function saveState(){
  const serializedState = JSON.stringify({ state, revision: financeStateRevision });
  financeSaveQueue = financeSaveQueue
    .catch(() => {})
    .then(() => persistServerState(serializedState));
  return financeSaveQueue;
}
function cloneStateSnapshot(){
  return JSON.parse(JSON.stringify(state));
}
async function persistStateOrRollback(snapshot, { button=null, savingText="Salvando..." }={}){
  const previousDisabled = button ? button.disabled : null;
  const previousText = button ? button.textContent : "";
  setFinancePersistBusy(1);
  if(button){
    button.disabled = true;
    button.textContent = savingText;
  }

  try{
    await saveState();
    return true;
  }catch(err){
    if(snapshot) state = migrate(snapshot);
    renderAll();
    if(err?.status === 409){
      // Forca a proxima leitura completa; a revisao atual do servidor nao
      // significa que esta aba ja possui o respectivo estado.
      financeStateRevision = "";
      financeSyncPending = true;
      alert("Os dados foram atualizados em outra aba durante esta operação. A versão mais recente será carregada; repita a alteração.");
    }else{
      alert(`Não foi possível salvar no banco. A alteração não foi confirmada.\n${err?.message || ""}`.trim());
    }
    return false;
  }finally{
    setFinancePersistBusy(-1);
    if(button){
      button.disabled = previousDisabled;
      button.textContent = previousText;
    }
    if(financeSyncPending) queueMicrotask(() => syncFinanceStateFromServer());
  }
}
function loadState(){
  return seed();
}
function replaceState(nextState){
  state = migrate(nextState);
}
async function loadServerState(){
  const payload = await requestJson(FINANCE_STATE_API);
  financeStateRevision = payload?.revision || "";
  replaceState(payload?.state || seed());
  if(financeStateNeedsPersist){
    financeStateNeedsPersist = false;
    try{
      await persistServerState();
    }catch(err){
      console.warn("Nao foi possivel persistir a normalizacao financeira automaticamente.", err);
    }
  }
}
async function persistServerState(serializedState=null){
  const payload = await requestJson(FINANCE_STATE_API, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: serializedState || JSON.stringify({ state, revision: financeStateRevision })
  });
  financeStateRevision = payload?.revision || financeStateRevision;
  announceFinanceStateChange();
  return payload;
}

function financeEditorIsOpen(){
  if(financePersistBusy) return true;
  if($(".modal:not(.hidden)")) return true;
  const active = document.activeElement;
  return !!active?.matches?.("input, select, textarea");
}

async function syncFinanceStateFromServer({ force=false }={}){
  if(financeSyncInFlight) return;
  if((document.hidden && !force) || financeEditorIsOpen()){
    financeSyncPending = true;
    return;
  }

  financeSyncInFlight = true;
  financeSyncPending = false;
  const requestedRevision = financeStateRevision;
  try{
    const query = requestedRevision
      ? `?revision=${encodeURIComponent(requestedRevision)}`
      : "";
    const payload = await requestJson(`${FINANCE_STATE_API}${query}`);
    // Uma resposta iniciada antes de uma gravacao local nunca pode repor a
    // copia antiga sobre a baixa que acabou de ser confirmada.
    if(financePersistBusy || financeStateRevision !== requestedRevision){
      financeSyncPending = true;
      return;
    }
    if(payload?.revision) financeStateRevision = payload.revision;
    if(payload?.changed !== false && payload?.state){
      replaceState(payload.state);
      renderAll();
    }
  }catch(err){
    console.warn("Nao foi possivel sincronizar o dashboard financeiro.", err);
  }finally{
    financeSyncInFlight = false;
    if(financeSyncPending && !document.hidden && !financeEditorIsOpen()){
      queueMicrotask(() => syncFinanceStateFromServer());
    }
  }
}

function startFinanceRealtimeSync(){
  if(financeSyncTimer) clearInterval(financeSyncTimer);
  financeSyncTimer = setInterval(() => syncFinanceStateFromServer(), FINANCE_SYNC_INTERVAL_MS);

  financeSyncChannel?.addEventListener("message", event => {
    if(!event.data?.revision || event.data.revision !== financeStateRevision){
      syncFinanceStateFromServer({ force: true });
    }
  });
  window.addEventListener("storage", event => {
    if(event.key === "nanotechsoft-financeiro-sync"){
      syncFinanceStateFromServer({ force: true });
    }
  });
  window.addEventListener("focus", () => syncFinanceStateFromServer({ force: true }));
  document.addEventListener("visibilitychange", () => {
    if(!document.hidden) syncFinanceStateFromServer({ force: true });
  });
}

function favorecidoHasPaymentData(favorecido){
  return !!(
    String(favorecido?.pixKey || "").trim()
    || String(favorecido?.bankAccount || "").trim()
  );
}

function normalizeExternalAccessUrl(value){
  const raw = String(value || "").trim();
  if(!raw) return "";
  const candidate = /^[a-z][a-z0-9+.-]*:/i.test(raw) ? raw : `https://${raw}`;
  let parsed;
  try{
    parsed = new URL(candidate);
  }catch{
    throw new Error("Informe um link de acesso válido.");
  }
  if(!["http:", "https:"].includes(parsed.protocol) || !parsed.hostname){
    throw new Error("O link de acesso deve começar com http:// ou https://.");
  }
  return parsed.toString();
}

function favorecidoHasReusableData(favorecido){
  return favorecidoHasPaymentData(favorecido) || !!String(favorecido?.accessUrl || "").trim();
}

function syncFavorecidoPaymentToLinkedTitles(data, favorecidoId=""){
  if(!Array.isArray(data?.favorecidos) || !Array.isArray(data?.titulos)) return 0;
  const favorites = new Map(
    data.favorecidos
      .filter(item => (!favorecidoId || item.id === favorecidoId) && favorecidoHasReusableData(item))
      .map(item => [item.id, item])
  );
  let changed = 0;
  for(const titulo of data.titulos){
    if(titulo.tipo !== "AP") continue;
    const favorite = favorites.get(titulo.favorecidoId);
    if(!favorite) continue;
    const payment = {
      pixKeyType: favorite.pixKeyType || "TELEFONE",
      pixKey: String(favorite.pixKey || "").trim(),
      pixCity: String(favorite.pixCity || "").trim(),
      bankName: String(favorite.bankName || "").trim(),
      bankAccountType: favorite.bankAccountType || "CORRENTE",
      bankAgency: String(favorite.bankAgency || "").trim(),
      bankAccount: String(favorite.bankAccount || "").trim(),
      accessUrl: String(favorite.accessUrl || "").trim()
    };
    const differs = Object.entries(payment).some(([field, value]) => titulo[field] !== value);
    if(!differs) continue;
    Object.assign(titulo, payment);
    changed++;
  }
  return changed;
}

function migrate(d){
  if(!d.config) d.config = { tolDias: 3, tolValor: 0.5, scoreMin: 60 };
  if(!d.reconciliations) d.reconciliations = [];
  if(!d.imports) d.imports = [];
  if(!d.ignoredBankTransactions) d.ignoredBankTransactions = [];
  if(!Array.isArray(d.favorecidos)) d.favorecidos = [];
  if(!d.lancamentos) d.lancamentos = [];
  if(!d.categorias) d.categorias = [];
  if(!d.contas) d.contas = [];
  if(!d.titulos) d.titulos = [];
  if(!d.compras) d.compras = [];
  d.compras = Array.isArray(d.compras) ? d.compras.map(normalizeCompraRecord) : [];
  let lancCategoriasChanged = false;
  for(const lanc of d.lancamentos){
    if(normalizeLancamentoCategorias(lanc)) lancCategoriasChanged = true;
    if(!Array.isArray(lanc.anexos)){
      lanc.anexos = [];
      lancCategoriasChanged = true;
    }
  }
  let tituloChanged = false;
  for(const titulo of d.titulos){
    if(normalizeTituloCategorias(titulo)) tituloChanged = true;
    if(normalizeTituloRemovedFields(titulo)) tituloChanged = true;
    if(!Array.isArray(titulo.anexos)){
      titulo.anexos = [];
      tituloChanged = true;
    }
  }
  if(syncFavorecidoPaymentToLinkedTitles(d)) tituloChanged = true;
  if(lancCategoriasChanged || tituloChanged) financeStateNeedsPersist = true;
  repairGeneratedStatementDuplicates(d);
  normalizeTituloLancamentoLinks(d);
  return d;
}

function statementBankTransactionsById(data){
  const result = new Map();
  for(const imp of data.imports || []){
    for(const tx of imp.txs || []){
      if(tx?.id) result.set(tx.id, { tx, contaId: imp.contaId || "" });
    }
  }
  return result;
}

function isGeneratedStatementTitle(title, lanc, bankTx){
  if(!title || !lanc || !bankTx) return false;
  return !String(title.pessoa || "").trim()
    && title.bankTxId === bankTx.id
    && normalizeText(title.desc || "") === normalizeText(bankTx.memo || "")
    && normalizeText(lanc.desc || "") === normalizeText(bankTx.memo || "");
}

function repairGeneratedStatementDuplicates(data){
  if(!Array.isArray(data?.imports) || !Array.isArray(data?.lancamentos)) return 0;
  const bankById = statementBankTransactionsById(data);
  const lancById = new Map(data.lancamentos.map(lanc => [lanc.id, lanc]));
  const titleByLancId = new Map(
    (data.titulos || []).filter(title => title.lancId).map(title => [title.lancId, title])
  );
  const reconciliationByBank = new Map(
    (data.reconciliations || []).map(item => [item.bankTxId, item])
  );
  const reconciliationByLanc = new Map(
    (data.reconciliations || []).map(item => [item.lancId, item])
  );
  const removeLancIds = new Set();
  let changed = 0;

  // Versoes anteriores permitiam que um titulo criado do extrato roubasse um
  // vinculo ja confirmado. Quando existe exatamente um lancamento anterior
  // que ainda carrega o mesmo bankTxId, o par gerado pelo extrato e inequivoco:
  // ele e cancelado e o vinculo original e restaurado.
  for(const [bankTxId, reconciliation] of reconciliationByBank){
    const bankRecord = bankById.get(bankTxId);
    const generatedLanc = lancById.get(reconciliation.lancId);
    const generatedTitle = titleByLancId.get(reconciliation.lancId);
    if(!bankRecord || !isGeneratedStatementTitle(generatedTitle, generatedLanc, bankRecord.tx)) continue;
    const alternatives = data.lancamentos.filter(lanc =>
      lanc.id !== generatedLanc.id
      && lanc.bankTxId === bankTxId
      && lanc.contaId === bankRecord.contaId
    );
    if(alternatives.length !== 1) continue;

    const preferred = alternatives[0];
    reconciliation.lancId = preferred.id;
    reconciliationByLanc.delete(generatedLanc.id);
    reconciliationByLanc.set(preferred.id, reconciliation);
    preferred.conciliado = true;
    preferred.bankTxId = bankTxId;
    const preferredTitle = titleByLancId.get(preferred.id);
    if(preferredTitle) preferredTitle.bankTxId = bankTxId;

    generatedTitle.status = "CANCELADO";
    generatedTitle.lancId = null;
    generatedTitle.bankTxId = null;
    generatedTitle.baixadoEm = null;
    removeLancIds.add(generatedLanc.id);
    changed++;
  }

  if(removeLancIds.size){
    data.lancamentos = data.lancamentos.filter(lanc => !removeLancIds.has(lanc.id));
  }

  const usedBankIds = new Set((data.reconciliations || []).map(item => item.bankTxId));
  const usedLancIds = new Set((data.reconciliations || []).map(item => item.lancId));
  for(const lanc of data.lancamentos){
    const bankTxId = lanc.bankTxId;
    const bankRecord = bankById.get(bankTxId);
    if(
      !bankTxId
      || !bankRecord
      || bankRecord.contaId !== lanc.contaId
      || usedBankIds.has(bankTxId)
      || usedLancIds.has(lanc.id)
    ) continue;
    const reconciliation = { bankTxId, lancId: lanc.id };
    data.reconciliations.push(reconciliation);
    reconciliationByBank.set(bankTxId, reconciliation);
    usedBankIds.add(bankTxId);
    usedLancIds.add(lanc.id);
    const linkedTitle = titleByLancId.get(lanc.id);
    if(linkedTitle) linkedTitle.bankTxId = bankTxId;
    changed++;
  }

  const refreshedLancById = new Map(data.lancamentos.map(lanc => [lanc.id, lanc]));
  const refreshedTitleByLancId = new Map(
    (data.titulos || []).filter(title => title.lancId).map(title => [title.lancId, title])
  );
  for(const reconciliation of data.reconciliations || []){
    const bankRecord = bankById.get(reconciliation.bankTxId);
    const lanc = refreshedLancById.get(reconciliation.lancId);
    if(!bankRecord || !lanc || bankRecord.contaId !== lanc.contaId) continue;
    if(!lanc.conciliado || lanc.bankTxId !== reconciliation.bankTxId){
      lanc.conciliado = true;
      lanc.bankTxId = reconciliation.bankTxId;
      changed++;
    }
    const linkedTitle = refreshedTitleByLancId.get(lanc.id);
    if(linkedTitle && linkedTitle.bankTxId !== reconciliation.bankTxId){
      linkedTitle.bankTxId = reconciliation.bankTxId;
      changed++;
    }
  }

  for(const title of data.titulos || []){
    if(title.status === "BAIXADO" || !title.bankTxId || String(title.pessoa || "").trim()) continue;
    const bankRecord = bankById.get(title.bankTxId);
    if(
      bankRecord
      && reconciliationByBank.has(title.bankTxId)
      && normalizeText(title.desc || "") === normalizeText(bankRecord.tx.memo || "")
    ){
      title.bankTxId = null;
      changed++;
    }
  }

  if(changed) financeStateNeedsPersist = true;
  return changed;
}

function tituloLancamentoPayloadFromRecord(titulo, dataBaixaISO, existing={}){
  const isAR = titulo.tipo === "AR";
  const categoriaIds = getTituloCategoriaIds(titulo);
  const desc = tituloDescricaoText(titulo);
  return {
    ...existing,
    data: dataBaixaISO,
    contaId: titulo.contaId,
    tipo: isAR ? "RECEITA" : "DESPESA",
    categoriaId: categoriaIds[0] || titulo.categoriaId || "",
    categoriaIds,
    desc: `${desc}${titulo.pessoa ? " - " + titulo.pessoa : ""}`,
    valor: Math.abs(Number(titulo.valor || 0)),
    conciliado: !!titulo.bankTxId,
    bankTxId: titulo.bankTxId || null
  };
}

function normalizeTituloLancamentoLinks(data){
  if(!Array.isArray(data.titulos) || !Array.isArray(data.lancamentos)) return;

  let changed = false;
  const lancById = new Map(data.lancamentos.map(lanc => [lanc.id, lanc]));
  const removeLancIds = new Set();
  const contaByBankTxId = new Map();

  for(const imp of data.imports || []){
    for(const tx of imp.txs || []){
      if(tx?.id) contaByBankTxId.set(tx.id, imp.contaId || "");
    }
  }

  for(const titulo of data.titulos){
    titulo.status = titulo.status || "ABERTO";

    const bankContaId = titulo.bankTxId ? contaByBankTxId.get(titulo.bankTxId) : "";
    if(bankContaId && bankContaId !== titulo.contaId){
      titulo.bankTxId = null;
      changed = true;
    }

    if(titulo.status !== "BAIXADO"){
      if(titulo.lancId){
        removeLancIds.add(titulo.lancId);
        titulo.lancId = null;
        changed = true;
      }
      if(titulo.baixadoEm){
        titulo.baixadoEm = null;
        changed = true;
      }
      continue;
    }

    const hadBaixadoEm = !!titulo.baixadoEm;
    const dataBaixa = titulo.baixadoEm || toISODate(new Date());
    let lanc = titulo.lancId ? lancById.get(titulo.lancId) : null;
    if(!lanc){
      lanc = { id: titulo.lancId || uid("lanc") };
      titulo.lancId = lanc.id;
      data.lancamentos.unshift(lanc);
      lancById.set(lanc.id, lanc);
      changed = true;
    }

    const nextLanc = tituloLancamentoPayloadFromRecord(titulo, dataBaixa, { id: lanc.id });
    const before = JSON.stringify(lanc);
    Object.assign(lanc, nextLanc);
    titulo.baixadoEm = dataBaixa;
    if(!hadBaixadoEm) changed = true;
    if(before !== JSON.stringify(lanc)) changed = true;
  }

  if(removeLancIds.size){
    data.lancamentos = data.lancamentos.filter(lanc => !removeLancIds.has(lanc.id));
    data.reconciliations = (data.reconciliations || []).filter(r => !removeLancIds.has(r.lancId));
    changed = true;
  }

  const validLancIds = new Set(data.lancamentos.map(lanc => lanc.id));
  const reconciliationsBefore = (data.reconciliations || []).length;
  data.reconciliations = (data.reconciliations || []).filter(r => validLancIds.has(r.lancId));
  if(data.reconciliations.length !== reconciliationsBefore) changed = true;

  for(const titulo of data.titulos){
    if(titulo.status !== "BAIXADO" || !titulo.lancId || !titulo.bankTxId) continue;
    const hasExact = data.reconciliations.some(r => r.lancId === titulo.lancId && r.bankTxId === titulo.bankTxId);
    const hasConflict = data.reconciliations.some(r =>
      (r.lancId === titulo.lancId || r.bankTxId === titulo.bankTxId) &&
      !(r.lancId === titulo.lancId && r.bankTxId === titulo.bankTxId)
    );
    if(!hasExact || hasConflict){
      data.reconciliations = data.reconciliations.filter(r => r.lancId !== titulo.lancId && r.bankTxId !== titulo.bankTxId);
      data.reconciliations.push({ bankTxId: titulo.bankTxId, lancId: titulo.lancId });
      changed = true;
    }
  }

  if(changed) financeStateNeedsPersist = true;
}
function seed(){
  const contaId = uid("conta");
  return {
    contas: [
      { id: contaId, nome: "Conta principal", moeda: "BRL", saldoInicial: 0 }
    ],
    categorias: [
      { id: uid("cat"), nome: "Alimentação", tipo: "DESPESA" },
      { id: uid("cat"), nome: "Transporte", tipo: "DESPESA" },
      { id: uid("cat"), nome: "Moradia", tipo: "DESPESA" },
      { id: uid("cat"), nome: "Salário", tipo: "RECEITA" },
      { id: uid("cat"), nome: "Outros", tipo: "DESPESA" },
    ],
    lancamentos: [],
    imports: [],
    reconciliations: [],
    ignoredBankTransactions: [],
    favorecidos: [],
    titulos: [],
    compras: [],
    config: { tolDias: 3, tolValor: 0.5, scoreMin: 60 }
  };
}

function escapeHtml(str){
  return String(str ?? "")
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;")
    .replaceAll('"',"&quot;")
    .replaceAll("'","&#039;");
}

const TITLE_META_MARKER = "__GF_META__:";

function parseTitleObs(obs){
  const raw = String(obs || "");
  const markerIndex = raw.indexOf(TITLE_META_MARKER);
  if(markerIndex < 0){
    return { text: raw.trim(), meta: {} };
  }

  const text = raw.slice(0, markerIndex).replace(/\s*\|\s*$/, "").trim();
  const metaRaw = raw.slice(markerIndex + TITLE_META_MARKER.length).trim();
  try{
    const meta = JSON.parse(metaRaw);
    return { text, meta: (meta && typeof meta === "object") ? meta : {} };
  }catch{
    return { text, meta: {} };
  }
}

function buildTitleObs(text, meta={}){
  const cleanText = String(text || "").trim();
  const cleanMeta = Object.fromEntries(
    Object.entries(meta).filter(([, value]) => value !== null && value !== undefined && String(value).trim() !== "")
  );
  if(!Object.keys(cleanMeta).length) return cleanText;
  return `${cleanText}${cleanText ? "\n" : ""}${TITLE_META_MARKER}${JSON.stringify(cleanMeta)}`;
}

function getCompraByTituloId(tituloId){
  return state.compras.find(compra => compra.titleId === tituloId) || null;
}

function stripRemovedTitleMeta(meta={}){
  const cleanMeta = { ...(meta || {}) };
  delete cleanMeta.formaPagamento;
  return cleanMeta;
}

function appendTextToDescription(desc, extraText){
  const base = String(desc || "").trim();
  const extra = String(extraText || "").trim();
  if(!extra) return base;
  if(!base) return extra;
  if(base.toLowerCase().includes(extra.toLowerCase())) return base;
  return `${base} | ${extra}`;
}

function normalizeTituloRemovedFields(titulo){
  if(!titulo) return false;
  const parsedDesc = parseTitleObs(titulo.desc);
  const parsedObs = parseTitleObs(titulo.obs);
  const mergedMeta = { ...parsedDesc.meta, ...parsedObs.meta };
  let nextDesc = appendTextToDescription(parsedDesc.text, parsedObs.text);
  if(mergedMeta.formaPagamento){
    nextDesc = appendTextToDescription(nextDesc, `Pagamento: ${mergedMeta.formaPagamento}`);
  }

  const nextObs = buildTitleObs("", stripRemovedTitleMeta(mergedMeta));
  const changed = nextDesc !== String(titulo.desc || "").trim() || String(titulo.obs || "") !== nextObs;
  titulo.desc = nextDesc;
  titulo.obs = nextObs;
  return changed;
}

function tituloDescricaoText(titulo, fallback=""){
  return parseTitleObs(titulo?.desc).text || fallback;
}

function uniqueNonEmpty(values){
  return Array.from(new Set((values || []).map(v => String(v || "").trim()).filter(Boolean)));
}

function normalizedLancCategoriaIds(lancamento){
  if(!lancamento || isTransferenciaLancamento(lancamento)) return [];
  const ids = Array.isArray(lancamento.categoriaIds) ? uniqueNonEmpty(lancamento.categoriaIds) : [];
  const primary = String(lancamento.categoriaId || "").trim();
  if(ids.length && (!primary || ids.includes(primary))) return ids;
  return primary ? [primary] : ids;
}

function normalizeLancamentoCategorias(lancamento){
  if(!lancamento || isTransferenciaLancamento(lancamento)) return false;
  const ids = normalizedLancCategoriaIds(lancamento);
  const before = JSON.stringify({
    categoriaId: lancamento.categoriaId || "",
    categoriaIds: Array.isArray(lancamento.categoriaIds) ? lancamento.categoriaIds : null
  });
  lancamento.categoriaIds = ids;
  lancamento.categoriaId = ids[0] || "";
  return before !== JSON.stringify({ categoriaId: lancamento.categoriaId, categoriaIds: lancamento.categoriaIds });
}

function getLancCategoriaIds(lancamento){
  return normalizedLancCategoriaIds(lancamento);
}

function normalizedTituloCategoriaIds(titulo){
  const ids = Array.isArray(titulo?.categoriaIds) ? uniqueNonEmpty(titulo.categoriaIds) : [];
  const primary = String(titulo?.categoriaId || "").trim();
  if(ids.length && (!primary || ids.includes(primary))) return ids;
  return primary ? [primary] : ids;
}

function normalizeTituloCategorias(titulo){
  if(!titulo) return false;
  const ids = normalizedTituloCategoriaIds(titulo);
  const before = JSON.stringify({
    categoriaId: titulo.categoriaId || "",
    categoriaIds: Array.isArray(titulo.categoriaIds) ? titulo.categoriaIds : null
  });
  titulo.categoriaIds = ids;
  titulo.categoriaId = ids[0] || "";
  return before !== JSON.stringify({ categoriaId: titulo.categoriaId, categoriaIds: titulo.categoriaIds });
}

function getTituloCategoriaIds(titulo){
  return normalizedTituloCategoriaIds(titulo);
}

function getSelectValues(selector){
  const el = $(selector);
  if(!el) return [];
  return Array.from(el.selectedOptions || []).map(opt => opt.value).filter(Boolean);
}

function setSelectValues(selector, values, fallback=""){
  const el = $(selector);
  if(!el) return;
  const wanted = new Set(uniqueNonEmpty(values));
  let selected = 0;
  for(const opt of Array.from(el.options)){
    opt.selected = wanted.has(opt.value);
    if(opt.selected) selected++;
  }
  if(!selected && fallback){
    const opt = Array.from(el.options).find(option => option.value === fallback);
    if(opt) opt.selected = true;
  }
}

function categoriaNamesText(categoriaIds, fallback="Sem categoria"){
  const ids = uniqueNonEmpty(categoriaIds);
  const names = ids
    .map(id => state.categorias.find(c => c.id === id)?.nome)
    .filter(Boolean);
  return names.length ? names.join(", ") : fallback;
}

function categoriaBadgesHtml(categoriaIds, fallback="Sem categoria"){
  const ids = uniqueNonEmpty(categoriaIds);
  const badges = ids
    .map(id => state.categorias.find(c => c.id === id))
    .filter(Boolean)
    .map(cat => `<span class="badge categoryTag">${escapeHtml(cat.nome)}</span>`);
  if(!badges.length) return `<span class="muted">${escapeHtml(fallback)}</span>`;
  return `<div class="tagList">${badges.join("")}</div>`;
}

const TRANSFERENCIA_TIPO = "TRANSFERENCIA";

function isTransferenciaLancamento(lancamento){
  return !!lancamento?.transferenciaId;
}

function isTransferenciaOrigem(lancamento){
  if(!isTransferenciaLancamento(lancamento)) return false;
  return lancamento.transferenciaLado === "ORIGEM" || lancamento.tipo === "DESPESA";
}

function isTransferenciaDestino(lancamento){
  if(!isTransferenciaLancamento(lancamento)) return false;
  return lancamento.transferenciaLado === "DESTINO" || lancamento.tipo === "RECEITA";
}

function getTransferenciaEntries(transferenciaId){
  if(!transferenciaId) return [];
  return state.lancamentos.filter(l => l.transferenciaId === transferenciaId);
}

function getTransferenciaPartes(transferenciaId){
  const entries = getTransferenciaEntries(transferenciaId);
  const origem = entries.find(isTransferenciaOrigem) || entries[0] || null;
  const destino = entries.find(l => l.id !== origem?.id && isTransferenciaDestino(l)) ||
    entries.find(l => l.id !== origem?.id) ||
    null;
  return { entries, origem, destino };
}

function contaNome(contaId){
  return state.contas.find(c => c.id === contaId)?.nome || "Conta";
}

function transferenciaDescricao(desc, origemId, destinoId){
  const clean = String(desc || "").trim();
  if(clean) return clean;
  return `Transferencia entre ${contaNome(origemId)} e ${contaNome(destinoId)}`;
}

function buildTransferenciaLancamento({ existing=null, transferenciaId, lado, data, contaOrigemId, contaDestinoId, desc, valor, conciliado }){
  const isOrigem = lado === "ORIGEM";
  return {
    ...(existing || {}),
    id: existing?.id || uid("lanc"),
    data,
    contaId: isOrigem ? contaOrigemId : contaDestinoId,
    tipo: isOrigem ? "DESPESA" : "RECEITA",
    categoriaId: "",
    categoriaIds: [],
    desc: transferenciaDescricao(desc, contaOrigemId, contaDestinoId),
    valor,
    conciliado: !!(existing?.bankTxId || conciliado),
    bankTxId: existing?.bankTxId || null,
    transferenciaId,
    transferenciaLado: lado,
    contaOrigemId,
    contaDestinoId
  };
}

function salvarTransferenciaLancamento({ data, contaOrigemId, contaDestinoId, desc, valor, conciliado }){
  const editingEntries = editTransferenciaId ? getTransferenciaEntries(editTransferenciaId) : [];
  const transferId = editTransferenciaId || uid("transf");
  const oldOrigem = editingEntries.find(isTransferenciaOrigem) || editingEntries[0] || null;
  const oldDestino = editingEntries.find(l => l.id !== oldOrigem?.id && isTransferenciaDestino(l)) ||
    editingEntries.find(l => l.id !== oldOrigem?.id) ||
    null;

  const origem = buildTransferenciaLancamento({
    existing: oldOrigem || (editLancId ? state.lancamentos.find(l => l.id === editLancId) : null),
    transferenciaId: transferId,
    lado: "ORIGEM",
    data,
    contaOrigemId,
    contaDestinoId,
    desc,
    valor,
    conciliado
  });
  const destino = buildTransferenciaLancamento({
    existing: oldDestino,
    transferenciaId: transferId,
    lado: "DESTINO",
    data,
    contaOrigemId,
    contaDestinoId,
    desc,
    valor,
    conciliado
  });

  const oldIds = new Set(editingEntries.map(l => l.id));
  if(editLancId) oldIds.add(editLancId);
  const keepIds = new Set([origem.id, destino.id]);
  state.reconciliations = state.reconciliations.filter(r => !oldIds.has(r.lancId) || keepIds.has(r.lancId));

  state.lancamentos = state.lancamentos.filter(l => {
    if(l.transferenciaId && l.transferenciaId === transferId) return false;
    if(editLancId && l.id === editLancId) return false;
    return true;
  });
  state.lancamentos.unshift(destino);
  state.lancamentos.unshift(origem);
  return { origem, destino };
}

function lancamentoTipoBadge(lancamento){
  if(isTransferenciaLancamento(lancamento)){
    const side = isTransferenciaOrigem(lancamento) ? "SAIDA" : "ENTRADA";
    const cls = isTransferenciaOrigem(lancamento) ? "bad" : "ok";
    return `<span class="badge ${cls}">TRANSF. ${side}</span>`;
  }
  return lancamento.tipo === "RECEITA"
    ? `<span class="badge ok">RECEITA</span>`
    : `<span class="badge bad">DESPESA</span>`;
}

function transferenciaConciliacaoBadge(entries){
  const total = entries.length || 2;
  const done = entries.filter(l => l.conciliado || l.bankTxId).length;
  if(done >= total) return `<span class="badge ok">Sim</span>`;
  if(done > 0) return `<span class="badge warn">Parcial</span>`;
  return `<span class="badge warn">Não</span>`;
}

function transferenciaRowFromLancamento(lancamento, scopedList){
  const partes = getTransferenciaPartes(lancamento.transferenciaId);
  const scopedEntries = scopedList.filter(l => l.transferenciaId === lancamento.transferenciaId);
  const origem = partes.origem || scopedEntries[0] || lancamento;
  const destino = partes.destino || scopedEntries.find(l => l.id !== origem.id) || null;
  return {
    kind: "transferencia",
    id: origem.id,
    transferenciaId: lancamento.transferenciaId,
    data: origem.data || destino?.data || lancamento.data || "",
    valor: Number(origem.valor || destino?.valor || lancamento.valor || 0),
    desc: origem.desc || destino?.desc || lancamento.desc || "",
    origem,
    destino,
    entries: partes.entries.length ? partes.entries : scopedEntries
  };
}

function buildLancamentoRows(list){
  const rows = [];
  const seenTransfers = new Set();

  for(const lanc of list){
    if(isTransferenciaLancamento(lanc)){
      if(seenTransfers.has(lanc.transferenciaId)) continue;
      seenTransfers.add(lanc.transferenciaId);
      rows.push(transferenciaRowFromLancamento(lanc, list));
      continue;
    }
    rows.push({ kind: "lancamento", id: lanc.id, data: lanc.data || "", lanc });
  }

  return rows.sort((a,b)=> String(b.data || "").localeCompare(String(a.data || "")));
}

/* ---------- Navegação ---------- */
function canUseFinanceView(name){
  return FINANCEIRO_ALLOWED.includes("*") || FINANCEIRO_ALLOWED.includes(name);
}
function firstAllowedFinanceView(){
  return $$(".tab").find(btn => canUseFinanceView(btn.dataset.view))?.dataset.view || "dashboard";
}
function applyFinancePermissions(){
  $$(".tab").forEach(btn => {
    btn.hidden = !canUseFinanceView(btn.dataset.view);
  });
}
function setView(name){
  if(!canUseFinanceView(name)) name = firstAllowedFinanceView();
  $$(".tab").forEach(b => b.classList.toggle("active", b.dataset.view === name));
  $$(".view").forEach(v => v.classList.add("hidden"));
  $("#view-"+name).classList.remove("hidden");
  renderAll();
}

function financeInitialView(){
  const params = new URLSearchParams(location.search);
  return window.FINANCEIRO_INITIAL_VIEW || params.get("view") || (location.hash || "").replace("#", "");
}

function financeReportDate(value){
  if(!isValidDateISO(value)) return value || "Não informado";
  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}

function financeReportMonth(value){
  const match = String(value || "").match(/^(\d{4})-(\d{2})$/);
  if(!match) return value || "Não informado";
  const date = new Date(Number(match[1]), Number(match[2]) - 1, 1);
  return date.toLocaleDateString("pt-BR", { month: "long", year: "numeric" });
}

function financeSelectedText(selector, fallback="Todos"){
  const element = $(selector);
  return element?.selectedOptions?.[0]?.textContent?.trim() || fallback;
}

function financeReportFilters(items){
  return `
    <div class="reportFilters">
      ${items.map(item => `
        <div class="reportFilter">
          <span>${escapeHtml(item.label)}</span>
          <b>${escapeHtml(item.value || "Não informado")}</b>
        </div>
      `).join("")}
    </div>
  `;
}

function openFinancePrintReport({ title, description, filters, content, layout="table" }){
  const printWindow = window.open("", "_blank");
  if(!printWindow){
    alert("O navegador bloqueou a janela de impressão. Libere pop-ups para gerar o PDF.");
    return;
  }

  printWindow.opener = null;
  const generatedAt = new Date().toLocaleString("pt-BR");
  const safeFileTitle = String(title || "Relatório financeiro").replace(/[\\/:*?"<>|]+/g, "-");
  printWindow.document.open();
  printWindow.document.write(`<!doctype html>
    <html lang="pt-br">
      <head>
        <meta charset="utf-8">
        <title>${escapeHtml(safeFileTitle)}</title>
        <style>
          @page { size: A4 landscape; margin: 10mm; }
          * { box-sizing: border-box; }
          html, body { margin: 0; padding: 0; color: #18212f; background: #fff; }
          body { font: 9pt/1.35 Arial, Helvetica, sans-serif; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
          .reportHeader { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; padding-bottom: 10px; border-bottom: 2px solid #174f75; }
          .reportBrand { color: #174f75; font-size: 8pt; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
          h1 { margin: 3px 0 2px; color: #102a43; font-size: 20pt; line-height: 1.1; }
          .reportDescription, .reportGenerated, .muted, .kpiLabel { color: #526579; }
          .reportGenerated { white-space: nowrap; text-align: right; font-size: 8pt; }
          .reportFilters { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
          .reportFilter { min-width: 130px; padding: 6px 8px; border: 1px solid #cfdae5; border-radius: 5px; background: #f5f8fb; }
          .reportFilter span, .reportFilter b { display: block; }
          .reportFilter span { color: #607487; font-size: 7pt; text-transform: uppercase; }
          .reportFilter b { margin-top: 2px; }
          .card { margin: 0 0 8px; padding: 8px; border: 1px solid #cfdae5; border-radius: 5px; break-inside: avoid-page; }
          .cardhead, .accountStatusHead, .item, .filteredTitlesTotal { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
          .cardhead { margin-bottom: 6px; }
          h2 { margin: 0; color: #174f75; font-size: 11pt; }
          .grid2, .grid3, .kpis, .accountStatusMetrics { display: grid; gap: 7px; }
          .grid2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .grid3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
          .kpis, .accountStatusMetrics { grid-template-columns: repeat(4, minmax(0, 1fr)); }
          .dashboardWide { margin-top: 8px; }
          .kpi, .accountStatusMetrics > div { padding: 6px; border: 1px solid #dce5ed; border-radius: 4px; background: #f7f9fb; }
          .kpiValue { margin-top: 2px; color: #102a43; font-size: 12pt; font-weight: 800; }
          .list { display: grid; gap: 4px; }
          .item { padding: 5px 0; border-bottom: 1px solid #e2e8ef; break-inside: avoid; }
          .item:last-child { border-bottom: 0; }
          .accountStatusItem { display: block; padding: 6px; border: 1px solid #dce5ed; border-radius: 4px; }
          .accountStatusMetrics { margin-top: 5px; }
          .accountStatusMetrics span, .accountStatusMetrics b { display: block; }
          .accountBalanceAudit { margin-top: 5px; padding-top: 5px; border-top: 1px solid #e2e8ef; }
          .accountBalanceAudit ul { margin: 3px 0 0; padding-left: 16px; }
          .accountStatusBadges, .tagList { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 3px; }
          .badge { display: inline-block; padding: 2px 5px; border: 1px solid #bdcad6; border-radius: 9px; background: #eef3f7; color: #29445c; font-size: 7.5pt; font-weight: 700; }
          .badge.ok, .ok, .okText { color: #146c43; }
          .badge.bad, .bad, .badText { color: #a12b35; }
          .badge.warn, .warn { color: #8a5700; }
          .tableWrap { overflow: visible; }
          table { width: 100%; border-collapse: collapse; table-layout: auto; }
          thead { display: table-header-group; }
          tr { break-inside: avoid; }
          th, td { padding: 5px 4px; border-bottom: 1px solid #d8e1e9; text-align: left; vertical-align: top; overflow-wrap: anywhere; }
          th { background: #eaf1f6; color: #29445c; font-size: 7.5pt; text-transform: uppercase; }
          th.right, td.right { text-align: right; white-space: nowrap; }
          .filteredTitlesTotal { margin-top: 8px; padding: 8px; border: 1px solid #b9c9d6; border-radius: 5px; background: #f5f8fb; }
          .filteredTitlesTotal > div { display: flex; gap: 8px; align-items: baseline; }
          .filteredTitlesTotal strong { color: #102a43; font-size: 13pt; }
          button, input, select, textarea, .modal, .footer { display: none !important; }
          body.report-table .grid2, body.report-table .grid3 { display: block; }
        </style>
      </head>
      <body class="report-${escapeHtml(layout)}">
        <header class="reportHeader">
          <div>
            <div class="reportBrand">NanotechSoft · Financeiro</div>
            <h1>${escapeHtml(title)}</h1>
            <div class="reportDescription">${escapeHtml(description)}</div>
          </div>
          <div class="reportGenerated">Gerado em<br><b>${escapeHtml(generatedAt)}</b></div>
        </header>
        ${financeReportFilters(filters)}
        <main>${content}</main>
      </body>
    </html>`);
  printWindow.document.close();
  printWindow.addEventListener("afterprint", () => printWindow.close(), { once: true });
  printWindow.focus();
  printWindow.setTimeout(() => printWindow.print(), 200);
}

function printDashboardReport(){
  renderDashboard();
  const dashboard = $("#view-dashboard")?.cloneNode(true);
  if(!dashboard) return alert("Não foi possível preparar o dashboard para impressão.");
  dashboard.querySelector(".cardhead .row")?.remove();
  dashboard.querySelectorAll("button, input, select").forEach(element => element.remove());
  openFinancePrintReport({
    title: "Dashboard financeiro",
    description: "Indicadores e detalhamentos conforme a seleção atual do dashboard.",
    layout: "dashboard",
    filters: [
      { label: "Conta", value: financeSelectedText("#dashConta") },
      { label: "Mês de referência", value: financeReportMonth($("#dashMes")?.value) }
    ],
    content: dashboard.innerHTML
  });
}

function titleReportFilters(tipo){
  const isAP = tipo === "AP";
  const prefix = isAP ? "ap" : "ar";
  const start = $(`#${prefix}Ini`)?.value || "";
  const end = $(`#${prefix}Fim`)?.value || "";
  const period = start || end
    ? `${start ? financeReportDate(start) : "Início livre"} a ${end ? financeReportDate(end) : "Sem limite final"}`
    : "Todas as datas";
  const search = $(`#${prefix}Busca`)?.value?.trim() || "Sem termo de busca";
  return [
    { label: "Conta", value: financeSelectedText(`#${prefix}Conta`) },
    { label: "Status", value: financeSelectedText(`#${prefix}Status`) },
    { label: "Vencimento", value: period },
    { label: "Busca", value: search }
  ];
}

async function printTitlesReport(tipo, button=null){
  const isAP = tipo === "AP";
  renderTabelaTitulos(tipo);
  const titles = filteredTitulos(tipo);
  const previewWindow = window.open("", "_blank");
  if(previewWindow){
    previewWindow.document.write(`<!doctype html><html lang="pt-br"><head><meta charset="utf-8"><title>Gerando PDF...</title></head><body style="font:16px Arial;padding:32px;color:#26394d">Gerando o relatório e unindo os anexos PDF...</body></html>`);
    previewWindow.document.close();
    previewWindow.opener = null;
  }

  const oldText = button?.textContent || "";
  if(button){
    button.disabled = true;
    button.textContent = "Gerando PDF...";
  }

  try{
    const response = await fetch("/apps/financeiro/api/titles-report-pdf", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/pdf, application/json" },
      body: JSON.stringify({
        tipo,
        revision: financeStateRevision,
        tituloIds: titles.map(title => title.id),
        filtros: titleReportFilters(tipo)
      })
    });
    if(!response.ok){
      let message = `Não foi possível gerar o PDF (${response.status}).`;
      try{
        const payload = await response.json();
        if(payload?.error) message = payload.error;
      }catch{
        // Mantém a mensagem baseada no status HTTP.
      }
      throw new Error(message);
    }

    const blob = await response.blob();
    if(blob.type && !blob.type.includes("pdf")){
      throw new Error("O servidor não retornou um arquivo PDF válido.");
    }
    const objectUrl = URL.createObjectURL(blob);
    if(previewWindow && !previewWindow.closed){
      previewWindow.location.replace(objectUrl);
    }else{
      const download = document.createElement("a");
      download.href = objectUrl;
      download.download = `${isAP ? "contas-a-pagar" : "contas-a-receber"}_${toISODate(new Date())}.pdf`;
      document.body.appendChild(download);
      download.click();
      download.remove();
      alert("O navegador bloqueou a prévia. O PDF único foi baixado automaticamente.");
    }
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 5 * 60 * 1000);
  }catch(err){
    previewWindow?.close();
    alert(err?.message || "Não foi possível gerar o relatório com os anexos.");
  }finally{
    if(button){
      button.disabled = false;
      button.textContent = oldText;
    }
  }
}

$("#tabs")?.addEventListener("click", (e)=>{
  const btn = e.target.closest(".tab");
  if(!btn) return;
  setView(btn.dataset.view);
});

/* ---------- Render geral ---------- */
function renderAll(){
  fillSelects();
  renderDashboard();
  renderLancamentos();
  renderContas();
  renderCategorias();
  renderFavorecidos();
  renderImportPreview();
  renderConciliacao();
  renderCompras();
  renderAPAR();
  renderConfig();
}

/* ---------- Selects (preserva seleção) ---------- */
function safeRestoreSelect(selector, value){
  const el = $(selector);
  if(!el) return;
  const exists = Array.from(el.options).some(o => o.value === value);
  el.value = exists ? value : (el.options[0]?.value || "");
}

function fillSelects(){
  const contas = state.contas;
  const cats = state.categorias;

  const prev = {
    dashConta: $("#dashConta")?.value,
    fConta: $("#fConta")?.value,
    lConta: $("#lConta")?.value,
    lContaDestino: $("#lContaDestino")?.value,
    ofxConta: $("#ofxConta")?.value,
    concConta: $("#concConta")?.value,
    concImport: $("#concImport")?.value,

    apConta: $("#apConta")?.value,
    arConta: $("#arConta")?.value,
    tConta: $("#tConta")?.value,
    tFavorecido: $("#tFavorecido")?.value,
    pcConta: $("#pcConta")?.value,

    lTipo: $("#lTipo")?.value,
    lCategoria: $("#lCategoria")?.value,
    lCategorias: getSelectValues("#lCategoria"),

    tTipo: $("#tTipo")?.value,
    tCategoria: $("#tCategoria")?.value,
    tCategorias: getSelectValues("#tCategoria"),
    pcCategoria: $("#pcCategoria")?.value
  };

  const contaOptions = (includeAll=false) => {
    const opts = [];
    if(includeAll) opts.push(`<option value="ALL">Todas</option>`);
    for(const c of contas){
      opts.push(`<option value="${c.id}">${escapeHtml(c.nome)}</option>`);
    }
    return opts.join("");
  };

  // contas gerais
  $("#dashConta").innerHTML = contaOptions(true);
  $("#fConta").innerHTML    = contaOptions(true);
  $("#lConta").innerHTML    = contaOptions(false);
  $("#lContaDestino").innerHTML = contaOptions(false);
  $("#ofxConta").innerHTML  = contaOptions(false);
  $("#concConta").innerHTML = contaOptions(false);

  // AP/AR
  $("#apConta").innerHTML = contaOptions(true);
  $("#arConta").innerHTML = contaOptions(true);
  $("#tConta").innerHTML  = contaOptions(false);
  if($("#pcConta")) $("#pcConta").innerHTML = contaOptions(false);

  safeRestoreSelect("#dashConta", prev.dashConta ?? "ALL");
  safeRestoreSelect("#fConta", prev.fConta ?? "ALL");
  safeRestoreSelect("#lConta", prev.lConta ?? (contas[0]?.id || ""));
  safeRestoreSelect("#lContaDestino", prev.lContaDestino ?? (contas.find(c => c.id !== $("#lConta")?.value)?.id || contas[1]?.id || ""));
  safeRestoreSelect("#ofxConta", prev.ofxConta ?? (contas[0]?.id || ""));
  safeRestoreSelect("#concConta", prev.concConta ?? (contas[0]?.id || ""));

  safeRestoreSelect("#apConta", prev.apConta ?? "ALL");
  safeRestoreSelect("#arConta", prev.arConta ?? "ALL");
  safeRestoreSelect("#tConta", prev.tConta ?? (contas[0]?.id || ""));
  safeRestoreSelect("#pcConta", prev.pcConta ?? (contas[0]?.id || ""));

  const favorecidos = (state.favorecidos || [])
    .slice()
    .sort((a, b) => String(a.nome || "").localeCompare(String(b.nome || ""), "pt-BR"));
  $("#tFavorecido").innerHTML = [
    `<option value="">Preenchimento manual</option>`,
    ...favorecidos.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.nome)}</option>`)
  ].join("");
  safeRestoreSelect("#tFavorecido", prev.tFavorecido ?? "");

  // categorias do modal de lançamento dependem do tipo
  const tipoLanc = $("#lTipo").value || prev.lTipo || "DESPESA";
  $("#lTipo").value = tipoLanc;
  if(tipoLanc === TRANSFERENCIA_TIPO){
    $("#lCategoria").innerHTML = `<option value="">Sem categoria</option>`;
    setSelectValues("#lCategoria", []);
  } else {
    const catsLanc = cats.filter(c => c.tipo === tipoLanc);
    $("#lCategoria").innerHTML = catsLanc.map(c => `<option value="${c.id}">${escapeHtml(c.nome)}</option>`).join("");
    setSelectValues(
      "#lCategoria",
      prev.lCategorias.length ? prev.lCategorias : uniqueNonEmpty([prev.lCategoria]),
      catsLanc[0]?.id || ""
    );
  }

  // categorias do modal de título dependem do tipo AP/AR
  const tipoTit = $("#tTipo")?.value || prev.tTipo || "AP";
  if($("#tTipo")) $("#tTipo").value = tipoTit;
  const tipoCatTit = (tipoTit === "AR") ? "RECEITA" : "DESPESA";
  const catsTit = cats.filter(c => c.tipo === tipoCatTit);
  $("#tCategoria").innerHTML = catsTit.map(c => `<option value="${c.id}">${escapeHtml(c.nome)}</option>`).join("");
  setSelectValues(
    "#tCategoria",
    prev.tCategorias.length ? prev.tCategorias : uniqueNonEmpty([prev.tCategoria]),
    catsTit[0]?.id || ""
  );

  const catsCompra = cats.filter(c => c.tipo === "DESPESA");
  if($("#pcCategoria")){
    $("#pcCategoria").innerHTML = catsCompra.map(c => `<option value="${c.id}">${escapeHtml(c.nome)}</option>`).join("");
    safeRestoreSelect("#pcCategoria", prev.pcCategoria ?? (catsCompra[0]?.id || ""));
  }
}

$("#lTipo").addEventListener("change", ()=>{
  fillSelects();
  updateLancModalMode();
});
$("#lConta").addEventListener("change", updateLancModalMode);
$("#tTipo").addEventListener("change", ()=>{
  fillSelects();
  syncPixPaymentUi();
});

/* ---------- Dashboard ---------- */
function isValidDateISO(value){
  return /^\d{4}-\d{2}-\d{2}$/.test(String(value || ""));
}

function isSameMonthISO(value, year, month){
  if(!isValidDateISO(value)) return false;
  const [y, m] = String(value).split("-").map(Number);
  return y === year && m === month;
}

function contaCriadaEm(conta){
  const suffix = String(conta?.id || "").match(/_([0-9a-f]+)$/i)?.[1];
  if(!suffix) return "";
  const timestamp = Number.parseInt(suffix, 16);
  if(!Number.isFinite(timestamp)) return "";
  const createdAt = new Date(timestamp);
  if(Number.isNaN(createdAt.getTime())) return "";
  const createdISO = toISODate(createdAt);
  return isValidDateISO(createdISO) ? createdISO : "";
}

function contaSaldoInicialEm(conta){
  if(isValidDateISO(conta?.saldoInicialEm)) return conta.saldoInicialEm;
  return contaCriadaEm(conta);
}

function latestStatementBalance(contaId, todayISO=toISODate(new Date())){
  return (state.imports || [])
    .filter(imp =>
      imp.contaId === contaId
      && Number.isFinite(Number(imp.closingBalance))
      && isValidDateISO(imp.balanceDate)
      && imp.balanceDate <= todayISO
    )
    .sort((a, b) =>
      String(b.balanceDate).localeCompare(String(a.balanceDate))
      || String(b.createdAt || "").localeCompare(String(a.createdAt || ""))
    )[0] || null;
}

function reconciledBankTransactionsByLancamento(contaId){
  const bankById = new Map(
    (state.imports || [])
      .filter(imp => imp.contaId === contaId)
      .flatMap(imp => (imp.txs || []).map(tx => [tx.id, tx]))
  );
  const result = new Map();
  for(const reconciliation of state.reconciliations || []){
    const bankTx = bankById.get(reconciliation.bankTxId);
    if(bankTx) result.set(reconciliation.lancId, bankTx);
  }
  return result;
}

function bankTransactionsForAccount(contaId){
  return (state.imports || [])
    .filter(imp => imp.contaId === contaId)
    .flatMap(imp => imp.txs || []);
}

function signedLancamentoValue(lancamento){
  const value = Math.abs(Number(lancamento?.valor || 0));
  return lancamento?.tipo === "RECEITA" ? value : -value;
}

function buildAccountBalanceAudit(contaId, calculatedBalance, todayISO=toISODate(new Date())){
  const statement = latestStatementBalance(contaId, todayISO);
  if(!statement) return null;

  const bankTxs = bankTransactionsForAccount(contaId);
  const bankById = new Map(bankTxs.map(tx => [tx.id, tx]));
  const reconByBank = new Map(
    (state.reconciliations || []).map(item => [item.bankTxId, item.lancId])
  );
  const reconByLanc = new Map(
    (state.reconciliations || []).map(item => [item.lancId, item.bankTxId])
  );
  const lancById = new Map((state.lancamentos || []).map(lanc => [lanc.id, lanc]));
  const bankMovementsAfterBalance = bankTxs.filter(tx =>
    isValidDateISO(tx.date)
    && tx.date > statement.balanceDate
    && tx.date <= todayISO
  );
  const expectedBankBalance = Number(statement.closingBalance)
    + bankMovementsAfterBalance.reduce((total, tx) => total + Number(tx.amount || 0), 0);
  const difference = Number(calculatedBalance || 0) - expectedBankBalance;
  const conta = state.contas.find(item => item.id === contaId);
  const initialDate = contaSaldoInicialEm(conta);
  const isInsideAuditPeriod = value =>
    isValidDateISO(value)
    && (!initialDate || value >= initialDate)
    && value <= todayISO;

  const unlinkedSystem = (state.lancamentos || []).filter(lanc =>
    lanc.contaId === contaId
    && !reconByLanc.has(lanc.id)
    && isInsideAuditPeriod(lanc.data)
  );
  const unlinkedBank = bankTxs.filter(tx =>
    !reconByBank.has(tx.id) && isInsideAuditPeriod(tx.date)
  );
  const divergentLinks = (state.reconciliations || []).flatMap(item => {
    const bankTx = bankById.get(item.bankTxId);
    const lanc = lancById.get(item.lancId);
    if(!bankTx || !lanc || lanc.contaId !== contaId) return [];
    const launchAmount = signedLancamentoValue(lanc);
    const bankAmount = Number(bankTx.amount || 0);
    if(Math.abs(launchAmount - bankAmount) < 0.005) return [];
    return [{ bankTx, lanc, difference: launchAmount - bankAmount }];
  });
  const knownDifference = unlinkedSystem.reduce(
    (total, lanc) => total + signedLancamentoValue(lanc),
    0
  ) - unlinkedBank.reduce((total, tx) => total + Number(tx.amount || 0), 0);
  const unexplainedDifference = difference - knownDifference;
  const referenceDayTxs = bankTxs.filter(tx =>
    tx.date === initialDate && reconByBank.has(tx.id)
  );
  let referenceCandidates = referenceDayTxs.filter(tx =>
    Math.abs(Number(tx.amount || 0) - unexplainedDifference) < 0.005
  );
  if(!referenceCandidates.length){
    for(let first = 0; first < referenceDayTxs.length; first++){
      for(let second = first + 1; second < referenceDayTxs.length; second++){
        const pairValue = Number(referenceDayTxs[first].amount || 0)
          + Number(referenceDayTxs[second].amount || 0);
        if(Math.abs(pairValue - unexplainedDifference) < 0.005){
          referenceCandidates = [referenceDayTxs[first], referenceDayTxs[second]];
          break;
        }
      }
      if(referenceCandidates.length) break;
    }
  }

  const reasons = [];
  for(const lanc of unlinkedSystem){
    reasons.push({
      kind: "system",
      date: lanc.data,
      description: lanc.desc || "Lançamento do sistema",
      amount: signedLancamentoValue(lanc),
      detail: "sem vínculo bancário"
    });
  }
  for(const tx of unlinkedBank){
    reasons.push({
      kind: "bank",
      date: tx.date,
      description: tx.memo || "Transação do banco",
      amount: Number(tx.amount || 0),
      detail: "existe no banco e está sem vínculo"
    });
  }
  for(const item of divergentLinks){
    reasons.push({
      kind: "value",
      date: item.bankTx.date,
      description: item.bankTx.memo || item.lanc.desc || "Vínculo com valor diferente",
      amount: item.difference,
      detail: `banco ${brl(item.bankTx.amount)} · sistema ${brl(signedLancamentoValue(item.lanc))}`
    });
  }
  for(const tx of referenceCandidates){
    const lanc = lancById.get(reconByBank.get(tx.id));
    reasons.push({
      kind: "reference",
      date: tx.date,
      description: tx.memo || lanc?.desc || "Movimento na data do saldo inicial",
      amount: Number(tx.amount || 0),
      detail: "provavelmente já está incluído no saldo inicial"
    });
  }

  return {
    expectedBankBalance,
    calculatedBalance: Number(calculatedBalance || 0),
    difference,
    statementDate: statement.balanceDate,
    reasons
  };
}

function isTituloAberto(titulo){
  return (titulo?.status || "ABERTO") === "ABERTO";
}

function selectedContaIds(selection){
  if(selection && selection !== "ALL") return [selection];
  return state.contas.map(conta => conta.id);
}

function emptyFinanceStatus(){
  return {
    receitasMes: 0,
    despesasMes: 0,
    saldoAtual: 0,
    receitasFuturas: 0,
    despesasFuturas: 0,
    receitasFuturasMes: 0,
    despesasFuturasMes: 0,
    apAbertoMes: 0,
    arAbertoMes: 0,
    apAbertoTotal: 0,
    arAbertoTotal: 0,
    apVencido: 0,
    arVencido: 0
  };
}

function finishFinanceStatus(status){
  return {
    ...status,
    resultadoRealizadoMes: status.receitasMes - status.despesasMes,
    resultadoPrevistoMes: status.receitasMes
      + status.receitasFuturasMes
      + status.arAbertoMes
      - status.despesasMes
      - status.despesasFuturasMes
      - status.apAbertoMes,
    saldoPrevisto: status.saldoAtual
      + status.receitasFuturas
      - status.despesasFuturas
      + status.arAbertoTotal
      - status.apAbertoTotal
  };
}

function calcContaFinanceStatus(contaId, mes, todayISO=toISODate(new Date())){
  const conta = state.contas.find(c => c.id === contaId);
  const [year, month] = String(mes || "").split("-").map(Number);
  const status = emptyFinanceStatus();

  if(!conta) return finishFinanceStatus(status);

  const reconciledBankTxs = reconciledBankTransactionsByLancamento(contaId);
  status.saldoAtual = Number(conta.saldoInicial || 0);
  const saldoInicialEm = contaSaldoInicialEm(conta);

  for(const lanc of state.lancamentos){
    if(lanc.contaId !== contaId) continue;
    const bankTx = reconciledBankTxs.get(lanc.id);
    const dataMovimento = bankTx?.date || lanc.data;
    const valor = bankTx
      ? Math.abs(Number(bankTx.amount || 0))
      : Number(lanc.valor || 0);
    const isReceita = bankTx
      ? Number(bankTx.amount || 0) >= 0
      : lanc.tipo === "RECEITA";
    const isTransferencia = isTransferenciaLancamento(lanc);
    const isLancamentoMes = isSameMonthISO(dataMovimento, year, month);
    const isLancamentoRealizado = isValidDateISO(dataMovimento) && dataMovimento <= todayISO;
    const isAposSaldoInicial = !saldoInicialEm || dataMovimento >= saldoInicialEm;

    // O saldo da conta e acumulado: o filtro mensal limita apenas os
    // indicadores do periodo. O saldo inicial representa a abertura da data
    // informada; movimentos anteriores ficam no historico sem serem reaplicados.
    if(isLancamentoRealizado && isAposSaldoInicial){
      status.saldoAtual += isReceita ? valor : -valor;
    }else if(!isLancamentoRealizado && isLancamentoMes && isValidDateISO(lanc.data) && isAposSaldoInicial){
      if(isReceita) status.receitasFuturas += valor;
      else status.despesasFuturas += valor;
      if(!isTransferencia){
        if(isReceita) status.receitasFuturasMes += valor;
        else status.despesasFuturasMes += valor;
      }
    }

    if(!isTransferencia && isLancamentoMes && isLancamentoRealizado){
      if(isReceita) status.receitasMes += valor;
      else status.despesasMes += valor;
    }
  }

  for(const titulo of state.titulos){
    if(titulo.contaId !== contaId || !isTituloAberto(titulo)) continue;
    if(!isSameMonthISO(titulo.vencimento, year, month)) continue;
    const valor = Number(titulo.valor || 0);
    const isAP = titulo.tipo === "AP";

    if(isAP) status.apAbertoTotal += valor;
    else status.arAbertoTotal += valor;

    if(isValidDateISO(titulo.vencimento) && titulo.vencimento < todayISO){
      if(isAP) status.apVencido += valor;
      else status.arVencido += valor;
    }

    if(isAP) status.apAbertoMes += valor;
    else status.arAbertoMes += valor;
  }

  return finishFinanceStatus(status);
}

function aggregateFinanceStatus(statuses){
  const total = emptyFinanceStatus();
  for(const status of statuses){
    total.receitasMes += status.receitasMes;
    total.despesasMes += status.despesasMes;
    total.saldoAtual += status.saldoAtual;
    total.receitasFuturas += status.receitasFuturas;
    total.despesasFuturas += status.despesasFuturas;
    total.receitasFuturasMes += status.receitasFuturasMes;
    total.despesasFuturasMes += status.despesasFuturasMes;
    total.apAbertoMes += status.apAbertoMes;
    total.arAbertoMes += status.arAbertoMes;
    total.apAbertoTotal += status.apAbertoTotal;
    total.arAbertoTotal += status.arAbertoTotal;
    total.apVencido += status.apVencido;
    total.arVencido += status.arVencido;
  }
  return finishFinanceStatus(total);
}

function buildCategoriaTotals(lancamentos){
  const byCat = new Map();

  for(const lanc of lancamentos){
    if(isTransferenciaLancamento(lanc)) continue;
    const valor = Math.abs(Number(lanc.valor || 0));
    const isReceita = lanc.tipo === "RECEITA";
    const ids = getLancCategoriaIds(lanc);
    const targetIds = ids.length ? ids : ["__sem_categoria__"];

    for(const categoriaId of targetIds){
      if(!byCat.has(categoriaId)){
        const cat = state.categorias.find(c => c.id === categoriaId);
        byCat.set(categoriaId, {
          id: categoriaId,
          nome: cat?.nome || "Sem categoria",
          tipo: cat?.tipo || lanc.tipo || "DESPESA",
          receitas: 0,
          despesas: 0
        });
      }
      const item = byCat.get(categoriaId);
      if(isReceita) item.receitas += valor;
      else item.despesas += valor;
    }
  }

  return Array.from(byCat.values())
    .map(item => ({ ...item, saldo: item.receitas - item.despesas, total: item.receitas + item.despesas }))
    .sort((a,b)=> Math.abs(b.total) - Math.abs(a.total) || a.nome.localeCompare(b.nome));
}

function renderCategoriasDashboard(lancamentos){
  const totals = buildCategoriaTotals(lancamentos);
  $("#boxCategoriasMes").innerHTML = totals.length ? totals.map(item=>{
    const hasBoth = item.receitas > 0 && item.despesas > 0;
    const primaryValue = hasBoth ? item.saldo : (item.receitas || item.despesas);
    const valueClass = hasBoth
      ? (item.saldo >= 0 ? "ok" : "bad")
      : (item.receitas > 0 ? "ok" : "bad");
    const details = hasBoth
      ? `Receitas ${brl(item.receitas)} · Despesas ${brl(item.despesas)}`
      : (item.receitas > 0 ? "Receita" : "Despesa");
    return `
      <div class="item categoryTotalItem">
        <div>
          <b>${escapeHtml(item.nome)}</b>
          <div class="muted">${escapeHtml(details)}</div>
        </div>
        <span class="badge ${valueClass}">${brl(primaryValue)}</span>
      </div>
    `;
  }).join("") : `<div class="muted">Sem valores por categoria no mês selecionado.</div>`;
}

function renderDashboard(){
  const selConta = $("#dashConta").value || "ALL";
  if(!$("#dashMes").value) $("#dashMes").value = toISODate(new Date()).slice(0,7);
  const mes = $("#dashMes").value;

  const [y,m] = mes.split("-").map(Number);
  const perAccount = state.contas.map(conta => ({
    conta,
    status: calcContaFinanceStatus(conta.id, mes)
  }));
  const scopeIds = new Set(selectedContaIds(selConta));
  const scopedStatus = aggregateFinanceStatus(
    perAccount.filter(item => scopeIds.has(item.conta.id)).map(item => item.status)
  );

  const lancs = state.lancamentos.filter(l => {
    if(selConta !== "ALL" && l.contaId !== selConta) return false;
    return isSameMonthISO(l.data, y, m);
  });

  $("#kpiReceitas").textContent = brl(scopedStatus.receitasMes);
  $("#kpiDespesas").textContent = brl(scopedStatus.despesasMes);
  $("#kpiSaldoMes").textContent = brl(scopedStatus.resultadoRealizadoMes);
  $("#kpiSaldoConta").textContent = brl(scopedStatus.saldoAtual);
  $("#kpiAPAberto").textContent = brl(scopedStatus.apAbertoMes);
  $("#kpiARAberto").textContent = brl(scopedStatus.arAbertoMes);
  $("#kpiPrevistoMes").textContent = brl(scopedStatus.resultadoPrevistoMes);
  $("#kpiSaldoPrevisto").textContent = brl(scopedStatus.saldoPrevisto);

  $("#boxStatusContas").innerHTML = perAccount.length ? perAccount.map(({ conta, status })=>{
    const selectedClass = selConta === conta.id ? " selected" : "";
    const saldoInicialEm = contaSaldoInicialEm(conta);
    const balanceAudit = buildAccountBalanceAudit(conta.id, status.saldoAtual);
    const overdue = status.apVencido > 0
      ? `<span class="badge bad">Vencido ${brl(status.apVencido)}</span>`
      : `<span class="badge ok">Em dia</span>`;
    const auditMatches = balanceAudit && Math.abs(balanceAudit.difference) < 0.005;
    const auditBadge = !balanceAudit
      ? `<span class="badge warn">Sem saldo bancário para conferir</span>`
      : auditMatches
        ? `<span class="badge ok">Saldo confere com o banco</span>`
        : `<span class="badge bad">Diferença ${brl(balanceAudit.difference)}</span>`;
    const auditDetails = !balanceAudit
      ? `<div class="accountBalanceAudit muted">Importe um extrato com saldo final para habilitar a conferência independente.</div>`
      : auditMatches
        ? `<div class="accountBalanceAudit okText">Calculado ${brl(status.saldoAtual)} · banco ${brl(balanceAudit.expectedBankBalance)}</div>`
        : `
          <div class="accountBalanceAudit badText">
            <b>Calculado ${brl(status.saldoAtual)} · banco ${brl(balanceAudit.expectedBankBalance)}</b>
            ${balanceAudit.reasons.length ? `
              <div class="muted">Lançamentos que precisam de revisão:</div>
              <ul>${balanceAudit.reasons.slice(0, 5).map(reason => `
                <li>${escapeHtml(reason.date || "-")} · ${escapeHtml(reason.description)} · ${brl(reason.amount)} (${escapeHtml(reason.detail)})</li>
              `).join("")}</ul>
              ${balanceAudit.reasons.length > 5 ? `<div class="muted">E mais ${balanceAudit.reasons.length - 5} item(ns).</div>` : ""}
            ` : `<div class="muted">Não há movimento sem vínculo após o último saldo bancário. Revise o saldo inicial e sua data de referência.</div>`}
          </div>
        `;
    return `
      <div class="item accountStatusItem${selectedClass}">
        <div class="accountStatusHead">
          <div>
            <b>${escapeHtml(conta.nome || "Conta")}</b>
            <div class="muted">${escapeHtml(conta.moeda || "BRL")} · saldo inicial ${brl(conta.saldoInicial)}${saldoInicialEm ? ` em ${escapeHtml(saldoInicialEm)}` : ""}</div>
          </div>
          <div class="accountStatusBadges">${auditBadge}${overdue}</div>
        </div>
        <div class="accountStatusMetrics">
          <div>
            <span class="muted">Atual</span>
            <b>${brl(status.saldoAtual)}</b>
          </div>
          <div>
            <span class="muted">Previsto</span>
            <b>${brl(status.saldoPrevisto)}</b>
          </div>
          <div>
            <span class="muted">A pagar</span>
            <b>${brl(status.apAbertoTotal)}</b>
          </div>
          <div>
            <span class="muted">A receber</span>
            <b>${brl(status.arAbertoTotal)}</b>
          </div>
        </div>
        ${auditDetails}
      </div>
    `;
  }).join("") : `<div class="muted">Nenhuma conta cadastrada.</div>`;

  const contas = state.contas;
  const rows = buildLancamentoRows(lancs);
  $("#boxLancamentosMes").innerHTML = rows.length ? rows.map(row=>{
    if(row.kind === "transferencia"){
      const origem = contas.find(c=>c.id===row.origem?.contaId);
      const destino = contas.find(c=>c.id===row.destino?.contaId);
      return `
        <div class="item">
          <div>
            <b>${escapeHtml(row.desc || "Transferência entre contas")}</b>
            <div class="muted">${escapeHtml(row.data || "-")} · ${escapeHtml(origem?.nome || "Origem")} -> ${escapeHtml(destino?.nome || "Destino")}</div>
          </div>
          <span class="badge transfer">${brl(row.valor)}</span>
        </div>
      `;
    }
    const l = row.lanc;
    const conta = contas.find(c=>c.id===l.contaId);
    const valueClass = l.tipo === "RECEITA" ? "ok" : "bad";
    return `
      <div class="item">
        <div>
          <b>${escapeHtml(l.desc || "Sem descrição")}</b>
          <div class="muted">${escapeHtml(l.data || "-")} · ${escapeHtml(conta?.nome || "Conta")} · ${escapeHtml(categoriaNamesText(getLancCategoriaIds(l)))}</div>
        </div>
        <span class="badge ${valueClass}">${brl(Number(l.valor || 0))}</span>
      </div>
    `;
  }).join("") : `<div class="muted">Sem lançamentos no mês selecionado.</div>`;

  renderCategoriasDashboard(lancs);

  const titulosMes = state.titulos
    .filter(t => {
      if(selConta !== "ALL" && t.contaId !== selConta) return false;
      return isTituloAberto(t) && isSameMonthISO(t.vencimento, y, m);
    })
    .slice()
    .sort((a,b)=> String(a.vencimento || "").localeCompare(String(b.vencimento || "")));

  $("#boxTitulosMes").innerHTML = titulosMes.length ? titulosMes.map(t=>{
    const conta = contas.find(c=>c.id===t.contaId);
    const isAR = t.tipo === "AR";
    const badgeClass = isAR ? "ok" : "bad";
    const tipoLabel = isAR ? "AR" : "AP";
    const desc = tituloDescricaoText(t, "Sem descrição");
    return `
      <div class="item">
        <div>
          <b>${escapeHtml(desc)}</b>
          <div class="muted">${escapeHtml(t.vencimento || "-")} · ${escapeHtml(conta?.nome || "Conta")} · ${escapeHtml(t.pessoa || "-")}</div>
          ${categoriaBadgesHtml(getTituloCategoriaIds(t), "-")}
        </div>
        <div style="text-align:right">
          <span class="badge ${badgeClass}">${tipoLabel}</span>
          <div><b>${brl(Number(t.valor || 0))}</b></div>
        </div>
      </div>
    `;
  }).join("") : `<div class="muted">Sem títulos em aberto no mês selecionado.</div>`;
}

$("#btnHoje").addEventListener("click", ()=>{
  $("#dashMes").value = toISODate(new Date()).slice(0,7);
  renderDashboard();
});
$("#btnImprimirDashboard").addEventListener("click", printDashboardReport);
$("#dashConta").addEventListener("change", renderDashboard);
$("#dashMes").addEventListener("change", renderDashboard);

/* ---------- Lançamentos ---------- */
let editLancId = null;
let editTransferenciaId = null;

function filteredLancamentos(){
  const conta = $("#fConta").value || "ALL";
  const ini = $("#fIni").value;
  const fim = $("#fFim").value;
  const busca = ($("#fBusca").value || "").trim().toLowerCase();

  let list = [...state.lancamentos];

  if(conta !== "ALL") list = list.filter(l => l.contaId === conta);
  if(ini) list = list.filter(l => l.data >= ini);
  if(fim) list = list.filter(l => l.data <= fim);
  if(busca) list = list.filter(l => (l.desc || "").toLowerCase().includes(busca));

  return list;
}

function lancamentosTotals(list){
  let receitas = 0;
  let despesas = 0;
  for(const lanc of list){
    if(isTransferenciaLancamento(lanc)) continue;
    const valor = Math.abs(Number(lanc.valor || 0));
    if(lanc.tipo === "RECEITA") receitas += valor;
    else despesas += valor;
  }
  return { receitas, despesas, saldo: receitas - despesas };
}

function excelXmlText(value){
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function excelStringCell(value, style=""){
  const styleAttr = style ? ` ss:StyleID="${style}"` : "";
  return `<Cell${styleAttr}><Data ss:Type="String">${excelXmlText(value)}</Data></Cell>`;
}

function excelNumberCell(value, style="Money"){
  const number = Number(value || 0);
  return `<Cell ss:StyleID="${style}"><Data ss:Type="Number">${Number.isFinite(number) ? number : 0}</Data></Cell>`;
}

function exportarLancamentosExcel(){
  const list = filteredLancamentos();
  const rows = buildLancamentoRows(list);
  if(!rows.length){
    alert("Não há lançamentos no filtro atual para exportar.");
    return;
  }

  const contaById = new Map(state.contas.map(conta => [conta.id, conta]));
  const totals = lancamentosTotals(list);
  const detailRows = rows.map(row => {
    if(row.kind === "transferencia"){
      const origem = contaById.get(row.origem?.contaId)?.nome || "Origem";
      const destino = contaById.get(row.destino?.contaId)?.nome || "Destino";
      const conciliado = (row.entries || []).some(item => item?.conciliado || item?.bankTxId) ? "Sim" : "Não";
      return `<Row>${[
        excelStringCell(row.data),
        excelStringCell(`${origem} -> ${destino}`),
        excelStringCell("TRANSFERÊNCIA"),
        excelStringCell(""),
        excelStringCell(row.desc || "Transferência entre contas"),
        excelNumberCell(row.valor),
        excelStringCell(conciliado)
      ].join("")}</Row>`;
    }

    const lanc = row.lanc;
    return `<Row>${[
      excelStringCell(lanc.data),
      excelStringCell(contaById.get(lanc.contaId)?.nome || "-"),
      excelStringCell(lanc.tipo === "RECEITA" ? "RECEITA" : "DESPESA"),
      excelStringCell(categoriaNamesText(getLancCategoriaIds(lanc), "-")),
      excelStringCell(lanc.desc || ""),
      excelNumberCell(Math.abs(Number(lanc.valor || 0))),
      excelStringCell(lanc.conciliado || lanc.bankTxId ? "Sim" : "Não")
    ].join("")}</Row>`;
  }).join("");

  const summaryRows = [
    ["Receitas", totals.receitas],
    ["Despesas", totals.despesas],
    ["Saldo", totals.saldo]
  ].map(([label, value]) => `<Row>${excelStringCell(label, "Header")}${excelNumberCell(value)}</Row>`).join("");

  const workbook = `<?xml version="1.0" encoding="UTF-8"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
 <Styles>
  <Style ss:ID="Header"><Font ss:Bold="1"/><Interior ss:Color="#D9EAF7" ss:Pattern="Solid"/></Style>
  <Style ss:ID="Money"><NumberFormat ss:Format="Currency"/></Style>
 </Styles>
 <Worksheet ss:Name="Lancamentos"><Table>
  <Column ss:Width="80"/><Column ss:Width="140"/><Column ss:Width="90"/>
  <Column ss:Width="140"/><Column ss:Width="240"/><Column ss:Width="90"/><Column ss:Width="75"/>
  <Row>${["Data", "Conta", "Tipo", "Categoria", "Descrição", "Valor", "Conciliado"].map(value => excelStringCell(value, "Header")).join("")}</Row>
  ${detailRows}
  <Row/>
  ${summaryRows}
 </Table></Worksheet>
</Workbook>`;

  const blob = new Blob([workbook], { type: "application/vnd.ms-excel;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const periodo = $("#fIni").value || $("#fFim").value
    ? `${$("#fIni").value || "inicio"}_${$("#fFim").value || "fim"}`
    : toISODate(new Date()).slice(0, 7);
  link.href = url;
  link.download = `lancamentos_${periodo}.xls`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function renderLancamentos(){
  const list = filteredLancamentos();
  const totals = lancamentosTotals(list);
  const rows = buildLancamentoRows(list);

  $("#totalLancReceitas").textContent = brl(totals.receitas);
  $("#totalLancDespesas").textContent = brl(totals.despesas);
  $("#totalLancSaldo").textContent = brl(totals.saldo);
  $("#totalLancSaldo").className = totals.saldo >= 0 ? "ok" : "bad";
  $("#totalLancRegistros").textContent = String(rows.length);

  const contaById = new Map(state.contas.map(c=>[c.id,c]));

  $("#tbLanc").innerHTML = rows.map(row=>{
    if(row.kind === "transferencia"){
      const origem = contaById.get(row.origem?.contaId);
      const destino = contaById.get(row.destino?.contaId);
      return `
        <tr>
          <td>${escapeHtml(row.data)}</td>
          <td>${escapeHtml(origem?.nome || "Origem")} -> ${escapeHtml(destino?.nome || "Destino")}</td>
          <td><span class="badge transfer">TRANSFERÊNCIA</span></td>
          <td>Transferência entre contas</td>
          <td>${escapeHtml(row.desc || "")}</td>
          <td class="right"><b>${brl(row.valor)}</b></td>
          <td><span class="badge">${row.entries.reduce((total, item) => total + (item.anexos?.length || 0), 0)}</span></td>
          <td>${transferenciaConciliacaoBadge(row.entries)}</td>
          <td class="right">
            <button class="btn" data-act="edit" data-id="${row.id}">Editar</button>
            <button class="btn danger" data-act="del-transfer" data-id="${row.transferenciaId}">Excluir</button>
          </td>
        </tr>
      `;
    }
    const l = row.lanc;
    const c = contaById.get(l.contaId);
    const conc = l.conciliado ? `<span class="badge ok">Sim</span>` : `<span class="badge warn">Não</span>`;
    const tipoBadge = lancamentoTipoBadge(l);
    return `
      <tr>
        <td>${escapeHtml(l.data)}</td>
        <td>${escapeHtml(c?.nome || "-")}</td>
        <td>${tipoBadge}</td>
        <td>${categoriaBadgesHtml(getLancCategoriaIds(l), "-")}</td>
        <td>${escapeHtml(l.desc || "")}</td>
        <td class="right"><b>${brl(l.valor)}</b></td>
        <td>${l.anexos?.length ? `<button class="btn" data-act="attachments" data-id="${l.id}">Ver ${l.anexos.length}</button>` : `<span class="muted">0</span>`}</td>
        <td>${conc}</td>
        <td class="right">
          <button class="btn" data-act="edit" data-id="${l.id}">Editar</button>
          <button class="btn danger" data-act="del" data-id="${l.id}">Excluir</button>
        </td>
      </tr>
    `;
  }).join("") || `<tr><td colspan="9" class="muted">Nenhum lançamento.</td></tr>`;
}

$("#btnFiltrar").addEventListener("click", renderLancamentos);
$("#btnExportarLanc").addEventListener("click", exportarLancamentosExcel);
$("#btnNovoLanc").addEventListener("click", ()=> openLancModal(null));

async function removeLancamentosFromState(lancamentoId, { deleteSourceTitles=false }={}){
  const lancamento = state.lancamentos.find(item => item.id === lancamentoId);
  if(!lancamento) return { removed: 0, reopenedTitles: 0, deletedTitles: 0, transfer: false };
  const entries = lancamento.transferenciaId
    ? state.lancamentos.filter(item => item.transferenciaId === lancamento.transferenciaId)
    : [lancamento];
  const ids = new Set(entries.map(item => item.id));
  const sourceTitles = state.titulos.filter(titulo => ids.has(titulo.lancId));
  const deletableTitles = deleteSourceTitles
    ? sourceTitles.filter(titulo => !getCompraByTituloId(titulo.id))
    : [];
  const deletableTitleIds = new Set(deletableTitles.map(titulo => titulo.id));
  const attachments = [
    ...entries.flatMap(item => item.anexos || []),
    ...deletableTitles.flatMap(titulo => titulo.anexos || [])
  ];
  let reopenedTitles = 0;

  state.reconciliations = state.reconciliations.filter(item => !ids.has(item.lancId));
  for(const titulo of state.titulos){
    if(!ids.has(titulo.lancId)) continue;
    if(deletableTitleIds.has(titulo.id)) continue;
    titulo.lancId = null;
    titulo.baixadoEm = null;
    if(titulo.status === "BAIXADO"){
      titulo.status = "ABERTO";
      reopenedTitles++;
    }
  }
  if(deletableTitleIds.size){
    state.titulos = state.titulos.filter(titulo => !deletableTitleIds.has(titulo.id));
  }
  state.lancamentos = state.lancamentos.filter(item => !ids.has(item.id));
  await Promise.allSettled(attachments.map(removeTituloAttachmentFile));
  return {
    removed: ids.size,
    reopenedTitles,
    deletedTitles: deletableTitleIds.size,
    transfer: !!lancamento.transferenciaId
  };
}

function unlinkedLancamentoDeletionPlan(contaId){
  const linkedLancIds = new Set(state.reconciliations.map(item => item.lancId));
  const candidates = state.lancamentos.filter(item =>
    item.contaId === contaId && !linkedLancIds.has(item.id)
  );
  const roots = [];
  const selectedEntries = [];
  const removedIds = new Set();
  const handledTransfers = new Set();
  const skippedTransfers = new Set();

  for(const lancamento of candidates){
    if(!lancamento.transferenciaId){
      roots.push(lancamento.id);
      selectedEntries.push(lancamento);
      removedIds.add(lancamento.id);
      continue;
    }

    const transferenciaId = lancamento.transferenciaId;
    if(handledTransfers.has(transferenciaId) || skippedTransfers.has(transferenciaId)) continue;
    const entries = getTransferenciaEntries(transferenciaId);
    if(entries.some(item => linkedLancIds.has(item.id))){
      skippedTransfers.add(transferenciaId);
      continue;
    }

    handledTransfers.add(transferenciaId);
    roots.push(lancamento.id);
    selectedEntries.push(...entries.filter(item => item.contaId === contaId));
    for(const entry of entries) removedIds.add(entry.id);
  }

  const netImpact = selectedEntries.reduce((total, item) =>
    total + (item.tipo === "RECEITA" ? Number(item.valor || 0) : -Number(item.valor || 0)), 0
  );
  const sourceTitles = state.titulos.filter(titulo => removedIds.has(titulo.lancId));
  const deletedTitles = sourceTitles.filter(titulo => !getCompraByTituloId(titulo.id)).length;
  const reopenedTitles = sourceTitles.filter(titulo =>
    getCompraByTituloId(titulo.id) && titulo.status === "BAIXADO"
  ).length;

  return {
    roots,
    selectedCount: selectedEntries.length,
    removedCount: removedIds.size,
    netImpact,
    reopenedTitles,
    deletedTitles,
    transferCount: handledTransfers.size,
    skippedTransferCount: skippedTransfers.size
  };
}

$("#tbLanc").addEventListener("click", async (e)=>{
  const btn = e.target.closest("button");
  if(!btn) return;
  const id = btn.dataset.id;
  const act = btn.dataset.act;
  if(act === "edit"){
    openLancModal(id);
  } else if(act === "attachments"){
    openLancModal(id);
    const first = currentLancamentoForAttachment()?.anexos?.[0];
    if(first){
      previewLancAnexoId = first.id;
      renderLancAnexos();
      renderLancAnexoPreview(first);
    }
  } else if(act === "del-transfer"){
    if(confirm("Excluir esta transferência?")){
      const snapshot = cloneStateSnapshot();
      const entries = getTransferenciaEntries(id);
      if(entries[0]) await removeLancamentosFromState(entries[0].id);
      if(!await persistStateOrRollback(snapshot, { button: btn })) return;
      renderAll();
    }
  } else if(act === "del"){
    if(confirm("Excluir este lançamento?")){
      const snapshot = cloneStateSnapshot();
      await removeLancamentosFromState(id);
      if(!await persistStateOrRollback(snapshot, { button: btn })) return;
      renderAll();
    }
  }
});

let previewLancAnexoId = null;

function currentLancamentoForAttachment(){
  return editLancId ? state.lancamentos.find(item => item.id === editLancId) : null;
}

function renderLancAnexoPreview(anexo){
  const box = $("#lAnexoPreview");
  if(!anexo){
    box.textContent = "Selecione um anexo para visualizar.";
    return;
  }
  const src = filePreviewSrc(anexo);
  if(!src){
    box.textContent = "Arquivo sem URL de visualização.";
    return;
  }
  const mime = String(anexo.mime || "");
  if(mime.includes("pdf")){
    box.innerHTML = `<iframe src="${escapeHtml(src)}" style="width:100%;height:360px;border:0;border-radius:12px"></iframe>${attachmentCodeDetails(anexo)}`;
  }else if(mime.startsWith("image/")){
    box.innerHTML = `<img src="${escapeHtml(src)}" alt="anexo" style="max-width:100%;border-radius:12px" />`;
  }else{
    box.textContent = "Formato não suportado na prévia.";
  }
}

function renderLancAnexos(){
  const lancamento = currentLancamentoForAttachment();
  const anexos = lancamento?.anexos || [];
  $("#btnAddLancAnexo").disabled = false;
  $("#btnAddLancAnexo").textContent = lancamento ? "Adicionar anexo" : "Anexar ao salvar";
  $("#listaLancAnexos").innerHTML = anexos.length ? anexos.map(anexo => `
    <div class="item ${previewLancAnexoId===anexo.id ? "selected" : ""}">
      <div class="left" style="flex:1">
        <span class="badge">${String(anexo.mime || "").includes("pdf") ? "PDF" : "IMG"}</span>
        <div style="min-width:0"><b>${escapeHtml(anexo.name || "Anexo")}</b></div>
      </div>
      <div class="row gap">
        <button class="btn" data-act="view" data-id="${anexo.id}">Ver</button>
        <button class="btn danger" data-act="del" data-id="${anexo.id}">Remover</button>
      </div>
    </div>
  `).join("") : `<div class="muted">${lancamento ? "Nenhum anexo." : "Selecione o arquivo; ele será enviado junto com o novo lançamento."}</div>`;
}

function openLancModal(id){
  editLancId = id;
  editTransferenciaId = null;
  $("#modalLanc").classList.remove("hidden");
  $("#modalLancTitle").textContent = id ? "Editar lançamento" : "Novo lançamento";

  const l = id ? state.lancamentos.find(x=>x.id===id) : null;
  const isTransferencia = isTransferenciaLancamento(l);
  const partes = isTransferencia ? getTransferenciaPartes(l.transferenciaId) : { origem: null, destino: null };
  const origem = partes.origem || l;
  const destino = partes.destino || null;

  if(isTransferencia){
    editTransferenciaId = l.transferenciaId;
    $("#modalLancTitle").textContent = "Editar transferência";
  }

  $("#lData").value = origem?.data || l?.data || toISODate(new Date());
  $("#lConta").value = origem?.contaId || l?.contaId || (state.contas[0]?.id || "");
  $("#lContaDestino").value = destino?.contaId || state.contas.find(c => c.id !== $("#lConta").value)?.id || "";
  $("#lTipo").value = isTransferencia ? TRANSFERENCIA_TIPO : (l?.tipo || "DESPESA");
  fillSelects();
  $("#lConta").value = origem?.contaId || l?.contaId || $("#lConta").value;
  $("#lContaDestino").value = destino?.contaId || $("#lContaDestino").value;
  if(isTransferencia) setSelectValues("#lCategoria", []);
  else setSelectValues("#lCategoria", getLancCategoriaIds(l), $("#lCategoria").options[0]?.value || "");
  $("#lDesc").value = origem?.desc || l?.desc || "";
  $("#lValor").value = (origem || l) ? Number((origem || l).valor || 0) : "";
  $("#lConc").value = (partes.entries || [l]).some(item => item?.conciliado || item?.bankTxId) ? "1" : "0";
  previewLancAnexoId = null;
  $("#lAnexoFile").value = "";
  renderLancAnexos();
  renderLancAnexoPreview(null);
  updateLancModalMode();
}
function closeLancModal(){
  $("#modalLanc").classList.add("hidden");
  editLancId = null;
  editTransferenciaId = null;
  previewLancAnexoId = null;
}

function updateLancModalMode(){
  const isTransferencia = $("#lTipo").value === TRANSFERENCIA_TIPO;
  $("#lContaLabel").textContent = isTransferencia ? "Conta origem" : "Conta";
  $("#lContaDestinoWrap").classList.toggle("hidden", !isTransferencia);
  $("#lCategoriaWrap").classList.toggle("hidden", isTransferencia);
  $("#lCategoria").disabled = isTransferencia;
  $("#lContaDestino").disabled = !isTransferencia;

  if(!isTransferencia) return;
  const origemId = $("#lConta").value;
  const destinoEl = $("#lContaDestino");
  if(!destinoEl.value || destinoEl.value === origemId){
    const destino = state.contas.find(c => c.id !== origemId);
    if(destino) destinoEl.value = destino.id;
  }
}

$("#btnFecharModalLanc").addEventListener("click", closeLancModal);
$("#btnCancelarLanc").addEventListener("click", closeLancModal);
$("#modalLanc").addEventListener("click",(e)=>{ if(e.target.id==="modalLanc") closeLancModal(); });

$("#btnAddLancAnexo").addEventListener("click", async (event)=>{
  const lancamento = currentLancamentoForAttachment();
  const file = $("#lAnexoFile").files?.[0];
  if(!file) return alert("Selecione um PDF ou imagem.");
  if(file.size > 15 * 1024 * 1024) return alert("Arquivo muito grande. Use até 15 MB por anexo.");
  if(!lancamento){
    const previewUrl = URL.createObjectURL(file);
    renderLancAnexoPreview({ name: file.name, mime: file.type || "application/pdf", url: previewUrl });
    $("#listaLancAnexos").innerHTML = `<div class="item"><b>${escapeHtml(file.name)}</b><span class="badge warn">Será anexado ao salvar</span></div>`;
    return;
  }

  let uploaded = null;
  try{
    uploaded = await uploadFinanceAttachment(file, {
      data: lancamento.data,
      contaId: lancamento.contaId,
      descricao: lancamento.desc
    });
    if(!uploaded) throw new Error("Upload não retornou os dados do anexo.");
    const snapshot = cloneStateSnapshot();
    if(!Array.isArray(lancamento.anexos)) lancamento.anexos = [];
    lancamento.anexos.push(uploaded);
    if(!await persistStateOrRollback(snapshot, { button: event.currentTarget })){
      await removeTituloAttachmentFile(uploaded);
      return;
    }
    $("#lAnexoFile").value = "";
    previewLancAnexoId = uploaded.id;
    renderLancAnexos();
    renderLancAnexoPreview(uploaded);
    renderLancamentos();
  }catch(err){
    alert(err?.message || "Não foi possível enviar o anexo.");
  }
});

$("#listaLancAnexos").addEventListener("click", async (event)=>{
  const button = event.target.closest("button");
  if(!button) return;
  const lancamento = currentLancamentoForAttachment();
  if(!lancamento) return;
  const anexo = (lancamento.anexos || []).find(item => item.id === button.dataset.id);
  if(!anexo) return;
  if(button.dataset.act === "view"){
    previewLancAnexoId = anexo.id;
    renderLancAnexos();
    renderLancAnexoPreview(anexo);
    return;
  }
  if(button.dataset.act !== "del" || !confirm(`Remover o anexo ${anexo.name || "selecionado"}?`)) return;

  const snapshot = cloneStateSnapshot();
  lancamento.anexos = (lancamento.anexos || []).filter(item => item.id !== anexo.id);
  try{
    await removeTituloAttachmentFile(anexo);
  }catch(err){
    console.warn("Falha ao remover arquivo físico do anexo.", err);
  }
  if(!await persistStateOrRollback(snapshot, { button })) return;
  previewLancAnexoId = null;
  renderLancAnexos();
  renderLancAnexoPreview(null);
  renderLancamentos();
});

document.addEventListener("keydown",(e)=>{
  if(e.key !== "Escape") return;
  if(!$("#modalCodigoPagamento")?.classList.contains("hidden")) closePaymentCodeModal();
  if(!$("#modalFavorecido")?.classList.contains("hidden")) closeFavorecidoModal();
  if(!$("#modalLanc").classList.contains("hidden")) closeLancModal();
  if(!$("#modalConta").classList.contains("hidden")) closeContaModal();
  if(!$("#modalTitulo").classList.contains("hidden")) closeTituloModal();
});

$("#btnSalvarLanc").addEventListener("click", async (e)=>{
  const data = $("#lData").value;
  const contaId = $("#lConta").value;
  const contaDestinoId = $("#lContaDestino").value;
  const tipo = $("#lTipo").value;
  const categoriaIds = getSelectValues("#lCategoria");
  const categoriaId = categoriaIds[0] || "";
  const desc = $("#lDesc").value.trim();
  const valor = Number($("#lValor").value);
  const conciliado = $("#lConc").value === "1";
  const btn = e.currentTarget;

  if(tipo === TRANSFERENCIA_TIPO){
    if(state.contas.length < 2){
      alert("Cadastre pelo menos duas contas para registrar uma transferência.");
      return;
    }
    if(!data || !contaId || !contaDestinoId || contaId === contaDestinoId || !Number.isFinite(valor) || valor<=0){
      alert("Informe data, conta origem, conta destino e valor positivo.");
      return;
    }
    if(editLancId && !editTransferenciaId && state.titulos.some(t => t.lancId === editLancId)){
      alert("Este lançamento está vinculado a um título. Para usar transferência, crie um novo lançamento.");
      return;
    }

    const snapshot = cloneStateSnapshot();
    const transferencia = salvarTransferenciaLancamento({
      data,
      contaOrigemId: contaId,
      contaDestinoId,
      desc,
      valor,
      conciliado
    });
    const pendingAttachment = $("#lAnexoFile").files?.[0] || null;
    let uploadedAttachment = null;
    if(pendingAttachment){
      try{
        uploadedAttachment = await uploadFinanceAttachment(pendingAttachment, { data, contaId, descricao: desc });
        if(!uploadedAttachment) throw new Error("O upload não retornou o anexo.");
        if(!Array.isArray(transferencia.origem.anexos)) transferencia.origem.anexos = [];
        transferencia.origem.anexos.push(uploadedAttachment);
      }catch(err){
        state = migrate(snapshot);
        alert(err?.message || "Não foi possível anexar o arquivo. A transferência não foi salva.");
        return;
      }
    }
    if(!await persistStateOrRollback(snapshot, { button: btn })){
      if(uploadedAttachment) await removeTituloAttachmentFile(uploadedAttachment);
      return;
    }
    closeLancModal();
    renderAll();
    return;
  }

  if(!data || !contaId || !tipo || !categoriaId || !desc || !Number.isFinite(valor) || valor<=0){
    alert("Preencha todos os campos corretamente.");
    return;
  }

  const snapshot = cloneStateSnapshot();
  let savedLancamento = null;
  if(editTransferenciaId){
    const entries = getTransferenciaEntries(editTransferenciaId);
    const keep = entries.find(l => l.id === editLancId) || entries.find(isTransferenciaOrigem) || entries[0] || null;
    const removedIds = new Set(entries.filter(l => l.id !== keep?.id).map(l => l.id));
    state.reconciliations = state.reconciliations.filter(r => !removedIds.has(r.lancId));
    state.lancamentos = state.lancamentos.filter(l => l.transferenciaId !== editTransferenciaId && l.id !== keep?.id);

    const base = keep ? { ...keep } : { id: uid("lanc") };
    delete base.transferenciaId;
    delete base.transferenciaLado;
    delete base.contaOrigemId;
    delete base.contaDestinoId;

    const normal = {
      ...base,
      data,
      contaId,
      tipo,
      categoriaId,
      categoriaIds,
      desc,
      valor,
      conciliado: !!(base.bankTxId || conciliado)
    };
    state.lancamentos.unshift(normal);
    savedLancamento = normal;
    syncTituloFromLancamento(normal);
  } else if(editLancId){
    const idx = state.lancamentos.findIndex(x=>x.id===editLancId);
    if(idx >= 0){
      const old = state.lancamentos[idx];
      state.lancamentos[idx] = { ...old, data, contaId, tipo, categoriaId, categoriaIds, desc, valor, conciliado };
      savedLancamento = state.lancamentos[idx];
      syncTituloFromLancamento(state.lancamentos[idx]);
    }
  } else {
    savedLancamento = { id: uid("lanc"), data, contaId, tipo, categoriaId, categoriaIds, desc, valor, conciliado, anexos: [] };
    state.lancamentos.unshift(savedLancamento);
  }
  const pendingAttachment = $("#lAnexoFile").files?.[0] || null;
  let uploadedAttachment = null;
  if(pendingAttachment && savedLancamento){
    try{
      uploadedAttachment = await uploadFinanceAttachment(pendingAttachment, { data, contaId, descricao: desc });
      if(!uploadedAttachment) throw new Error("O upload não retornou o anexo.");
      if(!Array.isArray(savedLancamento.anexos)) savedLancamento.anexos = [];
      savedLancamento.anexos.push(uploadedAttachment);
    }catch(err){
      state = migrate(snapshot);
      alert(err?.message || "Não foi possível anexar o arquivo. O lançamento não foi salvo.");
      return;
    }
  }
  if(!await persistStateOrRollback(snapshot, { button: btn })){
    if(uploadedAttachment) await removeTituloAttachmentFile(uploadedAttachment);
    return;
  }
  closeLancModal();
  renderAll();
});

/* ---------- Contas ---------- */
let editContaId = null;
let completeImportTargetId = null;

function renderContas(){
  $("#listaContas").innerHTML = state.contas.map(c=>{
    const saldoInicialEm = contaSaldoInicialEm(c);
    return `
      <div class="item">
        <div class="left">
          <span class="badge">${escapeHtml(c.moeda || "BRL")}</span>
          <div>
            <div><b>${escapeHtml(c.nome)}</b></div>
            <div class="muted">Saldo inicial: ${brl(c.saldoInicial)}${saldoInicialEm ? ` em ${escapeHtml(saldoInicialEm)}` : ""}</div>
          </div>
        </div>
        <div class="row gap">
          <button class="btn" data-act="edit" data-id="${c.id}">Editar</button>
          <button class="btn danger" data-act="del" data-id="${c.id}">Excluir</button>
        </div>
      </div>
    `;
  }).join("");

  renderFinanceImportsLists();
}

$("#btnNovaConta").addEventListener("click", ()=> openContaModal(null));

$("#listaContas").addEventListener("click", async (e)=>{
  const btn = e.target.closest("button");
  if(!btn) return;
  const id = btn.dataset.id;
  const act = btn.dataset.act;

  if(act === "edit") openContaModal(id);
  if(act === "del"){
    if(confirm("Excluir esta conta? (lançamentos, títulos e imports dessa conta também serão removidos)")){
      const snapshot = cloneStateSnapshot();
      state.lancamentos = state.lancamentos.filter(l =>
        l.contaId !== id && l.contaOrigemId !== id && l.contaDestinoId !== id
      );
      state.titulos = state.titulos.filter(t => t.contaId !== id);
      state.compras = state.compras.filter(c => c.contaId !== id);
      state.imports = state.imports.filter(i => i.contaId !== id);

      // remove reconciliations órfãos
      const lancIds = new Set(state.lancamentos.map(l=>l.id));
      const bankIds = new Set(state.imports.flatMap(i=>i.txs.map(t=>t.id)));
      state.reconciliations = state.reconciliations.filter(r => lancIds.has(r.lancId) && bankIds.has(r.bankTxId));

      state.contas = state.contas.filter(c => c.id !== id);
      if(state.contas.length === 0){
        state.contas.push({
          id: uid("conta"),
          nome: "Conta principal",
          moeda: "BRL",
          saldoInicial: 0,
          saldoInicialEm: toISODate(new Date())
        });
      }
      if(!await persistStateOrRollback(snapshot, { button: btn })) return;
      renderAll();
    }
  }
});

function financeImportRelatedSummary(importId){
  const imp = state.imports.find(item => item.id === importId);
  const bankIds = new Set((imp?.txs || []).map(item => item.id));
  const linkedLancIds = new Set(
    state.reconciliations
      .filter(item => bankIds.has(item.bankTxId))
      .map(item => item.lancId)
  );
  const lancamentos = state.lancamentos.filter(item =>
    linkedLancIds.has(item.id) || bankIds.has(item.bankTxId)
  );
  const lancIds = new Set(lancamentos.map(item => item.id));
  const titulos = state.titulos.filter(item =>
    bankIds.has(item.bankTxId) || (item.lancId && lancIds.has(item.lancId))
  );
  return { imp, bankIds, linkedLancIds, lancamentos, titulos };
}

function financeImportMoveConflicts(importId, targetAccountId){
  const summary = financeImportRelatedSummary(importId);
  if(!summary.imp || !targetAccountId || summary.imp.contaId === targetAccountId) return [];
  const fitids = new Set();
  const keys = new Set();
  for(const other of state.imports){
    if(other.id === importId || other.contaId !== targetAccountId) continue;
    for(const tx of other.txs || []){
      if(tx.fitid) fitids.add(tx.fitid);
      keys.add(bankTransactionKey(targetAccountId, tx));
    }
  }
  for(const ignored of state.ignoredBankTransactions || []){
    if(ignored.contaId !== targetAccountId) continue;
    if(ignored.fitid) fitids.add(ignored.fitid);
    keys.add(ignored.key || bankTransactionKey(targetAccountId, ignored));
  }
  return (summary.imp.txs || []).filter(tx =>
    (tx.fitid && fitids.has(tx.fitid)) || keys.has(bankTransactionKey(targetAccountId, tx))
  );
}

function moveFinanceImportAccount(importId, targetAccountId){
  const targetExists = state.contas.some(item => item.id === targetAccountId);
  const summary = financeImportRelatedSummary(importId);
  if(!summary.imp) throw new Error("Importação não encontrada.");
  if(!targetExists) throw new Error("Conta de destino não encontrada.");
  if(summary.imp.contaId === targetAccountId){
    return { movedTransactions: 0, movedLancamentos: 0, movedTitulos: 0, unlinkedTransfers: 0 };
  }
  const conflicts = financeImportMoveConflicts(importId, targetAccountId);
  if(conflicts.length){
    throw new Error(`A conta de destino já possui ${conflicts.length} transação(ões) deste extrato. Exclua o lote incorreto e confira as importações existentes antes de tentar novamente.`);
  }

  const transferLancIds = new Set(summary.lancamentos.filter(isTransferenciaLancamento).map(item => item.id));
  const transferBankIds = new Set(
    state.reconciliations
      .filter(item => summary.bankIds.has(item.bankTxId) && transferLancIds.has(item.lancId))
      .map(item => item.bankTxId)
  );
  state.reconciliations = state.reconciliations.filter(item =>
    !(transferBankIds.has(item.bankTxId) && transferLancIds.has(item.lancId))
  );

  let movedLancamentos = 0;
  let unlinkedTransfers = 0;
  for(const lancamento of summary.lancamentos){
    if(isTransferenciaLancamento(lancamento)){
      if(lancamento.bankTxId && summary.bankIds.has(lancamento.bankTxId)) lancamento.bankTxId = null;
      lancamento.conciliado = false;
      unlinkedTransfers++;
      continue;
    }
    lancamento.contaId = targetAccountId;
    movedLancamentos++;
  }

  let movedTitulos = 0;
  const movedTitleIds = new Set();
  for(const titulo of summary.titulos){
    titulo.contaId = targetAccountId;
    movedTitleIds.add(titulo.id);
    movedTitulos++;
  }
  for(const compra of state.compras || []){
    if(movedTitleIds.has(compra.titleId)) compra.contaId = targetAccountId;
  }

  summary.imp.contaId = targetAccountId;
  return {
    movedTransactions: summary.bankIds.size,
    movedLancamentos,
    movedTitulos,
    unlinkedTransfers
  };
}

function deleteFinanceImportFromState(importId){
  const summary = financeImportRelatedSummary(importId);
  if(!summary.imp) return { removedTransactions: 0, unlinkedLancamentos: 0, unlinkedTitulos: 0 };
  state.reconciliations = state.reconciliations.filter(item => !summary.bankIds.has(item.bankTxId));
  let unlinkedLancamentos = 0;
  for(const lancamento of state.lancamentos){
    if(!summary.bankIds.has(lancamento.bankTxId)) continue;
    lancamento.bankTxId = null;
    lancamento.conciliado = false;
    unlinkedLancamentos++;
  }
  let unlinkedTitulos = 0;
  for(const titulo of state.titulos){
    if(!summary.bankIds.has(titulo.bankTxId)) continue;
    titulo.bankTxId = null;
    unlinkedTitulos++;
  }
  state.imports = state.imports.filter(item => item.id !== importId);
  if(completeImportTargetId === importId) completeImportTargetId = null;
  return { removedTransactions: summary.bankIds.size, unlinkedLancamentos, unlinkedTitulos };
}

function renderFinanceImportsList(){
  return state.imports
    .slice()
    .sort((a,b)=> String(b.createdAt || "").localeCompare(String(a.createdAt || "")))
    .map(imp=>{
      const conta = state.contas.find(c=>c.id===imp.contaId);
      const accountOptions = state.contas.map(item =>
        `<option value="${escapeHtml(item.id)}" ${item.id === imp.contaId ? "selected" : ""}>${escapeHtml(item.nome)}</option>`
      ).join("");
      return `
        <div class="item" data-import-id="${escapeHtml(imp.id)}">
          <div class="left">
            <span class="badge">${escapeHtml(conta?.nome || "-")}</span>
            <div>
              <div><b>${escapeHtml(imp.fileName || "import.ofx")}</b></div>
              <div class="muted">${escapeHtml(imp.createdAt)} • ${(imp.txs || []).length} transações</div>
            </div>
          </div>
          <div class="row gap wrap importAccountActions">
            <button class="btn" data-act="useImport" data-id="${imp.id}">Conciliar</button>
            <button class="btn" data-act="completeImport" data-id="${imp.id}">Completar</button>
            <select data-role="importAccount" aria-label="Conta desta importação">${accountOptions}</select>
            <button class="btn" data-act="moveImport" data-id="${imp.id}">Trocar conta</button>
            <button class="btn danger" data-act="delImport" data-id="${imp.id}">Excluir lançamentos importados</button>
          </div>
        </div>
      `;
    }).join("") || `<div class="muted">Nenhuma importação ainda.</div>`;
}

function renderFinanceImportsLists(){
  const markup = renderFinanceImportsList();
  if($("#listaImports")) $("#listaImports").innerHTML = markup;
  if($("#listaImportsImportar")) $("#listaImportsImportar").innerHTML = markup;
}

async function handleFinanceImportAction(e){
  const btn = e.target.closest("button");
  if(!btn) return;
  const id = btn.dataset.id;
  const act = btn.dataset.act;

  if(act === "useImport"){
    setView("conciliacao");
    $("#concImport").value = id;
    renderConciliacao();
  }
  if(act === "completeImport"){
    const imp = state.imports.find(item => item.id === id);
    if(!imp) return;
    completeImportTargetId = imp.id;
    setView("importar");
    $("#ofxConta").value = imp.contaId;
    $("#ofxFile").value = "";
    alert("Selecione o extrato completo. As transações existentes serão mantidas e somente os dados que faltam serão acrescentados.");
    $("#ofxFile").click();
  }
  if(act === "moveImport"){
    const imp = state.imports.find(item => item.id === id);
    if(!imp) return;
    const targetAccountId = btn.closest(".item")?.querySelector('[data-role="importAccount"]')?.value || "";
    if(!targetAccountId || targetAccountId === imp.contaId){
      return alert("Selecione uma conta diferente para mover esta importação.");
    }
    const originName = state.contas.find(item => item.id === imp.contaId)?.nome || "conta atual";
    const targetName = state.contas.find(item => item.id === targetAccountId)?.nome || "conta de destino";
    const related = financeImportRelatedSummary(id);
    if(!confirm(
      `Trocar a importação ${imp.fileName || "do extrato"} de ${originName} para ${targetName}?\n\n` +
      `${related.bankIds.size} transação(ões), ${related.lancamentos.length} lançamento(s) e ${related.titulos.length} título(s) relacionados serão ajustados. Transferências já conciliadas serão desvinculadas para não alterar as duas contas da transferência.`
    )) return;
    const snapshot = cloneStateSnapshot();
    let result;
    try{
      result = moveFinanceImportAccount(id, targetAccountId);
    }catch(err){
      return alert(err?.message || "Não foi possível trocar a conta da importação.");
    }
    if(!await persistStateOrRollback(snapshot, { button: btn, savingText: "Movendo..." })) return;
    renderAll();
    alert(`Importação movida para ${targetName}. ${result.movedTransactions} transação(ões), ${result.movedLancamentos} lançamento(s) e ${result.movedTitulos} título(s) atualizados.${result.unlinkedTransfers ? ` ${result.unlinkedTransfers} lado(s) de transferência foram desvinculados para revisão.` : ""}`);
  }
  if(act === "delImport"){
    const imp = state.imports.find(item => item.id === id);
    if(!imp) return;
    const related = financeImportRelatedSummary(id);
    if(confirm(
      `Excluir as ${related.bankIds.size} transações importadas de ${imp.fileName || "este extrato"}?\n\n` +
      "A importação e seus vínculos de conciliação serão removidos. Lançamentos e títulos criados no sistema serão preservados, mas ficarão desvinculados do extrato."
    )){
      const snapshot = cloneStateSnapshot();
      const result = deleteFinanceImportFromState(id);
      if(!await persistStateOrRollback(snapshot, { button: btn, savingText: "Excluindo..." })) return;
      renderAll();
      alert(`${result.removedTransactions} transação(ões) importada(s) excluída(s). ${result.unlinkedLancamentos} lançamento(s) e ${result.unlinkedTitulos} título(s) foram preservados e desvinculados.`);
    }
  }
}

$("#listaImports")?.addEventListener("click", handleFinanceImportAction);
$("#listaImportsImportar")?.addEventListener("click", handleFinanceImportAction);

function openContaModal(id){
  editContaId = id;
  $("#modalConta").classList.remove("hidden");
  $("#modalContaTitle").textContent = id ? "Editar conta" : "Nova conta";
  const c = id ? state.contas.find(x=>x.id===id) : null;
  $("#cNome").value = c?.nome || "";
  $("#cMoeda").value = c?.moeda || "BRL";
  $("#cSaldo").value = c ? Number(c.saldoInicial || 0) : 0;
  $("#cSaldoData").value = c ? contaSaldoInicialEm(c) : toISODate(new Date());
}
function closeContaModal(){
  $("#modalConta").classList.add("hidden");
  editContaId = null;
}
$("#btnFecharModalConta").addEventListener("click", closeContaModal);
$("#btnCancelarConta").addEventListener("click", closeContaModal);
$("#modalConta").addEventListener("click",(e)=>{ if(e.target.id==="modalConta") closeContaModal(); });

$("#btnSalvarConta").addEventListener("click", async (e)=>{
  const nome = $("#cNome").value.trim();
  const moeda = ($("#cMoeda").value || "BRL").trim().toUpperCase();
  const saldoInicial = Number($("#cSaldo").value);
  const saldoInicialEm = $("#cSaldoData").value;

  if(!nome || !Number.isFinite(saldoInicial) || !isValidDateISO(saldoInicialEm)){
    alert("Informe nome, saldo inicial e a data de referência do saldo.");
    return;
  }

  const snapshot = cloneStateSnapshot();
  if(editContaId){
    const idx = state.contas.findIndex(c=>c.id===editContaId);
    if(idx>=0) state.contas[idx] = { ...state.contas[idx], nome, moeda, saldoInicial, saldoInicialEm };
  } else {
    state.contas.push({ id: uid("conta"), nome, moeda, saldoInicial, saldoInicialEm });
  }
  if(!await persistStateOrRollback(snapshot, { button: e.currentTarget })) return;
  closeContaModal();
  renderAll();
});

/* ---------- Categorias ---------- */
function renderCategorias(){
  const cats = state.categorias.slice().sort((a,b)=> a.tipo.localeCompare(b.tipo) || a.nome.localeCompare(b.nome));
  $("#listaCats").innerHTML = cats.map(c=>{
    const badge = c.tipo === "RECEITA" ? `<span class="badge ok">RECEITA</span>` : `<span class="badge bad">DESPESA</span>`;
    return `
      <div class="item">
        <div class="left">
          ${badge}
          <div><b>${escapeHtml(c.nome)}</b></div>
        </div>
        <div class="row gap">
          <button class="btn danger" data-id="${c.id}">Excluir</button>
        </div>
      </div>
    `;
  }).join("");
}

$("#btnAddCat").addEventListener("click", async (e)=>{
  const nome = $("#catNome").value.trim();
  const tipo = $("#catTipo").value;
  if(!nome) return alert("Informe o nome da categoria.");
  const snapshot = cloneStateSnapshot();
  state.categorias.push({ id: uid("cat"), nome, tipo });
  $("#catNome").value = "";
  if(!await persistStateOrRollback(snapshot, { button: e.currentTarget })) return;
  renderAll();
});

$("#listaCats").addEventListener("click", async (e)=>{
  const btn = e.target.closest("button");
  if(!btn) return;
  const id = btn.dataset.id;
  if(confirm("Excluir categoria? (lançamentos existentes manterão o ID antigo)")){
    const snapshot = cloneStateSnapshot();
    state.categorias = state.categorias.filter(c=>c.id!==id);
    if(!await persistStateOrRollback(snapshot, { button: btn })) return;
    renderAll();
  }
});

/* ---------- Cadastros de pagamento ---------- */
let editFavorecidoId = null;

function bankAccountTypeLabel(value){
  return ({
    CORRENTE: "Conta corrente",
    POUPANCA: "Poupança",
    PAGAMENTO: "Conta de pagamento",
    OUTRA: "Outra"
  })[value] || "Conta";
}

function renderFavorecidos(){
  const table = $("#tbFavorecidos");
  if(!table) return;
  const search = String($("#favBusca")?.value || "").trim().toLowerCase();
  const list = (state.favorecidos || [])
    .filter(item => !search || [
      item.nome, item.pixKey, item.bankName, item.bankAgency, item.bankAccount, item.accessUrl
    ].some(value => String(value || "").toLowerCase().includes(search)))
    .slice()
    .sort((a, b) => String(a.nome || "").localeCompare(String(b.nome || ""), "pt-BR"));

  table.innerHTML = list.map(item => {
    const pix = item.pixKey
      ? `<div><b>${escapeHtml(item.pixKey)}</b></div><div class="muted">${escapeHtml(item.pixKeyType || "PIX")}</div>`
      : `<span class="muted">Não informado</span>`;
    const account = item.bankAccount
      ? `<div><b>${escapeHtml(item.bankAgency || "Sem agência")} / ${escapeHtml(item.bankAccount)}</b></div><div class="muted">${escapeHtml(bankAccountTypeLabel(item.bankAccountType))}</div>`
      : `<span class="muted">Não informada</span>`;
    const accessUrl = String(item.accessUrl || "").trim();
    const portal = accessUrl
      ? `<a class="btn" href="${escapeHtml(accessUrl)}" target="_blank" rel="noopener noreferrer">Acessar site</a>`
      : `<span class="muted">Não informado</span>`;
    return `
      <tr>
        <td><b>${escapeHtml(item.nome || "-")}</b></td>
        <td>${pix}</td>
        <td>${escapeHtml(item.bankName || "-")}</td>
        <td>${account}</td>
        <td>${portal}</td>
        <td class="right">
          <button class="btn" data-act="edit" data-id="${escapeHtml(item.id)}">Editar</button>
          <button class="btn danger" data-act="del" data-id="${escapeHtml(item.id)}">Excluir</button>
        </td>
      </tr>
    `;
  }).join("") || `<tr><td colspan="6" class="muted">Nenhum favorecido cadastrado.</td></tr>`;
}

function openFavorecidoModal(id=null){
  editFavorecidoId = id;
  const item = id ? (state.favorecidos || []).find(candidate => candidate.id === id) : null;
  $("#modalFavorecidoTitle").textContent = item ? "Editar favorecido" : "Novo favorecido";
  $("#favNome").value = item?.nome || "";
  $("#favAccessUrl").value = item?.accessUrl || "";
  $("#favPixKeyType").value = item?.pixKeyType || "TELEFONE";
  $("#favPixKey").value = item?.pixKey || "";
  $("#favPixCity").value = item?.pixCity || "";
  $("#favBankName").value = item?.bankName || "";
  $("#favBankAccountType").value = item?.bankAccountType || "CORRENTE";
  $("#favBankAgency").value = item?.bankAgency || "";
  $("#favBankAccount").value = item?.bankAccount || "";
  $("#modalFavorecido").classList.remove("hidden");
  $("#favNome").focus();
}

function closeFavorecidoModal(){
  $("#modalFavorecido").classList.add("hidden");
  editFavorecidoId = null;
}

function currentFavorecidoDraft(){
  return {
    nome: $("#favNome").value.trim(),
    accessUrl: $("#favAccessUrl").value.trim(),
    pixKeyType: $("#favPixKeyType").value,
    pixKey: $("#favPixKey").value.trim(),
    pixCity: $("#favPixCity").value.trim(),
    bankName: $("#favBankName").value.trim(),
    bankAccountType: $("#favBankAccountType").value,
    bankAgency: $("#favBankAgency").value.trim(),
    bankAccount: $("#favBankAccount").value.trim()
  };
}

$("#btnNovoFavorecido").addEventListener("click", () => openFavorecidoModal());
$("#btnFecharFavorecido").addEventListener("click", closeFavorecidoModal);
$("#btnCancelarFavorecido").addEventListener("click", closeFavorecidoModal);
$("#modalFavorecido").addEventListener("click", event => {
  if(event.target.id === "modalFavorecido") closeFavorecidoModal();
});
$("#favBusca").addEventListener("input", renderFavorecidos);

$("#btnSalvarFavorecido").addEventListener("click", async event => {
  const draft = currentFavorecidoDraft();
  if(!draft.nome) return alert("Informe o nome do favorecido.");
  try{
    draft.accessUrl = normalizeExternalAccessUrl(draft.accessUrl);
  }catch(err){
    return alert(err?.message || "O link de acesso não é válido.");
  }
  if(!draft.pixKey && !draft.bankAccount && !draft.accessUrl){
    return alert("Informe uma chave PIX, o número da conta ou o link de acesso.");
  }
  if(draft.bankAccount && !draft.bankName){
    return alert("Informe o banco da conta para pagamento.");
  }
  const duplicatedName = (state.favorecidos || []).some(item =>
    item.id !== editFavorecidoId && String(item.nome || "").trim().toLowerCase() === draft.nome.toLowerCase()
  );
  if(duplicatedName) return alert("Já existe um favorecido com este nome.");

  if(draft.pixKey){
    try{
      const validated = await requestPixCode({
        pixKey: draft.pixKey,
        pixKeyType: draft.pixKeyType,
        valor: 0.01,
        pessoa: draft.nome,
        pixCity: draft.pixCity
      });
      draft.pixKey = validated.key || draft.pixKey;
    }catch(err){
      return alert(err?.message || "A chave PIX não pôde ser validada.");
    }
  }

  const snapshot = cloneStateSnapshot();
  const now = new Date().toISOString();
  let savedFavorecidoId = "";
  if(editFavorecidoId){
    const index = state.favorecidos.findIndex(item => item.id === editFavorecidoId);
    if(index < 0) return alert("Favorecido não encontrado.");
    state.favorecidos[index] = { ...state.favorecidos[index], ...draft, updatedAt: now };
    savedFavorecidoId = editFavorecidoId;
  }else{
    savedFavorecidoId = uid("fav");
    state.favorecidos.push({ id: savedFavorecidoId, ...draft, createdAt: now, updatedAt: now });
  }
  const linkedTitlesUpdated = syncFavorecidoPaymentToLinkedTitles(state, savedFavorecidoId);
  if(!await persistStateOrRollback(snapshot, { button: event.currentTarget })) return;
  closeFavorecidoModal();
  renderAll();
  if(linkedTitlesUpdated){
    alert(`Favorecido salvo. ${linkedTitlesUpdated} título(s) vinculado(s) foram atualizados com os dados de pagamento.`);
  }
});

$("#tbFavorecidos").addEventListener("click", async event => {
  const button = event.target.closest("button");
  if(!button) return;
  const item = (state.favorecidos || []).find(candidate => candidate.id === button.dataset.id);
  if(!item) return;
  if(button.dataset.act === "edit") return openFavorecidoModal(item.id);
  if(button.dataset.act !== "del") return;
  if(!confirm(`Excluir o favorecido ${item.nome}?\n\nOs títulos já salvos manterão os dados de pagamento copiados.`)) return;
  const snapshot = cloneStateSnapshot();
  state.favorecidos = state.favorecidos.filter(candidate => candidate.id !== item.id);
  if(!await persistStateOrRollback(snapshot, { button })) return;
  renderAll();
});

/* ---------- Importação de extratos ---------- */
function renderImportPreview(){
  const last = state.imports.slice().sort((a,b)=> b.createdAt.localeCompare(a.createdAt))[0];
  if(!last){
    $("#tbOfxPreview").innerHTML = `<tr><td colspan="4" class="muted">Nenhuma importação.</td></tr>`;
    return;
  }
  $("#tbOfxPreview").innerHTML = last.txs.slice(0,50).map(t=>{
    return `
      <tr>
        <td>${escapeHtml(t.date)}</td>
        <td>${escapeHtml(t.memo || "")}</td>
        <td class="right"><b>${brl(Math.abs(t.amount))}</b></td>
        <td class="muted">${escapeHtml(t.fitid || "")}</td>
      </tr>
    `;
  }).join("");
}

function importedBankFitids(contaId){
  return new Set([
    ...state.imports
      .filter(imp => imp.contaId === contaId)
      .flatMap(imp => (imp.txs || []).map(tx => tx.fitid).filter(Boolean)),
    ...state.ignoredBankTransactions
      .filter(item => item.contaId === contaId)
      .map(item => item.fitid)
      .filter(Boolean)
  ]);
}

function knownBankTransactionKeys(contaId){
  return new Set([
    ...state.imports
      .filter(imp => imp.contaId === contaId)
      .flatMap(imp => (imp.txs || []).map(tx => bankTransactionKey(contaId, tx))),
    ...state.ignoredBankTransactions
      .filter(item => item.contaId === contaId)
      .map(item => item.key || bankTransactionKey(contaId, item))
  ]);
}

async function parseFinanceStatementFile(file){
  if(file.name.toLowerCase().endsWith(".pdf") || file.type === "application/pdf"){
    const formData = new FormData();
    formData.set("file", file);
    const payload = await requestJson("/apps/financeiro/api/import-pdf", {
      method: "POST",
      body: formData
    });
    return {
      format: "PDF",
      bank: payload?.bank || "Banco",
      account: payload?.account || "",
      periodStart: payload?.periodStart || "",
      periodEnd: payload?.periodEnd || "",
      closingBalance: payload?.closingBalance !== null
        && payload?.closingBalance !== undefined
        && Number.isFinite(Number(payload.closingBalance))
        ? Number(payload.closingBalance)
        : null,
      balanceDate: payload?.balanceDate || "",
      txs: payload?.txs || []
    };
  }

  const ofxText = await file.text();
  const metadata = parseOFXMetadata(ofxText);
  return {
    format: "OFX",
    bank: metadata.bank,
    account: metadata.account,
    periodStart: metadata.periodStart,
    periodEnd: metadata.periodEnd,
    closingBalance: metadata.closingBalance,
    balanceDate: metadata.balanceDate,
    txs: parseOFX(ofxText)
  };
}

function applyStatementBalanceMetadata(contaId, parsed){
  if(!Number.isFinite(parsed?.closingBalance) || !isValidDateISO(parsed?.balanceDate)) return 0;
  let updated = 0;
  for(const imp of state.imports){
    if(
      imp.contaId === contaId
      && imp.periodStart === parsed.periodStart
      && imp.periodEnd === parsed.periodEnd
    ){
      imp.closingBalance = parsed.closingBalance;
      imp.balanceDate = parsed.balanceDate;
      updated++;
    }
  }
  return updated;
}

function statementPeriodsOverlap(imp, parsed){
  if(!isValidDateISO(imp?.periodStart) || !isValidDateISO(imp?.periodEnd)) return false;
  if(!isValidDateISO(parsed?.periodStart) || !isValidDateISO(parsed?.periodEnd)) return false;
  return imp.periodStart <= parsed.periodEnd && parsed.periodStart <= imp.periodEnd;
}

function statementCompletionTarget(contaId, parsed){
  const explicit = completeImportTargetId
    ? state.imports.find(imp => imp.id === completeImportTargetId && imp.contaId === contaId)
    : null;
  if(explicit){
    const sameAccount = !explicit.bankAccount || !parsed.account || explicit.bankAccount === parsed.account;
    return sameAccount && statementPeriodsOverlap(explicit, parsed) ? explicit : null;
  }

  const candidates = state.imports.filter(imp => {
    if(imp.contaId !== contaId || !statementPeriodsOverlap(imp, parsed)) return false;
    if(imp.bankAccount && parsed.account && imp.bankAccount !== parsed.account) return false;
    return true;
  });
  return candidates.sort((a, b) => {
    const exactA = a.periodStart === parsed.periodStart && a.periodEnd === parsed.periodEnd ? 1 : 0;
    const exactB = b.periodStart === parsed.periodStart && b.periodEnd === parsed.periodEnd ? 1 : 0;
    return exactB - exactA || String(b.createdAt || "").localeCompare(String(a.createdAt || ""));
  })[0] || null;
}

function completeStatementImport(target, parsed, fileName, newTransactions){
  target.fileName = fileName;
  target.updatedAt = new Date().toISOString().slice(0, 19).replace("T", " ");
  target.format = parsed.format || target.format;
  target.bank = parsed.bank || target.bank;
  target.bankAccount = parsed.account || target.bankAccount;
  target.periodStart = [target.periodStart, parsed.periodStart].filter(isValidDateISO).sort()[0] || "";
  target.periodEnd = [target.periodEnd, parsed.periodEnd].filter(isValidDateISO).sort().at(-1) || "";
  if(Number.isFinite(parsed.closingBalance)) target.closingBalance = parsed.closingBalance;
  if(isValidDateISO(parsed.balanceDate)) target.balanceDate = parsed.balanceDate;
  target.txs.push(...newTransactions.map(tx => ({ ...tx, id: uid("banktx") })));
  target.txs.sort((a, b) => String(a.date || "").localeCompare(String(b.date || "")));
  return target;
}

$("#btnImportarOFX").addEventListener("click", async (event)=>{
  const contaId = $("#ofxConta").value;
  const file = $("#ofxFile").files?.[0];
  if(!contaId) return alert("Selecione uma conta.");
  if(!file) return alert("Selecione um arquivo OFX ou PDF.");

  const button = event.currentTarget;
  const previousText = button.textContent;
  button.disabled = true;
  button.textContent = "Lendo extrato...";
  let parsed;
  try{
    parsed = await parseFinanceStatementFile(file);
  }catch(err){
    alert(err?.message || "Não foi possível ler o extrato.");
    return;
  }finally{
    button.disabled = false;
    button.textContent = previousText;
  }

  if(!parsed.txs.length){
    alert("Não consegui ler transações desse extrato.");
    return;
  }

  const alreadyImported = importedBankFitids(contaId);
  const knownKeys = knownBankTransactionKeys(contaId);
  const txs = parsed.txs.filter(tx => {
    const key = bankTransactionKey(contaId, tx);
    const duplicate = knownKeys.has(key) || (tx.fitid && alreadyImported.has(tx.fitid));
    knownKeys.add(key);
    if(tx.fitid) alreadyImported.add(tx.fitid);
    return !duplicate;
  });
  const duplicateCount = parsed.txs.length - txs.length;
  const completionTarget = statementCompletionTarget(contaId, parsed);
  if(completeImportTargetId && !completionTarget){
    completeImportTargetId = null;
    return alert("O extrato selecionado não pertence à mesma conta do extrato que será completado.");
  }
  if(completionTarget){
    const snapshot = cloneStateSnapshot();
    completeStatementImport(completionTarget, parsed, file.name, txs);
    completeImportTargetId = null;
    if(!await persistStateOrRollback(snapshot, { button })) return;
    renderAll();
    const balanceMessage = Number.isFinite(parsed.closingBalance)
      ? ` Saldo bancário de ${brl(parsed.closingBalance)} em ${parsed.balanceDate} salvo somente para conferência.`
      : "";
    alert(`Extrato completado: ${txs.length} transação(ões) nova(s), ${duplicateCount} já existente(s), ${completionTarget.txs.length} no total.${balanceMessage}`);
    return;
  }
  if(!txs.length){
    if(Number.isFinite(parsed.closingBalance) && isValidDateISO(parsed.balanceDate)){
      const snapshot = cloneStateSnapshot();
      applyStatementBalanceMetadata(contaId, parsed);
      if(!await persistStateOrRollback(snapshot, { button })) return;
      renderAll();
      alert(`Todas as ${parsed.txs.length} transações já estavam importadas. O saldo bancário de ${brl(parsed.closingBalance)} em ${parsed.balanceDate} foi salvo para conferência, sem alterar o saldo inicial.`);
      return;
    }
    alert(`Todas as ${parsed.txs.length} transações deste extrato já foram importadas para a conta selecionada.`);
    return;
  }

  const imp = {
    id: uid("imp"),
    contaId,
    createdAt: new Date().toISOString().slice(0,19).replace("T"," "),
    fileName: file.name,
    format: parsed.format,
    bank: parsed.bank,
    bankAccount: parsed.account,
    periodStart: parsed.periodStart,
    periodEnd: parsed.periodEnd,
    closingBalance: parsed.closingBalance,
    balanceDate: parsed.balanceDate,
    txs: txs.map(t => ({...t, id: uid("banktx")}))
  };

  const snapshot = cloneStateSnapshot();
  state.imports.push(imp);
  completeImportTargetId = null;
  if(!await persistStateOrRollback(snapshot, { button })) return;
  renderAll();
  const duplicateMessage = duplicateCount ? ` ${duplicateCount} duplicada(s) foram ignoradas.` : "";
  alert(`Importado: ${imp.txs.length} transações.${duplicateMessage} Vá em "Conciliação".`);
});

/* Parser OFX (foco OFX 1.x SGML). */
function normalizeOFXText(ofxText){
  let s = ofxText.replace(/\r\n/g,"\n");
  s = s.replace(/<(\w+?)>([^<\n\r]*)/g, (m,tag,val)=>{
    if(val.includes(`</${tag}>`)) return m;
    if(val.trim()==="") return `<${tag}>`;
    return `<${tag}>${escapeXml(val.trim())}</${tag}>`;
  });
  return s;
}

function parseOFXMetadata(ofxText){
  if(!ofxText) return {
    bank: "", account: "", periodStart: "", periodEnd: "",
    closingBalance: null, balanceDate: ""
  };
  const s = normalizeOFXText(ofxText);
  const ledgerBlock = s.match(/<LEDGERBAL>[\s\S]*?<\/LEDGERBAL>/i)?.[0] || "";
  const balanceValue = Number(String(getTag(ledgerBlock, "BALAMT") || "").replace(",", "."));
  return {
    bank: getTag(s, "ORG") || getTag(s, "FID") || "",
    account: getTag(s, "ACCTID") || "",
    periodStart: ofxDateToISO(getTag(s, "DTSTART")),
    periodEnd: ofxDateToISO(getTag(s, "DTEND")),
    closingBalance: Number.isFinite(balanceValue) ? balanceValue : null,
    balanceDate: ofxDateToISO(getTag(ledgerBlock, "DTASOF"))
  };
}

function parseOFX(ofxText){
  if(!ofxText) return [];

  const s = normalizeOFXText(ofxText);

  const blocks = s.match(/<STMTTRN>[\s\S]*?<\/STMTTRN>/gi) || [];
  const txs = [];

  for(const b of blocks){
    const type = getTag(b,"TRNTYPE") || "";
    const dt = getTag(b,"DTPOSTED") || getTag(b,"DTUSER") || "";
    const amt = getTag(b,"TRNAMT") || "";
    const fitid = getTag(b,"FITID") || "";
    const name = getTag(b,"NAME") || "";
    const memo = getTag(b,"MEMO") || "";

    const date = ofxDateToISO(dt);
    const amount = Number(String(amt).replace(",", "."));

    if(!date || !Number.isFinite(amount)) continue;

    txs.push({
      date,
      amount,
      fitid: fitid || "",
      memo: (memo || name || "").trim() || "(sem descrição)",
      trntype: type
    });
  }

  return txs;
}
function getTag(xmlish, tag){
  const re = new RegExp(`<${tag}>([\\s\\S]*?)<\\/${tag}>`, "i");
  const m = xmlish.match(re);
  return m ? decodeXml(m[1].trim()) : "";
}
function ofxDateToISO(dt){
  const m = String(dt).match(/^(\d{4})(\d{2})(\d{2})/);
  if(!m) return "";
  return `${m[1]}-${m[2]}-${m[3]}`;
}
function escapeXml(str){
  return String(str).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");
}
function decodeXml(str){
  return String(str).replaceAll("&lt;","<").replaceAll("&gt;",">").replaceAll("&amp;","&");
}

/* ---------- Conciliação ---------- */
let selectedBankTxId = null;
let selectedLancId = null;
let selectedTituloId = null;
let suggestedReconciliationMatches = new Map();
let selectedSuggestedBankTxIds = new Set();
let showReconciledItems = false;

function resetReconciliationSuggestions(){
  suggestedReconciliationMatches = new Map();
  selectedSuggestedBankTxIds = new Set();
}

function bankTransactionKey(contaId, tx){
  // O mesmo movimento pode vir com FITIDs diferentes em OFX e PDF. A chave
  // semântica impede duplicidade entre formatos sem abandonar a validação de
  // FITID feita separadamente durante a importação.
  return `${contaId}|movement|${tx?.date || ""}|${Number(tx?.amount || 0).toFixed(2)}|${normalizeText(tx?.memo || "")}`;
}

function bankTransactionRecord(bankTxId){
  for(const imp of state.imports || []){
    const bankTx = (imp.txs || []).find(tx => tx.id === bankTxId);
    if(bankTx) return { bankTx, contaId: imp.contaId || "" };
  }
  return null;
}

function reconcileBankTransactionWithLancamento(bankTxId, lancId){
  const bankRecord = bankTransactionRecord(bankTxId);
  const lanc = state.lancamentos.find(item => item.id === lancId);
  if(!bankRecord || !lanc) throw new Error("Transação ou lançamento não encontrado.");
  if(bankRecord.contaId !== lanc.contaId){
    throw new Error("A transação e o lançamento pertencem a contas diferentes.");
  }
  const bankConflict = state.reconciliations.find(item =>
    item.bankTxId === bankTxId && item.lancId !== lancId
  );
  const lancConflict = state.reconciliations.find(item =>
    item.lancId === lancId && item.bankTxId !== bankTxId
  );
  if(bankConflict || lancConflict){
    throw new Error("A transação ou o lançamento já possui outro vínculo. Desvincule o par atual antes de continuar.");
  }

  if(!state.reconciliations.some(item => item.bankTxId === bankTxId && item.lancId === lancId)){
    state.reconciliations.push({ bankTxId, lancId });
  }
  lanc.conciliado = true;
  lanc.bankTxId = bankTxId;
  syncTituloFromLancamento(lanc);
  return lanc;
}

function bankTransactionValueDiffers(bankTx, lanc){
  return Math.abs(Math.abs(Number(bankTx?.amount || 0)) - Math.abs(Number(lanc?.valor || 0))) > 0.005;
}

function bankTransactionTypeMatches(bankTx, lanc){
  return (Number(bankTx?.amount || 0) >= 0) === (lanc?.tipo === "RECEITA");
}

function possibleDuplicateBankTransaction(lanc, bankTransactions, linkedBankIds){
  let best = null;
  for(const bankTx of bankTransactions){
    if(!linkedBankIds.has(bankTx.id) || !bankTransactionTypeMatches(bankTx, lanc)) continue;
    if(bankTransactionValueDiffers(bankTx, lanc)) continue;
    const facts = financialMatchFacts(bankTx, lanc, state.config);
    if(!facts.dateWithinTolerance && !facts.descriptionSimilar) continue;
    const score = (facts.dateWithinTolerance ? 100 - facts.diffDays : 0)
      + Math.min(facts.descriptionOverlap, 3) * 10;
    if(!best || score > best.score) best = { bankTx, facts, score };
  }
  return best;
}

function correctLancamentoFromBank(bankTx, lanc){
  if(!bankTx || !lanc) return false;
  const bankValue = Math.abs(Number(bankTx.amount || 0));
  if(!Number.isFinite(bankValue)) return false;
  const affectedLancamentos = lanc.transferenciaId
    ? state.lancamentos.filter(item => item.transferenciaId === lanc.transferenciaId)
    : [lanc];
  for(const item of affectedLancamentos) item.valor = bankValue;
  for(const titulo of state.titulos){
    if(titulo.lancId === lanc.id) titulo.valor = bankValue;
  }
  return true;
}

function confirmBankValueCorrections(pairs, imp){
  const bankById = new Map((imp?.txs || []).map(tx => [tx.id, tx]));
  const mismatches = pairs.map(pair => {
    const bankTx = bankById.get(pair.bankTxId);
    const lanc = state.lancamentos.find(item => item.id === pair.lancId);
    return { bankTx, lanc };
  }).filter(pair => pair.bankTx && pair.lanc && bankTransactionValueDiffers(pair.bankTx, pair.lanc));
  if(!mismatches.length) return true;

  const preview = mismatches.slice(0, 5).map(({bankTx, lanc}) =>
    `• ${bankTx.date} — banco ${brl(Math.abs(Number(bankTx.amount || 0)))} / lançamento ${brl(Math.abs(Number(lanc.valor || 0)))}`
  ).join("\n");
  const remaining = mismatches.length > 5 ? `\n• e mais ${mismatches.length - 5} divergência(s)` : "";
  return confirm(
    `${mismatches.length} vínculo(s) têm valores diferentes.\n\n${preview}${remaining}\n\nO valor do banco será considerado correto e atualizará o(s) lançamento(s). Deseja continuar?`
  );
}

function reconciliationSuggestions(contaId, imp){
  if(!imp) return new Map();
  const cfg = state.config;
  const reconBank = new Set(state.reconciliations.map(r=>r.bankTxId));
  const reconLanc = new Set(state.reconciliations.map(r=>r.lancId));
  const pendingBank = imp.txs.filter(t => !reconBank.has(t.id));
  const availableLanc = state.lancamentos.filter(l => l.contaId===contaId && !reconLanc.has(l.id));
  const suggestions = new Map();

  for(const bankTx of pendingBank){
    let best = {score: -1, lanc: null, facts: null};
    const bankIsCredit = Number(bankTx.amount||0) >= 0;
    for(const lanc of availableLanc){
      if(bankIsCredit !== (lanc.tipo === "RECEITA")) continue;
      const facts = financialMatchFacts(bankTx, lanc, cfg);
      const score = scoreMatch(bankTx, lanc, cfg);
      const isFinancialCandidate = facts.valueWithinTolerance && facts.dateWithinTolerance;
      const bestIsFinancialCandidate = best.facts?.valueWithinTolerance && best.facts?.dateWithinTolerance;
      const isBetterFinancialCandidate = isFinancialCandidate && bestIsFinancialCandidate && (
        facts.diffValue < best.facts.diffValue
        || (facts.diffValue === best.facts.diffValue && facts.diffDays < best.facts.diffDays)
        || (
          facts.diffValue === best.facts.diffValue
          && facts.diffDays === best.facts.diffDays
          && score > best.score
        )
      );
      if(
        !best.lanc
        || (isFinancialCandidate && !bestIsFinancialCandidate)
        || isBetterFinancialCandidate
        || (!isFinancialCandidate && !bestIsFinancialCandidate && score > best.score)
      ){
        best = {score, lanc, facts};
      }
    }
    const matchesDateAndValue = best.facts?.sameType
      && best.facts?.valueWithinTolerance
      && best.facts?.dateWithinTolerance;
    const matchesByDateOrDescription = best.facts?.sameType
      && (best.facts?.dateWithinTolerance || best.facts?.descriptionSimilar);
    if(best.lanc && (matchesDateAndValue || matchesByDateOrDescription || best.score >= cfg.scoreMin)){
      let reason = "Similaridade";
      if(matchesDateAndValue) reason = "Data + valor";
      else if(best.facts?.valueWithinTolerance && best.facts?.descriptionSimilar) reason = "Valor + descrição";
      else if(best.facts?.dateWithinTolerance && !best.facts?.valueWithinTolerance) reason = "Data similar • valor divergente";
      else if(best.facts?.descriptionSimilar && !best.facts?.valueWithinTolerance) reason = "Descrição similar • valor divergente";
      suggestions.set(bankTx.id, {
        lancId: best.lanc.id,
        score: best.score,
        reason,
        valueMismatch: !best.facts?.valueWithinTolerance
      });
      const index = availableLanc.findIndex(lanc => lanc.id === best.lanc.id);
      if(index >= 0) availableLanc.splice(index, 1);
    }
  }

  return suggestions;
}

function pruneReconciliationSuggestions(contaId, imp){
  const bankIds = new Set((imp?.txs || []).map(tx => tx.id));
  const lancIds = new Set(state.lancamentos.filter(l => l.contaId===contaId).map(l => l.id));
  const reconBank = new Set(state.reconciliations.map(r=>r.bankTxId));
  const reconLanc = new Set(state.reconciliations.map(r=>r.lancId));
  for(const [bankTxId, suggestion] of suggestedReconciliationMatches){
    if(
      !bankIds.has(bankTxId)
      || !lancIds.has(suggestion.lancId)
      || reconBank.has(bankTxId)
      || reconLanc.has(suggestion.lancId)
    ){
      suggestedReconciliationMatches.delete(bankTxId);
      selectedSuggestedBankTxIds.delete(bankTxId);
    }
  }
}

function renderReconciliationMatchControls(linkedCount=0, divergentCount=0){
  const suggestionIds = [...suggestedReconciliationMatches.keys()];
  const selectedCount = suggestionIds.filter(id => selectedSuggestedBankTxIds.has(id)).length;
  const selectButton = $("#btnSelecionarMatches");
  const linkButton = $("#btnVincularMatches");
  selectButton.disabled = suggestionIds.length === 0;
  selectButton.textContent = suggestionIds.length > 0 && selectedCount === suggestionIds.length
    ? "Desmarcar todos os matches"
    : "Selecionar todos os matches";
  linkButton.disabled = selectedCount === 0;
  linkButton.textContent = `Vincular matches selecionados (${selectedCount})`;
  const linkedButton = $("#btnAlternarVinculados");
  linkedButton.disabled = linkedCount === 0;
  linkedButton.textContent = showReconciledItems
    ? "Ocultar vinculados"
    : `Mostrar vinculados (${linkedCount})`;
  const correctionButton = $("#btnCorrigirValores");
  correctionButton.disabled = divergentCount === 0;
  correctionButton.textContent = `Corrigir valores divergentes (${divergentCount})`;
  const ignoreButton = $("#btnIgnorarBankTx");
  const selectedIsUnlinked = !!selectedBankTxId && !state.reconciliations.some(item => item.bankTxId === selectedBankTxId);
  ignoreButton.disabled = !selectedIsUnlinked;
  const deleteLancButton = $("#btnExcluirLancConc");
  const selectedLancIsUnlinked = !!selectedLancId && !state.reconciliations.some(item => item.lancId === selectedLancId);
  deleteLancButton.disabled = !selectedLancIsUnlinked;
  const deleteAllButton = $("#btnExcluirTodosLancSemVinculo");
  const deletionPlan = unlinkedLancamentoDeletionPlan($("#concConta").value);
  deleteAllButton.disabled = deletionPlan.selectedCount === 0;
  deleteAllButton.textContent = `Excluir lançamentos e títulos sem vínculo (${deletionPlan.selectedCount})`;
}

function renderConciliacao(){
  const contaId = $("#concConta").value || state.contas[0]?.id || "";
  if(contaId) $("#concConta").value = contaId;

  const imports = state.imports
    .filter(i => i.contaId === contaId)
    .slice()
    .sort((a,b)=> b.createdAt.localeCompare(a.createdAt));

  const previouslySelectedImportId = $("#concImport").value;
  $("#concImport").innerHTML = imports.map(i=> `<option value="${i.id}">${escapeHtml(i.createdAt)} • ${escapeHtml(i.fileName||"import.ofx")}</option>`).join("")
    || `<option value="">(Sem importações)</option>`;

  const importId = imports.some(item => item.id === previouslySelectedImportId)
    ? previouslySelectedImportId
    : imports[0]?.id || "";
  if(importId) $("#concImport").value = importId;

  const imp = state.imports.find(i=>i.id===importId);
  const allBankTxs = imp?.txs || [];
  const allLancs = state.lancamentos.filter(l => l.contaId === contaId);

  const reconByBank = new Map(state.reconciliations.map(r=>[r.bankTxId, r.lancId]));
  const reconByLanc = new Map(state.reconciliations.map(r=>[r.lancId, r.bankTxId]));
  const currentBankIds = new Set(allBankTxs.map(tx => tx.id));
  const linkedCount = allBankTxs.filter(tx => reconByBank.has(tx.id)).length;
  const bankTxs = showReconciledItems
    ? allBankTxs
    : allBankTxs.filter(tx => !reconByBank.has(tx.id));
  const lancs = allLancs.filter(lanc => {
    const linkedBankId = reconByLanc.get(lanc.id);
    if(!linkedBankId) return true;
    return showReconciledItems && currentBankIds.has(linkedBankId);
  });
  pruneReconciliationSuggestions(contaId, imp);
  const suggestionByLanc = new Map(
    [...suggestedReconciliationMatches.entries()].map(([bankTxId, suggestion]) => [
      suggestion.lancId,
      { bankTxId, score: suggestion.score, reason: suggestion.reason, valueMismatch: suggestion.valueMismatch }
    ])
  );
  const suggestionNumberByBank = new Map(
    [...suggestedReconciliationMatches.keys()].map((bankTxId, index) => [bankTxId, index + 1])
  );
  const lancById = new Map(state.lancamentos.map(lanc => [lanc.id, lanc]));
  const bankById = new Map(state.imports.flatMap(item => (item.txs || []).map(tx => [tx.id, tx])));
  const tituloByLancId = new Map(state.titulos.filter(titulo => titulo.lancId).map(titulo => [titulo.lancId, titulo]));
  const divergentLinks = allBankTxs.map(bankTx => ({
    bankTx,
    lanc: lancById.get(reconByBank.get(bankTx.id))
  })).filter(pair => pair.lanc && bankTransactionValueDiffers(pair.bankTx, pair.lanc));
  const linkedBankIds = new Set(allBankTxs.filter(tx => reconByBank.has(tx.id)).map(tx => tx.id));
  const possibleDuplicateByLanc = new Map(allLancs.map(lanc => [
    lanc.id,
    reconByLanc.has(lanc.id) ? null : possibleDuplicateBankTransaction(lanc, allBankTxs, linkedBankIds)
  ]));

  $("#bankList").innerHTML = bankTxs.map(t=>{
    const linkedLancId = reconByBank.get(t.id);
    const linkedLanc = lancById.get(linkedLancId);
    const suggestion = suggestedReconciliationMatches.get(t.id);
    const suggestedLanc = lancById.get(suggestion?.lancId);
    const matchSelected = suggestion && selectedSuggestedBankTxIds.has(t.id);
    const pairNumber = suggestionNumberByBank.get(t.id);
    const linkedMismatch = linkedLanc && bankTransactionValueDiffers(t, linkedLanc);
    const status = linkedLancId
      ? `<span class="badge ${linkedMismatch ? "bad" : "ok"}">${linkedMismatch ? "Vinculado • valor divergente" : "Vinculado"}</span><div class="linkTarget">Com: ${escapeHtml(linkedLanc?.desc || "lançamento do sistema")}${linkedMismatch ? ` • lançamento ${brl(Math.abs(Number(linkedLanc.valor || 0)))}` : ""}</div>`
      : suggestion
        ? `<label class="matchChoice"><input class="matchSelect" type="checkbox" data-bank-id="${t.id}" ${matchSelected ? "checked" : ""}><span class="badge ${suggestion.valueMismatch ? "bad" : "match"}">Match #${pairNumber} • ${escapeHtml(suggestion.reason || "Sugestão")} • ${suggestion.score}%</span></label><div class="linkTarget">Com: ${escapeHtml(suggestedLanc?.desc || "lançamento sugerido")}${suggestion.valueMismatch ? ` • lançamento ${brl(Math.abs(Number(suggestedLanc?.valor || 0)))}` : ""}</div>`
        : `<span class="badge warn">Sem vínculo</span><div class="linkTarget">Nenhum lançamento relacionado.</div>`;
    const classes = [
      "item",
      selectedBankTxId === t.id ? "selected" : "",
      suggestion ? "matchSuggested" : "",
      matchSelected ? "matchChosen" : ""
    ].filter(Boolean).join(" ");
    const signBadge = t.amount >= 0 ? `<span class="badge ok">CR</span>` : `<span class="badge bad">DB</span>`;
    return `
      <div class="${classes}" data-id="${t.id}" data-kind="bank">
        <div class="left">
          ${signBadge}
          <div>
            <div><b>${escapeHtml(t.memo || "")}</b></div>
            <div class="muted">${escapeHtml(t.date)} • ${escapeHtml(t.fitid || "")}</div>
          </div>
        </div>
        <div style="text-align:right">
          <div><b>${brl(Math.abs(t.amount))}</b></div>
          <div>${status}</div>
        </div>
      </div>
    `;
  }).join("") || (
    allBankTxs.length && !showReconciledItems
      ? `<div class="muted">Todas as transações deste extrato já estão vinculadas.</div>`
      : `<div class="muted">Selecione um extrato importado.</div>`
  );

  $("#sysList").innerHTML = lancs
    .slice()
    .sort((a,b)=> b.data.localeCompare(a.data))
    .map(l=>{
      const linkedBankId = reconByLanc.get(l.id);
      const linkedBank = bankById.get(linkedBankId);
      const suggestion = suggestionByLanc.get(l.id);
      const suggestedBank = bankById.get(suggestion?.bankTxId);
      const matchSelected = suggestion && selectedSuggestedBankTxIds.has(suggestion.bankTxId);
      const pairNumber = suggestion ? suggestionNumberByBank.get(suggestion.bankTxId) : null;
      const possibleDuplicate = possibleDuplicateByLanc.get(l.id);
      const sourceTitle = tituloByLancId.get(l.id);
      const linkedMismatch = linkedBank && bankTransactionValueDiffers(linkedBank, l);
      const status = linkedBankId
        ? `<span class="badge ${linkedMismatch ? "bad" : "ok"}">${linkedMismatch ? "Vinculado • valor divergente" : "Vinculado"}</span><div class="linkTarget">Com: ${escapeHtml(linkedBank?.memo || "transação bancária")}${linkedMismatch ? ` • banco ${brl(Math.abs(Number(linkedBank.amount || 0)))}` : ""}</div>`
        : suggestion
          ? `<label class="matchChoice"><input class="matchSelect" type="checkbox" data-bank-id="${suggestion.bankTxId}" ${matchSelected ? "checked" : ""}><span class="badge ${suggestion.valueMismatch ? "bad" : "match"}">Match #${pairNumber} • ${escapeHtml(suggestion.reason || "Sugestão")} • ${suggestion.score}%</span></label><div class="linkTarget">Com: ${escapeHtml(suggestedBank?.memo || "transação sugerida")}${suggestion.valueMismatch ? ` • banco ${brl(Math.abs(Number(suggestedBank?.amount || 0)))}` : ""}</div>`
          : possibleDuplicate
            ? `<span class="badge bad">Possível duplicado</span><div class="linkTarget">Já consta no banco: ${escapeHtml(possibleDuplicate.bankTx.date)} • ${escapeHtml(possibleDuplicate.bankTx.memo || "transação bancária")}</div>`
          : `<span class="badge warn">Sem vínculo</span><div class="linkTarget">Nenhuma transação relacionada.</div>`;
      const classes = [
        "item",
        selectedLancId === l.id ? "selected" : "",
        suggestion ? "matchSuggested" : "",
        matchSelected ? "matchChosen" : ""
      ].filter(Boolean).join(" ");
      const tipoBadge = lancamentoTipoBadge(l);
      return `
        <div class="${classes}" data-id="${l.id}" data-kind="sys">
          <div class="left">
            ${tipoBadge}
            <div>
              <div><b>${escapeHtml(l.desc || "")}</b></div>
              <div class="muted">${escapeHtml(l.data)} • ${escapeHtml(categoriaNamesText(getLancCategoriaIds(l), "-"))}</div>
              ${sourceTitle ? `<div class="linkTarget">Origem: título ${escapeHtml(sourceTitle.tipo || "")} • ${escapeHtml(sourceTitle.status || "")}</div>` : ""}
            </div>
          </div>
          <div style="text-align:right">
            <div><b>${brl(l.valor)}</b></div>
            <div>${status}</div>
          </div>
        </div>
      `;
    }).join("") || (
      allLancs.length && !showReconciledItems
        ? `<div class="muted">Não há lançamentos sem vínculo nesta conta.</div>`
        : `<div class="muted">Sem lançamentos nesta conta.</div>`
    );

  // Títulos em aberto (AP/AR)
  const titulosAbertos = state.titulos
    .filter(t => t.contaId===contaId && t.status==="ABERTO")
    .slice()
    .sort((a,b)=> a.vencimento.localeCompare(b.vencimento));

  $("#titList").innerHTML = titulosAbertos.map(t=>{
    const cls = (selectedTituloId===t.id) ? "item selected" : "item";
    const badge = (t.tipo==="AR") ? `<span class="badge ok">AR</span>` : `<span class="badge bad">AP</span>`;
    return `
      <div class="${cls}" data-id="${t.id}">
        <div class="left">
          ${badge}
          <div>
            <div><b>${escapeHtml(tituloDescricaoText(t))}</b></div>
            <div class="muted">${escapeHtml(t.vencimento)} • ${escapeHtml(t.pessoa||"-")}</div>
            ${categoriaBadgesHtml(getTituloCategoriaIds(t), "-")}
          </div>
        </div>
        <div style="text-align:right">
          <div><b>${brl(t.valor)}</b></div>
          <div class="muted">ABERTO</div>
        </div>
      </div>
    `;
  }).join("") || `<div class="muted">Nenhum título em aberto nesta conta.</div>`;

  $("#concStatus").textContent = buildConcStatus(contaId, imp);
  renderReconciliationMatchControls(linkedCount, divergentLinks.length);
}

function buildConcStatus(contaId, imp){
  if(!imp) return "Selecione um extrato importado.";
  const bankCount = imp.txs.length;
  const reconciled = imp.txs.filter(t => state.reconciliations.some(r => r.bankTxId === t.id)).length;
  const bankById = new Map(imp.txs.map(tx => [tx.id, tx]));
  const lancById = new Map(state.lancamentos.map(lanc => [lanc.id, lanc]));
  const divergent = state.reconciliations.filter(item => {
    const bankTx = bankById.get(item.bankTxId);
    const lanc = lancById.get(item.lancId);
    return bankTx && lanc && bankTransactionValueDiffers(bankTx, lanc);
  }).length;
  const suggested = [...suggestedReconciliationMatches.keys()].filter(bankTxId => imp.txs.some(tx => tx.id === bankTxId)).length;
  const withoutLink = Math.max(0, bankCount - reconciled - suggested);
  const source = [imp.format, imp.bank].filter(Boolean).join(" ") || "OFX";
  return `Importação: ${imp.fileName || source} • ${source} • ${bankCount} transações • ${reconciled} vinculadas • ${divergent} com valor divergente • ${suggested} matches aguardando confirmação • ${withoutLink} sem vínculo • Conta: ${state.contas.find(c=>c.id===contaId)?.nome || "-"}`;
}

$("#concConta").addEventListener("change", ()=>{
  selectedBankTxId = null;
  selectedLancId = null;
  selectedTituloId = null;
  resetReconciliationSuggestions();
  showReconciledItems = false;
  renderConciliacao();
});
$("#concImport").addEventListener("change", ()=>{
  selectedBankTxId = null;
  selectedLancId = null;
  selectedTituloId = null;
  resetReconciliationSuggestions();
  showReconciledItems = false;
  renderConciliacao();
});

$("#btnAlternarVinculados").addEventListener("click", ()=>{
  showReconciledItems = !showReconciledItems;
  selectedBankTxId = null;
  selectedLancId = null;
  renderConciliacao();
});

$("#btnCorrigirValores").addEventListener("click", async (event)=>{
  const imp = state.imports.find(item => item.id === $("#concImport").value);
  if(!imp) return alert("Selecione um extrato importado.");
  const bankById = new Map(imp.txs.map(tx => [tx.id, tx]));
  const pairs = state.reconciliations.filter(item => {
    const bankTx = bankById.get(item.bankTxId);
    const lanc = state.lancamentos.find(candidate => candidate.id === item.lancId);
    return bankTx && lanc && bankTransactionValueDiffers(bankTx, lanc);
  });
  if(!pairs.length) return alert("Não há valores divergentes neste extrato.");
  if(!confirmBankValueCorrections(pairs, imp)) return;

  const snapshot = cloneStateSnapshot();
  for(const pair of pairs){
    correctLancamentoFromBank(
      bankById.get(pair.bankTxId),
      state.lancamentos.find(item => item.id === pair.lancId)
    );
  }
  if(!await persistStateOrRollback(snapshot, { button: event.currentTarget })) return;
  showReconciledItems = false;
  renderAll();
  alert(`${pairs.length} lançamento(s) corrigido(s) com os valores do banco.`);
});

$("#btnIgnorarBankTx").addEventListener("click", async (event)=>{
  const contaId = $("#concConta").value;
  const bankTxId = selectedBankTxId;
  if(!bankTxId) return alert("Selecione uma transação bancária sem vínculo.");
  if(state.reconciliations.some(item => item.bankTxId === bankTxId)){
    return alert("Esta transação está vinculada. Desvincule-a antes de excluir.");
  }

  let bankTx = null;
  for(const imp of state.imports){
    if(imp.contaId !== contaId) continue;
    bankTx = (imp.txs || []).find(tx => tx.id === bankTxId) || bankTx;
  }
  if(!bankTx) return alert("Transação bancária não encontrada.");
  if(!confirm(
    `Excluir da conciliação a transação de ${bankTx.date}, no valor de ${brl(Math.abs(Number(bankTx.amount || 0)))}?\n\nEla será ignorada caso o mesmo arquivo seja importado novamente.`
  )) return;

  const snapshot = cloneStateSnapshot();
  const key = bankTransactionKey(contaId, bankTx);
  if(!state.ignoredBankTransactions.some(item => item.key === key)){
    state.ignoredBankTransactions.push({
      id: uid("ignored_bank"),
      contaId,
      key,
      fitid: bankTx.fitid || "",
      date: bankTx.date || "",
      amount: Number(bankTx.amount || 0),
      memo: bankTx.memo || "",
      ignoredAt: new Date().toISOString()
    });
  }
  for(const imp of state.imports){
    if(imp.contaId === contaId) imp.txs = (imp.txs || []).filter(tx => tx.id !== bankTxId);
  }
  resetReconciliationSuggestions();
  selectedBankTxId = null;
  if(!await persistStateOrRollback(snapshot, { button: event.currentTarget })) return;
  renderAll();
});

$("#btnExcluirLancConc").addEventListener("click", async (event)=>{
  const lancamentoId = selectedLancId;
  const lancamento = state.lancamentos.find(item => item.id === lancamentoId);
  if(!lancamento) return alert("Selecione um lançamento do sistema sem vínculo.");
  if(state.reconciliations.some(item => item.lancId === lancamentoId)){
    return alert("Este lançamento está vinculado. Desvincule-o antes de excluir.");
  }

  const linkedTitles = state.titulos.filter(titulo => titulo.lancId === lancamentoId);
  const deletableTitles = linkedTitles.filter(titulo => !getCompraByTituloId(titulo.id));
  const protectedTitles = linkedTitles.filter(titulo => getCompraByTituloId(titulo.id));
  const transferWarning = lancamento.transferenciaId
    ? "\n\nOs dois lados da transferência serão excluídos."
    : "";
  const titleWarning = [
    deletableTitles.length ? `${deletableTitles.length} título(s) de origem também serão excluídos para não recriar o lançamento.` : "",
    protectedTitles.length ? `${protectedTitles.length} título(s) originado(s) por Compras serão preservados e reabertos.` : ""
  ].filter(Boolean).map(message => `\n\n${message}`).join("");
  if(!confirm(
    `Excluir o lançamento ${lancamento.data} — ${lancamento.desc} — ${brl(Math.abs(Number(lancamento.valor || 0)))}?${transferWarning}${titleWarning}`
  )) return;

  const snapshot = cloneStateSnapshot();
  const result = await removeLancamentosFromState(lancamentoId, { deleteSourceTitles: true });
  selectedLancId = null;
  resetReconciliationSuggestions();
  if(!await persistStateOrRollback(snapshot, { button: event.currentTarget })) return;
  renderAll();
  const deletedTitles = result.deletedTitles ? ` ${result.deletedTitles} título(s) de origem foram excluídos.` : "";
  const reopened = result.reopenedTitles ? ` ${result.reopenedTitles} título(s) de Compras foram reabertos.` : "";
  alert(`${result.removed} lançamento(s) excluído(s).${deletedTitles}${reopened}`);
});

$("#btnExcluirTodosLancSemVinculo").addEventListener("click", async (event)=>{
  const contaId = $("#concConta").value;
  const conta = state.contas.find(item => item.id === contaId);
  const plan = unlinkedLancamentoDeletionPlan(contaId);
  if(!plan.selectedCount){
    const skipped = plan.skippedTransferCount
      ? " Há transferência(s) cujo outro lado está vinculado; elas foram preservadas."
      : "";
    return alert(`Não há lançamentos sem vínculo que possam ser excluídos nesta conta.${skipped}`);
  }

  const transferWarning = plan.transferCount
    ? `\n${plan.transferCount} transferência(s) estão entre os lançamentos e os dois lados serão excluídos (${plan.removedCount} registros no total).`
    : "";
  const deletedTitleWarning = plan.deletedTitles
    ? `\n${plan.deletedTitles} título(s) de origem também serão excluídos para não recriar estes lançamentos.`
    : "";
  const reopenedTitleWarning = plan.reopenedTitles
    ? `\n${plan.reopenedTitles} título(s) originado(s) por Compras serão preservados e reabertos.`
    : "";
  const skippedWarning = plan.skippedTransferCount
    ? `\n${plan.skippedTransferCount} transferência(s) serão preservadas porque o outro lado já está vinculado.`
    : "";
  if(!confirm(
    `Excluir ${plan.selectedCount} lançamento(s) sem vínculo da conta ${conta?.nome || "selecionada"}?\n` +
    `Impacto no saldo desta conta: ${brl(plan.netImpact)}.${transferWarning}${deletedTitleWarning}${reopenedTitleWarning}${skippedWarning}\n\n` +
    "Esta ação não exclui lançamentos já vinculados."
  )) return;

  const snapshot = cloneStateSnapshot();
  let removed = 0;
  let reopenedTitles = 0;
  let deletedTitles = 0;
  for(const lancamentoId of plan.roots){
    const result = await removeLancamentosFromState(lancamentoId, { deleteSourceTitles: true });
    removed += result.removed;
    reopenedTitles += result.reopenedTitles;
    deletedTitles += result.deletedTitles;
  }
  selectedLancId = null;
  resetReconciliationSuggestions();
  if(!await persistStateOrRollback(snapshot, { button: event.currentTarget })) return;
  renderAll();
  const deleted = deletedTitles ? ` ${deletedTitles} título(s) de origem foram excluídos.` : "";
  const reopened = reopenedTitles ? ` ${reopenedTitles} título(s) de Compras foram reabertos.` : "";
  alert(`${removed} lançamento(s) excluído(s).${deleted}${reopened}`);
});

$("#bankList").addEventListener("click", (e)=>{
  if(e.target.closest(".matchSelect")) return;
  const item = e.target.closest(".item");
  if(!item) return;
  selectedBankTxId = item.dataset.id;
  renderConciliacao();
});
$("#sysList").addEventListener("click", (e)=>{
  if(e.target.closest(".matchSelect")) return;
  const item = e.target.closest(".item");
  if(!item) return;
  selectedLancId = item.dataset.id;
  renderConciliacao();
});
function updateSelectedReconciliationMatch(event){
  const checkbox = event.target.closest(".matchSelect");
  if(!checkbox) return;
  if(checkbox.checked) selectedSuggestedBankTxIds.add(checkbox.dataset.bankId);
  else selectedSuggestedBankTxIds.delete(checkbox.dataset.bankId);
  renderConciliacao();
}
$("#bankList").addEventListener("change", updateSelectedReconciliationMatch);
$("#sysList").addEventListener("change", updateSelectedReconciliationMatch);
$("#titList").addEventListener("click",(e)=>{
  const item=e.target.closest(".item"); if(!item) return;
  selectedTituloId = item.dataset.id;
  renderConciliacao();
});

// Banco ↔ Lançamento manual (um par por vez)
$("#btnVincular").addEventListener("click", async (e)=>{
  const contaId = $("#concConta").value;
  const importId = $("#concImport").value;
  const imp = state.imports.find(i=>i.id===importId);

  if(!selectedBankTxId){
    alert("Selecione 1 item do banco.");
    return;
  }
  if(!imp){
    alert("Selecione um extrato importado.");
    return;
  }

  const bankTx = imp.txs.find(t=>t.id===selectedBankTxId);
  if(!bankTx){
    alert("Transação do banco não encontrada.");
    return;
  }
  if(!selectedLancId){
    alert("Selecione também 1 lançamento do sistema. Para criar lançamentos automaticamente, use o botão no topo da tela.");
    return;
  }

  const existingBankLink = state.reconciliations.find(r => r.bankTxId === selectedBankTxId);
  const existingLancLink = state.reconciliations.find(r => r.lancId === selectedLancId);
  if(existingBankLink || existingLancLink){
    if(existingBankLink?.lancId === selectedLancId && existingLancLink?.bankTxId === selectedBankTxId){
      alert("Este par já está vinculado.");
    }else{
      alert("Um dos itens já possui vínculo. Desvincule-o antes de criar outro par.");
    }
    return;
  }

  const l = state.lancamentos.find(x=>x.id===selectedLancId);
  if(!l) return alert("Lançamento do sistema não encontrado.");
  if(!bankTransactionTypeMatches(bankTx, l)){
    alert("Não é possível vincular crédito com despesa ou débito com receita.");
    return;
  }
  const pair = { bankTxId: selectedBankTxId, lancId: selectedLancId };
  if(!confirmBankValueCorrections([pair], imp)) return;

  const snapshot = cloneStateSnapshot();
  correctLancamentoFromBank(bankTx, l);
  reconcileBankTransactionWithLancamento(selectedBankTxId, selectedLancId);

  if(!await persistStateOrRollback(snapshot, { button: e.currentTarget })) return;
  selectedBankTxId = null;
  selectedLancId = null;
  showReconciledItems = false;
  renderAll();
});

$("#btnDesvincular").addEventListener("click", async (e)=>{
  if(!selectedBankTxId && !selectedLancId){
    alert("Selecione um item do banco OU um lançamento conciliado.");
    return;
  }
  const snapshot = cloneStateSnapshot();
  const before = state.reconciliations.length;
  state.reconciliations = state.reconciliations.filter(r => {
    if(selectedBankTxId && r.bankTxId === selectedBankTxId) return false;
    if(selectedLancId && r.lancId === selectedLancId) return false;
    return true;
  });

  if(state.reconciliations.length !== before){
    for(const l of state.lancamentos){
      if(selectedLancId && l.id === selectedLancId){
        l.conciliado = false; l.bankTxId = null;
      }
      if(selectedBankTxId && l.bankTxId === selectedBankTxId){
        l.conciliado = false; l.bankTxId = null;
      }
    }
    // também remove bankTxId de títulos que apontem para esse bankTx
    if(selectedBankTxId){
      for(const t of state.titulos){
        if(t.bankTxId === selectedBankTxId){
          t.bankTxId = null;
        }
      }
    }
    if(!await persistStateOrRollback(snapshot, { button: e.currentTarget })) return;
  }
  selectedBankTxId = null;
  selectedLancId = null;
  selectedTituloId = null;
  showReconciledItems = false;
  renderAll();
});

$("#btnSugerir").addEventListener("click", ()=>{
  const contaId = $("#concConta").value;
  const importId = $("#concImport").value;
  const imp = state.imports.find(i=>i.id===importId);
  if(!imp) return alert("Selecione um extrato importado.");
  suggestedReconciliationMatches = reconciliationSuggestions(contaId, imp);
  selectedSuggestedBankTxIds = new Set(suggestedReconciliationMatches.keys());
  selectedBankTxId = null;
  selectedLancId = null;
  renderConciliacao();
  if(!suggestedReconciliationMatches.size){
    alert("Nenhum match foi encontrado dentro das tolerâncias configuradas.");
  }
});

$("#btnSelecionarMatches").addEventListener("click", ()=>{
  const suggestionIds = [...suggestedReconciliationMatches.keys()];
  const allSelected = suggestionIds.length > 0
    && suggestionIds.every(id => selectedSuggestedBankTxIds.has(id));
  selectedSuggestedBankTxIds = allSelected ? new Set() : new Set(suggestionIds);
  renderConciliacao();
});

$("#btnVincularMatches").addEventListener("click", async (event)=>{
  const importId = $("#concImport").value;
  const imp = state.imports.find(item => item.id === importId);
  if(!imp) return alert("Selecione um extrato importado.");

  const bankIds = new Set(imp.txs.map(tx => tx.id));
  const reconBank = new Set(state.reconciliations.map(item => item.bankTxId));
  const reconLanc = new Set(state.reconciliations.map(item => item.lancId));
  const pairs = [...selectedSuggestedBankTxIds]
    .map(bankTxId => ({ bankTxId, ...suggestedReconciliationMatches.get(bankTxId) }))
    .filter(pair =>
      pair.lancId
      && bankIds.has(pair.bankTxId)
      && !reconBank.has(pair.bankTxId)
      && !reconLanc.has(pair.lancId)
    );
  if(!pairs.length) return alert("Marque pelo menos 1 match sugerido para vincular.");
  if(!confirmBankValueCorrections(pairs, imp)) return;

  const snapshot = cloneStateSnapshot();
  const bankById = new Map(imp.txs.map(tx => [tx.id, tx]));
  for(const pair of pairs){
    const lanc = state.lancamentos.find(item => item.id === pair.lancId);
    if(lanc){
      correctLancamentoFromBank(bankById.get(pair.bankTxId), lanc);
      reconcileBankTransactionWithLancamento(pair.bankTxId, pair.lancId);
    }
  }

  if(!await persistStateOrRollback(snapshot, { button: event.currentTarget })) return;
  resetReconciliationSuggestions();
  showReconciledItems = false;
  renderAll();
  alert(`${pairs.length} match(es) vinculados com sucesso.`);
});

function financialMatchFacts(bankTx, lanc, cfg){
  const bankAbs = Math.abs(Number(bankTx.amount||0));
  const sysAbs = Math.abs(Number(lanc.valor||0));
  const diffValue = Math.abs(bankAbs - sysAbs);
  const bankDate = parseISODate(bankTx.date);
  const lancDate = parseISODate(lanc.data);
  const diffDays = Math.abs(Math.round((bankDate - lancDate) / (1000*60*60*24)));
  const sameType = (Number(bankTx.amount||0) >= 0) === (lanc.tipo === "RECEITA");
  const descriptionOverlap = textOverlap(
    normalizeText(bankTx.memo || ""),
    normalizeText(lanc.desc || "")
  );
  return {
    diffValue,
    diffDays,
    sameType,
    descriptionOverlap,
    descriptionSimilar: descriptionOverlap > 0,
    valueWithinTolerance: diffValue <= Number(cfg.tolValor||0),
    dateWithinTolerance: Number.isFinite(diffDays) && diffDays <= Number(cfg.tolDias||0)
  };
}

function scoreMatch(bankTx, lanc, cfg){
  const facts = financialMatchFacts(bankTx, lanc, cfg);
  const scoreValor = facts.valueWithinTolerance ? 55 : clamp(55 - (facts.diffValue*20), 0, 55);

  const scoreData = facts.dateWithinTolerance ? 25 : clamp(25 - (facts.diffDays*6), 0, 25);
  const scoreTipo = facts.sameType ? 15 : 0;

  const scoreTxt = clamp(facts.descriptionOverlap * 10, 0, 5);

  return Math.round(scoreValor + scoreData + scoreTipo + scoreTxt);
}
function normalizeText(s){
  return String(s).toLowerCase()
    .normalize("NFD").replace(/\p{Diacritic}/gu,"")
    .replace(/[^a-z0-9\s]/g," ")
    .replace(/\s+/g," ")
    .trim();
}
function textOverlap(a,b){
  if(!a || !b) return 0;
  const sa = new Set(a.split(" ").filter(w=>w.length>=4));
  const sb = new Set(b.split(" ").filter(w=>w.length>=4));
  let hit = 0;
  for(const w of sa) if(sb.has(w)) hit++;
  return hit;
}

$("#btnCriarLancDoBanco").addEventListener("click", async (e)=>{
  const contaId = $("#concConta").value;
  const importId = $("#concImport").value;
  const imp = state.imports.find(i=>i.id===importId);
  if(!imp) return alert("Selecione um extrato importado.");

  const reconBank = new Set(state.reconciliations.map(r=>r.bankTxId));
  const claimedBank = new Set([
    ...state.lancamentos.map(lanc => lanc.bankTxId).filter(Boolean),
    ...state.titulos.map(title => title.bankTxId).filter(Boolean)
  ]);
  const pendingCandidates = imp.txs.filter(t => !reconBank.has(t.id) && !claimedBank.has(t.id));
  const suggestions = reconciliationSuggestions(contaId, imp);
  const pendBank = pendingCandidates.filter(t => !suggestions.has(t.id));
  const protectedMatches = pendingCandidates.length - pendBank.length;

  if(!pendBank.length){
    suggestedReconciliationMatches = suggestions;
    selectedSuggestedBankTxIds = new Set(suggestions.keys());
    renderConciliacao();
    return alert(protectedMatches
      ? `${protectedMatches} transação(ões) possuem match e não foram duplicadas. Revise e clique em "Vincular matches selecionados".`
      : "Não há transações pendentes sem vínculo ou título relacionado.");
  }

  const catDesp = state.categorias.find(c=>c.tipo==="DESPESA")?.id || state.categorias[0]?.id;
  const catRec = state.categorias.find(c=>c.tipo==="RECEITA")?.id || state.categorias[0]?.id;

  const snapshot = cloneStateSnapshot();
  let created = 0;
  for(const bt of pendBank){
    const isCredit = Number(bt.amount||0) >= 0;
    const tipo = isCredit ? "RECEITA" : "DESPESA";
    const categoriaId = isCredit ? catRec : catDesp;

    const lanc = {
      id: uid("lanc"),
      data: bt.date,
      contaId,
      tipo,
      categoriaId,
      categoriaIds: uniqueNonEmpty([categoriaId]),
      desc: bt.memo || "(importado do banco)",
      valor: Math.abs(Number(bt.amount||0)),
      conciliado: true,
      bankTxId: bt.id
    };
    state.lancamentos.unshift(lanc);
    state.reconciliations.push({ bankTxId: bt.id, lancId: lanc.id });
    created++;
  }

  if(!await persistStateOrRollback(snapshot, { button: e.currentTarget })) return;
  suggestedReconciliationMatches = suggestions;
  selectedSuggestedBankTxIds = new Set(suggestions.keys());
  showReconciledItems = false;
  renderAll();
  const protectedMessage = protectedMatches
    ? ` ${protectedMatches} transação(ões) com match foram preservadas para confirmação, sem criar duplicidade.`
    : "";
  alert(`Criados ${created} lançamento(s) a partir do extrato e marcados como conciliados.${protectedMessage}`);
});

/* ---------- AP/AR (Títulos) + anexos ---------- */
function novoTitulo({tipo, pessoa, desc, categoriaId, categoriaIds, contaId, valor, vencimento, centroCusto, obs, favorecidoId="", pixKeyType="TELEFONE", pixKey="", pixCity="", bankName="", bankAccountType="CORRENTE", bankAgency="", bankAccount=""}){
  const tituloCategoriaIds = uniqueNonEmpty(Array.isArray(categoriaIds) && categoriaIds.length ? categoriaIds : [categoriaId]);
  return {
    id: uid("tit"),
    tipo,
    pessoa: (pessoa||"").trim(),
    desc: (desc||"").trim(),
    categoriaId: tituloCategoriaIds[0] || "",
    categoriaIds: tituloCategoriaIds,
    contaId,
    valor: Number(valor),
    vencimento,
    centroCusto: (centroCusto||"").trim(),
    obs: (obs||"").trim(),
    status: "ABERTO",
    baixadoEm: null,
    lancId: null,
    bankTxId: null,
    favorecidoId,
    pixKeyType,
    pixKey: String(pixKey || "").trim(),
    pixCity: String(pixCity || "").trim(),
    bankName: String(bankName || "").trim(),
    bankAccountType,
    bankAgency: String(bankAgency || "").trim(),
    bankAccount: String(bankAccount || "").trim(),
    anexos: []
  };
}

function tituloLancamentoPayload(titulo, dataBaixaISO){
  const isAR = titulo.tipo === "AR";
  const categoriaIds = getTituloCategoriaIds(titulo);
  const desc = tituloDescricaoText(titulo);
  return {
    data: dataBaixaISO,
    contaId: titulo.contaId,
    tipo: isAR ? "RECEITA" : "DESPESA",
    categoriaId: categoriaIds[0] || titulo.categoriaId || "",
    categoriaIds,
    desc: `${desc}${titulo.pessoa ? " - " + titulo.pessoa : ""}`,
    valor: Math.abs(Number(titulo.valor||0)),
    conciliado: !!titulo.bankTxId,
    bankTxId: titulo.bankTxId || null
  };
}

function contaIdFromBankTx(bankTxId){
  if(!bankTxId) return "";
  for(const imp of state.imports){
    if((imp.txs || []).some(tx => tx.id === bankTxId)) return imp.contaId || "";
  }
  return "";
}

function ensureTituloBankTxConta(titulo){
  if(!titulo.bankTxId) return;
  const bankContaId = contaIdFromBankTx(titulo.bankTxId);
  if(bankContaId && bankContaId !== titulo.contaId){
    state.reconciliations = state.reconciliations.filter(r => r.bankTxId !== titulo.bankTxId);
    titulo.bankTxId = null;
  }
}

function syncTituloLancamento(titulo){
  if(!titulo.lancId) return null;
  const lanc = state.lancamentos.find(l => l.id === titulo.lancId);
  if(!lanc){
    titulo.lancId = null;
    return null;
  }

  ensureTituloBankTxConta(titulo);
  const bankConflict = titulo.bankTxId && state.reconciliations.find(item =>
    item.bankTxId === titulo.bankTxId && item.lancId !== lanc.id
  );
  if(bankConflict){
    throw new Error("Esta transação bancária já está vinculada a outro lançamento. Desvincule o par atual antes de alterar este título.");
  }
  Object.assign(lanc, tituloLancamentoPayload(titulo, titulo.baixadoEm || lanc.data || toISODate(new Date())));

  state.reconciliations = state.reconciliations.filter(r => r.lancId !== lanc.id);
  if(titulo.bankTxId){
    state.reconciliations = state.reconciliations.filter(r => r.bankTxId !== titulo.bankTxId);
    state.reconciliations.push({ bankTxId: titulo.bankTxId, lancId: lanc.id });
  }

  return lanc;
}

function desfazerBaixaTituloRecord(titulo){
  if(titulo.lancId){
    const lancId = titulo.lancId;
    state.reconciliations = state.reconciliations.filter(r => r.lancId !== lancId);
    state.lancamentos = state.lancamentos.filter(l => l.id !== lancId);
  }

  titulo.lancId = null;
  titulo.baixadoEm = null;
}

function criarLancamentoDaBaixa(titulo, dataBaixaISO){
  ensureTituloBankTxConta(titulo);
  const bankConflict = titulo.bankTxId && state.reconciliations.find(item => item.bankTxId === titulo.bankTxId);
  if(bankConflict){
    throw new Error("Esta transação bancária já está vinculada a outro lançamento. O título não pode gerar uma duplicidade.");
  }
  const lanc = {
    id: uid("lanc"),
    ...tituloLancamentoPayload(titulo, dataBaixaISO)
  };

  state.lancamentos.unshift(lanc);
  titulo.lancId = lanc.id;
  titulo.baixadoEm = dataBaixaISO;

  if(titulo.bankTxId){
    state.reconciliations = state.reconciliations.filter(r => r.bankTxId !== titulo.bankTxId && r.lancId !== lanc.id);
    state.reconciliations.push({ bankTxId: titulo.bankTxId, lancId: lanc.id });
  }

  return lanc;
}

function aplicarStatusTitulo(titulo, statusDesejado, dataBaixaISO=null){
  if(statusDesejado === "BAIXADO"){
    titulo.status = "BAIXADO";
    const data = dataBaixaISO || titulo.baixadoEm || toISODate(new Date());
    if(titulo.lancId){
      titulo.baixadoEm = data;
      const lanc = syncTituloLancamento(titulo);
      if(lanc) return lanc;
    }
    return criarLancamentoDaBaixa(titulo, data);
  }

  if(titulo.lancId){
    desfazerBaixaTituloRecord(titulo);
  }
  titulo.status = statusDesejado || "ABERTO";
  titulo.baixadoEm = null;
  return null;
}

function baixarTitulo(tituloId, dataBaixaISO=null){
  const t = state.titulos.find(x=>x.id===tituloId);
  if(!t) throw new Error("Título não encontrado.");
  if(t.status !== "ABERTO") throw new Error("Título não está em aberto.");

  const data = dataBaixaISO || toISODate(new Date());

  aplicarStatusTitulo(t, "BAIXADO", data);
  return state.lancamentos.find(l => l.id === t.lancId) || null;
}

function syncTituloFromLancamento(lancamento){
  const titulo = state.titulos.find(t => t.lancId === lancamento.id);
  if(!titulo) return;

  const categoriaIds = getLancCategoriaIds(lancamento);
  titulo.contaId = lancamento.contaId;
  titulo.categoriaId = categoriaIds[0] || lancamento.categoriaId;
  titulo.categoriaIds = categoriaIds;
  titulo.tipo = lancamento.tipo === "RECEITA" ? "AR" : "AP";
  titulo.valor = Math.abs(Number(lancamento.valor || 0));
  titulo.status = "BAIXADO";
  titulo.baixadoEm = lancamento.data;
  titulo.bankTxId = lancamento.bankTxId || titulo.bankTxId || null;
}

function vincularBankTxAoTitulo({tituloId, bankTxId, bankDateISO}){
  const t = state.titulos.find(x=>x.id===tituloId);
  if(!t) throw new Error("Título não encontrado.");
  if(t.bankTxId && t.bankTxId !== bankTxId){
    throw new Error("Este título já possui outra transação bancária vinculada.");
  }
  const existingBankLink = state.reconciliations.find(item => item.bankTxId === bankTxId);
  if(existingBankLink && existingBankLink.lancId !== t.lancId){
    throw new Error("Esta transação bancária já está vinculada a outro lançamento. Desvincule o par atual antes de vinculá-la ao título.");
  }

  t.bankTxId = bankTxId;

  if(t.lancId){
    const l = state.lancamentos.find(x=>x.id===t.lancId);
    if(l){
      l.conciliado = true;
      l.bankTxId = bankTxId;
    }
  } else {
    baixarTitulo(tituloId, bankDateISO);
  }

  const lancId = t.lancId;
  if(lancId){
    state.reconciliations = state.reconciliations.filter(r => r.bankTxId !== bankTxId && r.lancId !== lancId);
    state.reconciliations.push({ bankTxId, lancId });
  }
}

async function detectCodesFromAttachment(anexo){
  const box = $("#anexoCodePreview");
  if(!box) return;

  if(!anexo){
    box.textContent = "Selecione uma imagem ou PDF para tentar ler QR Code, linha digitavel ou codigo de barras.";
    return;
  }
  const mime = anexo.mime || "";
  const isImage = mime.startsWith("image/");
  const isPdf = mime.includes("pdf");
  if(!isImage && !isPdf){
    box.textContent = "A leitura automatica esta disponivel para anexos de imagem e PDF.";
    return;
  }

  try{
    box.textContent = isPdf ? "Lendo codigo do PDF..." : "Lendo codigo da imagem...";
    const payload = await requestJson("/api/finance/attachments/decode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path: anexo.path || "",
        dataUrl: anexo.path ? "" : (anexo.dataUrl || ""),
        mime: anexo.mime || ""
      })
    });
    const results = payload?.codes || [];

    if(!results.length){
      box.textContent = isPdf
        ? "Nenhum QR Code, linha digitavel ou codigo de barras foi encontrado nas primeiras paginas do PDF."
        : "Nenhum QR Code ou codigo de barras foi encontrado na imagem.";
      return;
    }

    box.innerHTML = results.map((result, index)=>`
      <div class="item">
        <div class="left" style="flex:1">
          <span class="badge">${escapeHtml(result.format || `COD ${index + 1}`)}</span>
          <div style="min-width:0">
            <div><b>${escapeHtml(result.rawValue || "(sem valor)")}</b></div>
          </div>
        </div>
      </div>
    `).join("");
  }catch(err){
    console.warn("Falha ao ler codigo do anexo:", err);
    box.textContent = "Nao foi possivel ler QR Code, linha digitavel ou codigo de barras deste anexo.";
  }
}

function similarTitleForBankTransaction(contaId, bankTx){
  const expectedType = Number(bankTx.amount || 0) >= 0 ? "AR" : "AP";
  if(!isValidDateISO(bankTx.date)) return null;
  const bankDate = parseISODate(bankTx.date);
  return state.titulos.find(title => {
    if(title.contaId !== contaId || title.tipo !== expectedType || title.bankTxId) return false;
    if(Math.abs(Math.abs(Number(title.valor || 0)) - Math.abs(Number(bankTx.amount || 0))) > Number(state.config.tolValor || 0)) return false;
    const titleDateISO = title.baixadoEm || title.vencimento;
    if(!isValidDateISO(titleDateISO)) return false;
    const titleDate = parseISODate(titleDateISO);
    const diffDays = Math.abs(Math.round((bankDate - titleDate) / (1000 * 60 * 60 * 24)));
    return Number.isFinite(diffDays) && diffDays <= Number(state.config.tolDias || 0);
  }) || null;
}

function criarTitulosDoOFX({contaId, importId}){
  const imp = state.imports.find(i=>i.id===importId);
  if(!imp) throw new Error("Import OFX não encontrado.");

  const existentes = new Set(state.titulos.filter(t=>t.bankTxId).map(t=>t.bankTxId));
  const vinculados = new Set([
    ...state.reconciliations.map(item => item.bankTxId),
    ...state.lancamentos.map(item => item.bankTxId).filter(Boolean)
  ]);

  const catDesp = state.categorias.find(c=>c.tipo==="DESPESA")?.id || state.categorias[0]?.id;
  const catRec  = state.categorias.find(c=>c.tipo==="RECEITA")?.id  || state.categorias[0]?.id;

  let created = 0;
  let skippedLinked = 0;
  let skippedSimilar = 0;
  for(const bt of imp.txs){
    if(existentes.has(bt.id)) continue;
    if(vinculados.has(bt.id)){
      skippedLinked++;
      continue;
    }
    if(similarTitleForBankTransaction(contaId, bt)){
      skippedSimilar++;
      continue;
    }

    const isCredit = Number(bt.amount||0) >= 0;
    const tipo = isCredit ? "AR" : "AP";

    const t = novoTitulo({
      tipo,
      pessoa: "",
      desc: bt.memo || "(importado do banco)",
      categoriaId: isCredit ? catRec : catDesp,
      contaId,
      valor: Math.abs(Number(bt.amount||0)),
      vencimento: bt.date,
      centroCusto: "",
      obs: ""
    });

    // já salva o bankTx no título (você pode baixar depois ou vincular direto)
    t.bankTxId = bt.id;

    state.titulos.unshift(t);
    created++;
  }
  return { created, skippedLinked, skippedSimilar };
}

// Conciliação: Banco ↔ Título
$("#btnVincularTitulo").addEventListener("click", async (e)=>{
  const contaId = $("#concConta").value;
  const importId = $("#concImport").value;
  const imp = state.imports.find(i=>i.id===importId);
  if(!imp) return alert("Selecione um extrato importado.");
  if(!selectedBankTxId) return alert("Selecione 1 transação do banco.");
  if(!selectedTituloId) return alert("Selecione 1 título (AP/AR) em aberto.");

  const bt = imp.txs.find(t=>t.id===selectedBankTxId);
  if(!bt) return alert("Transação do banco não encontrada.");
  const titulo = state.titulos.find(item => item.id === selectedTituloId);
  if(!titulo) return alert("Título não encontrado.");
  const expectedType = Number(bt.amount || 0) >= 0 ? "AR" : "AP";
  if(titulo.tipo !== expectedType){
    return alert("Não é possível vincular um crédito bancário a AP ou um débito bancário a AR.");
  }
  if(Math.abs(Math.abs(Number(bt.amount || 0)) - Math.abs(Number(titulo.valor || 0))) > 0.005){
    if(!confirm(
      `Os valores são diferentes:\n\nBanco: ${brl(Math.abs(Number(bt.amount || 0)))}\nTítulo: ${brl(Math.abs(Number(titulo.valor || 0)))}\n\nO valor do banco será considerado correto e atualizará o título. Deseja continuar?`
    )) return;
  }

  try{
    const snapshot = cloneStateSnapshot();
    titulo.valor = Math.abs(Number(bt.amount || 0));
    vincularBankTxAoTitulo({ tituloId: selectedTituloId, bankTxId: bt.id, bankDateISO: bt.date });
    if(!await persistStateOrRollback(snapshot, { button: e.currentTarget })) return;
    selectedBankTxId = null;
    selectedTituloId = null;
    selectedLancId = null;
    resetReconciliationSuggestions();
    showReconciledItems = false;
    renderAll();
    alert("Vinculado ao título, baixado e lançamento gerado/conciliado.");
  }catch(err){
    alert(err?.message || "Falha ao vincular ao título.");
  }
});

$("#btnCriarTitulosDoOFX").addEventListener("click", async (e)=>{
  const contaId = $("#concConta").value;
  const importId = $("#concImport").value;
  if(!importId) return alert("Selecione um extrato importado.");
  const snapshot = cloneStateSnapshot();
  const result = criarTitulosDoOFX({contaId, importId});
  if(!result.created){
    const protectedCount = result.skippedLinked + result.skippedSimilar;
    return alert(protectedCount
      ? `${protectedCount} transação(ões) já possuem vínculo ou título similar e não foram duplicadas.`
      : "Não há novas transações para criar títulos.");
  }
  if(!await persistStateOrRollback(snapshot, { button: e.currentTarget })) return;
  renderAll();
  const protectedCount = result.skippedLinked + result.skippedSimilar;
  const protectedMessage = protectedCount
    ? ` ${protectedCount} transação(ões) já vinculadas ou similares foram preservadas sem duplicar.`
    : "";
  alert(`Criados ${result.created} título(s) a partir do extrato.${protectedMessage}`);
});

/* ---------- Compras ---------- */
let editCompraId = null;
const COMPRA_AI_CATEGORY_META = {
  melhor_preco: { title: "Melhor preco", cardClass: "best" },
  custo_beneficio: { title: "Custo-beneficio", cardClass: "value" },
  alternativa: { title: "Alternativas", cardClass: "" }
};
let compraAiState = defaultCompraAiState();

function defaultCompraAiState(){
  return {
    loading: false,
    error: "",
    query: "",
    summary: "",
    offers: [],
    sources: [],
    generatedAt: "",
    model: "",
    selectedOfferIndex: -1,
    selectedOffer: null
  };
}

function resetCompraAiState(){
  compraAiState = defaultCompraAiState();
}

function cloneCompraAiPayload(item){
  if(!item || typeof item !== "object") return null;
  try{
    return JSON.parse(JSON.stringify(item));
  }catch{
    return null;
  }
}

function buildPersistedCompraAiState(aiState){
  const persisted = {
    query: String(aiState?.query || "").trim(),
    summary: String(aiState?.summary || "").trim(),
    offers: Array.isArray(aiState?.offers) ? aiState.offers.map(cloneCompraAiPayload).filter(Boolean) : [],
    sources: Array.isArray(aiState?.sources) ? aiState.sources.map(cloneCompraAiPayload).filter(Boolean) : [],
    generatedAt: String(aiState?.generatedAt || "").trim(),
    model: String(aiState?.model || "").trim(),
    selectedOfferIndex: Number.isInteger(aiState?.selectedOfferIndex) ? aiState.selectedOfferIndex : -1,
    selectedOffer: cloneCompraAiPayload(aiState?.selectedOffer)
  };

  const hasContent = !!(
    persisted.query ||
    persisted.summary ||
    persisted.offers.length ||
    persisted.sources.length ||
    persisted.generatedAt ||
    persisted.model ||
    persisted.selectedOffer
  );

  return hasContent ? persisted : null;
}

function hydrateCompraAiState(savedState){
  const persisted = buildPersistedCompraAiState(savedState);
  return persisted ? { ...defaultCompraAiState(), ...persisted } : defaultCompraAiState();
}

function normalizeCompraRecord(compra){
  if(!compra || typeof compra !== "object") return compra;
  return {
    ...compra,
    aiResearch: buildPersistedCompraAiState(compra.aiResearch)
  };
}

function isSelectedCompraAiOffer(offer, index){
  if(index === compraAiState.selectedOfferIndex) return true;

  const selectedOffer = compraAiState.selectedOffer;
  if(!selectedOffer || typeof selectedOffer !== "object") return false;

  if(selectedOffer.url && offer?.url){
    return selectedOffer.url === offer.url;
  }

  return selectedOffer.title === offer?.title && selectedOffer.store === offer?.store;
}

function novoPedidoCompra({requestedAt, desc, fornecedor, produtoUrl, fotoUrl, justificativa, categoriaId, contaId, centroCusto, valor, vencimento, formaPagamento, obs, aiResearch}){
  return {
    id: uid("compra"),
    requestedAt,
    status: "PENDENTE",
    desc: (desc || "").trim(),
    fornecedor: (fornecedor || "").trim(),
    produtoUrl: (produtoUrl || "").trim(),
    fotoUrl: (fotoUrl || "").trim(),
    justificativa: (justificativa || "").trim(),
    categoriaId,
    contaId,
    centroCusto: (centroCusto || "").trim(),
    valor: Number(valor),
    vencimento,
    formaPagamento: (formaPagamento || "").trim(),
    obs: (obs || "").trim(),
    aiResearch: buildPersistedCompraAiState(aiResearch),
    titleId: null,
    approvedAt: null,
    rejectedAt: null
  };
}

function compraStatusBadge(status){
  if(status === "APROVADO") return `<span class="badge ok">APROVADO</span>`;
  if(status === "REPROVADO") return `<span class="badge bad">REPROVADO</span>`;
  if(status === "CANCELADO") return `<span class="badge bad">CANCELADO</span>`;
  return `<span class="badge warn">PENDENTE</span>`;
}

function buildCompraTituloObs(compra){
  return buildTitleObs("", {
    compraId: compra.id,
    produtoUrl: compra.produtoUrl,
    justificativaCompra: compra.justificativa
  });
}

function compraTituloDescricao(compra){
  return appendTextToDescription(compra.desc, compra.obs);
}

function gerarTituloDaCompra(compra){
  const titulo = novoTitulo({
    tipo: "AP",
    pessoa: compra.fornecedor,
    desc: compraTituloDescricao(compra),
    categoriaId: compra.categoriaId,
    categoriaIds: uniqueNonEmpty([compra.categoriaId]),
    contaId: compra.contaId,
    valor: compra.valor,
    vencimento: compra.vencimento,
    centroCusto: "",
    obs: buildCompraTituloObs(compra)
  });
  titulo.status = "ABERTO";
  state.titulos.unshift(titulo);
  return titulo;
}

function syncCompraToTitulo(compra){
  if(!compra.titleId) return;
  const titulo = state.titulos.find(t => t.id === compra.titleId);
  if(!titulo) return;

  titulo.contaId = compra.contaId;
  titulo.categoriaId = compra.categoriaId;
  titulo.categoriaIds = uniqueNonEmpty([compra.categoriaId]);
  titulo.pessoa = compra.fornecedor;
  titulo.desc = compraTituloDescricao(compra);
  titulo.valor = compra.valor;
  titulo.vencimento = compra.vencimento;
  titulo.centroCusto = "";
  titulo.obs = buildCompraTituloObs(compra);
  if(titulo.status === "BAIXADO") syncTituloLancamento(titulo);
}

function aprovarCompra(compraId){
  const compra = state.compras.find(c => c.id === compraId);
  if(!compra) throw new Error("Solicitacao de compra nao encontrada.");

  if(!compra.titleId){
    const titulo = gerarTituloDaCompra(compra);
    compra.titleId = titulo.id;
  } else {
    syncCompraToTitulo(compra);
  }

  compra.status = "APROVADO";
  compra.approvedAt = nowIsoLocal();
  compra.rejectedAt = null;
}

function reprovarCompra(compraId){
  const compra = state.compras.find(c => c.id === compraId);
  if(!compra) throw new Error("Solicitacao de compra nao encontrada.");
  if(compra.titleId) throw new Error("Nao e possivel reprovar uma solicitacao que ja gerou contas a pagar.");
  compra.status = "REPROVADO";
  compra.rejectedAt = nowIsoLocal();
  compra.approvedAt = null;
}

function cancelarCompra(compraId){
  const compra = state.compras.find(c => c.id === compraId);
  if(!compra) throw new Error("Solicitacao de compra nao encontrada.");
  if(compra.titleId) throw new Error("Nao e possivel cancelar uma solicitacao ja aprovada.");
  compra.status = "CANCELADO";
  compra.rejectedAt = null;
  compra.approvedAt = null;
}

function nowIsoLocal(){
  return new Date().toISOString();
}

function openTituloDaCompra(compraId){
  const compra = state.compras.find(c => c.id === compraId);
  if(!compra?.titleId) return;
  setView("pagar");
  openTituloModal(compra.titleId, "AP");
}

function renderCompraPreview(){
  const fotoBox = $("#compraFotoPreview");
  const linkBox = $("#compraLinkPreview");
  const statusBox = $("#compraStatusInfo");
  if(!fotoBox || !linkBox || !statusBox) return;

  const fotoUrl = ($("#pcFotoUrl").value || "").trim();
  const produtoUrl = ($("#pcProdutoUrl").value || "").trim();
  const compra = editCompraId ? state.compras.find(c => c.id === editCompraId) : null;

  fotoBox.innerHTML = fotoUrl
    ? `<img src="${escapeHtml(fotoUrl)}" alt="produto" onerror="this.replaceWith(document.createTextNode('Nao foi possivel carregar a foto informada.'))" />`
    : `Informe uma URL de imagem para visualizar a foto do produto.`;

  linkBox.innerHTML = produtoUrl
    ? `<a href="${escapeHtml(produtoUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(produtoUrl)}</a>`
    : `Informe o link do produto para facilitar a aprovacao.`;

  statusBox.textContent = compra?.titleId
    ? "Esta solicitacao ja gerou um contas a pagar. Alteracoes salvas aqui atualizam o titulo vinculado."
    : "A solicitacao nasce como pendente. A aprovacao gera automaticamente um titulo em contas a pagar.";
}

function renderCompraAiResults(){
  const btn = $("#btnPesquisaIA");
  const statusBox = $("#compraAiStatus");
  const resultsBox = $("#compraAiResultados");
  if(!statusBox || !resultsBox) return;

  if(btn){
    btn.disabled = compraAiState.loading;
    btn.textContent = compraAiState.loading ? "Pesquisando..." : "Pesquisa I.A";
  }

  if(compraAiState.loading){
    statusBox.textContent = "Varrendo lojas online e organizando ofertas por faixa de preco e aderencia.";
    resultsBox.innerHTML = `<div class="muted">Aguarde um instante, o motor Python esta pesquisando na web.</div>`;
    return;
  }

  if(compraAiState.error){
    statusBox.textContent = compraAiState.error;
    resultsBox.innerHTML = `<div class="muted">${escapeHtml(compraAiState.error)}</div>`;
    return;
  }

  if(!compraAiState.offers.length){
    statusBox.textContent = "Descreva o item e clique em Pesquisa I.A para comparar opcoes.";
    resultsBox.innerHTML = `<div class="muted">Nenhuma pesquisa realizada ainda.</div>`;
    return;
  }

  statusBox.textContent = `${compraAiState.offers.length} oferta(s) encontrada(s). Escolha uma opcao para preencher a solicitacao.`;

  const groups = Object.keys(COMPRA_AI_CATEGORY_META)
    .map(category => ({
      category,
      meta: COMPRA_AI_CATEGORY_META[category],
      items: compraAiState.offers
        .map((offer, index) => ({ offer, index }))
        .filter(entry => entry.offer.category === category)
    }))
    .filter(group => group.items.length);

  const summaryHtml = compraAiState.summary
    ? `<div class="aiSummary">${escapeHtml(compraAiState.summary)}</div>`
    : "";

  const queryHtml = compraAiState.query
    ? `<div class="muted" style="margin-top:8px">Consulta: <b>${escapeHtml(compraAiState.query)}</b></div>`
    : "";

  const groupsHtml = groups.map(group => `
    <section class="aiGroup">
      <div class="aiGroupTitle">${escapeHtml(group.meta.title)}</div>
      <div class="aiOfferList">
        ${group.items.map(({offer, index}) => {
          const priceValue = Number(offer.priceValue || 0);
          const priceLabel = priceValue > 0 ? brl(priceValue) : (offer.priceText || "Preco nao informado");
          const cardClasses = ["aiOfferCard"];
          const isSelected = isSelectedCompraAiOffer(offer, index);
          if(group.meta.cardClass) cardClasses.push(group.meta.cardClass);
          if(isSelected) cardClasses.push("selected");
          return `
            <article class="${cardClasses.join(" ")}">
              <div class="aiOfferHead">
                <div>
                  <h4 class="aiOfferTitle">${escapeHtml(offer.title || "Oferta encontrada")}</h4>
                  <div class="aiOfferStore">${escapeHtml(offer.store || "Loja nao informada")}</div>
                </div>
                <div>
                  ${isSelected ? `<div class="badge ok" style="margin-bottom:6px">Oferta selecionada</div>` : ""}
                  <div class="aiOfferPrice">${escapeHtml(priceLabel)}</div>
                </div>
              </div>
              <div class="aiOfferReason">${escapeHtml(offer.reason || "Link sugerido pela Pesquisa I.A.")}</div>
              <div class="aiOfferActions">
                <a class="btn" href="${escapeHtml(offer.url || "#")}" target="_blank" rel="noopener noreferrer">Abrir link</a>
                <button class="btn primary" type="button" data-act="useAiOffer" data-idx="${index}">${isSelected ? "Oferta aplicada" : "Usar esta oferta"}</button>
              </div>
            </article>
          `;
        }).join("")}
      </div>
    </section>
  `).join("");

  const sourcesHtml = Array.isArray(compraAiState.sources) && compraAiState.sources.length
    ? `
      <div class="aiSources">
        <div class="muted"><b>Fontes consultadas</b></div>
        <ul>
          ${compraAiState.sources.map(source => `
            <li><a href="${escapeHtml(source.url || "#")}" target="_blank" rel="noopener noreferrer">${escapeHtml(source.title || source.url || "Fonte")}</a></li>
          `).join("")}
        </ul>
      </div>
    `
    : "";

  resultsBox.innerHTML = `${queryHtml}${summaryHtml}${groupsHtml}${sourcesHtml}`;
}

async function pesquisarCompraComIA(){
  const draft = currentCompraDraft();
  if((draft.desc || "").trim().length < 3){
    alert("Descreva o produto ou servico antes de usar a Pesquisa I.A.");
    return;
  }

  compraAiState = {
    ...defaultCompraAiState(),
    loading: true
  };
  renderCompraAiResults();

  try{
    const payload = await requestJson("/api/finance/purchase-research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        desc: draft.desc,
        fornecedor: draft.fornecedor,
        justificativa: draft.justificativa,
        obs: draft.obs,
        produtoUrl: draft.produtoUrl
      })
    });

    compraAiState = {
      ...defaultCompraAiState(),
      query: payload?.query || draft.desc,
      summary: payload?.summary || "",
      offers: Array.isArray(payload?.offers) ? payload.offers : [],
      sources: Array.isArray(payload?.sources) ? payload.sources : [],
      generatedAt: payload?.generatedAt || "",
      model: payload?.model || ""
    };
  }catch(err){
    compraAiState = {
      ...defaultCompraAiState(),
      error: err?.message || "Nao foi possivel executar a Pesquisa I.A."
    };
  }

  renderCompraAiResults();
}

function aplicarOfertaPesquisaIA(index){
  const offer = compraAiState.offers[index];
  if(!offer) return;

  compraAiState.selectedOfferIndex = index;
  compraAiState.selectedOffer = cloneCompraAiPayload(offer);

  $("#pcFornecedor").value = offer.store || $("#pcFornecedor").value;
  $("#pcProdutoUrl").value = offer.url || $("#pcProdutoUrl").value;

  const priceValue = Number(offer.priceValue || 0);
  if(Number.isFinite(priceValue) && priceValue > 0){
    $("#pcValor").value = String(priceValue);
  }
  if(!$("#pcDesc").value.trim()){
    $("#pcDesc").value = offer.title || "";
  }

  renderCompraPreview();
  renderCompraAiResults();
}

function openCompraModal(id=null){
  editCompraId = id;
  resetCompraAiState();
  $("#modalCompra").classList.remove("hidden");
  $("#modalCompraTitle").textContent = id ? "Editar solicitacao de compra" : "Nova solicitacao de compra";

  const compra = id ? state.compras.find(c => c.id === id) : null;
  $("#pcData").value = compra?.requestedAt ? String(compra.requestedAt).slice(0, 10) : toISODate(new Date());
  $("#pcFornecedor").value = compra?.fornecedor || "";
  $("#pcDesc").value = compra?.desc || "";
  $("#pcProdutoUrl").value = compra?.produtoUrl || "";
  $("#pcFotoUrl").value = compra?.fotoUrl || "";
  $("#pcJustificativa").value = compra?.justificativa || "";
  $("#pcConta").value = compra?.contaId || $("#pcConta").value;
  $("#pcCategoria").value = compra?.categoriaId || $("#pcCategoria").value;
  $("#pcVenc").value = compra?.vencimento || toISODate(new Date());
  $("#pcValor").value = compra ? Number(compra.valor || 0) : "";
  $("#pcObs").value = compra?.obs || "";
  if(compra?.aiResearch){
    compraAiState = hydrateCompraAiState(compra.aiResearch);
  }
  renderCompraPreview();
  renderCompraAiResults();
}

function closeCompraModal(){
  $("#modalCompra").classList.add("hidden");
  resetCompraAiState();
  renderCompraAiResults();
  editCompraId = null;
}

function currentCompraDraft(){
  return {
    requestedAt: ($("#pcData").value || toISODate(new Date())) + "T00:00:00",
    fornecedor: $("#pcFornecedor").value.trim(),
    desc: $("#pcDesc").value.trim(),
    produtoUrl: $("#pcProdutoUrl").value.trim(),
    fotoUrl: $("#pcFotoUrl").value.trim(),
    justificativa: $("#pcJustificativa").value.trim(),
    contaId: $("#pcConta").value,
    categoriaId: $("#pcCategoria").value,
    centroCusto: "",
    formaPagamento: "",
    vencimento: $("#pcVenc").value,
    valor: Number($("#pcValor").value),
    obs: $("#pcObs").value.trim(),
    aiResearch: buildPersistedCompraAiState(compraAiState)
  };
}

function renderCompras(){
  const tb = $("#tbCompras");
  if(!tb) return;

  const filtroStatus = $("#cpStatus").value || "ALL";
  const busca = ($("#cpBusca").value || "").trim().toLowerCase();
  const contaById = new Map(state.contas.map(c => [c.id, c]));

  let list = [...state.compras];
  if(filtroStatus !== "ALL") list = list.filter(c => c.status === filtroStatus);
  if(busca){
    list = list.filter(c => `${c.desc} ${c.fornecedor} ${c.justificativa}`.toLowerCase().includes(busca));
  }

  list.sort((a, b)=> String(b.requestedAt || "").localeCompare(String(a.requestedAt || "")));

  tb.innerHTML = list.map(compra=>{
    const conta = contaById.get(compra.contaId);
    const temTitulo = !!compra.titleId;
    const podeAprovar = !temTitulo && (compra.status === "PENDENTE" || compra.status === "REPROVADO");
    const podeReprovar = !temTitulo && compra.status === "PENDENTE";
    const podeCancelar = !temTitulo && compra.status !== "CANCELADO";
    return `
      <tr>
        <td>${escapeHtml(String(compra.requestedAt || "").slice(0, 10))}</td>
        <td>${escapeHtml(compra.desc || "")}</td>
        <td>${escapeHtml(compra.fornecedor || "-")}</td>
        <td>${escapeHtml(conta?.nome || "-")}</td>
        <td>${escapeHtml(compra.vencimento || "-")}</td>
        <td class="right"><b>${brl(compra.valor)}</b></td>
        <td>${compraStatusBadge(compra.status)}</td>
        <td>${temTitulo ? `<button class="btn" data-act="openTitle" data-id="${compra.id}">Abrir AP</button>` : `<span class="muted">Pendente</span>`}</td>
        <td class="right">
          <button class="btn" data-act="edit" data-id="${compra.id}">Editar</button>
          <button class="btn primary" data-act="approve" data-id="${compra.id}" ${podeAprovar ? "" : "disabled"}>Aprovar</button>
          <button class="btn" data-act="reject" data-id="${compra.id}" ${podeReprovar ? "" : "disabled"}>Reprovar</button>
          <button class="btn danger" data-act="cancel" data-id="${compra.id}" ${podeCancelar ? "" : "disabled"}>Cancelar</button>
        </td>
      </tr>
    `;
  }).join("") || `<tr><td colspan="9" class="muted">Nenhuma solicitacao de compra.</td></tr>`;
}

$("#btnFiltrarCompras")?.addEventListener("click", renderCompras);
$("#btnNovaCompra")?.addEventListener("click", ()=> openCompraModal());
$("#btnFecharModalCompra")?.addEventListener("click", closeCompraModal);
$("#btnCancelarCompra")?.addEventListener("click", closeCompraModal);
$("#modalCompra")?.addEventListener("click", (e)=>{ if(e.target.id === "modalCompra") closeCompraModal(); });
$("#pcFotoUrl")?.addEventListener("input", renderCompraPreview);
$("#pcProdutoUrl")?.addEventListener("input", renderCompraPreview);
$("#btnPesquisaIA")?.addEventListener("click", pesquisarCompraComIA);
$("#compraAiResultados")?.addEventListener("click", (e)=>{
  const btn = e.target.closest("button[data-act='useAiOffer']");
  if(!btn) return;
  aplicarOfertaPesquisaIA(Number(btn.dataset.idx));
});

$("#btnSalvarCompra")?.addEventListener("click", async (e)=>{
  const draft = currentCompraDraft();
  if(!draft.desc || !draft.justificativa || !draft.contaId || !draft.categoriaId || !draft.vencimento || !Number.isFinite(draft.valor) || draft.valor <= 0){
    alert("Preencha produto, justificativa, conta, etiqueta, vencimento e valor.");
    return;
  }

  const snapshot = cloneStateSnapshot();
  if(editCompraId){
    const compra = state.compras.find(c => c.id === editCompraId);
    if(!compra) return;
    Object.assign(compra, draft);
    if(compra.titleId) syncCompraToTitulo(compra);
  } else {
    state.compras.unshift(novoPedidoCompra(draft));
  }

  if(!await persistStateOrRollback(snapshot, { button: e.currentTarget })) return;
  renderAll();
  closeCompraModal();
});

$("#tbCompras")?.addEventListener("click", async (e)=>{
  const btn = e.target.closest("button");
  if(!btn) return;
  const compraId = btn.dataset.id;
  const act = btn.dataset.act;
  const compra = state.compras.find(c => c.id === compraId);
  if(!compra) return;

  try{
    if(act === "edit") openCompraModal(compraId);
    if(act === "openTitle") openTituloDaCompra(compraId);
    if(act === "approve"){
      const snapshot = cloneStateSnapshot();
      aprovarCompra(compraId);
      if(!await persistStateOrRollback(snapshot, { button: btn })) return;
      renderAll();
      alert("Solicitacao aprovada e contas a pagar gerado.");
    }
    if(act === "reject"){
      const snapshot = cloneStateSnapshot();
      reprovarCompra(compraId);
      if(!await persistStateOrRollback(snapshot, { button: btn })) return;
      renderAll();
      alert("Solicitacao reprovada.");
    }
    if(act === "cancel"){
      const snapshot = cloneStateSnapshot();
      cancelarCompra(compraId);
      if(!await persistStateOrRollback(snapshot, { button: btn })) return;
      renderAll();
      alert("Solicitacao cancelada.");
    }
  }catch(err){
    alert(err?.message || "Nao foi possivel atualizar a solicitacao.");
  }
});

/* ---------- Views AP/AR ---------- */
let paymentCodeState = null;

async function requestPixCode({ pixKey, pixKeyType, valor, pessoa, pixCity }){
  return requestJson("/api/finance/pix-code", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      key: pixKey,
      keyType: pixKeyType,
      amount: Number(valor || 0),
      merchantName: pessoa || "Recebedor Pix",
      merchantCity: pixCity || ""
    })
  });
}

function closePaymentCodeModal(){
  $("#modalCodigoPagamento").classList.add("hidden");
  paymentCodeState = null;
  $("#codigoPagamentoImagem").textContent = "";
}

function paymentCodeImageUrl(kind){
  const attachment = paymentCodeState?.attachment;
  if(!attachment?.path) return "";
  const params = new URLSearchParams({
    path: attachment.path,
    page: String(attachment.page || 1),
    region: String(paymentCodeState?.region || attachment.region || 1),
    regions: String(paymentCodeState?.regionsOnPage || attachment.regionsOnPage || 1),
    kind
  });
  return `/api/finance/attachments/payment-code-image?${params}`;
}

function showPaymentCodeKind(kind){
  if(!paymentCodeState) return;
  if(paymentCodeState.mode === "pix"){
    paymentCodeState.kind = "qr";
    $("#btnMostrarCodigoBarras").classList.add("hidden");
    $("#btnMostrarQrCode").classList.remove("hidden");
    $("#btnMostrarQrCode").classList.add("primary");
    $("#codigoPagamentoImagem").innerHTML = paymentCodeState.pixImage
      ? `<img src="${escapeHtml(paymentCodeState.pixImage)}" alt="QR Code Pix do pagamento">`
      : `<div class="muted">Gerando QR Code Pix...</div>`;
    return;
  }
  $("#btnMostrarCodigoBarras").classList.remove("hidden");
  paymentCodeState.kind = kind;
  $("#btnMostrarCodigoBarras").classList.toggle("primary", kind === "barcode");
  $("#btnMostrarQrCode").classList.toggle("primary", kind === "qr");
  const url = paymentCodeImageUrl(kind);
  $("#codigoPagamentoImagem").innerHTML = url
    ? `<img src="${escapeHtml(url)}" alt="${kind === "qr" ? "QR Code" : "Código de barras"} da parcela">`
    : `<div class="badText">Não foi possível localizar a imagem do código.</div>`;
}

async function openPaymentCodeModal(titulo){
  const attachment = (titulo?.anexos || []).find(anexo => anexo.page || anexo.barcode || anexo.pix);
  if(titulo?.pixKey){
    paymentCodeState = { titulo, mode: "pix", kind: "qr", code: "", pixImage: "" };
    $("#codigoPagamentoTitulo").textContent = `PIX · ${tituloDescricaoText(titulo) || "Pagamento"}`;
    $("#codigoPagamentoResumo").innerHTML = `
      <b>${brl(titulo.valor)}</b>
      <span>Vencimento ${escapeHtml(titulo.vencimento || "-")}</span>
      <span>${escapeHtml(titulo.pessoa || "Recebedor PIX")}</span>
      ${titulo.bankAccount ? `<span>Conta alternativa: ${escapeHtml(titulo.bankName || "Banco")} · ${escapeHtml(titulo.bankAgency || "-")} / ${escapeHtml(titulo.bankAccount)}</span>` : ""}
    `;
    $("#codigoPagamentoTextoWrap").classList.add("hidden");
    $("#codigoPagamentoTextoLabel").textContent = "PIX copia e cola";
    $("#codigoPagamentoTexto").textContent = "";
    $("#btnMostrarCodigoBarras").classList.add("hidden");
    $("#btnMostrarQrCode").classList.remove("hidden");
    $("#codigoPagamentoHint").textContent = "Aponte a câmera do aplicativo bancário para o QR Code e confirme o recebedor e o valor antes de pagar.";
    $("#modalCodigoPagamento").classList.remove("hidden");
    showPaymentCodeKind("qr");
    try{
      const payload = await requestPixCode(titulo);
      if(paymentCodeState?.titulo?.id !== titulo.id || paymentCodeState.mode !== "pix") return;
      paymentCodeState.code = payload.payload || "";
      paymentCodeState.pixImage = payload.image || "";
      $("#codigoPagamentoTexto").textContent = paymentCodeState.code;
      $("#codigoPagamentoTextoWrap").classList.toggle("hidden", !paymentCodeState.code);
      showPaymentCodeKind("qr");
    }catch(err){
      $("#codigoPagamentoImagem").innerHTML = `<div class="badText">${escapeHtml(err?.message || "Não foi possível gerar o QR Code Pix.")}</div>`;
    }
    return;
  }
  if(titulo?.bankAccount){
    const accountLines = [
      `Favorecido: ${titulo.pessoa || "-"}`,
      `Banco: ${titulo.bankName || "-"}`,
      titulo.bankAgency ? `Agência: ${titulo.bankAgency}` : "",
      `Conta: ${titulo.bankAccount}`,
      `Tipo: ${bankAccountTypeLabel(titulo.bankAccountType)}`,
      `Valor: ${brl(titulo.valor)}`
    ].filter(Boolean);
    paymentCodeState = { titulo, mode: "bank", kind: "account", code: accountLines.join("\n") };
    $("#codigoPagamentoTitulo").textContent = `Dados bancários · ${tituloDescricaoText(titulo) || "Pagamento"}`;
    $("#codigoPagamentoResumo").innerHTML = `
      <b>${brl(titulo.valor)}</b>
      <span>Vencimento ${escapeHtml(titulo.vencimento || "-")}</span>
      <span>${escapeHtml(titulo.pessoa || "Favorecido")}</span>
    `;
    $("#btnMostrarCodigoBarras").classList.add("hidden");
    $("#btnMostrarQrCode").classList.add("hidden");
    $("#codigoPagamentoImagem").innerHTML = `
      <div class="bankPaymentDetails">
        <div><span>Banco</span><b>${escapeHtml(titulo.bankName || "-")}</b></div>
        <div><span>Agência</span><b>${escapeHtml(titulo.bankAgency || "-")}</b></div>
        <div><span>Conta</span><b>${escapeHtml(titulo.bankAccount)}</b></div>
        <div><span>Tipo</span><b>${escapeHtml(bankAccountTypeLabel(titulo.bankAccountType))}</b></div>
      </div>
    `;
    $("#codigoPagamentoTextoLabel").textContent = "Dados bancários para copiar";
    $("#codigoPagamentoTexto").textContent = paymentCodeState.code;
    $("#codigoPagamentoTextoWrap").classList.remove("hidden");
    $("#codigoPagamentoHint").textContent = "Confira no aplicativo bancário se o titular da conta corresponde ao favorecido antes de pagar.";
    $("#modalCodigoPagamento").classList.remove("hidden");
    return;
  }
  if(!attachment) return alert("Este título não possui código de pagamento associado.");
  paymentCodeState = {
    titulo,
    attachment,
    mode: "attachment",
    kind: "barcode",
    code: "",
    region: attachment.region || 1,
    regionsOnPage: attachment.regionsOnPage || 1
  };
  $("#codigoPagamentoTitulo").textContent = tituloDescricaoText(titulo) || "Código para pagamento";
  $("#codigoPagamentoResumo").innerHTML = `
    <b>${brl(titulo.valor)}</b>
    <span>Vencimento ${escapeHtml(titulo.vencimento || "-")}</span>
    <span>Parcela ${escapeHtml(String(attachment.installmentNumber || attachment.page || "-"))}${attachment.installmentTotal ? `/${escapeHtml(String(attachment.installmentTotal))}` : ""}</span>
  `;
  $("#codigoPagamentoTextoWrap").classList.add("hidden");
  $("#codigoPagamentoTextoLabel").textContent = "Linha digitável / código";
  $("#codigoPagamentoTexto").textContent = "";
  $("#btnMostrarQrCode").classList.remove("hidden");
  $("#codigoPagamentoHint").textContent = "Aponte a câmera do aplicativo bancário para a imagem. O PDF completo permanece disponível somente em “Editar”.";
  $("#modalCodigoPagamento").classList.remove("hidden");
  showPaymentCodeKind("barcode");

  if(!attachment.path) return;
  const params = new URLSearchParams({
    path: attachment.path,
    page: String(attachment.page || 1),
    region: String(attachment.region || 1)
  });
  try{
    const payload = await requestJson(`/api/finance/attachments/payment-code-info?${params}`);
    if(paymentCodeState?.titulo?.id !== titulo.id) return;
    const recognized = payload?.payment || {};
    paymentCodeState.region = recognized.region || paymentCodeState.region;
    paymentCodeState.regionsOnPage = recognized.regionsOnPage || paymentCodeState.regionsOnPage;
    const code = recognized.pix || recognized.barcode || attachment.pix || attachment.barcode || "";
    paymentCodeState.code = code;
    if(code){
      $("#codigoPagamentoTexto").textContent = code;
      $("#codigoPagamentoTextoWrap").classList.remove("hidden");
    }
    showPaymentCodeKind(recognized.pix ? "qr" : paymentCodeState.kind);
  }catch(err){
    console.warn("Não foi possível reler o código da parcela.", err);
    const fallback = attachment.pix || (String(attachment.barcode || "").length === 47 ? attachment.barcode : "");
    paymentCodeState.code = fallback;
    if(fallback){
      $("#codigoPagamentoTexto").textContent = fallback;
      $("#codigoPagamentoTextoWrap").classList.remove("hidden");
    }
  }
}

$("#btnFecharCodigoPagamento").addEventListener("click", closePaymentCodeModal);
$("#modalCodigoPagamento").addEventListener("click", event => {
  if(event.target.id === "modalCodigoPagamento") closePaymentCodeModal();
});
$("#btnMostrarCodigoBarras").addEventListener("click", () => showPaymentCodeKind("barcode"));
$("#btnMostrarQrCode").addEventListener("click", () => showPaymentCodeKind("qr"));
$("#btnCopiarCodigoPagamento").addEventListener("click", async () => {
  const code = paymentCodeState?.code || "";
  if(!code) return alert("Nenhum código foi reconhecido para copiar.");
  try{
    await navigator.clipboard.writeText(code);
    alert("Código copiado.");
  }catch{
    alert("Não foi possível copiar automaticamente. Selecione o código exibido.");
  }
});

function renderAPAR(){
  renderTabelaTitulos("AP");
  renderTabelaTitulos("AR");
}

function filteredTitulos(tipo){
  const isAP = tipo==="AP";
  const selConta = (isAP ? $("#apConta").value : $("#arConta").value) || "ALL";
  const selStatus = (isAP ? $("#apStatus").value : $("#arStatus").value) || "ALL";
  const ini = (isAP ? $("#apIni").value : $("#arIni").value) || "";
  const fim = (isAP ? $("#apFim").value : $("#arFim").value) || "";
  const busca = ((isAP ? $("#apBusca").value : $("#arBusca").value) || "").trim().toLowerCase();

  let list = state.titulos.filter(t=>t.tipo===tipo);

  if(selConta!=="ALL") list = list.filter(t=>t.contaId===selConta);
  if(selStatus!=="ALL") list = list.filter(t=>t.status===selStatus);
  if(ini) list = list.filter(t=>t.vencimento >= ini);
  if(fim) list = list.filter(t=>t.vencimento <= fim);
  if(busca){
    list = list.filter(t=>{
      const etiquetas = categoriaNamesText(getTituloCategoriaIds(t), "");
      const s = `${tituloDescricaoText(t)} ${t.pessoa} ${etiquetas}`.toLowerCase();
      return s.includes(busca);
    });
  }

  list.sort((a,b)=> a.vencimento.localeCompare(b.vencimento));
  return list;
}

function renderTabelaTitulos(tipo){
  const isAP = tipo==="AP";
  const tb = isAP ? $("#tbAP") : $("#tbAR");
  const list = filteredTitulos(tipo);
  const contaById = new Map(state.contas.map(c=>[c.id,c]));

  const totalFiltrado = list.reduce((total, titulo) => {
    const valor = Number(titulo.valor);
    return total + (Number.isFinite(valor) ? valor : 0);
  }, 0);
  const totalEl = isAP ? $("#apTotalFiltrado") : $("#arTotalFiltrado");
  const quantidadeEl = isAP ? $("#apTotalQuantidade") : $("#arTotalQuantidade");
  totalEl.textContent = brl(totalFiltrado);
  quantidadeEl.textContent = `${list.length} ${list.length === 1 ? "conta apresentada" : "contas apresentadas"}`;

  tb.innerHTML = list.map(t=>{
    const conta = contaById.get(t.contaId);
    const desc = tituloDescricaoText(t);
    const st = t.status==="ABERTO" ? `<span class="badge warn">ABERTO</span>`
            : t.status==="BAIXADO" ? `<span class="badge ok">BAIXADO</span>`
            : `<span class="badge bad">CANCELADO</span>`;

    const anexos = (t.anexos?.length||0);
    const paymentAttachment = (t.anexos || []).find(anexo => anexo.page || anexo.barcode || anexo.pix);
    const favorite = (state.favorecidos || []).find(item => item.id === t.favorecidoId);
    let accessUrl = "";
    try{
      accessUrl = normalizeExternalAccessUrl(favorite?.accessUrl || t.accessUrl || "");
    }catch{
      accessUrl = "";
    }
    const paymentButton = t.pixKey
      ? `<button class="btn primary" data-act="paymentCode" data-id="${t.id}">${t.bankAccount ? "Ver PIX / conta" : "Ver PIX QR"}</button>`
      : t.bankAccount
      ? `<button class="btn primary" data-act="paymentCode" data-id="${t.id}">Ver dados bancários</button>`
      : paymentAttachment
      ? `<button class="btn primary" data-act="paymentCode" data-id="${t.id}">Ver código</button>`
      : "";
    const hasPdf = (t.anexos || []).some(anexo => String(anexo.mime || "").includes("pdf"));
    const attachmentButton = anexos
      ? `<button class="btn" data-act="attachment" data-id="${t.id}">${hasPdf ? "Ver PDF" : `Ver anexo${anexos > 1 ? "s" : ""}`}${anexos > 1 ? ` (${anexos})` : ""}</button>`
      : "";
    const accessButton = accessUrl
      ? `<a class="btn" href="${escapeHtml(accessUrl)}" target="_blank" rel="noopener noreferrer">Acessar site</a>`
      : "";
    const paymentActions = [paymentButton, attachmentButton, accessButton].filter(Boolean).join("");
    const anexBadge = paymentActions
      ? `<div class="row gap wrap">${paymentActions}</div>`
      : `<span class="muted">0</span>`;
    const canBaixar = t.status==="ABERTO";

    return `
      <tr>
        <td>${escapeHtml(t.vencimento)}</td>
        <td>${escapeHtml(conta?.nome || "-")}</td>
        <td>${categoriaBadgesHtml(getTituloCategoriaIds(t), "-")}</td>
        <td>${escapeHtml(t.pessoa || "-")}</td>
        <td>${escapeHtml(desc)}</td>
        <td class="right"><b>${brl(t.valor)}</b></td>
        <td>${st}</td>
        <td>${anexBadge}</td>
        <td class="right">
          <button class="btn" data-act="edit" data-id="${t.id}">Editar</button>
          <button class="btn ${canBaixar?'primary':''}" data-act="baixar" data-id="${t.id}" ${canBaixar?'':'disabled'}>Baixar</button>
          <button class="btn danger" data-act="cancel" data-id="${t.id}">Cancelar</button>
        </td>
      </tr>
    `;
  }).join("") || `<tr><td colspan="9" class="muted">Nenhum título.</td></tr>`;
}

$("#btnFiltrarAP").addEventListener("click", ()=>renderTabelaTitulos("AP"));
$("#btnFiltrarAR").addEventListener("click", ()=>renderTabelaTitulos("AR"));
$("#btnImprimirAP").addEventListener("click", event=>printTitlesReport("AP", event.currentTarget));
$("#btnImprimirAR").addEventListener("click", event=>printTitlesReport("AR", event.currentTarget));
$("#btnNovoAP").addEventListener("click", ()=>openTituloModal(null,"AP"));
$("#btnNovoAR").addEventListener("click", ()=>openTituloModal(null,"AR"));

let installmentPdfPreview = [];
let installmentPdfSignature = "";

function installmentFileSignature(file){
  return file ? `${file.name}|${file.size}|${file.lastModified}` : "";
}

function openInstallmentPdfModal(){
  installmentPdfPreview = [];
  installmentPdfSignature = "";
  $("#parcelasPdfFile").value = "";
  $("#parcelasPdfConta").innerHTML = state.contas
    .map(conta => `<option value="${conta.id}">${escapeHtml(conta.nome)}</option>`).join("");
  const selectedAccount = $("#apConta").value;
  if(selectedAccount && selectedAccount !== "ALL") $("#parcelasPdfConta").value = selectedAccount;
  $("#parcelasPdfCategoria").innerHTML = state.categorias
    .filter(cat => cat.tipo === "DESPESA")
    .map(cat => `<option value="${cat.id}">${escapeHtml(cat.nome)}</option>`).join("");
  $("#parcelasPdfFavorecido").innerHTML = [
    `<option value="">Preenchimento manual</option>`,
    ...(state.favorecidos || [])
      .slice()
      .sort((a, b) => String(a.nome || "").localeCompare(String(b.nome || ""), "pt-BR"))
      .map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.nome)}</option>`)
  ].join("");
  $("#parcelasPdfPessoa").value = "";
  $("#parcelasPdfDesc").value = "";
  $("#parcelasPdfPreview").innerHTML = "";
  $("#parcelasPdfPreviewWrap").classList.add("hidden");
  $("#parcelasPdfStatus").textContent = "Cada página será tratada como uma parcela.";
  $("#btnCriarParcelasPdf").disabled = true;
  $("#modalImportarParcelasPdf").classList.remove("hidden");
}

function closeInstallmentPdfModal(){
  $("#modalImportarParcelasPdf").classList.add("hidden");
  installmentPdfPreview = [];
  installmentPdfSignature = "";
}

function renderInstallmentPdfPreview(){
  $("#parcelasPdfPreview").innerHTML = installmentPdfPreview.map((item, previewIndex) => {
    const code = item.barcode || item.pix || "Não reconhecido — ficará visível na página";
    const issues = item.issues?.length
      ? `<div class="badText">${escapeHtml(item.issues.join(" · "))}</div>`
      : "";
    return `
      <tr data-preview-index="${previewIndex}">
        <td><b>${item.installmentNumber ? `Parcela ${item.installmentNumber}/${item.installmentTotal || installmentPdfPreview.length}` : `Página ${item.page}/${item.pageCount}`}</b><div class="muted">Página ${item.page}${item.regionsOnPage > 1 ? ` · posição ${item.region}/${item.regionsOnPage}` : ""}</div>${issues}</td>
        <td><input class="installmentDueDate" type="date" value="${escapeHtml(item.dueDate || "")}"></td>
        <td><input class="installmentAmount" type="number" step="0.01" min="0.01" value="${item.amount ?? ""}"></td>
        <td class="installmentCode">${escapeHtml(code)}</td>
        <td><input class="installmentUse" type="checkbox" checked></td>
      </tr>
    `;
  }).join("");
  $("#parcelasPdfPreviewWrap").classList.remove("hidden");
  $("#btnCriarParcelasPdf").disabled = installmentPdfPreview.length === 0;
}

$("#btnImportarParcelasPdf").addEventListener("click", openInstallmentPdfModal);
$("#btnFecharImportarParcelasPdf").addEventListener("click", closeInstallmentPdfModal);
$("#btnCancelarImportarParcelasPdf").addEventListener("click", closeInstallmentPdfModal);
$("#modalImportarParcelasPdf").addEventListener("click", event => {
  if(event.target.id === "modalImportarParcelasPdf") closeInstallmentPdfModal();
});

$("#parcelasPdfFavorecido").addEventListener("change", event => {
  const favorecido = (state.favorecidos || []).find(item => item.id === event.currentTarget.value);
  if(favorecido) $("#parcelasPdfPessoa").value = favorecido.nome || "";
});

$("#btnLerParcelasPdf").addEventListener("click", async event => {
  const file = $("#parcelasPdfFile").files?.[0];
  if(!file) return alert("Selecione o PDF com as parcelas.");
  if(file.size > 15 * 1024 * 1024) return alert("O PDF excede o limite de 15 MB.");
  const formData = new FormData();
  formData.set("file", file);
  const button = event.currentTarget;
  const oldText = button.textContent;
  button.disabled = true;
  button.textContent = "Lendo páginas...";
  try{
    const payload = await requestJson("/apps/financeiro/api/import-installments-pdf", {
      method: "POST",
      body: formData
    });
    installmentPdfPreview = payload.pages || [];
    installmentPdfSignature = installmentFileSignature(file);
    renderInstallmentPdfPreview();
    const pending = installmentPdfPreview.filter(item => item.issues?.length).length;
    const physicalPages = new Set(installmentPdfPreview.map(item => item.page)).size;
    $("#parcelasPdfStatus").textContent = `${installmentPdfPreview.length} parcela(s) encontrada(s) em ${physicalPages} página(s).${pending ? ` Revise ${pending} parcela(s) destacada(s).` : " Datas, valores e códigos reconhecidos."}`;
  }catch(err){
    alert(err?.message || "Não foi possível ler as parcelas do PDF.");
  }finally{
    button.disabled = false;
    button.textContent = oldText;
  }
});

$("#btnCriarParcelasPdf").addEventListener("click", async event => {
  const file = $("#parcelasPdfFile").files?.[0];
  if(!file || installmentFileSignature(file) !== installmentPdfSignature){
    return alert("O PDF foi alterado. Leia as páginas novamente antes de criar as parcelas.");
  }
  const contaId = $("#parcelasPdfConta").value;
  const categoriaId = $("#parcelasPdfCategoria").value;
  const favorecido = (state.favorecidos || []).find(
    item => item.id === $("#parcelasPdfFavorecido").value
  );
  const pessoa = $("#parcelasPdfPessoa").value.trim();
  const baseDescription = $("#parcelasPdfDesc").value.trim();
  if(!contaId || !categoriaId || !baseDescription){
    return alert("Informe conta, categoria e descrição base.");
  }

  const rows = Array.from($$("#parcelasPdfPreview tr")).flatMap(row => {
    if(!row.querySelector(".installmentUse")?.checked) return [];
    const item = installmentPdfPreview[Number(row.dataset.previewIndex)];
    const dueDate = row.querySelector(".installmentDueDate")?.value || "";
    const amount = Number(row.querySelector(".installmentAmount")?.value);
    return [{ item, dueDate, amount }];
  });
  if(!rows.length) return alert("Selecione pelo menos uma página para importar.");
  if(rows.some(row => !row.item || !isValidDateISO(row.dueDate) || !Number.isFinite(row.amount) || row.amount <= 0)){
    return alert("Revise o vencimento e o valor de todas as páginas selecionadas.");
  }

  const snapshot = cloneStateSnapshot();
  let uploaded = null;
  try{
    uploaded = await uploadFinanceAttachment(file, { contaId, pessoa, descricao: baseDescription });
    if(!uploaded) throw new Error("O PDF não pôde ser armazenado.");
    const total = rows.length;
    rows.forEach(({ item, dueDate, amount }, index) => {
      const installmentNumber = item.installmentNumber || index + 1;
      const installmentTotal = item.installmentTotal || total;
      const titulo = novoTitulo({
        tipo: "AP",
        pessoa,
        desc: `${baseDescription} (${installmentNumber}/${installmentTotal})`,
        categoriaId,
        categoriaIds: [categoriaId],
        contaId,
        valor: amount,
        vencimento: dueDate,
        centroCusto: "",
        obs: "",
        favorecidoId: favorecido?.id || "",
        pixKeyType: favorecido?.pixKeyType || "TELEFONE",
        pixKey: favorecido?.pixKey || "",
        pixCity: favorecido?.pixCity || "",
        bankName: favorecido?.bankName || "",
        bankAccountType: favorecido?.bankAccountType || "CORRENTE",
        bankAgency: favorecido?.bankAgency || "",
        bankAccount: favorecido?.bankAccount || ""
      });
      titulo.anexos = [{
        ...uploaded,
        id: uid("anxlink"),
        page: item.page,
        pageCount: item.pageCount,
        region: item.region || 1,
        regionsOnPage: item.regionsOnPage || 1,
        installmentNumber,
        installmentTotal,
        barcode: item.barcode || "",
        pix: item.pix || ""
      }];
      state.titulos.unshift(titulo);
    });
    if(!await persistStateOrRollback(snapshot, { button: event.currentTarget })){
      await removeTituloAttachmentFile(uploaded);
      return;
    }
    closeInstallmentPdfModal();
    renderAll();
    alert(`${rows.length} conta(s) a pagar criada(s). Cada uma abre diretamente na página correspondente do PDF.`);
  }catch(err){
    if(uploaded){
      state = migrate(snapshot);
      await removeTituloAttachmentFile(uploaded);
    }
    alert(err?.message || "Não foi possível criar as parcelas.");
  }
});

$("#tbAP").addEventListener("click", async (e)=>{
  const btn=e.target.closest("button"); if(!btn) return;
  await handleTituloAction(btn.dataset.act, btn.dataset.id, btn);
});
$("#tbAR").addEventListener("click", async (e)=>{
  const btn=e.target.closest("button"); if(!btn) return;
  await handleTituloAction(btn.dataset.act, btn.dataset.id, btn);
});

async function handleTituloAction(act, id, button=null){
  const t = state.titulos.find(x=>x.id===id);
  if(!t) return;

  if(act==="edit") openTituloModal(id, t.tipo);
  if(act==="paymentCode") openPaymentCodeModal(t);
  if(act==="attachment"){
    openTituloModal(id, t.tipo);
    const first = (t.anexos || []).find(anexo => String(anexo.mime || "").includes("pdf")) || t.anexos?.[0];
    if(first){
      previewAnexoId = first.id;
      renderAnexos();
      renderAnexoPreview(first);
    }
  }

  if(act==="baixar"){
    try{
      const snapshot = cloneStateSnapshot();
      baixarTitulo(id, toISODate(new Date()));
      if(!await persistStateOrRollback(snapshot, { button })) return;
      renderAll();
      alert("Baixado e lançamento criado.");
    }catch(err){
      alert(err?.message || "Não foi possível baixar.");
    }
  }

  if(act==="cancel"){
    if(confirm("Cancelar este título?")){
      const snapshot = cloneStateSnapshot();
      aplicarStatusTitulo(t, "CANCELADO");
      if(!await persistStateOrRollback(snapshot, { button })) return;
      renderAll();
    }
  }
}

/* ---------- Modal Título (AP/AR) ---------- */
let editTituloId = null;
let previewAnexoId = null;

function syncPixPaymentUi(){
  const isPayable = $("#tTipo").value === "AP";
  $("#pixPaymentBox").classList.toggle("hidden", !isPayable);
  $("#tFavorecidoWrap").classList.toggle("hidden", !isPayable);
  $("#tFavorecido").disabled = !isPayable;
  $("#tPixKeyType").disabled = !isPayable;
  $("#tPixKey").disabled = !isPayable;
  $("#tPixCity").disabled = !isPayable;
  $("#tBankName").disabled = !isPayable;
  $("#tBankAccountType").disabled = !isPayable;
  $("#tBankAgency").disabled = !isPayable;
  $("#tBankAccount").disabled = !isPayable;
}

function applyFavorecidoToTitulo(){
  const item = (state.favorecidos || []).find(candidate => candidate.id === $("#tFavorecido").value);
  if(!item) return;
  $("#tPessoa").value = item.nome || "";
  $("#tPixKeyType").value = item.pixKeyType || "TELEFONE";
  $("#tPixKey").value = item.pixKey || "";
  $("#tPixCity").value = item.pixCity || "";
  $("#tBankName").value = item.bankName || "";
  $("#tBankAccountType").value = item.bankAccountType || "CORRENTE";
  $("#tBankAgency").value = item.bankAgency || "";
  $("#tBankAccount").value = item.bankAccount || "";
}

function syncParcelamentoUi(){
  const isNewTitulo = !editTituloId;
  const enabled = isNewTitulo && $("#tGerarParcelas").checked;
  const qtdParcelas = clamp(Number($("#tParcelas").value || 2), 2, 60);
  const modo = $("#tParcelamentoModo")?.value || "total";
  const valorInformado = Number($("#tValor").value);

  $("#tGerarParcelas").disabled = !isNewTitulo;
  $("#parcelamentoCampos").classList.toggle("hidden", !enabled);
  $("#tValorLabel").textContent = enabled && modo === "total"
    ? "Valor total (R$)"
    : enabled && modo === "mensal"
      ? "Valor da mensalidade (R$)"
      : "Valor (R$)";
  $("#tParcelasLabel").textContent = modo === "mensal" ? "Parcelas restantes" : "Qtd. parcelas";
  $("#parcelamentoHint").textContent = isNewTitulo
    ? "Disponivel para novos lancamentos. Escolha se o valor informado e total ou mensalidade."
    : "Parcelamento fica disponivel apenas na criacao de um novo titulo.";

  if(!$("#tPrimeiraParcela").value){
    $("#tPrimeiraParcela").value = $("#tVenc").value || toISODate(new Date());
  }

  if(enabled && Number.isFinite(valorInformado) && valorInformado > 0 && modo === "mensal"){
    const total = valorInformado * qtdParcelas;
    $("#parcelamentoResumo").textContent = `Serao geradas ${qtdParcelas} parcelas mensais de ${brl(valorInformado)}, totalizando ${brl(total)}.`;
    return;
  }

  if(enabled && Number.isFinite(valorInformado) && valorInformado > 0){
    const parcelas = splitAmount(valorInformado, qtdParcelas).map(brl);
    const exemplo = parcelas.slice(0, 3).join(", ");
    $("#parcelamentoResumo").textContent = `Serao geradas ${qtdParcelas} parcelas mensais. Ex.: ${exemplo}${parcelas.length > 3 ? "..." : ""}`;
    return;
  }

  $("#parcelamentoResumo").textContent = "As parcelas serao geradas mensalmente a partir do primeiro vencimento.";
}

function criarTitulosParcelados(draft){
  const parcelas = clamp(Number(draft.parcelas || 1), 2, 60);
  const primeiraParcela = draft.primeiraParcela || draft.vencimento;
  const modo = draft.parcelamentoModo || "total";
  const valores = modo === "mensal"
    ? Array.from({ length: parcelas }, () => Number(draft.valor || 0))
    : splitAmount(draft.valor, parcelas);
  const createdIds = [];

  for(let index = 0; index < parcelas; index++){
    const titulo = novoTitulo({
      ...draft,
      valor: valores[index],
      vencimento: addMonthsISO(primeiraParcela, index),
      desc: `${draft.desc} (${index + 1}/${parcelas})`,
      obs: ""
    });
    state.titulos.unshift(titulo);
    aplicarStatusTitulo(titulo, draft.status || "ABERTO");
    createdIds.push(titulo.id);
  }

  return createdIds;
}

function openTituloModal(id, tipoDefault="AP"){
  editTituloId = id;
  previewAnexoId = null;
  $("#modalTitulo").classList.remove("hidden");

  const t = id ? state.titulos.find(x=>x.id===id) : null;
  const compraVinculada = id ? getCompraByTituloId(id) : null;
  $("#modalTituloTitle").textContent = id ? "Editar título" : "Novo título";

  $("#tTipo").value = t?.tipo || tipoDefault;
  $("#tTipo").disabled = !!compraVinculada;
  fillSelects();
  $("#tStatus").value = t?.status || "ABERTO";
  $("#tVenc").value = t?.vencimento || toISODate(new Date());
  $("#tConta").value = t?.contaId || (state.contas[0]?.id || "");
  $("#tPessoa").value = t?.pessoa || "";
  $("#tDesc").value = tituloDescricaoText(t);
  setSelectValues("#tCategoria", getTituloCategoriaIds(t), $("#tCategoria").value);
  $("#tValor").value = t ? Number(t.valor||0) : "";
  $("#tFavorecido").value = t?.favorecidoId || "";
  $("#tPixKeyType").value = t?.pixKeyType || "TELEFONE";
  $("#tPixKey").value = t?.pixKey || "";
  $("#tPixCity").value = t?.pixCity || "";
  $("#tBankName").value = t?.bankName || "";
  $("#tBankAccountType").value = t?.bankAccountType || "CORRENTE";
  $("#tBankAgency").value = t?.bankAgency || "";
  $("#tBankAccount").value = t?.bankAccount || "";
  $("#tGerarParcelas").checked = false;
  $("#tParcelamentoModo").value = "total";
  $("#tParcelas").value = 2;
  $("#tPrimeiraParcela").value = t?.vencimento || $("#tVenc").value;
  $("#tVenc").dataset.prevValue = $("#tVenc").value;

  renderAnexos();
  renderAnexoPreview(null);
  syncPixPaymentUi();
  syncParcelamentoUi();
  updateBaixaButton();
}

function closeTituloModal(){
  $("#modalTitulo").classList.add("hidden");
  editTituloId = null;
  previewAnexoId = null;
  $("#tTipo").disabled = false;
  renderAnexoPreview(null);
}

function currentTituloDraft(){
  const categoriaIds = getSelectValues("#tCategoria");
  return {
    tipo: $("#tTipo").value,
    status: $("#tStatus").value,
    vencimento: $("#tVenc").value,
    contaId: $("#tConta").value,
    pessoa: $("#tPessoa").value.trim(),
    desc: $("#tDesc").value.trim(),
    categoriaId: categoriaIds[0] || "",
    categoriaIds,
    valor: Number($("#tValor").value),
    gerarParcelas: $("#tGerarParcelas").checked,
    parcelamentoModo: $("#tParcelamentoModo")?.value || "total",
    parcelas: clamp(Number($("#tParcelas").value || 1), 1, 60),
    primeiraParcela: $("#tPrimeiraParcela").value || $("#tVenc").value,
    favorecidoId: $("#tTipo").value === "AP" ? $("#tFavorecido").value : "",
    pixKeyType: $("#tTipo").value === "AP" ? $("#tPixKeyType").value : "",
    pixKey: $("#tTipo").value === "AP" ? $("#tPixKey").value.trim() : "",
    pixCity: $("#tTipo").value === "AP" ? $("#tPixCity").value.trim() : "",
    bankName: $("#tTipo").value === "AP" ? $("#tBankName").value.trim() : "",
    bankAccountType: $("#tTipo").value === "AP" ? $("#tBankAccountType").value : "",
    bankAgency: $("#tTipo").value === "AP" ? $("#tBankAgency").value.trim() : "",
    bankAccount: $("#tTipo").value === "AP" ? $("#tBankAccount").value.trim() : ""
  };
}

function syncCompraFromTitulo(titulo, draft, meta){
  const compraId = meta?.compraId || "";
  if(!compraId) return;

  const compra = state.compras.find(item => item.id === compraId);
  if(!compra) return;

  compra.fornecedor = draft.pessoa;
  compra.desc = draft.desc;
  compra.categoriaId = draft.categoriaId;
  compra.contaId = draft.contaId;
  compra.valor = draft.valor;
  compra.vencimento = draft.vencimento;
}

function updateBaixaButton(){
  const t = editTituloId ? state.titulos.find(x=>x.id===editTituloId) : null;
  const can = (t && t.status === "ABERTO");
  $("#btnBaixarTitulo").disabled = !can;
}

function renderAnexos(){
  const t = editTituloId ? state.titulos.find(x=>x.id===editTituloId) : null;
  const anexos = t?.anexos || [];
  $("#listaAnexos").innerHTML = anexos.length ? anexos.map(a=>`
    <div class="item ${previewAnexoId===a.id?'selected':''}">
      <div class="left" style="flex:1">
        <span class="badge">${a.mime.includes("pdf") ? "PDF" : "IMG"}</span>
        <div style="min-width:0">
          <div><b>${escapeHtml(a.name)}</b></div>
          <div class="muted">${escapeHtml(a.mime)}${a.path ? ` - ${escapeHtml(a.path)}` : ""}</div>
        </div>
      </div>
      <div class="row gap">
        <button class="btn" data-act="view" data-id="${a.id}">Ver</button>
        <button class="btn danger" data-act="del" data-id="${a.id}">Remover</button>
      </div>
    </div>
  `).join("") : `<div class="muted">Nenhum anexo.</div>`;
}

function renderAnexoPreview(anexo){
  const box = $("#anexoPreview");
  if(!anexo){
    box.innerHTML = `Selecione um anexo para visualizar.`;
    detectCodesFromAttachment(null);
    return;
  }
  const src = filePreviewSrc(anexo);
  if(!src){
    box.textContent = "Arquivo sem URL de visualizacao.";
    detectCodesFromAttachment(null);
    return;
  }
  if(anexo.mime.includes("pdf")){
    box.innerHTML = `<iframe src="${escapeHtml(src)}" style="width:100%;height:360px;border:0;border-radius:12px"></iframe>${attachmentCodeDetails(anexo)}`;
    detectCodesFromAttachment(anexo);
  } else if(anexo.mime.startsWith("image/")){
    box.innerHTML = `<img src="${src}" alt="anexo" style="max-width:100%;border-radius:12px" />`;
    detectCodesFromAttachment(anexo);
  } else {
    box.textContent = "Formato não suportado na prévia.";
    detectCodesFromAttachment(null);
  }
}

$("#btnFecharModalTitulo").addEventListener("click", closeTituloModal);
$("#btnCancelarTitulo").addEventListener("click", closeTituloModal);
$("#modalTitulo").addEventListener("click",(e)=>{ if(e.target.id==="modalTitulo") closeTituloModal(); });
$("#tGerarParcelas").addEventListener("change", syncParcelamentoUi);
$("#tFavorecido").addEventListener("change", applyFavorecidoToTitulo);
$("#tParcelamentoModo").addEventListener("change", syncParcelamentoUi);
$("#tParcelas").addEventListener("input", syncParcelamentoUi);
$("#tValor").addEventListener("input", syncParcelamentoUi);
$("#tVenc").addEventListener("change", ()=>{
  if(!$("#tPrimeiraParcela").value || $("#tPrimeiraParcela").value === $("#tVenc").dataset.prevValue){
    $("#tPrimeiraParcela").value = $("#tVenc").value;
  }
  $("#tVenc").dataset.prevValue = $("#tVenc").value;
  syncParcelamentoUi();
});

$("#btnSalvarTitulo").addEventListener("click", async (e)=>{
  const d = currentTituloDraft();
  const pendingAttachmentFile = $("#tAnexoFile").files?.[0] || null;
  if(!d.vencimento || !d.contaId || !d.categoriaIds.length || !d.desc || !Number.isFinite(d.valor) || d.valor<=0){
    alert("Preencha vencimento, conta, etiquetas, descrição e valor.");
    return;
  }
  if(d.bankAccount && !d.bankName){
    alert("Informe o banco da conta para pagamento.");
    return;
  }
  if(d.pixKey){
    try{
      await requestPixCode(d);
    }catch(err){
      alert(err?.message || "A chave Pix não pôde ser validada.");
      return;
    }
  }
  if(pendingAttachmentFile && pendingAttachmentFile.size > 15 * 1024 * 1024){
    alert("Arquivo muito grande. Use até 15MB por anexo.");
    return;
  }

  const snapshot = cloneStateSnapshot();
  let uploadedAttachment = null;
  const attachPendingFile = async titulo => {
    if(!pendingAttachmentFile) return;
    uploadedAttachment = await uploadTituloAttachment(pendingAttachmentFile, titulo);
    if(!uploadedAttachment) throw new Error("O upload não retornou os dados do anexo.");
    if(!Array.isArray(titulo.anexos)) titulo.anexos = [];
    titulo.anexos.push(uploadedAttachment);
  };
  let nextEditTituloId = editTituloId;
  if(editTituloId){
    const t = state.titulos.find(x=>x.id===editTituloId);
    if(!t) return;
    const oldMeta = stripRemovedTitleMeta(parseTitleObs(t.obs).meta);
    t.tipo = d.tipo;
    t.vencimento = d.vencimento;
    t.contaId = d.contaId;
    t.categoriaId = d.categoriaId;
    t.categoriaIds = d.categoriaIds;
    t.desc = d.desc;
    t.pessoa = d.pessoa;
    t.valor = d.valor;
    t.favorecidoId = d.favorecidoId;
    t.pixKeyType = d.pixKeyType;
    t.pixKey = d.pixKey;
    t.pixCity = d.pixCity;
    t.bankName = d.bankName;
    t.bankAccountType = d.bankAccountType;
    t.bankAgency = d.bankAgency;
    t.bankAccount = d.bankAccount;
    t.centroCusto = "";
    t.obs = buildTitleObs("", oldMeta);
    aplicarStatusTitulo(t, d.status);
    syncCompraFromTitulo(t, d, oldMeta);
  } else {
    if(d.gerarParcelas && d.parcelas > 1){
      const createdIds = criarTitulosParcelados(d);
      nextEditTituloId = createdIds[0] || null;
      const firstInstallment = state.titulos.find(item => item.id === nextEditTituloId);
      try{
        if(firstInstallment) await attachPendingFile(firstInstallment);
      }catch(err){
        state = migrate(snapshot);
        alert(err?.message || "Não foi possível enviar o anexo. As parcelas não foram salvas.");
        return;
      }
      if(!await persistStateOrRollback(snapshot, { button: e.currentTarget })){
        if(uploadedAttachment) await removeTituloAttachmentFile(uploadedAttachment);
        return;
      }
      if(uploadedAttachment) $("#tAnexoFile").value = "";
      editTituloId = nextEditTituloId;
      renderAll();
      if(editTituloId) openTituloModal(editTituloId, d.tipo);
      alert(`${createdIds.length} parcelas criadas com sucesso.${uploadedAttachment ? " O PDF foi anexado à primeira parcela." : ""}`);
      return;
    }

    const t = novoTitulo({ ...d, obs: "" });
    state.titulos.unshift(t);
    aplicarStatusTitulo(t, d.status || "ABERTO");
    nextEditTituloId = t.id;
  }

  const savedTitle = state.titulos.find(item => item.id === nextEditTituloId);
  try{
    if(savedTitle) await attachPendingFile(savedTitle);
  }catch(err){
    state = migrate(snapshot);
    alert(err?.message || "Não foi possível enviar o anexo. O título não foi salvo.");
    return;
  }
  if(!await persistStateOrRollback(snapshot, { button: e.currentTarget })){
    if(uploadedAttachment) await removeTituloAttachmentFile(uploadedAttachment);
    return;
  }
  if(uploadedAttachment) $("#tAnexoFile").value = "";
  editTituloId = nextEditTituloId;
  renderAll();
  openTituloModal(editTituloId, d.tipo);
});

$("#btnBaixarTitulo").addEventListener("click", async (e)=>{
  if(!editTituloId) return;
  try{
    const snapshot = cloneStateSnapshot();
    baixarTitulo(editTituloId, toISODate(new Date()));
    if(!await persistStateOrRollback(snapshot, { button: e.currentTarget })) return;
    renderAll();
    openTituloModal(editTituloId, $("#tTipo").value);
  }catch(err){
    alert(err?.message || "Não foi possível baixar.");
  }
});

$("#btnAddAnexo").addEventListener("click", async ()=>{
  if(!editTituloId){
    alert("Este título ainda é novo. O arquivo selecionado será enviado quando você clicar em Salvar.");
    return;
  }
  const file = $("#tAnexoFile").files?.[0];
  if(!file) return alert("Selecione um arquivo (PDF/Imagem).");

  if(file.size > 15 * 1024 * 1024){
    alert("Arquivo muito grande. Use até 15MB por anexo.");
    return;
  }

  const t = state.titulos.find(x=>x.id===editTituloId);
  if(!t) return;

  try{
    const snapshot = cloneStateSnapshot();
    const uploaded = await uploadTituloAttachment(file, t);
    if(!uploaded) throw new Error("Upload nao retornou metadados do anexo.");
    t.anexos.push(uploaded);

    $("#tAnexoFile").value = "";
    if(!await persistStateOrRollback(snapshot, { button: $("#btnAddAnexo") })) return;
    renderAll();
    openTituloModal(editTituloId, t.tipo);
    previewAnexoId = uploaded.id;
    renderAnexos();
    renderAnexoPreview(uploaded);
  }catch(err){
    alert(err?.message || "Nao foi possivel enviar o anexo.");
  }
});

$("#listaAnexos").addEventListener("click", async (e)=>{
  const btn = e.target.closest("button");
  if(!btn) return;
  const act = btn.dataset.act;
  const id = btn.dataset.id;
  const t = editTituloId ? state.titulos.find(x=>x.id===editTituloId) : null;
  if(!t) return;

  if(act==="view"){
    const a = t.anexos.find(x=>x.id===id);
    previewAnexoId = id;
    renderAnexos();
    renderAnexoPreview(a);
  }
  if(act==="del"){
    if(confirm("Remover anexo?")){
      const snapshot = cloneStateSnapshot();
      const anexo = t.anexos.find(x=>x.id===id);
      t.anexos = t.anexos.filter(x=>x.id!==id);
      if(previewAnexoId===id){ previewAnexoId=null; renderAnexoPreview(null); }
      try{
        await removeTituloAttachmentFile(anexo);
      }catch(err){
        console.warn("Falha ao remover arquivo fisico do anexo:", err);
      }
      if(!await persistStateOrRollback(snapshot, { button: btn })) return;
      renderAnexos();
    }
  }
});

/* ---------- Config ---------- */
function financeAiBadgeClass(level){
  if(level === "ok") return "ok";
  if(level === "bad") return "bad";
  return "warn";
}

function financeAiBadgeLabel(code, level){
  if(code === "scraper_ready") return "Pronto";
  if(code === "search_ok") return "Busca OK";
  if(code === "search_empty") return "Sem links";
  if(code === "search_unreachable") return "Busca";
  if(code === "network_error") return "Rede";
  if(level === "ok") return "Pronto";
  if(level === "bad") return "Falha";
  return "Atencao";
}

function renderFinanceAiStatus(){
  const badge = $("#aiStatusBadge");
  const checkedAt = $("#aiStatusCheckedAt");
  const messageBox = $("#aiStatusMessage");
  const detailsBox = $("#aiStatusDetails");
  const refreshBtn = $("#btnAtualizarAiStatus");
  if(!badge || !checkedAt || !messageBox || !detailsBox) return;

  if(refreshBtn){
    refreshBtn.disabled = financeAiDiagState.loading;
    refreshBtn.textContent = financeAiDiagState.loading ? "Atualizando..." : "Atualizar status";
  }

  if(financeAiDiagState.loading){
    badge.className = "badge warn";
    badge.textContent = "Verificando...";
    checkedAt.textContent = "Consultando o servidor e a busca web.";
    messageBox.className = "statusBox";
    messageBox.textContent = "Executando diagnostico da pesquisa inteligente. Aguarde um instante.";
    detailsBox.innerHTML = `
      <div class="diagItem"><div class="diagLabel">Servidor</div><div class="diagValue">Lendo configuracao...</div></div>
      <div class="diagItem"><div class="diagLabel">Busca web</div><div class="diagValue">Testando raspagem...</div></div>
    `;
    return;
  }

  if(financeAiDiagState.error){
    badge.className = "badge bad";
    badge.textContent = "Falha";
    checkedAt.textContent = "Nao foi possivel consultar o diagnostico.";
    messageBox.className = "statusBox bad";
    messageBox.textContent = financeAiDiagState.error;
    detailsBox.innerHTML = `
      <div class="diagItem">
        <div class="diagLabel">Sugestao</div>
        <div class="diagValue">Confira se o servidor foi redeployado corretamente e se a rota /api/finance/ai-status esta respondendo.</div>
      </div>
    `;
    return;
  }

  const payload = financeAiDiagState.data;
  if(!payload){
    badge.className = "badge warn";
    badge.textContent = "Pendente";
    checkedAt.textContent = "Nenhum diagnostico executado ainda.";
    messageBox.className = "statusBox";
    messageBox.textContent = "Abra esta aba ou clique em atualizar para verificar o mecanismo Python de scraping.";
    detailsBox.innerHTML = "";
    return;
  }

  const status = payload.status || {};
  const probe = payload.probe || {};
  const config = payload.config || {};
  const level = financeAiBadgeClass(status.level);

  badge.className = `badge ${level}`;
  badge.textContent = financeAiBadgeLabel(status.code, status.level);
  checkedAt.textContent = `Ultima verificacao: ${formatDateTime(payload.checkedAt)}`;
  messageBox.className = `statusBox ${level}`;
  messageBox.textContent = status.message || "Diagnostico carregado.";

  detailsBox.innerHTML = [
    {
      label: "Provedor",
      value: config.provider || "-"
    },
    {
      label: "Mecanismo",
      value: config.engine || "-"
    },
    {
      label: "Busca web",
      value: config.searchUrl || "-"
    },
    {
      label: "Lojas monitoradas",
      value: config.allowedDomainsCount || "-"
    },
    {
      label: "Dominios permitidos",
      value: Array.isArray(config.allowedDomains) && config.allowedDomains.length
        ? config.allowedDomains.join(", ")
        : "-"
    },
    {
      label: "Timeout",
      value: config.timeoutSeconds ? `${config.timeoutSeconds}s` : "-"
    },
    {
      label: "Max. ofertas",
      value: config.maxOffers || "-"
    },
    {
      label: "User-Agent",
      value: config.userAgentConfigured ? "Configurado" : "Padrao"
    },
    {
      label: "Teste da busca",
      value: probe.attempted ? (probe.success ? "Conexao validada" : "Falhou") : "Nao executado"
    },
    {
      label: "Resultados de teste",
      value: probe.resultCount || "-"
    },
    {
      label: "Codigo",
      value: probe.errorCode || status.code || "-"
    },
    {
      label: "Detalhe",
      value: probe.message || "Sem detalhe adicional."
    }
  ].map(item => `
    <div class="diagItem">
      <div class="diagLabel">${escapeHtml(item.label)}</div>
      <div class="diagValue">${escapeHtml(String(item.value || "-"))}</div>
    </div>
  `).join("");
}

async function loadFinanceAiStatus({force=false}={}){
  if(!$("#aiStatusBadge")) return;
  if(financeAiDiagState.loading) return;

  const now = Date.now();
  if(!force && financeAiDiagState.loaded && (now - financeAiDiagState.lastLoadedAt) < 30000){
    renderFinanceAiStatus();
    return;
  }

  financeAiDiagState.loading = true;
  financeAiDiagState.error = "";
  renderFinanceAiStatus();

  try{
    const payload = await requestJson("/api/finance/ai-status?probe=1");
    financeAiDiagState = {
      loading: false,
      loaded: true,
      error: "",
      data: payload,
      lastLoadedAt: Date.now()
    };
  }catch(err){
    financeAiDiagState = {
      loading: false,
      loaded: false,
      error: err?.message || "Nao foi possivel carregar o diagnostico da I.A.",
      data: null,
      lastLoadedAt: 0
    };
  }

  renderFinanceAiStatus();
}

function renderConfig(){
  $("#cfgTolDias").value = state.config.tolDias;
  $("#cfgTolValor").value = state.config.tolValor;
  $("#cfgScoreMin").value = state.config.scoreMin;
  renderFinanceAiStatus();
  if(!$("#view-config")?.classList.contains("hidden")){
    loadFinanceAiStatus();
  }
}
$("#btnSalvarCfg").addEventListener("click", async (e)=>{
  const snapshot = cloneStateSnapshot();
  state.config.tolDias = clamp(Number($("#cfgTolDias").value), 0, 30);
  state.config.tolValor = clamp(Number($("#cfgTolValor").value), 0, 999999);
  state.config.scoreMin = clamp(Number($("#cfgScoreMin").value), 0, 100);
  if(!await persistStateOrRollback(snapshot, { button: e.currentTarget })) return;
  alert("Config salva.");
});
$("#btnRodarAvisos")?.addEventListener("click", ()=> triggerFinanceReminders());
$("#btnAtualizarAiStatus")?.addEventListener("click", ()=> loadFinanceAiStatus({ force: true }));

/* ---------- Backup JSON ---------- */
$("#btnExportJSON").addEventListener("click", ()=>{
  const blob = new Blob([JSON.stringify(state,null,2)], {type:"application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `gestao-financeira-backup_${new Date().toISOString().slice(0,10)}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
});

$("#btnImportJSON").addEventListener("click", async ()=>{
  const file = $("#jsonFile").files?.[0];
  if(!file) return alert("Selecione um .json de backup.");
  const snapshot = cloneStateSnapshot();
  try{
    const text = await file.text();
    const data = migrate(JSON.parse(text));
    replaceState(data);
    if(!await persistStateOrRollback(snapshot, { button: $("#btnImportJSON") })) return;
    renderAll();
    alert("Backup importado com sucesso.");
  }catch(err){
    state = migrate(snapshot);
    alert(err?.message || "JSON inválido.");
  }
});

$("#btnReset").addEventListener("click", async (e)=>{
  if(confirm("Apagar tudo?")){
    const snapshot = cloneStateSnapshot();
    replaceState(seed());
    if(!await persistStateOrRollback(snapshot, { button: e.currentTarget })) return;
    renderAll();
  }
});

/* ---------- Boot ---------- */
async function init(){
  try{
    await loadServerState();
  }catch(err){
    console.warn("Nao foi possivel carregar dados do MySQL. Usando estado inicial.", err);
  }
  applyFinancePermissions();
  $("#dashMes").value = toISODate(new Date()).slice(0,7);
  $("#dashConta").value = "ALL";
  $("#fConta").value = "ALL";
  renderAll();
  startFinanceRealtimeSync();
  const initialView = financeInitialView();
  if(initialView && $(`#view-${initialView}`) && canUseFinanceView(initialView)){
    setView(initialView);
  }else if(!canUseFinanceView("dashboard")){
    setView(firstAllowedFinanceView());
  }
  triggerFinanceReminders({ silent: true });

  window.addEventListener("hashchange", ()=>{
    const view = (location.hash || "").replace("#", "");
    if(view && $(`#view-${view}`)) setView(view);
  });
}

init();
