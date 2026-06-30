//////////////////////////////////////////////////////
// SISTEMA RIO BRANCO - VERSÃO API (MENU MOBILE FIX + ANIMAÇÃO)
//////////////////////////////////////////////////////

let fretes = [];
let freteKanbanFiltro = "";
const FRETE_AUTO_ARQUIVO_HORAS = 24;
const FRETE_AUTO_SAVE_DELAY_MS = 900;
const ESTOQUE_CAMERA_SCAN_INTERVAL_MS = 450;
const freteDraftState = new Map();

let cacheCadastros = {
  colaboradores: null,
  motoristas: null,  // compatibilidade com APIs antigas
  veiculos: null,
  cargas: null,
};

let cacheUsuarios = null;
const CHAT_AI_RIO_CONTACT_ID = "__ia_rio__";
const CHAT_AI_RIO_STORAGE_KEY = "riobranco_chat_ai_rio_state_v1";
const CHAT_AI_RIO_NAME = "I.A-Rio";
let pontosVendaState = {
  view: "cadastro",
  items: [],
  report: null,
  editId: 0,
  reportTimer: null,
};
let chatState = {
  usuarioId: "",
  contatoId: "",
  pollHandle: null,
  unreadByContato: {},
  isOpen: false,
  unreadReqSeq: 0,
  unreadAppliedSeq: 0,
  showExternalDialer: false,
  pendingAttachment: null,
  pendingSendBubble: null,
  sendingMessage: false,
  aiRioMessages: [],
  lastSeenMessageId: 0,
  audioCtx: null,
};
let sipState = {
  ua: null,
  currentSession: null,
  currentDirection: "",
  currentTargetLabel: "",
  dtmfHistory: "",
  isEndingCall: false,
  mode: "freepbx",
  config: null,
  profile: null,
  me: null,
  isConnected: false,
  isRegistered: false,
  _sessionKey: "",
  initPromise: null,
  connectWatchdog: null,
  connectTimedOut: false,
  authRepairPromise: null,
  lastAuthRepairKey: "",
  statusText: "SIP indisponivel.",
  statusLevel: "warn",
  toneTimer: null,
};
let statusState = {
  sip: null,
  nfe: null,
};
let nfeConfigState = null;
let vendasConfigState = null;
let vendasImportRulesState = null;
let nfePortalState = { lastKey: "", lastAt: 0, lastMode: "", lastContext: "" };
let vendasState = {
  view: "relatorio",
  lastPayload: null,
  mes: "",
  tipoRelatorio: "bonificacoes",
};
let dashboardVendasPainelState = {
  view: "bonificacoes",
  payload: null,
  cacheId: "",
};
let vendasConfigMonitorTimer = null;
let vendasConfigMonitorAtivo = false;
const abastecimentoDraftState = new Map();
const abastecimentoFeedbackState = new Map();
let abastecimentosCache = [];
let manutencaoOcrDraft = null;
let manutencaoItensDraft = [];
let manutencaoXmlPreLancamentoId = 0;
let manutencaoXmlPendencias = [];
let estoqueState = {
  view: "lancar",
  conferencias: [],
  conferenciaAtual: null,
  importDraft: null,
  importDraftDirty: false,
  lastPortalPreviewSignature: "",
  cadastroProdutos: [],
  cadastroProdutoEditId: 0,
  posicaoRows: [],
  posicaoMeta: {},
  movimentos: [],
  importacoesXml: [],
  importacoesXmlMeta: {},
  importacoesXmlSelecionadas: [],
  importacoesXmlLoteExecutando: false,
  importacoesXmlLoteProgresso: null,
  fretesImportacaoXml: [],
  manualPhotoUrl: "",
  manualPhotoName: "",
  cameraStream: null,
  cameraTimer: null,
  scanningCamera: false,
  cameraTargetFieldId: "",
  cameraAfterScanAction: null,
  ocrContext: null,
};
let usuarioLogado = null;
const LOGIN_STORAGE_KEY = "riobranco_usuario_logado";
const LOGIN_MAX_AGE_MS = 8 * 60 * 60 * 1000; // 8 horas
const LOGIN_BYPASS = new URLSearchParams(window.location.search).get("no_login") === "1";
const NFE_PORTAL_PREVIEW_STORAGE_KEY = "riobranco_nfe_portal_preview";

function _consumirRetornoPortalNfe(payload){
  const data = payload || {};
  if (data?.type === "riobranco_nfe_portal_preview") {
    const assinatura = JSON.stringify({
      chave: data?.preview?.chave_acesso || "",
      numero: data?.preview?.numero_nota || "",
      origem: data?.preview?.arquivo_origem || "",
      itens: Array.isArray(data?.preview?.itens) ? data.preview.itens.length : 0,
    });
    if (estoqueState.lastPortalPreviewSignature && estoqueState.lastPortalPreviewSignature === assinatura) {
      return true;
    }
    _aplicarPreviewPortalNfeEstoque(
      { ...(data.preview || {}), __signature: assinatura },
      "Consulta publica recebida automaticamente da aba do portal. Revise os dados na confirmacao."
    );
    return true;
  }
  if (data?.type === "riobranco_nfe_portal_preview_erro") {
    const status = document.getElementById("estoqueNfeImportStatus");
    const mensagem = data?.erro || "Falha ao receber o retorno da consulta publica.";
    if (status) status.textContent = mensagem;
    alert(mensagem);
    return true;
  }
  return false;
}

window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin) return;
  _consumirRetornoPortalNfe(event.data || {});
});

window.addEventListener("storage", (event) => {
  if (event.key !== NFE_PORTAL_PREVIEW_STORAGE_KEY || !event.newValue) return;
  try {
    const data = JSON.parse(event.newValue);
    if (_consumirRetornoPortalNfe(data?.payload || {})) {
      localStorage.removeItem(NFE_PORTAL_PREVIEW_STORAGE_KEY);
    }
  } catch (err) {
    console.warn("storage portal retorno erro:", err);
  }
});

function verificarRetornoPortalNfePendente(){
  try {
    const raw = localStorage.getItem(NFE_PORTAL_PREVIEW_STORAGE_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    if (_consumirRetornoPortalNfe(data?.payload || {})) {
      localStorage.removeItem(NFE_PORTAL_PREVIEW_STORAGE_KEY);
    }
  } catch (err) {
    console.warn("retorno portal pendente erro:", err);
  }
}


// Fetch para API sem cache (evita dados antigos após excluir/editar)
function _apiRequestHeaders(headers = {}){
  const h = { ...(headers || {}) };
  if (usuarioLogado?.id) h["X-Usuario-Id"] = String(usuarioLogado.id);
  if (usuarioLogado?.nome) h["X-Usuario-Nome"] = String(usuarioLogado.nome);
  if (usuarioLogado?.login) h["X-Usuario-Login"] = String(usuarioLogado.login);
  if (!h["X-Usuario-Logado"] && (usuarioLogado?.nome || usuarioLogado?.login)) {
    h["X-Usuario-Logado"] = `${usuarioLogado?.nome || ""} (${usuarioLogado?.login || ""})`.trim();
  }
  return { ...h, "Cache-Control": "no-cache" };
}

function _apiRequestUrl(url){
  return url + (url.includes("?") ? "&" : "?") + "_=" + Date.now();
}

async function apiFetch(url, options={}){
  const opt = {
    ...options,
    cache: "no-store",
    headers: _apiRequestHeaders(options.headers || {}),
  };
  return fetch(_apiRequestUrl(url), opt);
}

function apiUploadWithProgress(url, { method = "POST", body = null, headers = {}, timeoutMs = 0, signal = null, onProgress = null, onUploadComplete = null } = {}){
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    let settled = false;

    const finishResolve = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    const finishReject = (error) => {
      if (settled) return;
      settled = true;
      reject(error);
    };
    const abortError = (message) => {
      const err = new Error(message || "Request aborted");
      err.name = "AbortError";
      return err;
    };

    xhr.open(method, _apiRequestUrl(url), true);
    xhr.timeout = timeoutMs > 0 ? timeoutMs : 0;

    const finalHeaders = _apiRequestHeaders(headers);
    Object.entries(finalHeaders).forEach(([key, value]) => {
      xhr.setRequestHeader(key, value);
    });

    xhr.onload = () => {
      const responseText = xhr.responseText || "";
      finishResolve({
        ok: xhr.status >= 200 && xhr.status < 300,
        status: xhr.status,
        async json(){
          try {
            return JSON.parse(responseText || "{}");
          } catch {
            return {};
          }
        },
        async text(){
          return responseText;
        },
      });
    };
    xhr.onerror = () => finishReject(new Error("NetworkError"));
    xhr.onabort = () => finishReject(abortError("Request aborted"));
    xhr.ontimeout = () => finishReject(abortError("Request timeout"));

    if (xhr.upload && typeof onProgress === "function") {
      xhr.upload.onprogress = (event) => {
        onProgress(event);
      };
    }
    if (xhr.upload && typeof onUploadComplete === "function") {
      xhr.upload.onloadend = () => {
        onUploadComplete();
      };
    }

    if (signal) {
      if (signal.aborted) {
        finishReject(abortError("Request aborted"));
        return;
      }
      signal.addEventListener("abort", () => {
        try {
          xhr.abort();
        } catch {}
      }, { once: true });
    }

    xhr.send(body);
  });
}

//////////////////////////////////////////////////////
// MENU MOBILE (toggle + animação)
//////////////////////////////////////////////////////
function _getMenuEls() {
  return {
    menu: document.querySelector(".menu"),
    overlay: document.querySelector(".menu-overlay"),
    toggle: document.getElementById("menuToggle"),
  };
}

function _setToggleIcon(isOpen) {
  const { toggle } = _getMenuEls();
  if (!toggle) return;
  toggle.textContent = isOpen ? "✕" : "☰";
  toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
}

function toggleMenuMobile(force) {
  const { menu, overlay } = _getMenuEls();
  if (!menu || !overlay) return;

  const abrir =
    force !== undefined
      ? !!force
      : !menu.classList.contains("show");

  if (abrir) {
    menu.classList.add("show");
    overlay.classList.add("show");
    document.body.classList.add("menu-open");
  } else {
    menu.classList.remove("show");
    overlay.classList.remove("show");
    document.body.classList.remove("menu-open");
  }

  _setToggleIcon(abrir);
}

//////////////////////////////////////////////////////
// CADASTROS
//////////////////////////////////////////////////////
async function editarCadastro(tipo, id, nomeAtual) {
  let novoNome = prompt("Editar nome:", nomeAtual);
  if (!novoNome) return;

  const payload = { nome: novoNome };
  if (tipo === "cargas") {
    const cargaAtual = (cacheCadastros.cargas || []).find((item) => Number(item.id) === Number(id)) || {};
    const veiculoAtual = (cargaAtual.veiculo_numero || "").toString().trim();
    const novoVeiculo = prompt("Numero do veiculo:", veiculoAtual);
    if (novoVeiculo == null) return;
    payload.veiculo_numero = (novoVeiculo || "").trim();
  }

  await fetch(`/api/${tipo}/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  await renderCadastros();
  await carregarSelectsNovoFrete();
}

async function salvarCadastro(tipo, inputId) {
  const inp = document.getElementById(inputId);
  const nome = (inp?.value || "").trim();
  if (!nome) return alert("Informe um nome.");

  const payload = { nome };
  if (tipo === "cargas") {
    const veiculoNumero = (document.getElementById("cargasVeiculoNumero")?.value || "").trim();
    if (veiculoNumero) payload.veiculo_numero = veiculoNumero;
  }

  const endpoint = `/api/${tipo}`;
  const body = JSON.stringify(payload);

  const resp = await apiFetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });

  if (!resp.ok) {
    const t = await resp.text();
    console.error("ERRO ao salvar cadastro:", resp.status, t);
    alert("Erro ao salvar (veja o console F12).");
    return;
  }

  if (inp) inp.value = "";
  if (tipo === "cargas") {
    const veiculoInput = document.getElementById("cargasVeiculoNumero");
    if (veiculoInput) veiculoInput.value = "";
  }

  // Invalida cache (para selects e cards)
  cacheCadastros[tipo] = null;

  await renderCadastros();
  await carregarSelectsNovoFrete();

  try { await carregarSelectsDevolucao?.(); } catch {}
}

async function importarCargasCsv() {
  if (!confirm("Importar o CSV da pasta CARGAS e atualizar os cadastros?")) return;

  const fileInput = document.getElementById("cargasCsvFile");
  const veiculoInput = document.getElementById("cargasVeiculoNumero");
  const file = fileInput?.files?.[0] || null;
  const veiculoNumero = (veiculoInput?.value || "").trim();
  const options = { method: "POST" };
  if (file || veiculoNumero) {
    const formData = new FormData();
    if (file) formData.append("arquivo", file, file.name || "cargas.csv");
    if (veiculoNumero) formData.append("veiculo_numero", veiculoNumero);
    options.body = formData;
  }

  const resp = await apiFetch("/api/cargas/importar_csv", options);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || data?.ok === false) {
    alert(data?.erro || "Erro ao importar CSV de cargas.");
    return;
  }

  const resumo = [
    `${data.cargas_criadas || 0} criadas`,
    `${data.cargas_atualizadas || 0} atualizadas`,
    `${data.fretes_criados || 0} cards de frete`,
    `${data.fretes_atualizados || 0} cards de frete atualizados`,
    `${data.cidades_total || 0} cidades`,
    `${data.linhas_total || 0} linhas`,
  ].join(" | ");
  alert(`Importacao concluida: ${resumo}.`);

  cacheCadastros.cargas = null;
  await renderCadastros();
  await carregarSelectsNovoFrete();
  await carregarFretes().catch(() => {});
  if (fileInput) fileInput.value = "";
  if (veiculoInput) veiculoInput.value = "";
}

async function importarCargasPdf() {
  if (!confirm("Importar o PDF de cargas e atualizar os fretes vinculados?")) return;

  const fileInput = document.getElementById("cargasPdfFile");
  const veiculoInput = document.getElementById("cargasVeiculoNumero");
  const file = fileInput?.files?.[0] || null;
  const veiculoNumero = (veiculoInput?.value || "").trim();
  const formData = new FormData();
  if (file) formData.append("arquivo", file, file.name || "cargas.pdf");
  if (veiculoNumero) formData.append("veiculo_numero", veiculoNumero);

  const resp = await apiFetch("/api/cargas/importar_pdf", {
    method: "POST",
    body: formData,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || data?.ok === false) {
    alert(data?.erro || "Erro ao importar PDF de cargas.");
    return;
  }

  const resumo = [
    `${data.paginas_importadas || 0} paginas`,
    `${data.cargas_criadas || 0} cargas criadas`,
    `${data.cargas_atualizadas || 0} cargas atualizadas`,
    `${data.fretes_criados || 0} fretes criados`,
    `${data.fretes_atualizados || 0} fretes atualizados`,
    `${data.cargas_baixadas || 0} baixas no estoque`,
  ].join(" | ");
  alert(`Importacao concluida: ${resumo}.`);

  cacheCadastros.cargas = null;
  await renderCadastros();
  await carregarSelectsNovoFrete();
  await carregarFretes().catch(() => {});
  if (window.__dashView === "estoque") await renderDashboardEstoque().catch(() => {});
  if (fileInput) fileInput.value = "";
  if (veiculoInput) veiculoInput.value = "";
}

async function carregarUsuariosCadastro() {
  const resp = await apiFetch("/api/colaboradores");
  if (!resp.ok) return [];
  const lista = await resp.json();
  return (Array.isArray(lista) ? lista : [])
    .filter((item) => Number(item?.usuario_id || 0) > 0)
    .map((item) => ({
      id: Number(item.usuario_id),
      colaborador_id: Number(item.id || 0),
      nome: item.nome || "",
      login: item.login || item.usuario_login || "",
      ativo: true,
      sip_habilitado: !!Number(item.sip_habilitado || 0),
      sip_usuario: item.sip_usuario || item.login || item.usuario_login || "",
      sip_ramal: item.sip_ramal || "",
      codbar_modo: item.codbar_modo || "bip",
    }));
}
// Cadastro específico de veículos (unificação veiculos + frota)
async function salvarVeiculo() {
  const nome = (document.getElementById("novoVeiculoNome")?.value || "").trim();
  const placa = (document.getElementById("frota_placa")?.value || "").trim();
  const modelo = (document.getElementById("frota_modelo")?.value || "").trim();
  const km_atual_raw = (document.getElementById("frota_km")?.value || "").trim();
  const km_atual = km_atual_raw === "" ? null : Number(km_atual_raw);
  const int_manut_raw = (document.getElementById("frota_int_manut")?.value || "").trim();
  const intervalo_manut_km = int_manut_raw === "" ? null : Number(int_manut_raw);
  const int_oleo_raw = (document.getElementById("frota_int_oleo")?.value || "").trim();
  const intervalo_oleo_km = int_oleo_raw === "" ? null : Number(int_oleo_raw);
  const combustivel_padrao = document.getElementById("frota_combustivel_padrao")?.value || "diesel_500";

  if (!nome) return alert("Informe o nome do veículo.");

  await fetch(`/api/veiculos`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nome, placa, modelo, km_atual, intervalo_manut_km, intervalo_oleo_km, combustivel_padrao }),
  });

  if (document.getElementById("novoVeiculoNome")) document.getElementById("novoVeiculoNome").value = "";
  if (document.getElementById("frota_placa")) document.getElementById("frota_placa").value = "";
  if (document.getElementById("frota_modelo")) document.getElementById("frota_modelo").value = "";
  if (document.getElementById("frota_km")) document.getElementById("frota_km").value = "";
  if (document.getElementById("frota_int_manut")) document.getElementById("frota_int_manut").value = "";
  if (document.getElementById("frota_int_oleo")) document.getElementById("frota_int_oleo").value = "";
  if (document.getElementById("frota_combustivel_padrao")) document.getElementById("frota_combustivel_padrao").value = "diesel_500";

  await renderCadastros();
  await carregarSelectsNovoFrete();
  if (window.__dashView === "frota") {
    await renderDashboardFrota();
  }
}

async function editarVeiculo(id, nomeAtual, placaAtual, modeloAtual, kmAtual) {
  const novoNome = prompt("Editar nome do veículo:", nomeAtual ?? "");
  if (novoNome === null) return;

  const novaPlaca = prompt("Editar placa:", placaAtual ?? "");
  if (novaPlaca === null) return;

  const novoModelo = prompt("Editar modelo:", modeloAtual ?? "");
  if (novoModelo === null) return;

  const novoKmStr = prompt("Editar KM atual:", (kmAtual ?? "").toString());
  if (novoKmStr === null) return;
  const novoKm = novoKmStr.trim() === "" ? null : Number(novoKmStr.trim());

  await fetch(`/api/veiculos/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      nome: (novoNome || "").trim(),
      placa: (novaPlaca || "").trim(),
      modelo: (novoModelo || "").trim(),
      km_atual: novoKm,
    }),
  });

  await renderCadastros();
  await carregarSelectsNovoFrete();
  if (window.__dashView === "frota") {
    await renderDashboardFrota();
  }
}

async function carregarCadastro(tipo) {
  let r = await apiFetch(`/api/${tipo}`);
  const dados = await r.json();
  if (tipo === "cargas" && Array.isArray(dados)) {
    return dados.map((item) => {
      const veiculo = (item.veiculo_numero || "").toString().trim();
      const nomeBase = (item.nome || item.cidade || "Carga").toString().trim();
      return {
        ...item,
        optionLabel: veiculo ? `${nomeBase} - Veiculo ${veiculo}` : nomeBase,
      };
    });
  }
  return dados;
}

async function salvarVeiculoLinha(id) {
  const nome = (document.getElementById(`v_nome_${id}`)?.value || "").trim();
  const placa = (document.getElementById(`v_placa_${id}`)?.value || "").trim();
  const modelo = (document.getElementById(`v_modelo_${id}`)?.value || "").trim();
  const kmRaw = (document.getElementById(`v_km_${id}`)?.value || "").trim();
  const km_atual = kmRaw === "" ? null : Number(kmRaw);
  const intManutRaw = (document.getElementById(`v_int_manut_${id}`)?.value || "").trim();
  const intervalo_manut_km = intManutRaw === "" ? null : Number(intManutRaw);
  const intOleoRaw = (document.getElementById(`v_int_oleo_${id}`)?.value || "").trim();
  const intervalo_oleo_km = intOleoRaw === "" ? null : Number(intOleoRaw);
  const combustivel_padrao = document.getElementById(`v_combustivel_${id}`)?.value || "diesel_500";

  if (!nome) return alert("Informe o nome do veículo.");

  const resp = await fetch(`/api/veiculos/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nome, placa, modelo, km_atual, intervalo_manut_km, intervalo_oleo_km, combustivel_padrao }),
  });

  if (!resp.ok) {
    const t = await resp.text();
    console.error("ERRO ao salvar veículo:", resp.status, t);
    alert("Erro ao salvar veículo (veja o console F12).");
    return;
  }

  await renderCadastros();
  await carregarSelectsNovoFrete();
  if (window.__dashView === "frota") {
    await renderDashboardFrota();
  }
}

function _escAttr(v) {
  return String(v ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

// Escape para conteúdo HTML (texto dentro de tags)
function _escHtml(v) {
  return String(v ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function _asStr(value, fallback = "") {
  const texto = value == null ? "" : String(value);
  return texto.trim() ? texto : String(fallback ?? "");
}

function _asInt(value, fallback = 0) {
  const numero = Number.parseInt(value, 10);
  return Number.isFinite(numero) ? numero : Number.parseInt(fallback, 10) || 0;
}

function _asBool(value, fallback = false) {
  if (typeof value === "boolean") return value;
  if (value == null) return !!fallback;
  const texto = String(value).trim().toLowerCase();
  if (["1", "true", "sim", "yes", "on"].includes(texto)) return true;
  if (["0", "false", "nao", "não", "no", "off", ""].includes(texto)) return false;
  return Boolean(value);
}

function _as_str(value, fallback = "") {
  return _asStr(value, fallback);
}

function _modeloVeiculoEhFlex(modelo) {
  const tokens = String(modelo || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .split(/\s+/)
    .filter(Boolean);
  return ["gol", "polo", "saveiro"].some((modeloFlex) => tokens.includes(modeloFlex));
}

function sincronizarCombustivelModeloVeiculo(modeloInput, combustivelSelect) {
  if (_modeloVeiculoEhFlex(modeloInput?.value) && combustivelSelect) {
    combustivelSelect.value = "flex";
  }
}

function veiculoRowTemplate(v) {
  const nome = v.nome ?? "";
  const placa = v.placa ?? "";
  const modelo = v.modelo ?? "";
  const km = v.km_atual ?? v.km ?? "";

  return `
    <li style="display:flex; gap:10px; align-items:center; justify-content:space-between;">
      <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
        <input id="v_nome_${v.id}" value="${_escAttr(nome)}" placeholder="Nome" style="width:170px;">
        <input id="v_placa_${v.id}" value="${_escAttr(placa)}" placeholder="Placa" style="width:110px;">
        <input id="v_modelo_${v.id}" list="modelosVeiculos" value="${_escAttr(modelo)}" placeholder="Modelo" style="width:170px;" oninput="sincronizarCombustivelModeloVeiculo(this, document.getElementById('v_combustivel_${v.id}'))">
        <input id="v_km_${v.id}" value="${_escAttr(km)}" placeholder="KM" type="number" style="width:110px;">
        <input id="v_int_manut_${v.id}" value="${_escAttr(v.intervalo_manut_km ?? '')}" placeholder="Int. Manut (KM)" type="number" style="width:140px;">
        <input id="v_int_oleo_${v.id}" value="${_escAttr(v.intervalo_oleo_km ?? '')}" placeholder="Int. Óleo (KM)" type="number" style="width:140px;">
        <select id="v_combustivel_${v.id}" style="width:160px;">
          <option value="diesel_500" ${_normalizarCombustivelPadraoVeiculo(v.combustivel_padrao) === "diesel_500" ? "selected" : ""}>Diesel 500</option>
          <option value="diesel_s10" ${_normalizarCombustivelPadraoVeiculo(v.combustivel_padrao) === "diesel_s10" ? "selected" : ""}>Diesel S10</option>
          <option value="gasolina" ${_normalizarCombustivelPadraoVeiculo(v.combustivel_padrao) === "gasolina" ? "selected" : ""}>Gasolina</option>
          <option value="etanol" ${_normalizarCombustivelPadraoVeiculo(v.combustivel_padrao) === "etanol" ? "selected" : ""}>Etanol</option>
          <option value="flex" ${_normalizarCombustivelPadraoVeiculo(v.combustivel_padrao) === "flex" ? "selected" : ""}>Flex</option>
        </select>
      </div>
      <div style="display:flex; gap:6px;">
        <button onclick="salvarVeiculoLinha(${v.id})">💾</button>
        <button onclick="deletar('veiculos', ${v.id})">❌</button>
      </div>
    </li>
  `;
}

function cadastroEmptyItem(msg) {
  return `<li class="cadastro-empty">${_escHtml(msg)}</li>`;
}

function _buscarColaboradorCadastro(colaboradorId){
  if (!colaboradorId) return null;
  const idStr = String(colaboradorId);
  return (
    (cacheCadastros.colaboradores || []).find((item) => String(item.id) === idStr) ||
    (cacheCadastros.motoristas || []).find((item) => String(item.id) === idStr) ||
    null
  );
}

function _colaboradorTemFuncao(colaborador, funcao){
  if (!colaborador) return false;
  const mapa = {
    motorista: "is_motorista",
    entregador: "is_entregador",
    ajudante: "is_ajudante",
    conferente: "is_conferente",
    vendedor: "is_vendedor",
  };
  const campo = mapa[funcao] || "";
  return campo ? !!Number(colaborador[campo] || 0) : false;
}

function _listaColaboradoresPorFuncao(funcao){
  return _ordenarListaNatural((cacheCadastros.colaboradores || []).filter((item) => _colaboradorTemFuncao(item, funcao)));
}

function _textoFuncoesColaborador(colaborador){
  const funcoes = [];
  if (_colaboradorTemFuncao(colaborador, "motorista")) funcoes.push("Motorista");
  if (_colaboradorTemFuncao(colaborador, "entregador")) funcoes.push("Entregador");
  if (_colaboradorTemFuncao(colaborador, "ajudante")) funcoes.push("Ajudante");
  if (_colaboradorTemFuncao(colaborador, "conferente")) funcoes.push("Conferente");
  if (_colaboradorTemFuncao(colaborador, "vendedor")) funcoes.push("Vendedor");
  return funcoes.length ? funcoes.join(" • ") : "Sem funcao";
}

function _coletarPapeisColaborador(sufixo = ""){
  const motorista = document.getElementById(`colaboradorMotorista${sufixo}`) || document.getElementById(`novoColaboradorMotorista`);
  const entregador = document.getElementById(`colaboradorEntregador${sufixo}`) || document.getElementById(`novoColaboradorEntregador`);
  const ajudante = document.getElementById(`colaboradorAjudante${sufixo}`) || document.getElementById(`novoColaboradorAjudante`);
  const conferente = document.getElementById(`colaboradorConferente${sufixo}`) || document.getElementById(`novoColaboradorConferente`);
  const vendedor = document.getElementById(`colaboradorVendedor${sufixo}`) || document.getElementById(`novoColaboradorVendedor`);
  const email = document.getElementById(`colaboradorEmail${sufixo}`) || document.getElementById(`novoColaboradorEmail`);
  const cpf = document.getElementById(`colaboradorCpf${sufixo}`) || document.getElementById(`novoColaboradorCpf`);
  return {
    is_motorista: !!motorista?.checked,
    is_entregador: !!entregador?.checked,
    is_ajudante: !!ajudante?.checked,
    is_conferente: !!conferente?.checked,
    is_vendedor: !!vendedor?.checked,
    email: (email?.value || "").trim(),
    cpf: (cpf?.value || "").trim(),
  };
}

function colaboradorRowTemplate(colaborador) {
  return `
    <li class="colaborador-row">
      <div class="colaborador-row-main">
        <input id="colaboradorNome_${colaborador.id}" value="${_escAttr(colaborador.nome || "")}" placeholder="Nome do colaborador">
        <input id="colaboradorEmail_${colaborador.id}" value="${_escAttr(colaborador.email || "")}" placeholder="Email" class="colaborador-email-input">
        <input id="colaboradorCpf_${colaborador.id}" value="${_escAttr(colaborador.cpf || "")}" placeholder="CPF" class="colaborador-cpf-input">
        <div class="colaborador-row-checks">
          <label class="colaborador-check"><input type="checkbox" id="colaboradorMotorista_${colaborador.id}" ${_colaboradorTemFuncao(colaborador, "motorista") ? "checked" : ""}> Motorista</label>
          <label class="colaborador-check"><input type="checkbox" id="colaboradorEntregador_${colaborador.id}" ${_colaboradorTemFuncao(colaborador, "entregador") ? "checked" : ""}> Entregador</label>
          <label class="colaborador-check"><input type="checkbox" id="colaboradorAjudante_${colaborador.id}" ${_colaboradorTemFuncao(colaborador, "ajudante") ? "checked" : ""}> Ajudante</label>
          <label class="colaborador-check"><input type="checkbox" id="colaboradorConferente_${colaborador.id}" ${_colaboradorTemFuncao(colaborador, "conferente") ? "checked" : ""}> Conferente</label>
          <label class="colaborador-check"><input type="checkbox" id="colaboradorVendedor_${colaborador.id}" ${_colaboradorTemFuncao(colaborador, "vendedor") ? "checked" : ""}> Vendedor</label>
        </div>
        <div class="colaborador-row-user">
          <input id="colaboradorLogin_${colaborador.id}" value="${_escAttr(colaborador.login || "")}" placeholder="Login">
          <input id="colaboradorSenha_${colaborador.id}" type="password" value="" placeholder="Nova senha">
          <label class="config-check"><input type="checkbox" id="colaboradorSipHabilitado_${colaborador.id}" ${_asBool(colaborador.sip_habilitado, false) ? "checked" : ""}> SIP externo</label>
          <input id="colaboradorSipUsuario_${colaborador.id}" value="${_escAttr(colaborador.sip_usuario || "")}" placeholder="Usuario SIP">
          <input id="colaboradorSipSenha_${colaborador.id}" type="password" value="" placeholder="Nova senha SIP">
          <input id="colaboradorSipRamal_${colaborador.id}" value="${_escAttr(colaborador.sip_ramal || "")}" placeholder="Ramal">
          <select id="colaboradorCodbarModo_${colaborador.id}">
            <option value="bip"${String(colaborador.codbar_modo || "bip") === "bip" ? " selected" : ""}>CODBAR: Bip/Leitor</option>
            <option value="camera"${String(colaborador.codbar_modo || "bip") === "camera" ? " selected" : ""}>CODBAR: Camera/Webcam</option>
          </select>
        </div>
        <div class="colaborador-funcoes-texto">${_escHtml(_textoFuncoesColaborador(colaborador))}</div>
      </div>
      <div class="colaborador-row-actions">
        <button onclick="salvarColaboradorLinha(${colaborador.id})">💾</button>
        <button onclick="deletar('colaboradores', ${colaborador.id})">❌</button>
      </div>
    </li>
  `;
}

async function renderCadastros() {
  await ensureCadastrosCache();

  const colaboradores = _ordenarListaNatural(cacheCadastros.colaboradores || []);
  const veiculos = _ordenarListaNatural(cacheCadastros.veiculos || []);
  const cargas = _ordenarListaNatural(cacheCadastros.cargas || []);

  const listaColaboradores = document.getElementById("listaMotoristas");
  if (listaColaboradores) {
    listaColaboradores.innerHTML = colaboradores.length ? colaboradores.map(colaboradorRowTemplate).join("") : cadastroEmptyItem("Nenhum colaborador cadastrado.");
  }

  const listaVeiculos = document.getElementById("listaVeiculos");
  if (listaVeiculos) {
    listaVeiculos.innerHTML = veiculos.length ? veiculos.map(veiculoRowTemplate).join("") : cadastroEmptyItem("Nenhum veiculo cadastrado.");
  }

  const listaCargas = document.getElementById("listaCargas");
  if (listaCargas) {
    listaCargas.innerHTML = cargas.length ? cargas
      .map((d) => `
        <li>
          <div style="display:flex; flex-direction:column; gap:2px;">
            <span>${_escHtml(d.nome || d.optionLabel || "-")}</span>
            <small style="opacity:.75;">${_escHtml(d.veiculo_numero ? `Veiculo ${d.veiculo_numero}` : "Sem veiculo")}</small>
          </div>
          <div>
            <button onclick="editarCadastro('cargas', ${d.id}, '${_escJsString(d.nome)}')">✏</button>
            <button onclick="deletar('cargas', ${d.id})">❌</button>
          </div>
        </li>
      `)
      .join("") : cadastroEmptyItem("Nenhuma carga cadastrada.");
  }

  if (window.__cargasView === "escala") {
    try { await renderEscala(); } catch (e) { console.warn("escala cadastro erro:", e); }
  }
}

function _pontosVendaOpcoesDiaSemana(selected = "") {
  const opcoes = [
    ["", "Dia da semana"],
    ["0", "Segunda-feira"],
    ["1", "Terca-feira"],
    ["2", "Quarta-feira"],
    ["3", "Quinta-feira"],
    ["4", "Sexta-feira"],
    ["5", "Sabado"],
    ["6", "Domingo"],
  ];
  return opcoes.map(([value, label]) => `<option value="${_escAttr(value)}"${String(selected) === String(value) ? " selected" : ""}>${_escHtml(label)}</option>`).join("");
}

function _pontosVendaDiaLabel(item) {
  return ["Segunda-feira", "Terca-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sabado", "Domingo"][Number(item?.dia_semana ?? -1)] || "-";
}

function _pontosVendaPeriodoLabel(item) {
  return String(item?.visita_periodicidade || "").toLowerCase() === "quinzenal" ? "Quinzenal" : "Semanal";
}

function _dataHojeInputLocal() {
  const agora = new Date();
  const local = new Date(agora.getTime() - (agora.getTimezoneOffset() * 60000));
  return local.toISOString().slice(0, 10);
}

function _pontosVendaSelecionado(formId, value) {
  const el = document.getElementById(formId);
  if (!el) return false;
  return String(el.value || "") === String(value || "");
}

function _pontosVendaPreencherFiltros(items = []) {
  const vendedorSel = document.getElementById("pontosVendaFiltroVendedor");
  const clienteSel = document.getElementById("pontosVendaFiltroCliente");
  const rotaSel = document.getElementById("pontosVendaFiltroRota");
  const selectedVendedor = vendedorSel?.value || "";
  const selectedCliente = clienteSel?.value || "";
  const selectedRota = rotaSel?.value || "";

  const vendedores = new Map();
  const clientes = new Map();
  const rotas = new Map();
  (items || []).forEach((item) => {
    if (item?.vendedor) vendedores.set(item.vendedor, item.vendedor);
    if (item?.cliente) clientes.set(item.cliente, item.cliente);
    if (item?.rota) rotas.set(item.rota, item.rota);
  });

  if (vendedorSel) {
    vendedorSel.innerHTML = ['<option value="">Todos os vendedores</option>'].concat(
      Array.from(vendedores.keys()).sort((a, b) => a.localeCompare(b, "pt-BR", { numeric: true, sensitivity: "base" })).map((item) => `<option value="${_escAttr(item)}">${_escHtml(item)}</option>`)
    ).join("");
    vendedorSel.value = selectedVendedor;
  }
  if (clienteSel) {
    clienteSel.innerHTML = ['<option value="">Todos os clientes</option>'].concat(
      Array.from(clientes.keys()).sort((a, b) => a.localeCompare(b, "pt-BR", { numeric: true, sensitivity: "base" })).map((item) => `<option value="${_escAttr(item)}">${_escHtml(item)}</option>`)
    ).join("");
    clienteSel.value = selectedCliente;
  }
  if (rotaSel) {
    rotaSel.innerHTML = ['<option value="">Todas as rotas</option>'].concat(
      Array.from(rotas.keys()).sort((a, b) => a.localeCompare(b, "pt-BR", { numeric: true, sensitivity: "base" })).map((item) => `<option value="${_escAttr(item)}">${_escHtml(item)}</option>`)
    ).join("");
    rotaSel.value = selectedRota;
  }
}

function atualizarVisibilidadeFiltrosPontosVenda() {
  const vendedor = document.getElementById("pontosVendaFiltroVendedor")?.value || "";
  const cliente = document.getElementById("pontosVendaFiltroCliente")?.value || "";
  const vendedorWrap = document.getElementById("pontosVendaVendedorWrap");
  const clienteWrap = document.getElementById("pontosVendaClienteWrap");
  if (vendedorWrap) vendedorWrap.classList.toggle("hidden", !!cliente && !vendedor);
  if (clienteWrap) clienteWrap.classList.toggle("hidden", !!vendedor && !cliente);
}

function renderPontosVendaLista(items = []) {
  const body = document.getElementById("pontosVendaBody");
  if (!body) return;
  body.innerHTML = items.length ? items.map((item) => `
    <tr>
      <td>${_escHtml(item.vendedor || "-")}</td>
      <td>${_escHtml(item.cliente || "-")}</td>
      <td>${_escHtml(item.rota || "-")}</td>
      <td>${_escHtml(_pontosVendaPeriodoLabel(item))}</td>
      <td>${_escHtml(item.dia_semana_label || _pontosVendaDiaLabel(item))}</td>
      <td>${_escHtml(item.data_base || "-")}</td>
      <td>${_escHtml(item.ativo ? "Sim" : "Nao")}</td>
      <td>
        <button type="button" onclick="editarPontoVenda(${item.id})">✏</button>
        <button type="button" onclick="deletarPontoVenda(${item.id})">❌</button>
      </td>
    </tr>
  `).join("") : '<tr><td colspan="8">Nenhum ponto de venda cadastrado.</td></tr>';
}

function limparFormularioPontoVenda() {
  pontosVendaState.editId = 0;
  const campos = {
    id: document.getElementById("pontosVendaId"),
    vendedor: document.getElementById("pontosVendaVendedor"),
    cliente: document.getElementById("pontosVendaCliente"),
    rota: document.getElementById("pontosVendaRota"),
    periodicidade: document.getElementById("pontosVendaPeriodicidade"),
    dia: document.getElementById("pontosVendaDiaSemana"),
    base: document.getElementById("pontosVendaDataBase"),
    obs: document.getElementById("pontosVendaObservacao"),
    ativo: document.getElementById("pontosVendaAtivo"),
    status: document.getElementById("pontosVendaFormStatus"),
  };
  if (campos.id) campos.id.value = "";
  if (campos.vendedor) campos.vendedor.value = "";
  if (campos.cliente) campos.cliente.value = "";
  if (campos.rota) campos.rota.value = "";
  if (campos.periodicidade) campos.periodicidade.value = "semanal";
  if (campos.dia) campos.dia.value = "";
  if (campos.base) campos.base.value = "";
  if (campos.obs) campos.obs.value = "";
  if (campos.ativo) campos.ativo.checked = true;
  if (campos.status) campos.status.textContent = "Preencha os campos e salve. Se houver cadastro parecido, o sistema vai pedir confirmação para evitar duplicidade.";
}

function editarPontoVenda(id) {
  const item = (pontosVendaState.items || []).find((row) => String(row.id) === String(id));
  if (!item) return;
  pontosVendaState.editId = Number(item.id) || 0;
  const campos = {
    id: document.getElementById("pontosVendaId"),
    vendedor: document.getElementById("pontosVendaVendedor"),
    cliente: document.getElementById("pontosVendaCliente"),
    rota: document.getElementById("pontosVendaRota"),
    periodicidade: document.getElementById("pontosVendaPeriodicidade"),
    dia: document.getElementById("pontosVendaDiaSemana"),
    base: document.getElementById("pontosVendaDataBase"),
    obs: document.getElementById("pontosVendaObservacao"),
    ativo: document.getElementById("pontosVendaAtivo"),
    status: document.getElementById("pontosVendaFormStatus"),
  };
  if (campos.id) campos.id.value = String(item.id || "");
  if (campos.vendedor) campos.vendedor.value = item.vendedor || "";
  if (campos.cliente) campos.cliente.value = item.cliente || "";
  if (campos.rota) campos.rota.value = item.rota || "";
  if (campos.periodicidade) campos.periodicidade.value = item.visita_periodicidade || "semanal";
  if (campos.dia) campos.dia.value = item.dia_semana != null ? String(item.dia_semana) : "";
  if (campos.base) campos.base.value = item.data_base || "";
  if (campos.obs) campos.obs.value = item.observacao || "";
  if (campos.ativo) campos.ativo.checked = !!item.ativo;
  if (campos.status) campos.status.textContent = `Editando registro #${item.id}. Salve para atualizar.`;
}

async function carregarPontosVenda() {
  const resp = await apiFetch("/api/pontos_venda");
  const data = await resp.json().catch(() => []);
  if (!resp.ok) throw new Error((data && data.erro) || "Falha ao carregar pontos de venda.");
  pontosVendaState.items = Array.isArray(data) ? data : [];
  _pontosVendaPreencherFiltros(pontosVendaState.items);
  renderPontosVendaLista(pontosVendaState.items);
  atualizarVisibilidadeFiltrosPontosVenda();
  if (pontosVendaState.view === "relatorio") {
    await carregarPontosVendaRelatorio().catch(() => {});
  }
  return pontosVendaState.items;
}

async function salvarPontoVenda() {
  const id = Number(document.getElementById("pontosVendaId")?.value || pontosVendaState.editId || 0);
  const payload = {
    vendedor: document.getElementById("pontosVendaVendedor")?.value || "",
    cliente: document.getElementById("pontosVendaCliente")?.value || "",
    rota: document.getElementById("pontosVendaRota")?.value || "",
    visita_periodicidade: document.getElementById("pontosVendaPeriodicidade")?.value || "semanal",
    dia_semana: document.getElementById("pontosVendaDiaSemana")?.value || "",
    data_base: document.getElementById("pontosVendaDataBase")?.value || "",
    observacao: document.getElementById("pontosVendaObservacao")?.value || "",
    ativo: !!document.getElementById("pontosVendaAtivo")?.checked,
  };
  const status = document.getElementById("pontosVendaFormStatus");
  if (status) status.textContent = "Salvando ponto de venda...";

  const method = id > 0 ? "PUT" : "POST";
  const url = id > 0 ? `/api/pontos_venda/${id}` : "/api/pontos_venda";
  const resp = await apiFetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (resp.status === 409 && data?.registro_existente) {
      const candidato = data.registro_existente;
      const msg = `Cadastro semelhante encontrado para ${candidato.vendedor} / ${candidato.cliente} / ${candidato.rota}.\n\nDeseja confirmar que se trata do mesmo cadastro?`;
      if (!confirm(msg)) {
        if (status) status.textContent = "Operação cancelada. Ajuste os dados e tente novamente.";
        return;
      }
      const forceResp = await apiFetch(id > 0 ? `/api/pontos_venda/${id}` : "/api/pontos_venda", {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, force: true }),
      });
      const forceData = await forceResp.json().catch(() => ({}));
      if (!forceResp.ok) {
        if (status) status.textContent = forceData?.erro || "Falha ao salvar ponto de venda.";
        alert(forceData?.erro || "Falha ao salvar ponto de venda.");
        return;
      }
      if (status) status.textContent = "Ponto de venda salvo com confirmação de cadastro semelhante.";
    } else {
      if (status) status.textContent = data?.erro || "Falha ao salvar ponto de venda.";
      alert(data?.erro || "Falha ao salvar ponto de venda.");
      return;
    }
  } else if (status) {
    status.textContent = "Ponto de venda salvo com sucesso.";
  }

  limparFormularioPontoVenda();
  await carregarPontosVenda().catch(() => {});
}

async function deletarPontoVenda(id) {
  if (!confirm("Excluir este ponto de venda?")) return;
  const resp = await apiFetch(`/api/pontos_venda/${id}`, { method: "DELETE" });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    alert(data?.erro || "Falha ao excluir ponto de venda.");
    return;
  }
  await carregarPontosVenda().catch(() => {});
}

async function importarPontosVendaCsv(force = false) {
  const fileInput = document.getElementById("pontosVendaCsvFile");
  const file = fileInput?.files?.[0] || null;
  if (!file) return alert("Selecione um CSV antes de importar.");
  const formData = new FormData();
  formData.append("arquivo", file, file.name || "pontos_venda.csv");
  if (force) formData.append("force", "1");
  const resp = await apiFetch("/api/pontos_venda/importar_csv", {
    method: "POST",
    body: formData,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (resp.status === 409 && Array.isArray(data?.duplicados) && data.duplicados.length) {
      const texto = data.duplicados.slice(0, 5).map((item) => {
        const ex = item?.existente || {};
        return `Linha ${item.linha}: ${ex.vendedor || "-"} / ${ex.cliente || "-"} / ${ex.rota || "-"}`;
      }).join("\n");
      if (confirm(`Foram encontrados cadastros semelhantes:\n\n${texto}\n\nDeseja importar mesmo assim?`)) {
        return importarPontosVendaCsv(true);
      }
    }
    alert(data?.erro || "Falha ao importar pontos de venda.");
    return;
  }
  if (Number(data?.ignorados || 0) > 0) {
    alert(`Importação concluída. Inseridos: ${data?.inseridos || 0}, atualizados: ${data?.atualizados || 0}, ignorados por duplicidade no arquivo: ${data?.ignorados || 0}.`);
  } else {
    alert(`Importação concluída. Inseridos: ${data?.inseridos || 0}, atualizados: ${data?.atualizados || 0}.`);
  }
  if (fileInput) fileInput.value = "";
  await carregarPontosVenda().catch(() => {});
}

function agendarCarregarPontosVendaRelatorio(delayMs = 200) {
  if (pontosVendaState.reportTimer) clearTimeout(pontosVendaState.reportTimer);
  pontosVendaState.reportTimer = setTimeout(() => {
    pontosVendaState.reportTimer = null;
    carregarPontosVendaRelatorio().catch((err) => console.warn("pontos de venda relatorio erro:", err));
  }, delayMs);
}

function limparFiltrosPontosVenda() {
  const dataRef = document.getElementById("pontosVendaDataRef");
  const vendedor = document.getElementById("pontosVendaFiltroVendedor");
  const cliente = document.getElementById("pontosVendaFiltroCliente");
  const rota = document.getElementById("pontosVendaFiltroRota");
  if (dataRef) dataRef.value = "";
  if (vendedor) vendedor.value = "";
  if (cliente) cliente.value = "";
  if (rota) rota.value = "";
  atualizarVisibilidadeFiltrosPontosVenda();
  agendarCarregarPontosVendaRelatorio();
}

function _pontosVendaResumoCards(resumo = {}) {
  return [
    ["Visitas", _fmtNumVendas(resumo.total)],
    ["Semanais", _fmtNumVendas(resumo.semanal)],
    ["Quinzenais", _fmtNumVendas(resumo.quinzenal)],
    ["Vendedores", _fmtNumVendas(resumo.vendedores)],
    ["Clientes", _fmtNumVendas(resumo.clientes)],
    ["Rotas", _fmtNumVendas(resumo.rotas)],
  ];
}

function renderRelatorioPontosVenda(payload = {}) {
  pontosVendaState.report = payload;
  const resumo = payload?.resumo || {};
  const filtros = payload?.filtros || {};
  const itens = Array.isArray(payload?.itens) ? payload.itens : [];
  const dias = Array.isArray(payload?.dias) ? payload.dias : [];
  const info = document.getElementById("pontosVendaRelatorioInfo");
  if (info) {
    info.textContent = `Semana de ${filtros.semana_inicio || "-"} até ${filtros.semana_fim || "-"}${filtros.vendedor ? ` | Vendedor: ${filtros.vendedor}` : ""}${filtros.cliente ? ` | Cliente: ${filtros.cliente}` : ""}${filtros.rota ? ` | Rota: ${filtros.rota}` : ""}`;
  }
  const cards = document.getElementById("pontosVendaResumoCards");
  if (cards) {
    cards.innerHTML = _renderCardsVendasResumo(_pontosVendaResumoCards(resumo));
  }
  const body = document.getElementById("pontosVendaRelatorioBody");
  if (body) {
    body.innerHTML = itens.length ? itens.map((item) => `
      <tr>
        <td>${_escHtml(item.visita_em || "-")}</td>
        <td>${_escHtml(item.dia_semana_label || _pontosVendaDiaLabel(item))}</td>
        <td>${_escHtml(item.vendedor || "-")}</td>
        <td>${_escHtml(item.cliente || "-")}</td>
        <td>${_escHtml(item.rota || "-")}</td>
        <td>${_escHtml(item.visita_periodicidade_label || _pontosVendaPeriodoLabel(item))}</td>
        <td>${_escHtml(item.data_base || "-")}</td>
        <td>${_escHtml(item.ativo ? "Sim" : "Nao")}</td>
        <td>${_escHtml(item.observacao || "-")}</td>
      </tr>
    `).join("") : '<tr><td colspan="9">Nenhum ponto de venda previsto para a semana selecionada.</td></tr>';
  }
  const dataRef = document.getElementById("pontosVendaDataRef");
  if (dataRef && !dataRef.value && filtros?.data_ref) dataRef.value = filtros.data_ref;
  const vendedorSel = document.getElementById("pontosVendaFiltroVendedor");
  const clienteSel = document.getElementById("pontosVendaFiltroCliente");
  const rotaSel = document.getElementById("pontosVendaFiltroRota");
  if (vendedorSel && !vendedorSel.value && filtros?.vendedor) vendedorSel.value = filtros.vendedor;
  if (clienteSel && !clienteSel.value && filtros?.cliente) clienteSel.value = filtros.cliente;
  if (rotaSel && !rotaSel.value && filtros?.rota) rotaSel.value = filtros.rota;
  _pontosVendaPreencherFiltros((pontosVendaState.items && pontosVendaState.items.length ? pontosVendaState.items : itens) || []);
  atualizarVisibilidadeFiltrosPontosVenda();
  return { resumo, itens, dias };
}

async function carregarPontosVendaRelatorio() {
  const params = new URLSearchParams();
  const dataRef = document.getElementById("pontosVendaDataRef")?.value || "";
  const vendedor = document.getElementById("pontosVendaFiltroVendedor")?.value || "";
  const cliente = document.getElementById("pontosVendaFiltroCliente")?.value || "";
  const rota = document.getElementById("pontosVendaFiltroRota")?.value || "";
  if (dataRef) params.set("data_ref", dataRef);
  if (vendedor) params.set("vendedor", vendedor);
  if (cliente) params.set("cliente", cliente);
  if (rota) params.set("rota", rota);
  const resp = await apiFetch(`/api/pontos_venda/relatorio?${params.toString()}`);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data?.erro || "Falha ao carregar relatório de pontos de venda.");
  renderRelatorioPontosVenda(data || {});
  return data;
}

function _escJsString(v) {
  return String(v ?? "").replaceAll("\\", "\\\\").replaceAll("'", "\\'");
}

function _coletarDadosUsuarioColaborador(baseId, suffix = "") {
  const sufixo = String(suffix || "");
  return {
    login: (document.getElementById(`${baseId}Login${sufixo}`)?.value || "").trim(),
    senha: (document.getElementById(`${baseId}Senha${sufixo}`)?.value || "").trim(),
    sip_habilitado: !!document.getElementById(`${baseId}SipHabilitado${sufixo}`)?.checked,
    sip_usuario: (document.getElementById(`${baseId}SipUsuario${sufixo}`)?.value || "").trim(),
    sip_senha: (document.getElementById(`${baseId}SipSenha${sufixo}`)?.value || "").trim(),
    sip_ramal: (document.getElementById(`${baseId}SipRamal${sufixo}`)?.value || "").trim(),
    codbar_modo: (document.getElementById(`${baseId}CodbarModo${sufixo}`)?.value || "bip").trim() || "bip",
  };
}

function _limparFormularioNovoColaboradorUsuario() {
  const campos = [
    "novoColaboradorLogin",
    "novoColaboradorSenha",
    "novoColaboradorSipHabilitado",
    "novoColaboradorSipUsuario",
    "novoColaboradorSipSenha",
    "novoColaboradorSipRamal"
  ];

  campos.forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      if (id === "novoColaboradorSipHabilitado") {
        el.checked = false;
      } else {
        el.value = "";
      }
    }
  });

  const select = document.getElementById("novoColaboradorCodbarModo");
  if (select) select.value = "bip";
}

async function salvarColaboradorCadastro() {
  const nomeEl = document.getElementById("novoColaboradorNome");
  const nome = (nomeEl?.value || "").trim();
  const payload = { nome, ..._coletarPapeisColaborador("") };
  const dadosUsuario = _coletarDadosUsuarioColaborador("novoColaborador");

  if (!nome) {
    alert("Informe o nome do colaborador.");
    return;
  }
  if (!payload.is_motorista && !payload.is_entregador && !payload.is_ajudante && !payload.is_conferente && !payload.is_vendedor && !dadosUsuario.login) {
    alert("Marque ao menos uma funcao ou informe os dados de acesso do colaborador.");
    return;
  }
  payload.login = dadosUsuario.login;
  if (dadosUsuario.senha) payload.senha = dadosUsuario.senha;
  payload.sip_habilitado = dadosUsuario.sip_habilitado ? 1 : 0;
  payload.sip_usuario = dadosUsuario.sip_usuario;
  payload.sip_senha = dadosUsuario.sip_senha;
  payload.sip_ramal = dadosUsuario.sip_ramal;
  payload.codbar_modo = dadosUsuario.codbar_modo;

  const resp = await apiFetch("/api/colaboradores", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || data?.ok === false) {
    alert(data?.erro || "Erro ao salvar colaborador.");
    return;
  }

  if (nomeEl) nomeEl.value = "";
  const emailEl = document.getElementById("novoColaboradorEmail");
  const cpfEl = document.getElementById("novoColaboradorCpf");
  const chkMotorista = document.getElementById("novoColaboradorMotorista");
  const chkEntregador = document.getElementById("novoColaboradorEntregador");
  const chkAjudante = document.getElementById("novoColaboradorAjudante");
  const chkConferente = document.getElementById("novoColaboradorConferente");
  const chkVendedor = document.getElementById("novoColaboradorVendedor");
  if (emailEl) emailEl.value = "";
  if (cpfEl) cpfEl.value = "";
  if (chkMotorista) chkMotorista.checked = false;
  if (chkEntregador) chkEntregador.checked = false;
  if (chkAjudante) chkAjudante.checked = false;
  if (chkConferente) chkConferente.checked = false;
  if (chkVendedor) chkVendedor.checked = false;

  _limparFormularioNovoColaboradorUsuario();

  cacheCadastros.colaboradores = null;
  cacheCadastros.motoristas = null;  // manter compatibilidade
  cacheUsuarios = null;  // limpar cache de usuários também
  await renderCadastros();
  await carregarSelectsNovoFrete();
  await renderFretes().catch(() => {});
}

async function salvarColaboradorLinha(id) {
  const nome = (document.getElementById(`colaboradorNome_${id}`)?.value || "").trim();
  const payload = { nome, ..._coletarPapeisColaborador(`_${id}`) };
  const dadosUsuario = _coletarDadosUsuarioColaborador("colaborador", `_${id}`);

  if (!nome) {
    alert("Informe o nome do colaborador.");
    return;
  }
  if (!payload.is_motorista && !payload.is_entregador && !payload.is_ajudante && !payload.is_conferente && !payload.is_vendedor && !dadosUsuario.login) {
    alert("Marque ao menos uma funcao ou informe os dados de acesso do colaborador.");
    return;
  }
  payload.login = dadosUsuario.login;
  if (dadosUsuario.senha) payload.senha = dadosUsuario.senha;
  payload.sip_habilitado = dadosUsuario.sip_habilitado ? 1 : 0;
  payload.sip_usuario = dadosUsuario.sip_usuario;
  payload.sip_senha = dadosUsuario.sip_senha;
  payload.sip_ramal = dadosUsuario.sip_ramal;
  payload.codbar_modo = dadosUsuario.codbar_modo;

  const resp = await apiFetch(`/api/colaboradores/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || data?.ok === false) {
    alert(data?.erro || "Erro ao atualizar colaborador.");
    return;
  }

  cacheCadastros.colaboradores = null;
  cacheCadastros.motoristas = null;  // manter compatibilidade
  cacheUsuarios = null;
  await renderCadastros();
  await carregarSelectsNovoFrete();
  await renderFretes().catch(() => {});
}

async function ensureCadastrosCache() {
  if (!cacheCadastros.colaboradores) {
    cacheCadastros.colaboradores = _ordenarListaNatural(await (await apiFetch("/api/colaboradores")).json());
  }
  if (!cacheCadastros.motoristas) {
    cacheCadastros.motoristas = _ordenarListaNatural(await (await apiFetch("/api/motoristas")).json());
  }
  if (!cacheCadastros.veiculos) {
    cacheCadastros.veiculos = _ordenarListaNatural(await (await apiFetch("/api/veiculos")).json());
  }
  if (!cacheCadastros.cargas) {
    cacheCadastros.cargas = _ordenarListaNatural(await (await apiFetch("/api/cargas")).json());
  }
}

function optionsFrom(lista, selectedId, options = {}) {
  const { selectedFallbackItem = null, emptyLabel = "-" } = options;
  const sel = selectedId == null ? "" : String(selectedId);
  let itens = _ordenarListaNatural(lista);
  if (sel && selectedFallbackItem && !itens.some((item) => String(item.id) === sel)) {
    itens = _ordenarListaNatural([...itens, selectedFallbackItem]);
  }
  return `<option value="">${_escHtml(emptyLabel)}</option>` + itens
    .map((i) => {
      const v = String(i.id);
      const s = v === sel ? "selected" : "";
      const label = i.optionLabel || i.nome;
      return `<option value="${v}" ${s}>${_escHtml(label)}</option>`;
    })
    .join("");
}

function optionsFromColaboradores(funcao, selectedId) {
  const selecionado = _buscarColaboradorCadastro(selectedId);
  const labelFuncao = funcao === "motorista" ? "motorista" : "entregador";
  const fallback = selecionado && !_colaboradorTemFuncao(selecionado, funcao)
    ? { ...selecionado, optionLabel: `${selecionado.nome} (sem perfil de ${labelFuncao})` }
    : selecionado;
  return optionsFrom(_listaColaboradoresPorFuncao(funcao), selectedId, { selectedFallbackItem: fallback });
}

function _resolverEntregadorPadrao(motoristaId, entregadorId){
  const motoristaNum = motoristaId ? Number(motoristaId) : null;
  const entregadorNum = entregadorId ? Number(entregadorId) : null;
  if (entregadorNum) return entregadorNum;
  if (motoristaNum && _colaboradorTemFuncao(_buscarColaboradorCadastro(motoristaNum), "entregador")) {
    return motoristaNum;
  }
  return null;
}

function _listaColaboradoresEscalaApoio() {
  return _ordenarListaNatural((cacheCadastros.colaboradores || []).filter((item) => (
    _colaboradorTemFuncao(item, "entregador") || _colaboradorTemFuncao(item, "ajudante")
  )));
}

function optionsFromEscalaApoio(selectedId, motoristaId = null) {
  const motorista = _buscarColaboradorCadastro(motoristaId);
  const selecionado = _buscarColaboradorCadastro(selectedId);
  const podeApoiar = selecionado && (
    _colaboradorTemFuncao(selecionado, "entregador") || _colaboradorTemFuncao(selecionado, "ajudante")
  );
  const fallback = selecionado && !podeApoiar
    ? { ...selecionado, optionLabel: `${selecionado.nome} (sem perfil de apoio)` }
    : selecionado;
  const emptyLabel = motorista && _colaboradorTemFuncao(motorista, "entregador")
    ? "Vai sozinho / selecione apoio"
    : "Selecione apoio";
  return optionsFrom(_listaColaboradoresEscalaApoio(), selectedId, {
    selectedFallbackItem: fallback,
    emptyLabel,
  });
}

async function preencherSelectColaboradores(selectId, funcao, textoPadrao, selectedId = "") {
  await ensureCadastrosCache();
  const select = document.getElementById(selectId);
  if (!select) return;
  select.innerHTML = `<option value="">${_escHtml(textoPadrao)}</option>` + _listaColaboradoresPorFuncao(funcao)
    .map((item) => {
      const selected = String(item.id) === String(selectedId || "") ? "selected" : "";
      return `<option value="${item.id}" ${selected}>${_escHtml(item.nome)}</option>`;
    })
    .join("");
}

function _ordenarListaNatural(lista, getLabel = (item) => item?.nome ?? item?.label ?? item?.nome_produto ?? ""){
  const itens = Array.isArray(lista) ? [...lista] : [];
  itens.sort((a, b) => String(getLabel(a) || "").localeCompare(String(getLabel(b) || ""), "pt-BR", {
    numeric: true,
    sensitivity: "base",
  }));
  return itens;
}

async function atualizarFreteCompleto(id, payload) {
  const resp = await apiFetch(`/api/fretes/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const respClone = resp.clone();
  let data = {};
  let rawText = "";
  try {
    data = await resp.json();
  } catch {
    try {
      rawText = await respClone.text();
    } catch {}
  }
  if (!resp.ok || data?.ok === false) {
    const fallbackText = (rawText || "").toString().trim();
    throw new Error(
      data?.erro
      || (fallbackText && !/^<!doctype html/i.test(fallbackText) ? fallbackText.slice(0, 300) : "")
      || `Erro ao atualizar frete (HTTP ${resp.status || "?"}).`
    );
  }
  if (data?.frete) _setFreteLocal(data.frete);
  await atualizarDash();
  if (window.__cargasView === "escala") {
    await renderEscala().catch(() => {});
  }
  return data?.frete || null;
}

//////////////////////////////////////////////////////
// CONFIG STATUS
//////////////////////////////////////////////////////
async function verificarStatus() {
  const statusAPIEl = document.getElementById("statusAPI");
  const statusBDEl = document.getElementById("statusBD");
  const statusESXIEl = document.getElementById("statusESXI");
  const statusEsxiHostEl = document.getElementById("statusEsxiHost");
  const statusSIPEl = document.getElementById("statusSIP");
  const statusCamerasBody = document.getElementById("statusCamerasBody");

  try {
    let r = await apiFetch("/api/status");
    let s = await r.json();

    if (statusAPIEl) statusAPIEl.textContent = s.api ? "🟢 API Online" : "🔴 API Offline";
    if (statusBDEl) statusBDEl.textContent = s.database ? "🟢 BD Conectado" : "🔴 Erro Banco";

    if (statusEsxiHostEl) statusEsxiHostEl.textContent = s?.esxi?.host || "192.168.200.198";
    if (statusESXIEl) statusESXIEl.textContent = s?.esxi?.online ? "🟢 Online" : "🔴 Offline";

    statusState.sip = s?.sip || null;
    statusState.nfe = s?.nfe || null;
    if (s?.usuario_logado?.id && String(usuarioLogado?.id || "") === String(s.usuario_logado.id)) {
      usuarioLogado = { ...(usuarioLogado || {}), ...s.usuario_logado };
    }
    atualizarStatusSipSistema(statusState.sip);
    atualizarStatusCodbarSistema(s?.usuario_logado || null);
    atualizarStatusNfeSistema(statusState.nfe);
    if (statusCamerasBody) {
      const cams = Array.isArray(s?.cameras) ? s.cameras : [];
      if (!cams.length) {
        statusCamerasBody.innerHTML = `<tr><td colspan="4">Nenhuma camera cadastrada.</td></tr>`;
      } else {
        statusCamerasBody.innerHTML = cams.map((c) => `
          <tr>
            <td>${_escHtml(c.name || c.id || "-")}</td>
            <td>${_escHtml(c.mode || "-")}</td>
            <td>${_escHtml(`${c.host || "-"}:${c.port || "-"}`)}</td>
            <td>${c.online ? "🟢 Online" : "🔴 Offline"}</td>
          </tr>
        `).join("");
      }
    }
  } catch {
    if (statusAPIEl) statusAPIEl.textContent = "🔴 API Offline";
    if (statusBDEl) statusBDEl.textContent = "-";
    if (statusESXIEl) statusESXIEl.textContent = "-";
    if (statusSIPEl) statusSIPEl.textContent = "Nao foi possivel verificar.";
    statusState.sip = null;
    statusState.nfe = null;
    atualizarStatusSipSistema(null);
    atualizarStatusCodbarSistema(null);
    atualizarStatusNfeSistema(null);
    if (statusCamerasBody) statusCamerasBody.innerHTML = `<tr><td colspan="4">Nao foi possivel verificar.</td></tr>`;
  }
}

function _sipStatusClienteResumo() {
  if (sipState.currentSession) {
    const incoming = sipState.currentDirection === "incoming" && !!sipState.currentSession?.isInProgress?.();
    return incoming ? "Recebendo chamada" : "Em chamada";
  }
  if (sipState.isRegistered) return "Registrado";
  if (sipState.isConnected) return sipState.profile?.auto_register ? "Conectado" : "Conectado sem registro";
  if (sipState.initPromise) return "Conectando";
  return String(sipState.statusText || "Indisponivel").trim() || "Indisponivel";
}

function atualizarStatusSipSistema(apiSip = statusState.sip) {
  const statusEl = document.getElementById("statusSIP");
  const modeEl = document.getElementById("statusSipModo");
  const endpointEl = document.getElementById("statusSipEndpoint");
  const clientEl = document.getElementById("statusSipCliente");
  const sip = apiSip || null;

  if (modeEl) modeEl.textContent = `Modo: ${sip?.modo_label || "-"}`;
  if (endpointEl) {
    const endpoint = sip?.endpoint_host
      ? `${sip.endpoint_host}:${sip.endpoint_port || "-"}`
      : (sip?.ws_url || "-");
    endpointEl.textContent = `Endpoint: ${endpoint}`;
  }
  if (clientEl) clientEl.textContent = `Cliente web: ${_sipStatusClienteResumo()}`;

  if (!statusEl) return;
  if (!sip) {
    statusEl.textContent = "Nao foi possivel verificar.";
    return;
  }
  if (!sip.habilitado) {
    statusEl.textContent = "SIP desativado.";
    return;
  }
  if (!sip.configurado) {
    statusEl.textContent = "Configuracao SIP incompleta.";
    return;
  }
  statusEl.textContent = sip.endpoint_online
    ? "OK - porta TCP do endpoint SIP acessivel."
    : "Falha - sem conexao com o endpoint SIP.";
}

function _codbarModoLabel(modo) {
  return String(modo || "").toLowerCase() === "camera" ? "Camera/Webcam" : "Bip/Leitor";
}

function atualizarStatusCodbarSistema(apiUsuario = null) {
  const statusModo = document.getElementById("statusCodbarModo");
  const statusDispositivo = document.getElementById("statusCodbarDispositivo");
  const hintModo = document.getElementById("estoqueCodbarModoHint");
  const btnCamera = document.getElementById("estoqueAbrirCameraBtn");
  const usuario = apiUsuario || usuarioLogado || null;
  const modo = usuario?.codbar_modo || "bip";
  const temCamera = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  const label = _codbarModoLabel(modo);

  if (statusModo) statusModo.textContent = `Registro do usuario: ${label}`;
  if (statusDispositivo) {
    statusDispositivo.textContent = modo === "camera"
      ? (temCamera ? "Dispositivo: camera/webcam disponivel neste navegador." : "Dispositivo: camera/webcam indisponivel neste navegador.")
      : "Dispositivo: uso principal por bip/leitor, com camera opcional.";
  }
  if (hintModo) hintModo.textContent = `CODBAR do usuario: ${label}`;
  if (btnCamera) {
    btnCamera.textContent = modo === "camera" ? "Abrir camera/webcam" : "Abrir camera/webcam (apoio)";
    btnCamera.disabled = !temCamera;
  }
}

function _nfeModeLabel(modo){
  return String(modo || "").toLowerCase() === "certificado_digital"
    ? "Certificado digital / DF-e"
    : "Portal assistido (reCAPTCHA)";
}

function _nfeImportSourceLabel(sourceType){
  const tipo = String(sourceType || "").toLowerCase();
  if (tipo === "importar_xml") return "Importar XML / aguardando confirmacao";
  if (tipo === "xml_fabrica") return "XML fabrica / transferencia";
  if (tipo === "pdf") return "PDF (contingencia)";
  if (tipo === "dfe") return "DF-e / XML oficial";
  if (tipo === "portal") return "Portal publico / HTML resumido";
  if (tipo === "ocr") return "OCR por foto";
  if (tipo === "manual") return "Foto de apoio / digitacao manual";
  return "XML";
}

function atualizarStatusNfeSistema(apiNfe = statusState.nfe) {
  const modoEl = document.getElementById("statusNfeModo");
  const ambienteEl = document.getElementById("statusNfeAmbiente");
  const consultaEl = document.getElementById("statusNfeConsulta");
  const duplicidadeEl = document.getElementById("statusNfeDuplicidade");
  const configEl = document.getElementById("statusNfeConfig");
  const pendenciasEl = document.getElementById("statusNfePendencias");
  const nfe = apiNfe || null;

  if (modoEl) modoEl.textContent = `Modo: ${nfe ? _nfeModeLabel(nfe.modo_ativo) : "-"}`;
  if (ambienteEl) {
    ambienteEl.textContent = !nfe
      ? "Ambiente: -"
      : `Ambiente: ${String(nfe.ambiente || "-")}${nfe?.uf_autor ? ` | UF: ${nfe.uf_autor}` : ""}`;
  }
  if (consultaEl) {
    if (!nfe) {
      consultaEl.textContent = "Consulta: -";
    } else if (!nfe.habilitado) {
      consultaEl.textContent = "Consulta: integração NF-e desativada.";
    } else if (String(nfe.modo_ativo || "").toLowerCase() === "certificado_digital") {
      consultaEl.textContent = `Consulta: DF-e ${nfe.pronto_dfe ? "pronto" : "pendente"} | Ultimo NSU: ${nfe.ultimo_nsu || "0"}.`;
    } else {
      consultaEl.textContent = nfe.abrir_portal_ao_bipar
        ? "Consulta: portal oficial abre ao bipar a chave."
        : "Consulta: portal oficial sob demanda.";
    }
  }
  if (duplicidadeEl) {
    duplicidadeEl.textContent = !nfe
      ? "Duplicidade: -"
      : `Duplicidade: ${nfe.bloquear_notas_duplicadas ? "bloqueio ativo" : "bloqueio desativado"}`;
  }
  if (configEl) {
    configEl.textContent = !nfe
      ? "Config: -"
      : `Config: ${nfe.resumo_status || (nfe.configurado ? "configurada" : "pendente")}`;
  }
  if (pendenciasEl) {
    const pendencias = Array.isArray(nfe?.pendencias) ? nfe.pendencias.filter(Boolean) : [];
    pendenciasEl.textContent = !nfe
      ? "Pendencias: -"
      : `Pendencias: ${pendencias.length ? pendencias.join(" | ") : "nenhuma."}`;
  }
  _atualizarDiagnosticoConfigNfe(nfe, nfeConfigState);
}

function _atualizarDiagnosticoConfigNfe(apiNfe = statusState?.nfe || null, cfg = nfeConfigState) {
  const diagnostico = document.getElementById("nfeConfigDiagnostico");
  const distStatus = document.getElementById("nfeDistribuicaoStatus");
  if (diagnostico) {
    const pendencias = Array.isArray(apiNfe?.pendencias) ? apiNfe.pendencias.filter(Boolean) : [];
    diagnostico.textContent = !apiNfe
      ? "Diagnostico: carregue o status do sistema para validar a integracao."
      : `Diagnostico: ${apiNfe.resumo_status || "-"}${pendencias.length ? " Pendencias: " + pendencias.join(" | ") : " Pendencias: nenhuma."}`;
  }
  if (distStatus) {
    const modo = String(cfg?.modo_ativo || apiNfe?.modo_ativo || "").toLowerCase();
    if (modo === "certificado_digital") {
      const uf = cfg?.uf_autor || apiNfe?.uf_autor || "-";
      const nsu = cfg?.ultimo_nsu || apiNfe?.ultimo_nsu || "0";
      const autoManifestar = cfg?.auto_manifestar_ciencia !== false;
      const deps = Array.isArray(apiNfe?.dependencias_dfe_faltando) ? apiNfe.dependencias_dfe_faltando : [];
      const certInfo = apiNfe?.certificado_arquivo
        ? `${apiNfe.certificado_existe ? "certificado localizado" : "certificado nao encontrado"}`
        : "certificado nao informado";
      distStatus.textContent = `DF-e ${apiNfe?.pronto_dfe ? "pronto" : "pendente"}. UF autora: ${uf}. Ultimo NSU: ${nsu}. Manifestacao automatica: ${autoManifestar ? "ativa" : "desativada"}. ${certInfo}.${deps.length ? " Dependencias faltando: " + deps.join(", ") + "." : ""}`;
    } else {
      distStatus.textContent = "Fluxo DF-e desativado enquanto o modo portal assistido estiver ativo.";
    }
  }
}

function preencherConfigNfe(cfg = {}) {
  nfeConfigState = {
    habilitado: !!cfg.habilitado,
    modo_ativo: cfg.modo_ativo || "portal_assistido",
    ambiente: cfg.ambiente || "producao",
    consulta_url: cfg.consulta_url || "https://www.nfe.fazenda.gov.br/portal/consultaRecaptcha.aspx?tipoConsulta=completa&tipoConteudo=XbSeqxE8pl8=",
    abrir_portal_ao_bipar: cfg.abrir_portal_ao_bipar !== false,
    bloquear_notas_duplicadas: cfg.bloquear_notas_duplicadas !== false,
    auto_manifestar_ciencia: cfg.auto_manifestar_ciencia !== false,
    destinatario_cnpj: cfg.destinatario_cnpj || "",
    uf_autor: (cfg.uf_autor || "").toUpperCase(),
    certificado_arquivo: cfg.certificado_arquivo || "",
    certificado_senha: cfg.certificado_senha || "",
    ultimo_nsu: cfg.ultimo_nsu || "",
    azure_docint_habilitado: !!cfg.azure_docint_habilitado,
    azure_docint_endpoint: cfg.azure_docint_endpoint || "",
    azure_docint_key: cfg.azure_docint_key || "",
    azure_docint_key_configurada: !!cfg.azure_docint_key_configurada,
    azure_docint_model_id: cfg.azure_docint_model_id || "prebuilt-invoice",
    azure_docint_api_version: cfg.azure_docint_api_version || "2024-11-30",
    updated_at: cfg.updated_at || null,
  };

  const resumo = document.getElementById("nfeConfigResumo");
  const campos = {
    habilitado: document.getElementById("nfeConfigHabilitado"),
    modo_ativo: document.getElementById("nfeConfigModoAtivo"),
    ambiente: document.getElementById("nfeConfigAmbiente"),
    consulta_url: document.getElementById("nfeConfigConsultaUrl"),
    abrir_portal_ao_bipar: document.getElementById("nfeConfigAbrirPortalAoBipar"),
    bloquear_notas_duplicadas: document.getElementById("nfeConfigBloquearDuplicadas"),
    auto_manifestar_ciencia: document.getElementById("nfeConfigAutoManifestarCiencia"),
    destinatario_cnpj: document.getElementById("nfeConfigDestinatarioCnpj"),
    uf_autor: document.getElementById("nfeConfigUfAutor"),
    certificado_arquivo: document.getElementById("nfeConfigCertificadoArquivo"),
    certificado_senha: document.getElementById("nfeConfigCertificadoSenha"),
    ultimo_nsu: document.getElementById("nfeConfigUltimoNsu"),
    azure_docint_habilitado: document.getElementById("nfeConfigAzureDocintHabilitado"),
    azure_docint_endpoint: document.getElementById("nfeConfigAzureDocintEndpoint"),
    azure_docint_key: document.getElementById("nfeConfigAzureDocintKey"),
    azure_docint_model_id: document.getElementById("nfeConfigAzureDocintModelId"),
    azure_docint_api_version: document.getElementById("nfeConfigAzureDocintApiVersion"),
  };
  const azureStatus = document.getElementById("nfeAzureDocintStatus");

  if (campos.habilitado) campos.habilitado.checked = !!nfeConfigState.habilitado;
  if (campos.modo_ativo) campos.modo_ativo.value = nfeConfigState.modo_ativo;
  if (campos.ambiente) campos.ambiente.value = nfeConfigState.ambiente;
  if (campos.consulta_url) campos.consulta_url.value = nfeConfigState.consulta_url;
  if (campos.abrir_portal_ao_bipar) campos.abrir_portal_ao_bipar.checked = !!nfeConfigState.abrir_portal_ao_bipar;
  if (campos.bloquear_notas_duplicadas) campos.bloquear_notas_duplicadas.checked = !!nfeConfigState.bloquear_notas_duplicadas;
  if (campos.auto_manifestar_ciencia) campos.auto_manifestar_ciencia.checked = !!nfeConfigState.auto_manifestar_ciencia;
  if (campos.destinatario_cnpj) campos.destinatario_cnpj.value = nfeConfigState.destinatario_cnpj;
  if (campos.uf_autor) campos.uf_autor.value = nfeConfigState.uf_autor;
  if (campos.certificado_arquivo) campos.certificado_arquivo.value = nfeConfigState.certificado_arquivo;
  if (campos.certificado_senha) campos.certificado_senha.value = nfeConfigState.certificado_senha;
  if (campos.ultimo_nsu) campos.ultimo_nsu.value = nfeConfigState.ultimo_nsu;
  if (campos.azure_docint_habilitado) campos.azure_docint_habilitado.checked = !!nfeConfigState.azure_docint_habilitado;
  if (campos.azure_docint_endpoint) campos.azure_docint_endpoint.value = nfeConfigState.azure_docint_endpoint;
  if (campos.azure_docint_key) campos.azure_docint_key.value = nfeConfigState.azure_docint_key;
  if (campos.azure_docint_model_id) campos.azure_docint_model_id.value = nfeConfigState.azure_docint_model_id;
  if (campos.azure_docint_api_version) campos.azure_docint_api_version.value = nfeConfigState.azure_docint_api_version;

  if (resumo) {
    resumo.textContent = nfeConfigState.updated_at
      ? `Ultima atualizacao: ${_fmtDateBr(nfeConfigState.updated_at)} | Modo: ${_nfeModeLabel(nfeConfigState.modo_ativo)} | Ambiente: ${nfeConfigState.ambiente}`
      : `Configuracao pronta para preenchimento. Modo: ${_nfeModeLabel(nfeConfigState.modo_ativo)} | Ambiente: ${nfeConfigState.ambiente}`;
  }
  if (azureStatus) {
    azureStatus.textContent = nfeConfigState.azure_docint_habilitado
      ? `Azure ativo. Modelo: ${nfeConfigState.azure_docint_model_id}. Endpoint: ${nfeConfigState.azure_docint_endpoint || "-"}. Chave ${nfeConfigState.azure_docint_key_configurada ? "configurada" : "nao informada"}.`
      : "Azure Document Intelligence desativado.";
  }

  _atualizarDiagnosticoConfigNfe(statusState?.nfe || null, nfeConfigState);

  atualizarStatusNfeSistema(statusState?.nfe || {
    habilitado: nfeConfigState.habilitado,
    modo_ativo: nfeConfigState.modo_ativo,
    ambiente: nfeConfigState.ambiente,
    bloquear_notas_duplicadas: nfeConfigState.bloquear_notas_duplicadas,
    abrir_portal_ao_bipar: nfeConfigState.abrir_portal_ao_bipar,
    uf_autor: nfeConfigState.uf_autor,
    ultimo_nsu: nfeConfigState.ultimo_nsu,
  });
}

async function carregarConfigNfe(silent = false) {
  const resumo = document.getElementById("nfeConfigResumo");
  if (!silent && resumo) resumo.textContent = "Carregando configuracao NF-e...";
  const resp = await apiFetch("/api/nfe/config");
  if (!resp.ok) {
    if (!silent && resumo) resumo.textContent = "Erro ao carregar configuracao NF-e.";
    throw new Error("Erro ao carregar configuracao NF-e.");
  }
  const cfg = await resp.json().catch(() => ({}));
  preencherConfigNfe(cfg);
  return cfg;
}

async function salvarConfigNfe() {
  const payload = {
    habilitado: !!document.getElementById("nfeConfigHabilitado")?.checked,
    modo_ativo: document.getElementById("nfeConfigModoAtivo")?.value || "portal_assistido",
    ambiente: document.getElementById("nfeConfigAmbiente")?.value || "producao",
    consulta_url: (document.getElementById("nfeConfigConsultaUrl")?.value || "").trim(),
    abrir_portal_ao_bipar: !!document.getElementById("nfeConfigAbrirPortalAoBipar")?.checked,
    bloquear_notas_duplicadas: !!document.getElementById("nfeConfigBloquearDuplicadas")?.checked,
    auto_manifestar_ciencia: !!document.getElementById("nfeConfigAutoManifestarCiencia")?.checked,
    destinatario_cnpj: _digitsOnly(document.getElementById("nfeConfigDestinatarioCnpj")?.value || ""),
    uf_autor: (document.getElementById("nfeConfigUfAutor")?.value || "").trim().toUpperCase(),
    certificado_arquivo: (document.getElementById("nfeConfigCertificadoArquivo")?.value || "").trim(),
    certificado_senha: document.getElementById("nfeConfigCertificadoSenha")?.value || "",
    ultimo_nsu: _digitsOnly(document.getElementById("nfeConfigUltimoNsu")?.value || ""),
    azure_docint_habilitado: !!document.getElementById("nfeConfigAzureDocintHabilitado")?.checked,
    azure_docint_endpoint: (document.getElementById("nfeConfigAzureDocintEndpoint")?.value || "").trim(),
    azure_docint_key: document.getElementById("nfeConfigAzureDocintKey")?.value || "",
    azure_docint_model_id: (document.getElementById("nfeConfigAzureDocintModelId")?.value || "").trim() || "prebuilt-invoice",
    azure_docint_api_version: (document.getElementById("nfeConfigAzureDocintApiVersion")?.value || "").trim() || "2024-11-30",
  };

  const resp = await apiFetch("/api/nfe/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    alert(data?.erro || "Erro ao salvar configuracao NF-e.");
    return;
  }

  preencherConfigNfe(data?.config || payload);
  await verificarStatus().catch(() => {});
}

async function sincronizarNfeDistribuicao() {
  const statusEl = document.getElementById("nfeDistribuicaoStatus");
  if (statusEl) statusEl.textContent = "Sincronizando DF-e via NFeDistribuicaoDFe...";

  const resp = await apiFetch("/api/nfe/df-e/sincronizar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (statusEl) statusEl.textContent = data?.erro || "Falha ao sincronizar DF-e.";
    alert(data?.erro || "Falha ao sincronizar DF-e.");
    return;
  }

  if (data?.config) preencherConfigNfe(data.config);
  const qtd = Array.isArray(data?.documentos) ? data.documentos.length : 0;
  const manifestos = Array.isArray(data?.manifestacoes) ? data.manifestacoes.length : 0;
  if (statusEl) {
    statusEl.textContent = `Sincronizacao concluida. cStat ${data?.c_stat || "-"} - ${data?.x_motivo || "-"}. Documentos: ${qtd}. Manifestacoes disparadas: ${manifestos}. Ultimo NSU: ${data?.ultimo_nsu || nfeConfigState?.ultimo_nsu || "0"}.`;
  }
}

function abrirPortalOficialNfeConfig(contexto = "") {
  abrirPortalOficialNfeConfigComChave("", contexto || "");
}

function _montarUrlConsultaPortalNfe(baseUrl, chave = "") {
  const fallback = "https://www.nfe.fazenda.gov.br/portal/consultaRecaptcha.aspx?tipoConsulta=completa&tipoConteudo=XbSeqxE8pl8=";
  const raw = String(baseUrl || "").trim() || fallback;
  const chaveLimpa = _digitsOnly(chave || "");
  if (chaveLimpa.length !== 44) return raw;
  try {
    const url = new URL(raw, window.location.origin);
    url.searchParams.set("nfe", chaveLimpa);
    return url.toString();
  } catch {
    const separador = raw.includes("?") ? "&" : "?";
    return `${raw}${separador}nfe=${encodeURIComponent(chaveLimpa)}`;
  }
}

function abrirPortalOficialNfeConfigComChave(chave = "", contexto = "") {
  const campoChave = contexto === "estoque"
    ? document.getElementById("estoqueChaveAcesso")
    : null;
  const chaveLimpa = _digitsOnly(chave || campoChave?.value || "");
  const baseUrl = (nfeConfigState?.consulta_url || document.getElementById("nfeConfigConsultaUrl")?.value || "").trim()
    || "https://www.nfe.fazenda.gov.br/portal/consultaRecaptcha.aspx?tipoConsulta=completa&tipoConteudo=XbSeqxE8pl8=";
  const url = _montarUrlConsultaPortalNfe(baseUrl, chaveLimpa);
  window.open(url, "_blank");
  if (contexto === "estoque") {
    const status = document.getElementById("estoqueNfeImportStatus");
    if (status) {
      status.textContent = chaveLimpa.length === 44
        ? `Site da Receita aberto com a chave ${chaveLimpa} preparada na URL. Resolva o reCAPTCHA e use o bookmarklet do portal para devolver os dados automaticamente.`
        : "Site da Receita aberto. Informe ou bipa a chave de acesso para deixar a consulta preparada na URL.";
    }
  }
}

async function _abrirConsultaPortalNfeSeConfigurado(chave, contexto = "") {
  const chaveLimpa = _digitsOnly(chave || "");
  if (chaveLimpa.length !== 44) return;

  let cfg = nfeConfigState;
  if (!cfg) {
    try {
      cfg = await carregarConfigNfe(true);
    } catch {
      cfg = null;
    }
  }
  if (!cfg?.habilitado) return;
  if (String(cfg.modo_ativo || "").toLowerCase() !== "portal_assistido") return;
  if (!cfg.abrir_portal_ao_bipar) return;

  const now = Date.now();
  if (
    nfePortalState.lastKey === chaveLimpa
    && nfePortalState.lastMode === "portal_assistido"
    && nfePortalState.lastContext === contexto
    && (now - nfePortalState.lastAt) < 4000
  ) return;
  nfePortalState = { lastKey: chaveLimpa, lastAt: now, lastMode: "portal_assistido", lastContext: contexto };

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(chaveLimpa);
    }
  } catch {}

  const url = _montarUrlConsultaPortalNfe(
    (cfg.consulta_url || "").trim()
      || "https://www.nfe.fazenda.gov.br/portal/consultaRecaptcha.aspx?tipoConsulta=completa&tipoConteudo=XbSeqxE8pl8=",
    chaveLimpa
  );
  window.open(url, "_blank");

  const statusEstoque = document.getElementById("estoqueNfeImportStatus");
  if (contexto === "estoque" && statusEstoque) {
    statusEstoque.textContent = `Portal oficial da NF-e aberto com a chave ${chaveLimpa} na URL. Resolva o reCAPTCHA e depois use o bookmarklet do portal para devolver os dados automaticamente.`;
  }
}

async function _processarChaveNfeLida(chave, contexto = "estoque") {
  const chaveLimpa = _digitsOnly(chave || "");
  if (chaveLimpa.length !== 44) return;
  const statusEstoque = contexto === "estoque"
    ? document.getElementById("estoqueNfeImportStatus")
    : null;

  let cfg = nfeConfigState;
  if (!cfg) {
    try {
      cfg = await carregarConfigNfe(true);
    } catch {
      cfg = null;
    }
  }
  if (!cfg?.habilitado) {
    if (statusEstoque) statusEstoque.textContent = "A integracao NF-e esta desativada em Config > NF-e.";
    return;
  }

  const modo = String(cfg.modo_ativo || "").toLowerCase();
  const now = Date.now();
  if (
    nfePortalState.lastKey === chaveLimpa
    && nfePortalState.lastMode === modo
    && nfePortalState.lastContext === contexto
    && (now - nfePortalState.lastAt) < 4000
  ) return;
  nfePortalState = { lastKey: chaveLimpa, lastAt: now, lastMode: modo, lastContext: contexto };

  if (modo === "certificado_digital") {
    if (contexto === "estoque") {
      if (statusEstoque) {
        statusEstoque.textContent = `Chave ${chaveLimpa} lida. Para evitar consumo indevido e respeitar o limite da SEFAZ, clique em "Buscar NF-e pela chave (DF-e)" somente quando quiser consultar.`;
      }
      return;
    }
    return;
  }

  await _abrirConsultaPortalNfeSeConfigurado(chaveLimpa, contexto);
}

function normalizarChaveNfeCampo(inputEl, abrirPortal = false) {
  if (!inputEl) return "";
  const digits = _digitsOnly(inputEl.value || "");
  inputEl.value = digits;
  if (abrirPortal && digits.length === 44) {
    const contexto = String(inputEl.id || "").startsWith("abast_") ? "abastecimento" : "estoque";
    _processarChaveNfeLida(digits, contexto).catch(() => {});
  }
  return digits;
}

function _resumoLimiteConsultasDfe(info){
  if (!info || typeof info !== "object") return "";
  const usadas = Number(info.usadas || 0);
  const limite = Number(info.limite || 20);
  const restantes = Number(info.restantes || Math.max(limite - usadas, 0));
  if (Number(info.bloqueado || false)) {
    const aguardar = Number(info.aguardar_segundos || 0);
    const minutos = aguardar > 0 ? Math.max(1, Math.ceil(aguardar / 60)) : 60;
    return ` Limite DF-e: ${usadas}/${limite} usadas na ultima hora. Aguarde cerca de ${minutos} min.`;
  }
  return ` Limite DF-e: ${usadas}/${limite} usadas, ${restantes} restante(s) na ultima hora.`;
}

async function carregarLogsExclusoes() {
  const body = document.getElementById("logsExclusoesBody");
  if (!body) return;

  const r = await apiFetch("/api/logs_exclusoes?limit=400");
  if (!r.ok) {
    body.innerHTML = `<tr><td colspan="5">Erro ao carregar logs.</td></tr>`;
    return;
  }

  const logs = await r.json();
  if (!Array.isArray(logs) || !logs.length) {
    body.innerHTML = `<tr><td colspan="5">Nenhuma exclusao registrada.</td></tr>`;
    return;
  }

  body.innerHTML = logs.map((l) => `
    <tr>
      <td>${_escHtml(_fmtDateBr(l.data_evento))}</td>
      <td>${_escHtml(l.usuario || "-")}</td>
      <td>${_escHtml(l.entidade || "-")}</td>
      <td>${_escHtml(String(l.item_id ?? "-"))}</td>
      <td>${_escHtml(l.descricao || "-")}</td>
    </tr>
  `).join("");
}

//////////////////////////////////////////////////////
// DASHBOARD
//////////////////////////////////////////////////////
async function atualizarDash() {
  let r = await apiFetch("/api/dashboard");
  let d = await r.json();

  d1.textContent = d["chegada"] || 0;
  d2.textContent = d["descarregado"] || 0;
  d3.textContent = d["liberado"] || 0;
  d4.textContent = d["carregando"] || 0;
  d5.textContent = d["carregado"] || 0;
  d6.textContent = d["entregando"] || 0;
  d7.textContent = d["retornando"] || 0;
  d8.textContent = d["paradoVasio"] || 0;
  d9.textContent = d["paradoCarregado"] || 0;
}

//////////////////////////////////////////////////////
// TABS (MENU)
//////////////////////////////////////////////////////


// =====================================================
// DASHBOARD SUBMENU + VIEWS
// =====================================================
function closeOpenSubmenus(exceptMenuItem = null){
  document.querySelectorAll(".menu-item.has-submenu.open").forEach((item) => {
    if (item !== exceptMenuItem) item.classList.remove("open");
  });
}

function toggleExclusiveSubmenu(ev, onDesktopOpen){
  if (!ev) return;
  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (!isMobile) {
    closeOpenSubmenus();
    if (typeof onDesktopOpen === "function") onDesktopOpen();
    return;
  }

  ev.preventDefault();
  ev.stopPropagation();
  const mi = ev.currentTarget;
  if (!mi || !mi.classList.contains("has-submenu")) return;

  const shouldOpen = !mi.classList.contains("open");
  closeOpenSubmenus(mi);
  mi.classList.toggle("open", shouldOpen);
}

function toggleDashboardSubmenu(ev){
  // No desktop, hover resolve. No mobile, toca para abrir/fechar.
  toggleExclusiveSubmenu(ev, () => openDashboardView(null, "resumo"));
}

function openDashboardView(ev, view){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  // ativa tab dashboard
  const dashMenu = document.querySelector('.menu-item.has-submenu[data-tab="dashboard"]');
  window.__dashboardSubmenuNavigation = true;
  showTab("dashboard", dashMenu);

  // marca submenu ativo
  document.querySelectorAll("#submenuDashboard .submenu-item").forEach(x=>x.classList.remove("active"));
  const targetMap = { resumo: 0, frota: 1, estoque: 2, bonificacoes: 3, variacao_preco: 4, mix_embalagens: 5, grupos_embalagem: 5, vendas: 3 };
  const target = targetMap[view] ?? 0;
  const items = document.querySelectorAll("#submenuDashboard .submenu-item");
  if (items && items[target]) items[target].classList.add("active");

  setDashboardView(view);

  // fecha submenu no mobile
  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && dashMenu) dashMenu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
  window.__dashboardSubmenuNavigation = false;
}

function setDashboardView(view){
  const raw = String(view || "resumo").toLowerCase();
  const target = _dashboardVendasIsView(raw)
    ? _dashboardVendasNormalizeView(raw === "vendas" ? (window.__dashVendasView || dashboardVendasPainelState.view || "bonificacoes") : raw)
    : ["resumo", "frota", "estoque"].includes(raw) ? raw : "resumo";
  const isVendasView = _dashboardVendasIsView(target);
  window.__dashView = target;
  const vResumo = document.getElementById("dashViewResumo");
  const vFrota = document.getElementById("dashViewFrota");
  const vEstoque = document.getElementById("dashViewEstoque");
  const vVendas = document.getElementById("dashViewVendas");
  if (vResumo) vResumo.classList.toggle("hidden", target !== "resumo");
  if (vFrota) vFrota.classList.toggle("hidden", target !== "frota");
  if (vEstoque) vEstoque.classList.toggle("hidden", target !== "estoque");
  if (vVendas) vVendas.classList.toggle("hidden", !isVendasView);

  if (target === "frota") {
    renderDashboardFrota().catch(e=>console.warn("dash frota erro:", e));
  } else if (target === "estoque") {
    renderDashboardEstoque().catch(e=>console.warn("dash estoque erro:", e));
  } else if (isVendasView) {
    setDashboardVendasView(target);
    recarregarDashboardVendaAtual().catch(e=>console.warn("dash vendas erro:", e));
  } else {
    atualizarDash().catch(()=>{});
  }
}

function _dashboardVendasIsView(view){
  return ["bonificacoes", "variacao_preco", "mix_embalagens", "grupos_embalagem", "vendas"].includes(String(view || "").toLowerCase());
}

function _dashboardVendasNormalizeView(view){
  const valor = String(view || "bonificacoes").toLowerCase();
  if (valor === "variacao_preco") return "variacao_preco";
  if (valor === "mix_embalagens" || valor === "grupos_embalagem") return "mix_embalagens";
  return "bonificacoes";
}

function setDashboardVendasView(view){
  const target = _dashboardVendasNormalizeView(view);
  dashboardVendasPainelState.view = target;
  window.__dashVendasView = target;

  const tituloEl = document.getElementById("dashVendasTitulo");
  if (tituloEl) {
    tituloEl.textContent = target === "variacao_preco"
      ? "Dashboard - Variação de Preço"
      : target === "mix_embalagens"
      ? "Dashboard - Grupos Embalagem"
      : "Dashboard - Bonificações";
  }

  const pBon = document.getElementById("dashVendasPanelBonificacoes");
  const pVar = document.getElementById("dashVendasPanelVariacao");
  const pMix = document.getElementById("dashVendasPanelMix");
  if (pBon) pBon.classList.toggle("hidden", target !== "bonificacoes");
  if (pVar) pVar.classList.toggle("hidden", target !== "variacao_preco");
  if (pMix) pMix.classList.toggle("hidden", target !== "mix_embalagens");
}

function _dashboardVendasAtualizarInfo(payload = {}) {
  const infoEl = document.getElementById("dashVendasArquivoInfo");
  if (!infoEl) return;
  const partes = [
    `Arquivo: ${payload?.arquivo?.nome || "Base atual"}`,
    `Atualizado em: ${payload?.arquivo?.atualizado_em || "-"}`,
    `Mês: ${_vendasMesLabelTexto(payload?.mes_atual || payload?.filtros?.mes || "")}`,
  ];
  infoEl.textContent = partes.join(" | ");
}

function renderDashboardBonificacoes(payload = {}) {
  dashboardVendasPainelState.payload = payload || {};
  dashboardVendasPainelState.cacheId = _as_str(payload?.cache?.id);
  _dashboardVendasAtualizarInfo(payload);
  _dashboardVendasRenderBonificacoes(payload);
}

function renderDashboardVariacao(payload = {}) {
  dashboardVendasPainelState.payload = payload || {};
  dashboardVendasPainelState.cacheId = _as_str(payload?.cache?.id);
  _dashboardVendasAtualizarInfo(payload);
  _dashboardVendasRenderVariacao(payload);
}

function renderDashboardMixEmbalagens(payload = {}) {
  dashboardVendasPainelState.payload = payload || {};
  dashboardVendasPainelState.cacheId = _as_str(payload?.cache?.id);
  _dashboardVendasAtualizarInfo(payload);
  _dashboardVendasRenderMixEmbalagens(payload);
}

async function carregarDashboardBonificacoes(force = false) {
  const infoEl = document.getElementById("dashVendasArquivoInfo");
  if (infoEl) infoEl.textContent = "Carregando dashboard de bonificações...";
  const resp = await apiFetch("/api/vendas/relatorio?tipo_relatorio=bonificacoes");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const erro = data?.erro || "Falha ao carregar dashboard de bonificações.";
    if (infoEl) infoEl.textContent = erro;
    if (resp.status !== 409) alert(erro);
    return;
  }
  renderDashboardBonificacoes(data || {});
}

async function carregarDashboardVariacao(force = false) {
  const infoEl = document.getElementById("dashVendasArquivoInfo");
  if (infoEl) infoEl.textContent = "Carregando dashboard de variação de preço...";
  const resp = await apiFetch("/api/vendas/relatorio?tipo_relatorio=variacao_preco");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const erro = data?.erro || "Falha ao carregar dashboard de variação de preço.";
    if (infoEl) infoEl.textContent = erro;
    if (resp.status !== 409) alert(erro);
    return;
  }
  renderDashboardVariacao(data || {});
}

async function carregarDashboardMixEmbalagens(force = false) {
  const infoEl = document.getElementById("dashVendasArquivoInfo");
  if (infoEl) infoEl.textContent = "Carregando dashboard de grupos embalagem...";
  const resp = await apiFetch("/api/vendas/relatorio?tipo_relatorio=grupos_embalagem");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const erro = data?.erro || "Falha ao carregar dashboard de grupos embalagem.";
    if (infoEl) infoEl.textContent = erro;
    if (resp.status !== 409) alert(erro);
    return;
  }
  renderDashboardMixEmbalagens(data || {});
}

async function recarregarDashboardVendaAtual(force = false) {
  const target = _dashboardVendasNormalizeView(window.__dashView || dashboardVendasPainelState.view || window.__dashVendasView || "bonificacoes");
  setDashboardVendasView(target);
  if (target === "variacao_preco") {
    await carregarDashboardVariacao(force);
    return;
  }
  if (target === "mix_embalagens") {
    await carregarDashboardMixEmbalagens(force);
    return;
  }
  await carregarDashboardBonificacoes(force);
}

function _dashboardVendasCelulaResumo(valorAtual = 0, valorAnterior = null) {
  if (valorAnterior === null || valorAnterior === undefined) {
    return "vendas-dashboard-cell vendas-dashboard-cell-neutral";
  }
  if (valorAtual > valorAnterior) return "vendas-dashboard-cell vendas-dashboard-cell-up";
  if (valorAtual < valorAnterior) return "vendas-dashboard-cell vendas-dashboard-cell-down";
  return "vendas-dashboard-cell vendas-dashboard-cell-equal";
}

function _dashboardVendasRenderLinhaTabela(valorAtual = 0, valorAnterior = null) {
  const delta = valorAnterior === null || valorAnterior === undefined ? null : (valorAtual - valorAnterior);
  const pct = valorAnterior && valorAnterior !== 0 ? (delta / Math.abs(valorAnterior)) * 100.0 : 0.0;
  const classe = _dashboardVendasCelulaResumo(valorAtual, valorAnterior);
  return `
    <td class="${classe}">
      <strong>${_escHtml(_fmtMoneyVendas(valorAtual))}</strong>
      ${delta === null ? "" : `<span>${_escHtml(`${delta >= 0 ? "+" : ""}${_fmtNumVendas(pct, 1)}%`)}</span>`}
    </td>
  `;
}

function _dashboardVendasRenderBonificacoes(payload = {}) {
  const resumo = payload?.resumo_geral || {};
  const grupos = Array.isArray(payload?.resumo_grupos) ? payload.resumo_grupos : [];
  const vendedores = Array.isArray(payload?.vendedores) ? payload.vendedores : [];
  const cardsEl = document.getElementById("dashVendasBonifCards");
  if (cardsEl) {
    cardsEl.innerHTML = _renderCardsVendasResumo([
      ["Mês", _vendasMesLabelTexto(payload?.mes_atual || "")],
      ["Itens", _fmtNumVendas(resumo.itens)],
      ["Vendedores", _fmtNumVendas(resumo.vendedores)],
      ["PDV", _fmtNumVendas(resumo.clientes)],
      ["Bonif.", _fmtMoneyVendas(resumo.bonificacao)],
      ["% Bonif.", `${_fmtNumVendas(resumo.percentual_bonificacao || resumo.percentual || 0, 2)}%`],
      ["Média %", `${_fmtNumVendas(resumo.media_percentual_bonificacao || 0, 2)}%`],
      ["Líquido", _fmtMoneyVendas(resumo.valor_liquido)],
    ]);
  }
  const gruposEl = document.getElementById("dashVendasBonifGrupos");
  if (gruposEl) {
    gruposEl.innerHTML = _vendasRenderGrupoBonificacoes(grupos);
  }
  const bodyEl = document.getElementById("dashVendasBonifBody");
  if (bodyEl) {
    bodyEl.innerHTML = vendedores.length ? vendedores.slice(0, 12).map((item) => `
      <tr>
        <td>${_escHtml(item.codigo || "-")}</td>
        <td>${_escHtml(item.nome || item.vendedor || "-")}</td>
        <td>${_escHtml(_fmtNumVendas(item.itens))}</td>
        <td>${_escHtml(_fmtNumVendas(item.clientes))}</td>
        <td>${_escHtml(_fmtNumVendas(item.notas))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.bonificacao))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_liquido || item.total_valor_liquido || 0))}</td>
        <td>${_escHtml(`${_fmtNumVendas(item.percentual_bonificacao || item.percentual || 0, 2)}%`)}</td>
      </tr>
    `).join("") : '<tr><td colspan="8">Nenhum dado de bonificações para o período.</td></tr>';
  }
}

function _dashboardVendasRenderVariacao(payload = {}) {
  const resumo = payload?.resumo_geral || {};
  const grupos = Array.isArray(payload?.resumo_grupos) ? payload.resumo_grupos : [];
  const variacoes = Array.isArray(payload?.variacoes) ? payload.variacoes : [];
  const cardsEl = document.getElementById("dashVendasVarCards");
  if (cardsEl) {
    cardsEl.innerHTML = _vendasResumoVariacaoCards(resumo, payload);
  }
  const gruposEl = document.getElementById("dashVendasVarGrupos");
  if (gruposEl) {
    gruposEl.innerHTML = _vendasRenderGrupoVariacao(grupos);
  }
  const bodyEl = document.getElementById("dashVendasVarBody");
  if (bodyEl) {
    bodyEl.innerHTML = variacoes.length ? _vendasRenderVariacoesTabela(variacoes) : '<tr><td colspan="12">Nenhuma variação de preço encontrada para o período selecionado.</td></tr>';
  }
}

function _dashboardVendasRenderMixEmbalagens(payload = {}) {
  const resumo = payload?.resumo_geral || {};
  const faixas = Array.isArray(payload?.resumo_faixas) ? payload.resumo_faixas : [];
  const clientes = Array.isArray(payload?.clientes) ? payload.clientes : [];
  const cardsEl = document.getElementById("dashVendasMixCards");
  if (cardsEl) {
    cardsEl.innerHTML = _renderCardsVendasResumo(_vendasResumoMixEmbalagensCards(resumo, payload));
  }
  const faixasBody = document.getElementById("dashVendasMixFaixasBody");
  if (faixasBody) {
    faixasBody.innerHTML = faixas.length ? faixas.map((item) => `
      <tr>
        <td>${_escHtml(item.faixa || "-")}</td>
        <td>${_escHtml(_fmtNumVendas(item.pdvs))}</td>
        <td>${_escHtml(`${_fmtNumVendas(item.percentual || 0, 2)}%`)}</td>
      </tr>
    `).join("") : '<tr><td colspan="3">Nenhum PDV encontrado no período.</td></tr>';
  }
  const bodyEl = document.getElementById("dashVendasMixBody");
  if (bodyEl) {
    bodyEl.innerHTML = clientes.length ? clientes.slice(0, 15).map((item) => `
      <tr>
        <td>${_escHtml(item.cliente || "-")}</td>
        <td>${_escHtml(item.cidade || "-")}</td>
        <td>${_escHtml(item.vendedor || item.vendedores_lista || "-")}</td>
        <td>${_escHtml(_fmtNumVendas(item.qtd_grupos))}</td>
        <td>${_escHtml(item.faixa_grupos || "-")}</td>
        <td>${_escHtml(item.grupos_lista || "-")}</td>
      </tr>
    `).join("") : '<tr><td colspan="6">Nenhum PDV encontrado para o período.</td></tr>';
  }
}

function toggleCargasSubmenu(ev){
  toggleExclusiveSubmenu(ev, () => openCargasView(null, window.__cargasView || "cadastro"));
}

function openCargasView(ev, view){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const menu = document.querySelector('.menu-item.has-submenu[data-tab="cargas"]');
  window.__cargasView = view;
  showTab("cargas", menu);

  document.querySelectorAll("#submenuCargas .submenu-item").forEach((x) => x.classList.remove("active"));
  const map = { cadastro: 0, escala: 1 };
  const target = map[view] ?? 0;
  const items = document.querySelectorAll("#submenuCargas .submenu-item");
  if (items && items[target]) items[target].classList.add("active");

  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && menu) menu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
}

function setCargasView(view){
  window.__cargasView = view;
  const views = {
    cadastro: document.getElementById("cargasViewCadastro"),
    escala: document.getElementById("cargasViewEscala"),
  };
  Object.entries(views).forEach(([key, el]) => {
    if (el) el.classList.toggle("hidden", key !== view);
  });
  document.querySelectorAll("#submenuCargas .submenu-item").forEach((item) => item.classList.remove("active"));
  const map = { cadastro: 0, escala: 1 };
  const items = document.querySelectorAll("#submenuCargas .submenu-item");
  const target = map[view] ?? 0;
  if (items && items[target]) items[target].classList.add("active");
  if (view === "escala") {
    renderEscala().catch((e) => console.warn("escala erro:", e));
  }
}

function toggleCadastrosSubmenu(ev){
  toggleExclusiveSubmenu(ev, () => openCadastrosView(null, window.__cadastrosView || "colaboradores"));
}

function openCadastrosView(ev, view){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const menu = document.querySelector('.menu-item.has-submenu[data-tab="cadastros"]');
  const normalizedView = view === "motoristas" || view === "conferentes" || view === "usuarios" ? "colaboradores" : view;
  window.__cadastrosView = normalizedView;
  showTab("cadastros", menu);

  document.querySelectorAll("#submenuCadastros .submenu-item").forEach((x) => x.classList.remove("active"));
  const map = { colaboradores: 0, veiculos: 1, comissao: 2 };
  const target = map[normalizedView] ?? 0;
  const items = document.querySelectorAll("#submenuCadastros .submenu-item");
  if (items && items[target]) items[target].classList.add("active");

  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && menu) menu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
}

function setCadastrosView(view){
  const normalizedView = view === "motoristas" || view === "conferentes" || view === "usuarios" ? "colaboradores" : view;
  window.__cadastrosView = normalizedView;
  const views = {
    colaboradores: document.getElementById("cadastrosViewMotoristas"),
    veiculos: document.getElementById("cadastrosViewVeiculos"),
    comissao: document.getElementById("cadastrosViewComissao"),
  };
  Object.entries(views).forEach(([key, el]) => {
    if (el) el.classList.toggle("hidden", key !== normalizedView);
  });
  document.querySelectorAll("#submenuCadastros .submenu-item").forEach((item) => item.classList.remove("active"));
  const map = { colaboradores: 0, veiculos: 1, comissao: 2 };
  const items = document.querySelectorAll("#submenuCadastros .submenu-item");
  const target = map[normalizedView] ?? 0;
  if (items && items[target]) items[target].classList.add("active");
  if (normalizedView === "comissao") {
    carregarComissaoCadastros().catch(() => {});
  }
}

function toggleGestaoFrotaSubmenu(ev){
  toggleExclusiveSubmenu(ev, () => openGestaoFrotaView(null, "registrar"));
}

function openGestaoFrotaView(ev, view){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const menu = document.querySelector('.menu-item.has-submenu[data-tab="gestaofrota"]');
  window.__gestaoView = view;
  showTab("gestaofrota", menu);

  document.querySelectorAll("#submenuGestaoFrota .submenu-item").forEach(x=>x.classList.remove("active"));
  const map = { registrar: 0, lista: 1, relatorios: 2 };
  const target = map[view] ?? 0;
  const items = document.querySelectorAll("#submenuGestaoFrota .submenu-item");
  if (items && items[target]) items[target].classList.add("active");

  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && menu) menu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
}

function setGestaoFrotaView(view){
  window.__gestaoView = view;
  const vRegistrar = document.getElementById("gestaoViewRegistrar");
  const vLista = document.getElementById("gestaoViewLista");
  const vRelatorios = document.getElementById("gestaoViewRelatorios");

  if (vRegistrar) vRegistrar.classList.toggle("hidden", view !== "registrar");
  if (vLista) vLista.classList.toggle("hidden", view !== "lista");
  if (vRelatorios) vRelatorios.classList.toggle("hidden", view !== "relatorios");
  if (view === "registrar") {
    setGestaoRegistroView(window.__gestaoRegistroView || "manutencao");
    return;
  }

  carregarFrotaResumo().catch(()=>{});
}

function openGestaoFrotaCargas(ev){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const menu = document.querySelector('.menu-item.has-submenu[data-tab="gestaofrota"]');
  showTab("cargas", menu);
  setCargasView("cadastro");

  document.querySelectorAll("#submenuGestaoFrota .submenu-item").forEach((item) => item.classList.remove("active"));
  const items = document.querySelectorAll("#submenuGestaoFrota .submenu-item");
  const target = 3;
  if (items && items[target]) items[target].classList.add("active");

  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && menu) menu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
}

function openGestaoFrotaEscala(ev){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const menu = document.querySelector('.menu-item.has-submenu[data-tab="gestaofrota"]');
  showTab("cargas", menu);
  setCargasView("escala");

  document.querySelectorAll("#submenuGestaoFrota .submenu-item").forEach((item) => item.classList.remove("active"));
  const items = document.querySelectorAll("#submenuGestaoFrota .submenu-item");
  const target = 4;
  if (items && items[target]) items[target].classList.add("active");

  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && menu) menu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
}

function openGestaoRegistroView(view){
  setGestaoRegistroView(view);
}

function setGestaoRegistroView(view){
  window.__gestaoRegistroView = view;
  const views = {
    manutencao: document.getElementById("gestaoRegistroManutencao"),
    oleo: document.getElementById("gestaoRegistroOleo"),
    pneu: document.getElementById("gestaoRegistroPneu"),
    abastecimento: document.getElementById("gestaoRegistroAbastecimento"),
    lavagem: document.getElementById("gestaoRegistroLavagem"),
  };

  Object.entries(views).forEach(([key, el]) => {
    if (el) el.classList.toggle("hidden", key !== view);
  });

  document.querySelectorAll(".gestao-registro-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.gestaoRegistro === view);
  });

  carregarFrotaResumo().catch(()=>{});
  if (view === "manutencao") {
    carregarPreLancamentosManutencaoXml().catch(()=>{});
  }
}

function toggleComissaoSubmenu(ev){
  toggleExclusiveSubmenu(ev, () => openComissaoView(null, "lancamento"));
}

function openComissaoView(ev, view){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const menu = document.querySelector('.menu-item.has-submenu[data-tab="comissao"]');
  window.__comissaoView = view;
  showTab("comissao", menu);

  document.querySelectorAll("#submenuComissao .submenu-item").forEach(x=>x.classList.remove("active"));
  const map = { lancamento: 0, relatorios: 1 };
  const target = map[view] ?? 0;
  const items = document.querySelectorAll("#submenuComissao .submenu-item");
  if (items && items[target]) items[target].classList.add("active");

  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && menu) menu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
}

function setComissaoView(view){
  window.__comissaoView = view;
  const vLanc = document.getElementById("comissaoViewLancamento");
  const vRel = document.getElementById("comissaoViewRelatorios");
  if (vLanc) vLanc.classList.toggle("hidden", view !== "lancamento");
  if (vRel) vRel.classList.toggle("hidden", view !== "relatorios");
  if (view === "lancamento") carregarComissaoLancamentos().catch(()=>{});
  if (view === "relatorios") carregarRelatoriosComissao().catch(()=>{});
}

function toggleVendasSubmenu(ev){
  toggleExclusiveSubmenu(ev, () => openVendasView(null, window.__vendasView || "relatorio"));
}

function openVendasView(ev, view){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const menu = document.querySelector('.menu-item.has-submenu[data-tab="vendas"]');
  document.querySelectorAll("#submenuVendas .submenu-item").forEach((x) => x.classList.remove("active"));
  const items = document.querySelectorAll("#submenuVendas .submenu-item");
  const targetView = (view === "pontosvenda" ? "pontosvenda" : "relatorio");
  const itemAtivo = document.querySelector(`#submenuVendas .submenu-item[data-vendas-view="${targetView}"]`);

  if (targetView === "pontosvenda") {
    window.__pontosVendaView = "cadastro";
    showTab("pontosvenda", menu);
    if (itemAtivo) itemAtivo.classList.add("active");
  } else {
    window.__vendasView = "relatorio";
    showTab("vendas", menu);
    if (itemAtivo) itemAtivo.classList.add("active");
    setVendasView("relatorio");
  }

  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && menu) menu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
}

function setVendasView(view){
  const target = String(view || "relatorio").toLowerCase() === "pontosvenda" ? "pontosvenda" : "relatorio";
  window.__vendasView = target;
  vendasState.view = target;
  const rel = document.getElementById("vendasViewRelatorio");
  if (rel) rel.classList.toggle("hidden", target !== "relatorio");
  if (target === "relatorio") {
    setVendasRelatorioModo(window.__vendasRelatorioModo || "bonificacoes");
  }
}

function openVendasComissao(ev){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const menu = document.querySelector('.menu-item.has-submenu[data-tab="vendas"]');
  showTab("comissao", menu);

  document.querySelectorAll("#submenuVendas .submenu-item").forEach((item) => item.classList.remove("active"));
  const items = document.querySelectorAll("#submenuVendas .submenu-item");
  const target = 2;
  if (items && items[target]) items[target].classList.add("active");

  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && menu) menu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
}

function _vendasDashboardCelulaClassificacao(valorAtual = 0, valorAnterior = null) {
  if (valorAnterior === null || valorAnterior === undefined) {
    return "vendas-dashboard-cell vendas-dashboard-cell-neutral";
  }
  if (valorAtual > valorAnterior) return "vendas-dashboard-cell vendas-dashboard-cell-up";
  if (valorAtual < valorAnterior) return "vendas-dashboard-cell vendas-dashboard-cell-down";
  return "vendas-dashboard-cell vendas-dashboard-cell-equal";
}

function renderDashboardVendas(payload = {}) {
  window.__vendasDashboardLastPayload = payload;
  const meses = Array.isArray(payload?.meses_disponiveis) ? payload.meses_disponiveis : [];
  const vendedores = Array.isArray(payload?.vendedores) ? payload.vendedores : [];
  const resumo = payload?.resumo_geral || {};
  const mesAtual = payload?.mes_atual || (meses.length ? meses[meses.length - 1] : "");
  const mesAnterior = payload?.mes_anterior || (meses.length > 1 ? meses[meses.length - 2] : "");
  const arquivo = payload?.arquivo || {};

  const infoEl = document.getElementById("vendasDashArquivoInfo");
  if (infoEl) {
    const parts = [
      `Arquivo: ${arquivo.nome || "Base atual"}`,
      `Mês atual: ${_vendasMesLabelTexto(mesAtual)}`,
    ];
    if (mesAnterior) parts.push(`Mês anterior: ${_vendasMesLabelTexto(mesAnterior)}`);
    infoEl.textContent = parts.join(" | ");
  }

  const cardsEl = document.getElementById("vendasDashResumoCards");
  if (cardsEl) {
    cardsEl.innerHTML = _renderCardsVendasResumo([
      ["Mês atual", _vendasMesLabelTexto(mesAtual)],
      ["Vendedores", _fmtNumVendas(resumo.vendedores)],
      ["Valor atual", _fmtMoneyVendas(resumo.valor_atual)],
      ["Valor anterior", _fmtMoneyVendas(resumo.valor_anterior)],
      ["Diferença", _fmtMoneyVendas(resumo.variacao_valor)],
      ["Dif. %", `${_fmtNumVendas(resumo.variacao_percentual || 0, 2)}%`],
      ["Cresceu", _fmtNumVendas(resumo.cresceu)],
      ["Caiu", _fmtNumVendas(resumo.caiu)],
      ["Estável", _fmtNumVendas(resumo.estavel)],
      ["Meses", _fmtNumVendas(meses.length)],
    ]);
  }

  const headEl = document.getElementById("vendasDashHead");
  if (headEl) {
    const monthHeaders = meses.map((mes) => `<th>${_escHtml(_vendasMesLabelTexto(mes))}</th>`).join("");
    headEl.innerHTML = `
      <tr>
        <th>Vendedor</th>
        <th>Cod</th>
        <th>Total</th>
        <th>Último</th>
        <th>Δ</th>
        <th>Δ%</th>
        ${monthHeaders}
      </tr>
    `;
  }

  const bodyEl = document.getElementById("vendasDashBody");
  if (bodyEl) {
    bodyEl.innerHTML = vendedores.length ? vendedores.map((item) => {
      const serie = item?.meses || {};
      let anterior = null;
      const mesesHtml = meses.map((mes) => {
        const valorAtual = _asFloat(serie?.[mes]?.valor_liquido, 0.0);
        const valorAnterior = anterior;
        const delta = valorAnterior === null ? 0.0 : valorAtual - valorAnterior;
        const deltaPct = valorAnterior && valorAnterior !== 0 ? (delta / Math.abs(valorAnterior)) * 100.0 : 0.0;
        const classe = _vendasDashboardCelulaClassificacao(valorAtual, valorAnterior);
        anterior = valorAtual;
        return `
          <td class="${classe}" title="${_escHtml(_vendasMesLabelTexto(mes))}">
            <strong>${_escHtml(_fmtMoneyVendas(valorAtual))}</strong>
            ${valorAnterior !== null ? `<span>${_escHtml(`${delta >= 0 ? "+" : ""}${_fmtNumVendas(deltaPct, 1)}%`)}</span>` : ""}
          </td>
        `;
      }).join("");
      const total = _asFloat(item?.total_valor_liquido, 0.0);
      const ultimo = _asFloat(item?.ultimo_valor_liquido, 0.0);
      const delta = _asFloat(item?.delta_ultimo_mes, 0.0);
      const deltaPct = _asFloat(item?.delta_percentual_ultimo_mes, 0.0);
      const classeResumo = delta > 0 ? "vendas-dashboard-chip vendas-dashboard-chip-up" : (delta < 0 ? "vendas-dashboard-chip vendas-dashboard-chip-down" : "vendas-dashboard-chip vendas-dashboard-chip-equal");
      return `
        <tr>
          <td>${_escHtml(item.nome || "-")}</td>
          <td>${_escHtml(item.codigo || "-")}</td>
          <td>${_escHtml(_fmtMoneyVendas(total))}</td>
          <td>${_escHtml(_fmtMoneyVendas(ultimo))}</td>
          <td><span class="${classeResumo}">${_escHtml(_fmtMoneyVendas(delta))}</span></td>
          <td><span class="${classeResumo}">${_escHtml(`${delta >= 0 ? "+" : ""}${_fmtNumVendas(deltaPct, 2)}%`)}</span></td>
          ${mesesHtml}
        </tr>
      `;
    }).join("") : `<tr><td colspan="${6 + meses.length}">Nenhum dado de evolução encontrado para o período selecionado.</td></tr>`;
  }
}

async function carregarDashboardVendas() {
  const infoEl = document.getElementById("vendasDashArquivoInfo");
  if (infoEl) infoEl.textContent = "Carregando dashboard de vendas...";
  const resp = await apiFetch("/api/vendas/dashboard");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const erro = data?.erro || "Falha ao carregar dashboard de vendas.";
    if (infoEl) infoEl.textContent = erro;
    alert(erro);
    return;
  }
  renderDashboardVendas(data || {});
}

function openPontosVendaView(ev, view){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const menu = document.querySelector('.menu-item.has-submenu[data-tab="vendas"]');
  window.__pontosVendaView = view;
  showTab("pontosvenda", menu);

  document.querySelectorAll("#submenuVendas .submenu-item").forEach((x) => x.classList.remove("active"));
  const items = document.querySelectorAll("#submenuVendas .submenu-item");
  if (items && items[2]) items[2].classList.add("active");

  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && menu) menu.classList.remove("open");
  try { toggleMenuMobile(false); } catch {}
}

function setPontosVendaView(view){
  window.__pontosVendaView = view;
  pontosVendaState.view = view;
  const vCadastro = document.getElementById("pontosVendaViewCadastro");
  const vRelatorio = document.getElementById("pontosVendaViewRelatorio");
  if (vCadastro) vCadastro.classList.toggle("hidden", view !== "cadastro");
  if (vRelatorio) vRelatorio.classList.toggle("hidden", view !== "relatorio");
  if (view === "relatorio") {
    const dataRef = document.getElementById("pontosVendaDataRef");
    if (dataRef && !dataRef.value) dataRef.value = _dataHojeInputLocal();
  }
  if (view === "cadastro") carregarPontosVenda().catch(() => {});
  if (view === "relatorio") carregarPontosVendaRelatorio().catch(() => {});
}

function _fmtMoneyVendas(value){
  return Number(value || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function _fmtNumVendas(value, digits = 0){
  return Number(value || 0).toLocaleString("pt-BR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function _resumoCardVendas(label, value){
  return `
    <div class="vendas-resumo-card">
      <strong>${_escHtml(label)}</strong>
      <span>${_escHtml(value)}</span>
    </div>
  `;
}

function _renderCardsVendasResumo(items){
  return items.map(([label, value]) => _resumoCardVendas(label, value)).join("");
}

const _VENDAS_RELATORIO_ESPECIAL_TIPOS = new Set([
  "volume_diario_resumo",
  "volume_diario_vendedor",
  "percentual_vendas_anual",
  "percentual_vendas_grupo_anual",
]);

function _vendasRelatorioEhEspecial(tipoRelatorio){
  return _VENDAS_RELATORIO_ESPECIAL_TIPOS.has(String(tipoRelatorio || ""));
}

function _vendasTabelaVazia(colspan, mensagem){
  return `<tr><td colspan="${_escHtml(colspan)}">${_escHtml(mensagem)}</td></tr>`;
}

function _vendasBoxTabelaHtml({ titulo, hint = "", maxHeight = "360px", thead = "", tbody = "", colspan = 1 } = {}) {
  return `
    <div class="boxFrota">
      <h3>${_escHtml(titulo || "-")}</h3>
      ${hint ? `<div class="hint">${_escHtml(hint)}</div>` : ""}
      <div style="overflow:auto; max-height:${_escHtml(maxHeight)};">
        <table>
          <thead>${thead}</thead>
          <tbody>${tbody || _vendasTabelaVazia(colspan, "Nenhum dado encontrado.")}</tbody>
        </table>
      </div>
    </div>
  `;
}

function _vendasBoxesEmGrupos(boxes = []){
  const itens = Array.isArray(boxes) ? boxes.filter(Boolean) : [];
  if (!itens.length) return "";
  const grupos = [];
  for (let i = 0; i < itens.length; i += 2) {
    grupos.push(`<div class="frotaGrid">${itens.slice(i, i + 2).join("")}</div>`);
  }
  return grupos.join("");
}

function _vendasResumoCardsParaTipo(tipoRelatorio, resumo = {}, payload = {}){
  if (tipoRelatorio === "volume_diario_resumo") {
    return [
      ["Dias", _fmtNumVendas(resumo.dias)],
      ["Itens", _fmtNumVendas(resumo.itens)],
      ["Notas", _fmtNumVendas(resumo.notas)],
      ["Clientes", _fmtNumVendas(resumo.clientes)],
      ["Vendedores", _fmtNumVendas(resumo.vendedores)],
      ["Hectolitros", _fmtNumVendas(resumo.hectolitros, 3)],
      ["Venda", _fmtMoneyVendas(resumo.valor_venda)],
      ["Devolvido", _fmtMoneyVendas(resumo.valor_devolvido)],
      ["Bonificação", _fmtMoneyVendas(resumo.bonificacao)],
      ["Líquido", _fmtMoneyVendas(resumo.valor_liquido)],
    ];
  }

  if (tipoRelatorio === "volume_diario_vendedor") {
    return [
      ["Dias", _fmtNumVendas(resumo.dias)],
      ["Vendedores", _fmtNumVendas(resumo.vendedores)],
      ["Itens", _fmtNumVendas(resumo.itens)],
      ["Clientes", _fmtNumVendas(resumo.clientes)],
      ["Notas", _fmtNumVendas(resumo.notas)],
      ["Hectolitros", _fmtNumVendas(resumo.hectolitros, 3)],
    ];
  }

  if (tipoRelatorio === "percentual_vendas_anual") {
    return [
      ["Ano atual", _fmtNumVendas(resumo.total_atual, 3)],
      ["Ano anterior", _fmtNumVendas(resumo.total_anterior, 3)],
      ["Variação", `${_fmtNumVendas(resumo.variacao_total, 2)}%`],
      ["Meses", _fmtNumVendas(Array.isArray(payload?.meses) ? payload.meses.length : 0)],
    ];
  }

  if (tipoRelatorio === "percentual_vendas_grupo_anual") {
    const primeiro = Array.isArray(payload?.blocos) && payload.blocos.length ? (payload.blocos[0]?.dados?.resumo || {}) : {};
    return [
      ["Blocos", _fmtNumVendas(Array.isArray(payload?.blocos) ? payload.blocos.length : 0)],
      ["Ano atual", _fmtNumVendas(primeiro.total_atual, 3)],
      ["Ano anterior", _fmtNumVendas(primeiro.total_anterior, 3)],
      ["Variação", `${_fmtNumVendas(primeiro.variacao_total, 2)}%`],
    ];
  }

  return [];
}

function _vendasTabelaComparativoAnualHtml(dados = {}, titulo = "", hint = "") {
  const meses = Array.isArray(dados?.meses) ? dados.meses : [];
  const linhas = Array.isArray(dados?.linhas) ? dados.linhas : [];
  if (!meses.length) {
    return _vendasBoxTabelaHtml({
      titulo,
      hint,
      thead: "<tr><th>Ano</th></tr>",
      tbody: _vendasTabelaVazia(1, "Nenhum dado encontrado."),
      colspan: 1,
    });
  }
  const colunas = meses.map((mes) => `<th>${_escHtml(mes?.label || "-")}</th>`).join("");
  const linhasHtml = linhas.map((linha) => {
    const valores = Array.isArray(linha?.valores) ? linha.valores : [];
    const rotulo = _as_str(linha?.rotulo || "-");
    const total = rotulo === "%"
      ? `${_fmtNumVendas(linha?.total, 2)}%`
      : _fmtNumVendas(linha?.total, 3);
    return `
      <tr${rotulo === "%" ? ' style="font-weight:700;"' : ""}>
        <td>${_escHtml(rotulo)}</td>
        ${valores.map((valor) => `<td>${_escHtml(rotulo === "%" ? `${_fmtNumVendas(valor, 2)}%` : _fmtNumVendas(valor, 3))}</td>`).join("")}
        <td>${_escHtml(total)}</td>
      </tr>
    `;
  }).join("");
  return _vendasBoxTabelaHtml({
    titulo,
    hint,
    maxHeight: "320px",
    thead: `<tr><th>Ano</th>${colunas}<th>Total</th></tr>`,
    tbody: linhasHtml,
    colspan: meses.length + 2,
  });
}

function _vendasRenderRelatorioEspecial(tipoRelatorio, payload = {}) {
  const resumo = payload?.resumo_geral || {};
  if (tipoRelatorio === "volume_diario_resumo") {
    const dias = Array.isArray(payload?.dias) ? payload.dias : [];
    const tbody = dias.length ? dias.map((item) => `
      <tr>
        <td>${_escHtml(item.data || "-")}</td>
        <td>${_escHtml(item.dia_semana || "-")}</td>
        <td>${_escHtml(_fmtNumVendas(item.itens))}</td>
        <td>${_escHtml(_fmtNumVendas(item.notas))}</td>
        <td>${_escHtml(_fmtNumVendas(item.clientes))}</td>
        <td>${_escHtml(_fmtNumVendas(item.vendedores))}</td>
        <td>${_escHtml(_fmtNumVendas(item.hectolitros, 3))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_venda))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_devolvido))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.bonificacao))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_liquido))}</td>
      </tr>
    `).join("") : _vendasTabelaVazia(11, "Nenhum dado encontrado para o intervalo selecionado.");
    return _vendasBoxTabelaHtml({
      titulo: "Resumo de volume diário",
      hint: "Os volumes são exibidos em hectolitros e a bonificação não entra na base.",
      maxHeight: "420px",
      thead: `
        <tr>
          <th>Data</th>
          <th>Dia</th>
          <th>Itens</th>
          <th>Notas</th>
          <th>Clientes</th>
          <th>Vendedores</th>
          <th>HL</th>
          <th>Venda</th>
          <th>Devolvido</th>
          <th>Bonificação</th>
          <th>Líquido</th>
        </tr>
      `,
      tbody,
      colspan: 11,
    });
  }

  if (tipoRelatorio === "volume_diario_vendedor") {
    const dias = Array.isArray(payload?.dias) ? payload.dias : [];
    const vendedores = Array.isArray(payload?.vendedores) ? payload.vendedores : [];
    const colunasDias = dias.map((dia) => `<th>${_escHtml(dia?.label || dia?.data || "-")}</th>`).join("");
    const tbody = vendedores.length ? vendedores.map((item) => `
      <tr>
        <td>${_escHtml(item.codigo || "-")}</td>
        <td>${_escHtml(item.nome || "-")}</td>
        <td>${_escHtml(_fmtNumVendas(item.itens))}</td>
        <td>${_escHtml(_fmtNumVendas(item.notas))}</td>
        <td>${_escHtml(_fmtNumVendas(item.clientes))}</td>
        ${(Array.isArray(item.valores) ? item.valores : []).map((valor) => `<td>${_escHtml(_fmtNumVendas(valor, 3))}</td>`).join("")}
        <td>${_escHtml(_fmtNumVendas(item.total, 3))}</td>
      </tr>
    `).join("") : _vendasTabelaVazia(dias.length + 6, "Nenhum vendedor encontrado para o intervalo selecionado.");
    return _vendasBoxTabelaHtml({
      titulo: "Volume diário por vendedor",
      hint: "Cada coluna de data mostra o volume em hectolitros para aquele vendedor.",
      maxHeight: "420px",
      thead: `<tr><th>Cod</th><th>Vendedor</th><th>Itens</th><th>Notas</th><th>Clientes</th>${colunasDias}<th>Total</th></tr>`,
      tbody,
      colspan: dias.length + 6,
    });
  }

  if (tipoRelatorio === "percentual_vendas_anual") {
    return _vendasTabelaComparativoAnualHtml(
      payload,
      "Percentual de vendas anual",
      "Comparativo entre o ano atual e o anterior, em hectolitros.",
    );
  }

  if (tipoRelatorio === "percentual_vendas_grupo_anual") {
    const blocos = Array.isArray(payload?.blocos) ? payload.blocos : [];
    const boxes = blocos.map((bloco) => _vendasTabelaComparativoAnualHtml(
      bloco?.dados || {},
      bloco?.titulo || "-",
      "Comparativo anual em hectolitros.",
    ));
    return _vendasBoxesEmGrupos(boxes);
  }

  return "";
}

function _vendasPainelMensalHtml(painel = {}) {
  const meses = Array.isArray(painel?.meses) ? painel.meses : [];
  const linhas = Array.isArray(painel?.linhas) ? painel.linhas : [];
  const total = painel?.total || {};
  if (!meses.length) return "";

  const colunasMes = meses.map((mes) => `<th>${_escHtml(mes?.label || "-")}</th>`).join("");

  const rowsHtml = linhas.map((item) => {
    const valores = Array.isArray(item?.valores) ? item.valores : [];
    return `
      <tr style="${item?.nome === "Total" ? "background:#fff3c4;font-weight:700;" : ""}">
        <td>${_escHtml(item?.nome || item?.rotulo || "-")}${item?.codigo ? ` <small style="display:block; opacity:.75;">${_escHtml(item.codigo)}</small>` : ""}</td>
        <td>${_escHtml(Number(item?.tendencia || 0) > 0 ? `+${_fmtNumVendas(Number(item.tendencia || 0), 1)}%` : `${_fmtNumVendas(Number(item?.tendencia || 0), 1)}%`)}</td>
        ${valores.map((valor) => `<td>${_escHtml(_fmtNumVendas(Number(valor || 0), 0))}</td>`).join("")}
        <td>${_escHtml(_fmtNumVendas(Number(item?.total || 0), 0))}</td>
      </tr>
    `;
  }).join("");

  const totalHtml = `
    <tr style="background:#fff3c4;font-weight:700;">
      <td>${_escHtml(total?.nome || "Total")}</td>
      <td>${_escHtml(Number(total?.tendencia || 0) > 0 ? `+${_fmtNumVendas(Number(total.tendencia || 0), 1)}%` : `${_fmtNumVendas(Number(total?.tendencia || 0), 1)}%`)}</td>
      ${(Array.isArray(total?.valores) ? total.valores : []).map((valor) => `<td>${_escHtml(_fmtNumVendas(Number(valor || 0), 0))}</td>`).join("")}
      <td>${_escHtml(_fmtNumVendas(Number(total?.total || 0), 0))}</td>
    </tr>
  `;

  return `
    <div class="boxFrota">
      <h3>${_escHtml(painel?.titulo || "VOLUME EM HL 12 ULTIMOS MESES")}</h3>
      <div class="hint">Referência: ${_escHtml(painel?.referencia || "-")}</div>
      <div style="overflow:auto; max-height:360px;">
        <table>
          <thead>
            <tr>
              <th>Vendedor</th>
              <th>Tend.</th>
              ${colunasMes}
              <th>Total</th>
            </tr>
          </thead>
          <tbody>
            ${rowsHtml}
            ${totalHtml}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function _vendasSetVisibilidadeRelatorio(tipoRelatorio){
  const resumoView = document.getElementById("vendasRelResumoView");
  const embalagensView = document.getElementById("vendasRelEmbalagensView");
  const variacaoView = document.getElementById("vendasRelVariacaoVendaView");
  const consolidadoView = document.getElementById("vendasRelConsolidadoVendaView");
  const bonificacaoView = document.getElementById("vendasRelBonificacaoView");
  const especialView = document.getElementById("vendasRelEspecialView");
  const especial = _vendasRelatorioEhEspecial(tipoRelatorio);
  if (resumoView) resumoView.classList.toggle("hidden", tipoRelatorio !== "resumo");
  if (embalagensView) embalagensView.classList.toggle("hidden", tipoRelatorio !== "embalagens");
  if (variacaoView) variacaoView.classList.toggle("hidden", tipoRelatorio !== "variacao_venda");
  if (consolidadoView) consolidadoView.classList.toggle("hidden", tipoRelatorio !== "consolidado_venda");
  if (bonificacaoView) bonificacaoView.classList.toggle("hidden", tipoRelatorio !== "bonificacao_percentual");
  if (especialView) especialView.classList.toggle("hidden", !especial);
}

function _vendasPreencherSelectClientes(clientes, selectedKey = "", selectId = "vendasRelCliente", placeholder = "Todos os PDVs"){
  const select = document.getElementById(selectId);
  if (!select) return;
  const current = String(selectedKey || select.value || "");
  const options = [`<option value="">${_escHtml(placeholder)}</option>`].concat(
    (Array.isArray(clientes) ? clientes : []).map((item) => {
      const key = item?.chave || "";
      const label = item?.cliente || item?.nome || "Sem PDV";
      const cidade = item?.cidade ? ` (${item.cidade})` : "";
      const qtd = item?.qtd_grupos != null ? ` - ${_fmtNumVendas(item.qtd_grupos)} grupos` : "";
      return `<option value="${_escHtml(key)}">${_escHtml(label + cidade + qtd)}</option>`;
    })
  );
  select.innerHTML = options.join("");
  select.value = (Array.isArray(clientes) && clientes.some((item) => String(item?.chave || "") === current)) ? current : "";
}

function atualizarVisibilidadeFiltrosRelatorioVendas() {
  const vendedorWrap = document.getElementById("vendasRelVendedorWrap");
  if (vendedorWrap) vendedorWrap.classList.remove("hidden");
}

function selecionarVendedorRelatorioVendas(chave = ""){
  const select = document.getElementById("vendasRelVendedor");
  if (select) select.value = chave || "";
  agendarCarregarRelatorioVendas();
}

function agendarCarregarRelatorioVendas(delayMs = 180){
  if (window.__vendasRelatorioTimer) {
    clearTimeout(window.__vendasRelatorioTimer);
  }
  window.__vendasRelatorioTimer = setTimeout(() => {
    window.__vendasRelatorioTimer = null;
    carregarRelatorioVendas().catch((err) => {
      console.warn("relatorio vendas erro:", err);
    });
  }, delayMs);
}

function renderRelatorioVendas(payload = {}){
  vendasState.lastPayload = payload;
  const tipoRelatorioRaw = (payload?.relatorio_tipo || document.getElementById("vendasRelTipo")?.value || "bonificacoes").toLowerCase();
  const tipoRelatorio = tipoRelatorioRaw.replace(/-/g, "_");
  vendasState.tipoRelatorio = tipoRelatorio;
  const mesAtual = payload?.mes_atual || payload?.filtros?.mes || "";
  vendasState.mes = mesAtual;
  const meses = Array.isArray(payload?.meses_disponiveis) ? payload.meses_disponiveis : [];
  const resumo = payload?.resumo_geral || {};
  const vendedores = Array.isArray(payload?.vendedores) ? payload.vendedores : [];
  const cidades = Array.isArray(payload?.cidades) ? payload.cidades : [];
  const produtos = Array.isArray(payload?.produtos) ? payload.produtos : [];
  const detalhes = Array.isArray(payload?.detalhes_vendedor) ? payload.detalhes_vendedor : [];
  const clientes = Array.isArray(payload?.clientes) ? payload.clientes : [];
  const clientesDisponiveis = Array.isArray(payload?.clientes_disponiveis) ? payload.clientes_disponiveis : [];
  const variacoes = Array.isArray(payload?.variacoes) ? payload.variacoes : [];
  const consolidados = Array.isArray(payload?.consolidados) ? payload.consolidados : [];
  const resumoGrupos = Array.isArray(payload?.resumo_grupos) ? payload.resumo_grupos : [];
  const arquivo = payload?.arquivo || {};
  const vendedorFiltro = document.getElementById("vendasRelVendedor")?.value || payload?.filtros?.vendedor || "";
  const clienteFiltro = document.getElementById("vendasRelCliente")?.value || payload?.filtros?.cliente || "";
  const especial = _vendasRelatorioEhEspecial(tipoRelatorio);
  const tipoSelect = document.getElementById("vendasRelTipo");
  if (tipoSelect) {
    tipoSelect.value = tipoRelatorio;
  }
  _vendasPreencherSelectMeses(meses, mesAtual, "vendasRelMes");
  _vendasPreencherSelectVendedores(vendedores, vendedorFiltro);

  if (tipoRelatorio === "resumo" || tipoRelatorio === "bonificacoes") {
    const infoEl = document.getElementById("vendasRelArquivoInfo");
    if (infoEl) {
      const parts = [];
      parts.push(`Arquivo: ${arquivo.nome || "Base atual"}`);
      parts.push(`Atualizado em: ${arquivo.atualizado_em || "-"}`);
      parts.push(`Mês: ${_vendasMesLabelTexto(mesAtual)}`);
      if (vendedorFiltro) parts.push(`Vendedor: ${vendedorFiltro}`);
      infoEl.textContent = parts.join(" | ");
    }

    const cardsEl = document.getElementById("vendasRelResumoCards");
    if (cardsEl) {
      cardsEl.innerHTML = _renderCardsVendasResumo(_vendasResumoBonificacoesCards(resumo, payload));
    }

    const grupoResumoEl = document.getElementById("vendasRelGrupoResumo");
    if (grupoResumoEl) {
      grupoResumoEl.innerHTML = _vendasRenderGrupoBonificacoes(resumoGrupos);
    }

    const vendedoresBody = document.getElementById("vendasRelVendedoresBody");
    if (vendedoresBody) {
      vendedoresBody.innerHTML = vendedores.length ? vendedores.map((item) => `
        <tr onclick="selecionarVendedorRelatorioVendas('${_escJsString(item.chave || "")}')">
          <td>${_escHtml(item.codigo || "-")}</td>
          <td>${_escHtml(item.nome || "-")}</td>
          <td>${_escHtml(_fmtNumVendas(item.itens))}</td>
          <td>${_escHtml(_fmtNumVendas(item.clientes))}</td>
          <td>${_escHtml(_fmtNumVendas(item.notas))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.valor_venda))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.bonificacao))}</td>
          <td>${_escHtml(`${_fmtNumVendas(item.percentual, 2)}%`)}</td>
          <td>${_escHtml(`${_fmtNumVendas(item.media_percentual_bonificacao || 0, 2)}%`)}</td>
        </tr>
      `).join("") : '<tr><td colspan="9">Nenhum vendedor encontrado para o mês selecionado.</td></tr>';
    }

    const detalhesHint = document.getElementById("vendasRelDetalhesHint");
    if (detalhesHint) {
      if (vendedorFiltro) {
        detalhesHint.textContent = `Mostrando detalhe individual para ${vendedorFiltro} no mês ${_vendasMesLabelTexto(mesAtual)}.`;
      } else {
        detalhesHint.textContent = "Selecione vendedor para ver o detalhe individual.";
      }
    }

    const detalhesBody = document.getElementById("vendasRelDetalhesBody");
    if (detalhesBody) {
      detalhesBody.innerHTML = detalhes.length ? detalhes.map((item) => `
        <tr>
          <td>${_escHtml(item.data || "-")}</td>
          <td>${_escHtml(item.numero_nf || "-")}</td>
          <td>${_escHtml(item.cliente || "-")}</td>
          <td>${_escHtml(item.cidade || "-")}</td>
          <td>${_escHtml(item.produto || "-")}</td>
          <td>${_escHtml(_fmtNumVendas(item.tab_venda))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.valor_venda))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.valor_devolvido))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.bonificacao))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.valor_liquido))}</td>
        </tr>
      `).join("") : '<tr><td colspan="10">Selecione vendedor para carregar os detalhes.</td></tr>';
    }
    return;
  }

  _vendasPreencherSelectClientes(clientesDisponiveis, clienteFiltro);
  atualizarVisibilidadeFiltrosRelatorioVendas();
  _vendasSetVisibilidadeRelatorio(tipoRelatorio);

  const infoEl = document.getElementById("vendasRelArquivoInfo");
  if (infoEl) {
    const parts = [];
    const relatorioLabels = {
      embalagens: "Embalagens por cliente",
      variacao_venda: "Variação de venda",
      consolidado_venda: "Consolidado de vendas",
      bonificacao_percentual: "Bonificação por vendedor",
      volume_diario_resumo: "Resumo de volume diário",
      volume_diario_vendedor: "Volume diário por vendedor",
      percentual_vendas_anual: "Percentual de vendas anual",
      percentual_vendas_grupo_anual: "Percentual de vendas por grupo anual",
      resumo: "Resumo de vendas",
    };
    const relatorioLabel = relatorioLabels[tipoRelatorio] || "Resumo de vendas";
    parts.push(`Arquivo: ${arquivo.nome || "Base atual"}`);
    parts.push(`Atualizado em: ${arquivo.atualizado_em || "-"}`);
    parts.push(`Relatorio: ${relatorioLabel}`);
    if (vendedorFiltro) parts.push(`Vendedor: ${vendedorFiltro}`);
    if (clienteFiltro) parts.push(`Cliente: ${clienteFiltro}`);
    infoEl.textContent = parts.join(" | ");
  }

  const cardsEl = document.getElementById("vendasRelResumoCards");
  const cardsResumo = especial
    ? _vendasResumoCardsParaTipo(tipoRelatorio, resumo, payload)
    : (tipoRelatorio === "embalagens"
    ? [
        ["Volumes", _fmtNumVendas(resumo.volumes ?? resumo.qtd_embalagens, 3)],
        ["Clientes", _fmtNumVendas(resumo.clientes)],
        ["Retornável", _fmtNumVendas(resumo.retornavel, 3)],
        ["Descartável (PET)", _fmtNumVendas(resumo.pet, 3)],
        ["Bonificação", _fmtMoneyVendas(resumo.bonificacao)],
        ["Categorias usadas", _fmtNumVendas(resumo.tipos_utilizados)],
        ["Categorias retornáveis", _fmtNumVendas(resumo.tipos_retornavel)],
        ["Categorias PET", _fmtNumVendas(resumo.tipos_pet)],
      ]
    : tipoRelatorio === "variacao_venda"
    ? [
        ["Variações", _fmtNumVendas(resumo.variacoes)],
        ["Categorias", _fmtNumVendas(resumo.categorias)],
        ["Cidades", _fmtNumVendas(resumo.cidades)],
        ["Preços distintos", _fmtNumVendas(resumo.precos_distintos)],
        ["Hectolitros", _fmtNumVendas(resumo.volumes ?? resumo.hectolitros, 3)],
        ["Bonificação", _fmtMoneyVendas(resumo.bonificacao)],
        ["Valor líquido", _fmtMoneyVendas(resumo.valor_liquido)],
      ]
    : tipoRelatorio === "consolidado_venda"
    ? [
        ["Categorias", _fmtNumVendas(resumo.categorias)],
        ["Clientes", _fmtNumVendas(resumo.clientes)],
        ["Cidades", _fmtNumVendas(resumo.cidades)],
        ["Hectolitros cliente", _fmtNumVendas(resumo.volumes_cliente, 3)],
        ["Hectolitros vendedor", _fmtNumVendas(resumo.volumes_vendedor, 3)],
        ["Participação total", `${_fmtNumVendas(resumo.participacao_total, 2)}%`],
        ["Bonificação", _fmtMoneyVendas(resumo.bonificacao)],
        ["Valor líquido", _fmtMoneyVendas(resumo.valor_liquido)],
      ]
    : tipoRelatorio === "bonificacao_percentual"
    ? [
        ["Vendedores", _fmtNumVendas(resumo.vendedores)],
        ["Clientes", _fmtNumVendas(resumo.clientes)],
        ["Notas", _fmtNumVendas(resumo.notas)],
        ["Itens", _fmtNumVendas(resumo.itens)],
        ["Líquido", _fmtMoneyVendas(resumo.valor_liquido)],
        ["Bonificação", _fmtMoneyVendas(resumo.bonificacao)],
        ["% Bonificação", `${_fmtNumVendas(resumo.percentual, 2)}%`],
      ]
    : [
        ["Valor liquido", _fmtMoneyVendas(resumo.valor_liquido)],
        ["Valor venda", _fmtMoneyVendas(resumo.valor_venda)],
        ["Valor devolvido", _fmtMoneyVendas(resumo.valor_devolvido)],
        ["Bonificação", _fmtMoneyVendas(resumo.bonificacao)],
        ["Notas", _fmtNumVendas(resumo.notas)],
        ["Clientes", _fmtNumVendas(resumo.clientes)],
        ["Itens", _fmtNumVendas(resumo.itens)],
      ]);
  if (cardsEl) {
    cardsEl.innerHTML = _renderCardsVendasResumo(cardsResumo);
  }

  const grupoResumoEl = document.getElementById("vendasRelGrupoResumo");
  if (grupoResumoEl) {
    if (tipoRelatorio === "consolidado_venda" && resumoGrupos.length) {
      grupoResumoEl.innerHTML = `
        <h4>Resumo por tipo de vendedor</h4>
        <div style="overflow:auto; max-height:240px;">
          <table>
            <thead>
              <tr>
                <th>Grupo</th>
                <th>Vendedores</th>
                <th>Clientes</th>
                <th>Notas</th>
                <th>Itens</th>
                <th>HL cliente</th>
                <th>HL vendedor</th>
                <th>%</th>
                <th>Liquido</th>
                <th>Bonificacao</th>
              </tr>
            </thead>
            <tbody>
              ${resumoGrupos.map((item) => `
                <tr>
                  <td>${_escHtml(item.nome || item.grupo || "-")}</td>
                  <td>${_escHtml(_fmtNumVendas(item.vendedores))}</td>
                  <td>${_escHtml(_fmtNumVendas(item.clientes))}</td>
                  <td>${_escHtml(_fmtNumVendas(item.notas))}</td>
                  <td>${_escHtml(_fmtNumVendas(item.itens))}</td>
                  <td>${_escHtml(_fmtNumVendas(item.hectolitros_cliente, 3))}</td>
                  <td>${_escHtml(_fmtNumVendas(item.hectolitros_vendedor, 3))}</td>
                  <td>${_escHtml(`${_fmtNumVendas(item.participacao_total, 2)}%`)}</td>
                  <td>${_escHtml(_fmtMoneyVendas(item.valor_liquido))}</td>
                  <td>${_escHtml(_fmtMoneyVendas(item.bonificacao))}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      `;
    } else {
      grupoResumoEl.innerHTML = "";
    }
  }

  const especialView = document.getElementById("vendasRelEspecialView");
  if (especialView) {
    especialView.innerHTML = especial ? _vendasRenderRelatorioEspecial(tipoRelatorio, payload) : "";
  }

  if (especial) {
    return;
  }

  const select = document.getElementById("vendasRelVendedor");
  if (select) {
    const current = select.value || "";
    const options = ['<option value="">Todos os vendedores</option>'].concat(
      vendedores.map((item) => {
        const key = item?.chave || [item?.codigo, item?.nome].filter(Boolean).join(" - ");
        const label = [item?.codigo, item?.nome].filter(Boolean).join(" - ") || "Sem vendedor";
        return `<option value="${_escHtml(key)}">${_escHtml(label)}</option>`;
      })
    );
    select.innerHTML = options.join("");
    select.value = vendedores.some((item) => (item?.chave || "") === current) ? current : "";
  }

  if (tipoRelatorio === "embalagens") {
    const embalagensBody = document.getElementById("vendasRelEmbalagensBody");
    if (embalagensBody) {
      embalagensBody.innerHTML = clientes.length ? clientes.map((item) => `
        <tr>
          <td>${_escHtml(item.cliente || "-")}</td>
          <td>${_escHtml(item.cidade || "-")}</td>
          <td>${_escHtml(_fmtNumVendas(item.volumes ?? item.qtd_embalagens, 3))}</td>
          <td>${_escHtml(_fmtNumVendas(item.retornavel, 3))}</td>
          <td>${_escHtml(_fmtNumVendas(item.pet, 3))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.bonificacao))}</td>
          <td>${_escHtml(_fmtNumVendas(item.tipos_utilizados))}</td>
          <td>${_escHtml(_fmtNumVendas(item.tipos_retornavel))}</td>
          <td>${_escHtml(_fmtNumVendas(item.tipos_pet))}</td>
          <td>${_escHtml(item.tipos_lista || "-")}</td>
        </tr>
      `).join("") : '<tr><td colspan="10">Nenhum dado de embalagens encontrado.</td></tr>';
    }
    return;
  }

  if (tipoRelatorio === "variacao_venda") {
    const variacaoBody = document.getElementById("vendasRelVariacaoBody");
    if (variacaoBody) {
      variacaoBody.innerHTML = variacoes.length ? variacoes.map((item) => `
        <tr>
          <td>${_escHtml(item.categoria || "-")}</td>
          <td>${_escHtml(item.cidade || "-")}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.preco_aplicado))}</td>
          <td>${_escHtml(_fmtNumVendas(item.hectolitros ?? item.volumes, 3))}</td>
          <td>${_escHtml(_fmtNumVendas(item.itens))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.valor_venda))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.valor_devolvido))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.bonificacao))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.valor_liquido))}</td>
          <td>${_escHtml(_fmtNumVendas(item.notas))}</td>
          <td>${_escHtml(_fmtNumVendas(item.clientes))}</td>
        </tr>
      `).join("") : '<tr><td colspan="11">Nenhuma variação de venda encontrada.</td></tr>';
    }
    return;
  }

  if (tipoRelatorio === "consolidado_venda") {
    const consolidadoBody = document.getElementById("vendasRelConsolidadoBody");
    if (consolidadoBody) {
      consolidadoBody.innerHTML = consolidados.length ? consolidados.map((item) => `
        <tr>
          <td>${_escHtml(item.cidade || "-")}</td>
          <td>${_escHtml(item.categoria || "-")}</td>
          <td>${_escHtml(_fmtNumVendas(item.hectolitros_cliente ?? item.volumes_cliente, 3))}</td>
          <td>${_escHtml(_fmtNumVendas(item.hectolitros_vendedor ?? item.volumes_vendedor, 3))}</td>
          <td>${_escHtml(`${_fmtNumVendas(item.percentual, 2)}%`)}</td>
          <td>${_escHtml(_fmtNumVendas(item.itens))}</td>
          <td>${_escHtml(_fmtNumVendas(item.notas))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.valor_venda))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.valor_devolvido))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.bonificacao))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.valor_liquido))}</td>
        </tr>
      `).join("") : '<tr><td colspan="11">Nenhum dado encontrado para os filtros atuais.</td></tr>';
    }
    return;
  }

  if (tipoRelatorio === "bonificacao_percentual") {
    const bonificacaoBody = document.getElementById("vendasRelBonificacaoBody");
    if (bonificacaoBody) {
      bonificacaoBody.innerHTML = vendedores.length ? vendedores.map((item) => `
        <tr>
          <td>${_escHtml(item.codigo || "-")}</td>
          <td>${_escHtml(item.nome || "-")}</td>
          <td>${_escHtml(_fmtNumVendas(item.clientes))}</td>
          <td>${_escHtml(_fmtNumVendas(item.notas))}</td>
          <td>${_escHtml(_fmtNumVendas(item.itens))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.valor_liquido))}</td>
          <td>${_escHtml(_fmtMoneyVendas(item.bonificacao))}</td>
          <td>${_escHtml(`${_fmtNumVendas(item.percentual, 2)}%`)}</td>
        </tr>
      `).join("") : '<tr><td colspan="8">Nenhuma bonificação encontrada.</td></tr>';
    }
    return;
  }

  const vendedoresBody = document.getElementById("vendasRelVendedoresBody");
  if (vendedoresBody) {
    vendedoresBody.innerHTML = vendedores.length ? vendedores.map((item) => `
      <tr onclick="selecionarVendedorRelatorioVendas('${_escJsString(item.chave || "")}')">
        <td>${_escHtml(item.codigo || "-")}</td>
        <td>${_escHtml(item.nome || "-")}</td>
        <td>${_escHtml(_fmtNumVendas(item.clientes))}</td>
        <td>${_escHtml(_fmtNumVendas(item.notas))}</td>
        <td>${_escHtml(_fmtNumVendas(item.itens))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_venda))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_devolvido))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_liquido))}</td>
      </tr>
    `).join("") : '<tr><td colspan="8">Nenhum dado encontrado no CSV.</td></tr>';
  }

  const cidadesBody = document.getElementById("vendasRelCidadesBody");
  if (cidadesBody) {
    cidadesBody.innerHTML = cidades.length ? cidades.map((item) => `
      <tr>
        <td>${_escHtml(item.nome || "-")}</td>
        <td>${_escHtml(_fmtNumVendas(item.clientes))}</td>
        <td>${_escHtml(_fmtNumVendas(item.notas))}</td>
        <td>${_escHtml(_fmtNumVendas(item.itens))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_venda))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_devolvido))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_liquido))}</td>
      </tr>
    `).join("") : '<tr><td colspan="7">Nenhum agrupamento por cidade encontrado.</td></tr>';
  }

  const produtosBody = document.getElementById("vendasRelProdutosBody");
  if (produtosBody) {
    produtosBody.innerHTML = produtos.length ? produtos.map((item) => `
      <tr>
        <td>${_escHtml(item.nome || "-")}</td>
        <td>${_escHtml(_fmtNumVendas(item.clientes))}</td>
        <td>${_escHtml(_fmtNumVendas(item.notas))}</td>
        <td>${_escHtml(_fmtNumVendas(item.itens))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_venda))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_devolvido))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_liquido))}</td>
      </tr>
    `).join("") : '<tr><td colspan="7">Nenhum agrupamento por produto encontrado.</td></tr>';
  }

  const detalhesHint = document.getElementById("vendasRelDetalhesHint");
  if (detalhesHint) {
    if (!vendedorFiltro) {
      detalhesHint.textContent = "Selecione um vendedor para ver as linhas do relatorio.";
    } else if (payload?.detalhes_limitados) {
      detalhesHint.textContent = "Mostrando as primeiras linhas do vendedor filtrado.";
    } else {
      detalhesHint.textContent = `Detalhes carregados para ${vendedorFiltro}.`;
    }
  }

  const detalhesBody = document.getElementById("vendasRelDetalhesBody");
  if (detalhesBody) {
    detalhesBody.innerHTML = detalhes.length ? detalhes.map((item) => `
      <tr>
        <td>${_escHtml(item.data || "-")}</td>
        <td>${_escHtml(item.numero_nf || "-")}</td>
        <td>${_escHtml(item.cliente || "-")}</td>
        <td>${_escHtml(item.cidade || "-")}</td>
        <td>${_escHtml(item.produto || "-")}</td>
        <td>${_escHtml(_fmtNumVendas(item.quantidade, 3))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_venda))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_devolvido))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_liquido))}</td>
      </tr>
    `).join("") : '<tr><td colspan="9">Sem detalhes para exibir.</td></tr>';
  }
}

async function carregarRelatorioVendas(){
  const infoEl = document.getElementById("vendasRelArquivoInfo");
  if (infoEl) infoEl.textContent = "Carregando relatorios vendas...";

  const params = new URLSearchParams();
  const tipoRelatorio = "bonificacoes";
  const mes = document.getElementById("vendasRelMes")?.value || vendasState.mes || "";
  const vendedor = document.getElementById("vendasRelVendedor")?.value || "";
  const cliente = document.getElementById("vendasRelCliente")?.value || "";
  const dataInicio = document.getElementById("vendasRelDataInicio")?.value || "";
  const dataFim = document.getElementById("vendasRelDataFim")?.value || "";
  params.set("tipo_relatorio", tipoRelatorio);
  if (mes) params.set("mes", mes);
  if (vendedor) params.set("vendedor", vendedor);
  if (cliente) params.set("cliente", cliente);
  if (dataInicio) params.set("data_inicio", dataInicio);
  if (dataFim) params.set("data_fim", dataFim);
  if (vendedor) params.set("limite", "300");

  const resp = await apiFetch(`/api/vendas/relatorio?${params.toString()}`);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (infoEl) infoEl.textContent = data?.erro || "Falha ao carregar relatorio de vendas.";
    if (resp.status !== 409) {
      alert(data?.erro || "Falha ao carregar relatorio de vendas.");
    }
    return;
  }
  renderRelatorioVendas(data || {});
}

function _vendasMesLabelTexto(valor) {
  const texto = String(valor || "").trim();
  const m = texto.match(/^(\d{4})-(\d{2})$/);
  if (!m) return texto || "-";
  const meses = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
  const idx = Math.max(1, Math.min(12, Number(m[2]) || 1)) - 1;
  return `${meses[idx]} ${m[1]}`;
}

function _vendasPreencherSelectMeses(meses, selected = "", selectId = "vendasRelMes") {
  const select = document.getElementById(selectId);
  if (!select) return;
  const current = String(selected || select.value || "");
  const values = Array.isArray(meses) ? meses : [];
  const fallbackValues = values.length ? values : (current ? [current] : []);
  const options = ['<option value="">Último mês processado</option>'].concat(
    fallbackValues.map((mes) => `<option value="${_escHtml(mes)}">${_escHtml(_vendasMesLabelTexto(mes))}</option>`)
  );
  select.innerHTML = options.join("");
  select.value = fallbackValues.includes(current) ? current : (fallbackValues.length ? fallbackValues[fallbackValues.length - 1] : "");
}

function _vendasPreencherSelectVendedores(vendedores, selected = "", selectId = "vendasRelVendedor") {
  const select = document.getElementById(selectId);
  if (!select) return;
  const current = String(selected || select.value || "");
  const options = ['<option value="">Todos os vendedores</option>'].concat(
    (Array.isArray(vendedores) ? vendedores : []).map((item) => {
      const key = item?.chave || "";
      const label = [item?.codigo, item?.nome].filter(Boolean).join(" - ") || "Sem vendedor";
      return `<option value="${_escHtml(key)}">${_escHtml(label)}</option>`;
    })
  );
  select.innerHTML = options.join("");
  select.value = (Array.isArray(vendedores) && vendedores.some((item) => String(item?.chave || "") === current)) ? current : "";
}

function _vendasResumoBonificacoesCards(resumo = {}, payload = {}) {
  const mes = payload?.mes_atual || "";
  return [
    ["Mês", _vendasMesLabelTexto(mes)],
    ["Itens", _fmtNumVendas(resumo.itens)],
    ["Vendedores", _fmtNumVendas(resumo.vendedores)],
    ["PDV", _fmtNumVendas(resumo.clientes)],
    ["Notas", _fmtNumVendas(resumo.notas)],
    ["Venda", _fmtMoneyVendas(resumo.valor_venda)],
    ["Bonificação", _fmtMoneyVendas(resumo.bonificacao)],
    ["% Bonif.", `${_fmtNumVendas(resumo.percentual_bonificacao || resumo.percentual || 0, 2)}%`],
    ["Média %", `${_fmtNumVendas(resumo.media_percentual_bonificacao || 0, 2)}%`],
    ["Líquido", _fmtMoneyVendas(resumo.valor_liquido)],
  ];
}

function _vendasRenderGrupoBonificacoes(resumoGrupos = []) {
  if (!Array.isArray(resumoGrupos) || !resumoGrupos.length) {
    return "";
  }
  const labelGrupo = (item) => {
    const grupo = String(item?.grupo || "").toLowerCase();
    if (grupo === "todos") return "Rio Branco";
    if (grupo === "rio_branco") return "CLT";
    if (grupo === "autonomos") return "Autônomos";
    return item?.nome || item?.grupo || "-";
  };
  return `
    <table>
      <thead>
        <tr>
          <th>Grupo</th>
          <th>Itens</th>
          <th>PDV</th>
          <th>Notas</th>
          <th>Venda</th>
          <th>Bonificação</th>
          <th>% Bonif.</th>
          <th>Líquido</th>
        </tr>
      </thead>
      <tbody>
        ${resumoGrupos.map((item) => `
          <tr>
            <td>${_escHtml(labelGrupo(item))}</td>
            <td>${_escHtml(_fmtNumVendas(item.itens))}</td>
            <td>${_escHtml(_fmtNumVendas(item.clientes))}</td>
            <td>${_escHtml(_fmtNumVendas(item.notas))}</td>
            <td>${_escHtml(_fmtMoneyVendas(item.valor_venda))}</td>
            <td>${_escHtml(_fmtMoneyVendas(item.bonificacao))}</td>
            <td>${_escHtml(`${_fmtNumVendas(item.percentual_bonificacao || 0, 2)}%`)}</td>
            <td>${_escHtml(_fmtMoneyVendas(item.valor_liquido))}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function _vendasResumoMixEmbalagensCards(resumo = {}, payload = {}) {
  const mes = payload?.mes_atual || "";
  return [
    ["Mês", _vendasMesLabelTexto(mes)],
    ["PDVs", _fmtNumVendas(resumo.pdvs)],
    ["6 grupos", _fmtNumVendas(resumo.pdvs_6)],
    ["5 grupos", _fmtNumVendas(resumo.pdvs_5)],
    ["4 grupos", _fmtNumVendas(resumo.pdvs_4)],
    ["3 grupos", _fmtNumVendas(resumo.pdvs_3)],
    ["2 grupos", _fmtNumVendas(resumo.pdvs_2)],
    ["1 grupo", _fmtNumVendas(resumo.pdvs_1)],
    ["Média grupos/PDV", _fmtNumVendas(resumo.media_grupos_por_pdv || 0, 2)],
  ];
}

function _vendasRenderMixEmbalagensFaixas(faixas = [], bodyId = "vendasMixFaixasBody") {
  const body = document.getElementById(bodyId);
  if (!body) return;
  body.innerHTML = Array.isArray(faixas) && faixas.length ? faixas.map((item) => `
    <tr>
      <td>${_escHtml(item.faixa || "-")}</td>
      <td>${_escHtml(_fmtNumVendas(item.pdvs))}</td>
      <td>${_escHtml(`${_fmtNumVendas(item.percentual || 0, 2)}%`)}</td>
    </tr>
  `).join("") : '<tr><td colspan="3">Nenhum PDV encontrado no período.</td></tr>';
}

function _vendasRenderMixEmbalagensDetalhe(item = null, hintId = "vendasMixDetalheHint", bodyId = "vendasMixDetalheBody") {
  const hint = document.getElementById(hintId);
  const body = document.getElementById(bodyId);
  if (!hint || !body) return;
  if (!item) {
    hint.textContent = "Selecione um PDV para ver exatamente quais grupos ele usou no mês.";
    body.innerHTML = '<tr><td colspan="6">Nenhum PDV selecionado.</td></tr>';
    return;
  }
  hint.textContent = `PDV ${item.cliente || "-"} no mês selecionado.`;
  body.innerHTML = `
    <tr>
      <td>${_escHtml(item.cliente || "-")}</td>
      <td>${_escHtml(item.cidade || "-")}</td>
      <td>${_escHtml(item.vendedor || item.vendedores_lista || "-")}</td>
      <td>${_escHtml(_fmtNumVendas(item.qtd_grupos))}</td>
      <td>${_escHtml(item.faixa_grupos || "-")}</td>
      <td>${_escHtml(item.grupos_lista || "-")}</td>
    </tr>
  `;
}

function selecionarClienteRelatorioMixEmbalagens(chave = "") {
  const select = document.getElementById("vendasMixCliente");
  if (select) select.value = chave || "";
  carregarRelatorioMixEmbalagens().catch(() => {});
}

function limparFiltrosRelatorioMixEmbalagens() {
  const mes = document.getElementById("vendasMixMes");
  const vendedor = document.getElementById("vendasMixVendedor");
  const cliente = document.getElementById("vendasMixCliente");
  if (mes) mes.value = "";
  if (vendedor) vendedor.value = "";
  if (cliente) cliente.value = "";
  carregarRelatorioMixEmbalagens().catch(() => {});
}

function renderRelatorioMixEmbalagens(payload = {}) {
  vendasState.lastPayload = payload;
  vendasState.tipoRelatorio = "grupos_embalagem";
  vendasState.mes = payload?.mes_atual || payload?.filtros?.mes || "";

  const mesAtual = payload?.mes_atual || payload?.filtros?.mes || "";
  const meses = Array.isArray(payload?.meses_disponiveis) ? payload.meses_disponiveis : [];
  const vendedores = Array.isArray(payload?.vendedores) ? payload.vendedores : [];
  const clientes = Array.isArray(payload?.clientes) ? payload.clientes : [];
  const clientesDisponiveis = Array.isArray(payload?.clientes_disponiveis) ? payload.clientes_disponiveis : [];
  const faixas = Array.isArray(payload?.resumo_faixas) ? payload.resumo_faixas : [];
  const resumo = payload?.resumo_geral || {};
  const detalhe = payload?.detalhe_pdv || null;
  const vendedorFiltro = payload?.filtros?.vendedor || document.getElementById("vendasMixVendedor")?.value || "";
  const clienteFiltro = payload?.filtros?.cliente || document.getElementById("vendasMixCliente")?.value || "";
  const pdvLabel = detalhe?.cliente || clienteFiltro;
  const arquivo = payload?.arquivo || {};

  _vendasPreencherSelectMeses(meses, mesAtual, "vendasMixMes");
  _vendasPreencherSelectVendedores(vendedores, vendedorFiltro, "vendasMixVendedor");
  _vendasPreencherSelectClientes(clientesDisponiveis, clienteFiltro, "vendasMixCliente", "Todos os PDVs");

  const infoEl = document.getElementById("vendasRelArquivoInfo");
  if (infoEl) {
    const parts = [
      `Arquivo: ${arquivo.nome || "Base atual"}`,
      `Atualizado em: ${arquivo.atualizado_em || "-"}`,
      `Relatorio: Grupos Embalagem`,
      `Mês: ${_vendasMesLabelTexto(mesAtual)}`,
    ];
    if (vendedorFiltro) parts.push(`Vendedor: ${vendedorFiltro}`);
    if (clienteFiltro) parts.push(`PDV: ${pdvLabel}`);
    infoEl.textContent = parts.join(" | ");
  }

  const cardsEl = document.getElementById("vendasMixResumoCards");
  if (cardsEl) {
    cardsEl.innerHTML = _renderCardsVendasResumo(_vendasResumoMixEmbalagensCards(resumo, payload));
  }

  _vendasRenderMixEmbalagensFaixas(faixas, "vendasMixFaixasBody");

  const clientesBody = document.getElementById("vendasMixClientesBody");
  if (clientesBody) {
    clientesBody.innerHTML = clientes.length ? clientes.map((item) => `
      <tr onclick="selecionarClienteRelatorioMixEmbalagens('${_escJsString(item.chave || "")}')">
        <td>${_escHtml(item.cliente || "-")}</td>
        <td>${_escHtml(item.cidade || "-")}</td>
        <td>${_escHtml(item.vendedor || item.vendedores_lista || "-")}</td>
        <td>${_escHtml(_fmtNumVendas(item.qtd_grupos))}</td>
        <td>${_escHtml(item.faixa_grupos || "-")}</td>
        <td>${_escHtml(_fmtNumVendas(item.itens))}</td>
        <td>${_escHtml(_fmtNumVendas(item.notas))}</td>
        <td>${_escHtml(item.grupos_lista || "-")}</td>
      </tr>
    `).join("") : '<tr><td colspan="8">Nenhum PDV encontrado para os filtros atuais.</td></tr>';
  }

  _vendasRenderMixEmbalagensDetalhe(detalhe);
}

async function carregarRelatorioMixEmbalagens() {
  const infoEl = document.getElementById("vendasRelArquivoInfo");
  if (infoEl) infoEl.textContent = "Carregando grupos embalagem...";

  const params = new URLSearchParams();
  const mes = document.getElementById("vendasMixMes")?.value || vendasState.mes || "";
  const vendedor = document.getElementById("vendasMixVendedor")?.value || "";
  const cliente = document.getElementById("vendasMixCliente")?.value || "";
  params.set("tipo_relatorio", "grupos_embalagem");
  if (mes) params.set("mes", mes);
  if (vendedor) params.set("vendedor", vendedor);
  if (cliente) params.set("cliente", cliente);

  const resp = await apiFetch(`/api/vendas/relatorio?${params.toString()}`);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const erro = data?.erro || "Falha ao carregar relatorio de grupos embalagem.";
    if (infoEl) infoEl.textContent = erro;
    if (resp.status !== 409) alert(erro);
    return;
  }
  renderRelatorioMixEmbalagens(data || {});
}

async function recarregarRelatorioVendasAtual() {
  const modo = String(window.__vendasRelatorioModo || vendasState.tipoRelatorio || "bonificacoes").toLowerCase();
  if (modo === "variacao_preco") {
    await carregarRelatorioVariacaoPreco();
    return;
  }
  if (modo === "mix_embalagens" || modo === "grupos_embalagem") {
    await carregarRelatorioMixEmbalagens();
    return;
  }
  await carregarRelatorioVendas();
}

function setVendasRelatorioModo(modo){
  const raw = String(modo || "bonificacoes").toLowerCase();
  const valor = raw === "variacao_preco"
    ? "variacao_preco"
    : raw === "mix_embalagens" || raw === "grupos_embalagem"
    ? "grupos_embalagem"
    : "bonificacoes";
  window.__vendasRelatorioModo = valor;
  vendasState.tipoRelatorio = valor;
  const viewBon = document.getElementById("vendasViewRelatorio");
  const viewVar = document.getElementById("vendasViewRelatorioVariacao");
  const viewMix = document.getElementById("vendasViewRelatorioMix");
  const tabBon = document.getElementById("vendasRelTabBonificacoes");
  const tabVar = document.getElementById("vendasRelTabVariacao");
  const tabMix = document.getElementById("vendasRelTabMix");
  if (viewBon) viewBon.classList.toggle("hidden", valor !== "bonificacoes");
  if (viewVar) viewVar.classList.toggle("hidden", valor !== "variacao_preco");
  if (viewMix) viewMix.classList.toggle("hidden", valor !== "grupos_embalagem");
  if (tabBon) tabBon.classList.toggle("active", valor === "bonificacoes");
  if (tabVar) tabVar.classList.toggle("active", valor === "variacao_preco");
  if (tabMix) tabMix.classList.toggle("active", valor === "grupos_embalagem");
  recarregarRelatorioVendasAtual().catch(() => {});
}

function _vendasResumoVariacaoCards(resumo = {}, payload = {}) {
  const mes = payload?.mes_atual || "";
  return [
    ["Mês", _vendasMesLabelTexto(mes)],
    ["Linhas válidas", _fmtNumVendas(resumo.itens)],
    ["Vendedores", _fmtNumVendas(resumo.vendedores)],
    ["Grupos", _fmtNumVendas(resumo.grupos)],
    ["Variações", _fmtNumVendas(resumo.variacoes)],
    ["Preços distintos", _fmtNumVendas(resumo.precos_distintos)],
    ["Clientes", _fmtNumVendas(resumo.clientes)],
    ["Cidades", _fmtNumVendas(resumo.cidades)],
    ["Preço mín.", _fmtMoneyVendas(resumo.preco_min)],
    ["Preço máx.", _fmtMoneyVendas(resumo.preco_max)],
    ["Diferença", _fmtMoneyVendas(resumo.variacao_absoluta || resumo.variacao_valor)],
    ["Dif. %", `${_fmtNumVendas(resumo.variacao_percentual || 0, 2)}%`],
  ];
}

function _vendasRenderGrupoVariacao(resumoGrupos = []) {
  if (!Array.isArray(resumoGrupos) || !resumoGrupos.length) {
    return "";
  }
  const labelGrupo = (item) => {
    const grupo = String(item?.grupo || "").toLowerCase();
    if (grupo === "todos") return "Todos";
    if (grupo === "rio_branco") return "Rio Branco";
    if (grupo === "autonomos") return "Autônomos";
    return item?.nome || item?.grupo || "-";
  };
  return `
    <table>
      <thead>
        <tr>
          <th>Grupo</th>
          <th>Itens</th>
          <th>Grupos</th>
          <th>Variações</th>
          <th>Preços</th>
          <th>Clientes</th>
          <th>Cidades</th>
          <th>Min</th>
          <th>Max</th>
          <th>Dif.</th>
          <th>Dif.%</th>
        </tr>
      </thead>
      <tbody>
        ${resumoGrupos.map((item) => `
          <tr>
            <td>${_escHtml(labelGrupo(item))}</td>
            <td>${_escHtml(_fmtNumVendas(item.itens))}</td>
            <td>${_escHtml(_fmtNumVendas(item.grupos))}</td>
            <td>${_escHtml(_fmtNumVendas(item.variacoes))}</td>
            <td>${_escHtml(_fmtNumVendas(item.precos_distintos))}</td>
            <td>${_escHtml(_fmtNumVendas(item.clientes))}</td>
            <td>${_escHtml(_fmtNumVendas(item.cidades))}</td>
            <td>${_escHtml(_fmtMoneyVendas(item.preco_min))}</td>
            <td>${_escHtml(_fmtMoneyVendas(item.preco_max))}</td>
            <td>${_escHtml(_fmtMoneyVendas(item.variacao_absoluta || item.variacao_valor))}</td>
            <td>${_escHtml(`${_fmtNumVendas(item.variacao_percentual || 0, 2)}%`)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function _vendasRenderVariacoesTabela(variacoes = []) {
  if (!Array.isArray(variacoes) || !variacoes.length) {
    return '<tr><td colspan="12">Nenhuma variação de preço encontrada no mês selecionado.</td></tr>';
  }
  return variacoes.map((item) => `
    <tr onclick="selecionarVendedorRelatorioVariacao('${_escJsString(item.vendedor_key || "")}')">
      <td>${_escHtml(item.codigo || "-")}</td>
      <td>${_escHtml(item.vendedor || "-")}</td>
      <td>${_escHtml(item.grupo || "-")}</td>
      <td>${_escHtml(item.produtos || "-")}</td>
      <td>${_escHtml(item.precos || "-")}</td>
      <td>${_escHtml(_fmtMoneyVendas(item.preco_min))}</td>
      <td>${_escHtml(_fmtMoneyVendas(item.preco_max))}</td>
      <td>${_escHtml(_fmtMoneyVendas(item.variacao_valor))}</td>
      <td>${_escHtml(`${_fmtNumVendas(item.variacao_percentual || 0, 2)}%`)}</td>
      <td>${_escHtml(item.cidades_lista || "-")}</td>
      <td>${_escHtml(item.clientes_lista || "-")}</td>
      <td>${_escHtml(_fmtNumVendas(item.itens))}</td>
    </tr>
  `).join("");
}

function _vendasRenderDetalheVariacao(detalhes = [], vendedorFiltro = "", mesAtual = "", hintId = "vendasRelDetalhesHint", bodyId = "vendasRelDetalhesBody") {
  const detalheHint = document.getElementById(hintId);
  if (detalheHint) {
    if (vendedorFiltro) {
      detalheHint.textContent = `Mostrando as linhas de preço para ${vendedorFiltro} no mês ${_vendasMesLabelTexto(mesAtual)}.`;
    } else {
      detalheHint.textContent = "Selecione um vendedor para ver as linhas de preço e a origem da variação.";
    }
  }
  const detalhesBody = document.getElementById(bodyId);
  if (detalhesBody) {
    detalhesBody.innerHTML = detalhes.length ? detalhes.map((item) => `
      <tr>
        <td>${_escHtml(item.data || "-")}</td>
        <td>${_escHtml(item.numero_nf || "-")}</td>
        <td>${_escHtml(item.cliente || "-")}</td>
        <td>${_escHtml(item.cidade || "-")}</td>
        <td>${_escHtml(item.grupo || "-")}</td>
        <td>${_escHtml(item.produto || "-")}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.preco_aplicado))}</td>
        <td>${_escHtml(_fmtNumVendas(item.quantidade, 3))}</td>
        <td>${_escHtml(_fmtMoneyVendas(item.valor_venda))}</td>
        <td>${_escHtml(item.tipo_operacao || "-")}</td>
      </tr>
    `).join("") : `<tr><td colspan="10">${vendedorFiltro ? "Sem linhas para exibir." : "Selecione vendedor para carregar os detalhes."}</td></tr>`;
  }
}

const VENDAS_RELATORIO_CACHE_KEY = "riobranco.vendas.bonificacoes.last_payload.v3";
const VENDAS_RELATORIO_ACTIVE_CACHE_KEY = "riobranco.vendas.bonificacoes.active_cache_id.v3";
const VENDAS_VARIACAO_CACHE_KEY = "riobranco.vendas.variacao_preco.last_payload.v3";
const VENDAS_VARIACAO_ACTIVE_CACHE_KEY = "riobranco.vendas.variacao_preco.active_cache_id.v3";

function _vendasCacheLocalMigrarLimparAntigo() {
  try {
    [
      "riobranco.vendas.bonificacoes.last_payload.v2",
      "riobranco.vendas.bonificacoes.active_cache_id.v2",
      "riobranco.vendas.variacao_preco.last_payload.v2",
      "riobranco.vendas.variacao_preco.active_cache_id.v2",
      "riobranco.vendas.dashboard.last_payload.v2",
      "riobranco.vendas.dashboard.active_cache_id.v2",
      "riobranco.vendas.dashboard.last_payload.v3",
      "riobranco.vendas.dashboard.active_cache_id.v3",
    ].forEach((key) => localStorage.removeItem(key));
  } catch {}
}

_vendasCacheLocalMigrarLimparAntigo();

function _vendasCacheLocalSalvar(payload = {}) {
  try {
    _vendasCacheLocalMigrarLimparAntigo();
    const clean = {
      __cache_local_schema: 3,
      cache: { id: payload?.cache?.id || "" },
      cache_entry: { id: payload?.cache_entry?.id || "" },
      relatorio_tipo: "bonificacoes",
      mes_atual: _asStr(payload?.mes_atual || ""),
      filtro_vendedor: _asStr(payload?.filtros?.vendedor || payload?.filtro_vendedor || ""),
      filtro_cliente: _asStr(payload?.filtros?.cliente || payload?.filtro_cliente || ""),
      atualizado_em: _asStr(payload?.arquivo?.atualizado_em || ""),
    };
    localStorage.setItem(VENDAS_RELATORIO_CACHE_KEY, JSON.stringify(clean));
    const cacheId = clean?.cache?.id || clean?.cache_entry?.id || "";
    if (cacheId) {
      localStorage.setItem(VENDAS_RELATORIO_ACTIVE_CACHE_KEY, String(cacheId));
    }
  } catch {}
}

function _vendasCacheLocalObter() {
  try {
    const raw = localStorage.getItem(VENDAS_RELATORIO_CACHE_KEY);
    if (!raw) return null;
    const payload = JSON.parse(raw);
    return payload && typeof payload === "object" ? payload : null;
  } catch {
    return null;
  }
}

function _vendasCacheLocalAtualizarAtivo(cacheId = "") {
  try {
    const texto = String(cacheId || "").trim();
    if (texto) {
      localStorage.setItem(VENDAS_RELATORIO_ACTIVE_CACHE_KEY, texto);
    } else {
      localStorage.removeItem(VENDAS_RELATORIO_ACTIVE_CACHE_KEY);
    }
  } catch {}
}

function _vendasConfigMonitorCancelar(){
  if (vendasConfigMonitorTimer) {
    clearTimeout(vendasConfigMonitorTimer);
    vendasConfigMonitorTimer = null;
  }
}

function _vendasConfigTemImportando(imports){
  const rows = Array.isArray(imports) ? imports : [];
  return rows.some((item) => _asStr(item?.status) === "importando");
}

function _vendasConfigTemErro(imports){
  const rows = Array.isArray(imports) ? imports : [];
  return rows.some((item) => _asStr(item?.status) === "erro");
}

function _vendasConfigQtdProntos(imports){
  const rows = Array.isArray(imports) ? imports : [];
  return rows.filter((item) => _asBool(item?.cache_exists, false) && _asStr(item?.status) !== "importando").length;
}

function _vendasConfigAgendarMonitor(importando){
  vendasConfigMonitorAtivo = !!importando;
  _vendasConfigMonitorCancelar();
  if (!importando) return;
  vendasConfigMonitorTimer = setTimeout(() => {
    vendasConfigMonitorTimer = null;
    carregarConfigVendas().catch(() => {});
  }, 3000);
}

function _vendasConfigAtualizarIndicador(cfg = {}, fonte = {}, imports = [], meta = {}){
  const statusEl = document.getElementById("vendasConfigStatus");
  const importando = !!meta?.processando_importacao || _vendasConfigTemImportando(imports);
  const erro = _vendasConfigTemErro(imports);
  const prontos = _vendasConfigQtdProntos(imports);
  const textoFonte = _asStr(meta?.mensagem || fonte?.message || "");
  const textoBase = cfg?.updated_at
    ? `Atualizado em ${_chatDataLabel(cfg.updated_at)}`
    : "Configuracao pronta para uso.";

  let texto = textoBase;
  let classe = "is-idle";
  if (importando) {
    classe = "is-running";
    texto = textoFonte || "Importacao em andamento. A tela sera atualizada automaticamente.";
  } else if (erro) {
    classe = "is-error";
    texto = textoFonte || "Ultima importacao com erro. Verifique a fonte e tente novamente.";
  } else if (prontos > 0) {
    classe = "is-success";
    texto = textoFonte || `${prontos} cache(s) pronto(s) para uso.`;
  } else if (textoFonte) {
    texto = textoFonte;
  }

  if (statusEl) {
    statusEl.className = `hint vendas-config-status ${classe}`;
    statusEl.innerHTML = `
      <span class="vendas-config-status-dot"></span>
      <span>${_escHtml(texto)}</span>
    `;
  }

  _vendasConfigAgendarMonitor(importando);
}

function _vendasCacheLocalRestaurar() {
  const payload = _vendasCacheLocalObter();
  if (!payload) return false;
  if (_asInt(payload?.__cache_local_schema, 0) !== 3) {
    localStorage.removeItem(VENDAS_RELATORIO_CACHE_KEY);
    localStorage.removeItem(VENDAS_RELATORIO_ACTIVE_CACHE_KEY);
    return false;
  }
  const cacheId = String(payload?.cache?.id || payload?.cache_entry?.id || "").trim();
  const cacheAtivo = String(localStorage.getItem(VENDAS_RELATORIO_ACTIVE_CACHE_KEY) || "").trim();
  const tipoRelatorio = String(payload?.relatorio_tipo || "").replace(/-/g, "_");
  const meses = Array.isArray(payload?.meses_disponiveis) ? payload.meses_disponiveis : [];
  const vendedores = Array.isArray(payload?.vendedores) ? payload.vendedores : Array.isArray(payload?.vendedores_disponiveis) ? payload.vendedores_disponiveis : [];
  if (tipoRelatorio && !["bonificacoes", "resumo"].includes(tipoRelatorio)) {
    localStorage.removeItem(VENDAS_RELATORIO_CACHE_KEY);
    localStorage.removeItem(VENDAS_RELATORIO_ACTIVE_CACHE_KEY);
    return false;
  }
  if (!meses.length || !vendedores.length) return false;
  if (cacheAtivo && cacheId && cacheAtivo !== cacheId) {
    return false;
  }
  if (!cacheId) {
    return false;
  }
  renderRelatorioVendas({ ...(payload || {}), __cache_local_restaurado: true });
  return true;
}

function _vendasVariacaoCacheLocalSalvar(payload = {}) {
  try {
    _vendasCacheLocalMigrarLimparAntigo();
    const clean = {
      __cache_local_schema: 3,
      cache: { id: payload?.cache?.id || "" },
      cache_entry: { id: payload?.cache_entry?.id || "" },
      relatorio_tipo: "variacao_preco",
      mes_atual: _asStr(payload?.mes_atual || ""),
      filtro_vendedor: _asStr(payload?.filtros?.vendedor || payload?.filtro_vendedor || ""),
      atualizado_em: _asStr(payload?.arquivo?.atualizado_em || ""),
    };
    localStorage.setItem(VENDAS_VARIACAO_CACHE_KEY, JSON.stringify(clean));
    const cacheId = clean?.cache?.id || clean?.cache_entry?.id || "";
    if (cacheId) {
      localStorage.setItem(VENDAS_VARIACAO_ACTIVE_CACHE_KEY, String(cacheId));
    }
  } catch {}
}

function _vendasVariacaoCacheLocalObter() {
  try {
    const raw = localStorage.getItem(VENDAS_VARIACAO_CACHE_KEY);
    if (!raw) return null;
    const payload = JSON.parse(raw);
    return payload && typeof payload === "object" ? payload : null;
  } catch {
    return null;
  }
}

function _vendasVariacaoCacheLocalAtualizarAtivo(cacheId = "") {
  try {
    const texto = String(cacheId || "").trim();
    if (texto) {
      localStorage.setItem(VENDAS_VARIACAO_ACTIVE_CACHE_KEY, texto);
    } else {
      localStorage.removeItem(VENDAS_VARIACAO_ACTIVE_CACHE_KEY);
    }
  } catch {}
}

function _vendasVariacaoCacheLocalRestaurar() {
  const payload = _vendasVariacaoCacheLocalObter();
  if (!payload) return false;
  if (_asInt(payload?.__cache_local_schema, 0) !== 3) {
    localStorage.removeItem(VENDAS_VARIACAO_CACHE_KEY);
    localStorage.removeItem(VENDAS_VARIACAO_ACTIVE_CACHE_KEY);
    return false;
  }
  const meses = Array.isArray(payload?.meses_disponiveis) ? payload.meses_disponiveis : [];
  const vendedores = Array.isArray(payload?.vendedores) ? payload.vendedores : Array.isArray(payload?.vendedores_disponiveis) ? payload.vendedores_disponiveis : [];
  if (!meses.length || !vendedores.length) return false;
  const cacheId = String(payload?.cache?.id || payload?.cache_entry?.id || "").trim();
  const cacheAtivo = String(localStorage.getItem(VENDAS_VARIACAO_ACTIVE_CACHE_KEY) || "").trim();
  const tipoRelatorio = String(payload?.relatorio_tipo || "").replace(/-/g, "_");
  if (tipoRelatorio && !["variacao_preco", "variacao_venda"].includes(tipoRelatorio)) {
    return false;
  }
  if (cacheAtivo && cacheId && cacheAtivo !== cacheId) {
    return false;
  }
  if (!cacheId) {
    return false;
  }
  renderRelatorioVariacaoPreco({ ...(payload || {}), __cache_local_restaurado: true });
  return true;
}

function selecionarVendedorRelatorioVariacao(chave = "") {
  const select = document.getElementById("vendasVarVendedor");
  if (select) select.value = chave || "";
  carregarRelatorioVariacaoPreco().catch(() => {});
}

function renderRelatorioVariacaoPreco(payload = {}) {
  const filtros = payload?.filtros || {};
  const mesAtual = payload?.mes_atual || filtros?.mes || "";
  vendasState.mes = mesAtual;
  const meses = Array.isArray(payload?.meses_disponiveis) ? payload.meses_disponiveis : [];
  const vendedores = Array.isArray(payload?.vendedores) ? payload.vendedores : Array.isArray(payload?.vendedores_disponiveis) ? payload.vendedores_disponiveis : [];
  const variacoes = Array.isArray(payload?.variacoes) ? payload.variacoes : [];
  const detalhes = Array.isArray(payload?.detalhes_vendedor) ? payload.detalhes_vendedor : [];
  const resumo = payload?.resumo_geral || {};
  const resumoGrupos = Array.isArray(payload?.resumo_grupos) ? payload.resumo_grupos : [];
  const arquivo = payload?.arquivo || {};
  const vendedorFiltro = filtros?.vendedor || document.getElementById("vendasVarVendedor")?.value || "";
  const cacheId = payload?.cache?.id || payload?.cache_entry?.id || "";

  vendasState.tipoRelatorio = "variacao_preco";
  _vendasPreencherSelectMeses(meses, mesAtual, "vendasVarMes");
  _vendasPreencherSelectVendedores(vendedores, vendedorFiltro, "vendasVarVendedor");
  atualizarVisibilidadeFiltrosRelatorioVendas();

  const infoEl = document.getElementById("vendasVarArquivoInfo");
  if (infoEl) {
    const parts = [
      "Cache remoto carregado",
      `Arquivo: ${arquivo.nome || "Base atual"}`,
        `Atualizado em: ${arquivo.atualizado_em || "-"}`,
        `Mês: ${_vendasMesLabelTexto(mesAtual)}`,
    ];
    if (vendedorFiltro) parts.push(`Vendedor: ${vendedorFiltro}`);
    if (cacheId) parts.push(`Cache: ${cacheId}`);
    infoEl.textContent = parts.join(" | ");
  }

  const cardsEl = document.getElementById("vendasVarResumoCards");
  if (cardsEl) {
    cardsEl.innerHTML = _renderCardsVendasResumo(_vendasResumoVariacaoCards(resumo, payload));
  }

  const grupoResumoEl = document.getElementById("vendasVarGrupoResumo");
  if (grupoResumoEl) {
    grupoResumoEl.innerHTML = _vendasRenderGrupoVariacao(resumoGrupos);
  }

  const vendedoresBody = document.getElementById("vendasVarVendedoresBody");
  if (vendedoresBody) {
    vendedoresBody.innerHTML = _vendasRenderVariacoesTabela(variacoes);
  }

  _vendasRenderDetalheVariacao(detalhes, vendedorFiltro, mesAtual, "vendasVarDetalhesHint", "vendasVarDetalhesBody");
}

async function carregarRelatorioVariacaoPreco() {
  const infoEl = document.getElementById("vendasVarArquivoInfo");
  if (infoEl) infoEl.textContent = "Carregando relatorios vendas...";

  const params = new URLSearchParams();
  const mes = document.getElementById("vendasVarMes")?.value || vendasState.mes || "";
  const vendedor = document.getElementById("vendasVarVendedor")?.value || "";
  if (mes) params.set("mes", mes);
  if (vendedor) params.set("vendedor", vendedor);
  params.set("tipo_relatorio", "variacao_preco");

  const resp = await apiFetch(`/api/vendas/relatorio?${params.toString()}`);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const erro = data?.erro || "Falha ao carregar relatorio de variacao de preco.";
    if (infoEl) infoEl.textContent = erro;
    if (resp.status !== 409) {
      alert(erro);
    }
    return;
  }
  renderRelatorioVariacaoPreco(data || {});
}

function limparFiltrosRelatorioVendas() {
  const mes = document.getElementById("vendasRelMes");
  const vendedor = document.getElementById("vendasRelVendedor");
  const cliente = document.getElementById("vendasRelCliente");
  const dataInicio = document.getElementById("vendasRelDataInicio");
  const dataFim = document.getElementById("vendasRelDataFim");
  if (mes) mes.value = "";
  if (vendedor) vendedor.value = "";
  if (cliente) cliente.value = "";
  if (dataInicio) dataInicio.value = "";
  if (dataFim) dataFim.value = "";
  atualizarVisibilidadeFiltrosRelatorioVendas();
  agendarCarregarRelatorioVendas();
}

async function processarRelatoriosVendas() {
  const resumo = document.getElementById("vendasConfigResumo");
  if (resumo) resumo.textContent = "Processando cache dos relatórios de vendas...";
  const resp = await apiFetch("/api/vendas/cache/processar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const erro = data?.erro || "Falha ao processar relatórios.";
    if (resumo) resumo.textContent = erro;
    alert(erro);
    return;
  }
  if (resumo) resumo.textContent = data?.mensagem || "Todos dashboards e relatorios criados com sucesso.";
  await carregarConfigVendas();
  if (window.__vendasView === "relatorio") {
    await recarregarRelatorioVendasAtual().catch(() => {});
  }
  if (_dashboardVendasIsView(window.__dashView)) {
    await recarregarDashboardVendaAtual(true).catch(() => {});
  }
}

const MONITOR_APPS = {
  esxi: {
    label: "ESXi",
    url: () => "/monitor/esxi/",
    bootMonitor: true,
  },
  cameras: {
    label: "Cameras",
    url: () => "/monitor/cameras/",
    bootMonitor: true,
  },
  automacao: {
    label: "Automacao",
    url: () => "/monitor/automacao/",
    bootMonitor: true,
  },
  importar_xml: {
    label: "Importar XML",
    url: () => "/importar-xml/",
  },
  gestor_emails: {
    label: "Gestor de E-mails",
    url: () => "/gestor-emails/",
  },
};

function toggleMonitorSubmenu(ev){
  toggleExclusiveSubmenu(ev, () => openMonitorView(null, window.__monitorView || "esxi"));
}

function openMonitorView(ev, view){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const menu = document.querySelector('.menu-item.has-submenu[data-tab="monitor"]');
  window.__monitorView = MONITOR_APPS[view] ? view : "esxi";
  showTab("monitor", menu);

  document.querySelectorAll("#submenuMonitor .submenu-item").forEach((item) => item.classList.remove("active"));
  const active = document.querySelector(`#submenuMonitor .submenu-item[data-monitor-view="${window.__monitorView}"]`);
  if (active) active.classList.add("active");

  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && menu) menu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
}

function setMonitorView(view){
  window.__monitorView = MONITOR_APPS[view] ? view : "esxi";
  const config = MONITOR_APPS[window.__monitorView];
  const appLabel = document.getElementById("monitorAppLabel");
  const frame = document.getElementById("monitorFrame");
  const url = config?.url ? config.url() : "";
  if (appLabel) appLabel.textContent = config?.label || "Monitor";

  const loadFrame = () => {
    if (!frame || !url) return;
    if (frame.dataset.src !== url) {
      frame.src = url;
      frame.dataset.src = url;
    }
  };

  if (config?.bootMonitor) {
    apiFetch("/api/monitor_boot")
      .then(() => setTimeout(loadFrame, 350))
      .catch(() => loadFrame());
  } else {
    loadFrame();
  }
}

function openMonitorComunicacao(ev){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const menu = document.querySelector('.menu-item.has-submenu[data-tab="monitor"]');
  showTab("comunicacao", menu);

  document.querySelectorAll("#submenuMonitor .submenu-item").forEach((item) => item.classList.remove("active"));
  const active = document.querySelector('#submenuMonitor .submenu-item[data-monitor-view="comunicacao"]');
  if (active) active.classList.add("active");

  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && menu) menu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
}

function openMonitorExternal(){
  const view = window.__monitorView || "esxi";
  const config = MONITOR_APPS[view];
  const url = config?.url ? config.url() : "";
  if (!url) return;
  window.open(url, "_blank", "noopener");
}

function toggleConfigSubmenu(ev){
  toggleExclusiveSubmenu(ev, () => openConfigView(null, "status"));
}

function openConfigView(ev, view){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const menu = document.querySelector('.menu-item.has-submenu[data-tab="config"]');
  window.__configView = (view === "logs" || view === "cameras" || view === "sip" || view === "nfe" || view === "vendas") ? view : "status";
  showTab("config", menu);

  document.querySelectorAll("#submenuConfig .submenu-item").forEach(x=>x.classList.remove("active"));
  const map = { status: 0, logs: 1, cameras: 2, sip: 3, nfe: 4, vendas: 5 };
  const target = map[window.__configView] ?? 0;
  const items = document.querySelectorAll("#submenuConfig .submenu-item");
  if (items && items[target]) items[target].classList.add("active");

  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && menu) menu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
}

function openDocsPortal(ev){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const menu = document.querySelector('.menu-item.has-submenu[data-tab="config"]');
  closeOpenSubmenus();
  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && menu) menu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
  window.open("/docs/index.html", "_blank", "noopener");
}

async function carregarConfigCameras(){
  const body = document.getElementById("configCamerasBody");
  if (!body) return;
  const r = await apiFetch("/monitor/cameras/api/list");
  if (!r.ok) {
    body.innerHTML = `<tr><td colspan="4">Erro ao carregar cameras.</td></tr>`;
    return;
  }
  const data = await r.json().catch(() => ({}));
  const cams = Array.isArray(data?.cams) ? data.cams : [];
  if (!cams.length) {
    body.innerHTML = `<tr><td colspan="4">Nenhuma camera cadastrada.</td></tr>`;
    return;
  }
  body.innerHTML = cams.map((c) => {
    const origem = (String(c.mode || "").toLowerCase() === "rtsp")
      ? (c.rtsp || "-")
      : (c.hls || "-");
    return `
      <tr>
        <td>${_escHtml(c.name || c.id || "-")}</td>
        <td>${_escHtml(c.mode || "-")}</td>
        <td>${_escHtml(origem)}</td>
        <td>
          <button type="button" onclick="editarCameraConfig('${_escJsString(c.id || "")}')">Editar</button>
          <button type="button" onclick="excluirCameraConfig('${_escJsString(c.id || "")}')">Excluir</button>
        </td>
      </tr>
    `;
  }).join("");
}

function alternarModoNovaCameraConfig(){
  const modoEl = document.getElementById("configCameraNovoModo");
  const transportEl = document.getElementById("configCameraNovoTransport");
  const valorEl = document.getElementById("configCameraNovoValor");
  const hintEl = document.getElementById("configCameraNovoHint");
  const modo = String(modoEl?.value || "rtsp").toLowerCase();
  if (transportEl) transportEl.disabled = modo !== "rtsp";
  if (valorEl) {
    valorEl.placeholder = modo === "rtsp"
      ? "rtsp://usuario:senha@ip:554/..."
      : "https://servidor/cams/camera/live.m3u8";
  }
  if (hintEl) {
    hintEl.textContent = modo === "rtsp"
      ? "Cole a URL RTSP. O painel de cameras tenta tocar em TCP automaticamente para melhor estabilidade."
      : "Cole a URL HLS pronta (.m3u8) quando o stream ja vier convertido.";
  }
}

async function adicionarCameraConfig(){
  const nomeEl = document.getElementById("configCameraNovoNome");
  const modoEl = document.getElementById("configCameraNovoModo");
  const transportEl = document.getElementById("configCameraNovoTransport");
  const valorEl = document.getElementById("configCameraNovoValor");
  const nome = (nomeEl?.value || "").trim();
  const modo = String(modoEl?.value || "rtsp").trim().toLowerCase();
  const valor = (valorEl?.value || "").trim();
  const transport = String(transportEl?.value || "tcp").trim().toLowerCase();

  if (!nome || !valor) {
    alert("Preencha nome e origem da camera.");
    return;
  }
  if (!["rtsp", "hls"].includes(modo)) {
    alert("Modo de camera invalido.");
    return;
  }

  const resp = await apiFetch("/monitor/cameras/api/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: nome, mode: modo, value: valor, transport }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    alert(data?.error || "Erro ao adicionar camera.");
    return;
  }

  if (nomeEl) nomeEl.value = "";
  if (valorEl) valorEl.value = "";
  if (modoEl) modoEl.value = "rtsp";
  if (transportEl) transportEl.value = "tcp";
  alternarModoNovaCameraConfig();
  await Promise.all([carregarConfigCameras(), verificarStatus()]);
}

async function editarCameraConfig(id){
  const r = await apiFetch("/monitor/cameras/api/list");
  if (!r.ok) return alert("Nao foi possivel carregar cameras.");
  const data = await r.json().catch(() => ({}));
  const cams = Array.isArray(data?.cams) ? data.cams : [];
  const cam = cams.find((x) => String(x.id) === String(id));
  if (!cam) return alert("Camera nao encontrada.");

  const nome = prompt("Nome da camera:", cam.name || "") || "";
  if (!nome.trim()) return;

  const modoAtual = String(cam.mode || "").toLowerCase() === "hls" ? "hls" : "rtsp";
  const modo = (prompt("Modo (rtsp ou hls):", modoAtual) || modoAtual).trim().toLowerCase();
  if (!["rtsp", "hls"].includes(modo)) return alert("Modo invalido.");

  const valorAtual = modo === "rtsp" ? (cam.rtsp || "") : (cam.hls || "");
  const valor = prompt(`URL ${modo.toUpperCase()}:`, valorAtual || "") || "";
  if (!valor.trim()) return;

  let transport = cam.transport || "tcp";
  if (modo === "rtsp") {
    transport = (prompt("Transporte RTSP (tcp/udp):", transport) || transport).trim().toLowerCase();
    if (!["tcp", "udp"].includes(transport)) transport = "tcp";
  }

  const up = await apiFetch("/monitor/cameras/api/update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, name: nome.trim(), mode: modo, value: valor.trim(), transport }),
  });
  const j = await up.json().catch(() => ({}));
  if (!up.ok) return alert(j?.error || "Erro ao editar camera.");

  await Promise.all([carregarConfigCameras(), verificarStatus()]);
}

async function excluirCameraConfig(id){
  if (!confirm("Excluir esta camera?")) return;
  const r = await apiFetch("/monitor/cameras/api/remove", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) return alert(j?.error || "Erro ao excluir camera.");
  await Promise.all([carregarConfigCameras(), verificarStatus()]);
}

function _sipPerfilIds(prefix) {
  return {
    wsUrl: document.getElementById(`${prefix}WsUrl`),
    dominio: document.getElementById(`${prefix}Dominio`),
    registrar: document.getElementById(`${prefix}RegistrarServer`),
    outbound: document.getElementById(`${prefix}OutboundProxy`),
    prefixo: document.getElementById(`${prefix}PrefixoSaida`),
    callerIdTemplate: document.getElementById(`${prefix}CallerIdTemplate`),
    stun: document.getElementById(`${prefix}StunServers`),
    turnUrl: document.getElementById(`${prefix}TurnUrl`),
    turnUsuario: document.getElementById(`${prefix}TurnUsuario`),
    turnSenha: document.getElementById(`${prefix}TurnSenha`),
    autoRegister: document.getElementById(`${prefix}AutoRegister`),
  };
}

function _preencherPerfilSip(prefix, cfg = {}) {
  const els = _sipPerfilIds(prefix);
  if (els.wsUrl) els.wsUrl.value = cfg.ws_url || "";
  if (els.dominio) els.dominio.value = cfg.dominio || "";
  if (els.registrar) els.registrar.value = cfg.registrar_server || "";
  if (els.outbound) els.outbound.value = cfg.outbound_proxy || "";
  if (els.prefixo) els.prefixo.value = cfg.prefixo_saida || "";
  if (els.callerIdTemplate) els.callerIdTemplate.value = cfg.caller_id_template || "{nome} RioBranco";
  if (els.stun) els.stun.value = cfg.stun_servers || "";
  if (els.turnUrl) els.turnUrl.value = cfg.turn_url || "";
  if (els.turnUsuario) els.turnUsuario.value = cfg.turn_usuario || "";
  if (els.turnSenha) els.turnSenha.value = cfg.turn_senha || "";
  if (els.autoRegister) els.autoRegister.checked = cfg.auto_register !== false;
}

function _coletarPerfilSip(prefix) {
  const els = _sipPerfilIds(prefix);
  return {
    ws_url: (els.wsUrl?.value || "").trim(),
    dominio: (els.dominio?.value || "").trim(),
    registrar_server: (els.registrar?.value || "").trim(),
    outbound_proxy: (els.outbound?.value || "").trim(),
    prefixo_saida: (els.prefixo?.value || "").trim(),
    caller_id_template: (els.callerIdTemplate?.value || "").trim() || "{nome} RioBranco",
    stun_servers: (els.stun?.value || "").trim(),
    turn_url: (els.turnUrl?.value || "").trim(),
    turn_usuario: (els.turnUsuario?.value || "").trim(),
    turn_senha: (els.turnSenha?.value || "").trim(),
    auto_register: !!els.autoRegister?.checked,
  };
}

function alternarPerfilSipConfig() {
  const modo = document.getElementById("sipConfigModoAtivo")?.value || "freepbx";
  const sete = document.getElementById("sipPerfilSetevoip");
  const freepbx = document.getElementById("sipPerfilFreepbx");
  if (sete) sete.classList.toggle("hidden", modo !== "setevoip_direto");
  if (freepbx) freepbx.classList.toggle("hidden", modo !== "freepbx");
}

function preencherConfigSip(cfg = {}) {
  const resumo = document.getElementById("sipConfigResumo");
  const habilitado = document.getElementById("sipConfigHabilitado");
  const modo = document.getElementById("sipConfigModoAtivo");
  const modoAtivo = cfg.modo_ativo || "freepbx";

  if (habilitado) habilitado.checked = !!cfg.habilitado;
  if (modo) modo.value = modoAtivo;
  _preencherPerfilSip("sipSetevoip", cfg.setevoip_direto || {});
  _preencherPerfilSip("sipFreepbx", cfg.freepbx || {});
  alternarPerfilSipConfig();

  if (resumo) {
    const labelModo = modoAtivo === "setevoip_direto" ? "SeteVoIP Direto" : "FreePBX";
    resumo.textContent = cfg.updated_at
      ? `Ultima atualizacao: ${_chatDataLabel(cfg.updated_at)} | Modo ativo: ${labelModo}`
      : `Configuracao SIP pronta para preenchimento. Modo ativo: ${labelModo}`;
  }
}

async function carregarConfigSip() {
  const resumo = document.getElementById("sipConfigResumo");
  if (resumo) resumo.textContent = "Carregando configuracao SIP...";
  const resp = await apiFetch("/api/sip/config");
  if (!resp.ok) {
    if (resumo) resumo.textContent = "Erro ao carregar configuracao SIP.";
    return;
  }
  const cfg = await resp.json().catch(() => ({}));
  preencherConfigSip(cfg);
}

async function salvarConfigSip() {
  const payload = {
    habilitado: !!document.getElementById("sipConfigHabilitado")?.checked,
    modo_ativo: document.getElementById("sipConfigModoAtivo")?.value || "freepbx",
    setevoip_direto: _coletarPerfilSip("sipSetevoip"),
    freepbx: _coletarPerfilSip("sipFreepbx"),
  };

  const resp = await apiFetch("/api/sip/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    alert(data?.erro || "Erro ao salvar configuracao SIP.");
    return;
  }

  preencherConfigSip(data?.config || payload);
  await initSipClient(true).catch(() => {});
  atualizarEstadoSipChat();
}

async function sincronizarRamaisFreepbx() {
  const resumo = document.getElementById("sipConfigResumo");
  if (resumo) resumo.textContent = "Sincronizando ramais dos usuarios no FreePBX...";

  const resp = await apiFetch("/api/sip/freepbx/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ convert_legacy: true }),
  });
  const data = await resp.json().catch(() => ({}));

  if (!resp.ok) {
    const erro = data?.erro || "Erro ao sincronizar ramais no FreePBX.";
    if (resumo) resumo.textContent = erro;
    alert(erro);
    return;
  }

  const summary = data?.summary || {};
  const results = Array.isArray(data?.results) ? data.results : [];
  const conflitos = results.filter((item) => item?.status === "legacy_conflict");
  const ignorados = results.filter((item) => item?.status === "skipped");
  const erros = results.filter((item) => item?.status === "error");

  if (resumo) {
    resumo.textContent = [
      `FreePBX: ${summary.created || 0} criados`,
      `${summary.updated || 0} atualizados`,
      `${summary.converted || 0} convertidos`,
      `${summary.legacy_conflicts || 0} conflitos legados`,
      `${summary.errors || 0} erros`,
    ].join(" | ");
  }

  let mensagem = `Sincronizacao concluida.\nCriados: ${summary.created || 0}\nAtualizados: ${summary.updated || 0}\nConvertidos: ${summary.converted || 0}\nConflitos legados: ${summary.legacy_conflicts || 0}\nErros: ${summary.errors || 0}`;
  if (summary.reloaded) mensagem += "\nConfiguracao aplicada no FreePBX.";
  if (conflitos.length) {
    const lista = conflitos.slice(0, 8).map((item) => `${item.extension} (${item.login || "sem login"})`).join(", ");
    mensagem += `\nConflitos: ${lista}`;
  }
  if (ignorados.length) {
    const lista = ignorados.slice(0, 8).map((item) => `${item.extension || "sem ramal"} (${item.login || "sem login"}): ${item.message || "ignorado"}`).join("\n");
    mensagem += `\nIgnorados:\n${lista}`;
  }
  if (erros.length) {
    const lista = erros.slice(0, 8).map((item) => `${item.extension || "sem ramal"} (${item.login || "sem login"}): ${item.message || "erro"}`).join("\n");
    mensagem += `\nErros:\n${lista}`;
  }
  await initSipClient(true).catch(() => {});
  alert(mensagem);
}

async function _sipSincronizarUsuarioAtualFreepbx() {
  const usuarioId = Number(chatState.usuarioId || usuarioLogado?.id || 0);
  if (!usuarioId) {
    throw new Error("Usuario atual sem identificacao para sincronizar no FreePBX.");
  }

  const resp = await apiFetch("/api/sip/freepbx/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ usuario_ids: [usuarioId], convert_legacy: true }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data?.erro || "Erro ao sincronizar o ramal atual no FreePBX.");
  }

  const results = Array.isArray(data?.results) ? data.results : [];
  const item = results.find((row) => Number(row?.user_id || 0) === usuarioId) || results[0] || null;
  const status = String(item?.status || "").trim();
  if (status === "error" || status === "legacy_conflict" || status === "skipped") {
    throw new Error(item?.message || "O FreePBX rejeitou a sincronizacao do ramal.");
  }

  return data;
}

function _sipPodeTentarReparoAuth(cause, sessionKey) {
  const texto = String(cause || "").trim().toLowerCase();
  if (!texto || !sessionKey) return false;
  if (!sipState.profile?.auto_register) return false;
  if (sipState.authRepairPromise) return false;
  if (sipState.lastAuthRepairKey === sessionKey) return false;
  return (
    texto.includes("rejected")
    || texto.includes("unauthorized")
    || texto.includes("forbidden")
    || texto.includes("authentication")
  );
}

async function _sipRepararAuthERegistrar(sessionKey, modeLabel) {
  if (!sessionKey || sipState.authRepairPromise) return false;
  sipState.lastAuthRepairKey = sessionKey;

  sipState.authRepairPromise = (async () => {
    try {
      _sipSetStatus("Registro SIP rejeitado; sincronizando o ramal no FreePBX...", "warn");
      await _sipSincronizarUsuarioAtualFreepbx();
      _sipSetStatus("Ramal sincronizado. Tentando registrar novamente...", "warn");
      await initSipClient(true);
      return true;
    } catch (err) {
      _sipSetStatus(`Falha no registro SIP em ${modeLabel}: ${err?.message || err}.`, "error");
      return false;
    } finally {
      sipState.authRepairPromise = null;
      atualizarEstadoSipChat();
    }
  })();

  return sipState.authRepairPromise;
}

function _vendasConfigAtualizarRegras(regras = null) {
  if (regras) vendasImportRulesState = regras;
  const regrasAtuais = regras || vendasImportRulesState || null;
  const regrasEl = document.getElementById("vendasConfigRegras");
  const gruposEl = document.getElementById("vendasConfigGrupos");
  if (!regrasEl && !gruposEl) return;
  if (!regrasAtuais) {
    if (regrasEl) regrasEl.textContent = "Arquivo de regras: Relatorios/config-rel-vendas.";
    if (gruposEl) gruposEl.textContent = "Regras de importacao indisponiveis no momento.";
    return;
  }
  const arquivo = regrasAtuais?.arquivo_relativo || regrasAtuais?.arquivo || "Relatorios/config-rel-vendas";
  const descartar = Array.isArray(regrasAtuais?.descartar_registros) ? regrasAtuais.descartar_registros : [];
  const grupos = Array.isArray(regrasAtuais?.grupos) ? regrasAtuais.grupos : [];
  const colunasIgnoradas = Array.isArray(regrasAtuais?.colunas_ignoradas) ? regrasAtuais.colunas_ignoradas : [];
  const gruposTexto = grupos.map((item) => {
    const codigo = item?.codigo_exibicao || item?.codigo || "";
    const nome = item?.nome || "";
    return [codigo, nome].filter(Boolean).join(" ");
  }).filter(Boolean).join(" | ");
  const origem = regrasAtuais?.carregado_de_arquivo ? "regras aplicadas do arquivo" : "regras padrao aplicadas";
  if (regrasEl) {
    const partes = [`Arquivo de regras: ${arquivo}`, origem];
    if (descartar.length) partes.push(`descartes: ${descartar.join(", ")}`);
    if (colunasIgnoradas.length) partes.push(`colunas ignoradas: ${colunasIgnoradas.length}`);
    partes.push("colunas fora do conjunto necessario sao ignoradas na importacao");
    regrasEl.textContent = partes.join(" | ");
  }
  if (gruposEl) {
    gruposEl.textContent = gruposTexto
      ? `Grupos normalizados: ${gruposTexto}`
      : "Grupos normalizados: sem configuracao detalhada.";
  }
}

function preencherConfigVendas(cfg = {}, fonte = {}, imports = [], meta = {}){
  vendasConfigState = cfg || {};
  _vendasCacheLocalAtualizarAtivo(cfg?.active_cache_id || "");
  const habilitado = document.getElementById("vendasConfigHabilitado");
  const sourceType = document.getElementById("vendasConfigSourceType");
  const csvDir = document.getElementById("vendasConfigCsvDir");
  const resumo = document.getElementById("vendasConfigResumo");
  const fonteEl = document.getElementById("vendasConfigFonte");
  const body = document.getElementById("vendasCacheBody");

  if (habilitado) habilitado.checked = !!cfg.habilitado;
  if (sourceType) sourceType.value = cfg.source_type || "csv_relatorios_dir";
  if (csvDir) csvDir.value = cfg.csv_dir || "";

  if (resumo) {
    resumo.textContent = cfg.updated_at
      ? `Ultima atualizacao: ${_chatDataLabel(cfg.updated_at)} | Origem: ${cfg.source_type || "-"}`
      : `Configuracao pronta para preenchimento. Origem: ${cfg.source_type || "-"}`;
  }
  if (fonteEl) {
    const nome = fonte?.name || fonte?.path || fonte?.message || "-";
    fonteEl.textContent = `Fonte atual: ${nome}`;
  }
  if (body) {
    const rows = Array.isArray(imports) ? imports : [];
    body.innerHTML = rows.length ? rows.map((item) => `
      <tr>
        <td><input type="checkbox" ${item.active ? "checked" : ""} onchange="ativarCacheVendas('${_escJsString(item.id || "")}', this.checked)"></td>
        <td>${_escHtml(item.source_name || "-")}</td>
        <td>${_escHtml(_fmtNumVendas(item.rows_importadas || 0))}</td>
        <td>${_escHtml(item.importado_em || "-")}</td>
        <td>${_escHtml(item.cache_exists ? `${item.status || "-"} | cache pronto` : (item.status || "-"))}</td>
        <td><button type="button" onclick="excluirCacheVendas('${_escJsString(item.id || "")}')">Excluir</button></td>
      </tr>
    `).join("") : '<tr><td colspan="6">Nenhum cache importado ainda.</td></tr>';
  }
  _vendasConfigAtualizarRegras(meta?.regras_importacao || null);
  _vendasConfigAtualizarIndicador(cfg, fonte, imports, meta);
}

async function carregarConfigVendas(){
  const resumo = document.getElementById("vendasConfigResumo");
  if (resumo) resumo.textContent = "Carregando configuracao de vendas...";
  const resp = await apiFetch("/api/vendas/config");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (resumo) resumo.textContent = data?.erro || "Erro ao carregar configuracao de vendas.";
    if (vendasConfigMonitorAtivo) _vendasConfigAgendarMonitor(true);
    return;
  }
  preencherConfigVendas(data?.config || {}, data?.fonte || {}, data?.imports || [], {
    regras_importacao: data?.regras_importacao || null,
  });
}

async function salvarConfigVendas(){
  const payload = {
    habilitado: !!document.getElementById("vendasConfigHabilitado")?.checked,
    source_type: document.getElementById("vendasConfigSourceType")?.value || "csv_relatorios_dir",
    csv_dir: (document.getElementById("vendasConfigCsvDir")?.value || "").trim(),
  };
  const resp = await apiFetch("/api/vendas/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    alert(data?.erro || "Erro ao salvar configuracao de vendas.");
    return;
  }
  preencherConfigVendas(data?.config || payload, data?.fonte || {}, data?.imports || [], {
    regras_importacao: data?.regras_importacao || null,
  });
}

async function importarCacheVendas(){
  const resumo = document.getElementById("vendasConfigResumo");
  if (resumo) resumo.textContent = "Importando CSV da pasta configurada...";
  const resp = await apiFetch("/api/vendas/cache/importar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (resumo) resumo.textContent = data?.erro || "Falha ao importar relatorio de vendas.";
    alert(data?.erro || "Falha ao importar relatorio de vendas.");
    return;
  }
  preencherConfigVendas(
    data?.config || vendasConfigState || {},
    data?.fonte || {},
    data?.imports || [],
    {
      processando_importacao: !!data?.processando_importacao,
      mensagem: data?.mensagem || "",
      regras_importacao: data?.regras_importacao || null,
    }
  );
  if (resumo) {
    resumo.textContent = data?.mensagem || "Todos dashboards e relatorios criados com sucesso.";
  }
  if (!(resp.status === 202 || data?.processando_importacao)) await carregarConfigVendas().catch(() => {});
  if (_dashboardVendasIsView(window.__dashView)) {
    recarregarDashboardVendaAtual(true).catch(()=>{});
  }
}

async function importarRelatorioCsvVendas(){
  const input = document.getElementById("vendasConfigArquivoCsv");
  const arquivo = input?.files?.[0] || null;
  if (!arquivo) {
    alert("Selecione um arquivo CSV antes de importar.");
    return;
  }
  const resumo = document.getElementById("vendasConfigResumo");
  if (resumo) resumo.textContent = `Importando ${arquivo.name}...`;
  const form = new FormData();
  form.append("arquivo", arquivo);
  const resp = await apiFetch("/api/vendas/cache/importar", {
    method: "POST",
    body: form,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (resumo) resumo.textContent = data?.erro || "Falha ao importar relatorio CSV.";
    alert(data?.erro || "Falha ao importar relatorio CSV.");
    return;
  }
  if (input) input.value = "";
  preencherConfigVendas(
    data?.config || vendasConfigState || {},
    data?.fonte || {},
    data?.imports || [],
    {
      processando_importacao: !!data?.processando_importacao,
      mensagem: data?.mensagem || "",
      regras_importacao: data?.regras_importacao || null,
    }
  );
  if (resumo) {
    resumo.textContent = data?.mensagem || "Todos dashboards e relatorios criados com sucesso.";
  }
  if (!(resp.status === 202 || data?.processando_importacao)) await carregarConfigVendas().catch(() => {});
  if (_dashboardVendasIsView(window.__dashView)) {
    recarregarDashboardVendaAtual(true).catch(()=>{});
  }
}

async function ativarCacheVendas(cacheId, checked){
  if (!cacheId) return;
  if (!checked) {
    await carregarConfigVendas();
    return;
  }
  const resp = await apiFetch(`/api/vendas/cache/${encodeURIComponent(cacheId)}/ativar`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    alert(data?.erro || "Falha ao ativar relatorio.");
    await carregarConfigVendas();
    return;
  }
  preencherConfigVendas(data?.config || vendasConfigState || {}, data?.fonte || {}, data?.imports || [], {
    regras_importacao: data?.regras_importacao || null,
  });
  if (window.__vendasView === "relatorio") recarregarRelatorioVendasAtual().catch(()=>{});
  if (_dashboardVendasIsView(window.__dashView)) recarregarDashboardVendaAtual(true).catch(()=>{});
}

async function excluirCacheVendas(cacheId){
  if (!cacheId) return;
  if (!confirm("Excluir este cache importado?")) return;
  const resp = await apiFetch(`/api/vendas/cache/${encodeURIComponent(cacheId)}`, { method: "DELETE" });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    alert(data?.erro || "Falha ao excluir cache.");
    return;
  }
  await carregarConfigVendas();
  if (_dashboardVendasIsView(window.__dashView)) {
    recarregarDashboardVendaAtual(true).catch(()=>{});
  }
}

function setConfigView(view){
  window.__configView = (view === "logs" || view === "cameras" || view === "sip" || view === "nfe" || view === "vendas") ? view : "status";
  const vStatus = document.getElementById("configViewStatus");
  const vLogs = document.getElementById("configViewLogs");
  const vCameras = document.getElementById("configViewCameras");
  const vSip = document.getElementById("configViewSip");
  const vNfe = document.getElementById("configViewNfe");
  const vVendas = document.getElementById("configViewVendas");
  if (vStatus) vStatus.classList.toggle("hidden", window.__configView !== "status");
  if (vLogs) vLogs.classList.toggle("hidden", window.__configView !== "logs");
  if (vCameras) vCameras.classList.toggle("hidden", window.__configView !== "cameras");
  if (vSip) vSip.classList.toggle("hidden", window.__configView !== "sip");
  if (vNfe) vNfe.classList.toggle("hidden", window.__configView !== "nfe");
  if (vVendas) vVendas.classList.toggle("hidden", window.__configView !== "vendas");

  if (window.__configView === "status") verificarStatus().catch(()=>{});
  if (window.__configView === "logs") carregarLogsExclusoes().catch(()=>{});
  if (window.__configView === "cameras") {
    alternarModoNovaCameraConfig();
    Promise.all([verificarStatus(), carregarConfigCameras()]).catch(()=>{});
  }
  if (window.__configView === "sip") carregarConfigSip().catch(()=>{});
  if (window.__configView === "nfe") carregarConfigNfe().catch(()=>{});
  if (window.__configView === "vendas") carregarConfigVendas().catch(()=>{});
}


// ================= DASH FROTA: TOOLTIP LINHA VERMELHA =================
const DASH_WARN_KM = 800; // "vencendo" quando faltar <= este valor

function _statusTxt(faltaKm){
  const v = Number(faltaKm);
  if (!isFinite(v)) return "";
  if (v <= 0) return `VENCIDO (${v} km)`;
  if (v <= DASH_WARN_KM) return `VENCENDO (faltam ${v} km)`;
  return `OK (faltam ${v} km)`;
}

function _buildDashFrotaTip(d){
  const faltaManut = (d.falta_manut_km !== null && d.falta_manut_km !== undefined) ? Number(d.falta_manut_km) : 0;
  const faltaOleo  = (d.falta_oleo_km !== null && d.falta_oleo_km !== undefined) ? Number(d.falta_oleo_km) : 0;

  const manutTipo = (d.ultima_manut_tipo || "").trim();
  const oleoTipo  = (d.ultimo_oleo_tipo || "").trim();

  const partes = [];
  // Só mostra o que está vencido/vencendo (mais útil)
  if (faltaManut <= DASH_WARN_KM){
    const extra = manutTipo ? ` • ${manutTipo}` : "";
    const ultKm = (d.ultima_manut_km !== null && d.ultima_manut_km !== undefined) ? ` • últ. ${d.ultima_manut_km} km` : "";
    partes.push(`Manutenção${extra}${ultKm}: ${_statusTxt(faltaManut)}`);
  }
  if (faltaOleo <= DASH_WARN_KM){
    const extra = oleoTipo ? ` • ${oleoTipo}` : "";
    const ultKm = (d.ultimo_oleo_km !== null && d.ultimo_oleo_km !== undefined) ? ` • últ. ${d.ultimo_oleo_km} km` : "";
    partes.push(`Óleo${extra}${ultKm}: ${_statusTxt(faltaOleo)}`);
  }

  return partes.join("\n");
}

let _dashTipEl = null;
function _ensureDashTipEl(){
  if (_dashTipEl) return _dashTipEl;
  const el = document.createElement("div");
  el.className = "dash-tooltip hidden";
  document.body.appendChild(el);
  _dashTipEl = el;
  return el;
}

function _showDashTip(text, anchorEl){
  if (!text) return;
  const el = _ensureDashTipEl();
  el.textContent = text;
  el.classList.remove("hidden");

  const r = anchorEl.getBoundingClientRect();
  // posiciona abaixo da linha (ou acima se estourar)
  let top = r.bottom + window.scrollY + 8;
  let left = r.left + window.scrollX + 10;

  // ajusta limites
  const pad = 8;
  const maxLeft = window.scrollX + document.documentElement.clientWidth - el.offsetWidth - pad;
  if (left > maxLeft) left = Math.max(pad + window.scrollX, maxLeft);
  const maxTop = window.scrollY + document.documentElement.clientHeight - el.offsetHeight - pad;
  if (top > maxTop) top = r.top + window.scrollY - el.offsetHeight - 8;

  el.style.left = left + "px";
  el.style.top = top + "px";
}

function _hideDashTip(){
  if (_dashTipEl) _dashTipEl.classList.add("hidden");
}

function _initDashFrotaTooltips(dados){
  const body = document.getElementById("dashFrotaBody");
  if (!body) return;

  const rows = body.querySelectorAll("tr");
  rows.forEach((tr, idx) => {
    const d = (dados && dados[idx]) ? dados[idx] : null;
    if (!d) return;

    const tip = _buildDashFrotaTip(d);
    tr.dataset.tip = tip || "";

    // Tooltip nativo (desktop): aparece ao passar o mouse
    if (tip) tr.setAttribute("title", tip);

    // Mouse
    tr.addEventListener("mouseenter", () => {
      if (tr.classList.contains("dash-row-alert") && tip) _showDashTip(tip, tr);
    });
    tr.addEventListener("mouseleave", () => _hideDashTip());

  });

  // clique fora fecha
  document.addEventListener("click", (e) => {
    if (_dashTipEl && !_dashTipEl.classList.contains("hidden")) {
      // se clicou no tooltip, não fecha
      if (e.target === _dashTipEl) return;
      _hideDashTip();
    }
  }, { once:false });
}
function getStatusBadge(status) {
  const statusMap = {
    chegada: { label: "Chegou", color: "#4CAF50", bgColor: "#E8F5E9" },
    descarregado: { label: "Descarregado", color: "#2196F3", bgColor: "#E3F2FD" },
    liberado: { label: "Liberado", color: "#FF9800", bgColor: "#FFF3E0" },
    carregando: { label: "Carregando", color: "#F44336", bgColor: "#FFEBEE" },
    carregado: { label: "Carregado", color: "#9C27B0", bgColor: "#F3E5F5" },
    entregando: { label: "Entregando", color: "#00BCD4", bgColor: "#E0F2F1" },
    retornando: { label: "Retornando", color: "#3F51B5", bgColor: "#EEE5F7" },
    paradoVasio: { label: "Parado (vazio)", color: "#795548", bgColor: "#EFEBE9" },
    paradoCarregado: { label: "Parado (carregado)", color: "#607D8B", bgColor: "#ECEFF1" }
  };

  const s = statusMap[status] || { label: "-", color: "#999", bgColor: "#f0f0f0" };
  return `<span style="background-color: ${s.bgColor}; color: ${s.color}; padding: 4px 8px; border-radius: 4px; font-weight: bold;">${s.label}</span>`;
}

async function renderDashboardFrota(){
  const body = document.getElementById("dashFrotaBody");
  if (!body) return;

  const r = await apiFetch("/api/dashboard_frota");
  const dados = await r.json();

  let alt = 0;
  body.innerHTML = (dados || []).map((d) => {
    const nomeCaminhao = d.veiculo_nome || d.modelo || d.placa || "-";
    const veiculoDetalhe = [d.placa || "", d.modelo || ""].filter(Boolean).join(" / ") || "-";
    const motorista = d.motorista_nome || "-";
    const frete = d.frete_nome || "-";
    const status = d.frete_status || "-";
    const media = (d.media_km !== null && d.media_km !== undefined)
      ? Number(d.media_km).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : "-";
    const faltaManut = (d.falta_manut_km !== null && d.falta_manut_km !== undefined) ? Number(d.falta_manut_km) : 0;
    const faltaOleo  = (d.falta_oleo_km !== null && d.falta_oleo_km !== undefined) ? Number(d.falta_oleo_km) : 0;

    const isAlert = (faltaManut <= 0) || (faltaOleo <= 0);
    const cls = isAlert ? "dash-row-alert" : `dash-row-ok-${alt%3}`;
    alt++;

    const veiculoId = Number(d.veiculo_id || 0);
    return `
      <tr class="${cls}" onclick="abrirHistoricoFrota(${veiculoId})">
        <td>
          <div class="dash-veiculo-nome">${_escHtml(nomeCaminhao)}</div>
          <div class="dash-veiculo-detalhe">${_escHtml(veiculoDetalhe)}</div>
        </td>
        <td>${_escHtml(motorista)}</td>
        <td>${_escHtml(frete)}</td>
        <td>${_escHtml(status)}</td>
        <td>${_escHtml(String(media))}</td>
        <td>${_escHtml(faltaManut.toString())} km</td>
        <td>${_escHtml(faltaOleo.toString())} km</td>
      </tr>
    `;
  }).join("");

  _initDashFrotaTooltips(dados);
}

function showTab(tabId, el) {
  const mudouDeComunicacao = tabId !== "comunicacao";
  if (mudouDeComunicacao && chatState.isOpen) {
    toggleChatPopup(false).catch(() => {});
  }

  closeOpenSubmenus();

  document.querySelectorAll(".section").forEach((sec) => sec.classList.remove("activeSection"));

  const target = document.getElementById(tabId);
  if (target) target.classList.add("activeSection");

  document.querySelectorAll(".menu-item").forEach((m) => m.classList.remove("active"));
  if (el) el.classList.add("active");

  // No celular, ao navegar, fecha o menu
  if (window.matchMedia && window.matchMedia("(max-width: 768px)").matches) {
    toggleMenuMobile(false);
  }

  // Hooks por aba
  if (tabId === "gestaofrota") {
    if (!window.__gestaoView) window.__gestaoView = "registrar";
    if (!window.__gestaoRegistroView) window.__gestaoRegistroView = "manutencao";
    setGestaoFrotaView(window.__gestaoView);
  }
  if (tabId === "dashboard") {
    // Ao abrir o item Dashboard sem escolher um submenu específico, volta para o resumo.
    if (!window.__dashboardSubmenuNavigation) {
      window.__dashView = "resumo";
      setDashboardView("resumo");
    }
  }
  if (tabId === "comissao") {
    if (!window.__comissaoView || !["lancamento", "relatorios"].includes(window.__comissaoView)) {
      window.__comissaoView = "lancamento";
    }
    setComissaoView(window.__comissaoView);
  }
  if (tabId === "vendas") {
    if (!window.__vendasView || !["dashboard", "relatorio"].includes(window.__vendasView)) {
      window.__vendasView = "relatorio";
    }
    setVendasView(window.__vendasView);
  }
  if (tabId === "monitor") {
    if (!MONITOR_APPS[window.__monitorView]) {
      window.__monitorView = "esxi";
    }
    setMonitorView(window.__monitorView);
  }
  if (tabId === "comunicacao") {
    initChatInterno();
    toggleChatPopup(true).catch(() => {});
  }
  if (tabId === "config") {
    if (!window.__configView || !["status", "logs", "cameras", "sip", "nfe", "vendas"].includes(window.__configView)) {
      window.__configView = "status";
    }
    setConfigView(window.__configView);
  }
  if (tabId === "pontosvenda") {
    if (!window.__pontosVendaView || !["cadastro", "relatorio"].includes(window.__pontosVendaView)) {
      window.__pontosVendaView = "cadastro";
    }
    setPontosVendaView(window.__pontosVendaView);
  }
  if (tabId === "estoque") {
    if (!window.__estoqueView || !["lancar", "posicao", "cadastrar", "rastreio"].includes(window.__estoqueView)) {
      window.__estoqueView = "lancar";
    }
    setEstoqueView(window.__estoqueView);
  }
  if (tabId === "cargas") {
    if (!window.__cargasView || !["cadastro", "escala"].includes(window.__cargasView)) {
      window.__cargasView = "cadastro";
    }
    setCargasView(window.__cargasView);
  }
  if (tabId === "agentia") {
    iniciarAgentIa();
  }
  if (tabId === "cadastros") {
    if (!window.__cadastrosView) window.__cadastrosView = "colaboradores";
    setCadastrosView(window.__cadastrosView);
  }
  if (tabId === "fretes") {
    _agendarEqualizacaoAlturaKanban(0);
  } else {
    _atualizarScrollbarAuxiliarKanban();
  }

}

//////////////////////////////////////////////////////
// AGENT IA EMBUTIDO
//////////////////////////////////////////////////////
const AGENTIA_STORAGE_KEY = "riobranco_agentia_state_v1";
const AGENTIA_MESSAGE_LIMIT = 80;
const AGENTIA_HISTORY_LIMIT = 12;
const agentIaState = {
  initialized: false,
  busy: false,
  cards: [],
  selectedId: null,
  history: [],
  messages: [],
  thinkingBox: null,
  thinkingTimer: null,
};

function agentIaEscape(value){
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function agentIaNormalizeRole(role){
  const value = String(role || "").trim().toLowerCase();
  if (value === "assistant" || value === "agent") return "agent";
  return "user";
}

function agentIaHistoryRole(role){
  return agentIaNormalizeRole(role) === "agent" ? "assistant" : "user";
}

function agentIaNormalizeMessage(message){
  const role = agentIaNormalizeRole(message?.role);
  const text = String(message?.text ?? message?.content ?? "").trim().slice(0, 2000);
  const output = String(message?.output ?? "").trim().slice(0, 4000);
  const actions = Array.isArray(message?.actions) ? message.actions : [];
  return {
    role,
    text,
    output,
    actions: actions
      .map((action) => ({
        name: String(action?.name || "").trim(),
        label: String(action?.label || "").trim(),
        kind: String(action?.kind || "").trim() || undefined,
        danger: !!action?.danger,
        needsMessage: !!(action?.needsMessage || action?.needs_message),
      }))
      .filter((action) => !!action.name),
  };
}

function agentIaPersistState(){
  try {
    const payload = {
      selectedId: agentIaState.selectedId || null,
      history: agentIaState.history.slice(-AGENTIA_HISTORY_LIMIT),
      messages: agentIaState.messages.slice(-AGENTIA_MESSAGE_LIMIT),
    };
    localStorage.setItem(AGENTIA_STORAGE_KEY, JSON.stringify(payload));
  } catch {}
}

function agentIaLoadState(){
  try {
    const raw = localStorage.getItem(AGENTIA_STORAGE_KEY);
    if (!raw) return false;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") {
      if (Array.isArray(parsed.history)) {
        agentIaState.history = parsed.history
          .map((item) => ({
            role: agentIaHistoryRole(item?.role),
            content: String(item?.content ?? "").trim(),
          }))
          .filter((item) => !!item.content)
          .slice(-AGENTIA_HISTORY_LIMIT);
      }
      if (Array.isArray(parsed.messages)) {
        agentIaState.messages = parsed.messages
          .map((item) => agentIaNormalizeMessage(item))
          .filter((item) => !!item.text || !!item.output)
          .slice(-AGENTIA_MESSAGE_LIMIT);
      } else if (!agentIaState.messages.length && Array.isArray(parsed.history)) {
        agentIaState.messages = parsed.history
          .map((item) => ({
            role: agentIaHistoryRole(item?.role),
            text: String(item?.content ?? "").trim(),
            output: "",
            actions: [],
          }))
          .filter((item) => !!item.text)
          .slice(-AGENTIA_MESSAGE_LIMIT);
      }
      if (parsed.selectedId !== undefined && parsed.selectedId !== null) {
        const selected = Number(parsed.selectedId);
        agentIaState.selectedId = Number.isFinite(selected) ? selected : null;
      }
      return true;
    }
  } catch {}
  return false;
}

function agentIaBuildMessageBox(message){
  const box = document.createElement("div");
  box.className = `agentia-msg ${message.role}`;
  box.textContent = message.text || "";

  if (Array.isArray(message.actions) && message.actions.length) {
    const row = document.createElement("div");
    row.className = "agentia-msg-actions";
    message.actions.forEach((action) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "agentia-action" + (action.kind === "secondary" ? " secondary" : "") + (action.danger ? " danger" : "");
      btn.textContent = action.label || action.name || "Executar";
      btn.onclick = () => agentIaSendAction(action);
      row.appendChild(btn);
    });
    box.appendChild(row);
  }

  if (message.output) {
    const pre = document.createElement("pre");
    pre.textContent = message.output;
    box.appendChild(pre);
  }

  return box;
}

function agentIaBuildThinkingBox(){
  const box = document.createElement("div");
  box.className = "agentia-msg agent thinking";
  box.setAttribute("aria-live", "polite");
  box.innerHTML = `
    <span class="agentia-thinking-label">Pensando</span>
    <span class="agentia-thinking-dots" aria-hidden="true">
      <span></span><span></span><span></span>
    </span>
  `;
  return box;
}

function agentIaRenderConversation(){
  const chat = document.getElementById("agentIaChat");
  if (!chat) return;
  chat.innerHTML = "";
  agentIaState.messages.forEach((message) => {
    chat.appendChild(agentIaBuildMessageBox(message));
  });
  chat.scrollTop = chat.scrollHeight;
}

function agentIaRecordMessage(message){
  const normalized = agentIaNormalizeMessage(message);
  if (!normalized.text && !normalized.output) return null;
  agentIaState.messages.push(normalized);
  if (agentIaState.messages.length > AGENTIA_MESSAGE_LIMIT) {
    agentIaState.messages = agentIaState.messages.slice(-AGENTIA_MESSAGE_LIMIT);
  }
  agentIaState.history.push({
    role: agentIaHistoryRole(normalized.role),
    content: normalized.output ? `${normalized.text}\n${normalized.output}`.trim().slice(0, 2000) : normalized.text,
  });
  if (agentIaState.history.length > AGENTIA_HISTORY_LIMIT) {
    agentIaState.history = agentIaState.history.slice(-AGENTIA_HISTORY_LIMIT);
  }
  agentIaPersistState();
  return normalized;
}

function agentIaSetBusy(busy){
  agentIaState.busy = !!busy;
  const btn = document.getElementById("agentIaSendBtn");
  if (btn) {
    btn.disabled = !!busy;
    btn.textContent = busy ? "Enviando..." : "Enviar";
  }
}

function agentIaShowThinking(){
  agentIaHideThinking();
  const chat = document.getElementById("agentIaChat");
  if (!chat) return;
  const box = agentIaBuildThinkingBox();
  agentIaState.thinkingBox = box;
  chat.appendChild(box);
  chat.scrollTop = chat.scrollHeight;
  const labels = ["Pensando", "Pensando.", "Pensando..", "Pensando..."];
  let idx = 0;
  agentIaState.thinkingTimer = window.setInterval(() => {
    if (!agentIaState.thinkingBox) return;
    const labelEl = agentIaState.thinkingBox.querySelector(".agentia-thinking-label");
    if (labelEl) labelEl.textContent = labels[idx % labels.length];
    idx += 1;
  }, 450);
}

function agentIaUpdateThinkingText(text){
  const box = agentIaState.thinkingBox;
  if (!box) return;
  if (agentIaState.thinkingTimer) {
    window.clearInterval(agentIaState.thinkingTimer);
    agentIaState.thinkingTimer = null;
  }
  box.classList.remove("thinking");
  box.classList.add("streaming");
  box.textContent = text || "Pensando...";
}

function agentIaFinalizeLiveReply(text, actions = [], output = "", workspace = null){
  if (workspace) agentIaRenderWorkspace(workspace);

  const stored = agentIaRecordMessage({
    role: "agent",
    text: text || "Sem resposta.",
    actions,
    output,
  });
  const chat = document.getElementById("agentIaChat");
  const liveBox = agentIaState.thinkingBox;
  const finalBox = stored ? agentIaBuildMessageBox(stored) : agentIaBuildMessageBox({
    role: "agent",
    text: text || "Sem resposta.",
    actions,
    output,
  });

  if (liveBox && liveBox.parentNode) {
    liveBox.replaceWith(finalBox);
  } else if (chat) {
    chat.appendChild(finalBox);
  }

  agentIaState.thinkingBox = null;
  if (chat) {
    chat.scrollTop = chat.scrollHeight;
  }
}

function agentIaHideThinking(){
  if (agentIaState.thinkingTimer) {
    window.clearInterval(agentIaState.thinkingTimer);
    agentIaState.thinkingTimer = null;
  }
  if (agentIaState.thinkingBox) {
    agentIaState.thinkingBox.remove();
    agentIaState.thinkingBox = null;
  }
}

function agentIaSetActiveMenu(option){
  document.querySelectorAll(".agentia-menu-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.agentiaOption === option);
  });
}

function agentIaAddMessage(role, text, actions = [], output = ""){
  const stored = agentIaRecordMessage({ role, text, actions, output });
  const chat = document.getElementById("agentIaChat");
  if (!chat || !stored) return;
  chat.appendChild(agentIaBuildMessageBox(stored));
  chat.scrollTop = chat.scrollHeight;
}

function agentIaSelectedCardHtml(card){
  if (!card) return "";
  const statuses = [
    ["chegada", "Chegada"],
    ["descarregado", "Descarregado"],
    ["liberado", "Liberado"],
    ["carregando", "Carregando"],
    ["carregado", "Carregado"],
    ["entregando", "Entregando"],
    ["retornando", "Retornando"],
  ];
  const buttons = statuses.map(([status, label]) => {
    const disabled = status === card.status ? "disabled" : "";
    return `<button type="button" class="agentia-action secondary" data-agentia-move-status="${agentIaEscape(status)}" ${disabled}>${agentIaEscape(label)}</button>`;
  }).join("");
  return `
    <div class="agentia-frete-title">#${agentIaEscape(card.id)} ${agentIaEscape(card.title)}</div>
    <div class="agentia-frete-row">Status atual: ${agentIaEscape(card.status_label)} | Caminhao: ${agentIaEscape(card.vehicle)} ${card.plate ? "| Placa: " + agentIaEscape(card.plate) : ""}</div>
    <div class="agentia-frete-row">Motorista: ${agentIaEscape(card.driver)} | Entregador: ${agentIaEscape(card.helper)}</div>
    <div class="agentia-frete-row">Carga: ${agentIaEscape(card.load)} ${card.date ? "| Data: " + agentIaEscape(card.date) : ""}</div>
    <div class="agentia-selected-actions">${buttons}</div>
  `;
}

function agentIaSelectCard(id){
  agentIaState.selectedId = Number(id);
  agentIaPersistState();
  const selected = agentIaState.cards.find((card) => Number(card.id) === agentIaState.selectedId);
  document.querySelectorAll(".agentia-frete-card").forEach((el) => {
    el.classList.toggle("selected", Number(el.dataset.id) === agentIaState.selectedId);
  });

  const panel = document.getElementById("agentIaSelectedCard");
  if (!panel) return;
  if (!selected) {
    panel.classList.remove("visible");
    panel.innerHTML = "";
    return;
  }

  panel.innerHTML = agentIaSelectedCardHtml(selected);
  panel.classList.add("visible");
  panel.querySelectorAll("[data-agentia-move-status]").forEach((btn) => {
    btn.onclick = () => {
      const status = btn.dataset.agentiaMoveStatus;
      agentIaAddMessage("user", `mover frete ${selected.id} para ${btn.textContent}`);
      agentIaChat({ action: "move_frete", frete_id: selected.id, status, confirmed: true });
    };
  });
}

function agentIaRenderWorkspace(workspace){
  if (!workspace) return;
  if (workspace.active) agentIaSetActiveMenu(workspace.active);

  const title = document.getElementById("agentIaWorkspaceTitle");
  const meta = document.getElementById("agentIaWorkspaceMeta");
  const grid = document.getElementById("agentIaCardGrid");
  const selectedPanel = document.getElementById("agentIaSelectedCard");
  if (title && workspace.title) title.textContent = workspace.title;
  if (meta && workspace.meta) meta.textContent = workspace.meta;
  if (!grid || !Array.isArray(workspace.cards)) return;

  agentIaState.cards = workspace.cards;
  grid.innerHTML = "";

  if (!agentIaState.cards.length) {
    grid.innerHTML = `<div class="agentia-frete-row">Nenhum card encontrado.</div>`;
    if (selectedPanel) {
      selectedPanel.classList.remove("visible");
      selectedPanel.innerHTML = "";
    }
    return;
  }

  agentIaState.cards.forEach((card) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "agentia-frete-card";
    btn.dataset.id = card.id;
    btn.innerHTML = `
      <div class="agentia-frete-title">#${agentIaEscape(card.id)} ${agentIaEscape(card.title)}</div>
      <div class="agentia-frete-status">${agentIaEscape(card.status_label)}</div>
      <div class="agentia-frete-row">Caminhao: ${agentIaEscape(card.vehicle)} ${card.plate ? "| " + agentIaEscape(card.plate) : ""}</div>
      <div class="agentia-frete-row">Motorista: ${agentIaEscape(card.driver)}</div>
      <div class="agentia-frete-row">Carga: ${agentIaEscape(card.load)}</div>
    `;
    btn.onclick = () => agentIaSelectCard(card.id);
    grid.appendChild(btn);
  });

  agentIaSelectCard(workspace.selected_id || agentIaState.selectedId || agentIaState.cards[0].id);
}

async function agentIaSincronizarAplicacao(data){
  if (!data || typeof data !== "object") return;
  const tasks = [];
  if (data.workspace?.active === "kanban" && typeof carregarFretes === "function") {
    tasks.push(carregarFretes().catch((err) => console.warn("Agent IA: falha ao atualizar kanban", err)));
  }
  if (data.devolucoes_updated && typeof carregarDevolucoes === "function") {
    tasks.push(carregarDevolucoes().catch((err) => console.warn("Agent IA: falha ao atualizar devolucoes", err)));
  }
  if (tasks.length) await Promise.all(tasks);
}

async function agentIaChat(payload){
  if (agentIaState.busy) return;
  agentIaSetBusy(true);
  agentIaShowThinking();
  try {
    if (!usuarioLogado && !LOGIN_BYPASS) {
      await restaurarSessaoLogin().catch(() => false);
    }
    const payloadFinal = { ...(payload || {}) };
    if (usuarioLogado?.id) {
      payloadFinal.usuario_id = usuarioLogado.id;
      payloadFinal.usuario_login = usuarioLogado.login || "";
      payloadFinal.usuario_nome = usuarioLogado.nome || "";
    }
    if (!payloadFinal.chat_mode) payloadFinal.chat_mode = "agent";
    payloadFinal.history = agentIaState.history.slice(-12);
    payloadFinal.stream = true;
    const resp = await apiFetch("/api/agent/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payloadFinal),
    });
    if (!resp.ok) {
      const errorText = await resp.text();
      throw new Error(errorText || `Falha HTTP ${resp.status}`);
    }

    const contentType = (resp.headers.get("content-type") || "").toLowerCase();
    if (contentType.includes("application/x-ndjson") && resp.body) {
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalData = null;

      while (true) {
        const { value, done } = await reader.read();
        if (value) {
          buffer += decoder.decode(value, { stream: !done });
        }

        let newlineIndex = buffer.indexOf("\n");
        while (newlineIndex !== -1) {
          const line = buffer.slice(0, newlineIndex).trim();
          buffer = buffer.slice(newlineIndex + 1);
          if (line) {
            try {
              const event = JSON.parse(line);
              if (event.type === "status") {
                agentIaUpdateThinkingText(event.reply || "Pensando...");
              } else if (event.type === "delta") {
                agentIaUpdateThinkingText(event.reply || event.text || "Pensando...");
              } else if (event.type === "final") {
                finalData = event;
              } else if (event.type === "error") {
                throw new Error(event.reply || event.message || "Nao consegui conversar com o Agent IA.");
              }
            } catch (parseErr) {
              console.warn("Agent IA stream parse error", parseErr);
            }
          }
          newlineIndex = buffer.indexOf("\n");
        }

        if (done) {
          const tail = buffer.trim();
          if (tail) {
            try {
              const event = JSON.parse(tail);
              if (event.type === "status") {
                agentIaUpdateThinkingText(event.reply || "Pensando...");
              } else if (event.type === "delta") {
                agentIaUpdateThinkingText(event.reply || event.text || "Pensando...");
              } else if (event.type === "final") {
                finalData = event;
              } else if (event.type === "error") {
                throw new Error(event.reply || event.message || "Nao consegui conversar com o Agent IA.");
              }
            } catch (parseErr) {
              console.warn("Agent IA stream parse error", parseErr);
            }
          }
          break;
        }
      }

      if (!finalData) {
        throw new Error("A resposta terminou sem finalizar o stream.");
      }

      agentIaFinalizeLiveReply(
        finalData.reply || finalData.output || "Sem resposta.",
        finalData.actions || [],
        finalData.output || "",
        finalData.workspace || null,
      );
      await agentIaSincronizarAplicacao(finalData);
    } else {
      const data = await resp.json();
      agentIaFinalizeLiveReply(
        data.reply || data.output || "Sem resposta.",
        data.actions || [],
        data.output || "",
        data.workspace || null,
      );
      await agentIaSincronizarAplicacao(data);
    }
  } catch (err) {
    agentIaHideThinking();
    agentIaAddMessage("agent", err?.message || "Nao consegui conversar com o Agent IA.");
  } finally {
    agentIaHideThinking();
    agentIaSetBusy(false);
    const input = document.getElementById("agentIaInput");
    if (input) input.focus();
  }
}

function agentIaSendAction(action){
  if (!action) return;
  if (String(action.name || "").startsWith("module_")) {
    agentIaAddMessage("user", action.label || action.name || "Abrir modulo");
    agentIaChat({ action: action.name, confirmed: true });
    return;
  }
  if (action.needsMessage) {
    const message = prompt("Mensagem do commit:");
    if (!message) return;
    agentIaAddMessage("user", `${action.label || action.name} - ${message}`);
    agentIaChat({ action: action.name, commit_message: message, confirmed: true });
    return;
  }
  agentIaAddMessage("user", action.label || action.name || "Executar");
  agentIaChat({ ...action, action: action.name, confirmed: true });
}

function agentIaEnviarPergunta(event){
  event.preventDefault();
  const input = document.getElementById("agentIaInput");
  const text = (input?.value || "").trim();
  if (!text) return;
  input.value = "";
  agentIaAddMessage("user", text);
  agentIaChat({ message: text });
}

function agentIaMenu(option){
  agentIaSetActiveMenu(option);
  const messages = {
    kanban: "listar cargas",
    devolucoes: "explicar devolucoes",
    status: "explicar status",
    backup: "explicar backup",
    brief: "analisar pedido",
    validate: "validar baseline",
    git: "explicar git",
    deploy: "explicar deploy",
  };
  const text = messages[option] || "ajuda";
  agentIaAddMessage("user", text);
  agentIaChat({ message: text });
}

function iniciarAgentIa(){
  if (agentIaState.initialized) return;
  agentIaState.initialized = true;
  const restored = agentIaLoadState();
  if (restored && agentIaState.messages.length) {
    agentIaRenderConversation();
    return;
  }
  agentIaAddMessage("agent", "Oi. Eu sou o Agent IA do RioBranco. Posso conversar, listar cargas, destacar cards do kanban e executar rotinas do sistema quando voce pedir. Exemplos: listar cargas, mostrar caminhao 13, mover status para carregado caminhao 13.", [
    { name: "module_base", label: "Visao geral" },
    { name: "module_nfe", label: "NF-e", kind: "secondary" },
    { name: "module_fretes", label: "Fretes", kind: "secondary" },
    { name: "refresh_fretes", label: "Listar cargas" },
    { name: "status", label: "Status geral", kind: "secondary" },
  ]);
}

function abrirAgentIaDoChat(){
  try {
    showTab("agentia");
  } catch {}
  try {
    iniciarAgentIa();
  } catch {}
}

//////////////////////////////////////////////////////
// CHAT INTERNO
//////////////////////////////////////////////////////
function _chatDataLabel(dtStr) {
  if (!dtStr) return "";
  const raw = String(dtStr).trim().replace("T", " ");

  // Evita conversão de fuso pelo navegador (que estava gerando +3h/-3h).
  // Interpreta o valor vindo da API como horário local já correto.
  const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})[ ](\d{2}):(\d{2})(?::(\d{2}))?$/);
  if (m) {
    const dd = m[3];
    const mm = m[2];
    const yyyy = m[1];
    const hh = m[4];
    const mi = m[5];
    return `${dd}/${mm}/${yyyy} ${hh}:${mi}`;
  }

  const dt = new Date(raw);
  if (Number.isNaN(dt.getTime())) return raw;
  return dt.toLocaleString("pt-BR");
}

function _chatNomePorId(id) {
  const usuarios = cacheUsuarios || [];
  const u = usuarios.find((x) => String(x.id) === String(id));
  return u?.nome || "";
}

function _chatIniciais(nome) {
  const partes = String(nome || "").trim().split(/\s+/).filter(Boolean);
  if (!partes.length) return "??";
  return partes.slice(0, 2).map((p) => p.charAt(0)).join("").toUpperCase();
}

function _chatMensagemHtml(texto) {
  return _escHtml(texto || "").replace(/\n/g, "<br>");
}

function _chatResumoContato(contato) {
  if (!contato) {
    return chatState.usuarioId
      ? "Abra uma conversa para enviar mensagens ou usar SIP."
      : "Faca login para usar o chat.";
  }
  if (contato.sip_ramal) return `Ramal ${contato.sip_ramal}`;
  if (contato.login) return `Login ${contato.login}`;
  return "Contato interno";
}

function _chatAutoResizeInput() {
  const input = document.getElementById("chatTexto");
  if (!input || input.tagName !== "TEXTAREA") return;
  input.style.height = "0px";
  input.style.height = `${Math.min(Math.max(input.scrollHeight, 48), 120)}px`;
}

function _chatFormatBytes(total) {
  const bytes = Number(total || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function _chatGetAudioCtx() {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return null;
  if (!chatState.audioCtx) {
    try {
      chatState.audioCtx = new Ctx();
    } catch {
      return null;
    }
  }
  return chatState.audioCtx;
}

function _audioTone(freq = 880, duration = 0.18, volume = 0.05, type = "sine", delay = 0) {
  const ctx = _chatGetAudioCtx();
  if (!ctx) return;
  try {
    if (ctx.state === "suspended") {
      ctx.resume().catch(() => {});
    }
    const now = ctx.currentTime + Math.max(Number(delay || 0), 0);
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, now);
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(volume, now + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(now);
    osc.stop(now + duration + 0.02);
  } catch {}
}

function tocarAlertaChat() {
  _audioTone(880, 0.18, 0.05, "sine");
}

function _sipPararTons() {
  if (sipState.toneTimer) {
    try { clearInterval(sipState.toneTimer); } catch {}
    sipState.toneTimer = null;
  }
}

function _sipTocarToqueEntrada() {
  _sipPararTons();
  const tocar = () => {
    _audioTone(740, 0.16, 0.05, "triangle");
    _audioTone(880, 0.16, 0.05, "triangle", 0.22);
  };
  tocar();
  sipState.toneTimer = setInterval(tocar, 1800);
}

function _sipTocarTomDiscagem() {
  _sipPararTons();
  const tocar = () => {
    _audioTone(425, 0.35, 0.035, "sine");
    _audioTone(425, 0.35, 0.035, "sine", 0.45);
  };
  tocar();
  sipState.toneTimer = setInterval(tocar, 2200);
}

function _chatProcessarNovasMensagens(mensagens = []) {
  const lista = Array.isArray(mensagens) ? mensagens : [];
  const maxId = lista.reduce((acc, msg) => Math.max(acc, Number(msg?.id || 0)), 0);
  const ultimoVisto = Number(chatState.lastSeenMessageId || 0);
  if (!ultimoVisto) {
    chatState.lastSeenMessageId = maxId;
    return;
  }
  const haNovaMensagemRemota = lista.some((msg) => {
    const id = Number(msg?.id || 0);
    const remetente = String(msg?.remetente_id || "");
    return id > ultimoVisto && remetente !== String(chatState.usuarioId || "");
  });
  chatState.lastSeenMessageId = Math.max(ultimoVisto, maxId);
  if (haNovaMensagemRemota) tocarAlertaChat();
}

function renderAnexoPendenteChat() {
  const wrap = document.getElementById("chatAnexoPreview");
  const arquivo = chatState.pendingAttachment || null;
  if (!wrap) return;
  if (!arquivo) {
    wrap.innerHTML = "";
    wrap.classList.add("hidden");
    return;
  }
  const tamanho = _chatFormatBytes(arquivo.size);
  wrap.innerHTML = `
    <div class="chat-pending-attachment-card">
      <div class="chat-pending-attachment-title">${_escHtml(arquivo.name || "arquivo")}</div>
      <div class="chat-pending-attachment-meta">${_escHtml(tamanho || "Anexo pronto para envio")}</div>
    </div>
    <button type="button" class="chat-pending-attachment-remove" onclick="limparAnexoChat()" title="Remover anexo">Remover</button>
  `;
  wrap.classList.remove("hidden");
}

function limparAnexoChat() {
  chatState.pendingAttachment = null;
  const input = document.getElementById("chatAnexoInput");
  if (input) input.value = "";
  renderAnexoPendenteChat();
}

function abrirSeletorAnexoChat() {
  if (!chatState.usuarioId || !chatState.contatoId) return;
  document.getElementById("chatAnexoInput")?.click();
}

function selecionarAnexoChat(ev) {
  const arquivo = ev?.target?.files?.[0] || null;
  chatState.pendingAttachment = arquivo || null;
  renderAnexoPendenteChat();
}

function _chatAnexoMensagemHtml(msg) {
  if (!msg?.tem_anexo || !msg?.anexo_url) return "";
  const nome = _escHtml(msg.anexo_nome || "arquivo");
  const tamanho = _chatFormatBytes(msg.anexo_tamanho);
  const meta = tamanho ? `<span class="chat-attachment-size">${_escHtml(tamanho)}</span>` : "";
  if (msg.anexo_eh_imagem && msg.anexo_inline_url) {
    return `
      <a class="chat-attachment-image" href="${_escAttr(msg.anexo_inline_url)}" target="_blank" rel="noopener">
        <img src="${_escAttr(msg.anexo_inline_url)}" alt="${nome}">
      </a>
      <a class="chat-attachment-file" href="${_escAttr(msg.anexo_url)}" target="_blank" rel="noopener">
        <span class="chat-attachment-name">${nome}</span>
        ${meta}
      </a>
    `;
  }
  return `
    <a class="chat-attachment-file" href="${_escAttr(msg.anexo_url)}" target="_blank" rel="noopener">
      <span class="chat-attachment-name">${nome}</span>
      ${meta}
    </a>
  `;
}

function _chatEhContatoAIRio(contatoId = chatState.contatoId) {
  return String(contatoId || "") === CHAT_AI_RIO_CONTACT_ID;
}

function _chatAIRioNormalizeMessage(message){
  const role = String(message?.role || "").toLowerCase() === "user" ? "user" : "agent";
  return {
    role,
    text: String(message?.text ?? message?.content ?? "").trim().slice(0, 4000),
    output: String(message?.output ?? "").trim().slice(0, 4000),
    pending: !!message?.pending,
  };
}

function _chatAIRioPersistState(){
  try {
    localStorage.setItem(CHAT_AI_RIO_STORAGE_KEY, JSON.stringify({
      messages: (chatState.aiRioMessages || []).slice(-60),
    }));
  } catch {}
}

function _chatAIRioLoadState(){
  try {
    const raw = localStorage.getItem(CHAT_AI_RIO_STORAGE_KEY);
    if (!raw) return false;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && Array.isArray(parsed.messages)) {
      chatState.aiRioMessages = parsed.messages
        .map((item) => _chatAIRioNormalizeMessage(item))
        .filter((item) => !!item.text || !!item.output || item.pending);
      return true;
    }
  } catch {}
  return false;
}

function _chatAIRioEnsureGreeting(){
  if (chatState.aiRioMessages && chatState.aiRioMessages.length) return;
  chatState.aiRioMessages = [{
    role: "agent",
    text: "Oi. Eu sou a I.A-Rio. Posso conversar com voce por aqui, como se fosse mais uma pessoa da equipe.",
    output: "",
    pending: false,
  }];
  _chatAIRioPersistState();
}

function _chatAIRioConversationToHistory(){
  return (chatState.aiRioMessages || [])
    .filter((m) => !m.pending)
    .map((m) => ({
      role: m.role === "user" ? "user" : "assistant",
      content: (m.output ? `${m.text}\n${m.output}` : m.text).trim().slice(0, 2000),
    }))
    .filter((m) => !!m.content);
}

function _chatAIRioBuildMessageBox(message){
  const box = document.createElement("div");
  box.className = `chat-item ${message.role === "user" ? "me" : "other"}${message.pending ? " chat-item-sending" : ""}`;
  const text = String(message.text || "").trim();
  if (message.pending) {
    box.innerHTML = `
      ${text ? `<div class="chat-item-text">${_chatMensagemHtml(text)}</div>` : ""}
      <small class="chat-item-meta">
        <span class="chat-item-sending-label">I.A-Rio pensando</span>
        <span class="chat-item-sending-dots" aria-hidden="true"><span></span><span></span><span></span></span>
      </small>
    `;
    return box;
  }
  if (text) {
    box.innerHTML = `<div class="chat-item-text">${_chatMensagemHtml(text)}</div>`;
  }
  if (message.output) {
    const pre = document.createElement("pre");
    pre.textContent = message.output;
    box.appendChild(pre);
  }
  return box;
}

function _chatAIRioRenderConversation(){
  const box = document.getElementById("chatMensagens");
  if (!box) return;
  const mensagens = chatState.aiRioMessages || [];
  if (!mensagens.length) {
    box.innerHTML = `<div class='chat-empty'><div class='chat-empty-title'>I.A-Rio pronta para conversar</div><div class='chat-empty-text'>Escreva algo para iniciar a conversa.</div></div>`;
    return;
  }
  box.innerHTML = "";
  mensagens.forEach((message) => {
    box.appendChild(_chatAIRioBuildMessageBox(message));
  });
  box.scrollTop = box.scrollHeight;
}

function _chatAIRioAppendMessage(message){
  chatState.aiRioMessages.push(_chatAIRioNormalizeMessage(message));
  chatState.aiRioMessages = chatState.aiRioMessages.slice(-60);
  _chatAIRioPersistState();
  _chatAIRioRenderConversation();
}

function _chatAIRioReplaceLastAgentMessage(message){
  const msgs = chatState.aiRioMessages || [];
  for (let i = msgs.length - 1; i >= 0; i -= 1) {
    if (msgs[i].role === "agent") {
      msgs[i] = _chatAIRioNormalizeMessage(message);
      chatState.aiRioMessages = msgs.slice(-60);
      _chatAIRioPersistState();
      _chatAIRioRenderConversation();
      return msgs[i];
    }
  }
  return null;
}

function _chatAIRioSetPending(text = "Pensando..."){
  const msgs = chatState.aiRioMessages || [];
  const last = msgs[msgs.length - 1];
  if (!last || last.role !== "agent" || !last.pending) {
    msgs.push(_chatAIRioNormalizeMessage({ role: "agent", text, pending: true }));
  } else {
    last.text = text;
    last.pending = true;
  }
  chatState.aiRioMessages = msgs.slice(-60);
  _chatAIRioPersistState();
  _chatAIRioRenderConversation();
}

function _chatAIRioFinalize(replyText, output = ""){
  const msgs = chatState.aiRioMessages || [];
  const last = msgs[msgs.length - 1];
  const finalText = String(replyText || output || "Sem resposta.").trim();
  if (last && last.role === "agent" && last.pending) {
    last.text = finalText;
    last.output = String(output || "").trim();
    last.pending = false;
  } else {
    msgs.push(_chatAIRioNormalizeMessage({ role: "agent", text: finalText, output, pending: false }));
  }
  chatState.aiRioMessages = msgs.slice(-60);
  _chatAIRioPersistState();
  _chatAIRioRenderConversation();
}

function _chatFriendlyHttpError(status, rawText) {
  const code = Number(status || 0);
  const text = String(rawText || "").trim();
  if (code === 504) return "Tempo limite ao consultar a I.A-Rio. Tente novamente com uma pergunta mais objetiva.";
  if (code >= 500) return `Falha HTTP ${code} ao consultar a I.A-Rio.`;
  if (!text) return `Falha HTTP ${code || "desconhecida"} ao consultar a I.A-Rio.`;
  if (/<html[\s>]/i.test(text)) return `Falha HTTP ${code || "desconhecida"} ao consultar a I.A-Rio.`;
  return text;
}

function _chatBuildSendingBubble(mensagem = "", anexo = null) {
  const box = document.createElement("div");
  box.className = "chat-item me chat-item-sending";
  const texto = String(mensagem || "").trim();
  const temAnexo = !!anexo;
  box.innerHTML = `
    ${texto ? `<div class="chat-item-text">${_chatMensagemHtml(texto)}</div>` : ""}
    ${temAnexo ? `<div class="chat-item-text chat-item-sending-attachment">Enviando anexo...</div>` : ""}
    <small class="chat-item-meta">
      <span class="chat-item-sending-label">Enviando</span>
      <span class="chat-item-sending-dots" aria-hidden="true"><span></span><span></span><span></span></span>
    </small>
  `;
  return box;
}

function _chatMostrarEnviando(mensagem = "", anexo = null) {
  const box = document.getElementById("chatMensagens");
  if (!box) return null;
  _chatRemoverEnviando();
  const bubble = _chatBuildSendingBubble(mensagem, anexo);
  chatState.pendingSendBubble = bubble;
  box.appendChild(bubble);
  box.scrollTop = box.scrollHeight;
  chatState.sendingMessage = true;
  atualizarEstadoEnvioChat();
  return bubble;
}

function _chatRemoverEnviando() {
  if (chatState.pendingSendBubble) {
    try { chatState.pendingSendBubble.remove(); } catch {}
    chatState.pendingSendBubble = null;
  }
  chatState.sendingMessage = false;
  atualizarEstadoEnvioChat();
}

function _sipSetStatus(text, level = "warn") {
  sipState.statusText = text || "SIP indisponivel.";
  sipState.statusLevel = level || "warn";
  const el = document.getElementById("chatSipStatus");
  if (el) {
    el.textContent = sipState.statusText;
    el.classList.remove("ok", "warn", "error");
    el.classList.add(sipState.statusLevel);
  }
  atualizarStatusSipSistema(statusState.sip);
}

function _sipAudioEl() {
  return document.getElementById("sipRemoteAudio");
}

function _sipResetAudio() {
  const el = _sipAudioEl();
  if (!el) return;
  try { el.pause(); } catch {}
  try { el.srcObject = null; } catch {}
}

function _sipClearConnectWatchdog() {
  if (sipState.connectWatchdog) {
    try { clearTimeout(sipState.connectWatchdog); } catch {}
    sipState.connectWatchdog = null;
  }
}

function _sipArmConnectWatchdog(ua) {
  _sipClearConnectWatchdog();
  sipState.connectTimedOut = false;
  sipState.connectWatchdog = setTimeout(() => {
    if (sipState.ua !== ua || sipState.isConnected || sipState.isRegistered) return;
    sipState.connectTimedOut = true;
    try { ua.stop(); } catch {}
    _sipSetStatus("Timeout ao conectar no WebSocket SIP. Verifique WSS/TLS no FreePBX.", "error");
    atualizarEstadoSipChat();
  }, 12000);
}

function _sipContatoAtual() {
  const usuarios = cacheUsuarios || [];
  return usuarios.find((u) => String(u.id) === String(chatState.contatoId)) || null;
}

function _sipSanitizarDestino(raw) {
  const original = String(raw || "").trim();
  if (!original) return "";
  if (/^sip:/i.test(original) || original.includes("@")) return original;
  const compactado = original.replace(/[\s().-]+/g, "");
  return /^[+\d*#]+$/.test(compactado) ? compactado : original;
}

function _sipDestinoManual() {
  return _sipSanitizarDestino(document.getElementById("chatSipManualNumber")?.value || "");
}

function _sipDestinoBruto(contato) {
  return String(contato?.sip_ramal || contato?.sip_usuario || "").trim();
}

function _sipPodeDiscarExterno() {
  return !!sipState.me?.sip_habilitado;
}

function _sipChaveInterna(raw) {
  let value = String(raw || "").trim();
  if (!value) return "";
  value = value.replace(/^sip:/i, "");
  value = value.split(";")[0].split("?")[0];
  if (value.includes("@")) value = value.split("@")[0];
  return value.trim().toLowerCase();
}

function _sipDestinoEhInterno(raw) {
  const key = _sipChaveInterna(raw);
  if (!key) return false;
  if (/^\d{4}$/.test(key)) return true;
  const usuarios = cacheUsuarios || [];
  return usuarios.some((u) => {
    const ramal = _sipChaveInterna(u?.sip_ramal || "");
    const usuarioSip = _sipChaveInterna(u?.sip_usuario || u?.login || "");
    return key === ramal || key === usuarioSip;
  });
}

function _sipNormalizarUri(raw, domain = "") {
  let value = String(raw || "").trim();
  if (!value) return "";
  if (/^sip:/i.test(value)) return value;
  if (value.includes("@")) return `sip:${value}`;
  if (domain) return `sip:${value}@${domain}`;
  return value;
}

function _sipAuthUser(raw) {
  const value = String(raw || "").trim().replace(/^sip:/i, "");
  return value.split("@")[0] || value;
}

function _sipDisplayName() {
  const template = String(sipState.profile?.caller_id_template || "{nome} RioBranco").trim() || "{nome} RioBranco";
  const nome = String(sipState.me?.nome || "").trim() || String(sipState.me?.login || "").trim() || _sipAuthUser(sipState.me?.sip_usuario || "");
  const login = String(sipState.me?.login || "").trim();
  const ramal = String(sipState.me?.sip_ramal || sipState.me?.sip_usuario || "").trim();
  return template
    .replaceAll("{nome}", nome)
    .replaceAll("{login}", login)
    .replaceAll("{ramal}", ramal)
    .replace(/\s+/g, " ")
    .trim();
}

function _sipIceServers(cfg = {}) {
  const servers = [];
  const stunServers = String(cfg.stun_servers || "")
    .split(/\r?\n|,/)
    .map((s) => s.trim())
    .filter(Boolean);
  for (const url of stunServers) {
    servers.push({ urls: url });
  }
  const turnUrl = String(cfg.turn_url || "").trim();
  if (turnUrl) {
    const turn = { urls: turnUrl };
    const username = String(cfg.turn_usuario || "").trim();
    const credential = String(cfg.turn_senha || "").trim();
    if (username) turn.username = username;
    if (credential) turn.credential = credential;
    servers.push(turn);
  }
  return servers;
}

function _sipExtraHeaders() {
  const proxy = String(sipState.profile?.outbound_proxy || "").trim();
  if (!proxy) return [];
  let route = proxy;
  if (!route.includes("<")) {
    if (!/^sip:/i.test(route)) route = `sip:${route}`;
    if (!/;lr$/i.test(route)) route = `${route};lr`;
    route = `<${route}>`;
  }
  return [`Route: ${route}`];
}

function _sipCallOptions() {
  return {
    mediaConstraints: { audio: true, video: false },
    rtcOfferConstraints: { offerToReceiveAudio: 1, offerToReceiveVideo: 0 },
    pcConfig: { iceServers: _sipIceServers(sipState.profile) },
    extraHeaders: _sipExtraHeaders(),
    sessionTimersExpires: 120,
  };
}

function _sipAttachRemoteAudio(session) {
  const audio = _sipAudioEl();
  const pc = session?.connection;
  if (!audio || !pc) return;
  const mixedStream = new MediaStream();

  const playFrom = (stream) => {
    if (!stream) return;
    audio.srcObject = stream;
    audio.play().catch(() => {});
  };

  try {
    const remoteStreams = pc.getRemoteStreams?.() || [];
    if (remoteStreams[0]) playFrom(remoteStreams[0]);
  } catch {}

  try {
    pc.addEventListener("track", (ev) => {
      if (ev.streams && ev.streams[0]) {
        playFrom(ev.streams[0]);
        return;
      }
      if (ev.track) {
        mixedStream.addTrack(ev.track);
        playFrom(mixedStream);
      }
    });
  } catch {}
}

function _sipClearCurrentSession(finalText = "", finalLevel = "warn") {
  _sipPararTons();
  sipState.currentSession = null;
  sipState.currentDirection = "";
  sipState.currentTargetLabel = "";
  sipState.dtmfHistory = "";
  sipState.isEndingCall = false;
  _sipResetAudio();
  if (finalText) _sipSetStatus(finalText, finalLevel);
  atualizarEstadoSipChat();
}

function _sipResolverStatusEncerramento(direction, label, event, wasConnected = false) {
  const nome = String(label || "").trim() || "o destino";
  const originator = String(event?.originator || "").trim().toLowerCase();
  const cause = String(event?.cause || "").trim();
  const causes = JsSIP?.C?.causes || {};
  const remoteRejected = originator === "remote" && direction === "outgoing" && !wasConnected;
  const localRejected = originator === "local" && direction === "incoming" && !wasConnected;
  const callFinished = wasConnected || cause === causes.BYE || cause === "Terminated";

  if (remoteRejected) {
    return { text: `Chamada rejeitada por ${nome}.`, level: "warn" };
  }
  if (localRejected) {
    return { text: `Chamada rejeitada${label ? ` de ${nome}` : ""}.`, level: "warn" };
  }
  if (callFinished || originator === "remote" || originator === "local") {
    return {
      text: originator === "remote"
        ? `Chamada finalizada por ${nome}.`
        : `Chamada finalizada${label ? ` com ${nome}` : ""}.`,
      level: "warn",
    };
  }
  if (cause) {
    return { text: `Falha na chamada com ${nome}: ${cause}.`, level: "error" };
  }
  return { text: `Chamada finalizada${label ? ` com ${nome}` : ""}.`, level: "warn" };
}

function _sipBindSession(session, direction, targetLabel = "") {
  if (!session) return;
  sipState.currentSession = session;
  sipState.currentDirection = direction || "";
  sipState.currentTargetLabel = targetLabel || "";
  sipState.dtmfHistory = "";
  _sipAttachRemoteAudio(session);
  atualizarEstadoSipChat();

  const label = sipState.currentTargetLabel || "destino";
  const stillCurrent = () => sipState.currentSession === session;
  let wasConnected = false;

  session.on("progress", () => {
    if (!stillCurrent()) return;
    if (direction === "outgoing") _sipTocarTomDiscagem();
    const txt = direction === "incoming"
      ? `Chamada recebida de ${label}.`
      : `Chamando ${label}...`;
    _sipSetStatus(txt, "warn");
    atualizarEstadoSipChat();
  });
  session.on("accepted", () => {
    if (!stillCurrent()) return;
    _sipPararTons();
    wasConnected = true;
    _sipSetStatus(`Ligacao aceita com ${label}.`, "ok");
    atualizarEstadoSipChat();
  });
  session.on("confirmed", () => {
    if (!stillCurrent()) return;
    _sipPararTons();
    wasConnected = true;
    _sipSetStatus(`Em chamada com ${label}.`, "ok");
    atualizarEstadoSipChat();
  });
  session.on("ended", (event) => {
    if (!stillCurrent()) return;
    const finalStatus = _sipResolverStatusEncerramento(direction, label, event, wasConnected);
    _sipClearCurrentSession(finalStatus.text, finalStatus.level);
  });
  session.on("failed", (event) => {
    if (!stillCurrent()) return;
    const finalStatus = _sipResolverStatusEncerramento(direction, label, event, wasConnected);
    _sipClearCurrentSession(finalStatus.text, finalStatus.level);
  });
}

function stopSipClient(clearProfile = false) {
  _sipPararTons();
  _sipClearConnectWatchdog();
  if (sipState.currentSession) {
    try { sipState.currentSession.terminate(); } catch {}
  }
  if (sipState.ua) {
    try { sipState.ua.stop(); } catch {}
  }
  sipState.ua = null;
  sipState.currentSession = null;
  sipState.currentDirection = "";
  sipState.currentTargetLabel = "";
  sipState.dtmfHistory = "";
  sipState.isEndingCall = false;
  sipState.isConnected = false;
  sipState.isRegistered = false;
  sipState._sessionKey = "";
  sipState.initPromise = null;
  sipState.connectTimedOut = false;
  if (clearProfile) {
    sipState.authRepairPromise = null;
    sipState.config = null;
    sipState.me = null;
    sipState.profile = null;
    sipState.mode = "freepbx";
    sipState.lastAuthRepairKey = "";
    _sipSetStatus("SIP indisponivel.", "warn");
  }
  _sipResetAudio();
  atualizarEstadoSipChat();
}

function enviarTomSip(tone) {
  const tom = String(tone || "").trim();
  const session = sipState.currentSession;
  const estabelecida = !!session?.isEstablished?.() && !session?.isEnded?.();
  if (!tom || !estabelecida) {
    atualizarEstadoSipChat();
    return;
  }
  try {
    session.sendDTMF(tom);
    sipState.dtmfHistory = `${sipState.dtmfHistory || ""}${tom}`.slice(-24);
    _sipSetStatus(`Tom ${tom} enviado para ${sipState.currentTargetLabel || "a chamada"}.`, "ok");
  } catch (err) {
    _sipSetStatus(`Falha ao enviar tom ${tom}: ${err?.message || err}.`, "error");
  }
  atualizarEstadoSipChat();
}

async function initSipClient(force = false) {
  if (!window.JsSIP) {
    _sipSetStatus("Biblioteca SIP nao carregada.", "error");
    atualizarEstadoSipChat();
    return false;
  }
  if (!chatState.usuarioId) {
    stopSipClient(true);
    return false;
  }
  if (sipState.initPromise && !force) return sipState.initPromise;

  sipState.initPromise = (async () => {
    const resp = await apiFetch(`/api/sip/me?usuario_id=${encodeURIComponent(chatState.usuarioId)}`);
    if (!resp.ok) {
      stopSipClient(false);
      _sipSetStatus("Nao foi possivel carregar o perfil SIP do usuario.", "error");
      return false;
    }

    const data = await resp.json().catch(() => ({}));
    sipState.config = data?.config || {};
    sipState.me = data?.usuario || {};
    sipState.mode = String(sipState.config?.modo_ativo || "freepbx").trim() || "freepbx";
    sipState.profile = sipState.config?.[sipState.mode] || {};

    const wsUrl = String(sipState.profile?.ws_url || "").trim();
    const domain = String(sipState.profile?.dominio || "").trim();
    const sipAuthUser = String(sipState.me?.sip_usuario || sipState.me?.login || "").trim();
    const sipUriUser = String(sipState.me?.sip_ramal || sipState.me?.sip_usuario || "").trim();
    const sipPass = String(sipState.me?.sip_senha || "").trim();
    const enabled = !!sipState.config?.habilitado;
    const modeLabel = sipState.mode === "setevoip_direto" ? "SeteVoIP Direto" : "FreePBX";

    if (!enabled) {
      stopSipClient(false);
      _sipSetStatus("SIP desativado na configuracao do sistema.", "warn");
      return false;
    }
    if (!wsUrl || !domain) {
      stopSipClient(false);
      _sipSetStatus(`Preencha WSS e dominio SIP para o modo ${modeLabel}.`, "warn");
      return false;
    }
    if (!sipUriUser || !sipAuthUser || !sipPass) {
      stopSipClient(false);
      _sipSetStatus("Credenciais SIP do usuario ainda nao foram provisionadas. Faca login novamente ou informe a senha SIP no cadastro.", "warn");
      return false;
    }

    const sessionKey = JSON.stringify({
      mode: sipState.mode,
      wsUrl,
      domain,
      sipUriUser,
      sipAuthUser,
      sipPass,
      registrar: sipState.profile?.registrar_server || "",
      autoRegister: !!sipState.profile?.auto_register,
    });

    if (!force && sipState.ua && sipState._sessionKey === sessionKey) {
      atualizarEstadoSipChat();
      return true;
    }

    stopSipClient(false);

    try {
      const socket = new window.JsSIP.WebSocketInterface(wsUrl);
      const ua = new window.JsSIP.UA({
        sockets: [socket],
        uri: _sipNormalizarUri(sipUriUser, domain),
        password: sipPass,
        authorization_user: _sipAuthUser(sipAuthUser),
        display_name: _sipDisplayName(),
        registrar_server: sipState.profile?.registrar_server || undefined,
        register: !!sipState.profile?.auto_register,
        session_timers: false,
      });

      ua.on("connecting", () => {
        sipState.isConnected = false;
        _sipSetStatus("Conectando ao servidor SIP...", "warn");
        atualizarEstadoSipChat();
      });
      ua.on("connected", () => {
        _sipClearConnectWatchdog();
        sipState.connectTimedOut = false;
        sipState.isConnected = true;
        if (!sipState.profile?.auto_register) {
          _sipSetStatus(`SIP conectado em ${modeLabel} como ${sipState.me?.sip_usuario || sipState.me?.login || "usuario"}.`, "ok");
        }
        atualizarEstadoSipChat();
      });
      ua.on("disconnected", () => {
        _sipClearConnectWatchdog();
        sipState.isConnected = false;
        sipState.isRegistered = false;
        if (!sipState.currentSession) {
          if (sipState.connectTimedOut) {
            _sipSetStatus("Timeout ao conectar no WebSocket SIP. Verifique WSS/TLS no FreePBX.", "error");
          } else {
            _sipSetStatus("SIP desconectado do servidor.", "error");
          }
        }
        sipState.connectTimedOut = false;
        atualizarEstadoSipChat();
      });
      ua.on("registered", () => {
        _sipClearConnectWatchdog();
        sipState.connectTimedOut = false;
        sipState.isRegistered = true;
        sipState.lastAuthRepairKey = "";
        _sipSetStatus(`SIP registrado em ${modeLabel} como ${sipState.me?.sip_usuario || sipState.me?.login || "usuario"}.`, "ok");
        atualizarEstadoSipChat();
      });
      ua.on("unregistered", () => {
        _sipClearConnectWatchdog();
        sipState.isRegistered = false;
        if (!sipState.currentSession) {
          const txt = sipState.profile?.auto_register
            ? "SIP desconectado."
            : "SIP pronto para chamadas sem registro automatico.";
          _sipSetStatus(txt, sipState.profile?.auto_register ? "warn" : "ok");
        }
        atualizarEstadoSipChat();
      });
      ua.on("registrationFailed", (e) => {
        _sipClearConnectWatchdog();
        sipState.connectTimedOut = false;
        sipState.isRegistered = false;
        const cause = String(e?.cause || "erro desconhecido");
        if (_sipPodeTentarReparoAuth(cause, sessionKey)) {
          _sipRepararAuthERegistrar(sessionKey, modeLabel).catch(() => {});
          return;
        }
        _sipSetStatus(`Falha no registro SIP: ${cause}.`, "error");
        atualizarEstadoSipChat();
      });
      ua.on("newRTCSession", ({ originator, session }) => {
        if (originator === "local") return;
        if (sipState.currentSession && sipState.currentSession !== session) {
          try { session.terminate({ status_code: 486, reason_phrase: "Busy Here" }); } catch {}
          return;
        }
        const label = session?.remote_identity?.display_name
          || session?.remote_identity?.uri?.user
          || "origem desconhecida";
        _sipBindSession(session, "incoming", label);
        _sipTocarToqueEntrada();
        _sipSetStatus(`Chamada recebida de ${label}.`, "warn");
      });

      sipState.ua = ua;
      sipState._sessionKey = sessionKey;
      _sipArmConnectWatchdog(ua);
      ua.start();
      _sipSetStatus("Inicializando SIP...", "warn");
      atualizarEstadoSipChat();
      return true;
    } catch (err) {
      stopSipClient(false);
      _sipSetStatus(`Falha ao iniciar SIP: ${err?.message || err}.`, "error");
      return false;
    }
  })();

  try {
    return await sipState.initPromise;
  } finally {
    sipState.initPromise = null;
  }
}

function atualizarEstadoSipChat() {
  const statusEl = document.getElementById("chatSipStatus");
  const callBtn = document.getElementById("chatSipCallBtn");
  const externalToggleBtn = document.getElementById("chatSipExternalToggleBtn");
  const dialerWrap = document.getElementById("chatSipDialerWrap");
  const manualCallBtn = document.getElementById("chatSipManualCallBtn");
  const manualCloseBtn = document.getElementById("chatSipManualCloseBtn");
  const answerBtn = document.getElementById("chatSipAnswerBtn");
  const rejectBtn = document.getElementById("chatSipRejectBtn");
  const hangupBtn = document.getElementById("chatSipHangupBtn");
  const activePanel = document.getElementById("chatSipActivePanel");
  const dtmfPanel = document.getElementById("chatSipDtmfPanel");
  const activeLabelEl = document.getElementById("chatSipActiveLabel");
  const dtmfFeedbackEl = document.getElementById("chatSipDtmfFeedback");
  const hangupMainBtn = document.getElementById("chatSipHangupMainBtn");
  const dtmfButtons = document.querySelectorAll("[data-sip-dtmf]");
  const contato = _sipContatoAtual();
  const destino = _sipDestinoBruto(contato);
  const destinoManual = _sipDestinoManual();
  const destinoInterno = _sipDestinoEhInterno(destino);
  const destinoManualInterno = _sipDestinoEhInterno(destinoManual);
  const hasActiveSession = !!sipState.currentSession;
  const incomingPending = hasActiveSession && sipState.currentDirection === "incoming" && !!sipState.currentSession?.isInProgress?.();
  const callEstablished = hasActiveSession && !!sipState.currentSession?.isEstablished?.() && !sipState.currentSession?.isEnded?.();
  const externalEnabled = _sipPodeDiscarExterno();
  const readyToDial = !!sipState.ua && (sipState.isConnected || sipState.isRegistered);
  if (hasActiveSession && chatState.showExternalDialer) chatState.showExternalDialer = false;
  if (!externalEnabled && chatState.showExternalDialer) chatState.showExternalDialer = false;
  const canCall = !!chatState.usuarioId && readyToDial && !hasActiveSession && !!destino && (_sipPodeDiscarExterno() || destinoInterno);
  const canManualCall = !!chatState.usuarioId && readyToDial && !hasActiveSession && !!destinoManual && (_sipPodeDiscarExterno() || destinoManualInterno);

  if (callBtn) {
    callBtn.disabled = !canCall;
    callBtn.title = !chatState.contatoId
      ? "Selecione um contato"
      : (!destino
          ? "Contato sem ramal SIP configurado"
          : ((!_sipPodeDiscarExterno() && !destinoInterno) ? "Seu usuario pode ligar apenas para ramais internos" : ""));
  }
  if (externalToggleBtn) {
    externalToggleBtn.classList.toggle("hidden", !externalEnabled);
    externalToggleBtn.disabled = !externalEnabled || !chatState.usuarioId || hasActiveSession;
    externalToggleBtn.textContent = chatState.showExternalDialer ? "Ocultar externo" : "Discar externo";
    externalToggleBtn.title = hasActiveSession
      ? "Finalize a chamada atual para abrir o discador externo"
      : "Abrir discador manual para numero externo, ramal ou URI SIP";
  }
  if (dialerWrap) {
    dialerWrap.classList.toggle("hidden", !externalEnabled || !chatState.showExternalDialer || hasActiveSession);
  }
  if (manualCallBtn) {
    manualCallBtn.disabled = !canManualCall;
    manualCallBtn.title = !destinoManual
      ? "Digite um numero, ramal ou URI SIP"
      : ((!_sipPodeDiscarExterno() && !destinoManualInterno) ? "Seu usuario pode discar apenas ramais internos" : "");
  }
  if (manualCloseBtn) manualCloseBtn.disabled = hasActiveSession;
  if (answerBtn) answerBtn.classList.toggle("hidden", !incomingPending);
  if (rejectBtn) rejectBtn.classList.toggle("hidden", !incomingPending);
  if (hangupBtn) hangupBtn.classList.toggle("hidden", !hasActiveSession || incomingPending);
  if (hangupMainBtn) hangupMainBtn.disabled = !hasActiveSession;

  if (activePanel) {
    activePanel.classList.toggle("hidden", !hasActiveSession);
  }
  if (dtmfPanel) {
    dtmfPanel.classList.toggle("hidden", !callEstablished);
  }
  if (activeLabelEl) {
    const label = sipState.currentTargetLabel || "destino";
    let activeText = "Nenhuma chamada em andamento.";
    if (incomingPending) {
      activeText = `Chamada recebida de ${label}.`;
    } else if (sipState.isEndingCall) {
      activeText = `Encerrando ligacao com ${label}...`;
    } else if (callEstablished) {
      activeText = `Em chamada com ${label}.`;
    } else if (hasActiveSession) {
      activeText = `Chamando ${label}...`;
    }
    activeLabelEl.textContent = activeText;
  }
  if (dtmfFeedbackEl) {
    dtmfFeedbackEl.textContent = !hasActiveSession
      ? "O teclado aparece durante a chamada."
      : (callEstablished
          ? (sipState.dtmfHistory ? `Tons enviados: ${sipState.dtmfHistory}` : "Use o teclado abaixo quando a central pedir digitos.")
          : "O teclado DTMF fica ativo depois que a chamada for atendida.");
  }
  for (const btn of dtmfButtons) {
    btn.disabled = !callEstablished;
  }

  if (statusEl) {
    let text = sipState.statusText || "SIP indisponivel.";
    let level = sipState.statusLevel || "warn";
    if (!hasActiveSession && !!sipState.ua && chatState.contatoId && !destino) {
      text = "Contato selecionado sem ramal SIP configurado.";
      level = "warn";
    } else if (!hasActiveSession && !!sipState.ua && chatState.contatoId && destino && !_sipPodeDiscarExterno() && !destinoInterno) {
      text = "Seu usuario pode ligar apenas para ramais internos.";
      level = "warn";
    } else if (!hasActiveSession && !!sipState.ua && destinoManual && !_sipPodeDiscarExterno() && !destinoManualInterno) {
      text = "Discagem externa bloqueada para este usuario.";
      level = "warn";
    }
    statusEl.textContent = text;
    statusEl.classList.remove("ok", "warn", "error");
    statusEl.classList.add(level);
  }
  atualizarStatusSipSistema(statusState.sip);
}

async function _iniciarChamadaSipDestino(destinoRaw, label) {
  if (!chatState.usuarioId) return false;
  const pronto = await initSipClient().catch(() => false);
  if (!pronto || !sipState.ua) {
    atualizarEstadoSipChat();
    return false;
  }
  if (sipState.currentSession) {
    alert("Ja existe uma chamada SIP em andamento.");
    return false;
  }

  const destinoLimpo = _sipSanitizarDestino(destinoRaw);
  if (!destinoLimpo) {
    _sipSetStatus("Informe um numero, ramal ou URI SIP valida.", "warn");
    atualizarEstadoSipChat();
    return false;
  }

  const destinoInterno = _sipDestinoEhInterno(destinoLimpo);
  if (!destinoInterno && !_sipPodeDiscarExterno()) {
    alert("Seu usuario pode discar apenas ramais internos.");
    atualizarEstadoSipChat();
    return false;
  }

  const prefixo = String(sipState.profile?.prefixo_saida || "").trim();
  const destinoComPrefixo = (!destinoInterno && !/^sip:/i.test(destinoLimpo) && !String(destinoLimpo).includes("@") && prefixo)
    ? `${prefixo}${destinoLimpo}`
    : destinoLimpo;
  const target = _sipNormalizarUri(destinoComPrefixo, String(sipState.profile?.dominio || "").trim());

  try {
    const session = sipState.ua.call(target, _sipCallOptions());
    _sipBindSession(session, "outgoing", label);
    _sipSetStatus(`Discando para ${label}...`, "warn");
    return true;
  } catch (err) {
    _sipSetStatus(`Falha ao iniciar chamada: ${err?.message || err}.`, "error");
    atualizarEstadoSipChat();
    return false;
  }
}

function toggleChatSipExternalPanel(force) {
  const next = force === undefined ? !chatState.showExternalDialer : !!force;
  if (next && !_sipPodeDiscarExterno()) {
    chatState.showExternalDialer = false;
    atualizarEstadoSipChat();
    return;
  }
  if (next && !chatState.usuarioId) return;
  chatState.showExternalDialer = next;
  const input = document.getElementById("chatSipManualNumber");
  if (!next && input) input.value = "";
  atualizarEstadoSipChat();
  if (next) {
    initSipClient().catch(() => {});
    setTimeout(() => {
      try { input?.focus(); } catch {}
    }, 40);
  }
}

async function iniciarChamadaSipChat() {
  if (!chatState.usuarioId || !chatState.contatoId) return;
  const contato = _sipContatoAtual();
  const destinoRaw = _sipDestinoBruto(contato);
  if (!destinoRaw) {
    alert("Este contato nao possui ramal SIP configurado.");
    atualizarEstadoSipChat();
    return;
  }
  await _iniciarChamadaSipDestino(destinoRaw, contato?.nome || destinoRaw);
}

async function iniciarChamadaSipManual() {
  if (!chatState.usuarioId) return;
  const destinoRaw = _sipDestinoManual();
  if (!destinoRaw) {
    alert("Informe um numero, ramal ou URI SIP para discagem manual.");
    atualizarEstadoSipChat();
    return;
  }
  const ok = await _iniciarChamadaSipDestino(destinoRaw, destinoRaw);
  if (ok) toggleChatSipExternalPanel(false);
}

function atenderChamadaSip() {
  const session = sipState.currentSession;
  if (!session || sipState.currentDirection !== "incoming") return;
  try {
    session.answer(_sipCallOptions());
    _sipSetStatus(`Atendendo ${sipState.currentTargetLabel || "chamada"}...`, "warn");
    atualizarEstadoSipChat();
  } catch (err) {
    _sipSetStatus(`Falha ao atender chamada: ${err?.message || err}.`, "error");
    atualizarEstadoSipChat();
  }
}

function recusarChamadaSip() {
  const session = sipState.currentSession;
  if (!session) return;
  sipState.isEndingCall = true;
  try {
    session.terminate({ status_code: 486, reason_phrase: "Busy Here" });
  } catch {}
  _sipSetStatus(`Recusando chamada${sipState.currentTargetLabel ? ` de ${sipState.currentTargetLabel}` : ""}...`, "warn");
  atualizarEstadoSipChat();
}

function encerrarChamadaSip() {
  const session = sipState.currentSession;
  if (!session) return;
  sipState.isEndingCall = true;
  try {
    session.terminate();
  } catch {}
  _sipSetStatus(`Encerrando ligacao${sipState.currentTargetLabel ? ` com ${sipState.currentTargetLabel}` : ""}...`, "warn");
  atualizarEstadoSipChat();
}

function atualizarEstadoEnvioChat() {
  const btn = document.getElementById("chatEnviarBtn");
  const input = document.getElementById("chatTexto");
  const attachBtn = document.getElementById("chatAnexoBtn");
  const attachInput = document.getElementById("chatAnexoInput");
  const ok = !!chatState.usuarioId && !!chatState.contatoId;
  const sending = !!chatState.sendingMessage;
  const allowAttachment = ok && !_chatEhContatoAIRio();
  if (btn) btn.disabled = !ok || sending;
  if (btn) btn.textContent = sending ? "Enviando..." : "Enviar";
  if (input) input.disabled = !ok;
  if (attachBtn) attachBtn.disabled = !allowAttachment;
  if (attachInput) attachInput.disabled = !allowAttachment;
  atualizarEstadoSipChat();
}

function atualizarCabecalhoChat() {
  const nomeEl = document.getElementById("chatContatoAtualNome");
  const statusEl = document.getElementById("chatContatoAtualStatus");
  const avatarEl = document.getElementById("chatContatoAvatar");
  if (!nomeEl) return;
  if (_chatEhContatoAIRio()) {
    nomeEl.textContent = CHAT_AI_RIO_NAME;
    if (statusEl) statusEl.textContent = "Assistente da equipe";
    if (avatarEl) avatarEl.textContent = "IA";
    atualizarEstadoSipChat();
    return;
  }
  const contato = _sipContatoAtual();
  nomeEl.textContent = contato?.nome || "Selecione um contato";
  if (statusEl) statusEl.textContent = _chatResumoContato(contato);
  if (avatarEl) avatarEl.textContent = contato ? _chatIniciais(contato.nome) : "--";
  atualizarEstadoSipChat();
}

function atualizarBadgeFab(total) {
  const badge = document.getElementById("chatFabBadge");
  if (!badge) return;
  const qtd = Number(total || 0);
  if (qtd > 0) {
    badge.textContent = qtd > 99 ? "99+" : String(qtd);
    badge.classList.remove("hidden");
  } else {
    badge.classList.add("hidden");
  }
}

function atualizarBadgeFabDoMapa() {
  const mapa = chatState.unreadByContato || {};
  const total = Object.values(mapa).reduce((acc, v) => acc + Number(v || 0), 0);
  atualizarBadgeFab(total);
}

async function carregarNaoLidasChat() {
  if (!chatState.usuarioId) return;
  const reqSeq = ++chatState.unreadReqSeq;
  const r = await apiFetch(`/api/chat/unread?usuario_id=${encodeURIComponent(chatState.usuarioId)}`);
  if (!r.ok) return;
  const j = await r.json();
  if (reqSeq < chatState.unreadAppliedSeq) return;
  chatState.unreadAppliedSeq = reqSeq;
  const mapa = {};
  for (const item of (j.por_contato || [])) {
    mapa[String(item.remetente_id)] = Number(item.total || 0);
  }
  chatState.unreadByContato = mapa;
  atualizarBadgeFab(j.total_mensagens_nao_lidas ?? j.total ?? 0);
  renderListaContatosChat();
}

async function marcarLidasContatoChat(contatoId) {
  const cid = String(contatoId || chatState.contatoId || "");
  if (!chatState.usuarioId || !cid) return;

  if (!chatState.unreadByContato) chatState.unreadByContato = {};

  // Atualiza UI imediatamente para evitar badge "preso"
  chatState.unreadAppliedSeq = Math.max(chatState.unreadAppliedSeq, chatState.unreadReqSeq + 1);
  chatState.unreadByContato[cid] = 0;
  renderListaContatosChat();
  atualizarBadgeFabDoMapa();

  const resp = await apiFetch("/api/chat/marcar_lidas", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      usuario_id: Number(chatState.usuarioId),
      contato_id: Number(cid),
    }),
  });
  if (resp.ok) {
    const j = await resp.json().catch(() => null);
    if (j && j.total_mensagens_nao_lidas !== undefined) {
      atualizarBadgeFab(j.total_mensagens_nao_lidas);
    }
  }
  renderListaContatosChat();
}

function renderListaContatosChat() {
  const wrap = document.getElementById("chatContatosLista");
  if (!wrap) return;

  const usuarios = cacheUsuarios || [];
  const eu = String(chatState.usuarioId || "");
  const contatos = [
    {
      id: CHAT_AI_RIO_CONTACT_ID,
      nome: CHAT_AI_RIO_NAME,
      login: "ia-rio",
      sip_ramal: "",
      sip_usuario: "",
      ativo: true,
      codbar_modo: "bip",
      is_ai_rio: true,
    },
    ...usuarios.filter((u) => String(u.id) !== eu),
  ];

  if (!eu) {
    wrap.innerHTML = `<div class="hint">Faca login para usar o chat.</div>`;
    atualizarBadgeFabDoMapa();
    atualizarEstadoSipChat();
    return;
  }
  if (!contatos.length) {
    wrap.innerHTML = `<div class="hint">Nao ha outros usuarios cadastrados.</div>`;
    atualizarBadgeFabDoMapa();
    atualizarEstadoSipChat();
    return;
  }

  wrap.innerHTML = contatos.map((u) => {
    const uid = String(u.id);
    const active = String(chatState.contatoId) === uid ? "active" : "";
    const qtd = Number(chatState.unreadByContato?.[uid] || 0);
    const badge = qtd > 0 && !u.is_ai_rio ? `<span class="chat-contato-badge">${qtd > 99 ? "99+" : qtd}</span>` : "";
    const subtitulo = u.is_ai_rio
      ? "Assistente da equipe"
      : (qtd > 0
        ? `${qtd} ${qtd === 1 ? "mensagem nao lida" : "mensagens nao lidas"}`
        : (u.sip_ramal ? `Ramal ${_escHtml(String(u.sip_ramal))}` : (u.login ? `Login ${_escHtml(String(u.login))}` : "Clique para conversar")));
    return `
      <button type="button" class="chat-contato ${active}${u.is_ai_rio ? " chat-contato-ai" : ""}" onclick='selecionarContatoChat(${JSON.stringify(uid)})' title="Abrir conversa com ${_escHtml(u.nome)}">
        <span class="chat-contato-avatar">${_chatIniciais(u.nome)}</span>
        <span class="chat-contato-textos">
          <span class="chat-contato-nome">${_escHtml(u.nome)}</span>
          <span class="chat-contato-desc">${subtitulo}</span>
        </span>
        <span class="chat-contato-meta">${badge}</span>
      </button>
    `;
  }).join("");

  // Mantem o badge do botao sempre em sincronia com a lista local.
  atualizarBadgeFabDoMapa();
  atualizarEstadoSipChat();
}

async function carregarUsuariosChat(manterSelecao = true) {
  if (!cacheUsuarios) cacheUsuarios = await carregarUsuariosCadastro();
  const contatos = [
    { id: CHAT_AI_RIO_CONTACT_ID, is_ai_rio: true },
    ...(cacheUsuarios || []).filter((u) => String(u.id) !== String(chatState.usuarioId)),
  ];
  if (!manterSelecao || !contatos.some((u) => String(u.id) === String(chatState.contatoId))) {
    chatState.contatoId = CHAT_AI_RIO_CONTACT_ID;
  }
  _chatAIRioLoadState();
  if (String(chatState.contatoId) === CHAT_AI_RIO_CONTACT_ID && !(chatState.aiRioMessages || []).length) {
    _chatAIRioEnsureGreeting();
  }
  renderListaContatosChat();
  atualizarCabecalhoChat();
  atualizarEstadoEnvioChat();
}

async function selecionarContatoChat(contatoId) {
  limparAnexoChat();
  chatState.contatoId = String(contatoId || "");
  if (_chatEhContatoAIRio()) {
    _chatAIRioLoadState();
    if (!(chatState.aiRioMessages || []).length) _chatAIRioEnsureGreeting();
    _chatAIRioRenderConversation();
    atualizarCabecalhoChat();
    atualizarEstadoEnvioChat();
    return;
  }
  if (!_chatEhContatoAIRio(chatState.contatoId)) {
    await marcarLidasContatoChat(chatState.contatoId);
  }
  await carregarChat();
}

async function carregarChat() {
  const box = document.getElementById("chatMensagens");
  if (!box) return;
  if (!chatState.usuarioId || !chatState.contatoId) {
    box.innerHTML = "<div class='chat-empty'><div class='chat-empty-title'>Nenhuma conversa aberta</div><div class='chat-empty-text'>Selecione um contato para iniciar o chat.</div></div>";
    atualizarCabecalhoChat();
    atualizarEstadoEnvioChat();
    return;
  }

  if (_chatEhContatoAIRio()) {
    _chatAIRioLoadState();
    if (!(chatState.aiRioMessages || []).length) _chatAIRioEnsureGreeting();
    _chatAIRioRenderConversation();
    atualizarCabecalhoChat();
    renderListaContatosChat();
    atualizarEstadoEnvioChat();
    _chatAutoResizeInput();
    return;
  }

  const url = `/api/chat/conversa?usuario_id=${encodeURIComponent(chatState.usuarioId)}&contato_id=${encodeURIComponent(chatState.contatoId)}&limit=250`;
  const resp = await apiFetch(url);
  if (!resp.ok) {
    box.innerHTML = "<div class='chat-empty'><div class='chat-empty-title'>Erro ao carregar conversa</div><div class='chat-empty-text'>Tente novamente em alguns segundos.</div></div>";
    return;
  }
  const mensagens = await resp.json();
  _chatProcessarNovasMensagens(mensagens);
  if (!(mensagens || []).length) {
    const nomeContato = _escHtml(_chatNomePorId(chatState.contatoId) || "o contato");
    box.innerHTML = `<div class="chat-empty"><div class="chat-empty-title">Conversa vazia</div><div class="chat-empty-text">Envie a primeira mensagem para ${nomeContato}.</div></div>`;
  } else {
    box.innerHTML = (mensagens || []).map((m) => {
      const eu = String(m.remetente_id) === String(chatState.usuarioId);
      const cls = eu ? "me" : "other";
      const data = _chatDataLabel(m.data_envio);
      const anexoHtml = _chatAnexoMensagemHtml(m);
      const textoHtml = m.mensagem ? `<div class="chat-item-text">${_chatMensagemHtml(m.mensagem || "")}</div>` : "";
      return `<div class="chat-item ${cls}">${anexoHtml}${textoHtml}<small class="chat-item-meta">${_escHtml(data)}</small></div>`;
    }).join("");
    box.scrollTop = box.scrollHeight;
  }

  if (!_chatEhContatoAIRio(chatState.contatoId)) {
    await marcarLidasContatoChat(chatState.contatoId);
  }
  atualizarCabecalhoChat();
  renderListaContatosChat();
  atualizarEstadoEnvioChat();
  _chatAutoResizeInput();
}

async function enviarMensagemChat() {
  const txt = document.getElementById("chatTexto");
  const mensagem = (txt?.value || "").trim();
  const anexo = chatState.pendingAttachment || null;
  if (!chatState.usuarioId || !chatState.contatoId) return;
  if (chatState.sendingMessage) return;
  if (!mensagem && !anexo) return;

  if (_chatEhContatoAIRio()) {
    await enviarMensagemChatAIRio(mensagem, anexo);
    return;
  }

  _chatMostrarEnviando(mensagem, anexo);
  try {
    let resp;
    if (anexo) {
      const form = new FormData();
      form.append("remetente_id", String(Number(chatState.usuarioId)));
      form.append("destinatario_id", String(Number(chatState.contatoId)));
      form.append("mensagem", mensagem);
      form.append("anexo", anexo);
      resp = await apiFetch("/api/chat/mensagens", {
        method: "POST",
        body: form,
      });
    } else {
      resp = await apiFetch("/api/chat/mensagens", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          remetente_id: Number(chatState.usuarioId),
          destinatario_id: Number(chatState.contatoId),
          mensagem,
        }),
      });
    }
    if (!resp.ok) {
      const j = await resp.json().catch(() => null);
      alert(j?.erro || "Erro ao enviar mensagem.");
      return;
    }
    if (txt) {
      txt.value = "";
      _chatAutoResizeInput();
      txt.focus();
    }
    limparAnexoChat();
    await carregarChat();
  } finally {
    _chatRemoverEnviando();
  }
}

async function enviarMensagemChatAIRio(mensagem, anexo = null) {
  if (anexo) {
    alert("A I.A-Rio nao recebe anexos. Envie apenas texto.");
    return;
  }
  const textoUsuario = String(mensagem || "").trim();
  if (!textoUsuario) return;
  if (chatState.sendingMessage) return;

  chatState.sendingMessage = true;
  atualizarEstadoEnvioChat();
  try {
    _chatAIRioAppendMessage({ role: "user", text: textoUsuario, pending: false });
    _chatAIRioSetPending("Pensando...");

    const payload = {
      message: textoUsuario,
      history: _chatAIRioConversationToHistory().slice(-12),
      persona_name: CHAT_AI_RIO_NAME,
      chat_mode: "ia",
      stream: true,
    };

    const resp = await apiFetch("/api/agent/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const errorText = await resp.text().catch(() => "");
      throw new Error(_chatFriendlyHttpError(resp.status, errorText));
    }

    const contentType = (resp.headers.get("content-type") || "").toLowerCase();
    let finalData = null;
    if (contentType.includes("application/x-ndjson") && resp.body) {
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (value) buffer += decoder.decode(value, { stream: !done });

        let newlineIndex = buffer.indexOf("\n");
        while (newlineIndex !== -1) {
          const line = buffer.slice(0, newlineIndex).trim();
          buffer = buffer.slice(newlineIndex + 1);
          if (line) {
            try {
              const event = JSON.parse(line);
              if (event.type === "status") {
                _chatAIRioSetPending(event.reply || "Pensando...");
              } else if (event.type === "delta") {
                _chatAIRioSetPending(event.reply || event.text || "Pensando...");
              } else if (event.type === "final") {
                finalData = event;
              } else if (event.type === "error") {
                throw new Error(event.reply || event.message || "Nao consegui conversar com a I.A-Rio.");
              }
            } catch (parseErr) {
              console.warn("I.A-Rio stream parse error", parseErr);
            }
          }
          newlineIndex = buffer.indexOf("\n");
        }

        if (done) {
          const tail = buffer.trim();
          if (tail) {
            try {
              const event = JSON.parse(tail);
              if (event.type === "status") {
                _chatAIRioSetPending(event.reply || "Pensando...");
              } else if (event.type === "delta") {
                _chatAIRioSetPending(event.reply || event.text || "Pensando...");
              } else if (event.type === "final") {
                finalData = event;
              } else if (event.type === "error") {
                throw new Error(event.reply || event.message || "Nao consegui conversar com a I.A-Rio.");
              }
            } catch (parseErr) {
              console.warn("I.A-Rio stream parse error", parseErr);
            }
          }
          break;
        }
      }
    } else {
      finalData = await resp.json();
    }

    const finalText = finalData?.reply || finalData?.output || "Sem resposta.";
    _chatAIRioFinalize(finalText, finalData?.output || "");
    if (txt) {
      txt.value = "";
      _chatAutoResizeInput();
      txt.focus();
    }
    limparAnexoChat();
    renderListaContatosChat();
  } catch (err) {
    _chatAIRioFinalize(err?.message || "Nao consegui conversar com a I.A-Rio.");
    alert(err?.message || "Nao consegui conversar com a I.A-Rio.");
  } finally {
    chatState.sendingMessage = false;
    atualizarEstadoEnvioChat();
  }
}

async function toggleChatPopup(force) {
  if (!window.__chatIniciado) {
    initChatInterno();
  }
  const w = document.getElementById("chatWidget");
  const fab = document.getElementById("chatFab");
  if (!w) return;
  w.style.pointerEvents = "auto";
  if (fab) fab.style.pointerEvents = "auto";
  const abrir = force === undefined ? w.classList.contains("hidden") : !!force;
  chatState.isOpen = abrir;
  w.classList.toggle("hidden", !abrir);
  if (abrir) {
    await initSipClient().catch(() => {});
    await carregarUsuariosChat(true).catch(() => {});
    await carregarChat().catch(() => {});
    _chatAutoResizeInput();
    setTimeout(() => {
      try { document.getElementById("chatTexto")?.focus(); } catch {}
    }, 60);
  } else {
    toggleChatSipExternalPanel(false);
    if (chatState.contatoId && !_chatEhContatoAIRio(chatState.contatoId)) await marcarLidasContatoChat(chatState.contatoId).catch(() => {});
    renderListaContatosChat();
    atualizarBadgeFabDoMapa();
    atualizarEstadoSipChat();
  }
}

function atualizarUsuarioLogadoUI() {
  const label = document.getElementById("chatUserLabel");
  const avatar = document.getElementById("chatUserAvatar");
  const logoutBtn = document.getElementById("logoutBtn");
  const menuLogoutBtn = document.getElementById("menuLogoutBtn");
  if (label) {
    label.textContent = usuarioLogado ? `${usuarioLogado.nome} (${usuarioLogado.login})` : "Nao logado";
  }
  if (avatar) {
    avatar.textContent = usuarioLogado ? _chatIniciais(usuarioLogado.nome) : "RB";
  }
  if (logoutBtn) {
    logoutBtn.style.display = LOGIN_BYPASS ? "none" : "";
    logoutBtn.disabled = !usuarioLogado;
  }
  if (menuLogoutBtn) {
    menuLogoutBtn.style.display = LOGIN_BYPASS ? "none" : "";
    menuLogoutBtn.style.opacity = usuarioLogado ? "1" : "0.65";
    menuLogoutBtn.style.pointerEvents = usuarioLogado ? "auto" : "none";
  }
  atualizarEstadoSipChat();
  atualizarStatusCodbarSistema();
}

function _syncBlockingPopupState() {
  const body = document.body;
  if (!body) return;
  const hasBlockingPopup = !!document.querySelector(".foto-modal:not(.hidden), .login-modal:not(.hidden)");
  body.classList.toggle("modal-open", hasBlockingPopup);
}

function _abrirPopupBloqueante(modal) {
  if (!modal) return;
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  _syncBlockingPopupState();
}

function _fecharPopupBloqueante(modal) {
  if (!modal) return;
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
  _syncBlockingPopupState();
}

if (document.readyState !== "loading") {
  _syncBlockingPopupState();
}

function abrirLoginModal(showMsg = "") {
  const modal = document.getElementById("loginModal");
  const msg = document.getElementById("loginMsg");
  const loginInput = document.getElementById("loginUsuario");

  // Failsafe: remove overlays que podem bloquear clique no card de login.
  try { toggleMenuMobile(false); } catch {}
  try { _hideDashTip(); } catch {}
  try {
    document.querySelectorAll(".foto-modal").forEach((m) => m.classList.add("hidden"));
    document.body.classList.remove("menu-open");
  } catch {}

  document.body.classList.add("login-active");
  _abrirPopupBloqueante(modal);
  if (msg) msg.textContent = showMsg || "";
  try { loginInput?.focus(); } catch {}
  setTimeout(() => { try { loginInput?.focus(); } catch {} }, 40);
}

function fecharLoginModal() {
  const modal = document.getElementById("loginModal");
  _fecharPopupBloqueante(modal);
  document.body.classList.remove("login-active");
}

function _sessaoObjFromStorage() {
  const raw = localStorage.getItem(LOGIN_STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    // compatibilidade com formato antigo: objeto direto do usuário
    if (parsed && parsed.id && !parsed.usuario) {
      return {
        usuario: { id: parsed.id, nome: parsed.nome, login: parsed.login, codbar_modo: parsed.codbar_modo || "bip" },
        login_at: Date.now(),
        expires_at: Date.now() + LOGIN_MAX_AGE_MS,
      };
    }
    if (!parsed?.usuario?.id) return null;
    return parsed;
  } catch {
    return null;
  }
}

function _salvarSessaoLogin(usuario) {
  const now = Date.now();
  const sessao = {
    usuario: {
      id: usuario.id,
      nome: usuario.nome,
      login: usuario.login,
      codbar_modo: usuario.codbar_modo || "bip",
    },
    login_at: now,
    expires_at: now + LOGIN_MAX_AGE_MS,
  };
  localStorage.setItem(LOGIN_STORAGE_KEY, JSON.stringify(sessao));
}

function _logoutSessaoLocal(showLogin = true, msg = "Sessao expirada. Faca login novamente.") {
  usuarioLogado = null;
  chatState.usuarioId = "";
  chatState.contatoId = "";
  chatState.unreadByContato = {};
  chatState.showExternalDialer = false;
  chatState.lastSeenMessageId = 0;
  localStorage.removeItem(LOGIN_STORAGE_KEY);
  stopSipClient(true);
  limparAnexoChat();
  atualizarUsuarioLogadoUI();
  renderListaContatosChat();
  atualizarBadgeFab(0);
  if (showLogin && !LOGIN_BYPASS) abrirLoginModal(msg);
}

async function forcarLogoutSistema() {
  if (LOGIN_BYPASS) return;
  _logoutSessaoLocal(true, "Logout realizado. Faca login novamente.");
  await toggleChatPopup(false);
  const u = document.getElementById("loginUsuario");
  const s = document.getElementById("loginSenha");
  if (u) u.value = "";
  if (s) s.value = "";
}

function _sessaoExpirada(sessao) {
  if (!sessao?.expires_at) return true;
  return Date.now() > Number(sessao.expires_at);
}

function _aplicarUsuarioLogado(usuario, salvarSessao = false) {
  if (!usuario?.id) return null;
  usuarioLogado = {
    id: usuario.id,
    nome: usuario.nome,
    login: usuario.login,
    codbar_modo: usuario.codbar_modo || "bip",
  };
  chatState.usuarioId = String(usuarioLogado.id);
  chatState.lastSeenMessageId = 0;
  if (salvarSessao) _salvarSessaoLogin(usuarioLogado);
  atualizarUsuarioLogadoUI();
  return usuarioLogado;
}

async function fazerLoginSistema() {
  if (LOGIN_BYPASS) {
    fecharLoginModal();
    return;
  }
  const login = (document.getElementById("loginUsuario")?.value || "").trim();
  const senha = (document.getElementById("loginSenha")?.value || "").trim();
  if (!login || !senha) {
    abrirLoginModal("Informe login e senha.");
    return;
  }
  const resp = await apiFetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ login, senha }),
  });
  if (!resp.ok) {
    const j = await resp.json().catch(() => null);
    abrirLoginModal(j?.erro || "Falha no login.");
    return;
  }
  const j = await resp.json();
  _aplicarUsuarioLogado(j.usuario || null, true);
  fecharLoginModal();
  await initSipClient(true).catch(() => {});
  await carregarUsuariosChat(false);
  await carregarNaoLidasChat();
  renderListaContatosChat();
}

async function restaurarSessaoLogin() {
  if (LOGIN_BYPASS) return true;
  const sessao = _sessaoObjFromStorage();
  if (!sessao) return false;
  if (_sessaoExpirada(sessao)) {
    _logoutSessaoLocal(false, "");
    return false;
  }
  const usuarioSessao = sessao?.usuario || null;
  if (!usuarioSessao?.id) return false;
  _aplicarUsuarioLogado(usuarioSessao, false);
  fecharLoginModal();

  const uid = usuarioSessao.id;
  void (async () => {
    try {
      const resp = await apiFetch(`/api/me?usuario_id=${encodeURIComponent(uid)}`);
      if (!resp.ok) throw new Error("sessao invalida");
      const payload = await resp.json();
      const user = payload?.usuario || payload;
      if (String(usuarioLogado?.id || "") !== String(uid)) return;
      _aplicarUsuarioLogado(user, true); // renova por mais 8h após revalidação
      await initSipClient(true).catch(() => {});
    } catch {
      if (String(usuarioLogado?.id || "") === String(uid)) {
        _logoutSessaoLocal(true, "Sessao expirada. Faca login novamente.");
      }
    }
  })();

  return true;
}

function initChatInterno() {
  if (window.__chatIniciado) return;
  window.__chatIniciado = true;
  renderAnexoPendenteChat();
  _chatAIRioLoadState();
  if (!(chatState.aiRioMessages || []).length) _chatAIRioEnsureGreeting();

  const input = document.getElementById("chatTexto");
  if (input) {
    input.addEventListener("keydown", async (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        await enviarMensagemChat();
      }
    });
    input.addEventListener("input", () => _chatAutoResizeInput());
    _chatAutoResizeInput();
  }

  if (chatState.pollHandle) clearInterval(chatState.pollHandle);
  chatState.pollHandle = setInterval(async () => {
    try {
      if (!chatState.usuarioId) return;
      if (!LOGIN_BYPASS) {
        const s = _sessaoObjFromStorage();
        if (!s || _sessaoExpirada(s)) {
          _logoutSessaoLocal(true, "Sessao expirada (8h). Faca login novamente.");
          return;
        }
      }
      if (!sipState.ua && !sipState.initPromise) {
        initSipClient().catch(() => {});
      }
      await carregarNaoLidasChat();
      renderListaContatosChat();
      if (chatState.isOpen && chatState.contatoId) await carregarChat();
      atualizarEstadoSipChat();
    } catch {}
  }, 2000);
}

//////////////////////////////////////////////////////
// FRETES
//////////////////////////////////////////////////////
const FRETE_STATUS_OPCOES = [
  { key: "chegada", label: "Chegou C/ Vasilhames" },
  { key: "descarregado", label: "Descarregado Aguardando Carga" },
  { key: "liberado", label: "Liberado Para Carregar" },
  { key: "carregando", label: "Carregando Em Andamento" },
  { key: "carregado", label: "Carregado Liberado P Viajem" },
  { key: "entregando", label: "Viajando Em Entrega" },
  { key: "retornando", label: "Finalizado Retornando" },
  { key: "paradoVasio", label: "Parado (vazio)" },
  { key: "paradoCarregado", label: "Parado (carregado)" },
];
const FRETE_CARD_TEMPLATE_VERSION = "kanban-minimo-popup-20260429";
const ESCALA_STATUS_OPCOES = FRETE_STATUS_OPCOES.filter((item) => ["chegada", "descarregado", "liberado"].includes(item.key));
const ESCALA_STATUS_VIAGEM = new Set(["carregado", "entregando"]);

function _freteStatusLabel(status){
  return FRETE_STATUS_OPCOES.find((item) => item.key === status)?.label || status || "-";
}

function _rotuloFreteExibicao(frete){
  const cidades = (frete?.carga_cidades || "").toString().trim();
  const veiculo = (frete?.carga_veiculo_numero || frete?.veiculo_nome || frete?.veiculo_placa || "").toString().trim();
  const rota = (frete?.carga_rota || "").toString().trim();
  const nomeCalculado = (frete?.frete_nome || frete?.nome_exibicao || "").toString().trim();
  if (nomeCalculado) return nomeCalculado;
  if (cidades && veiculo) return `${cidades} - ${veiculo}`;
  if (!veiculo && cidades && rota) return `${cidades} - ${rota}`;
  if (cidades) return cidades;
  if (rota) return rota;
  if (veiculo) return veiculo;
  return (frete?.nome || "").toString().trim() || "Frete sem nome";
}

function _resumoFreteCabecalho(frete = {}) {
  const cidade = (frete?.carga_cidades || frete?.carga_nome || frete?.cidade || "").toString().trim();
  const rota = (frete?.carga_rota || "").toString().trim();
  const veiculo = (frete?.carga_veiculo_numero || frete?.veiculo_nome || frete?.veiculo_placa || "").toString().trim();
  if (cidade && rota) return `${cidade} - rota ${rota}`;
  if (cidade) return cidade;
  if (rota) return `rota ${rota}`;
  if (veiculo) return veiculo;
  return (frete?.nome || "").toString().trim() || "Frete sem nome";
}

function _resumoVeiculoPlacaFrete(frete = {}) {
  const veiculo = _buscarVeiculoCadastro(_resolverVeiculoIdDoFrete(frete));
  if (veiculo?.id) {
    const numeroOuNome = (veiculo.nome || `Veiculo ${veiculo.id}`).toString().trim();
    const placa = (veiculo.placa || "").toString().trim();
    return placa ? `${numeroOuNome} - ${placa}` : numeroOuNome;
  }
  const numero = _extrairNumeroVeiculoTexto(frete?.carga_veiculo_numero || frete?.veiculo_nome || frete?.carga_nome || frete?.nome);
  return numero ? numero : "";
}

function _freteKey(id){
  return String(id ?? "");
}

function _findFreteById(id){
  return fretes.find((f) => String(f.id) === String(id)) || null;
}

function _indiceStatusFrete(status){
  return FRETE_STATUS_OPCOES.findIndex((item) => item.key === String(status || ""));
}

function _atualizarBotoesMovimentoMobile(card, status){
  if (!card) return;
  const idx = _indiceStatusFrete(status);
  const btnPrev = card.querySelector(".btn-mover-mobile-prev");
  const btnNext = card.querySelector(".btn-mover-mobile-next");
  const temPrev = idx > 0;
  const temNext = idx >= 0 && idx < FRETE_STATUS_OPCOES.length - 1;

  if (btnPrev) {
    btnPrev.disabled = !temPrev;
    btnPrev.title = temPrev ? `Mover para ${_freteStatusLabel(FRETE_STATUS_OPCOES[idx - 1].key)}` : "Sem coluna anterior";
  }
  if (btnNext) {
    btnNext.disabled = !temNext;
    btnNext.title = temNext ? `Mover para ${_freteStatusLabel(FRETE_STATUS_OPCOES[idx + 1].key)}` : "Sem coluna seguinte";
  }
}

function _setFreteLocal(frete){
  if (!frete || frete.id == null) return;
  const idx = fretes.findIndex((item) => String(item.id) === String(frete.id));
  if (idx >= 0) fretes[idx] = frete;
  else fretes.unshift(frete);
}

function _removeFreteLocal(id){
  fretes = fretes.filter((item) => String(item.id) !== String(id));
}

function _normalizarApoioEscalaId(motoristaId, apoioId) {
  const motoristaNum = motoristaId ? Number(motoristaId) : null;
  const apoioNum = apoioId ? Number(apoioId) : null;
  if (!apoioNum) return null;
  return motoristaNum && motoristaNum === apoioNum ? null : apoioNum;
}

function _resolverEquipeEscala(motoristaId, apoioId) {
  const motoristaNum = motoristaId ? Number(motoristaId) : null;
  const motorista = _buscarColaboradorCadastro(motoristaNum);
  const apoioNum = _normalizarApoioEscalaId(motoristaNum, apoioId);
  const apoio = _buscarColaboradorCadastro(apoioNum);
  const motoristaEntregador = _colaboradorTemFuncao(motorista, "entregador");
  const entregadorId = apoioNum || (motoristaEntregador ? motoristaNum : null);
  return {
    motoristaId: motoristaNum,
    apoioId: apoioNum,
    entregadorId,
    motorista,
    apoio,
    motoristaEntregador,
  };
}

function _listaFretesEscalaAtivos(excludeFreteId = null) {
  return (fretes || []).filter((item) => (
    ESCALA_STATUS_OPCOES.some((statusInfo) => statusInfo.key === item?.status) &&
    String(item?.id) !== String(excludeFreteId ?? "")
  ));
}

function _buscarConflitosPessoaEscala(freteId, pessoaIds) {
  const ids = Array.from(new Set((pessoaIds || []).filter(Boolean).map((item) => String(item))));
  const vistos = new Set();
  const conflitos = [];
  if (!ids.length) return conflitos;

  _listaFretesEscalaAtivos(freteId).forEach((outroFrete) => {
    const usados = new Set();
    const motoristaAtual = _freteColaboradorMotoristaId(outroFrete);
    const entregadorAtual = _freteColaboradorEntregadorId(outroFrete);
    if (motoristaAtual) usados.add(String(motoristaAtual));
    if (entregadorAtual) usados.add(String(entregadorAtual));
    ids.forEach((id) => {
      if (!usados.has(id)) return;
      const chave = `${id}:${String(outroFrete?.id ?? "")}`;
      if (vistos.has(chave)) return;
      vistos.add(chave);
      conflitos.push({
        pessoaId: Number(id),
        frete: outroFrete,
      });
    });
  });

  return conflitos;
}

function _buscarPessoasEmViagem(freteId, pessoaIds) {
  const ids = Array.from(new Set((pessoaIds || []).filter(Boolean).map((item) => String(item))));
  const vistos = new Set();
  const avisos = [];
  if (!ids.length) return avisos;

  (fretes || []).forEach((outroFrete) => {
    if (String(outroFrete?.id ?? "") === String(freteId ?? "")) return;
    if (!ESCALA_STATUS_VIAGEM.has(String(outroFrete?.status || ""))) return;

    const usados = new Set();
    const motoristaAtual = _freteColaboradorMotoristaId(outroFrete);
    const entregadorAtual = _freteColaboradorEntregadorId(outroFrete);
    if (motoristaAtual) usados.add(String(motoristaAtual));
    if (entregadorAtual) usados.add(String(entregadorAtual));

    ids.forEach((id) => {
      if (!usados.has(id)) return;
      const chave = `${id}:${String(outroFrete?.id ?? "")}`;
      if (vistos.has(chave)) return;
      vistos.add(chave);
      avisos.push({
        pessoaId: Number(id),
        frete: outroFrete,
      });
    });
  });

  return avisos;
}

function _avaliarEscalaFreteSelecao(frete, motoristaId, apoioId) {
  const equipe = _resolverEquipeEscala(motoristaId, apoioId);
  const pendencias = [];
  const avisos = [];

  if (!equipe.motoristaId) {
    pendencias.push("Selecione um motorista.");
  } else if (!equipe.motorista) {
    pendencias.push("Motorista informado nao foi encontrado.");
  } else if (!_colaboradorTemFuncao(equipe.motorista, "motorista")) {
    pendencias.push(`${equipe.motorista.nome} nao tem perfil de motorista.`);
  }

  if (!equipe.entregadorId) {
    pendencias.push("Selecione um apoio entregador ou use um motorista-entregador.");
  } else if (equipe.apoioId) {
    if (!equipe.apoio) {
      pendencias.push("Apoio informado nao foi encontrado.");
    } else if (
      !_colaboradorTemFuncao(equipe.apoio, "entregador") &&
      !_colaboradorTemFuncao(equipe.apoio, "ajudante")
    ) {
      pendencias.push(`${equipe.apoio.nome} nao tem perfil de apoio.`);
    } else if (!equipe.motoristaEntregador && !_colaboradorTemFuncao(equipe.apoio, "entregador")) {
      pendencias.push(`${equipe.apoio.nome} precisa ter perfil de entregador com este motorista.`);
    }
  }

  const conflitos = pendencias.length ? [] : _buscarConflitosPessoaEscala(frete?.id, [
    equipe.motoristaId,
    equipe.apoioId,
  ]);

  conflitos.forEach((conflito) => {
    const pessoa = _buscarColaboradorCadastro(conflito.pessoaId);
    const nomePessoa = pessoa?.nome || "Colaborador";
    const nomeVeiculo = conflito.frete?.veiculo_nome || conflito.frete?.nome || `frete ${conflito.frete?.id}`;
    pendencias.push(`${nomePessoa} ja esta escalado no veiculo ${nomeVeiculo}.`);
  });

  const pessoasEmViagem = pendencias.length ? [] : _buscarPessoasEmViagem(frete?.id, [
    equipe.motoristaId,
    equipe.apoioId,
  ]);

  pessoasEmViagem.forEach((item) => {
    const pessoa = _buscarColaboradorCadastro(item.pessoaId);
    const nomePessoa = pessoa?.nome || "Colaborador";
    const nomeVeiculo = item.frete?.veiculo_nome || item.frete?.nome || `frete ${item.frete?.id}`;
    avisos.push(`${nomePessoa} consta em viagem no veiculo ${nomeVeiculo} (${_freteStatusLabel(item.frete?.status)}). Confirme antes de escalar.`);
  });

  if (
    equipe.apoioId &&
    equipe.motoristaEntregador &&
    equipe.apoio &&
    _colaboradorTemFuncao(equipe.apoio, "ajudante") &&
    _colaboradorTemFuncao(equipe.apoio, "entregador")
  ) {
    avisos.push(`${equipe.apoio.nome} esta como ajudante-entregador com motorista que ja entrega. Confirme essa dupla.`);
  }

  if (
    equipe.apoioId &&
    equipe.apoio &&
    _colaboradorTemFuncao(equipe.apoio, "motorista")
  ) {
    avisos.push(`${equipe.apoio.nome} tambem e motorista. Confirme se faz sentido escalar dois motoristas juntos.`);
  }

  return { equipe, pendencias, avisos };
}

function _renderMensagensEscala(avaliacao) {
  const badges = [];
  avaliacao.pendencias.forEach((mensagem) => {
    badges.push(`<span class="escala-pendencia">${_escHtml(mensagem)}</span>`);
  });
  avaliacao.avisos.forEach((mensagem) => {
    badges.push(`<span class="escala-aviso">${_escHtml(mensagem)}</span>`);
  });
  if (!badges.length) {
    badges.push(`<span class="escala-ok">Equipe valida</span>`);
  }
  return badges.join("");
}

function _pendenciasEscalaFrete(frete){
  const motoristaId = _freteColaboradorMotoristaId(frete);
  const apoioId = _normalizarApoioEscalaId(motoristaId, _freteColaboradorEntregadorId(frete));
  const avaliacao = _avaliarEscalaFreteSelecao(frete, motoristaId, apoioId);
  const pendencias = [...avaliacao.pendencias];
  if (!frete?.veiculo_id) pendencias.unshift("Sem veiculo.");
  return pendencias;
}

function atualizarPreviewEscalaFrete(id) {
  const card = document.querySelector(`.escala-item[data-frete-id="${String(id)}"]`);
  const frete = _findFreteById(id);
  if (!card || !frete) return;

  const motoristaId = card.querySelector(".escala-motorista")?.value
    ? Number(card.querySelector(".escala-motorista").value)
    : null;
  const apoioId = card.querySelector(".escala-apoio")?.value
    ? Number(card.querySelector(".escala-apoio").value)
    : null;
  const avaliacao = _avaliarEscalaFreteSelecao(frete, motoristaId, apoioId);
  card.classList.toggle("escala-item--pendente", avaliacao.pendencias.length > 0);
  card.classList.toggle("escala-item--aviso", !avaliacao.pendencias.length && avaliacao.avisos.length > 0);
  const area = card.querySelector(".escala-pendencias");
  if (area) area.innerHTML = _renderMensagensEscala(avaliacao);
}

async function salvarEscalaFrete(id) {
  const card = document.querySelector(`.escala-item[data-frete-id="${String(id)}"]`);
  const frete = _findFreteById(id);
  if (!card || !frete) return;

  const motoristaId = card.querySelector(".escala-motorista")?.value
    ? Number(card.querySelector(".escala-motorista").value)
    : null;
  const apoioEscolhido = card.querySelector(".escala-apoio")?.value
    ? Number(card.querySelector(".escala-apoio").value)
    : null;
  const avaliacao = _avaliarEscalaFreteSelecao(frete, motoristaId, apoioEscolhido);

  if (avaliacao.pendencias.length) {
    alert(avaliacao.pendencias.join("\n"));
    return;
  }

  if (avaliacao.avisos.length && !window.confirm(avaliacao.avisos.join("\n\n"))) return;

  try {
    await atualizarFreteCompleto(frete.id, {
      ..._cloneFretePayload(frete),
      motorista_id: avaliacao.equipe.motoristaId,
      colaborador_motorista_id: avaliacao.equipe.motoristaId,
      entregador_id: avaliacao.equipe.entregadorId,
      colaborador_entregador_id: avaliacao.equipe.entregadorId,
    });
    await renderFretes();
    await renderEscala();
  } catch (err) {
    alert(err?.message || "Erro ao salvar a escala.");
  }
}

async function renderEscala() {
  await ensureCadastrosCache();

  const grid = document.getElementById("escalaGrid");
  if (!grid) return;

  const fretesEscala = fretes
    .filter((frete) => ESCALA_STATUS_OPCOES.some((item) => item.key === frete.status))
    .sort((a, b) => {
      const statusA = ESCALA_STATUS_OPCOES.findIndex((item) => item.key === a.status);
      const statusB = ESCALA_STATUS_OPCOES.findIndex((item) => item.key === b.status);
      if (statusA !== statusB) return statusA - statusB;
      return String(a.veiculo_nome || a.nome || "").localeCompare(String(b.veiculo_nome || b.nome || ""), "pt-BR", { numeric: true, sensitivity: "base" });
    });

  const pendentes = fretesEscala.filter((frete) => _pendenciasEscalaFrete(frete).length > 0);
  const resumoTotal = document.getElementById("escalaResumoTotal");
  const resumoCompleta = document.getElementById("escalaResumoCompleta");
  const resumoPendentes = document.getElementById("escalaResumoPendentes");
  if (resumoTotal) resumoTotal.textContent = String(fretesEscala.length);
  if (resumoCompleta) resumoCompleta.textContent = String(fretesEscala.length - pendentes.length);
  if (resumoPendentes) resumoPendentes.textContent = String(pendentes.length);

  grid.innerHTML = ESCALA_STATUS_OPCOES.map((statusInfo) => {
    const itens = fretesEscala.filter((frete) => frete.status === statusInfo.key);
    const conteudo = itens.length ? itens.map((frete) => {
      const motoristaAtual = _freteColaboradorMotoristaId(frete);
      const apoioAtualId = _freteColaboradorEntregadorId(frete);
      const apoioSelecionado = _normalizarApoioEscalaId(motoristaAtual, apoioAtualId);
      const avaliacao = _avaliarEscalaFreteSelecao(frete, motoristaAtual, apoioSelecionado);
      const pendenciasFrete = [...avaliacao.pendencias];
      if (!frete?.veiculo_id) pendenciasFrete.unshift("Sem veiculo.");
      const rotuloFrete = _rotuloFreteExibicao(frete);
      const veiculoRotulo = (frete.carga_veiculo_numero || frete.veiculo_nome || frete.veiculo_placa || "").toString().trim();
      const rotaRotulo = (frete.carga_rota || "").toString().trim();
      const apoioAtual = apoioSelecionado
        ? (_buscarColaboradorCadastro(apoioSelecionado)?.nome || frete.entregador_nome || "-")
        : (avaliacao.equipe.motoristaEntregador ? "Motorista vai sozinho" : (frete.entregador_nome || "-"));
      return `
        <article class="escala-item ${pendenciasFrete.length ? "escala-item--pendente" : (avaliacao.avisos.length ? "escala-item--aviso" : "")}" data-frete-id="${_escAttr(String(frete.id))}">
          <div class="escala-item-header">
            <div>
              <strong>${_escHtml(rotuloFrete)}</strong>
              <div class="escala-item-subtitle">${_escHtml(veiculoRotulo ? `Veiculo ${veiculoRotulo}` : (rotaRotulo ? `Rota ${rotaRotulo}` : (frete.nome || "-")))}</div>
            </div>
            <span class="escala-status-pill">${_escHtml(statusInfo.label)}</span>
          </div>
          <div class="escala-item-meta">
            <span>Carga: ${_escHtml(frete.carga_nome || "-")}</span>
            <span>Motorista atual: ${_escHtml(frete.motorista_nome || "-")}</span>
            <span>Apoio atual: ${_escHtml(apoioAtual)}</span>
          </div>
          <div class="escala-item-grid">
            <label class="escala-field">
              <span>Motorista</span>
              <select class="escala-motorista" onchange="atualizarPreviewEscalaFrete(${frete.id})">
                ${optionsFromColaboradores("motorista", motoristaAtual)}
              </select>
            </label>
            <label class="escala-field">
              <span>Entregador / Ajudante</span>
              <select class="escala-apoio" onchange="atualizarPreviewEscalaFrete(${frete.id})">
                ${optionsFromEscalaApoio(apoioSelecionado, motoristaAtual)}
              </select>
            </label>
          </div>
          <div class="escala-item-footer">
            <div class="escala-pendencias">${_renderMensagensEscala({ pendencias: pendenciasFrete, avisos: avaliacao.avisos })}</div>
            <button type="button" onclick="salvarEscalaFrete(${frete.id})">Salvar equipe</button>
          </div>
        </article>
      `;
    }).join("") : `<div class="escala-empty">Nenhum caminhao nesta etapa.</div>`;

    return `
      <section class="escala-coluna">
        <div class="escala-coluna-header">
          <h3>${_escHtml(statusInfo.label)}</h3>
          <span>${itens.length}</span>
        </div>
        <div class="escala-coluna-body">${conteudo}</div>
      </section>
    `;
  }).join("");
}

function filtrarFretesKanban(valor = ""){
  freteKanbanFiltro = (valor || "").toString().trim().toLowerCase();
  renderFretes().catch((err) => console.warn("filtro fretes erro:", err));
}

function _freteCombinaBusca(frete, termo = ""){
  const filtro = (termo || "").trim().toLowerCase();
  if (!filtro) return true;
  const alvo = [
    frete?.nome,
    frete?.veiculo_nome,
    frete?.veiculo_placa,
    frete?.motorista_nome,
    frete?.entregador_nome,
    frete?.cidade,
    frete?.carga_nome,
    frete?.carga_cidades,
    frete?.carga_rota,
    frete?.carga_veiculo_numero,
  ].map((v) => (v || "").toString().toLowerCase()).join(" ");
  return alvo.includes(filtro);
}

function _freteOcultoNoKanban(frete){
  return !!frete?.arquivado;
}

function _parseFreteDateTime(value){
  const raw = String(value || "").trim();
  if (!raw) return null;
  const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$/);
  if (!m) return null;
  const dt = new Date(
    Number(m[1]),
    Number(m[2]) - 1,
    Number(m[3]),
    Number(m[4] || 0),
    Number(m[5] || 0),
    Number(m[6] || 0),
    0
  );
  return Number.isNaN(dt.getTime()) ? null : dt;
}

function _getNomeById(lista, id) {
  if (!id || !lista) return null;
  const item = lista.find(item => item.id == id);
  return item ? (item.optionLabel || item.nome) : null;
}

function _getNomeColaborador(id) {
  if (!id) return null;
  const colaborador = cacheCadastros.colaboradores?.find(c => c.id == id);
  return colaborador ? colaborador.nome : null;
}

function _formatDate(dateStr) {
  if (!dateStr) return 'N/A';
  try {
    const date = new Date(dateStr);
    return date.toLocaleDateString('pt-BR');
  } catch {
    return dateStr;
  }
}

async function _arquivarFretesAutomaticamente() {
  // Arquivar cards em "retornando" com mais de 1 dia.
  const candidatos = fretes.filter(f =>
    String(f.status || "") === "retornando" &&
    !f.arquivado &&
    _parseFreteDateTime(f.finalizado_em) &&
    (Date.now() - _parseFreteDateTime(f.finalizado_em).getTime()) >= (FRETE_AUTO_ARQUIVO_HORAS * 60 * 60 * 1000)
  );

  for (const frete of candidatos) {
    try {
      const r = await apiFetch(`/api/fretes/${frete.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ arquivado: true })
      });
      if (r.ok) {
        frete.arquivado = true;
        console.info(`Frete ${frete.id} arquivado automaticamente.`);
      }
    } catch (e) {
      console.error(`Erro ao arquivar frete ${frete.id}:`, e);
    }
  }
}

function _normalizarDataFreteInput(value){
  const raw = (value || "").toString().trim();
  return raw ? raw.slice(0, 10) : "";
}

function _hojeInputDate(){
  const now = new Date();
  const tzOffsetMs = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - tzOffsetMs).toISOString().slice(0, 10);
}

function _buscarVeiculoCadastro(veiculoId){
  if (!veiculoId) return null;
  return (cacheCadastros.veiculos || []).find((item) => String(item.id) === String(veiculoId)) || null;
}

function _extrairNumeroVeiculoTexto(valor) {
  const texto = (valor ?? "").toString().trim();
  if (!texto) return "";
  const match = texto.match(/\d+/);
  if (!match) return "";
  return match[0].replace(/^0+/, "") || "0";
}

function _normalizarNumeroVeiculoTexto(valor) {
  return (valor ?? "").toString().trim().toLowerCase().replace(/\s+/g, " ");
}

function _buscarVeiculoPorNumeroTexto(valor) {
  const texto = (valor ?? "").toString().trim();
  if (!texto) return null;
  const alvoTexto = _normalizarNumeroVeiculoTexto(texto);
  const alvoNumero = _extrairNumeroVeiculoTexto(texto);
  return (cacheCadastros.veiculos || []).find((item) => {
    const candidatos = [
      item?.nome,
      item?.placa,
      item?.optionLabel,
    ];
    return candidatos.some((candidato) => {
      const atualTexto = _normalizarNumeroVeiculoTexto(candidato);
      if (atualTexto && atualTexto === alvoTexto) return true;
      const atualNumero = _extrairNumeroVeiculoTexto(candidato);
      if (alvoNumero && atualNumero && atualNumero === alvoNumero) return true;
      return false;
    });
  }) || null;
}

function _resolverVeiculoIdDoFrete(frete = {}) {
  const veiculoId = Number(frete?.veiculo_id || 0);
  if (veiculoId > 0) return veiculoId;
  const candidatos = [
    frete?.carga_veiculo_numero,
    frete?.veiculo_nome,
    frete?.veiculo_placa,
    frete?.carga_nome,
    frete?.nome,
  ];
  for (const candidato of candidatos) {
    const veiculo = _buscarVeiculoPorNumeroTexto(candidato);
    if (veiculo?.id) return Number(veiculo.id);
  }
  return null;
}

function _rotuloVeiculoCadastradoDoFrete(frete = {}) {
  const veiculo = _buscarVeiculoCadastro(_resolverVeiculoIdDoFrete(frete));
  if (veiculo?.id) {
    return `${veiculo.nome || "Veiculo"}${veiculo.placa ? ` (${veiculo.placa})` : ""}`;
  }
  const numero = _extrairNumeroVeiculoTexto(frete?.carga_veiculo_numero || frete?.veiculo_nome || frete?.carga_nome || frete?.nome);
  return numero ? `Veiculo ${numero}` : "";
}

function _kmAtualCadastroVeiculo(veiculoId){
  const veiculo = _buscarVeiculoCadastro(veiculoId);
  const km = Number(veiculo?.km_atual || 0);
  return Number.isFinite(km) && km > 0 ? km : 0;
}

function _sincronizarKmAtualComVeiculo(selectEl, kmInput, options = {}){
  const { force = false } = options;
  if (!selectEl || !kmInput) return;

  const kmCadastro = _kmAtualCadastroVeiculo(selectEl.value);
  const valorAtual = (kmInput.value || "").trim();
  const podeAtualizar = force || valorAtual === "" || Number(valorAtual || 0) === 0 || kmInput.dataset.autoFromVehicle === "1";
  if (!podeAtualizar) return;

  kmInput.value = kmCadastro > 0 ? String(kmCadastro) : "0";
  kmInput.dataset.autoFromVehicle = kmCadastro > 0 ? "1" : "0";
}

function _bindNovoFreteKmAtual(){
  const selVeiculo = document.getElementById("novoFreteVeiculo");
  const inpKmAtual = document.getElementById("novoFreteKmAtual");
  if (!selVeiculo || !inpKmAtual) return;

  if (inpKmAtual.dataset.kmManualBound !== "1") {
    inpKmAtual.dataset.kmManualBound = "1";
    inpKmAtual.addEventListener("input", () => {
      inpKmAtual.dataset.autoFromVehicle = "0";
    });
    inpKmAtual.addEventListener("change", () => {
      inpKmAtual.dataset.autoFromVehicle = "0";
    });
  }

  if (selVeiculo.dataset.kmCadastroBound !== "1") {
    selVeiculo.dataset.kmCadastroBound = "1";
    selVeiculo.addEventListener("change", () => {
      _sincronizarKmAtualComVeiculo(selVeiculo, inpKmAtual, { force: true });
    });
  }
}

function _bindNovoAbastecimentoKmAtual(){
  const selVeiculo = document.getElementById("abast_veiculo");
  const inpKmAtual = document.getElementById("abast_km");
  const selCombustivel = document.getElementById("abast_combustivel");
  if (!selVeiculo || !inpKmAtual || !selCombustivel) return;

  if (inpKmAtual.dataset.kmManualBound !== "1") {
    inpKmAtual.dataset.kmManualBound = "1";
    inpKmAtual.addEventListener("input", () => {
      inpKmAtual.dataset.autoFromVehicle = "0";
    });
    inpKmAtual.addEventListener("change", () => {
      inpKmAtual.dataset.autoFromVehicle = "0";
    });
  }

  if (selVeiculo.dataset.kmCadastroBound !== "1") {
    selVeiculo.dataset.kmCadastroBound = "1";
    selVeiculo.addEventListener("change", () => {
      _sincronizarKmAtualComVeiculo(selVeiculo, inpKmAtual, { force: true });
      _sincronizarCombustivelAbastecimentoComVeiculo(selVeiculo, selCombustivel);
    });
  }

  _sincronizarKmAtualComVeiculo(selVeiculo, inpKmAtual, { force: false });
  _sincronizarCombustivelAbastecimentoComVeiculo(selVeiculo, selCombustivel, selCombustivel.value);
}

function _freteColaboradorMotoristaId(frete = {}) {
  return frete.colaborador_motorista_id ? Number(frete.colaborador_motorista_id) : (frete.motorista_id ? Number(frete.motorista_id) : null);
}

function _freteColaboradorEntregadorId(frete = {}) {
  return frete.colaborador_entregador_id ? Number(frete.colaborador_entregador_id) : (frete.entregador_id ? Number(frete.entregador_id) : null);
}

function _cloneFretePayload(frete = {}){
  const motoristaId = _freteColaboradorMotoristaId(frete);
  const entregadorId = _freteColaboradorEntregadorId(frete);
  return {
    id: frete.id != null ? Number(frete.id) : null,
    nome: (frete.nome || "").toString().trim(),
    cidade: (frete.cidade || "").toString().trim(),
    data_carga: _normalizarDataFreteInput(frete.data_carga || frete.created_at || ""),
    status: (frete.status || "liberado").toString(),
    veiculo_id: _resolverVeiculoIdDoFrete(frete),
    motorista_id: motoristaId,
    colaborador_motorista_id: motoristaId,
    entregador_id: entregadorId || _resolverEntregadorPadrao(motoristaId, null),
    colaborador_entregador_id: entregadorId || _resolverEntregadorPadrao(motoristaId, null),
    carga_id: frete.carga_id ? Number(frete.carga_id) : null,
    km_atual: Number(frete.km_atual || 0) || 0,
    peso: Number(frete.peso || 0) || 0,
    qtd_entregas: Number(frete.qtd_entregas || 0) || 0,
    observacao: (frete.observacao || "").toString(),
    carga_rota: (frete.carga_rota || "").toString().trim(),
    carga_cidades: (frete.carga_cidades || "").toString().trim(),
    carga_veiculo_numero: (frete.carga_veiculo_numero || "").toString().trim(),
    carga_nome: (frete.carga_nome || "").toString().trim(),
    veiculo_nome: (frete.veiculo_nome || "").toString().trim(),
    veiculo_placa: (frete.veiculo_placa || "").toString().trim(),
    colaborador_motorista_nome: (frete.colaborador_motorista_nome || "").toString().trim(),
    motorista_nome: (frete.motorista_nome || "").toString().trim(),
    colaborador_entregador_nome: (frete.colaborador_entregador_nome || "").toString().trim(),
    entregador_nome: (frete.entregador_nome || "").toString().trim(),
  };
}

function _fretePayloadSignature(payload){
  return JSON.stringify(_cloneFretePayload(payload));
}

function _freteRemoteSignature(frete){
  return JSON.stringify([
    frete.id,
    frete.nome || "",
    frete.cidade || "",
    _normalizarDataFreteInput(frete.data_carga || frete.created_at || ""),
    frete.status || "",
    frete.colaborador_motorista_id || frete.motorista_id || "",
    frete.colaborador_entregador_id || frete.entregador_id || "",
    _resolverVeiculoIdDoFrete(frete) || "",
    frete.carga_id || "",
    frete.observacao || "",
    Number(frete.km_atual || 0),
    Number(frete.peso || 0),
    Number(frete.qtd_entregas || 0),
    frete.updated_at || "",
    frete.finalizado_em || "",
    frete.carga_rota || "",
    frete.carga_cidades || "",
    frete.carga_veiculo_numero || "",
    frete.carga_nome || "",
    frete.veiculo_nome || "",
    frete.veiculo_placa || "",
    frete.colaborador_motorista_nome || "",
    frete.motorista_nome || "",
    frete.colaborador_entregador_nome || "",
    frete.entregador_nome || "",
  ]);
}

function _ensureFreteDraftState(frete){
  const key = _freteKey(frete?.id);
  let state = freteDraftState.get(key);
  if (!state) {
    const draft = _cloneFretePayload(frete || {});
    state = {
      draft,
      dirty: false,
      saving: false,
      queued: false,
      queuedPayload: null,
      focused: false,
      saveTimer: null,
      lastSavedSignature: _fretePayloadSignature(draft),
      error: "",
    };
    freteDraftState.set(key, state);
    return state;
  }
  if (!state.dirty && !state.saving && !state.focused) {
    const draft = _cloneFretePayload(frete || {});
    state.draft = draft;
    state.lastSavedSignature = _fretePayloadSignature(draft);
    state.error = "";
  }
  return state;
}

function _clearFreteSaveTimer(state){
  if (!state?.saveTimer) return;
  clearTimeout(state.saveTimer);
  state.saveTimer = null;
}

function _isFreteCardLocked(id){
  const state = freteDraftState.get(_freteKey(id));
  return !!(state && (state.dirty || state.saving || state.focused));
}

function _freteColunas(){
  return {
    chegada: document.getElementById("col-chegada"),
    descarregado: document.getElementById("col-descarregado"),
    liberado: document.getElementById("col-liberado"),
    carregando: document.getElementById("col-carregando"),
    carregado: document.getElementById("col-carregado"),
    entregando: document.getElementById("col-entregando"),
    retornando: document.getElementById("col-retornando"),
    paradoVasio: document.getElementById("col-paradoVasio"),
    paradoCarregado: document.getElementById("col-paradoCarregado"),
  };
}

function _equalizarAlturaColunasKanban(){
  const secFretes = document.getElementById("fretes");
  const estaVisivel = !!(secFretes && secFretes.classList.contains("activeSection"));
  if (!estaVisivel) {
    _atualizarScrollbarAuxiliarKanban();
    return;
  }

  const cols = Array.from(secFretes.querySelectorAll(".kanban-col"));
  if (!cols.length) return;
  const zonasCards = cols
    .map((col) => col.querySelector(".kanban-cards"))
    .filter(Boolean);

  cols.forEach((col) => {
    col.style.minHeight = "";
  });
  zonasCards.forEach((zona) => {
    zona.style.minHeight = "";
  });

  let maiorAltura = 800;
  cols.forEach((col) => {
    maiorAltura = Math.max(maiorAltura, col.scrollHeight);
  });
  let maiorAreaCards = 120;
  zonasCards.forEach((zona) => {
    maiorAreaCards = Math.max(maiorAreaCards, zona.scrollHeight);
  });

  const alturaFinal = `${Math.ceil(maiorAltura)}px`;
  cols.forEach((col) => {
    col.style.minHeight = alturaFinal;
  });
  const alturaCardsFinal = `${Math.ceil(maiorAreaCards)}px`;
  zonasCards.forEach((zona) => {
    zona.style.minHeight = alturaCardsFinal;
  });
  _atualizarScrollbarAuxiliarKanban();
}

function _agendarEqualizacaoAlturaKanban(delay = 0){
  if (_agendarEqualizacaoAlturaKanban._timer) {
    clearTimeout(_agendarEqualizacaoAlturaKanban._timer);
  }
  _agendarEqualizacaoAlturaKanban._timer = setTimeout(() => {
    _equalizarAlturaColunasKanban();
    _agendarEqualizacaoAlturaKanban._timer = null;
  }, delay);
}

function _bindKanbanScrollbarAuxiliar(kanban, barra){
  if (!kanban || !barra || barra.dataset.syncBound === "1") return;
  barra.dataset.syncBound = "1";

  let sincronizando = false;

  kanban.addEventListener("scroll", () => {
    if (sincronizando) return;
    sincronizando = true;
    barra.scrollLeft = kanban.scrollLeft;
    sincronizando = false;
  });

  barra.addEventListener("scroll", () => {
    if (sincronizando) return;
    sincronizando = true;
    kanban.scrollLeft = barra.scrollLeft;
    sincronizando = false;
  });
}

function _bindKanbanDesktopAutoScroll(kanban){
  if (!kanban || kanban.dataset.desktopDragScrollBound === "1") return;
  kanban.dataset.desktopDragScrollBound = "1";
  kanban.addEventListener("dragover", (e) => {
    const rect = kanban.getBoundingClientRect();
    if (!rect.width) return;
    const edge = Math.min(140, Math.max(48, rect.width * 0.12));
    if (e.clientX <= rect.left + edge) {
      kanban.scrollLeft -= 24;
    } else if (e.clientX >= rect.right - edge) {
      kanban.scrollLeft += 24;
    }
  });
}

function _atualizarScrollbarAuxiliarKanban(){
  const secFretes = document.getElementById("fretes");
  const kanban = secFretes?.querySelector(".kanban");
  const barra = document.getElementById("kanbanScrollbar");
  const inner = document.getElementById("kanbanScrollbarInner");
  const estaVisivel = !!(secFretes && secFretes.classList.contains("activeSection"));

  if (!barra || !inner) return;
  if (!kanban || !estaVisivel) {
    barra.classList.remove("is-active");
    inner.style.width = "0px";
    barra.scrollLeft = 0;
    return;
  }

  _bindKanbanScrollbarAuxiliar(kanban, barra);
  _bindKanbanDesktopAutoScroll(kanban);

  inner.style.width = `${Math.ceil(kanban.scrollWidth)}px`;
  const precisaBarra = kanban.scrollWidth > (kanban.clientWidth + 2);
  barra.classList.toggle("is-active", precisaBarra);
  if (precisaBarra) barra.scrollLeft = kanban.scrollLeft;
}

function _getFreteCard(id){
  return document.querySelector(`.card[data-frete-id="${String(id)}"]`);
}

function _setFreteSaveStatus(card, message, tone = "saved"){
  const el = card?.querySelector(".frete-save-status");
  if (!el) return;
  el.textContent = message;
  el.dataset.tone = tone;
}

function _renderFreteSaveStatus(card, id){
  const state = freteDraftState.get(_freteKey(id));
  if (!card || !state) return;
  if (state.saving) {
    _setFreteSaveStatus(card, "Salvando...", "saving");
    return;
  }
  if (state.error) {
    _setFreteSaveStatus(card, state.error, "error");
    return;
  }
  if (state.dirty) {
    _setFreteSaveStatus(card, "Alteracoes pendentes", "pending");
    return;
  }
  _setFreteSaveStatus(card, "Salvo automaticamente", "saved");
}

function _coletarPayloadFreteDoCard(card, freteBase){
  if (!card) return _cloneFretePayload(freteBase || {});
  const inpDataCarga = card.querySelector(".frete-data-carga");
  const selVeiculo = card.querySelector(".frete-veiculo");
  const selMotorista = card.querySelector(".frete-motorista");
  const selEntregador = card.querySelector(".frete-entregador");
  const selCarga = card.querySelector(".frete-carga");
  const inpKmAtual = card.querySelector(".frete-km-atual");
  const inpPeso = card.querySelector(".frete-peso");
  const inpEntregas = card.querySelector(".frete-qtd-entregas");
  const txtObs = card.querySelector(".frete-obs");
  const motoristaId = selMotorista?.value ? Number(selMotorista.value) : null;
  const entregadorId = _resolverEntregadorPadrao(motoristaId, selEntregador?.value ? Number(selEntregador.value) : null);
  return {
    nome: (freteBase?.nome || "").toString().trim() || _resumoFreteCabecalho(freteBase || {}),
    cidade: (freteBase?.cidade || "").toString().trim(),
    data_carga: _normalizarDataFreteInput(inpDataCarga?.value || freteBase?.data_carga || freteBase?.created_at || ""),
    status: (freteBase?.status || "liberado").toString(),
    veiculo_id: selVeiculo?.value ? Number(selVeiculo.value) : _resolverVeiculoIdDoFrete(freteBase || {}),
    motorista_id: motoristaId,
    colaborador_motorista_id: motoristaId,
    entregador_id: entregadorId,
    colaborador_entregador_id: entregadorId,
    carga_id: selCarga?.value ? Number(selCarga.value) : null,
    km_atual: inpKmAtual && inpKmAtual.value.trim() !== "" ? Number(inpKmAtual.value) : 0,
    peso: inpPeso && inpPeso.value.trim() !== "" ? Number(inpPeso.value) : 0,
    qtd_entregas: inpEntregas && inpEntregas.value.trim() !== "" ? Number(inpEntregas.value) : 0,
    observacao: (txtObs?.value || "").trim(),
    carga_rota: (freteBase?.carga_rota || "").toString().trim(),
    carga_cidades: (freteBase?.carga_cidades || "").toString().trim(),
    carga_veiculo_numero: (freteBase?.carga_veiculo_numero || "").toString().trim(),
    carga_nome: (freteBase?.carga_nome || "").toString().trim(),
    veiculo_nome: (freteBase?.veiculo_nome || "").toString().trim(),
    veiculo_placa: (freteBase?.veiculo_placa || "").toString().trim(),
    colaborador_motorista_nome: (freteBase?.colaborador_motorista_nome || freteBase?.motorista_nome || "").toString().trim(),
    motorista_nome: (freteBase?.motorista_nome || freteBase?.colaborador_motorista_nome || "").toString().trim(),
    colaborador_entregador_nome: (freteBase?.colaborador_entregador_nome || freteBase?.entregador_nome || "").toString().trim(),
    entregador_nome: (freteBase?.entregador_nome || freteBase?.colaborador_entregador_nome || "").toString().trim(),
  };
}

function _atualizarDraftFreteDoCard(id){
  const freteBase = _findFreteById(id) || {};
  const card = _getFreteCard(id);
  const state = _ensureFreteDraftState(freteBase);
  state.draft = _coletarPayloadFreteDoCard(card, freteBase);
  state.dirty = _fretePayloadSignature(state.draft) !== state.lastSavedSignature;
  if (state.dirty) state.error = "";
  _renderFreteSaveStatus(card, id);
  return state.draft;
}

function _agendarAutoSaveFrete(id, delay = FRETE_AUTO_SAVE_DELAY_MS){
  const state = freteDraftState.get(_freteKey(id));
  if (!state) return;
  _clearFreteSaveTimer(state);
  state.saveTimer = setTimeout(() => {
    _salvarFreteAutomaticamente(id).catch((err) => {
      console.warn("Erro ao salvar frete automaticamente:", err);
    });
  }, delay);
}

async function _salvarFreteAutomaticamente(id, options = {}){
  const { payloadOverride = null, retryDelay = 250 } = options;
  const freteAtual = _findFreteById(id);
  const card = _getFreteCard(id);
  if (!freteAtual || !card) return null;

  const state = _ensureFreteDraftState(freteAtual);
  _clearFreteSaveTimer(state);

  if (payloadOverride) {
    state.draft = _cloneFretePayload({ ...state.draft, ...payloadOverride });
    state.dirty = _fretePayloadSignature(state.draft) !== state.lastSavedSignature;
    state.error = "";
  }

  if (!state.dirty && !payloadOverride) {
    _renderFreteSaveStatus(card, id);
    return freteAtual;
  }

  if (state.saving) {
    state.queued = true;
    state.queuedPayload = payloadOverride
      ? _cloneFretePayload({ ...state.draft, ...payloadOverride })
      : _coletarPayloadFreteDoCard(card, freteAtual);
    return null;
  }

  const payload = payloadOverride
    ? _cloneFretePayload({ ...state.draft, ...payloadOverride })
    : _coletarPayloadFreteDoCard(card, freteAtual);

  if (!payload.nome) throw new Error("Nome do frete e obrigatorio.");

  const currentSignature = _fretePayloadSignature(payload);
  if (!payloadOverride && currentSignature === state.lastSavedSignature) {
    state.dirty = false;
    _renderFreteSaveStatus(card, id);
    return freteAtual;
  }

  state.draft = payload;
  state.dirty = true;
  state.saving = true;
  state.error = "";
  _renderFreteSaveStatus(card, id);

  try {
    const atualizado = await atualizarFreteCompleto(id, payload);
    if (atualizado) {
      _setFreteLocal(atualizado);
      state.draft = _cloneFretePayload(atualizado);
    }
    state.lastSavedSignature = _fretePayloadSignature(state.draft);
    state.dirty = false;
    const freteRender = _findFreteById(id) || atualizado;
    if (freteRender) _renderOrUpdateFreteCard(freteRender, { force: true });
    return atualizado || freteAtual;
  } catch (err) {
    state.error = (err?.message || "Falha ao salvar").toString().trim();
    state.dirty = true;
    _renderFreteSaveStatus(card, id);
    throw err;
  } finally {
    state.saving = false;
    const queued = state.queued;
    const queuedPayload = state.queuedPayload;
    state.queued = false;
    state.queuedPayload = null;
    if (queued) {
      setTimeout(() => {
        _salvarFreteAutomaticamente(id, { payloadOverride: queuedPayload, retryDelay }).catch((err) => {
          console.warn("Erro ao reenfileirar salvamento do frete:", err);
        });
      }, retryDelay);
    } else if (!state.focused) {
      const freteRender = _findFreteById(id);
      if (freteRender) _renderOrUpdateFreteCard(freteRender, { force: true });
    }
    _renderFreteSaveStatus(_getFreteCard(id), id);
  }
}

async function _atualizarStatusFrete(id, novoStatus){
  const freteAtual = _findFreteById(id);
  if (!freteAtual) return null;
  const atualizado = await atualizarFreteCompleto(id, { status: novoStatus });
  if (atualizado) {
    const state = freteDraftState.get(_freteKey(id));
    if (state) {
      state.draft = _cloneFretePayload(atualizado);
      state.lastSavedSignature = _fretePayloadSignature(state.draft);
      state.dirty = false;
      state.error = "";
      state.saving = false;
      state.queued = false;
      state.queuedPayload = null;
      _clearFreteSaveTimer(state);
    }
    _setFreteLocal(atualizado);
    _renderOrUpdateFreteCard(atualizado, { force: true });
  }
  return atualizado;
}

async function _moverFreteStatusAdjacente(frete, direcao){
  if (!frete) return;
  const idx = _indiceStatusFrete(frete.status);
  if (idx < 0) return;
  const destinoIdx = idx + direcao;
  if (destinoIdx < 0 || destinoIdx >= FRETE_STATUS_OPCOES.length) return;
  const destino = FRETE_STATUS_OPCOES[destinoIdx]?.key;
  if (!destino || destino === frete.status) return;
  await _atualizarStatusFrete(frete.id, destino);
}

async function _moverFreteStatusAdjacenteComFeedback(frete, direcao){
  try {
    await _moverFreteStatusAdjacente(frete, direcao);
  } catch (err) {
    alert(err?.message || "Nao foi possivel mover o frete.");
  }
}

function _freteCardTemplate(frete){
  const data = _cloneFretePayload(frete);
  return `
    <div class="card-header" draggable="true" data-frete-id="${_escAttr(String(frete.id))}">
      <span class="frete-card-header-title">Arrastar</span>
      <div class="frete-card-actions" aria-label="Acoes do card">
        <button class="btn-mover-mobile btn-mover-mobile-prev" type="button" aria-label="Mover para a coluna anterior">←</button>
        <button class="btn-mover-mobile btn-mover-mobile-next" type="button" aria-label="Mover para a coluna seguinte">→</button>
        <button class="btn-excluir-icon" type="button" aria-label="Excluir frete">×</button>
      </div>
    </div>
    <div class="card-body">
      <div class="frete-carga-info">${_escHtml(_resumoFreteCabecalho(data) || "-")}</div>
      <div class="frete-card-compact-grid">
        <div>
          <span>Veículo</span>
          <strong class="frete-veiculo-resumo">${_escHtml(_resumoVeiculoPlacaFrete(data) || "-")}</strong>
        </div>
        <div>
          <span>Motorista</span>
          <strong class="frete-card-motorista">${_escHtml(data.colaborador_motorista_nome || data.motorista_nome || "-")}</strong>
        </div>
      </div>
      <div class="frete-card-footer">
        <button class="btn-dados" type="button">Dados</button>
      </div>
    </div>
  `;
}

function _atualizarResumoCompactoFreteCard(card, data){
  if (!card) return;
  const payload = data || {};
  const infoCarga = card.querySelector(".frete-carga-info");
  const infoVeiculo = card.querySelector(".frete-veiculo-resumo");
  const infoMotorista = card.querySelector(".frete-card-motorista");
  if (infoCarga) infoCarga.textContent = _resumoFreteCabecalho(payload) || "-";
  if (infoVeiculo) infoVeiculo.textContent = _resumoVeiculoPlacaFrete(payload) || "-";
  if (infoMotorista) infoMotorista.textContent = payload.colaborador_motorista_nome || payload.motorista_nome || "-";
}

function _abrirFreteDadosDoCard(id, tab = "dados"){
  const freteAtual = _findFreteById(id);
  if (!freteAtual) return;
  abrirDetalhesFrete(id, tab);
}

function _preencherFreteCard(card, frete){
  const data = _cloneFretePayload(frete);
  _atualizarResumoCompactoFreteCard(card, data);
  _atualizarBotoesMovimentoMobile(card, data.status);

  const btnDados = card.querySelector(".btn-dados");
  const btnExcluir = card.querySelector(".btn-excluir-icon");
  const btnMoverPrev = card.querySelector(".btn-mover-mobile-prev");
  const btnMoverNext = card.querySelector(".btn-mover-mobile-next");

  if (btnDados) btnDados.onclick = () => _abrirFreteDadosDoCard(frete.id, "dados");
  if (btnExcluir) {
    btnExcluir.onclick = async () => {
      if (!confirm("Deseja excluir este frete?")) return;
      await excluirFrete(frete.id);
    };
  }
  if (btnMoverPrev) {
    btnMoverPrev.onclick = async () => {
      const freteAtual = _findFreteById(frete.id);
      if (freteAtual) await _moverFreteStatusAdjacenteComFeedback(freteAtual, -1);
    };
  }
  if (btnMoverNext) {
    btnMoverNext.onclick = async () => {
      const freteAtual = _findFreteById(frete.id);
      if (freteAtual) await _moverFreteStatusAdjacenteComFeedback(freteAtual, 1);
    };
  }
}

function _bindFreteCardEvents(card){
  const id = card.dataset.freteId;
  const header = card.querySelector(".card-header");
  const cardBody = card.querySelector(".card-body");
  if (header) {
    header.draggable = true;
    header.ondragstart = (e) => e.dataTransfer.setData("id", id);
  }
  if (cardBody) {
    cardBody.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      _abrirFreteDadosDoCard(id, "dados");
    });
  }
}

function _renderOrUpdateFreteCard(frete, options = {}){
  const { force = false } = options;
  if (!frete || frete.id == null) return null;
  const colunas = _freteColunas();
  const targetCol = colunas[frete.status];
  if (!targetCol) return null;

  let card = _getFreteCard(frete.id);
  const signature = _freteRemoteSignature(frete);
  const locked = _isFreteCardLocked(frete.id);
  const mesmaColuna = !!(card && card.parentElement === targetCol);
  const precisaRecriarTemplate = !!(card && card.dataset.templateVersion !== FRETE_CARD_TEMPLATE_VERSION);

  if (card && locked && !force) {
    _renderFreteSaveStatus(card, frete.id);
    return card;
  }

  if (!card || (precisaRecriarTemplate && (!locked || force))) {
    const cardAntigo = card;
    card = document.createElement("div");
    card.className = "card";
    card.dataset.freteId = String(frete.id);
    card.dataset.templateVersion = FRETE_CARD_TEMPLATE_VERSION;
    card.innerHTML = _freteCardTemplate(frete);
    _bindFreteCardEvents(card);
    if (cardAntigo) cardAntigo.replaceWith(card);
  } else if (!force && !precisaRecriarTemplate && card.dataset.remoteSignature === signature) {
    if (!mesmaColuna) targetCol.appendChild(card);
    _renderFreteSaveStatus(card, frete.id);
    _agendarEqualizacaoAlturaKanban();
    return card;
  }

  _preencherFreteCard(card, frete);
  card.dataset.remoteSignature = signature;
  card.dataset.templateVersion = FRETE_CARD_TEMPLATE_VERSION;
  if (!mesmaColuna) targetCol.appendChild(card);
  _renderFreteSaveStatus(card, frete.id);
  _agendarEqualizacaoAlturaKanban();
  return card;
}

async function moverFreteMobile(frete){
  if (!frete) return;
  const atual = String(frete.status || "");
  const opcoes = FRETE_STATUS_OPCOES
    .map((s, idx) => `${idx + 1}. ${s.label}${s.key === atual ? " (atual)" : ""}`)
    .join("\n");
  const entrada = prompt(
    `Mover "${_rotuloFreteExibicao(frete)}" para:\n\n${opcoes}\n\nDigite o numero do destino:`,
    ""
  );
  if (entrada == null) return;
  const idx = Number(String(entrada).trim()) - 1;
  if (!Number.isInteger(idx) || idx < 0 || idx >= FRETE_STATUS_OPCOES.length) {
    alert("Opcao invalida.");
    return;
  }
  const destino = FRETE_STATUS_OPCOES[idx].key;
  if (destino === atual) return;
  await _atualizarStatusFrete(frete.id, destino);
}

async function carregarInfoFrete() {
  let freteId = document.getElementById("dev_frete").value;
  if (!freteId) return;

  let r = await apiFetch("/api/fretes");
  let fretes = await r.json();

  let frete = fretes.find((f) => f.id == freteId);
  if (!frete) return;

  document.getElementById("infoFreteSelecionado").innerHTML = `
    🚛 ${frete.veiculo_nome || _rotuloVeiculoCadastradoDoFrete(frete) || "-"} |
    👤 ${frete.motorista_nome || "-"} |
    📦 ${frete.carga_nome || "-"}
  `;
}

async function toggleNovoFrete() {
  const card = document.getElementById("cardNovoFrete");

  if (card.classList.contains("hidden")) {
    card.classList.remove("hidden");
    await carregarSelectsNovoFrete();
    const dataCarga = document.getElementById("novoFreteDataCarga");
    if (dataCarga && !dataCarga.value) dataCarga.value = _hojeInputDate();
  } else {
    card.classList.add("hidden");
  }
}

async function toggleArquivados() {
  const fretesSection = document.getElementById("fretes");
  const arquivadosSection = document.getElementById("fretesArquivados");

  if (arquivadosSection.classList.contains("hidden")) {
    // Mostrar arquivados
    fretesSection.classList.add("hidden");
    fretesSection.classList.remove("activeSection");
    arquivadosSection.classList.remove("hidden");
    arquivadosSection.classList.add("activeSection");
    await renderFretesArquivados();
  } else {
    // Voltar ao kanban
    arquivadosSection.classList.add("hidden");
    arquivadosSection.classList.remove("activeSection");
    fretesSection.classList.remove("hidden");
    fretesSection.classList.add("activeSection");
    await renderFretes();
  }
}

async function renderFretesArquivados(filtro = "") {
  const container = document.getElementById("fretesArquivadosContainer");
  if (!container) return;

  container.innerHTML = '<div class="loading">Carregando fretes arquivados...</div>';
  await ensureCadastrosCache();

  // Filtrar fretes arquivados
  const arquivados = fretes.filter(f => f.arquivado && _freteCombinaBusca(f, filtro));

  container.innerHTML = '';

  if (arquivados.length === 0) {
    container.innerHTML = '<div class="empty-state">Nenhum frete arquivado encontrado.</div>';
    return;
  }

  // Renderizar como lista/grid de cards read-only
  arquivados.forEach(f => {
    const card = document.createElement("div");
    card.className = "card card-arquivado";
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", `Ver detalhes do frete arquivado ${f.nome || f.id || ""}`.trim());
    const veiculo = f.veiculo_nome || _rotuloVeiculoCadastradoDoFrete(f) || _getNomeById(cacheCadastros.veiculos, f.veiculo_id) || "N/A";
    const motorista = f.motorista_nome || _getNomeColaborador(f.colaborador_motorista_id || f.motorista_id) || "N/A";
    const entregador = f.entregador_nome || _getNomeColaborador(f.colaborador_entregador_id || f.entregador_id) || "N/A";
    const dataCarga = f.data_carga ? _fmtDataCurtaBr(f.data_carga) : "N/A";
    card.innerHTML = `
      <div class="card-header">
        <span>${_escHtml(f.nome || "(sem nome)")}</span>
        <small>Arquivado em ${_escHtml(_formatDate(f.finalizado_em))}</small>
      </div>
      <div class="card-body">
        <div class="arquivado-info">
          <div><strong>Veiculo:</strong> ${_escHtml(veiculo)}</div>
          <div><strong>Motorista:</strong> ${_escHtml(motorista)}</div>
          <div><strong>Entregador:</strong> ${_escHtml(entregador)}</div>
          <div><strong>Data carga:</strong> ${_escHtml(dataCarga)}</div>
          <div><strong>Status final:</strong> ${_escHtml(f.status || 'N/A')}</div>
          <div><strong>Observacao:</strong> ${_escHtml(f.observacao || 'N/A')}</div>
        </div>
        <div class="crud-actions">
          <button class="btn-primary btn-arquivado-detalhes" type="button">${f.carga_id ? "Ver tudo" : "Detalhes"}</button>
          <button class="btn-secondary btn-arquivado-desarquivar" type="button">Desarquivar</button>
        </div>
      </div>
    `;
    card.addEventListener("click", (ev) => {
      if (ev.target?.closest?.("button")) return;
      abrirDetalhesFreteArquivado(f.id);
    });
    card.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      ev.preventDefault();
      abrirDetalhesFreteArquivado(f.id);
    });
    card.querySelector(".btn-arquivado-detalhes")?.addEventListener("click", (ev) => {
      ev.stopPropagation();
      abrirDetalhesFreteArquivado(f.id);
    });
    card.querySelector(".btn-arquivado-desarquivar")?.addEventListener("click", (ev) => {
      ev.stopPropagation();
      desarquivarFrete(f.id);
    });
    container.appendChild(card);
  });
}

function filtrarFretesArquivados(filtro) {
  renderFretesArquivados(filtro);
}

function _freteCamposRegistradosHtml(frete = {}) {
  const rows = Object.entries(frete)
    .sort(([a], [b]) => String(a).localeCompare(String(b), "pt-BR"))
    .map(([campo, valor]) => {
      const texto = valor && typeof valor === "object"
        ? JSON.stringify(valor, null, 2)
        : String(valor ?? "-");
      return `
        <tr>
          <td>${_escHtml(campo)}</td>
          <td><pre style="white-space:pre-wrap;margin:0;">${_escHtml(texto)}</pre></td>
        </tr>
      `;
    });
  if (!rows.length) return "";
  return `
    <div class="frota-historico-card">
      <h4>Campos gravados no frete</h4>
      <details open>
        <summary>Ver todos os campos do registro</summary>
        <div class="frota-historico-table-wrap">
          <table class="frota-historico-table">
            <thead><tr><th>Campo</th><th>Valor</th></tr></thead>
            <tbody>${rows.join("")}</tbody>
          </table>
        </div>
      </details>
    </div>
  `;
}

function _freteResumoDetalhadoHtml(frete = {}) {
  return `
    <div class="frota-historico-card">
      <h4>Resumo do frete</h4>
      <div class="frota-historico-kv">
        ${_frotaHistoricoResumoRow("Nome", frete.nome || "-")}
        ${_frotaHistoricoResumoRow("Status", frete.status || "-")}
        ${_frotaHistoricoResumoRow("Cidade", frete.cidade || "-")}
        ${_frotaHistoricoResumoRow("Rota", frete.carga_rota || frete.rota || "-")}
        ${_frotaHistoricoResumoRow("Veiculo importado", frete.carga_veiculo_numero || "-")}
        ${_frotaHistoricoResumoRow("Veiculo cadastrado", _rotuloVeiculoCadastradoDoFrete(frete) || frete.veiculo_nome || "-")}
        ${_frotaHistoricoResumoRow("Motorista", frete.motorista_nome || _getNomeColaborador(frete.colaborador_motorista_id || frete.motorista_id) || "-")}
        ${_frotaHistoricoResumoRow("Entregador", frete.entregador_nome || _getNomeColaborador(frete.colaborador_entregador_id || frete.entregador_id) || "-")}
        ${_frotaHistoricoResumoRow("Data carga", frete.data_carga ? _fmtDataCurtaBr(frete.data_carga) : "-")}
        ${_frotaHistoricoResumoRow("KM atual", frete.km_atual ?? 0)}
        ${_frotaHistoricoResumoRow("Peso", _fmtNumeroCarga(frete.peso, 3))}
        ${_frotaHistoricoResumoRow("Entregas", frete.qtd_entregas ?? frete.numero_entregas ?? 0)}
        ${_frotaHistoricoResumoRow("Carga vinculada", frete.carga_id || "-")}
        ${_frotaHistoricoResumoRow("Criado em", frete.created_at ? _fmtDateBr(frete.created_at) : "-")}
        ${_frotaHistoricoResumoRow("Atualizado em", frete.updated_at ? _fmtDateBr(frete.updated_at) : "-")}
        ${_frotaHistoricoResumoRow("Finalizado em", frete.finalizado_em ? _fmtDateBr(frete.finalizado_em) : "-")}
        ${_frotaHistoricoResumoRow("Arquivado", frete.arquivado ? "Sim" : "Nao")}
        ${_frotaHistoricoResumoRow("Observacao", frete.observacao || "-")}
      </div>
    </div>
  `;
}

async function abrirDetalhesFreteArquivado(freteId) {
  const frete = _findFreteById(freteId);
  if (!frete) {
    alert("Frete arquivado nao encontrado.");
    return;
  }
  if (Number(frete.carga_id) > 0) {
    await abrirDetalhesCarga(frete.carga_id);
    return;
  }

  const modal = document.getElementById("cargaDetalheModal");
  const body = document.getElementById("cargaDetalheBody");
  const title = modal?.querySelector(".foto-modal-header h3");
  if (!modal || !body) return;

  await ensureCadastrosCache();
  if (title) title.textContent = "Detalhes do Frete Arquivado";
  body.innerHTML = `
    <div class="frota-historico-grid">
      ${_freteResumoDetalhadoHtml(frete)}
      ${_freteCamposRegistradosHtml(frete)}
    </div>
  `;
  _abrirPopupBloqueante(modal);
}

async function desarquivarFrete(freteId) {
  if (!confirm("Deseja desarquivar este frete? Ele voltará ao Kanban ativo.")) return;

  try {
    const r = await apiFetch(`/api/fretes/${freteId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arquivado: false })
    });

    if (!r.ok) throw new Error("Erro ao desarquivar frete.");

    // Recarregar fretes e voltar ao kanban
    await carregarFretes();
    toggleArquivados();
  } catch (e) {
    alert("Erro ao desarquivar frete: " + e.message);
  }
}

async function salvarFrete() {
  let nome = document.getElementById("novoFreteNome").value;
  let dataCarga = document.getElementById("novoFreteDataCarga").value;
  let motorista = document.getElementById("novoFreteMotorista").value;
  let entregador = document.getElementById("novoFreteEntregador").value;
  let veiculo = document.getElementById("novoFreteVeiculo").value;
  let carga = document.getElementById("novoFreteCarga").value;
  let kmAtual = document.getElementById("novoFreteKmAtual").value;
  let peso = document.getElementById("novoFretePeso").value;
  let qtdEntregas = document.getElementById("novoFreteQtdEntregas").value;

  const motoristaId = motorista ? Number(motorista) : null;
  const entregadorId = _resolverEntregadorPadrao(motoristaId, entregador ? Number(entregador) : null);

  if (!nome || !motoristaId || !entregadorId || !veiculo || !carga) {
    return alert("Informe nome, motorista, entregador, veiculo e carga.");
  }

  const resp = await apiFetch("/api/fretes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      nome: nome,
      data_carga: dataCarga || _hojeInputDate(),
      motorista_id: motoristaId,
      colaborador_motorista_id: motoristaId,
      entregador_id: entregadorId,
      colaborador_entregador_id: entregadorId,
      veiculo_id: veiculo,
      carga_id: carga,
      km_atual: kmAtual ? Number(kmAtual) : 0,
      peso: peso ? Number(peso) : 0,
      qtd_entregas: qtdEntregas ? Number(qtdEntregas) : 0,
    }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || data?.ok === false) {
    alert(data?.erro || "Erro ao criar frete.");
    return;
  }

  await carregarFretes();
  await atualizarDash();
  document.getElementById("novoFreteNome").value = "";
  document.getElementById("novoFreteDataCarga").value = _hojeInputDate();
  document.getElementById("novoFreteMotorista").value = "";
  document.getElementById("novoFreteEntregador").value = "";
  document.getElementById("novoFreteVeiculo").value = "";
  document.getElementById("novoFreteCarga").value = "";
  document.getElementById("novoFreteKmAtual").value = "";
  document.getElementById("novoFretePeso").value = "";
  document.getElementById("novoFreteQtdEntregas").value = "";
}

async function preencherSelect(tipo, selectId, textoPadrao) {
  let r = await apiFetch(`/api/${tipo}`);
  let dados = await r.json();

  let select = document.getElementById(selectId);
  if (!select) return;

  select.innerHTML = `<option value="">${textoPadrao}</option>`;
  dados.forEach((item) => {
    const label = item.optionLabel || (tipo === "cargas" && item.veiculo_numero
      ? `${item.nome || item.cidade || "Carga"} - Veiculo ${item.veiculo_numero}`
      : item.nome);
    select.innerHTML += `<option value="${item.id}">${_escHtml(label || "")}</option>`;
  });
}

async function excluirFrete(id) {
  if (!confirm("Deseja realmente excluir este frete?")) return;

  const resp = await apiFetch(`/api/fretes/${id}`, { method: "DELETE" });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || data?.ok === false) {
    alert(data?.erro || "Erro ao excluir frete.");
    return;
  }
  const key = _freteKey(id);
  const state = freteDraftState.get(key);
  if (state) _clearFreteSaveTimer(state);
  freteDraftState.delete(key);
  _removeFreteLocal(id);
  const card = _getFreteCard(id);
  if (card) card.remove();
  _agendarEqualizacaoAlturaKanban();
  await atualizarDash();
  if (window.__cargasView === "escala") {
    await renderEscala().catch(() => {});
  }
}

function ativarDragDrop() {
  _bindKanbanDesktopAutoScroll(document.querySelector("#fretes .kanban"));

  async function processarDrop(e, col) {
    e.preventDefault();

    const id = e.dataTransfer?.getData("id");
    const novoStatus = col.dataset.status;
    if (!id || !novoStatus) return;

    const frete = fretes.find((f) => f.id == id);
    if (!frete) return;

    try {
      await _atualizarStatusFrete(frete.id, novoStatus);
    } catch (err) {
      alert(err?.message || "Nao foi possivel mover o frete.");
    }
  }

  document.querySelectorAll(".kanban-col").forEach((col) => {
    const alvosDrop = [col, col.querySelector(".kanban-cards")].filter(Boolean);
    alvosDrop.forEach((alvo) => {
      if (alvo.dataset.dragdropBound === "1") return;
      alvo.dataset.dragdropBound = "1";
      alvo.addEventListener("dragover", (e) => {
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
      });
      alvo.addEventListener("drop", async (e) => {
        await processarDrop(e, col);
      });
    });
  });
}

// ===============================
// DRAG & DROP NO CELULAR (TOUCH)
// ===============================
function ativarDragDropMobile() {
  // só ativa em telas pequenas
  if (!window.matchMedia("(max-width: 768px)").matches) return;

  const kanban = document.querySelector(".kanban");
  if (!kanban) return;

  let pendingId = null;
  let draggingId = null;
  let draggingCard = null;
  let holdTimer = null;
  let startX = 0;
  let startY = 0;
  let lastHoverCol = null;
  const HOLD_MS = 170;
  const MOVE_CANCEL_THRESHOLD = 10;

  function colFromPoint(x, y) {
    const el = document.elementFromPoint(x, y);
    if (!el) return null;
    const zonaCards = el.closest(".kanban-cards");
    if (zonaCards) return zonaCards.closest(".kanban-col");
    return el.closest(".kanban-col");
  }

  function clearHighlight() {
    document.querySelectorAll(".kanban-col").forEach(c => c.classList.remove("highlight"));
  }

  function resetState() {
    pendingId = null;
    draggingId = null;
    if (holdTimer) {
      clearTimeout(holdTimer);
      holdTimer = null;
    }
    if (draggingCard) draggingCard.classList.remove("dragging-touch");
    draggingCard = null;
    lastHoverCol = null;
    clearHighlight();
  }

  // vincula eventos no cabeçalho (handle do arraste)
  document.querySelectorAll(".kanban-col .card-header").forEach(header => {
    if (header.dataset.touchBound === "1") return;
    header.dataset.touchBound = "1";

    header.addEventListener("touchstart", (e) => {
      const id = header.dataset.freteId;
      if (!id) return;

      const t = e.touches && e.touches[0];
      if (!t) return;
      pendingId = id;
      draggingId = null;
      draggingCard = header.closest(".card");
      startX = t.clientX;
      startY = t.clientY;
      lastHoverCol = null;
      clearHighlight();

      if (holdTimer) clearTimeout(holdTimer);
      holdTimer = setTimeout(() => {
        draggingId = pendingId;
        pendingId = null;
        if (draggingCard) draggingCard.classList.add("dragging-touch");
      }, HOLD_MS);
    }, { passive: true });

    header.addEventListener("touchmove", (e) => {
      const t = e.touches && e.touches[0];
      if (!t) return;

      if (!draggingId) {
        const dx = Math.abs(t.clientX - startX);
        const dy = Math.abs(t.clientY - startY);
        if (Math.max(dx, dy) > MOVE_CANCEL_THRESHOLD) {
          if (holdTimer) {
            clearTimeout(holdTimer);
            holdTimer = null;
          }
          pendingId = null;
        }
        return;
      }

      // auto-scroll horizontal do kanban durante o arraste
      const edge = 52;
      if (t.clientX < edge) kanban.scrollLeft -= 16;
      if (t.clientX > (window.innerWidth - edge)) kanban.scrollLeft += 16;

      const col = colFromPoint(t.clientX, t.clientY);
      clearHighlight();
      if (col) {
        col.classList.add("highlight");
        lastHoverCol = col;
      } else {
        lastHoverCol = null;
      }
      e.preventDefault();
    }, { passive: false });

    header.addEventListener("touchend", async (e) => {
      if (holdTimer) {
        clearTimeout(holdTimer);
        holdTimer = null;
      }
      const id = draggingId;
      if (!id) {
        resetState();
        return;
      }

      try {
        if (lastHoverCol) {
          const novoStatus = lastHoverCol.dataset.status;
          const frete = fretes.find(f => String(f.id) === String(id));
          if (frete && novoStatus && novoStatus !== frete.status) {
            await _atualizarStatusFrete(frete.id, novoStatus);
          }
        }
      } finally {
        resetState();
      }
      e.preventDefault();
    }, { passive: false });

    header.addEventListener("touchcancel", () => {
      resetState();
    }, { passive: true });
  });
}

async function carregarSelectsNovoFrete() {
  await preencherSelectColaboradores("novoFreteMotorista", "motorista", "Selecione motorista");
  await preencherSelectColaboradores("novoFreteEntregador", "entregador", "Selecione entregador");
  await preencherSelect("veiculos", "novoFreteVeiculo", "Selecione veículo");
  await preencherSelect("cargas", "novoFreteCarga", "Selecione carga");
  _bindNovoFreteKmAtual();
}

//////////////////////////////////////////////////////
// DELETE GENÉRICO
//////////////////////////////////////////////////////
async function deletar(tipo, id) {
  if (!confirm("Deseja excluir?")) return;

  // Deleta do servidor
  await apiFetch(`/api/${tipo}/${id}`, { method: "DELETE" });

  // Força recarregar o cache deste tipo
  cacheCadastros[tipo] = null; // Marca como inválido
  if (tipo === "colaboradores" || tipo === "usuarios") {
    cacheUsuarios = null;
  }

  // Recarrega do servidor
  await renderCadastros();

  await carregarSelectsNovoFrete();
  await renderFretes().catch(() => {});
  if (window.__cargasView === "escala") {
    await renderEscala().catch(() => {});
  }
}

//////////////////////////////////////////////////////
// DEVOLUÇÕES (mantive sua lógica original)
//////////////////////////////////////////////////////

async function abrirFotosDevolucao(id) {
  const modal = document.getElementById("fotoModal");
  const body = document.getElementById("fotoModalBody");
  if (!modal || !body) return;

  body.innerHTML = "Carregando...";

  const r = await apiFetch(`/api/devolucoes/${id}/fotos`);
  if (!r.ok) {
    body.innerHTML = "Erro ao carregar fotos.";
    _abrirPopupBloqueante(modal);
    return;
  }

  const j = await r.json();
  const fotos = j.fotos || [];

  if (!fotos.length) {
    body.innerHTML = "Nenhuma foto anexada.";
    _abrirPopupBloqueante(modal);
    return;
  }

  body.innerHTML = fotos
    .map((url) => `<img src="${url}" alt="Foto devolução ${id}">`)
    .join("");

  _abrirPopupBloqueante(modal);
}

function fecharFotosDevolucao(e) {
  // se clicar no fundo (overlay), fecha também
  const modal = document.getElementById("fotoModal");
  _fecharPopupBloqueante(modal);
}

function fecharHistoricoFrota(e) {
  const modal = document.getElementById("frotaHistoricoModal");
  _fecharPopupBloqueante(modal);
}

function _frotaHistoricoResumoRow(label, value) {
  return `<div class="k">${_escHtml(label)}</div><div class="v">${_escHtml(String(value ?? "-"))}</div>`;
}

function _frotaHistoricoTable(headers, rowsHtml, emptyMsg) {
  if (!rowsHtml.length) return `<div>${_escHtml(emptyMsg)}</div>`;
  return `
    <div class="frota-historico-table-wrap">
      <table class="frota-historico-table">
        <thead><tr>${headers.map((h) => `<th>${_escHtml(h)}</th>`).join("")}</tr></thead>
        <tbody>${rowsHtml.join("")}</tbody>
      </table>
    </div>
  `;
}

function fecharDetalhesCarga(e) {
  const modal = document.getElementById("cargaDetalheModal");
  _fecharPopupBloqueante(modal);
}

function fecharDetalhesFrete(e) {
  const modal = document.getElementById("freteDetalheModal");
  _fecharPopupBloqueante(modal);
}

function _freteDetalheDadosTemplate(frete) {
  return `
    <div class="frete-detail-grid">
      <div class="crud-field crud-field--full">
        <span>Nome do frete</span>
        <input type="text" class="frete-nome" value="${_escAttr(String(frete.nome || frete.frete_nome || ""))}">
      </div>
      <div class="crud-field">
        <span>Data carga</span>
        <input type="date" class="frete-data-carga" value="${_escAttr(String(frete.data_carga || ""))}">
      </div>
      <div class="crud-field">
        <span>Veiculo</span>
        <select class="frete-veiculo">
          ${optionsFrom(cacheCadastros.veiculos, frete.veiculo_id || _resolverVeiculoIdDoFrete(frete))}
        </select>
      </div>
      <div class="crud-field">
        <span>Motorista</span>
        <select class="frete-motorista">
          ${optionsFromColaboradores("motorista", frete.motorista_id)}
        </select>
      </div>
      <div class="crud-field">
        <span>Entregador</span>
        <select class="frete-entregador">
          ${optionsFromColaboradores("entregador", frete.entregador_id)}
        </select>
      </div>
      <div class="crud-field">
        <span>Carga</span>
        <select class="frete-carga">
          ${optionsFrom(cacheCadastros.cargas, frete.carga_id)}
        </select>
      </div>
      <div class="crud-field">
        <span>KM atual</span>
        <input type="number" class="frete-km-atual" min="0" value="${_escAttr(String(frete.km_atual ?? 0))}">
      </div>
      <div class="crud-field">
        <span>Peso</span>
        <input type="number" class="frete-peso" min="0" step="0.001" value="${_escAttr(String(frete.peso ?? 0))}">
      </div>
      <div class="crud-field">
        <span>Entregas</span>
        <input type="number" class="frete-qtd-entregas" min="0" value="${_escAttr(String(frete.qtd_entregas ?? 0))}">
      </div>
      <div class="crud-field crud-field--full">
        <span>Observacao</span>
        <textarea class="frete-obs" rows="4" placeholder="Digite uma observacao...">${_escHtml(frete.observacao || "")}</textarea>
      </div>
    </div>
    <div class="crud-actions frete-detail-actions">
      <button class="btn-primary btn-salvar-frete" type="button">Salvar</button>
      <button class="btn-secondary" type="button" onclick="fecharDetalhesFrete()">Fechar</button>
    </div>
  `;
}

function _freteDetalheCargaTemplate(frete) {
  const cargaId = frete.carga_id;
  return `
    <div class="frete-detail-carga-summary">
      ${cargaId ? `
        <p><strong>ID da carga:</strong> ${_escHtml(String(cargaId))}</p>
        ${frete.carga_nome ? `<p><strong>Nome da carga:</strong> ${_escHtml(frete.carga_nome)}</p>` : ""}
        ${frete.carga_cidades ? `<p><strong>Cidades:</strong> ${_escHtml(frete.carga_cidades)}</p>` : ""}
        ${frete.carga_rota ? `<p><strong>Rota:</strong> ${_escHtml(frete.carga_rota)}</p>` : ""}
        <button class="btn-primary btn-abre-carga" type="button">Ver detalhes da carga</button>
      ` : `<p>Este frete não possui carga vinculada.</p>`}
    </div>
  `;
}

function _freteDetalheNotasSaidaTemplate(notas) {
  if (!Array.isArray(notas) || !notas.length) {
    return `<div class="frete-detail-empty">Nenhuma nota de saida vinculada a este frete.</div>`;
  }
  return `
    <div class="frete-notas-summary">${notas.length} nota(s) de saida vinculada(s)</div>
    <div class="frota-historico-table-wrap">
      <table class="frota-historico-table">
        <thead>
          <tr>
            <th>Nota</th>
            <th>Emissao</th>
            <th>Rota registrada</th>
            <th>Vinculo XML</th>
            <th>Destino</th>
            <th>Itens</th>
            <th>Quantidade</th>
            <th>Valor</th>
            <th>Registro</th>
          </tr>
        </thead>
        <tbody>
          ${notas.map((nota) => `
            <tr>
              <td>
                <strong>${_escHtml(nota.numero_nota || "-")}</strong>
                ${nota.chave_nfe ? `<div class="hint">${_escHtml(nota.chave_nfe)}</div>` : ""}
              </td>
              <td>${_escHtml(_fmtDataCurtaBr(nota.data_emissao) || "-")}</td>
              <td>${_escHtml(nota.rota_registrada || "-")}</td>
              <td>
                ${_escHtml(nota.vinculacao_origem === "automatica_xml" ? "Automatico" : "Manual")}
                ${(nota.placa_xml || nota.mapa_xml) ? `<div class="hint">${_escHtml([
                  nota.placa_xml ? `Placa ${nota.placa_xml}` : "",
                  nota.mapa_xml ? `Mapa ${nota.mapa_xml}` : "",
                ].filter(Boolean).join(" | "))}</div>` : ""}
              </td>
              <td>${_escHtml(nota.destinatario_nome || "-")}</td>
              <td>${_escHtml(String(nota.itens_total || 0))}</td>
              <td>${_escHtml(_fmtNumeroCarga(nota.quantidade_total, 3))}</td>
              <td>${_escHtml(_fmtMoney(nota.valor_total_nota || 0))}</td>
              <td>
                ${_escHtml(_fmtDateBr(nota.criado_em) || nota.criado_em || "-")}
                ${nota.usuario_registro ? `<div class="hint">${_escHtml(nota.usuario_registro)}</div>` : ""}
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

async function _renderFreteDetalheTab(frete, tab = "dados") {
  const modal = document.getElementById("freteDetalheModal");
  const body = document.getElementById("freteDetalheBody");
  if (!modal || !body || !frete) return;
  modal.dataset.activeTab = tab;
  modal.querySelectorAll(".frete-detail-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tab);
  });
  if (tab === "carga") {
    if (frete.carga_id) {
      fecharDetalhesFrete();
      await abrirDetalhesCarga(frete.carga_id);
      return;
    }
    body.innerHTML = _freteDetalheCargaTemplate(frete);
  } else if (tab === "notas_saida") {
    body.innerHTML = `<div class="frete-detail-empty">Carregando notas de saida...</div>`;
    const resp = await apiFetch(`/api/fretes/${Number(frete.id)}/notas-saida`);
    const data = await resp.json().catch(() => ({}));
    body.innerHTML = resp.ok
      ? _freteDetalheNotasSaidaTemplate(data?.notas || [])
      : `<div class="frete-detail-empty">${_escHtml(data?.erro || "Falha ao carregar notas de saida.")}</div>`;
  } else {
    body.innerHTML = _freteDetalheDadosTemplate(frete);
  }
  const btnSalvar = body.querySelector(".btn-salvar-frete");
  if (btnSalvar) {
    btnSalvar.onclick = async () => {
      try {
        btnSalvar.disabled = true;
        btnSalvar.textContent = "Salvando...";
        const payload = _coletarPayloadFreteDoDetalheModal(frete);
        await atualizarFreteCompleto(Number(frete.id), payload);
        fecharDetalhesFrete();
        const atualizado = _findFreteById(frete.id);
        if (atualizado) _renderOrUpdateFreteCard(atualizado, { force: true });
      } catch (err) {
        alert(err?.message || "Erro ao salvar frete.");
      } finally {
        btnSalvar.disabled = false;
        btnSalvar.textContent = "Salvar";
      }
    };
  }
  const btnAbreCarga = body.querySelector(".btn-abre-carga");
  if (btnAbreCarga) {
    btnAbreCarga.onclick = async () => {
      fecharDetalhesFrete();
      await abrirDetalhesCarga(frete.carga_id);
    };
  }
}

function _bindFreteDetalheModalEvents(freteId) {
  const modal = document.getElementById("freteDetalheModal");
  if (!modal) return;
  modal.querySelectorAll(".frete-detail-tab").forEach((button) => {
    const abrirAba = async (event) => {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }
      const frete = _findFreteById(freteId);
      if (!frete) return;
      await _renderFreteDetalheTab(frete, button.dataset.tab || "dados");
    };
    button.onclick = abrirAba;
    button.ontouchend = abrirAba;
  });
}

async function abrirDetalhesFrete(freteId, initialTab = "dados"){
  const modal = document.getElementById("freteDetalheModal");
  const body = document.getElementById("freteDetalheBody");
  if (!modal || !body) return;
  const frete = _findFreteById(freteId);
  if (!frete) return;

  await ensureCadastrosCache();
  const state = _ensureFreteDraftState(frete);
  const data = _cloneFretePayload(state.dirty ? state.draft : frete);
  modal.dataset.freteId = String(freteId);
  _abrirPopupBloqueante(modal);
  _bindFreteDetalheModalEvents(freteId);
  await _renderFreteDetalheTab(data, initialTab);
}

function _coletarPayloadFreteDoDetalheModal(freteBase){
  const modal = document.getElementById("freteDetalheModal");
  if (!modal) return {};
  const body = modal.querySelector(".frete-detail-body");
  if (!body) return {};
  const inpDataCarga = body.querySelector(".frete-data-carga");
  const selVeiculo = body.querySelector(".frete-veiculo");
  const selMotorista = body.querySelector(".frete-motorista");
  const selEntregador = body.querySelector(".frete-entregador");
  const selCarga = body.querySelector(".frete-carga");
  const inpKmAtual = body.querySelector(".frete-km-atual");
  const inpPeso = body.querySelector(".frete-peso");
  const inpEntregas = body.querySelector(".frete-qtd-entregas");
  const txtObs = body.querySelector(".frete-obs");
  const txtNome = body.querySelector(".frete-nome");
  const motoristaId = selMotorista?.value ? Number(selMotorista.value) : null;
  const entregadorId = _resolverEntregadorPadrao(motoristaId, selEntregador?.value ? Number(selEntregador.value) : null);
  return {
    nome: (txtNome?.value || "").toString().trim() || (freteBase?.nome || freteBase?.frete_nome || "").toString().trim(),
    cidade: (freteBase?.cidade || "").toString().trim(),
    data_carga: _normalizarDataFreteInput(inpDataCarga?.value || freteBase?.data_carga || ""),
    status: (freteBase?.status || "liberado").toString(),
    veiculo_id: selVeiculo?.value ? Number(selVeiculo.value) : _resolverVeiculoIdDoFrete(freteBase || {}),
    motorista_id: motoristaId,
    colaborador_motorista_id: motoristaId,
    entregador_id: entregadorId,
    colaborador_entregador_id: entregadorId,
    carga_id: selCarga?.value ? Number(selCarga.value) : null,
    km_atual: inpKmAtual && inpKmAtual.value.trim() !== "" ? Number(inpKmAtual.value) : 0,
    peso: inpPeso && inpPeso.value.trim() !== "" ? Number(inpPeso.value) : 0,
    qtd_entregas: inpEntregas && inpEntregas.value.trim() !== "" ? Number(inpEntregas.value) : 0,
    observacao: (txtObs?.value || "").trim(),
    carga_rota: (freteBase?.carga_rota || "").toString().trim(),
    carga_cidades: (freteBase?.carga_cidades || "").toString().trim(),
    carga_veiculo_numero: (freteBase?.carga_veiculo_numero || "").toString().trim(),
    carga_nome: (freteBase?.carga_nome || "").toString().trim(),
    veiculo_nome: (freteBase?.veiculo_nome || "").toString().trim(),
    veiculo_placa: (freteBase?.veiculo_placa || "").toString().trim(),
  };
}

function _fmtNumeroCarga(v, casas = 3) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "-";
  return n.toLocaleString("pt-BR", {
    minimumFractionDigits: casas,
    maximumFractionDigits: casas,
  });
}

function _fmtDataCurtaBr(v){
  const raw = String(v || "").trim();
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (match) return `${match[3]}/${match[2]}/${match[1]}`;
  return _fmtDateBr(raw);
}

function _cargaTipoImportacaoLabel(tipo = ""){
  const valor = String(tipo || "").toLowerCase();
  if (valor === "pdf") return "PDF de carga";
  if (valor === "csv") return "CSV";
  return valor ? valor.toUpperCase() : "Manual";
}

function _cargaEstoqueStatusLabel(carga = {}, estoque = {}){
  const baixadoEm = estoque?.baixado_em || carga?.estoque_baixado_em || "";
  const baixadoPor = estoque?.baixado_por || carga?.estoque_baixado_por || "";
  if (baixadoEm) {
    return `Baixado em ${_fmtDateBr(baixadoEm)}${baixadoPor ? ` por ${baixadoPor}` : ""}`;
  }
  if (String(carga?.tipo_importacao || "").toLowerCase() === "pdf") {
    return "Aguardando baixa no estoque";
  }
  return "Sem baixa automatica";
}

async function abrirDetalhesCarga(cargaId) {
  const modal = document.getElementById("cargaDetalheModal");
  const body = document.getElementById("cargaDetalheBody");
  const title = modal?.querySelector(".foto-modal-header h3");
  if (!modal || !body) return;
  if (!(Number(cargaId) > 0)) return;

  await ensureCadastrosCache();
  if (title) title.textContent = "Detalhes da Carga";
  body.innerHTML = "Carregando detalhes da carga...";
  _abrirPopupBloqueante(modal);

  const r = await apiFetch(`/api/cargas/${cargaId}/detalhes`);
  const data = await r.json().catch(() => ({}));
  if (!r.ok || data?.ok === false) {
    body.innerHTML = _escHtml(data?.erro || "Erro ao carregar detalhes da carga.");
    return;
  }

  const carga = data.carga || {};
  const frete = data.frete || null;
  const linhas = Array.isArray(data.linhas) ? data.linhas : [];
  const itensEstoque = Array.isArray(data.itens_estoque) ? data.itens_estoque : [];
  const estoque = data.estoque || {};
  const resumo = data.resumo || {};

  const freteHtml = frete ? `
    <div class="frota-historico-card">
      <h4>Frete vinculado</h4>
      <div class="frota-historico-kv">
        ${_frotaHistoricoResumoRow("Nome", frete.nome || "-")}
        ${_frotaHistoricoResumoRow("Status", frete.status || "-")}
        ${_frotaHistoricoResumoRow("Cidade", frete.cidade || "-")}
        ${_frotaHistoricoResumoRow("Cidades", Array.isArray(carga.cidades) && carga.cidades.length ? carga.cidades.join(", ") : (carga.cidade || "-"))}
        ${_frotaHistoricoResumoRow("Veiculo importado", frete.carga_veiculo_numero || carga.veiculo_numero || "-")}
        ${_frotaHistoricoResumoRow("Veiculo cadastrado", _rotuloVeiculoCadastradoDoFrete(frete) || "-")}
        ${_frotaHistoricoResumoRow("Motorista", frete.motorista_nome || "-")}
        ${_frotaHistoricoResumoRow("Entregador", frete.entregador_nome || "-")}
        ${_frotaHistoricoResumoRow("Data carga", frete.data_carga ? _fmtDataCurtaBr(frete.data_carga) : "-")}
        ${_frotaHistoricoResumoRow("KM atual", frete.km_atual ?? 0)}
        ${_frotaHistoricoResumoRow("Peso", _fmtNumeroCarga(frete.peso, 3))}
        ${_frotaHistoricoResumoRow("Entregas", frete.qtd_entregas ?? 0)}
        ${_frotaHistoricoResumoRow("Observacao", frete.observacao || "-")}
      </div>
    </div>
    ${_freteCamposRegistradosHtml(frete)}
  ` : `
    <div class="frota-historico-card">
      <h4>Frete vinculado</h4>
      <div>Nenhum frete encontrado para esta carga.</div>
    </div>
  `;

  const itensEstoqueHtml = itensEstoque.map((item) => `
      <tr>
        <td>${_escHtml(String(item.item_seq || "-"))}</td>
        <td>${_escHtml(item.codigo_produto || item.codigo_barras || "-")}</td>
        <td>${_escHtml(item.nome_produto || "-")}</td>
        <td>${_escHtml(item.embalagem || item.unidade_embalagem || "-")}</td>
        <td>${_escHtml(_fmtNumeroCarga(item.quantidade_embalagem, 3))}</td>
        <td>${_escHtml(_fmtNumeroCarga(item.quantidade_solta, 3))}</td>
        <td>${_escHtml(_fmtNumeroCarga(item.fator_embalagem, 3))}</td>
        <td>${_escHtml(_fmtNumeroCarga(item.quantidade_total, 3))}</td>
        <td>${_escHtml(item.baixado_em ? _fmtDateBr(item.baixado_em) : "Pendente")}</td>
      </tr>
    `);

  const linhasHtml = linhas.map((linha) => {
    const bruto = typeof linha.dados_json === "string"
      ? linha.dados_json
      : JSON.stringify(linha.dados_json || {}, null, 2);
    return `
      <tr>
        <td>${_escHtml(String(linha.linha_num ?? ""))}</td>
        <td>${_escHtml(linha.cliente || "-")}</td>
        <td>${_escHtml(linha.veiculo_numero || carga.veiculo_numero || "-")}</td>
        <td>${_escHtml(linha.numero_nf || "-")}</td>
        <td>${_escHtml(linha.produto || "-")}</td>
        <td>${_escHtml(_fmtNumeroCarga(linha.quantidade, 3))}</td>
        <td>${_escHtml(_fmtNumeroCarga(linha.litro, 3))}</td>
        <td>${_escHtml(_fmtNumeroCarga(linha.peso, 3))}</td>
        <td>R$ ${_escHtml(_fmtMoney(linha.valor_venda ?? 0))}</td>
        <td>
          <details>
            <summary>Ver</summary>
            <pre style="white-space:pre-wrap;max-width:420px;">${_escHtml(bruto)}</pre>
          </details>
        </td>
      </tr>
    `;
  });

  body.innerHTML = `
    <div class="frota-historico-grid">
      <div class="frota-historico-card">
        <h4>Resumo da carga</h4>
        <div class="frota-historico-kv">
          ${_frotaHistoricoResumoRow("Carga", carga.nome || carga.cidade || "-")}
          ${_frotaHistoricoResumoRow("Tipo", _cargaTipoImportacaoLabel(carga.tipo_importacao))}
          ${_frotaHistoricoResumoRow("Mapa", carga.mapa_numero || "-")}
          ${_frotaHistoricoResumoRow("Cidade", Array.isArray(carga.cidades) && carga.cidades.length ? carga.cidades.join(", ") : (carga.cidade || "-"))}
          ${_frotaHistoricoResumoRow("Rota", carga.rota || "-")}
          ${_frotaHistoricoResumoRow("Veiculo", carga.veiculo_numero || "-")}
          ${_frotaHistoricoResumoRow("Arquivo origem", carga.arquivo_origem || carga.origem_csv || "-")}
          ${_frotaHistoricoResumoRow("Data carga", carga.data_carga ? _fmtDataCurtaBr(carga.data_carga) : "-")}
          ${_frotaHistoricoResumoRow("Entregas", carga.numero_entregas ?? 0)}
          ${_frotaHistoricoResumoRow("Volumes", _fmtNumeroCarga(carga.volumes_total ?? 0, 3))}
          ${_frotaHistoricoResumoRow("Linhas importadas", carga.registros_importados ?? resumo.linhas ?? 0)}
          ${_frotaHistoricoResumoRow("Itens estoque", resumo.itens_estoque ?? itensEstoque.length)}
          ${_frotaHistoricoResumoRow("Clientes distintos", carga.clientes_distintos ?? resumo.clientes ?? 0)}
          ${_frotaHistoricoResumoRow("Quantidade total", _fmtNumeroCarga(carga.quantidade_total ?? resumo.quantidade_total ?? 0, 3))}
          ${_frotaHistoricoResumoRow("Litros total", _fmtNumeroCarga(carga.litros_total ?? resumo.litros_total ?? 0, 3))}
          ${_frotaHistoricoResumoRow("Peso total", _fmtNumeroCarga(carga.peso_total ?? resumo.peso_total ?? 0, 3))}
          ${_frotaHistoricoResumoRow("Bonificacao", `R$ ${_fmtMoney(carga.valor_bonificacao ?? 0)}`)}
          ${_frotaHistoricoResumoRow("Valor total", `R$ ${_fmtMoney(carga.valor_total ?? resumo.valor_total ?? 0)}`)}
          ${_frotaHistoricoResumoRow("Estoque", _cargaEstoqueStatusLabel(carga, estoque))}
          ${_frotaHistoricoResumoRow("Atualizado em", carga.atualizado_em || "-")}
        </div>
      </div>
      ${freteHtml}
    </div>

    <div class="frota-historico-card">
      <h4>Itens para baixa de estoque</h4>
      <div class="frota-historico-table-wrap">
        <table class="frota-historico-table carga-detalhe-table">
          <thead>
            <tr>
              <th>Item</th>
              <th>Codigo</th>
              <th>Produto</th>
              <th>Emb.</th>
              <th>Qtd emb.</th>
              <th>Qtd solta</th>
              <th>Fator</th>
              <th>Total un.</th>
              <th>Baixa</th>
            </tr>
          </thead>
          <tbody>
            ${itensEstoqueHtml.length ? itensEstoqueHtml.join("") : `<tr><td colspan="9">Nenhum item de estoque vinculado a esta carga.</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>

    <div class="frota-historico-card">
      <h4>Linhas importadas</h4>
      <div class="frota-historico-table-wrap">
        <table class="frota-historico-table carga-detalhe-table">
          <thead>
            <tr>
              <th>Linha</th>
              <th>Cliente</th>
              <th>Veiculo</th>
              <th>NF</th>
              <th>Produto</th>
              <th>Qtd.</th>
              <th>Litros</th>
              <th>Peso</th>
              <th>Valor</th>
              <th>Bruto</th>
            </tr>
          </thead>
          <tbody>
            ${linhasHtml.length ? linhasHtml.join("") : `<tr><td colspan="10">Nenhuma linha CSV vinculada a esta carga.</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

async function preencherSelectFretes() {
  let r = await apiFetch("/api/fretes");
  let dados = await r.json();

  let select = document.getElementById("dev_frete");
  if (!select) return;

  select.innerHTML =
    '<option value="">Selecione o frete</option>' +
    dados
      .map(
        (f) => `
      <option value="${f.id}">
        ${f.nome}
      </option>
    `
      )
      .join("");
}

async function addDevolucao() {
  if (!dev_frete.value) return alert("Selecione o frete");
  if (!dev_conf.value) return alert("Selecione o conferente");

  let r = await apiFetch("/api/fretes");
  let listaFretes = await r.json();

  let frete = listaFretes.find((f) => f.id == dev_frete.value);
  if (!frete) return alert("Frete inválido");

  const fd = new FormData();
  fd.append("frete_id", String(dev_frete.value));
  fd.append("veiculo_id", String(frete.veiculo_id || ""));
  fd.append("conferente_id", String(dev_conf.value));
  fd.append("colaborador_conferente_id", String(dev_conf.value));

  fd.append("c24", String(dev_c24.value || 0));
  fd.append("c48", String(dev_c48.value || 0));
  fd.append("pet2l", String(dev_pet2l.value || 0));
  fd.append("pet600", String(dev_pet600.value || 0));
  fd.append("pet200", String(dev_pet200.value || 0));

  fd.append("obs_c24", (document.getElementById("dev_obs_c24")?.value || "").trim());
  fd.append("obs_c48", (document.getElementById("dev_obs_c48")?.value || "").trim());
  fd.append("obs_pet2l", (document.getElementById("dev_obs_pet2l")?.value || "").trim());
  fd.append("obs_pet600", (document.getElementById("dev_obs_pet600")?.value || "").trim());
  fd.append("obs_pet200", (document.getElementById("dev_obs_pet200")?.value || "").trim());
  // NOVOS CAMPOS
  fd.append("agua_com_gas", String(dev_agua_com_gas.value || 0));
  fd.append("obs_agua_com_gas", String(dev_obs_agua_com_gas.value || ""));
  fd.append("agua_sem_gas", String(dev_agua_sem_gas.value || 0));
  fd.append("obs_agua_sem_gas", String(dev_obs_agua_sem_gas.value || ""));
  fd.append("cx_600", String(dev_cx_600.value || 0));
  fd.append("obs_cx_600", String(dev_obs_cx_600.value || ""));

const galeria = document.getElementById("dev_fotos_galeria");
const camera  = document.getElementById("dev_fotos_camera");

const filesGaleria = galeria?.files ? Array.from(galeria.files) : [];
const fileCamera = (camera?.files && camera.files[0]) ? [camera.files[0]] : [];

[...filesGaleria, ...fileCamera].forEach((file) => fd.append("fotos", file));

  const resp = await fetch("/api/devolucoes", {
    method: "POST",
    body: fd
  });

  if (!resp.ok) {
    let t = "";
    try { t = await resp.text(); } catch {}
    console.error("Erro ao salvar devolução:", resp.status, t);
    return alert("Erro ao salvar devolução (veja o console F12).");
  }

  // limpa fotos para próxima
if (galeria) galeria.value = "";
if (camera) camera.value = "";

  await carregarDevolucoes();
  toggleNovaDevolucao();
}

async function toggleNovaDevolucao() {
  const card = document.getElementById("cardNovaDevolucao");

  if (card.classList.contains("hidden")) {
    card.classList.remove("hidden");
    await preencherSelectFretes();
    await preencherSelectColaboradores("dev_conf", "conferente", "Selecione conferente");
  } else {
    card.classList.add("hidden");
  }
}

let devolucoesCache = [];
let devolucaoEditandoId = null;

async function carregarDevolucoes() {
  const r = await fetch("/api/devolucoes");
  devolucoesCache = await r.json();

  devTable.innerHTML = devolucoesCache
    .map((d) => {
      const emEdicao = devolucaoEditandoId === d.id;

      if (!emEdicao) {
        const temFotos = !!(d.tem_fotos || (Array.isArray(d.fotos) && d.fotos.length));
        return `
          <tr>
            <td>${d.frete_nome || "-"}</td>
            <td>${d.veiculo_nome || "-"}</td>

            <td>${d.c24 ?? 0}</td><td>${d.obs_c24 || "-"}</td>
            <td>${d.c48 ?? 0}</td><td>${d.obs_c48 || "-"}</td>
            <td>${d.pet2l ?? 0}</td><td>${d.obs_pet2l || "-"}</td>
            <td>${d.pet600 ?? 0}</td><td>${d.obs_pet600 || "-"}</td>
            <td>${d.pet200 ?? 0}</td><td>${d.obs_pet200 || "-"}</td>
           <!-- ADICIONE ESTES CAMPOS NOVOS AQUI -->
            <td>${d.agua_com_gas ?? 0}</td><td>${d.obs_agua_com_gas || "-"}</td>
            <td>${d.agua_sem_gas ?? 0}</td><td>${d.obs_agua_sem_gas || "-"}</td>
            <td>${d.cx_600 ?? 0}</td><td>${d.obs_cx_600 || "-"}</td>

            <td>${d.conferente_nome || "-"}</td>

            <td>
              ${temFotos ? `<button title="Ver anexos" onclick="abrirFotosDevolucao(${d.id})">📎</button>` : "-"}
            </td>

            <td>
              <button onclick="editarDevolucaoInline(${d.id})">✏</button>
              <button onclick="excluirDevolucao(${d.id})">❌</button>
            </td>
          </tr>
        `;
      }

      return `
      <tr>
        <td>${d.frete_nome || "-"}</td>
        <td>${d.veiculo_nome || "-"}</td>

        <td><input type="number" min="0" id="ed_c24_${d.id}" value="${d.c24 ?? 0}" style="width:80px"></td>
        <td><input type="text" id="ed_obs_c24_${d.id}" value="${_escAttr(d.obs_c24 || "")}" placeholder="Obs Cx24"></td>

        <td><input type="number" min="0" id="ed_c48_${d.id}" value="${d.c48 ?? 0}" style="width:80px"></td>
        <td><input type="text" id="ed_obs_c48_${d.id}" value="${_escAttr(d.obs_c48 || "")}" placeholder="Obs Cx48"></td>

        <td><input type="number" min="0" id="ed_pet2l_${d.id}" value="${d.pet2l ?? 0}" style="width:80px"></td>
        <td><input type="text" id="ed_obs_pet2l_${d.id}" value="${_escAttr(d.obs_pet2l || "")}" placeholder="Obs Pet 2L"></td>

        <td><input type="number" min="0" id="ed_pet600_${d.id}" value="${d.pet600 ?? 0}" style="width:80px"></td>
        <td><input type="text" id="ed_obs_pet600_${d.id}" value="${_escAttr(d.obs_pet600 || "")}" placeholder="Obs Pet 600"></td>

        <td><input type="number" min="0" id="ed_pet200_${d.id}" value="${d.pet200 ?? 0}" style="width:80px"></td>
        <td><input type="text" id="ed_obs_pet200_${d.id}" value="${_escAttr(d.obs_pet200 || "")}" placeholder="Obs Pet 200"></td>

         <!-- NOVOS CAMPOS -->
        <td><input type="number" min="0" id="ed_agua_com_gas_${d.id}" value="${d.agua_com_gas ?? 0}" style="width:80px"></td>
        <td><input type="text" id="ed_obs_agua_com_gas_${d.id}" value="${_escAttr(d.obs_agua_com_gas || "")}" placeholder="Obs Água c/G"></td>

        <td><input type="number" min="0" id="ed_agua_sem_gas_${d.id}" value="${d.agua_sem_gas ?? 0}" style="width:80px"></td>
        <td><input type="text" id="ed_obs_agua_sem_gas_${d.id}" value="${_escAttr(d.obs_agua_sem_gas || "")}" placeholder="Obs Água s/G"></td>

        <td><input type="number" min="0" id="ed_cx_600_${d.id}" value="${d.cx_600 ?? 0}" style="width:80px"></td>
        <td><input type="text" id="ed_obs_cx_600_${d.id}" value="${_escAttr(d.obs_cx_600 || "")}" placeholder="Obs CX 600"></td>

        <td>${d.conferente_nome || "-"}</td>
        <td style="white-space:nowrap">
          <button onclick="salvarDevolucaoInline(${d.id})">💾</button>
          <button onclick="cancelarEdicaoDevolucao()">↩</button>
        </td>
      </tr>
    `;
    })
    .join("");
}

function editarDevolucaoInline(id) {
  devolucaoEditandoId = id;
  carregarDevolucoes();
}

function cancelarEdicaoDevolucao() {
  devolucaoEditandoId = null;
  carregarDevolucoes();
}

async function salvarDevolucaoInline(id) {
  const d = devolucoesCache.find((x) => x.id === id);
  if (!d) return;

  const payload = {
    frete_id: d.frete_id,
    veiculo_id: d.veiculo_id,
    conferente_id: d.conferente_id,
    colaborador_conferente_id: d.colaborador_conferente_id || d.conferente_id,

    c24: Number(document.getElementById(`ed_c24_${id}`).value || 0),
    c48: Number(document.getElementById(`ed_c48_${id}`).value || 0),
    pet2l: Number(document.getElementById(`ed_pet2l_${id}`).value || 0),
    pet600: Number(document.getElementById(`ed_pet600_${id}`).value || 0),
    pet200: Number(document.getElementById(`ed_pet200_${id}`).value || 0),

    obs_c24: (document.getElementById(`ed_obs_c24_${id}`).value || "").trim(),
    obs_c48: (document.getElementById(`ed_obs_c48_${id}`).value || "").trim(),
    obs_pet2l: (document.getElementById(`ed_obs_pet2l_${id}`).value || "").trim(),
    obs_pet600: (document.getElementById(`ed_obs_pet600_${id}`).value || "").trim(),
    obs_pet200: (document.getElementById(`ed_obs_pet200_${id}`).value || "").trim(),
    agua_com_gas: parseInt(document.getElementById(`ed_agua_com_gas_${id}`).value || 0),
    obs_agua_com_gas: document.getElementById(`ed_obs_agua_com_gas_${id}`).value,
    agua_sem_gas: parseInt(document.getElementById(`ed_agua_sem_gas_${id}`).value || 0),
    obs_agua_sem_gas: document.getElementById(`ed_obs_agua_sem_gas_${id}`).value,
    cx_600: parseInt(document.getElementById(`ed_cx_600_${id}`).value || 0),
    obs_cx_600: document.getElementById(`ed_obs_cx_600_${id}`).value,

  };

  const resp = await fetch(`/api/devolucoes/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!resp.ok) return alert("Erro ao salvar devolução.");

  devolucaoEditandoId = null;
  await carregarDevolucoes();
}

async function excluirDevolucao(id) {
  if (!confirm("Deseja excluir esta devolução?")) return;
  await apiFetch(`/api/devolucoes/${id}`, { method: "DELETE" });
  await carregarDevolucoes();
}



function _fmtMoney(v){
  const n = Number(v || 0);
  if (!Number.isFinite(n)) return "-";
  return n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function _fmtNumber(v, casas = 2){
  const n = Number(v);
  if (!Number.isFinite(n)) return "-";
  return n.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
}

function _fmtNumberNullable(v, casas = 2){
  if (v === null || v === undefined || v === "") return "-";
  return _fmtNumber(v, casas);
}

function _fmtKmNullable(v){
  if (v === null || v === undefined || v === "") return "-";
  const n = Number(v);
  if (!Number.isFinite(n)) return "-";
  return String(Math.trunc(n));
}

function _fmtDateBr(v){
  if (!v) return "-";
  const d = new Date(String(v).replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return _escHtml(String(v));
  return d.toLocaleString("pt-BR");
}

function _digitsOnly(v){
  return String(v ?? "").replace(/\D+/g, "");
}

function _normalizarCombustivelTipo(v){
  const tipo = String(v || "").trim().toLowerCase().replace(/\s+/g, " ");
  if (["arla", "arla32", "arla 32"].includes(tipo)) return "arla";
  if (["gasolina", "gasolina comum", "gasolina c", "gasolina c comum"].includes(tipo)) return "gasolina";
  if (["etanol", "etanol comum", "etanol hidratado", "etanol hidratado comum", "alcool", "álcool"].includes(tipo)) return "etanol";
  if (["diesel_500", "diesel_s500", "diesel 500", "diesel s500", "diesel s-500", "diesel500", "diesels500", "s500", "s-500"].includes(tipo)) {
    return "diesel_500";
  }
  return "diesel_s10";
}

function _combustivelLabel(v){
  return {
    diesel_s10: "Diesel S10",
    diesel_500: "Diesel 500",
    gasolina: "Gasolina",
    etanol: "Etanol",
    arla: "Arla",
  }[_normalizarCombustivelTipo(v)];
}

function _normalizarCombustivelPadraoVeiculo(v){
  const tipo = String(v || "").trim().toLowerCase().replace(/\s+/g, " ");
  if (["flex", "gasolina/etanol", "gasolina e etanol", "etanol/gasolina", "etanol e gasolina"].includes(tipo)) return "flex";
  if (["gasolina", "gasolina comum", "gasolina c", "gasolina c comum"].includes(tipo)) return "gasolina";
  if (["etanol", "etanol comum", "etanol hidratado", "etanol hidratado comum", "alcool", "álcool"].includes(tipo)) return "etanol";
  if (["diesel_s10", "diesel s10", "diesel s-10", "diesels10", "diesel10", "s10", "s-10", "diesel"].includes(tipo)) return "diesel_s10";
  if (["diesel_500", "diesel_s500", "diesel 500", "diesel s500", "diesel s-500", "diesel500", "diesels500", "s500", "s-500"].includes(tipo)) return "diesel_500";
  return "diesel_500";
}

function _combustivelOptionsVeiculoHtml(combustivelPadrao, selected = ""){
  const padrao = _normalizarCombustivelPadraoVeiculo(combustivelPadrao);
  let permitidos;
  if (padrao === "diesel_s10") {
    permitidos = [["diesel_s10", "Diesel S10"], ["arla", "Arla"]];
  } else if (padrao === "flex") {
    permitidos = [["gasolina", "Gasolina"], ["etanol", "Etanol"]];
  } else {
    permitidos = [[padrao, _combustivelLabel(padrao)]];
  }
  const solicitado = _normalizarCombustivelTipo(selected || padrao);
  const atual = permitidos.some(([value]) => value === solicitado)
    ? solicitado
    : permitidos[0][0];
  return permitidos.map(([value, label]) => (
    `<option value="${value}" ${atual === value ? "selected" : ""}>${label}</option>`
  )).join("");
}

function _combustivelPadraoCadastroVeiculo(veiculoId){
  const veiculo = _buscarVeiculoCadastro(veiculoId);
  return _normalizarCombustivelPadraoVeiculo(veiculo?.combustivel_padrao);
}

function _sincronizarCombustivelAbastecimentoComVeiculo(veiculoSelect, combustivelSelect, selected = ""){
  if (!veiculoSelect || !combustivelSelect) return;
  if (!veiculoSelect.value) {
    combustivelSelect.innerHTML = `<option value="">Selecione o veiculo</option>`;
    return;
  }
  const padrao = _combustivelPadraoCadastroVeiculo(veiculoSelect.value);
  combustivelSelect.innerHTML = _combustivelOptionsVeiculoHtml(padrao, selected || padrao);
}

function _normalizarDraftAbastecimento(draft = {}){
  const dados = draft && typeof draft === "object" ? draft : {};
  return {
    chave_acesso_nfe: _digitsOnly(dados.chave_acesso_nfe || dados.chave_acesso || ""),
    numero_nota: String(dados.numero_nota || "").trim(),
    emitente_nome: String(dados.emitente_nome || "").trim(),
    valor: dados.valor != null && dados.valor !== "" ? String(dados.valor) : "",
    quantidade_litros: dados.quantidade_litros != null && dados.quantidade_litros !== "" ? String(dados.quantidade_litros) : "",
    combustivel_tipo: _normalizarCombustivelTipo(dados.combustivel_tipo),
  };
}

function _salvarDraftAbastecimento(id, draft = {}){
  const key = String(id ?? "");
  if (!key) return;
  const atual = _normalizarDraftAbastecimento(abastecimentoDraftState.get(key) || {});
  abastecimentoDraftState.set(key, _normalizarDraftAbastecimento({ ...atual, ...draft }));
}

function _limparDraftAbastecimento(id){
  const key = String(id ?? "");
  if (!key) return;
  abastecimentoDraftState.delete(key);
}

function _draftAbastecimentoLinha(id, row = {}){
  const key = String(id ?? "");
  return _normalizarDraftAbastecimento({
    ...(row && typeof row === "object" ? row : {}),
    ...(abastecimentoDraftState.get(key) || {}),
  });
}

function _capturarDraftAbastecimentoDom(id){
  _salvarDraftAbastecimento(id, {
    chave_acesso_nfe: document.getElementById(`abast_chave_${id}`)?.value || "",
    numero_nota: document.getElementById(`abast_nota_${id}`)?.value || "",
    emitente_nome: document.getElementById(`abast_emitente_${id}`)?.value || "",
    valor: document.getElementById(`abast_valor_${id}`)?.value || "",
    quantidade_litros: document.getElementById(`abast_qtd_${id}`)?.value || "",
    combustivel_tipo: document.getElementById(`abast_combustivel_${id}`)?.value || "diesel_s10",
  });
}

function _formatBytesProgress(bytes){
  const value = Number(bytes || 0);
  if (!(value > 0)) return "0 KB";
  if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(value / 1024))} KB`;
}

function _renderAbastecimentoFeedback(id){
  const slot = document.getElementById(`abast_feedback_slot_${id}`);
  if (!slot) return;
  slot.innerHTML = _getAbastecimentoFeedbackHtml(id);
}

function _setAbastecimentoFeedback(id, message = "", tone = "info", extra = {}){
  const key = String(id ?? "");
  if (!key) return;
  const texto = String(message || "").trim();
  const detalhes = extra && typeof extra === "object" ? extra : {};
  if (!texto && !String(detalhes.title || "").trim()) {
    abastecimentoFeedbackState.delete(key);
    _renderAbastecimentoFeedback(id);
    return;
  }
  abastecimentoFeedbackState.set(key, {
    message: texto,
    tone: String(tone || "info"),
    title: String(detalhes.title || "").trim(),
    detail: String(detalhes.detail || "").trim(),
    progress: Number.isFinite(Number(detalhes.progress)) ? Math.max(0, Math.min(100, Math.round(Number(detalhes.progress)))) : null,
    indeterminate: !!detalhes.indeterminate,
  });
  _renderAbastecimentoFeedback(id);
}

function _getAbastecimentoFeedbackHtml(id){
  const state = abastecimentoFeedbackState.get(String(id ?? ""));
  if (!state?.message) return "";
  const title = String(state.title || "").trim();
  const detail = String(state.detail || "").trim();
  const hasProgress = state.progress != null || state.indeterminate;
  return `<div class="abastecimento-feedback${hasProgress ? " abastecimento-feedback--progress" : ""}" data-tone="${_escAttr(state.tone || "info")}">
    ${title ? `<div class="abastecimento-feedback-title">${_escHtml(title)}</div>` : ""}
    <div class="abastecimento-feedback-message">${_escHtml(state.message || "")}</div>
    ${detail ? `<div class="abastecimento-feedback-detail">${_escHtml(detail)}</div>` : ""}
    ${hasProgress ? `
      <div class="abastecimento-feedback-progress" aria-hidden="true">
        <span class="abastecimento-feedback-progress-fill${state.indeterminate ? " is-indeterminate" : ""}" style="${state.indeterminate ? "" : `width:${_escAttr(String(state.progress || 0))}%`}"></span>
      </div>
    ` : ""}
  </div>`;
}

function _resumoNfeAbastecimentoFeedback(nfe){
  const info = nfe && typeof nfe === "object" ? nfe : {};
  const partes = [];
  if (info.numero_nota) partes.push(`nota ${info.numero_nota}`);
  if (info.emitente_nome) partes.push(`emitente ${info.emitente_nome}`);
  if (info.valor != null && info.valor !== "") partes.push(`V.Total R$ ${_fmtMoney(info.valor)}`);
  if (info.quantidade_litros != null && info.quantidade_litros !== "") {
    partes.push(`Quantidade ${_fmtNumber(info.quantidade_litros, 3)}`);
  }
  return partes.length ? `DF-e localizou ${partes.join(" | ")}.` : "DF-e localizou a NF-e.";
}

async function liberarAbastecimento(){
  const veiculo_id = Number((document.getElementById("abast_veiculo")?.value || "").trim());
  const km = Number((document.getElementById("abast_km")?.value || "").trim() || 0);
  const posto = (document.getElementById("abast_posto")?.value || "").trim();
  const combustivel_tipo = (document.getElementById("abast_combustivel")?.value || "").trim();

  if (!veiculo_id) return alert("Selecione o veiculo.");
  if (!(km > 0)) return alert("Informe uma quilometragem válida.");
  if (!posto) return alert("Informe o posto.");

  const resp = await apiFetch("/api/abastecimentos/liberar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ veiculo_id, km, posto, combustivel_tipo }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao liberar abastecimento.");

  if (document.getElementById("abast_km")) {
    document.getElementById("abast_km").value = "";
    document.getElementById("abast_km").dataset.autoFromVehicle = "1";
  }
  if (document.getElementById("abast_posto")) document.getElementById("abast_posto").value = "";
  _sincronizarCombustivelAbastecimentoComVeiculo(
    document.getElementById("abast_veiculo"),
    document.getElementById("abast_combustivel"),
  );

  await Promise.all([carregarFrotaResumo(), carregarAbastecimentos()]);
  if (window.__dashView === "frota") await renderDashboardFrota();
  if (data?.pdf_url) {
    window.open(data.pdf_url, "_blank");
  }
}

async function carregarResumoAbastecimentosXml(){
  const status = document.getElementById("abastXmlSyncStatus");
  if (!status) return;
  const resp = await apiFetch("/api/abastecimentos/importacoes-xml");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    status.textContent = data?.erro || "Falha ao carregar o resumo das NF-e de abastecimento.";
    return;
  }
  const meta = data?.meta || {};
  const pendente = (data?.rows || []).find((item) => item.status === "pendente");
  status.textContent = [
    `${Number(meta.total || 0)} NF-e processada(s)`,
    `${Number(meta.vinculados || 0)} vinculada(s) a lancamentos existentes`,
    `${Number(meta.criados || 0)} requisicao(oes) criada(s) automaticamente`,
    `${Number(meta.pendentes || 0)} pendente(s)`,
    `${Number(meta.manutencoes_pendentes || 0)} pre-manutencao(oes) para conferencia`,
    pendente ? `Primeira pendencia: nota ${pendente.numero_nota || pendente.chave_nfe || "-"} - ${pendente.motivo || "revisao necessaria"}` : "",
  ].filter(Boolean).join(" | ");
}

async function sincronizarAbastecimentosXml(){
  const status = document.getElementById("abastXmlSyncStatus");
  if (status) status.textContent = "Sincronizando NF-e dos postos...";
  const resp = await apiFetch("/api/abastecimentos/importacoes-xml/sincronizar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (status) status.textContent = data?.erro || "Falha ao sincronizar as NF-e dos postos.";
    alert(data?.erro || "Falha ao sincronizar as NF-e dos postos.");
    return;
  }
  const resumo = data?.resumo || {};
  if (status) {
    status.textContent = `${Number(resumo.requisicoes_concluidas || 0)} requisicao(oes) concluida(s), ${Number(resumo.manuais_vinculados || 0)} lancamento(s) manual(is) vinculado(s), ${Number(resumo.criados || 0)} criado(s), ${Number(resumo.manutencoes_pre_lancadas || 0)} enviado(s) para conferencia de manutencao e ${Number(resumo.pendentes || 0)} pendente(s).`;
  }
  await Promise.all([
    carregarFrotaResumo(),
    carregarAbastecimentos(),
    carregarResumoAbastecimentosXml(),
    carregarPreLancamentosManutencaoXml(),
  ]);
  if (window.__dashView === "frota") await renderDashboardFrota();
}

async function concluirAbastecimento(id){
  const valor = Number((document.getElementById(`abast_valor_${id}`)?.value || "").trim() || 0);
  const quantidade_litros = Number((document.getElementById(`abast_qtd_${id}`)?.value || "").trim() || 0);
  const combustivel_tipo = (document.getElementById(`abast_combustivel_${id}`)?.value || "diesel_s10").trim() || "diesel_s10";
  const chave_acesso_nfe = normalizarChaveNfeCampo(document.getElementById(`abast_chave_${id}`), false);
  const numero_nota = (document.getElementById(`abast_nota_${id}`)?.value || "").trim();
  const emitente_nome = (document.getElementById(`abast_emitente_${id}`)?.value || "").trim();

  if (!(valor > 0)) return alert("Informe um valor válido.");
  if (!(quantidade_litros > 0)) return alert("Informe uma quantidade válida.");
  if (chave_acesso_nfe && chave_acesso_nfe.length !== 44) {
    return alert("A chave de acesso da NF-e precisa ter 44 digitos.");
  }

  const resp = await apiFetch(`/api/abastecimentos/${id}/abastecer`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ valor, quantidade_litros, combustivel_tipo, chave_acesso_nfe, numero_nota, emitente_nome }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao concluir abastecimento.");

  _limparDraftAbastecimento(id);
  await Promise.all([carregarFrotaResumo(), carregarAbastecimentos()]);
  if (window.__dashView === "frota") await renderDashboardFrota();
}

async function importarNfeAbastecimento(id){
  const fileInput = document.getElementById(`abast_xml_${id}`);
  const file = fileInput?.files?.[0];
  const chave_acesso_esperada = _digitsOnly(document.getElementById(`abast_chave_${id}`)?.value || "");
  const combustivel_tipo = (document.getElementById(`abast_combustivel_${id}`)?.value || "diesel_s10").trim() || "diesel_s10";

  if (!file) return alert("Selecione o XML da NF-e para importar.");
  if (chave_acesso_esperada && chave_acesso_esperada.length !== 44) {
    return alert("A chave de acesso da NF-e precisa ter 44 digitos.");
  }

  const formData = new FormData();
  formData.append("xml", file);
  formData.append("combustivel_tipo", combustivel_tipo);
  if (chave_acesso_esperada) formData.append("chave_acesso_esperada", chave_acesso_esperada);

  const resp = await apiFetch(`/api/abastecimentos/${id}/importar_nfe`, {
    method: "POST",
    body: formData,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao importar XML da NF-e.");

  if (fileInput) fileInput.value = "";
  _limparDraftAbastecimento(id);
  _setAbastecimentoFeedback(id, `XML importado com sucesso. Nota ${data?.numero_nota || data?.chave_acesso_nfe || "-"}.`, "success");
  await Promise.all([carregarFrotaResumo(), carregarAbastecimentos()]);
  if (window.__dashView === "frota") await renderDashboardFrota();
  alert(`NF-e importada com sucesso para ${_combustivelLabel(data?.combustivel_tipo)}. Nota: ${data?.numero_nota || data?.chave_acesso_nfe || "-"}.`);
}

async function _consultarDfeAbastecimento(id, chave_acesso_esperada, combustivel_tipo) {
  _capturarDraftAbastecimentoDom(id);
  _setAbastecimentoFeedback(id, "Consultando DF-e...", "info");
  await carregarAbastecimentos();

  const resp = await apiFetch(`/api/abastecimentos/${id}/importar_nfe_dfe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chave_acesso_esperada, combustivel_tipo }),
  });
  const data = await resp.json().catch(() => ({}));
  _aplicarResumoNfeAbastecimento(id, data?.nfe || data);
  if (!resp.ok) {
    const resumo = _resumoNfeAbastecimentoFeedback(data?.nfe || data);
    _setAbastecimentoFeedback(
      id,
      resumo && data?.nfe ? `${resumo} ${data?.erro || ""}`.trim() : (data?.erro || "Erro ao consultar DF-e do abastecimento."),
      resp.status === 409 ? "warning" : "error"
    );
    await carregarAbastecimentos();
    alert((data?.erro || "Erro ao consultar DF-e do abastecimento.") + _resumoLimiteConsultasDfe(data?.limite_consultas));
    return false;
  }

  _setAbastecimentoFeedback(id, `${_resumoNfeAbastecimentoFeedback(data)} Importacao concluida com sucesso.`, "success");
  await Promise.all([carregarFrotaResumo(), carregarAbastecimentos()]);
  if (window.__dashView === "frota") await renderDashboardFrota();
  alert(`NF-e obtida via DF-e e importada com sucesso para ${_combustivelLabel(data?.combustivel_tipo)}. Nota: ${data?.numero_nota || data?.chave_acesso_nfe || "-"}.${_resumoLimiteConsultasDfe(data?.limite_consultas)}`);
  return true;
}

async function buscarNfeAbastecimento(id, opts = {}) {
  const chave_acesso_esperada = _digitsOnly(opts?.chave || document.getElementById(`abast_chave_${id}`)?.value || "");
  const combustivel_tipo = (document.getElementById(`abast_combustivel_${id}`)?.value || "diesel_s10").trim() || "diesel_s10";
  if (chave_acesso_esperada.length === 44) {
    return _consultarDfeAbastecimento(id, chave_acesso_esperada, combustivel_tipo);
  }

  estoqueState.cameraAfterScanAction = { type: "buscar_dfe_abastecimento", id: Number(id || 0) };
  _setAbastecimentoFeedback(id, "Buscando chave NF-e pela camera ou foto...", "info");
  await abrirCameraEstoque(`abast_chave_${id}`);
  return false;
}

function buscarScrapingAbastecimento(id){
  _capturarDraftAbastecimentoDom(id);
  _setAbastecimentoFeedback(id, "Abrindo captura para scraping do codigo/QR...", "info");
  selecionarImagemNfeOcr({ tipo: "abastecimento_barcode", id: Number(id || 0) });
}

async function excluirAbastecimento(id){
  if (!confirm("Excluir este lancamento de abastecimento?")) return;

  const resp = await apiFetch(`/api/abastecimentos/${id}`, { method: "DELETE" });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao excluir abastecimento.");

  _limparDraftAbastecimento(id);
  await Promise.all([carregarFrotaResumo(), carregarAbastecimentos()]);
  if (window.__dashView === "frota") await renderDashboardFrota();
}

function _datetimeLocalAbastecimento(value){
  const raw = String(value || "").trim().replace(" ", "T");
  return raw ? raw.slice(0, 16) : "";
}

async function abrirEdicaoAbastecimento(id){
  const item = abastecimentosCache.find((row) => Number(row.id) === Number(id));
  if (!item) return alert("Lancamento de abastecimento nao encontrado.");

  await ensureCadastrosCache();
  const modal = document.getElementById("abastecimentoEditModal");
  const veiculoSelect = document.getElementById("abastEditVeiculo");
  if (!modal || !veiculoSelect) return;

  veiculoSelect.innerHTML = optionsFrom(
    cacheCadastros.veiculos || [],
    item.veiculo_id,
    {
      emptyLabel: "Selecione...",
      selectedFallbackItem: {
        id: item.veiculo_id,
        nome: item.veiculo_nome || item.placa || `Veiculo ${item.veiculo_id}`,
      },
    }
  );
  const combustivelSelect = document.getElementById("abastEditCombustivel");
  _sincronizarCombustivelAbastecimentoComVeiculo(
    veiculoSelect,
    combustivelSelect,
    item.combustivel_tipo,
  );
  if (veiculoSelect.dataset.combustivelBound !== "1") {
    veiculoSelect.dataset.combustivelBound = "1";
    veiculoSelect.addEventListener("change", () => {
      _sincronizarCombustivelAbastecimentoComVeiculo(veiculoSelect, combustivelSelect);
    });
  }
  document.getElementById("abastEditId").value = String(item.id || "");
  document.getElementById("abastEditData").value = _datetimeLocalAbastecimento(item.data_abastecimento || item.data_liberacao);
  document.getElementById("abastEditKm").value = String(item.km || "");
  document.getElementById("abastEditPosto").value = item.posto || "";
  document.getElementById("abastEditChave").value = item.chave_acesso_nfe || "";
  document.getElementById("abastEditNota").value = item.numero_nota || "";
  document.getElementById("abastEditEmitente").value = item.emitente_nome || "";
  document.getElementById("abastEditQuantidade").value = item.quantidade_litros ?? "";
  document.getElementById("abastEditValor").value = item.valor ?? "";
  _abrirPopupBloqueante(modal);
}

function fecharEdicaoAbastecimento(){
  _fecharPopupBloqueante(document.getElementById("abastecimentoEditModal"));
}

async function salvarEdicaoAbastecimento(){
  const id = Number(document.getElementById("abastEditId")?.value || 0);
  const payload = {
    veiculo_id: Number(document.getElementById("abastEditVeiculo")?.value || 0),
    data_abastecimento: document.getElementById("abastEditData")?.value || "",
    km: Number(document.getElementById("abastEditKm")?.value || 0),
    posto: (document.getElementById("abastEditPosto")?.value || "").trim(),
    combustivel_tipo: document.getElementById("abastEditCombustivel")?.value || "diesel_s10",
    chave_acesso_nfe: _digitsOnly(document.getElementById("abastEditChave")?.value || ""),
    numero_nota: (document.getElementById("abastEditNota")?.value || "").trim(),
    emitente_nome: (document.getElementById("abastEditEmitente")?.value || "").trim(),
    quantidade_litros: Number(document.getElementById("abastEditQuantidade")?.value || 0),
    valor: Number(document.getElementById("abastEditValor")?.value || 0),
  };

  if (!id) return alert("Lancamento invalido.");
  if (!payload.veiculo_id) return alert("Selecione o veiculo.");
  if (!payload.data_abastecimento) return alert("Informe a data do abastecimento.");
  if (!(payload.km > 0)) return alert("Informe uma quilometragem valida.");
  if (!payload.posto) return alert("Informe o posto.");
  if (!(payload.quantidade_litros > 0)) return alert("Informe uma quantidade valida.");
  if (!(payload.valor > 0)) return alert("Informe um valor valido.");
  if (payload.chave_acesso_nfe && payload.chave_acesso_nfe.length !== 44) {
    return alert("A chave de acesso da NF-e precisa ter 44 digitos.");
  }

  const resp = await apiFetch(`/api/abastecimentos/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao editar abastecimento.");

  fecharEdicaoAbastecimento();
  cacheCadastros.veiculos = null;
  await Promise.all([carregarFrotaResumo(), carregarAbastecimentos()]);
  if (window.__dashView === "frota") await renderDashboardFrota();
}

async function carregarAbastecimentos(){
  const pendBody = document.getElementById("abastPendentesBody");
  const histBody = document.getElementById("abastHistoricoBody");
  if (!pendBody && !histBody) return;

  const resp = await apiFetch("/api/abastecimentos");
  if (!resp.ok) {
    if (pendBody) pendBody.innerHTML = `<tr><td colspan="10">Erro ao carregar abastecimentos.</td></tr>`;
    if (histBody) histBody.innerHTML = `<tr><td colspan="14">Erro ao carregar historico.</td></tr>`;
    return;
  }
  const dados = await resp.json();
  abastecimentosCache = Array.isArray(dados) ? dados : [];
  const pendentes = (dados || []).filter((x) => (x.status || "").toLowerCase() === "liberado");
  const historico = (dados || []).filter((x) => (x.status || "").toLowerCase() === "abastecido");

  if (pendBody) {
    pendBody.innerHTML = pendentes.length ? pendentes.map((r) => {
      const v = `${r.placa || ""} ${r.modelo || r.veiculo_nome || ""}`.trim();
      const draft = _draftAbastecimentoLinha(r.id, r);
      const combustivel = draft.combustivel_tipo || r.combustivel_padrao;
      return `
        <tr>
          <td>${_escHtml(v || ("Veiculo " + r.veiculo_id))}</td>
          <td>${_escHtml(String(r.km || 0))}</td>
          <td>${_escHtml(r.posto || "-")}</td>
          <td>
            <select id="abast_combustivel_${r.id}">
              ${_combustivelOptionsVeiculoHtml(r.combustivel_padrao, combustivel)}
            </select>
          </td>
          <td>
            <div class="abastecimento-inline">
              <input id="abast_chave_${r.id}" class="barcode-input" type="text" maxlength="44" value="${_escAttr(draft.chave_acesso_nfe || "")}" placeholder="Bipe a chave" oninput="normalizarChaveNfeCampo(this,false)" onkeydown="if(event.key==='Enter'){event.preventDefault(); normalizarChaveNfeCampo(this,true);}">
            </div>
          </td>
          <td><input id="abast_xml_${r.id}" type="file" accept=".xml,text/xml,application/xml"></td>
          <td>
            <div class="abastecimento-manual-grid">
              <input id="abast_nota_${r.id}" type="text" value="${_escAttr(draft.numero_nota || "")}" placeholder="Numero da nota">
              <input id="abast_emitente_${r.id}" type="text" value="${_escAttr(draft.emitente_nome || "")}" placeholder="Emitente">
            </div>
          </td>
          <td><input id="abast_valor_${r.id}" type="number" step="0.01" min="0" placeholder="0,00" value="${_escAttr(draft.valor)}"></td>
          <td><input id="abast_qtd_${r.id}" type="number" step="0.001" min="0" placeholder="${_escAttr(combustivel === "arla" ? "Qtd" : "Litros")}" value="${_escAttr(draft.quantidade_litros)}"></td>
          <td class="abastecimento-actions-cell">
            <div class="abastecimento-actions">
              <button type="button" onclick="concluirAbastecimento(${r.id})">Marcar abastecido</button>
              <button type="button" onclick="importarNfeAbastecimento(${r.id})">Importar XML</button>
              <button type="button" onclick="buscarNfeAbastecimento(${r.id})">Buscar DF-e</button>
              <button type="button" onclick="buscarScrapingAbastecimento(${r.id})">Busca.s</button>
              <button type="button" onclick="selecionarImagemNfeOcr({ tipo: 'abastecimento', id: ${r.id} })">Foto OCR</button>
              <button type="button" onclick="window.open('/api/abastecimentos/${r.id}/pdf','_blank')">PDF</button>
              <button type="button" onclick="excluirAbastecimento(${r.id})">Excluir</button>
            </div>
            <div id="abast_feedback_slot_${r.id}">${_getAbastecimentoFeedbackHtml(r.id)}</div>
          </td>
        </tr>
      `;
    }).join("") : `<tr><td colspan="10">Sem requisicoes liberadas.</td></tr>`;
  }

  if (histBody) {
    histBody.innerHTML = historico.length ? historico.map((r) => {
      const v = `${r.placa || ""} ${r.modelo || r.veiculo_nome || ""}`.trim();
      const postoEmitente = [r.posto || "", r.emitente_nome || ""]
        .filter((value, idx, arr) => value && arr.indexOf(value) === idx)
        .join(" / ") || "-";
      const nota = r.numero_nota || r.chave_acesso_nfe || "-";
      const valorLitro = (r.valor_litro !== null && r.valor_litro !== undefined)
        ? `R$ ${_fmtMoney(r.valor_litro)}`
        : "-";
      const valorTotal = (r.valor !== null && r.valor !== undefined)
        ? `R$ ${_fmtMoney(r.valor)}`
        : "-";
      return `
        <tr>
          <td>${_escHtml(_fmtDateBr(r.data_abastecimento || r.data_liberacao))}</td>
          <td>${_escHtml(v || ("Veiculo " + r.veiculo_id))}</td>
          <td>${_escHtml(_combustivelLabel(r.combustivel_tipo))}</td>
          <td>${_escHtml(_fmtKmNullable(r.km_inicial))}</td>
          <td>${_escHtml(_fmtKmNullable(r.km_final ?? r.km_atual ?? r.km))}</td>
          <td>${_escHtml(_fmtKmNullable(r.km_rodado))}</td>
          <td>${_escHtml(postoEmitente)}</td>
          <td>${_escHtml(nota)}</td>
          <td>${_escHtml(_fmtNumber(r.quantidade_litros, 3))}</td>
          <td>${_escHtml(valorLitro)}</td>
          <td>${_escHtml(valorTotal)}</td>
          <td>${_escHtml(_fmtNumberNullable(r.km_l, 2))}</td>
          <td>${_escHtml(r.status || "-")}</td>
          <td class="abastecimento-actions">
            <button type="button" onclick="abrirEdicaoAbastecimento(${r.id})">Editar</button>
            <button type="button" onclick="window.open('/api/abastecimentos/${r.id}/pdf','_blank')">PDF</button>
            <button type="button" onclick="excluirAbastecimento(${r.id})">Excluir</button>
          </td>
        </tr>
      `;
    }).join("") : `<tr><td colspan="14">Sem abastecimentos concluidos.</td></tr>`;
  }
  carregarResumoAbastecimentosXml().catch(() => {});
}

function _normalizarPreviewOcrManutencao(preview = {}){
  const itens = Array.isArray(preview?.itens) ? preview.itens : [];
  const warnings = Array.isArray(preview?.warnings) ? preview.warnings.filter(Boolean) : [];
  const valorTotal = preview?.valor_total != null && preview?.valor_total !== "" ? Number(preview.valor_total) : null;
  return {
    arquivo_origem: String(preview?.arquivo_origem || ""),
    emitente_nome: String(preview?.emitente_nome || ""),
    emitente_cnpj: String(preview?.emitente_cnpj || ""),
    numero_nota: String(preview?.numero_nota || ""),
    serie: String(preview?.serie || ""),
    data_documento: String(preview?.data_documento || preview?.data_emissao || ""),
    valor_total: Number.isFinite(valorTotal) ? valorTotal : null,
    valor_total_label: String(preview?.valor_total_label || ""),
    texto_bruto: String(preview?.texto_bruto || ""),
    itens,
    warnings,
  };
}

function _resumoItensPreManutencaoXml(itens = []){
  const normalizados = _normalizarItensManutencao(itens);
  if (!normalizados.length) return "-";
  return normalizados
    .slice(0, 3)
    .map((item) => item.nome_produto || item.codigo_produto_nfe || "Item")
    .join(", ") + (normalizados.length > 3 ? ` +${normalizados.length - 3}` : "");
}

function _renderPreLancamentosManutencaoXml(){
  const body = document.getElementById("manutXmlPendenciasBody");
  const resumo = document.getElementById("manutXmlPendenciasResumo");
  if (!body || !resumo) return;
  resumo.textContent = `${manutencaoXmlPendencias.length} nota(s) aguardando conferencia.`;
  body.innerHTML = manutencaoXmlPendencias.length
    ? manutencaoXmlPendencias.map((row) => {
        const veiculo = [
          row.veiculo_nome || "",
          row.veiculo_placa || "",
          row.veiculo_modelo || "",
        ].filter(Boolean).join(" / ");
        const confianca = Number(row.sugestao_confianca || 0);
        const sugestao = veiculo
          ? `${veiculo}${confianca > 0 && confianca < 1 ? ` (${Math.round(confianca * 100)}%)` : ""}`
          : "Selecionar na conferencia";
        return `
          <tr class="${Number(row.id) === Number(manutencaoXmlPreLancamentoId) ? "is-selected" : ""}">
            <td>${_escHtml(row.numero_nota || row.chave_nfe || "-")}</td>
            <td>${_escHtml(row.placa_xml || "-")}</td>
            <td>${_escHtml(sugestao)}</td>
            <td>${_escHtml(_resumoItensPreManutencaoXml(row.itens || []))}</td>
            <td>${_escHtml(row.motivo || "Revisao necessaria")}</td>
            <td class="abastecimento-actions">
              <button type="button" onclick="conferirPreLancamentoManutencaoXml(${Number(row.id)})">Conferir</button>
              <button type="button" class="btn-secondary" onclick="descartarPreLancamentoManutencaoXml(${Number(row.id)})">Descartar</button>
            </td>
          </tr>
        `;
      }).join("")
    : `<tr><td colspan="6">Nenhum pre-lancamento de manutencao pendente.</td></tr>`;
}

async function carregarPreLancamentosManutencaoXml(){
  const body = document.getElementById("manutXmlPendenciasBody");
  const resumo = document.getElementById("manutXmlPendenciasResumo");
  if (!body || !resumo) return;
  const resp = await apiFetch("/api/manutencoes/importacoes-xml?status=pendente");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    resumo.textContent = data?.erro || "Falha ao carregar pre-lancamentos.";
    body.innerHTML = `<tr><td colspan="6">Falha ao carregar pendencias.</td></tr>`;
    return;
  }
  manutencaoXmlPendencias = Array.isArray(data?.rows) ? data.rows : [];
  if (
    manutencaoXmlPreLancamentoId
    && !manutencaoXmlPendencias.some(
      (row) => Number(row.id) === Number(manutencaoXmlPreLancamentoId)
    )
  ) {
    manutencaoXmlPreLancamentoId = 0;
  }
  _renderPreLancamentosManutencaoXml();
}

function conferirPreLancamentoManutencaoXml(id){
  const row = manutencaoXmlPendencias.find(
    (item) => Number(item.id) === Number(id)
  );
  if (!row) return;
  manutencaoXmlPreLancamentoId = Number(row.id || 0);
  _aplicarPreviewOcrManutencao({
    arquivo_origem: `Importar XML #${row.xml_id || row.id}`,
    emitente_nome: row.emitente_nome || "",
    numero_nota: row.numero_nota || "",
    data_documento: row.data_documento || "",
    valor_total: Number(row.valor || 0),
    itens: row.itens || [],
    warnings: [row.motivo || "Confira o veiculo e os itens antes de salvar."],
  });
  const campoVeiculo = document.getElementById("manut_veiculo");
  const campoKm = document.getElementById("manut_km");
  const campoTipo = document.getElementById("manut_tipo");
  if (campoVeiculo) campoVeiculo.value = row.veiculo_id ? String(row.veiculo_id) : "";
  if (campoKm) campoKm.value = Number(row.km || 0) > 0 ? String(row.km) : "";
  if (campoTipo) campoTipo.value = _resumirItensManutencao(row.itens || []);
  _renderPreLancamentosManutencaoXml();
  document.getElementById("manut_veiculo")?.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function descartarPreLancamentoManutencaoXml(id){
  if (!confirm("Descartar este pre-lancamento sem criar uma manutencao?")) return;
  const resp = await apiFetch(`/api/manutencoes/importacoes-xml/${Number(id)}/descartar`, {
    method: "POST",
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Falha ao descartar pre-lancamento.");
  if (Number(manutencaoXmlPreLancamentoId) === Number(id)) {
    limparPreviewOcrManutencao();
  }
  await carregarPreLancamentosManutencaoXml();
}

function _normalizarItemManutencao(item = {}, index = 0){
  const quantidade = Number(item?.quantidade);
  const valorUnitario = Number(item?.valor_unitario);
  const valorTotalBruto = Number(item?.valor_total);
  const valorTotal = Number.isFinite(valorTotalBruto)
    ? valorTotalBruto
    : (Number.isFinite(quantidade) && Number.isFinite(valorUnitario) ? quantidade * valorUnitario : 0);
  return {
    item_seq: String(item?.item_seq || index + 1),
    codigo_produto_nfe: String(item?.codigo_produto_nfe || item?.codigo || ""),
    codigo_barras: String(item?.codigo_barras || ""),
    nome_produto: String(item?.nome_produto || item?.descricao || ""),
    unidade: String(item?.unidade || ""),
    quantidade: Number.isFinite(quantidade) ? quantidade : 0,
    valor_unitario: Number.isFinite(valorUnitario) ? valorUnitario : 0,
    valor_total: Number.isFinite(valorTotal) ? valorTotal : 0,
    observacao: String(item?.observacao || item?.obs || ""),
    _manual: Boolean(item?._manual),
  };
}

function _normalizarItensManutencao(lista = [], preserveBlank = false){
  if (!Array.isArray(lista)) return [];
  return lista
    .map((item, index) => _normalizarItemManutencao(item, index))
    .filter((item) => {
      if (item._manual && preserveBlank) return true;
      return item.nome_produto || item.codigo_produto_nfe || item.codigo_barras || item.quantidade > 0 || item.valor_total > 0 || item.observacao;
    });
}

function _resumirItensManutencao(lista = []){
  const nomes = [];
  _normalizarItensManutencao(lista).forEach((item) => {
    const nome = String(item?.nome_produto || "").trim();
    if (nome && !nomes.includes(nome)) nomes.push(nome);
  });
  if (!nomes.length) return "";
  if (nomes.length === 1) return nomes[0];
  const base = nomes.slice(0, 3).join(", ");
  return `${nomes.length} itens: ${base}${nomes.length > 3 ? "..." : ""}`;
}

function _renderItensManutencaoEditor(){
  const vazio = document.getElementById("manutItensVazio");
  const wrap = document.getElementById("manutItensEditorWrap");
  const body = document.getElementById("manutItensEditorBody");
  if (!vazio || !wrap || !body) return;

  manutencaoItensDraft = _normalizarItensManutencao(manutencaoItensDraft, true);
  if (!manutencaoItensDraft.length) {
    vazio.classList.remove("hidden");
    wrap.classList.add("hidden");
    body.innerHTML = "";
    return;
  }

  vazio.classList.add("hidden");
  wrap.classList.remove("hidden");
  body.innerHTML = manutencaoItensDraft.map((item, index) => `
    <tr>
      <td>${_escHtml(String(index + 1))}</td>
      <td><input class="manut-item-desc" value="${_escAttr(item.nome_produto || "")}" placeholder="Descricao" oninput="atualizarItemManutencaoCampo(${index}, 'nome_produto', this.value)"></td>
      <td><input value="${_escAttr(item.codigo_produto_nfe || item.codigo_barras || "")}" placeholder="Codigo" oninput="atualizarItemManutencaoCampo(${index}, 'codigo_produto_nfe', this.value)"></td>
      <td><input type="number" step="0.001" value="${_escAttr(String(item.quantidade || 0))}" oninput="atualizarItemManutencaoCampo(${index}, 'quantidade', this.value)"></td>
      <td><input type="number" step="0.01" value="${_escAttr(String(item.valor_unitario || 0))}" oninput="atualizarItemManutencaoCampo(${index}, 'valor_unitario', this.value)"></td>
      <td><input type="number" step="0.01" value="${_escAttr(String(item.valor_total || 0))}" oninput="atualizarItemManutencaoCampo(${index}, 'valor_total', this.value)"></td>
      <td><input class="manut-item-obs" value="${_escAttr(item.observacao || "")}" placeholder="Observacao" oninput="atualizarItemManutencaoCampo(${index}, 'observacao', this.value)"></td>
      <td><button type="button" class="btn-secondary manutencao-item-remove" onclick="removerItemManutencao(${index})">Remover</button></td>
    </tr>
  `).join("");
}

function adicionarItemManutencao(item = {}){
  manutencaoItensDraft = _normalizarItensManutencao([
    ...manutencaoItensDraft,
    _normalizarItemManutencao({ ...item, _manual: true }, manutencaoItensDraft.length),
  ], true);
  _renderItensManutencaoEditor();
}

function removerItemManutencao(index){
  manutencaoItensDraft = manutencaoItensDraft.filter((_, itemIndex) => itemIndex !== Number(index));
  _renderItensManutencaoEditor();
}

function atualizarItemManutencaoCampo(index, campo, valor){
  const pos = Number(index);
  if (!(pos >= 0) || !manutencaoItensDraft[pos]) return;
  const atual = { ...manutencaoItensDraft[pos] };
  if (campo === "quantidade" || campo === "valor_unitario" || campo === "valor_total") {
    const numero = Number(valor);
    atual[campo] = Number.isFinite(numero) ? numero : 0;
    if ((campo === "quantidade" || campo === "valor_unitario") && !(Number(atual.valor_total) > 0)) {
      atual.valor_total = Number(atual.quantidade || 0) * Number(atual.valor_unitario || 0);
    }
  } else {
    atual[campo] = String(valor || "");
  }
  manutencaoItensDraft[pos] = _normalizarItemManutencao(atual, pos);
}

function _renderItensManutencaoHistorico(lista = []){
  const itens = _normalizarItensManutencao(lista);
  if (!itens.length) return "0";
  const linhas = itens.map((item) => {
    const partes = [
      item.nome_produto || item.codigo_produto_nfe || item.codigo_barras || "Item sem descricao",
      item.quantidade > 0 ? `Qtd ${_fmtNumber(item.quantidade, 3)}` : "",
      item.valor_total > 0 ? `Total R$ ${_fmtMoney(item.valor_total)}` : "",
      item.observacao || "",
    ].filter(Boolean);
    return `<div>${_escHtml(partes.join(" | "))}</div>`;
  }).join("");
  return `<details class="manutencao-itens-details"><summary>${_escHtml(String(itens.length))} item(ns)</summary><div class="manutencao-itens-list">${linhas}</div></details>`;
}

function _renderPreviewOcrManutencao(){
  const card = document.getElementById("manutOcrPreview");
  const resumo = document.getElementById("manutOcrResumo");
  const itensWrap = document.getElementById("manutOcrItensWrap");
  const itensBody = document.getElementById("manutOcrItensBody");
  const warningsEl = document.getElementById("manutOcrWarnings");
  const status = document.getElementById("manutOcrStatus");
  const draft = manutencaoOcrDraft;

  if (!card || !resumo || !itensWrap || !itensBody || !warningsEl) return;
  if (!draft) {
    card.classList.add("hidden");
    document.querySelectorAll(".estoque-import-add-btn").forEach((button) => button.classList.remove("hidden"));
    itensWrap.classList.add("hidden");
    warningsEl.classList.add("hidden");
    warningsEl.textContent = "";
    itensBody.innerHTML = "";
    resumo.textContent = "";
    if (status) {
      status.textContent = "Use a camera do celular para fotografar a nota impressa. O sistema tenta extrair fornecedor, numero, valor e itens para conferencia antes do lancamento.";
    }
    _renderItensManutencaoEditor();
    return;
  }

  const resumoPartes = [
    `Arquivo: ${draft.arquivo_origem || "-"}`,
    `Fornecedor: ${draft.emitente_nome || "-"}`,
    `Nota: ${draft.numero_nota || "-"}`,
    `Data: ${draft.data_documento ? _fmtDateBr(draft.data_documento) : "-"}`,
    `Valor: ${draft.valor_total != null ? `R$ ${_fmtMoney(draft.valor_total)}` : (draft.valor_total_label || "-")}`,
  ];
  resumo.textContent = resumoPartes.join(" | ");
  card.classList.remove("hidden");

  if (Array.isArray(draft.itens) && draft.itens.length) {
    itensBody.innerHTML = draft.itens.map((item, index) => `
      <tr>
        <td>${_escHtml(String(item?.item_seq || index + 1))}</td>
        <td>${_escHtml(item?.codigo_produto_nfe || item?.codigo_barras || "-")}</td>
        <td>${_escHtml(item?.nome_produto || "-")}</td>
        <td>${_escHtml(_fmtNumber(item?.quantidade, 3))}</td>
        <td>${_escHtml(item?.valor_unitario != null ? `R$ ${_fmtMoney(item.valor_unitario)}` : "-")}</td>
      </tr>
    `).join("");
    itensWrap.classList.remove("hidden");
  } else {
    itensBody.innerHTML = "";
    itensWrap.classList.add("hidden");
  }

  if (draft.warnings.length) {
    warningsEl.textContent = draft.warnings.join(" ");
    warningsEl.classList.remove("hidden");
  } else {
    warningsEl.textContent = "";
    warningsEl.classList.add("hidden");
  }

  if (status) {
    status.textContent = draft.itens.length
      ? `OCR concluido. Revise os ${draft.itens.length} item(ns) antes de salvar a manutencao.`
      : "OCR concluido. Revise os dados lidos antes de salvar a manutencao.";
  }
}

function _aplicarPreviewOcrManutencao(preview = {}){
  manutencaoOcrDraft = _normalizarPreviewOcrManutencao(preview);
  manutencaoItensDraft = _normalizarItensManutencao(manutencaoOcrDraft.itens || []);
  const campoValor = document.getElementById("manut_valor");
  const campoNota = document.getElementById("manut_nota");
  const campoEmitente = document.getElementById("manut_emitente");
  const campoData = document.getElementById("manut_data_documento");
  const campoTipo = document.getElementById("manut_tipo");
  if (campoValor && manutencaoOcrDraft.valor_total != null) campoValor.value = String(manutencaoOcrDraft.valor_total);
  if (campoNota && manutencaoOcrDraft.numero_nota) campoNota.value = manutencaoOcrDraft.numero_nota;
  if (campoEmitente && manutencaoOcrDraft.emitente_nome) campoEmitente.value = manutencaoOcrDraft.emitente_nome;
  if (campoData && manutencaoOcrDraft.data_documento) campoData.value = manutencaoOcrDraft.data_documento;
  if (campoTipo && !campoTipo.value.trim()) campoTipo.value = _resumirItensManutencao(manutencaoItensDraft);
  _renderItensManutencaoEditor();
  _renderPreviewOcrManutencao();
}

function limparPreviewOcrManutencao(){
  manutencaoOcrDraft = null;
  manutencaoItensDraft = [];
  manutencaoXmlPreLancamentoId = 0;
  const campoNota = document.getElementById("manut_nota");
  const campoEmitente = document.getElementById("manut_emitente");
  const campoData = document.getElementById("manut_data_documento");
  if (campoNota) campoNota.value = "";
  if (campoEmitente) campoEmitente.value = "";
  if (campoData) campoData.value = "";
  _renderPreviewOcrManutencao();
  _renderPreLancamentosManutencaoXml();
}

async function addManutencao(){
  const veiculo_id = Number((document.getElementById("manut_veiculo")?.value || "").trim());
  const tipo = (document.getElementById("manut_tipo")?.value || "").trim();
  const km = Number((document.getElementById("manut_km")?.value || "").trim() || 0);
  const valor = Number((document.getElementById("manut_valor")?.value || "").trim() || 0);
  const numero_nota = (document.getElementById("manut_nota")?.value || "").trim();
  const emitente_nome = (document.getElementById("manut_emitente")?.value || "").trim();
  const data_documento = (document.getElementById("manut_data_documento")?.value || "").trim();

  if (!veiculo_id) return alert("Selecione o veiculo.");
  const payload = {
    veiculo_id,
    tipo,
    km,
    valor,
    numero_nota,
    emitente_nome,
    data_documento,
    itens_json: _normalizarItensManutencao(manutencaoItensDraft),
    pre_lancamento_id: manutencaoXmlPreLancamentoId || 0,
  };
  if (!payload.tipo.trim()) payload.tipo = _resumirItensManutencao(payload.itens_json);
  if (manutencaoOcrDraft) {
    payload.ocr_preview = {
      ...manutencaoOcrDraft,
      numero_nota: numero_nota || manutencaoOcrDraft.numero_nota,
      emitente_nome: emitente_nome || manutencaoOcrDraft.emitente_nome,
      data_documento: data_documento || manutencaoOcrDraft.data_documento,
    };
  }

  const resp = await apiFetch("/api/manutencoes", {
    method:"POST",
    headers:{ "Content-Type":"application/json" },
    body: JSON.stringify(payload)
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao registrar manutencao.");

  // limpa
  if (document.getElementById("manut_tipo")) document.getElementById("manut_tipo").value="";
  if (document.getElementById("manut_km")) document.getElementById("manut_km").value="";
  if (document.getElementById("manut_valor")) document.getElementById("manut_valor").value="";
  limparPreviewOcrManutencao();

  await carregarManutencoesFrota();
  await carregarPreLancamentosManutencaoXml();
  await carregarFrotaResumo();
  if (window.__dashView === "frota") await renderDashboardFrota();
}

async function addTrocaOleo(){
  const veiculo_id = Number((document.getElementById("oleo_veiculo")?.value || "").trim());
  const km = Number((document.getElementById("oleo_km")?.value || "").trim() || 0);
  const tipo = (document.getElementById("oleo_tipo")?.value || "").trim();

  if (!veiculo_id) return alert("Selecione o veiculo.");
  await fetch("/api/trocas_oleo", {
    method:"POST",
    headers:{ "Content-Type":"application/json" },
    body: JSON.stringify({ veiculo_id, km, tipo })
  });

  if (document.getElementById("oleo_km")) document.getElementById("oleo_km").value="";
  if (document.getElementById("oleo_tipo")) document.getElementById("oleo_tipo").value="";

  await carregarFrotaResumo();
  if (window.__dashView === "frota") await renderDashboardFrota();
}

async function addTrocaPneu(){
  const veiculo_id = Number((document.getElementById("pneu_veiculo")?.value || "").trim());
  const data_troca = (document.getElementById("pneu_data_troca")?.value || "").trim();
  const km = Number((document.getElementById("pneu_km")?.value || "").trim() || 0);
  const marca = (document.getElementById("pneu_marca")?.value || "").trim();
  const valor_total = Number((document.getElementById("pneu_valor")?.value || "").trim() || 0);
  const quantidade = Number((document.getElementById("pneu_qtd")?.value || "").trim() || 0);
  const localizacao_posicao = (document.getElementById("pneu_posicao")?.value || "").trim();
  const localizacao_lado = (document.getElementById("pneu_lado")?.value || "").trim();
  const localizacao = [localizacao_posicao, localizacao_lado].filter(Boolean).join(" ");
  const observacao_rodizio = (document.getElementById("pneu_obs_rodizio")?.value || "").trim();

  if (!veiculo_id) return alert("Selecione o veiculo.");
  if (!(km > 0)) return alert("Informe um KM valido.");
  if (!marca) return alert("Informe a marca do pneu.");
  if (!(quantidade > 0)) return alert("Informe uma quantidade de pneus valida.");

  const resp = await fetch("/api/trocas_pneu", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      veiculo_id,
      data_troca,
      km,
      marca,
      valor_total,
      quantidade,
      localizacao,
      localizacao_posicao,
      localizacao_lado,
      observacao_rodizio,
    }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao registrar troca de pneu.");

  if (document.getElementById("pneu_data_troca")) document.getElementById("pneu_data_troca").value = "";
  if (document.getElementById("pneu_km")) document.getElementById("pneu_km").value = "";
  if (document.getElementById("pneu_marca")) document.getElementById("pneu_marca").value = "";
  if (document.getElementById("pneu_valor")) document.getElementById("pneu_valor").value = "";
  if (document.getElementById("pneu_qtd")) document.getElementById("pneu_qtd").value = "";
  if (document.getElementById("pneu_posicao")) document.getElementById("pneu_posicao").value = "";
  if (document.getElementById("pneu_lado")) document.getElementById("pneu_lado").value = "";
  if (document.getElementById("pneu_obs_rodizio")) document.getElementById("pneu_obs_rodizio").value = "";

  await carregarFrotaResumo();
  if (window.__dashView === "frota") await renderDashboardFrota();
}

async function carregarTrocasPneu(){
  const histBody = document.getElementById("pneuHistoricoBody");
  if (!histBody) return;

  const resp = await apiFetch("/api/trocas_pneu");
  if (!resp.ok) {
    histBody.innerHTML = `<tr><td colspan="9">Erro ao carregar historico de pneus.</td></tr>`;
    return;
  }
  const dados = await resp.json();
  histBody.innerHTML = (dados || []).length ? (dados || []).map((r) => {
    const veiculo = `${r.placa || ""} ${r.modelo || r.veiculo_nome || ""}`.trim();
    const obs = (r.observacao_rodizio || "").trim();
    const localBase = (r.localizacao || "").trim();
    const localizacaoTxt = obs ? `${localBase || "-"} (${obs})` : (localBase || "-");
    return `
      <tr>
        <td>${_escHtml(_fmtDateBr(r.data_troca || r.data_registro))}</td>
        <td>${_escHtml(veiculo || ("Veiculo " + r.veiculo_id))}</td>
        <td>${_escHtml(String(r.km || 0))}</td>
        <td>${_escHtml(r.marca || "-")}</td>
        <td>${_escHtml(String(r.quantidade || 0))}</td>
        <td>R$ ${_escHtml(_fmtMoney(r.valor_total))}</td>
        <td>${_escHtml(_fmtNumber(r.km_por_pneu, 1))}</td>
        <td>R$ ${_escHtml(_fmtMoney(r.custo_por_pneu))}</td>
        <td>${_escHtml(localizacaoTxt)}</td>
      </tr>
    `;
  }).join("") : `<tr><td colspan="9">Sem trocas de pneu registradas.</td></tr>`;
}

function _comissaoNum(id, defaultValue = 0){
  const raw = (document.getElementById(id)?.value || "").trim().replace(",", ".");
  if (raw === "") return defaultValue;
  const n = Number(raw);
  return Number.isFinite(n) ? n : defaultValue;
}

function _comissaoText(id){
  return (document.getElementById(id)?.value || "").trim();
}

async function _apiComissaoCadastros(funcao = ""){
  const q = funcao ? `?funcao=${encodeURIComponent(funcao)}` : "";
  const resp = await apiFetch(`/api/comissao/cadastros${q}`);
  if (!resp.ok) throw new Error("falha cadastro comissao");
  return await resp.json();
}

async function salvarComissaoLancamento(){
  const payload = {
    cod_vendedor: _comissaoNum("com_cod_vendedor", 0),
    motorista: _comissaoText("com_motorista"),
    entregador: _comissaoText("com_entregador"),
    rota: _comissaoText("com_rota"),
    usina: _comissaoText("com_usina"),
    data_faturamento: _comissaoText("com_data_faturamento"),
    data_saida: _comissaoText("com_data_saida"),
    data_chegada: _comissaoText("com_data_chegada"),

    v_gf: _comissaoNum("com_v_gf", 0),
    d_gf: _comissaoNum("com_d_gf", 0),
    icms_gf: _comissaoNum("com_icms_gf", 0),
    v_pet: _comissaoNum("com_v_pet", 0),
    d_pet: _comissaoNum("com_d_pet", 0),
    icms_pet: _comissaoNum("com_icms_pet", 0),
    v_agua: _comissaoNum("com_v_agua", 0),
    d_agua: _comissaoNum("com_d_agua", 0),

    gf_600: _comissaoNum("com_gf_600", 0),
    gf_200: _comissaoNum("com_gf_200", 0),
    gf_300: _comissaoNum("com_gf_300", 0),
    dev_gf: _comissaoNum("com_dev_gf", 0),
    pet_2l: _comissaoNum("com_pet_2l", 0),
    pet_600: _comissaoNum("com_pet_600", 0),
    dev_pet: _comissaoNum("com_dev_pet", 0),
    agua_vol: _comissaoNum("com_agua_vol", 0),
    total_pedidos: _comissaoNum("com_total_pedidos", 0),
    acucar_qtd: _comissaoNum("com_acucar_qtd", 0),
    t_acucar: _comissaoNum("com_t_acucar", 0),

    pct_vend_gf: _comissaoNum("com_pct_vend_gf", 0.01),
    pct_vend_pet: _comissaoNum("com_pct_vend_pet", 0.01),
    pct_vend_agua: _comissaoNum("com_pct_vend_agua", 0.03),
    pct_ent_gf: _comissaoNum("com_pct_ent_gf", 0.08),
    pct_ent_pet: _comissaoNum("com_pct_ent_pet", 0.06),
    pct_ent_agua: _comissaoNum("com_pct_ent_agua", 0.06),
    taxa_ent_acucar: _comissaoNum("com_taxa_ent_acucar", 0),
  };

  if (!payload.motorista) return alert("Informe o motorista.");
  if (!payload.entregador) return alert("Informe o entregador.");
  if (!payload.rota) return alert("Informe a rota.");

  const resp = await apiFetch("/api/comissao/lancamentos", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao salvar lancamento.");

  [
    "com_cod_vendedor", "com_motorista", "com_entregador", "com_rota", "com_usina",
    "com_data_faturamento", "com_data_saida", "com_data_chegada",
    "com_v_gf", "com_d_gf", "com_icms_gf", "com_v_pet", "com_d_pet", "com_icms_pet", "com_v_agua", "com_d_agua",
    "com_gf_600", "com_gf_200", "com_gf_300", "com_dev_gf", "com_pet_2l", "com_pet_600", "com_dev_pet",
    "com_agua_vol", "com_total_pedidos", "com_acucar_qtd", "com_t_acucar"
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });

  await carregarComissaoLancamentos();
}

async function excluirComissaoLancamento(id){
  if (!confirm("Excluir este lancamento de comissao?")) return;
  const resp = await apiFetch(`/api/comissao/lancamentos/${id}`, { method: "DELETE" });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao excluir lancamento.");
  await carregarComissaoLancamentos();
}

async function carregarComissaoLancamentos(){
  const body = document.getElementById("comissaoLancamentosBody");
  if (!body) return;

  const resp = await apiFetch("/api/comissao/lancamentos");
  if (!resp.ok) {
    body.innerHTML = `<tr><td colspan="10">Erro ao carregar lancamentos.</td></tr>`;
    return;
  }
  const dados = await resp.json();
  if (!Array.isArray(dados) || dados.length === 0) {
    body.innerHTML = `<tr><td colspan="10">Sem lancamentos de comissao.</td></tr>`;
    return;
  }

  body.innerHTML = dados.map((r) => {
    const vend = Number(r.base_vendedor_total || 0);
    const entBase = Number(r.base_ent_gf || 0) + Number(r.base_ent_pet || 0) + Number(r.base_ent_agua || 0);
    return `
      <tr>
        <td>${_escHtml(String(r.id || 0))}</td>
        <td>${_escHtml(String(r.cod_vendedor || 0))}</td>
        <td>${_escHtml(r.motorista || "-")}</td>
        <td>${_escHtml(r.entregador || "-")}</td>
        <td>${_escHtml(r.rota || "-")}</td>
        <td>R$ ${_escHtml(_fmtMoney(vend))}</td>
        <td>R$ ${_escHtml(_fmtMoney(r.comissao_vendedor || 0))}</td>
        <td>${_escHtml(_fmtNumber(entBase, 2))}</td>
        <td>R$ ${_escHtml(_fmtMoney(r.comissao_entregador || 0))}</td>
        <td><button type="button" onclick="excluirComissaoLancamento(${Number(r.id || 0)})">Excluir</button></td>
      </tr>
    `;
  }).join("");
}

async function salvarComissaoCadastro(){
  const payload = {
    codigo: _comissaoNum("comcad_codigo", 0),
    nome: _comissaoText("comcad_nome"),
    funcao: _comissaoText("comcad_funcao").toLowerCase(),
    pct_gf: _comissaoNum("comcad_pct_gf", 0),
    pct_pet: _comissaoNum("comcad_pct_pet", 0),
    pct_agua: _comissaoNum("comcad_pct_agua", 0),
  };
  if (!payload.nome) return alert("Informe o nome do cadastro.");
  if (!payload.funcao) return alert("Informe a funcao.");

  const resp = await apiFetch("/api/comissao/cadastros", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao salvar cadastro.");
  ["comcad_codigo", "comcad_nome", "comcad_pct_gf", "comcad_pct_pet", "comcad_pct_agua"].forEach((id)=>{
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  await carregarComissaoCadastros();
}

async function salvarComissaoCadastroRapido(funcao, nomeId, codigoId = "", pctGfId = "", pctPetId = "", pctAguaId = ""){
  const nome = _comissaoText(nomeId);
  const codigo = codigoId ? _comissaoNum(codigoId, 0) : 0;
  const pct_gf = pctGfId ? _comissaoNum(pctGfId, 0) : 0;
  const pct_pet = pctPetId ? _comissaoNum(pctPetId, 0) : 0;
  const pct_agua = pctAguaId ? _comissaoNum(pctAguaId, 0) : 0;

  if (!nome) return alert("Informe o nome.");

  const resp = await apiFetch("/api/comissao/cadastros", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ codigo, nome, funcao, pct_gf, pct_pet, pct_agua }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao salvar cadastro.");

  [nomeId, codigoId, pctGfId, pctPetId, pctAguaId].filter(Boolean).forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });

  await carregarComissaoCadastros();
}

async function excluirComissaoCadastro(id){
  if (!confirm("Excluir este cadastro de comissao?")) return;
  const resp = await apiFetch(`/api/comissao/cadastros/${id}`, { method: "DELETE" });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao excluir cadastro.");
  await carregarComissaoCadastros();
}

async function salvarComissaoCidade(){
  const rota = _comissaoText("comcidade_rota");
  if (!rota) return alert("Informe a rota.");
  const resp = await apiFetch("/api/comissao/cidades", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rota }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao salvar rota.");
  const el = document.getElementById("comcidade_rota");
  if (el) el.value = "";
  await carregarComissaoCadastros();
}

async function excluirComissaoCidade(id){
  if (!confirm("Excluir esta rota?")) return;
  const resp = await apiFetch(`/api/comissao/cidades/${id}`, { method: "DELETE" });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao excluir rota.");
  await carregarComissaoCadastros();
}

function _renderComissaoCadRows(bodyId, rows, isSimple = false){
  const body = document.getElementById(bodyId);
  if (!body) return;
  if (!rows?.length){
    body.innerHTML = `<tr><td colspan="${isSimple ? 4 : 6}">Sem registros.</td></tr>`;
    return;
  }
  body.innerHTML = rows.map((r)=> isSimple ? `
    <tr>
      <td>${_escHtml(String(r.codigo || 0))}</td>
      <td>${_escHtml(r.nome || "-")}</td>
      <td>${_escHtml(_fmtNumber(r.pct_gf || 0, 4))}</td>
      <td><button type="button" onclick="excluirComissaoCadastro(${Number(r.id || 0)})">Excluir</button></td>
    </tr>
  ` : `
    <tr>
      <td>${_escHtml(String(r.codigo || 0))}</td>
      <td>${_escHtml(r.nome || "-")}</td>
      <td>${_escHtml(_fmtNumber(r.pct_gf || 0, 4))}</td>
      <td>${_escHtml(_fmtNumber(r.pct_pet || 0, 4))}</td>
      <td>${_escHtml(_fmtNumber(r.pct_agua || 0, 4))}</td>
      <td><button type="button" onclick="excluirComissaoCadastro(${Number(r.id || 0)})">Excluir</button></td>
    </tr>
  `).join("");
}

async function carregarComissaoCadastros(){
  const [vendedores, entregadores, acucar, usinas, cidades] = await Promise.all([
    _apiComissaoCadastros("vendedor"),
    _apiComissaoCadastros("entregador"),
    _apiComissaoCadastros("acucar"),
    _apiComissaoCadastros("usina"),
    (async ()=> {
      const r = await apiFetch("/api/comissao/cidades");
      if (!r.ok) throw new Error("falha cidades");
      return await r.json();
    })()
  ]);

  _renderComissaoCadRows("comissaoCadVendedoresBody", vendedores, false);
  _renderComissaoCadRows("comissaoCadEntregadoresBody", entregadores, false);
  _renderComissaoCadRows("comissaoCadAcucarBody", acucar, true);
  _renderComissaoCadRows("comissaoCadUsinasBody", usinas, true);

  const cityBody = document.getElementById("comissaoCidadesBody");
  if (cityBody){
    if (!cidades?.length) {
      cityBody.innerHTML = `<tr><td colspan="2">Sem rotas cadastradas.</td></tr>`;
    } else {
      cityBody.innerHTML = cidades.map((c)=>`
        <tr>
          <td>${_escHtml(c.rota || "-")}</td>
          <td><button type="button" onclick="excluirComissaoCidade(${Number(c.id || 0)})">Excluir</button></td>
        </tr>
      `).join("");
    }
  }

  const selVend = document.getElementById("comrel_vendedor");
  if (selVend){
    selVend.innerHTML = `<option value="">Todos vendedores</option>` + vendedores.map((v)=>
      `<option value="${Number(v.codigo || 0)}">${_escHtml(`${v.codigo || 0} - ${v.nome || ""}`)}</option>`
    ).join("");
  }
  const selEnt = document.getElementById("comrel_entregador");
  if (selEnt){
    selEnt.innerHTML = `<option value="">Todos entregadores</option>` + entregadores.map((e)=>
      `<option value="${_escHtml(e.nome || "")}">${_escHtml(e.nome || "")}</option>`
    ).join("");
  }
}

async function carregarRelatoriosComissao(){
  const prevVend = _comissaoText("comrel_vendedor");
  const prevEnt = _comissaoText("comrel_entregador");
  try { await carregarComissaoCadastros(); } catch {}
  const selVendEl = document.getElementById("comrel_vendedor");
  const selEntEl = document.getElementById("comrel_entregador");
  if (selVendEl && prevVend && Array.from(selVendEl.options).some((o)=>o.value === prevVend)) selVendEl.value = prevVend;
  if (selEntEl && prevEnt && Array.from(selEntEl.options).some((o)=>o.value === prevEnt)) selEntEl.value = prevEnt;

  const codVend = _comissaoText("comrel_vendedor");
  const entreg = _comissaoText("comrel_entregador");
  atualizarBotaoImprimirComissao();
  const params = new URLSearchParams();
  if (codVend) params.set("cod_vendedor", codVend);
  if (entreg) params.set("entregador", entreg);

  const resp = await apiFetch(`/api/comissao/relatorios?${params.toString()}`);
  if (!resp.ok) {
    alert("Erro ao carregar relatorios de comissao.");
    return;
  }
  const data = await resp.json();

  const resumo = document.getElementById("comrelResumoGeral");
  if (resumo){
    const g = data?.resumo_geral || {};
    resumo.innerHTML = `
      Lancamentos: <b>${_escHtml(String(g.total_lancamentos || 0))}</b><br>
      Base vendedor: <b>R$ ${_escHtml(_fmtMoney(g.base_vendedor_total || 0))}</b><br>
      Comissao vendedor: <b>R$ ${_escHtml(_fmtMoney(g.comissao_vendedor_total || 0))}</b><br>
      Comissao entregador: <b>R$ ${_escHtml(_fmtMoney(g.comissao_entregador_total || 0))}</b>
    `;
  }

  const vendBody = document.getElementById("comrelTotalVendedoresBody");
  if (vendBody){
    const rows = data?.total_vendedores || [];
    vendBody.innerHTML = rows.length ? rows.map((r)=>`
      <tr>
        <td>${_escHtml(String(r.codigo || 0))}</td>
        <td>${_escHtml(r.nome || "-")}</td>
        <td>R$ ${_escHtml(_fmtMoney(r.base_total || 0))}</td>
        <td>R$ ${_escHtml(_fmtMoney(r.comissao_total || 0))}</td>
      </tr>
    `).join("") : `<tr><td colspan="4">Sem dados.</td></tr>`;
  }

  const entBody = document.getElementById("comrelTotalEntregadoresBody");
  if (entBody){
    const rows = data?.total_entregadores || [];
    entBody.innerHTML = rows.length ? rows.map((r)=>`
      <tr>
        <td>${_escHtml(r.nome || "-")}</td>
        <td>${_escHtml(_fmtNumber(r.volume_total || 0, 2))}</td>
        <td>R$ ${_escHtml(_fmtMoney(r.comissao_total || 0))}</td>
      </tr>
    `).join("") : `<tr><td colspan="3">Sem dados.</td></tr>`;
  }

  const refBody = document.getElementById("comrelRefugoBody");
  if (refBody){
    const rows = data?.total_refugo || [];
    refBody.innerHTML = rows.length ? rows.map((r)=>`
      <tr>
        <td>${_escHtml(r.entregador || "-")}</td>
        <td>${_escHtml(_fmtNumber(r.dev_gf || 0, 2))}</td>
        <td>${_escHtml(_fmtNumber(r.dev_pet || 0, 2))}</td>
      </tr>
    `).join("") : `<tr><td colspan="3">Sem dados.</td></tr>`;
  }

  const acuBody = document.getElementById("comrelAcucarBody");
  if (acuBody){
    const rows = data?.total_acucar || [];
    acuBody.innerHTML = rows.length ? rows.map((r)=>`
      <tr>
        <td>${_escHtml(r.usina || "-")}</td>
        <td>${_escHtml(_fmtNumber(r.qtd || 0, 2))}</td>
        <td>R$ ${_escHtml(_fmtMoney(r.comissao || 0))}</td>
      </tr>
    `).join("") : `<tr><td colspan="3">Sem dados.</td></tr>`;
  }
}

function atualizarBotaoImprimirComissao(){
  const btn = document.getElementById("comrelPrintBtn");
  if (!btn) return;
  const codVend = _comissaoText("comrel_vendedor");
  const entreg = _comissaoText("comrel_entregador");
  const mostrar = !!codVend || !!entreg;
  btn.classList.toggle("hidden", !mostrar);
}

function imprimirRelatorioComissaoPdf(){
  const codVend = _comissaoText("comrel_vendedor");
  const entreg = _comissaoText("comrel_entregador");
  const params = new URLSearchParams();
  if (codVend) params.set("cod_vendedor", codVend);
  if (entreg) params.set("entregador", entreg);
  const url = `/api/comissao/relatorios/pdf?${params.toString()}`;
  window.open(url, "_blank");
}

//////////////////////////////////////////////////////
// BACKUPS
//////////////////////////////////////////////////////
async function baixarBackup(url, nomePadrao, extensao) {
  const resp = await fetch(url);

  if (!resp.ok) {
    let j = null;
    try { j = await resp.json(); } catch {}
    alert("Erro no backup:\n" + (j?.detalhes || j?.erro || `HTTP ${resp.status}`));
    return;
  }

  const blob = await resp.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = `${nomePadrao}_${new Date().toISOString().slice(0, 19).replaceAll(":", "-")}.${extensao}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}

async function gerarBackup() {
  await baixarBackup("/api/backup", "backup", "sql");
}

async function gerarBackupCompleto() {
  await baixarBackup("/api/backup/full", "backup_full", "tar.gz");
}

//////////////////////////////////////////////////////
// INICIALIZAR APLICAÇÃO
//////////////////////////////////////////////////////
function _veiculoFrotaLabel(v){
  return `${v.placa || ""} ${v.modelo || v.nome || ""}`.trim() || (`Veiculo ${v.id || "-"}`);
}

async function carregarManutencoesFrota(){
  const body = document.getElementById("manutHistoricoBody");
  if (!body) return;

  const resp = await apiFetch("/api/manutencoes");
  if (!resp.ok) {
    body.innerHTML = `<tr><td colspan="7">Erro ao carregar manutencoes.</td></tr>`;
    return;
  }

  const dados = await resp.json();
  _renderPreviewOcrManutencao();
  body.innerHTML = (dados || []).length ? (dados || []).map((r) => `
    <tr>
      <td>${_escHtml(_fmtDateBr(r.data_registro))}</td>
      <td>${_escHtml(_veiculoFrotaLabel(r))}</td>
      <td>${_escHtml(r.tipo || "-")}</td>
      <td>${_escHtml(String(r.km || 0))}</td>
      <td>R$ ${_escHtml(_fmtMoney(r.valor))}</td>
      <td>${_escHtml([r.numero_nota || "", r.emitente_nome || ""].filter(Boolean).join(" - ") || "-")}</td>
      <td>${_renderItensManutencaoHistorico(r.itens || [])}</td>
    </tr>
  `).join("") : `<tr><td colspan="7">Sem manutencoes registradas.</td></tr>`;
}

async function carregarTrocasOleoFrota(){
  const body = document.getElementById("oleoHistoricoBody");
  if (!body) return;

  const resp = await apiFetch("/api/trocas_oleo");
  if (!resp.ok) {
    body.innerHTML = `<tr><td colspan="4">Erro ao carregar trocas de oleo.</td></tr>`;
    return;
  }

  const dados = await resp.json();
  body.innerHTML = (dados || []).length ? (dados || []).map((r) => `
    <tr>
      <td>${_escHtml(_fmtDateBr(r.data_registro))}</td>
      <td>${_escHtml(_veiculoFrotaLabel(r))}</td>
      <td>${_escHtml(r.tipo || "-")}</td>
      <td>${_escHtml(String(r.km || 0))}</td>
    </tr>
  `).join("") : `<tr><td colspan="4">Sem trocas de oleo registradas.</td></tr>`;
}

async function addLavagem(){
  const veiculo_id = Number((document.getElementById("lav_veiculo")?.value || "").trim());
  const data_lavagem = (document.getElementById("lav_data")?.value || "").trim();
  const km = Number((document.getElementById("lav_km")?.value || "").trim() || 0);
  const local = (document.getElementById("lav_local")?.value || "").trim();
  const valor = Number((document.getElementById("lav_valor")?.value || "").trim() || 0);
  const observacao = (document.getElementById("lav_obs")?.value || "").trim();

  if (!veiculo_id) return alert("Selecione o veiculo.");

  const resp = await fetch("/api/lavagens", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ veiculo_id, data_lavagem, km, local, valor, observacao })
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao registrar lavagem.");

  if (document.getElementById("lav_data")) document.getElementById("lav_data").value = "";
  if (document.getElementById("lav_km")) document.getElementById("lav_km").value = "";
  if (document.getElementById("lav_local")) document.getElementById("lav_local").value = "";
  if (document.getElementById("lav_valor")) document.getElementById("lav_valor").value = "";
  if (document.getElementById("lav_obs")) document.getElementById("lav_obs").value = "";

  await carregarFrotaResumo();
  if (window.__dashView === "frota") await renderDashboardFrota();
}

async function carregarLavagens(){
  const body = document.getElementById("lavHistoricoBody");
  if (!body) return;

  const resp = await apiFetch("/api/lavagens");
  if (!resp.ok) {
    body.innerHTML = `<tr><td colspan="6">Erro ao carregar lavagens.</td></tr>`;
    return;
  }

  const dados = await resp.json();
  body.innerHTML = (dados || []).length ? (dados || []).map((r) => `
    <tr>
      <td>${_escHtml(_fmtDateBr(r.data_lavagem || r.data_registro))}</td>
      <td>${_escHtml(_veiculoFrotaLabel(r))}</td>
      <td>${_escHtml(String(r.km || 0))}</td>
      <td>${_escHtml(r.local || "-")}</td>
      <td>R$ ${_escHtml(_fmtMoney(r.valor))}</td>
      <td>${_escHtml(r.observacao || "-")}</td>
    </tr>
  `).join("") : `<tr><td colspan="6">Sem lavagens registradas.</td></tr>`;
}

async function carregarFrotaResumo(){
  const [veiculosResp, resumoResp] = await Promise.allSettled([
    fetch("/api/veiculos"),
    fetch("/api/frota_resumo"),
  ]);

  let veiculos = [];
  if (veiculosResp.status === "fulfilled") {
    try { veiculos = await veiculosResp.value.json(); } catch {}
  }
  cacheCadastros.veiculos = _ordenarListaNatural(Array.isArray(veiculos) ? veiculos : []);

  const selManut = document.getElementById("manut_veiculo");
  const selOleo = document.getElementById("oleo_veiculo");
  const selPneu = document.getElementById("pneu_veiculo");
  const selAbast = document.getElementById("abast_veiculo");
  const selLav = document.getElementById("lav_veiculo");
  const opt = (v)=>`<option value="${v.id}">${_escHtml(v.nome || (v.placa||'') || ('Veiculo '+v.id))}</option>`;
  if (selManut) selManut.innerHTML = `<option value="">Selecione...</option>` + veiculos.map(opt).join("");
  if (selOleo) selOleo.innerHTML = `<option value="">Selecione...</option>` + veiculos.map(opt).join("");
  if (selPneu) selPneu.innerHTML = `<option value="">Selecione...</option>` + veiculos.map(opt).join("");
  if (selAbast) selAbast.innerHTML = `<option value="">Selecione...</option>` + veiculos.map(opt).join("");
  if (selLav) selLav.innerHTML = `<option value="">Selecione...</option>` + veiculos.map(opt).join("");
  _bindNovoAbastecimentoKmAtual();

  const tbody = document.getElementById("tabelaFrota");
  if (tbody) {
    if (resumoResp.status !== "fulfilled") {
      tbody.innerHTML = `<tr><td colspan="7">Erro ao carregar frota.</td></tr>`;
    } else {
      const resumo = await resumoResp.value.json();
      tbody.innerHTML = (resumo || []).map((v)=> {
        const ultimoOleo = (v.ultimo_oleo_km ?? "-");
        const manutCount = (v.manut_count ?? 0);
        const custo = Number(v.custo_total ?? 0).toFixed(2);
        return `
          <tr>
            <td>${_escHtml(v.placa || "-")}</td>
            <td>${_escHtml(v.modelo || v.nome || "-")}</td>
            <td>${_escHtml((v.km_atual ?? 0).toString())}</td>
            <td>${_escHtml(ultimoOleo.toString())}</td>
            <td>${_escHtml(manutCount.toString())}</td>
            <td>R$ ${_escHtml(custo)}</td>
            <td><button type="button" onclick="abrirHistoricoFrota(${Number(v.id || 0)})">Abrir</button></td>
          </tr>
        `;
      }).join("");
    }
  }

  await Promise.all([
    carregarAbastecimentos(),
    carregarTrocasPneu(),
    carregarManutencoesFrota(),
    carregarTrocasOleoFrota(),
    carregarLavagens()
  ]);
}

async function abrirHistoricoFrota(veiculoId) {
  const modal = document.getElementById("frotaHistoricoModal");
  const body = document.getElementById("frotaHistoricoBody");
  if (!modal || !body) return;
  if (!(Number(veiculoId) > 0)) return;

  body.innerHTML = "Carregando historico...";
  _abrirPopupBloqueante(modal);

  const r = await apiFetch(`/api/frota_historico/${veiculoId}`);
  if (!r.ok) {
    body.innerHTML = "Erro ao carregar historico do caminhao.";
    return;
  }

  const j = await r.json();
  const v = j.veiculo || {};
  const resumo = j.resumo || {};
  const frete = j.frete_atual || {};
  const hist = j.historico || {};
  const manutencoes = hist.manutencoes || [];
  const trocasOleo = hist.trocas_oleo || [];
  const trocasPneu = hist.trocas_pneu || [];
  const abastecimentos = hist.abastecimentos || [];
  const lavagens = hist.lavagens || [];

  const titulo = `${v.nome || v.modelo || "-"} ${v.placa || ""}`.trim();
  const mediaKm = (resumo.media_km !== null && resumo.media_km !== undefined && Number.isFinite(Number(resumo.media_km)))
    ? Number(resumo.media_km).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "-";

  const manutRows = manutencoes.map((m) => `
    <tr>
      <td>${_escHtml(_fmtDateBr(m.data_manutencao))}</td>
      <td>${_escHtml(m.tipo || "-")}</td>
      <td>${_escHtml(String(m.km || 0))}</td>
      <td>R$ ${_escHtml(_fmtMoney(m.valor))}</td>
      <td>${_renderItensManutencaoHistorico(m.itens || [])}</td>
    </tr>
  `);

  const oleoRows = trocasOleo.map((o) => `
    <tr>
      <td>${_escHtml(_fmtDateBr(o.data_troca || o.data_registro))}</td>
      <td>${_escHtml(o.tipo || "-")}</td>
      <td>${_escHtml(String(o.km || 0))}</td>
    </tr>
  `);

  const pneuRows = trocasPneu.map((p) => `
    <tr>
      <td>${_escHtml(_fmtDateBr(p.data_troca || p.data_registro))}</td>
      <td>${_escHtml(p.marca || "-")}</td>
      <td>${_escHtml(String(p.km || 0))}</td>
      <td>${_escHtml(String(p.quantidade || 0))}</td>
      <td>R$ ${_escHtml(_fmtMoney(p.valor_total))}</td>
      <td>R$ ${_escHtml(_fmtMoney(p.custo_por_pneu))}</td>
      <td>${_escHtml(p.localizacao || "-")}</td>
    </tr>
  `);

  const abastRows = abastecimentos.map((a) => {
    const postoEmitente = [a.posto || "", a.emitente_nome || ""]
      .filter((value, idx, arr) => value && arr.indexOf(value) === idx)
      .join(" / ") || "-";
    const nota = a.numero_nota || a.chave_acesso_nfe || "-";
    const valorLitro = (a.valor_litro !== null && a.valor_litro !== undefined)
      ? `R$ ${_fmtMoney(a.valor_litro)}`
      : "-";
    const valorTotal = (a.valor !== null && a.valor !== undefined)
      ? `R$ ${_fmtMoney(a.valor)}`
      : "-";
    return `
      <tr>
        <td>${_escHtml(_fmtDateBr(a.data_abastecimento || a.data_liberacao))}</td>
        <td>${_escHtml(a.status || "-")}</td>
        <td>${_escHtml(_combustivelLabel(a.combustivel_tipo))}</td>
        <td>${_escHtml(_fmtKmNullable(a.km_inicial))}</td>
        <td>${_escHtml(_fmtKmNullable(a.km_final ?? a.km_atual ?? a.km))}</td>
        <td>${_escHtml(_fmtKmNullable(a.km_rodado))}</td>
        <td>${_escHtml(postoEmitente)}</td>
        <td>${_escHtml(nota)}</td>
        <td>${_escHtml(_fmtNumber(a.quantidade_litros, 3))}</td>
        <td>${_escHtml(valorLitro)}</td>
        <td>${_escHtml(valorTotal)}</td>
        <td>${_escHtml(_fmtNumberNullable(a.km_l, 2))}</td>
      </tr>
    `;
  });

  const lavagemRows = lavagens.map((l) => `
    <tr>
      <td>${_escHtml(_fmtDateBr(l.data_lavagem || l.data_registro))}</td>
      <td>${_escHtml(String(l.km || 0))}</td>
      <td>${_escHtml(l.local || "-")}</td>
      <td>R$ ${_escHtml(_fmtMoney(l.valor))}</td>
      <td>${_escHtml(l.observacao || "-")}</td>
    </tr>
  `);

  body.innerHTML = `
    <div class="frota-historico-card">
      <h4>${_escHtml(titulo || "Historico do Caminhao")}</h4>
      <div class="frota-historico-kv">
        ${_frotaHistoricoResumoRow("Placa", v.placa || "-")}
        ${_frotaHistoricoResumoRow("Modelo", v.modelo || v.nome || "-")}
        ${_frotaHistoricoResumoRow("KM atual veiculo", v.km_atual ?? 0)}
        ${_frotaHistoricoResumoRow("KM atual frete", frete.km_atual ?? 0)}
        ${_frotaHistoricoResumoRow("Motorista atual", frete.motorista_nome || "-")}
        ${_frotaHistoricoResumoRow("Entregador", frete.entregador_nome || frete.motorista_nome || "-")}
        ${_frotaHistoricoResumoRow("Peso", frete.peso ?? 0)}
        ${_frotaHistoricoResumoRow("Qtd entregas", frete.qtd_entregas ?? 0)}
        ${_frotaHistoricoResumoRow("Frete atual", frete.nome || "-")}
        ${_frotaHistoricoResumoRow("Status frete", frete.status || "-")}
        ${_frotaHistoricoResumoRow("Media KM/L", mediaKm)}
        ${_frotaHistoricoResumoRow("Falta p/ manutencao", `${resumo.falta_manut_km ?? "-"} km`)}
        ${_frotaHistoricoResumoRow("Falta p/ oleo", `${resumo.falta_oleo_km ?? "-"} km`)}
      </div>
    </div>

    <div class="frota-historico-grid">
      <div class="frota-historico-card">
        <h4>Manutencoes</h4>
        ${_frotaHistoricoTable(["Data", "Tipo", "KM", "Valor", "Itens"], manutRows, "Sem manutencoes registradas.")}
      </div>
      <div class="frota-historico-card">
        <h4>Trocas de Oleo</h4>
        ${_frotaHistoricoTable(["Data", "Tipo", "KM"], oleoRows, "Sem trocas de oleo registradas.")}
      </div>
      <div class="frota-historico-card">
        <h4>Trocas de Pneu</h4>
        ${_frotaHistoricoTable(["Data", "Marca", "KM", "Qtd", "Valor", "Custo/pneu", "Localizacao"], pneuRows, "Sem trocas de pneu registradas.")}
      </div>
      <div class="frota-historico-card">
        <h4>Abastecimentos</h4>
        ${_frotaHistoricoTable(["Data", "Status", "Comb.", "KM inicial", "KM final", "KM rodado", "Posto / Emitente", "NF-e", "Qtd litros", "Valor/L", "Valor total", "Média KM/L"], abastRows, "Sem abastecimentos registrados.")}
      </div>
      <div class="frota-historico-card">
        <h4>Lavagens</h4>
        ${_frotaHistoricoTable(["Data", "KM", "Local", "Valor", "Observacao"], lavagemRows, "Sem lavagens registradas.")}
      </div>
    </div>
  `;
}

const RELATORIO_FRETE_TIPOS_FILTRAVEIS = new Set(["escala", "historico_fretes"]);
const RELATORIO_ABASTECIMENTO_TIPOS_FILTRAVEIS = new Set([
  "abastecimentos",
  "abastecimentos_criticos",
  "abastecimentos_sem_placa",
]);

function renderFiltrosRelatorioFretes(){
  const wrap = document.getElementById("frotaRelFreteStatusChecklist");
  if (!wrap) return;
  wrap.innerHTML = FRETE_STATUS_OPCOES.map((status) => `
    <label class="relatorio-frete-status-item">
      <input type="checkbox" class="relatorio-frete-status-check" value="${_escHtml(status.key)}" checked>
      <span>${_escHtml(status.label)}</span>
    </label>
  `).join("");
}

function marcarTodosStatusRelatorioFrete(marcar = true){
  document.querySelectorAll(".relatorio-frete-status-check").forEach((input) => {
    input.checked = !!marcar;
  });
}

function _tipoRelatorioUsaFiltroFretes(tipo = ""){
  return RELATORIO_FRETE_TIPOS_FILTRAVEIS.has(String(tipo || "").toLowerCase());
}

function _tipoRelatorioUsaFiltroAbastecimentos(tipo = ""){
  return RELATORIO_ABASTECIMENTO_TIPOS_FILTRAVEIS.has(String(tipo || "").toLowerCase());
}

function _tipoRelatorioEscala(tipo = ""){
  return String(tipo || "").toLowerCase() === "escala";
}

function _coletarFiltrosRelatorioFretes(){
  const dataInicio = (document.getElementById("frotaRelFreteDataInicio")?.value || "").trim();
  const dataFim = (document.getElementById("frotaRelFreteDataFim")?.value || "").trim();
  const ordenacao = (document.getElementById("frotaRelFreteOrdenacao")?.value || "status_data").trim();
  const statuses = Array.from(document.querySelectorAll(".relatorio-frete-status-check:checked"))
    .map((input) => (input.value || "").trim())
    .filter(Boolean);
  return { dataInicio, dataFim, ordenacao, statuses };
}

function _coletarFiltrosRelatorioAbastecimentos(){
  let dataInicio = (document.getElementById("frotaRelAbastDataInicio")?.value || "").trim();
  let dataFim = (document.getElementById("frotaRelAbastDataFim")?.value || "").trim();
  if (!dataInicio && !dataFim) {
    dataInicio = (document.getElementById("frotaRelFreteDataInicio")?.value || "").trim();
    dataFim = (document.getElementById("frotaRelFreteDataFim")?.value || "").trim();
  }
  if (dataInicio && !dataFim) dataFim = dataInicio;
  if (!dataInicio && dataFim) dataInicio = dataFim;
  return { dataInicio, dataFim };
}

function gerarRelatorioFrota(tipo = "resumo"){
  const params = new URLSearchParams();
  params.set("tipo", tipo);

  if (_tipoRelatorioUsaFiltroFretes(tipo)) {
    const { dataInicio, dataFim, ordenacao, statuses } = _coletarFiltrosRelatorioFretes();
    if (_tipoRelatorioEscala(tipo) && (!dataInicio || !dataFim)) {
      alert("Informe a data inicial e a data final para gerar a escala.");
      return;
    }
    if (dataInicio && dataFim && dataInicio > dataFim) {
      alert("A data inicial nao pode ser maior que a data final.");
      return;
    }
    if (!statuses.length) {
      alert("Selecione ao menos um status do kanban para gerar o relatorio.");
      return;
    }
    if (dataInicio) params.set("data_inicio", dataInicio);
    if (dataFim) params.set("data_fim", dataFim);
    if (_tipoRelatorioEscala(tipo) && ordenacao) {
      params.set("ordenacao", ordenacao);
    }
    if (statuses.length < FRETE_STATUS_OPCOES.length) {
      statuses.forEach((status) => params.append("status", status));
    }
  }

  if (_tipoRelatorioUsaFiltroAbastecimentos(tipo)) {
    const { dataInicio, dataFim } = _coletarFiltrosRelatorioAbastecimentos();
    if (dataInicio && dataFim && dataInicio > dataFim) {
      alert("A data inicial nao pode ser maior que a data final.");
      return;
    }
    if (dataInicio) params.set("data_inicio", dataInicio);
    if (dataFim) params.set("data_fim", dataFim);
  }

  window.open(`/api/frota_relatorio?${params.toString()}`, "_blank", "noopener");
}

function _estoqueFormatQtd(v){
  const n = Number(v || 0);
  if (!Number.isFinite(n)) return "0";
  const casas = Number.isInteger(n) ? 0 : 3;
  return n.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: 3 });
}

function _estoqueRowsPayload(payload){
  if (Array.isArray(payload?.rows)) return payload.rows;
  return Array.isArray(payload) ? payload : [];
}

function _estoqueMetaPayload(payload){
  return payload && typeof payload === "object" && !Array.isArray(payload) ? (payload.meta || {}) : {};
}

const ESTOQUE_FORNECEDOR_CATEGORIAS = {
  materia_prima: "Materia-prima",
  pecas_auto: "Pecas auto / frota",
  distribuidora: "Distribuidora",
  outros: "Outros",
};

function _estoqueCategoriaFornecedorLabel(valor = ""){
  const key = String(valor || "outros").trim().toLowerCase() || "outros";
  return ESTOQUE_FORNECEDOR_CATEGORIAS[key] || key.replace(/_/g, " ");
}

function _estoqueFornecedorKey(fornecedor = {}){
  return String(fornecedor?.cnpj || fornecedor?.nome || "").trim();
}

function _estoqueFornecedoresItem(item = {}){
  if (Array.isArray(item.fornecedores)) return item.fornecedores.filter(Boolean);
  if (item.fornecedor && typeof item.fornecedor === "object") return [item.fornecedor];
  if (item.fornecedor_nome || item.fornecedor_categoria) {
    return [{
      cnpj: item.fornecedor_cnpj || "",
      nome: item.fornecedor_nome || "",
      categoria: item.fornecedor_categoria || "outros",
    }];
  }
  return [];
}

function _estoqueFornecedorResumo(item = {}){
  const fornecedores = _estoqueFornecedoresItem(item);
  if (!fornecedores.length) return "Sem fornecedor";
  return fornecedores.map((f) => f.nome || f.cnpj || "Fornecedor").filter(Boolean).join(" | ");
}

function _estoqueCategoriaFornecedorResumo(item = {}){
  const categorias = Array.isArray(item.fornecedor_categorias)
    ? item.fornecedor_categorias
    : _estoqueFornecedoresItem(item).map((f) => f.categoria || "outros");
  const unicas = [...new Set(categorias.filter(Boolean).map((cat) => String(cat).toLowerCase()))];
  return unicas.length ? unicas.map(_estoqueCategoriaFornecedorLabel).join(" | ") : "Sem categoria";
}

function _estoqueTextoBusca(valor = ""){
  return String(valor || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toUpperCase();
}

function _estoqueValoresSelecionados(id){
  const el = document.getElementById(id);
  if (!el) return [];
  if (el.multiple) {
    return Array.from(el.selectedOptions || []).map((opt) => String(opt.value || "").trim()).filter(Boolean);
  }
  const value = String(el.value || "").trim();
  return value ? [value] : [];
}

function _estoqueFiltroValor(id){
  return String(document.getElementById(id)?.value || "").trim();
}

function _estoqueFiltrosEscopo(escopo){
  return {
    categoria: _estoqueFiltroValor(`estoqueFiltroCategoria${escopo}`),
    fornecedores: _estoqueValoresSelecionados(`estoqueFiltroFornecedor${escopo}`),
    produtos: _estoqueValoresSelecionados(`estoqueFiltroProduto${escopo}`),
    produtoTexto: _estoqueFiltroValor("estoqueFiltroProdutoLancar"),
    termo: _estoqueFiltroValor("estoqueFiltroNotaRastreio"),
  };
}

function _estoqueItemCombinaFiltros(item = {}, filtros = {}){
  const fornecedores = _estoqueFornecedoresItem(item);
  const categorias = new Set(
    fornecedores.map((f) => String(f.categoria || "outros").toLowerCase())
  );
  if (Array.isArray(item.fornecedor_categorias)) {
    item.fornecedor_categorias.forEach((cat) => categorias.add(String(cat || "outros").toLowerCase()));
  }
  if (filtros.categoria && !categorias.has(String(filtros.categoria).toLowerCase())) return false;

  if (filtros.fornecedores?.length) {
    const keys = new Set(fornecedores.map(_estoqueFornecedorKey).filter(Boolean));
    if (![...keys].some((key) => filtros.fornecedores.includes(key))) return false;
  }

  if (filtros.produtos?.length) {
    const produtoKey = _estoqueProdutoBaseKey(item);
    if (!filtros.produtos.includes(produtoKey)) return false;
  }

  const termo = _estoqueTextoBusca(filtros.termo || "");
  if (termo) {
    const haystack = _estoqueTextoBusca([
      item.numero_nota,
      item.codigo_produto_nfe,
      item.codigo_barras,
      item.nome_produto,
      item.produto_base_nome,
      _estoqueFornecedorResumo(item),
      _estoqueCategoriaFornecedorResumo(item),
    ].join(" "));
    if (!haystack.includes(termo)) return false;
  }
  return true;
}

function _estoqueLinhaPosicaoDoProduto(produto = {}){
  const rows = Array.isArray(estoqueState.posicaoRows) ? estoqueState.posicaoRows : [];
  const produtoKey = _estoqueProdutoBaseKey(produto);
  const codigoBarras = _digitsOnly(produto.codigo_barras || "");
  const codigoNfe = _estoqueCodigoNormalizadoComparacao(produto.codigo_produto_nfe || "");
  const nome = _estoqueTextoBusca(produto.produto_base_nome || produto.nome_produto || "");
  return rows.find((row) => {
    if (produtoKey && _estoqueProdutoBaseKey(row) === produtoKey) return true;
    if (codigoBarras && _digitsOnly(row.codigo_barras || "") === codigoBarras) return true;
    if (codigoNfe && _estoqueCodigoNormalizadoComparacao(row.codigo_produto_nfe || "") === codigoNfe) return true;
    return nome && _estoqueTextoBusca(row.produto_base_nome || row.nome_produto || "") === nome;
  }) || null;
}

function _estoqueProdutoLancamentoCombinaFiltros(produto = {}){
  const filtros = _estoqueFiltrosEscopo("Lancar");
  const texto = _estoqueTextoBusca(filtros.produtoTexto || "");
  if (texto) {
    const haystack = _estoqueTextoBusca([
      produto.nome_produto,
      produto.produto_base_nome,
      produto.codigo_barras,
      produto.codigo_produto_nfe,
      produto.grupo_estoque,
    ].join(" "));
    if (!haystack.includes(texto)) return false;
  }
  if (!filtros.categoria && !filtros.fornecedores.length) return true;
  const row = _estoqueLinhaPosicaoDoProduto(produto);
  return row ? _estoqueItemCombinaFiltros(row, filtros) : false;
}

const ESTOQUE_GRUPOS_ORDEM = { GFA: 0, PET: 1, AGUA: 2, OUTROS: 3 };

function _estoqueGrupoNormalizado(valor = ""){
  const raw = String(valor || "").trim().toUpperCase();
  if (!raw) return "";
  const aliases = {
    GF: "GFA",
    GFA: "GFA",
    GRF: "GFA",
    GARRAFA: "GFA",
    RETORNAVEL: "GFA",
    RETORNAVEIS: "GFA",
    VIDRO: "GFA",
    PET: "PET",
    DESCARTAVEL: "PET",
    DESCARTAVEIS: "PET",
    AGUA: "AGUA",
    "ÁGUA": "AGUA",
    OUTRO: "OUTROS",
    OUTROS: "OUTROS",
  };
  return aliases[raw] || (Object.prototype.hasOwnProperty.call(ESTOQUE_GRUPOS_ORDEM, raw) ? raw : "");
}

function _estoqueGrupoInferido(item = {}){
  const explicito = _estoqueGrupoNormalizado(item.grupo_estoque || item.grupo || "");
  if (explicito) return explicito;
  const texto = `${item.nome_produto || ""} ${item.codigo_produto_nfe || ""} ${item.codigo_barras || ""}`.toUpperCase();
  if (/\bAGUA\b/.test(texto)) return "AGUA";
  if (/\bPREFORMA\b/.test(texto) || /\bPRE\s*-?\s*FORMA\b/.test(texto)) return "OUTROS";
  if (/\bPET\b/.test(texto) || /\bDESCART/.test(texto)) return "PET";
  if (/\bGFA\b/.test(texto) || /\bGRF\b/.test(texto) || /\bGARRAFA\b/.test(texto) || /\bVIDRO\b/.test(texto)) return "GFA";
  return "OUTROS";
}

function _estoqueGrupoLabel(valor = ""){
  const grupo = _estoqueGrupoNormalizado(valor) || "OUTROS";
  return grupo === "OUTROS" ? "Outros" : grupo;
}

function _estoqueGrupoOrdem(valor = ""){
  const grupo = _estoqueGrupoNormalizado(valor) || "OUTROS";
  return Object.prototype.hasOwnProperty.call(ESTOQUE_GRUPOS_ORDEM, grupo) ? ESTOQUE_GRUPOS_ORDEM[grupo] : 99;
}

function _estoqueOrdenarPorGrupo(rows = []){
  return [...(Array.isArray(rows) ? rows : [])].sort((a, b) => {
    const grupoA = _estoqueGrupoOrdem(a?.grupo_estoque);
    const grupoB = _estoqueGrupoOrdem(b?.grupo_estoque);
    if (grupoA !== grupoB) return grupoA - grupoB;
    const nomeA = String(a?.produto_base_nome || a?.nome_produto || "").toUpperCase();
    const nomeB = String(b?.produto_base_nome || b?.nome_produto || "").toUpperCase();
    const porNome = nomeA.localeCompare(nomeB, "pt-BR");
    if (porNome) return porNome;
    const fatorA = Number(a?.fator_embalagem_padrao || a?.fator_embalagem || 0) || 0;
    const fatorB = Number(b?.fator_embalagem_padrao || b?.fator_embalagem || 0) || 0;
    if (fatorA !== fatorB) return fatorA - fatorB;
    const codigoA = String(a?.codigo_produto_nfe || a?.codigo_barras || "").toUpperCase();
    const codigoB = String(b?.codigo_produto_nfe || b?.codigo_barras || "").toUpperCase();
    return codigoA.localeCompare(codigoB, "pt-BR");
  });
}

function _estoqueLinhasAgrupadas(rows = [], rowRenderer, colspan = 1){
  let grupoAtual = "";
  return _estoqueOrdenarPorGrupo(rows).map((row) => {
    const grupo = _estoqueGrupoNormalizado(row?.grupo_estoque) || "OUTROS";
    const partes = [];
    if (grupo !== grupoAtual) {
      grupoAtual = grupo;
      partes.push(`<tr class="estoque-group-row"><td colspan="${Number(colspan || 1)}">${_escHtml(_estoqueGrupoLabel(grupo))}</td></tr>`);
    }
    partes.push(rowRenderer(row));
    return partes.join("");
  }).join("");
}

function _estoqueBaseNomeInferido(item = {}){
  const explicito = String(item.produto_base_nome || item.produto_base || "").trim();
  if (explicito) return explicito;
  const grupo = _estoqueGrupoInferido(item);
  const texto = String(item.nome_produto || "").toUpperCase();
  if (grupo === "PET") {
    if (/\b2\s*L(T)?\b|\b2LT\b/.test(texto)) return "PET 2L";
    if (/\b600\s*ML\b|\bPET\s*600\b/.test(texto)) return "PET 600ML";
    if (/\b200\s*ML\b|\bPET\s*200\b/.test(texto)) return "PET 200ML";
  }
  if (grupo === "GFA") {
    if (/\b600\s*ML\b|\bGFA\s*600\b|\bGRF\s*600\b/.test(texto)) return "GFA 600ML";
    if (/\b200\s*ML\b|\bGFA\s*200\b|\bGRF\s*200\b/.test(texto)) return "GFA 200ML";
  }
  if (grupo === "AGUA") {
    if (/\b510\s*ML\b/.test(texto)) return "AGUA 510ML";
    return "AGUA";
  }
  const tokens = String(item.nome_produto || "")
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .filter((tok) => !["UN", "UND", "UNIDADE", "UNIDADES", "DZ", "DUZIA", "DUZIAS", "CX", "CX24", "CX48", "CAIXA", "CAIXAS", "PCT", "PAC", "PACOTE", "PACOTES", "FD", "FARDO", "FARDOS", "PAL", "PALLET", "PALLETS", "9", "12", "24", "35", "48", "80"].includes(tok));
  return tokens.join(" ") || String(item.nome_produto || "").trim() || "PRODUTO";
}

function _estoqueTextoChave(valor = ""){
  return String(valor || "")
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, " ")
    .trim();
}

function _estoqueProdutoBaseKey(item = {}){
  const existente = String(item.produto_base_key || "").trim();
  if (existente) return existente;
  const grupo = _estoqueGrupoNormalizado(item.grupo_estoque || item.grupo || "") || _estoqueGrupoInferido(item) || "OUTROS";
  const base = _estoqueTextoChave(item.produto_base_nome || item.produto_base || _estoqueBaseNomeInferido(item) || item.nome_produto || "");
  const codigo = _estoqueCodigoNormalizadoComparacao(item.codigo_produto_nfe || "") || _digitsOnly(item.codigo_barras || "");
  return `${grupo}:${base || codigo || "PRODUTO"}`;
}

function _estoqueApresentacaoNormalizada(...valores){
  const texto = valores.map((valor) => String(valor || "").trim().toUpperCase()).filter(Boolean).join(" ");
  if (!texto) return "UN";
  if (texto.includes("PALLET") || /\bPAL\b/.test(texto)) return "PALLET";
  if (texto.includes("DUZIA") || texto.includes("DUZIAS") || /\bDZ\b/.test(texto)) return "DZ";
  if (texto.includes("CX48")) return "CX48";
  if (texto.includes("CX24")) return "CX24";
  if (texto.includes("CAIXA") || texto.includes("CAIXAS") || /\bCX\b/.test(texto)) return "CX";
  if (texto.includes("PACOTE") || texto.includes("PACOTES") || /\bPCT\b/.test(texto) || /\bPAC\b/.test(texto)) return "PCT";
  if (texto.includes("FARDO") || texto.includes("FARDOS") || /\bFD\b/.test(texto)) return "FD";
  if (texto.includes("UNIDADE") || texto.includes("UNIDADES") || /\bUND\b/.test(texto) || /\bUN\b/.test(texto)) return "UN";
  return _estoqueEmbalagemPadrao(texto);
}

function _estoqueExtrairMultiplicador(...valores){
  const texto = valores.map((valor) => String(valor || "").trim().toUpperCase()).filter(Boolean).join(" ");
  if (!texto) return 0;
  const patterns = [
    /\b(?:C\/|COM|X)\s*0*([1-9]\d{0,2})\b/,
    /\b(?:PCT|PAC|PACOTE|PACOTES|FD|FARDO|FARDOS|CX|CAIXA|CAIXAS)\s*0*([1-9]\d{0,2})\b/,
    /\b0*([1-9]\d{0,2})\s*(?:UN|UND|UNIDADES|GARRAFAS|PACOTES|CAIXAS)\b/,
  ];
  for (const pattern of patterns) {
    const match = texto.match(pattern);
    if (match) return Number(match[1] || 0) || 0;
  }
  return 0;
}

function _estoqueResolverFatorProduto(item = {}, cadastro = null){
  const produto = cadastro || _buscarProdutoCadastroEstoque(item) || null;
  const combinado = {
    ...produto,
    ...item,
    nome_produto: item.nome_produto || produto?.nome_produto || "",
    grupo_estoque: item.grupo_estoque || produto?.grupo_estoque || "",
    produto_base_nome: item.produto_base_nome || produto?.produto_base_nome || "",
  };
  const grupo = _estoqueGrupoNormalizado(combinado.grupo_estoque) || _estoqueGrupoInferido(combinado) || "OUTROS";
  const produtoBaseNome = String(combinado.produto_base_nome || _estoqueBaseNomeInferido({ ...combinado, grupo_estoque: grupo }) || combinado.nome_produto || "").trim();
  const apresentacao = _estoqueApresentacaoNormalizada(
    item.embalagem_tipo || item.unidade || "",
    produto?.embalagem_tipo_padrao || produto?.unidade || "",
    combinado.nome_produto || ""
  );
  const fatorInformado = Number(item.fator_embalagem || produto?.fator_embalagem_padrao || 0) || 0;
  const cadastroExplicitado = !!(produto && Number(produto.id || 0) > 0 && Number(produto.cadastro_explicitado || 0) === 1 && Number(produto.fator_embalagem_padrao || 0) > 0);
  const texto = [
    item.embalagem_tipo,
    item.unidade,
    item.nome_produto,
    produto?.nome_produto,
    produto?.embalagem_tipo_padrao,
    produtoBaseNome,
  ].map((valor) => String(valor || "").trim().toUpperCase()).filter(Boolean).join(" ");
  const multiplicador = _estoqueExtrairMultiplicador(texto);
  const pacotePet = /\b9\b/.test(texto) ? 9 : (/\b12\b/.test(texto) ? 12 : 0);
  let fator = fatorInformado;
  let fatorInferido = false;
  let motivoConfirmacao = "";

  if (!(fator > 0)) {
    if (apresentacao === "UN") {
      fator = 1;
    } else if (grupo === "GFA") {
      if (apresentacao === "DZ") {
        fator = 12;
      } else if (apresentacao === "PALLET") {
        fator = multiplicador > 100 ? multiplicador : 35 * 24;
        motivoConfirmacao = "Pallet de GFA assumido no padrao 35 caixas x 24 garrafas.";
      } else if (["CX", "CX24", "CX48"].includes(apresentacao)) {
        fator = multiplicador > 0 ? multiplicador : 24;
        motivoConfirmacao = multiplicador > 0 ? "Caixa de GFA inferida pelo texto da embalagem." : "Caixa de GFA assumida no padrao de 24 garrafas.";
      } else {
        fator = 12;
        motivoConfirmacao = "Apresentacao de GFA assumida como duzia (12 garrafas).";
      }
      fatorInferido = true;
    } else if (grupo === "PET") {
      const pacotePadrao = pacotePet || 12;
      if (apresentacao === "PALLET") {
        fator = pacotePadrao * 80;
        motivoConfirmacao = pacotePet
          ? `Pallet PET calculado com 80 pacotes de ${pacotePadrao}.`
          : "Pallet PET assumido no padrao 80 pacotes de 12 unidades.";
      } else if (["PCT", "FD", "CX", "CX24", "CX48"].includes(apresentacao)) {
        fator = multiplicador > 0 ? multiplicador : pacotePadrao;
        motivoConfirmacao = pacotePet
          ? `PET inferido com pacote de ${fator} unidades.`
          : "PET assumido no padrao de 12 unidades por pacote.";
      } else {
        fator = 1;
      }
      fatorInferido = fator > 1;
    } else if (grupo === "AGUA") {
      if (multiplicador > 0) {
        fator = multiplicador;
        fatorInferido = true;
        motivoConfirmacao = "Agua inferida pelo multiplicador encontrado na descricao.";
      } else if (apresentacao === "UN") {
        fator = 1;
      } else {
        fator = 0;
        motivoConfirmacao = "Produto de agua sem fator explicito. Revise o cadastro antes de lancar.";
      }
    } else {
      if (multiplicador > 0) {
        fator = multiplicador;
        fatorInferido = true;
        motivoConfirmacao = "Fator inferido pelo texto da embalagem.";
      } else if (apresentacao === "UN") {
        fator = 1;
      } else {
        fator = 0;
        motivoConfirmacao = "Produto sem fator explicito para esta apresentacao.";
      }
    }
  }

  const confirmacaoPendente = !cadastroExplicitado || fatorInferido;
  if (!motivoConfirmacao && !cadastroExplicitado) {
    motivoConfirmacao = "Cadastro do produto ainda sem grupo/base/fator explicitados.";
  }
  return {
    produto,
    grupo_estoque: grupo,
    produto_base_nome: produtoBaseNome || combinado.nome_produto || "Produto",
    produto_base_key: _estoqueProdutoBaseKey({
      ...combinado,
      grupo_estoque: grupo,
      produto_base_nome: produtoBaseNome,
    }),
    embalagem_tipo: apresentacao || "UN",
    fator_embalagem: Number(fator || 0) || 0,
    fator_inferido: !!fatorInferido,
    cadastro_explicitado: cadastroExplicitado ? 1 : 0,
    confirmacao_pendente: !!confirmacaoPendente,
    motivo_confirmacao: motivoConfirmacao,
    bloqueado: !(Number(fator || 0) > 0),
  };
}

function _estoqueConfirmacaoLancamentoTexto(item = {}, resolvido = null){
  const meta = resolvido || _estoqueResolverFatorProduto(item);
  const qtdEmb = Number(item.quantidade_embalagem ?? item.quantidade ?? 0) || 0;
  const totalBase = Number(item.quantidade_unidades ?? (qtdEmb * (Number(meta.fator_embalagem || 0) || 0))) || 0;
  const produto = item.nome_produto || meta.produto_base_nome || "Produto";
  const embalagem = meta.embalagem_tipo || "UN";
  const motivo = meta.motivo_confirmacao ? `\nMotivo: ${meta.motivo_confirmacao}` : "";
  return `${produto}\nGrupo: ${_estoqueGrupoLabel(meta.grupo_estoque)}\nLancamento: ${_estoqueFormatQtd(qtdEmb)} ${embalagem}${Number(meta.fator_embalagem || 0) > 1 ? ` x ${_estoqueFormatQtd(meta.fator_embalagem)}` : ""}\nTotal em estoque: ${_estoqueFormatQtd(totalBase)} unidade(s).${motivo}`;
}

function _estoqueCodigoReferencia(item = {}){
  return item?.codigo_produto_nfe || item?.codigo_barras || "-";
}

function sincronizarNumeroNotaPorCodigo(){
  const codigo = document.getElementById("estoqueCodigoBarras");
  const nota = document.getElementById("estoqueNumeroNota");
  if (!codigo || !nota) return;
  if (!nota.value.trim()) nota.value = (codigo.value || "").trim();
}

async function renderDashboardEstoque(){
  const bodyPrevisao = document.getElementById("dashEstoquePrevisaoBody");
  const bodySaldo = document.getElementById("dashEstoqueSaldoBody");
  const resumo = document.getElementById("dashEstoqueResumo");
  if (!bodyPrevisao || !bodySaldo) return;
  const resp = await apiFetch("/api/dashboard_estoque");
  if (!resp.ok) {
    bodyPrevisao.innerHTML = `<tr><td colspan="7">Erro ao carregar previsao do estoque.</td></tr>`;
    bodySaldo.innerHTML = `<tr><td colspan="7">Erro ao carregar saldo do estoque.</td></tr>`;
    if (resumo) resumo.textContent = "Nao foi possivel carregar o saldo comprometido do estoque.";
    return;
  }
  const payload = await resp.json();
  const dados = _estoqueRowsPayload(payload);
  const meta = _estoqueMetaPayload(payload);
  if (resumo) {
    resumo.textContent = [
      `Referencia: ${_fmtDataCurtaBr(meta.data_referencia || "")}`,
      `Cargas importadas: ${meta.cargas_importadas || 0}`,
      `Pendentes: ${meta.cargas_pendentes || 0}`,
      `Baixadas: ${meta.cargas_baixadas || 0}`,
      `Vendas dia: ${_estoqueFormatQtd(meta.vendas_dia_total || 0)}`,
      `Saidas dia: ${_estoqueFormatQtd(meta.saidas_dia_total || 0)}`,
    ].join(" | ");
  }
  bodyPrevisao.innerHTML = dados.length ? _estoqueLinhasAgrupadas(dados, (r) => `
    <tr>
      <td>${_escHtml(r.produto_base_nome || r.nome_produto || "-")}</td>
      <td>${_escHtml(_estoqueCodigoReferencia(r))}</td>
      <td>${_escHtml(_estoqueFormatQtd(r.quantidade_atual))}</td>
      <td>${_escHtml(_estoqueFormatQtd(r.vendas_dia))}</td>
      <td>${_escHtml(_estoqueFormatQtd(r.saidas_dia))}</td>
      <td>${_escHtml(_estoqueFormatQtd(r.quantidade_comprometida))}</td>
      <td><span style="font-weight:700;color:${Number(r.saldo_previsto_dia || 0) < 0 ? "#b91c1c" : "#166534"};">${_escHtml(_estoqueFormatQtd(r.saldo_previsto_dia))}</span></td>
    </tr>
  `, 7) : `<tr><td colspan="7">Sem itens cadastrados no estoque.</td></tr>`;
  bodySaldo.innerHTML = dados.length ? _estoqueLinhasAgrupadas(dados, (r) => `
    <tr>
      <td>${_escHtml(r.produto_base_nome || r.nome_produto || "-")}</td>
      <td>${_escHtml(_estoqueCodigoReferencia(r))}</td>
      <td>${_escHtml(_estoqueFormatQtd(r.quantidade_atual))}</td>
      <td>${_escHtml(_estoqueFormatQtd(r.quantidade_comprometida))}</td>
      <td><span style="font-weight:700;color:${Number(r.saldo_remanescente || 0) < 0 ? "#b91c1c" : "#166534"};">${_escHtml(_estoqueFormatQtd(r.saldo_remanescente))}</span></td>
      <td>R$ ${_escHtml(_fmtMoney(r.ultimo_valor))}</td>
      <td>${_escHtml(_fmtDateBr(r.ultima_movimentacao))}</td>
    </tr>
  `, 7) : `<tr><td colspan="7">Sem itens cadastrados no estoque.</td></tr>`;
}

function _estoqueResumoFluxo(item){
  const origem = (item?.origem_setor || "").trim();
  const destino = (item?.destino_setor || "").trim();
  if (origem && destino) return `${origem} -> ${destino}`;
  return origem || destino || "-";
}

function _novoItemImportacaoEstoque(seq = 1){
  return {
    xml_item_id: 0,
    item_seq: String(seq || 1),
    produto_id: "",
    codigo_produto_nfe: "",
    codigo_barras: "",
    nome_produto: "",
    grupo_estoque: "",
    produto_base_nome: "",
    unidade: "",
    quantidade: "",
    quantidade_embalagem: "",
    embalagem_tipo: "",
    fator_embalagem: "",
    fator_inferido: false,
    confirmacao_pendente: false,
    motivo_confirmacao: "",
    quantidade_unidades: "",
    valor_unitario: "",
  };
}

function _estoqueEmbalagemPadrao(valor = ""){
  const raw = String(valor || "").trim().toUpperCase();
  if (!raw) return "UN";
  if (raw.includes("PALLET") || /\bPAL\b/.test(raw)) return "PALLET";
  if (raw.includes("DUZIA") || raw.includes("DUZIAS") || /\bDZ\b/.test(raw)) return "DZ";
  if (raw.includes("CX48")) return "CX48";
  if (raw.includes("CX24")) return "CX24";
  if (/^CX\b/.test(raw) || raw.includes("CAIXA")) return "CX";
  if (raw.includes("FARDO") || /\bFD\b/.test(raw)) return "FD";
  if (raw.includes("PCT") || raw.includes("PAC")) return "PCT";
  if (raw.includes("UN") || raw.includes("UND") || raw.includes("PC")) return "UN";
  return raw;
}

function _estoqueAjustarEmbalagemPorFator(embalagem, fator){
  const base = _estoqueEmbalagemPadrao(embalagem);
  const numero = Number(fator || 0) || 0;
  if ((base === "CX" || base === "CX24" || base === "CX48") && numero === 24) return "CX24";
  if ((base === "CX" || base === "CX24" || base === "CX48") && numero === 48) return "CX48";
  return base;
}

function _estoqueProdutoCadastroNormalizado(item = {}){
  const grupo = _estoqueGrupoNormalizado(item.grupo_estoque || item.grupo || "") || _estoqueGrupoInferido(item) || "OUTROS";
  const produtoBaseNome = String(item.produto_base_nome || item.produto_base || "").trim() || _estoqueBaseNomeInferido({ ...item, grupo_estoque: grupo });
  const produto = {
    id: Number(item.id || 0) || 0,
    codigo_barras: _digitsOnly(item.codigo_barras || ""),
    codigo_produto_nfe: String(item.codigo_produto_nfe || "").trim(),
    nome_produto: String(item.nome_produto || "").trim(),
    grupo_estoque: grupo,
    produto_base_nome: produtoBaseNome,
    unidade: String(item.unidade || "").trim(),
    embalagem_tipo_padrao: _estoqueEmbalagemPadrao(item.embalagem_tipo_padrao || item.embalagem_tipo || item.unidade || ""),
    fator_embalagem_padrao: Number(item.fator_embalagem_padrao || item.fator_embalagem || 0) || 0,
    cadastro_explicitado: Number(item.cadastro_explicitado || 0) === 1 ? 1 : 0,
  };
  produto.produto_base_key = String(item.produto_base_key || "").trim() || _estoqueProdutoBaseKey(produto);
  return produto;
}

function _buscarProdutoCadastroEstoque(item = {}){
  const produtoId = Number(item.produto_id || item.id || 0) || 0;
  const codigoBarras = _digitsOnly(item.codigo_barras || "");
  const codigoNfe = String(item.codigo_produto_nfe || "").trim().toUpperCase();
  const nome = String(item.nome_produto || "").trim().toUpperCase();
  const baseKey = _estoqueProdutoBaseKey(item);
  const lista = Array.isArray(estoqueState.cadastroProdutos) ? estoqueState.cadastroProdutos : [];
  if (produtoId > 0) {
    const porId = lista.find((prod) => Number(prod.id || 0) === produtoId);
    if (porId) return porId;
  }
  if (codigoBarras) {
    const porBarras = lista.find((prod) => _digitsOnly(prod.codigo_barras || "") === codigoBarras);
    if (porBarras) return porBarras;
  }
  if (codigoNfe) {
    const porCodigo = lista.find((prod) => String(prod.codigo_produto_nfe || "").trim().toUpperCase() === codigoNfe);
    if (porCodigo) return porCodigo;
  }
  if (nome) {
    const porNome = lista.find((prod) => String(prod.nome_produto || "").trim().toUpperCase() === nome);
    if (porNome) return porNome;
  }
  if (baseKey) {
    const porBase = lista.find((prod) => _estoqueProdutoBaseKey(prod) === baseKey);
    if (porBase) return porBase;
  }
  return null;
}

function _estoqueInferirFatorEmbalagem(item = {}){
  return Number(_estoqueResolverFatorProduto(item).fator_embalagem || 0) || 0;
}

function _enriquecerItemImportacaoEstoque(item = {}){
  const cadastro = _buscarProdutoCadastroEstoque(item);
  let unidadeRaw = String(item.unidade || "").trim();
  if (/^\d[\d.,]*$/.test(unidadeRaw)) {
    unidadeRaw = "";
  }
  const embalagemInicial = item.embalagem_tipo || cadastro?.embalagem_tipo_padrao || unidadeRaw || "";
  const embalagemBase = _estoqueApresentacaoNormalizada(embalagemInicial, unidadeRaw, item.nome_produto || cadastro?.nome_produto || "");
  const quantidade_embalagem = Number(item.quantidade_embalagem ?? item.quantidade ?? 0) || 0;
  const resolvido = _estoqueResolverFatorProduto({
    ...item,
    unidade: unidadeRaw,
    embalagem_tipo: embalagemBase,
    quantidade_embalagem,
  }, cadastro);
  const fator_embalagem = Number(resolvido.fator_embalagem || 0) || 0;
  const embalagem_tipo = _estoqueAjustarEmbalagemPorFator(resolvido.embalagem_tipo || embalagemBase, fator_embalagem);
  const quantidade_unidades = fator_embalagem > 0
    ? (Number(item.quantidade_unidades ?? 0) || (quantidade_embalagem * fator_embalagem))
    : 0;
  const fator_inferido = item.fator_inferido === true || item.fator_inferido === 1 || item.fator_inferido === "1"
    ? true
    : !!resolvido.fator_inferido;
  return {
    ...item,
    produto_id: Number(item.produto_id || cadastro?.id || 0) || 0,
    grupo_estoque: resolvido.grupo_estoque,
    produto_base_nome: resolvido.produto_base_nome,
    produto_base_key: resolvido.produto_base_key,
    cadastro_explicitado: resolvido.cadastro_explicitado ? 1 : 0,
    confirmacao_pendente: resolvido.confirmacao_pendente ? 1 : 0,
    motivo_confirmacao: resolvido.motivo_confirmacao || "",
    unidade: unidadeRaw,
    embalagem_tipo,
    quantidade_embalagem,
    fator_embalagem: fator_embalagem > 0 ? fator_embalagem : 0,
    fator_inferido,
    quantidade_unidades,
  };
}

function _normalizarDraftImportacaoEstoque(draft){
  const base = draft || {};
  const itens = Array.isArray(base.itens) ? base.itens.map((item, idx) => ({
    xml_item_id: Number(item?.xml_item_id || 0) || 0,
    item_seq: String(item?.item_seq || (idx + 1)).trim() || String(idx + 1),
    produto_id: item?.produto_id ?? "",
    codigo_produto_nfe: (item?.codigo_produto_nfe || "").trim(),
    codigo_barras: (item?.codigo_barras || "").trim(),
    nome_produto: (item?.nome_produto || "").trim(),
    grupo_estoque: (item?.grupo_estoque || "").trim(),
    produto_base_nome: (item?.produto_base_nome || "").trim(),
    unidade: (item?.unidade || "").trim(),
    quantidade: item?.quantidade ?? "",
    quantidade_embalagem: item?.quantidade_embalagem ?? item?.quantidade ?? "",
    embalagem_tipo: (item?.embalagem_tipo || "").trim(),
    fator_embalagem: item?.fator_embalagem ?? "",
    fator_inferido: item?.fator_inferido === true || item?.fator_inferido === 1 || item?.fator_inferido === "1",
    confirmacao_pendente: item?.confirmacao_pendente === true || item?.confirmacao_pendente === 1 || item?.confirmacao_pendente === "1",
    motivo_confirmacao: (item?.motivo_confirmacao || "").trim(),
    quantidade_unidades: item?.quantidade_unidades ?? "",
    valor_unitario: item?.valor_unitario ?? "",
  })).map((item) => _enriquecerItemImportacaoEstoque(item)).filter((item) => (
    item.nome_produto || item.codigo_produto_nfe || item.codigo_barras || String(item.quantidade || "").trim() || String(item.valor_unitario || "").trim()
  )) : [];
  const sourceType = String(base.source_type || "xml").toLowerCase();
  const transporteXml = base.transporte_xml && typeof base.transporte_xml === "object"
    ? base.transporte_xml
    : {};
  const freteSugestao = base.frete_sugestao && typeof base.frete_sugestao === "object"
    ? base.frete_sugestao
    : {};
  const preVinculoFrete = base.pre_vinculo_frete && typeof base.pre_vinculo_frete === "object"
    ? base.pre_vinculo_frete
    : {};
  const decisaoLogistica = base.decisao_logistica && typeof base.decisao_logistica === "object"
    ? base.decisao_logistica
    : {};

  return {
    source_type: sourceType === "pdf" || sourceType === "dfe" || sourceType === "portal" || sourceType === "ocr" || sourceType === "manual" || sourceType === "xml_fabrica" || sourceType === "importar_xml" ? sourceType : "xml",
    importar_xml_chave: String(base.importar_xml_chave || "").trim(),
    frete_id: Number(base.frete_id || 0) || 0,
    veiculo_id: Number(base.veiculo_id || 0) || 0,
    dispensa_frete: base.dispensa_frete === true || base.dispensa_frete === 1 || base.dispensa_frete === "1",
    tipo_transporte: String(base.tipo_transporte || "").trim(),
    decisao_logistica: {
      origem: String(decisaoLogistica.origem || "").trim(),
      motivo: String(decisaoLogistica.motivo || "").trim(),
    },
    pre_vinculo_frete: {
      origem_veiculo: String(preVinculoFrete.origem_veiculo || "").trim(),
      origem_frete: String(preVinculoFrete.origem_frete || "").trim(),
      status: String(preVinculoFrete.status || "").trim(),
    },
    transporte_xml: {
      placa: String(transporteXml.placa || "").trim(),
      uf_placa: String(transporteXml.uf_placa || "").trim(),
      mapa: String(transporteXml.mapa || "").trim(),
      numero_caminhao: String(transporteXml.numero_caminhao || "").trim(),
      modalidade_frete: String(transporteXml.modalidade_frete || "").trim(),
      arquivo_xml: String(transporteXml.arquivo_xml || "").trim(),
    },
    frete_sugestao: {
      frete_id: Number(freteSugestao.frete_id || 0) || 0,
      confianca: String(freteSugestao.confianca || "").trim(),
      motivo: String(freteSugestao.motivo || "").trim(),
      candidatos_total: Number(freteSugestao.candidatos_total || 0) || 0,
    },
    tipo_movimento: String(base.tipo_movimento || "entrada").trim().toLowerCase() === "saida" ? "saida" : "entrada",
    preview_tipo: String(base.preview_tipo || "completo").toLowerCase() === "parcial" ? "parcial" : "completo",
    limitation_message: (base.limitation_message || "").trim(),
    arquivo_origem: (base.arquivo_origem || "").trim(),
    __signature: (base.__signature || "").trim(),
    numero_nota: (base.numero_nota || "").trim(),
    serie: (base.serie || "").trim(),
    chave_acesso: _digitsOnly(base.chave_acesso || ""),
    data_emissao: (base.data_emissao || "").trim().slice(0, 10),
    emitente_nome: (base.emitente_nome || "").trim(),
    emitente_cnpj: _digitsOnly(base.emitente_cnpj || ""),
    destinatario_nome: (base.destinatario_nome || "").trim(),
    destinatario_cnpj: _digitsOnly(base.destinatario_cnpj || ""),
    valor_total: Number(base.valor_total || 0) || 0,
    warnings: Array.isArray(base.warnings) ? base.warnings.filter(Boolean) : [],
    itens,
  };
}

function _coletarDraftImportacaoEstoqueForm(){
  if (!estoqueState.importDraft) return null;
  const body = document.getElementById("estoqueImportPreviewItemsBody");
  const itens = body
    ? Array.from(body.querySelectorAll("tr[data-item-index]")).map((row, idx) => {
        const select = row.querySelector(".estoque-import-item-nome");
        const selected = select?.selectedOptions?.[0];
        return {
          xml_item_id: Number(row.dataset.xmlItemId || 0) || 0,
          item_seq: row.querySelector(".estoque-import-item-seq")?.value || String(idx + 1),
          produto_id: selected?.dataset.produtoId || "",
          codigo_produto_nfe: row.querySelector(".estoque-import-item-codnfe")?.value || "",
          codigo_barras: row.querySelector(".estoque-import-item-codbar")?.value || "",
          nome_produto: selected?.dataset.nome || select?.value || "",
          grupo_estoque: selected?.dataset.grupo || "",
          produto_base_nome: selected?.dataset.base || "",
          unidade: row.querySelector(".estoque-import-item-und")?.value || "",
          embalagem_tipo: row.querySelector(".estoque-import-item-und")?.value || "",
          quantidade: row.querySelector(".estoque-import-item-qtd")?.value || "",
          quantidade_embalagem: row.querySelector(".estoque-import-item-qtd")?.value || "",
          fator_embalagem: row.querySelector(".estoque-import-item-fator")?.value || "",
          fator_inferido: row.querySelector(".estoque-import-item-total-un")?.dataset.inferred === "1",
          quantidade_unidades: row.querySelector(".estoque-import-item-total-un")?.dataset.value || "",
          valor_unitario: row.querySelector(".estoque-import-item-valor")?.value || "",
        };
      })
    : [];

  return _normalizarDraftImportacaoEstoque({
    ...estoqueState.importDraft,
    numero_nota: document.getElementById("estoquePreviewNumeroNota")?.value || "",
    serie: document.getElementById("estoquePreviewSerie")?.value || "",
    chave_acesso: document.getElementById("estoquePreviewChaveAcesso")?.value || "",
    data_emissao: document.getElementById("estoquePreviewDataEmissao")?.value || "",
    emitente_nome: document.getElementById("estoquePreviewEmitenteNome")?.value || "",
    emitente_cnpj: document.getElementById("estoquePreviewEmitenteCnpj")?.value || "",
    destinatario_nome: document.getElementById("estoquePreviewDestinatarioNome")?.value || "",
    destinatario_cnpj: document.getElementById("estoquePreviewDestinatarioCnpj")?.value || "",
    frete_id: Number(document.getElementById("estoqueXmlFreteSelect")?.value || 0) || 0,
    itens,
  });
}

function _freteImportacaoXmlPorId(freteId){
  return (estoqueState.fretesImportacaoXml || []).find(
    (frete) => Number(frete.id || 0) === Number(freteId || 0)
  ) || null;
}

function _rotuloFreteImportacaoXml(frete){
  if (!frete) return "";
  const nome = _rotuloFreteExibicao(frete);
  const rota = String(frete.carga_rota || frete.carga_cidades || frete.cidade || "").trim();
  const status = _freteStatusLabel(String(frete.status || ""));
  return [nome, rota ? `Rota ${rota}` : "", status].filter(Boolean).join(" | ");
}

function _atualizarHintFreteImportacaoXml(){
  const select = document.getElementById("estoqueXmlFreteSelect");
  const hint = document.getElementById("estoqueXmlFreteHint");
  if (!select || !hint) return;
  const frete = _freteImportacaoXmlPorId(select.value);
  const draft = estoqueState.importDraft || {};
  const transporte = draft.transporte_xml || {};
  const sugestao = draft.frete_sugestao || {};
  if (draft.dispensa_frete) {
    hint.textContent = draft.decisao_logistica?.motivo
      || "A baixa sera confirmada sem vinculo com frete, rota ou veiculo da empresa.";
    return;
  }
  const identificadores = [
    transporte.numero_caminhao ? `caminhao ${transporte.numero_caminhao}` : "",
    transporte.placa ? `placa ${transporte.placa}` : "",
    transporte.mapa ? `mapa ${transporte.mapa}` : "",
  ].filter(Boolean).join(" | ");
  if (frete) {
    const automatico = Number(frete.id || 0) === Number(sugestao.frete_id || 0);
    const origem = automatico
      ? `Sugestao automatica${sugestao.confianca ? ` (${sugestao.confianca})` : ""}`
      : "Vinculo alterado manualmente";
    hint.textContent = [
      identificadores ? `XML: ${identificadores}` : "",
      `${origem}: ${_rotuloFreteImportacaoXml(frete)}`,
      automatico ? sugestao.motivo : "",
    ].filter(Boolean).join(". ");
    return;
  }
  hint.textContent = [
    identificadores ? `XML: ${identificadores}` : "",
    sugestao.motivo || "Selecione um frete ativo antes de confirmar a saida.",
  ].filter(Boolean).join(". ");
}

function selecionarFreteImportacaoXml(){
  if (!estoqueState.importDraft) return;
  const select = document.getElementById("estoqueXmlFreteSelect");
  estoqueState.importDraft.frete_id = Number(select?.value || 0) || 0;
  estoqueState.importDraftDirty = true;
  _atualizarHintFreteImportacaoXml();
}

async function alterarDispensaFreteImportacaoXml(){
  const checkbox = document.getElementById("estoqueXmlDispensaFrete");
  const draftAtual = _coletarDraftImportacaoEstoqueForm();
  if (!checkbox || !draftAtual?.importar_xml_chave) return;
  const dispensaFrete = !!checkbox.checked;
  const mensagem = dispensaFrete
    ? "Confirmar que o transporte desta saida foi realizado pelo cliente? O card automatico ainda nao utilizado sera arquivado."
    : "Confirmar que esta saida exige frete da empresa? O sistema preparara um card para vinculacao.";
  if (!confirm(mensagem)) {
    checkbox.checked = !dispensaFrete;
    return;
  }
  checkbox.disabled = true;
  try {
    const resp = await apiFetch("/api/estoque/importacoes-xml/logistica", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chave: draftAtual.importar_xml_chave,
        dispensa_frete: dispensaFrete,
      }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data?.erro || "Falha ao alterar a logistica da nota.");
    const atualizado = _normalizarDraftImportacaoEstoque(data.preview || {});
    estoqueState.importDraft = _normalizarDraftImportacaoEstoque({
      ...atualizado,
      numero_nota: draftAtual.numero_nota,
      serie: draftAtual.serie,
      chave_acesso: draftAtual.chave_acesso,
      data_emissao: draftAtual.data_emissao,
      emitente_nome: draftAtual.emitente_nome,
      emitente_cnpj: draftAtual.emitente_cnpj,
      destinatario_nome: draftAtual.destinatario_nome,
      destinatario_cnpj: draftAtual.destinatario_cnpj,
      itens: draftAtual.itens,
    });
    if (!estoqueState.importDraft.dispensa_frete) {
      await carregarFretesImportacaoXml(true);
    }
    estoqueState.importDraftDirty = true;
    renderEstoqueImportPreview();
    await carregarImportacoesXmlEstoque();
  } catch (err) {
    checkbox.checked = !dispensaFrete;
    alert(err?.message || "Falha ao alterar a logistica da nota.");
  } finally {
    checkbox.disabled = false;
  }
}

async function carregarFretesImportacaoXml(force = false){
  if (!force && Array.isArray(estoqueState.fretesImportacaoXml) && estoqueState.fretesImportacaoXml.length) {
    return estoqueState.fretesImportacaoXml;
  }
  const resp = await apiFetch("/api/estoque/importacoes-xml/fretes");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data?.erro || "Falha ao carregar fretes ativos.");
  }
  estoqueState.fretesImportacaoXml = Array.isArray(data?.fretes) ? data.fretes : [];
  return estoqueState.fretesImportacaoXml;
}

function renderEstoqueImportPreview(){
  const card = document.getElementById("estoqueImportPreviewCard");
  const fonte = document.getElementById("estoqueImportPreviewFonte");
  const status = document.getElementById("estoqueImportPreviewStatus");
  const body = document.getElementById("estoqueImportPreviewItemsBody");
  const fotoPanel = document.getElementById("estoqueManualFotoPanel");
  const fotoImg = document.getElementById("estoqueManualFotoImg");
  const fotoNome = document.getElementById("estoqueManualFotoNome");
  const fretePanel = document.getElementById("estoqueXmlFretePanel");
  const freteSelect = document.getElementById("estoqueXmlFreteSelect");
  const dispensaFreteInput = document.getElementById("estoqueXmlDispensaFrete");
  const freteVinculo = document.getElementById("estoqueXmlFreteVinculo");
  if (!card || !fonte || !status || !body) return;

  const draft = estoqueState.importDraft ? _normalizarDraftImportacaoEstoque(estoqueState.importDraft) : null;
  if (!draft) {
    card.classList.add("hidden");
    body.innerHTML = `<tr><td colspan="10">Nenhum item carregado.</td></tr>`;
    if (fotoPanel) fotoPanel.classList.add("hidden");
    if (fretePanel) fretePanel.classList.add("hidden");
    if (fotoImg) fotoImg.removeAttribute("src");
    if (fotoNome) fotoNome.textContent = "Nenhuma foto carregada.";
    return;
  }

  estoqueState.importDraft = draft;
  card.classList.remove("hidden");
  const movimentoLabel = draft.source_type === "importar_xml"
    ? ` | Movimento reconhecido: ${draft.tipo_movimento === "saida" ? "SAIDA" : "ENTRADA"}`
    : "";
  fonte.textContent = `Arquivo: ${draft.arquivo_origem || "-"} | Origem: ${_nfeImportSourceLabel(draft.source_type)}${draft.preview_tipo === "parcial" ? " (preview parcial)" : ""}${movimentoLabel}`;
  status.textContent = draft.warnings.length
    ? draft.warnings.join(" | ")
    : "Revise os dados abaixo e confirme a importacao quando estiver tudo certo.";
  document.querySelectorAll(".estoque-import-add-btn").forEach((button) => {
    button.classList.toggle("hidden", draft.source_type === "importar_xml");
  });
  const exigeFrete = draft.source_type === "importar_xml" && draft.tipo_movimento === "saida";
  if (fretePanel) fretePanel.classList.toggle("hidden", !exigeFrete);
  if (dispensaFreteInput) dispensaFreteInput.checked = !!draft.dispensa_frete;
  if (freteVinculo) freteVinculo.classList.toggle("hidden", !exigeFrete || draft.dispensa_frete);
  if (freteSelect && exigeFrete && !draft.dispensa_frete) {
    freteSelect.innerHTML = `
      <option value="">Selecione o frete/rota</option>
      ${(estoqueState.fretesImportacaoXml || []).map((frete) => `
        <option value="${Number(frete.id || 0)}">${_escHtml(_rotuloFreteImportacaoXml(frete))}</option>
      `).join("")}
    `;
    freteSelect.value = draft.frete_id ? String(draft.frete_id) : "";
    _atualizarHintFreteImportacaoXml();
  }

  const itens = draft.itens.length ? draft.itens : [_novoItemImportacaoEstoque(1)];
  document.getElementById("estoquePreviewNumeroNota").value = draft.numero_nota || "";
  document.getElementById("estoquePreviewSerie").value = draft.serie || "";
  document.getElementById("estoquePreviewChaveAcesso").value = draft.chave_acesso || "";
  document.getElementById("estoquePreviewDataEmissao").value = draft.data_emissao || "";
  document.getElementById("estoquePreviewEmitenteNome").value = draft.emitente_nome || "";
  document.getElementById("estoquePreviewEmitenteCnpj").value = draft.emitente_cnpj || "";
  document.getElementById("estoquePreviewDestinatarioNome").value = draft.destinatario_nome || "";
  document.getElementById("estoquePreviewDestinatarioCnpj").value = draft.destinatario_cnpj || "";
  if (fotoPanel) fotoPanel.classList.toggle("hidden", !estoqueState.manualPhotoUrl);
  if (fotoImg && estoqueState.manualPhotoUrl) fotoImg.src = estoqueState.manualPhotoUrl;
  if (fotoImg && !estoqueState.manualPhotoUrl) fotoImg.removeAttribute("src");
  if (fotoNome) fotoNome.textContent = estoqueState.manualPhotoName || "Nenhuma foto carregada.";

  body.innerHTML = itens.map((item, idx) => `
    <tr data-item-index="${idx}" data-xml-item-id="${Number(item.xml_item_id || 0)}">
      <td><input type="text" class="estoque-import-item-seq" value="${_escAttr(String(item.item_seq || idx + 1))}" oninput="estoqueState.importDraftDirty = true"></td>
      <td><input type="text" class="estoque-import-item-codnfe" value="${_escAttr(item.codigo_produto_nfe || "")}" oninput="estoqueState.importDraftDirty = true"></td>
      <td><input type="text" class="estoque-import-item-codbar" value="${_escAttr(item.codigo_barras || "")}" oninput="estoqueState.importDraftDirty = true"></td>
      <td>
        <select class="estoque-import-item-nome" onchange="sincronizarProdutoImportacaoEstoque(${idx})">
          ${_optionsProdutosEstoqueImport(item)}
        </select>
      </td>
      <td><input type="text" class="estoque-import-item-und" value="${_escAttr(item.embalagem_tipo || "")}" oninput="atualizarTotaisImportacaoEstoque()" readonly></td>
      <td><input type="number" class="estoque-import-item-qtd" min="0" step="0.001" value="${_escAttr(String(item.quantidade_embalagem ?? item.quantidade ?? ""))}" oninput="atualizarTotaisImportacaoEstoque(); estoqueState.importDraftDirty = true;"></td>
      <td><input type="number" class="estoque-import-item-fator" min="0.001" step="0.001" value="${Number(item.fator_embalagem || 0) > 0 ? _escAttr(String(item.fator_embalagem)) : ""}" placeholder="Informe" title="Unidades de estoque existentes em cada embalagem" oninput="atualizarTotaisImportacaoEstoque()"></td>
      <td>
        <div class="estoque-total-un-cell">
          <span class="estoque-import-item-total-un${item.fator_inferido ? " is-inferred" : ""}" data-value="${_escAttr(String(item.quantidade_unidades ?? 0))}" data-inferred="${item.fator_inferido ? "1" : "0"}">${_escHtml(_estoqueFormatQtd(item.quantidade_unidades ?? 0))}</span>
          ${item.confirmacao_pendente ? `<span class="estoque-pack-hint">${_escHtml(item.fator_inferido ? "inferido" : "confirmar")}</span>` : ""}
        </div>
      </td>
      <td><input type="number" class="estoque-import-item-valor" min="0" step="0.01" value="${_escAttr(String(item.valor_unitario ?? ""))}"></td>
      <td class="estoque-item-action">${draft.source_type === "importar_xml" ? '<span class="hint-chip">Obrigatorio</span>' : `<button type="button" onclick="removerItemImportacaoEstoque(${idx})">Remover</button>`}</td>
    </tr>
  `).join("");
  atualizarTotaisImportacaoEstoque(false);
}

function atualizarTotaisImportacaoEstoque(markDirty = true){
  document.querySelectorAll("#estoqueImportPreviewItemsBody tr[data-item-index]").forEach((row) => {
    const select = row.querySelector(".estoque-import-item-nome");
    const selected = select?.selectedOptions?.[0];
    const codBarEl = row.querySelector(".estoque-import-item-codbar");
    const codNfeEl = row.querySelector(".estoque-import-item-codnfe");
    const undEl = row.querySelector(".estoque-import-item-und");
    const qtdEl = row.querySelector(".estoque-import-item-qtd");
    const fatorEl = row.querySelector(".estoque-import-item-fator");
    const totalEl = row.querySelector(".estoque-import-item-total-un");
    if (!totalEl) return;
    const item = _enriquecerItemImportacaoEstoque({
      produto_id: selected?.dataset.produtoId || "",
      codigo_barras: codBarEl?.value || "",
      codigo_produto_nfe: codNfeEl?.value || "",
      nome_produto: selected?.dataset.nome || select?.value || "",
      grupo_estoque: selected?.dataset.grupo || "",
      produto_base_nome: selected?.dataset.base || "",
      unidade: undEl?.value || "",
      embalagem_tipo: undEl?.value || "",
      quantidade: qtdEl?.value || "",
      quantidade_embalagem: qtdEl?.value || "",
      fator_embalagem: fatorEl?.value || "",
      fator_inferido: totalEl?.dataset.inferred === "1",
    });
    if (fatorEl && (!String(fatorEl.value || "").trim() || Number(fatorEl.value || 0) <= 0)) {
      fatorEl.value = Number(item.fator_embalagem || 0) > 0 ? String(item.fator_embalagem) : "";
    }
    totalEl.dataset.value = String(item.quantidade_unidades || 0);
    totalEl.dataset.inferred = item.fator_inferido ? "1" : "0";
    totalEl.classList.toggle("is-inferred", !!item.fator_inferido);
    totalEl.textContent = _estoqueFormatQtd(item.quantidade_unidades || 0);
    const cell = totalEl.closest(".estoque-total-un-cell");
    if (cell) {
      let hint = cell.querySelector(".estoque-pack-hint");
      if (item.confirmacao_pendente) {
        if (!hint) {
          hint = document.createElement("span");
          hint.className = "estoque-pack-hint";
          cell.appendChild(hint);
        }
        hint.textContent = item.fator_inferido ? "inferido" : "confirmar";
      } else if (hint) {
        hint.remove();
      }
    }
  });
  if (markDirty) estoqueState.importDraftDirty = true;
}

function adicionarItemImportacaoEstoque(){
  const draftAtual = _coletarDraftImportacaoEstoqueForm() || _normalizarDraftImportacaoEstoque(estoqueState.importDraft || {});
  if (draftAtual.source_type === "importar_xml") {
    alert("A revisao do Importar XML deve manter exatamente os itens reconhecidos na NF-e.");
    return;
  }
  const itens = Array.isArray(draftAtual.itens) ? [...draftAtual.itens] : [];
  itens.push(_novoItemImportacaoEstoque(itens.length + 1));
  estoqueState.importDraft = { ...draftAtual, itens };
  estoqueState.importDraftDirty = true;
  renderEstoqueImportPreview();
}

function removerItemImportacaoEstoque(index){
  const draftAtual = _coletarDraftImportacaoEstoqueForm();
  if (!draftAtual) return;
  if (draftAtual.source_type === "importar_xml") {
    alert("Itens reconhecidos pelo Importar XML nao podem ser removidos. Cancele a revisao se nao quiser confirmar esta nota.");
    return;
  }
  const itens = (draftAtual.itens || []).filter((_, idx) => idx !== Number(index));
  estoqueState.importDraft = { ...draftAtual, itens };
  estoqueState.importDraftDirty = true;
  renderEstoqueImportPreview();
}

function renderImportacoesXmlEstoque(){
  const body = document.getElementById("estoqueXmlPendentesBody");
  const resumo = document.getElementById("estoqueXmlPendentesResumo");
  if (!body || !resumo) return;
  const tipo = String(document.getElementById("estoqueXmlPendentesTipo")?.value || "");
  const rows = (estoqueState.importacoesXml || []).filter((row) => !tipo || row.tipo_movimento === tipo);
  const chavesDisponiveis = new Set(
    (estoqueState.importacoesXml || []).map((row) => String(row.nota_key || "")).filter(Boolean)
  );
  estoqueState.importacoesXmlSelecionadas = (estoqueState.importacoesXmlSelecionadas || []).filter(
    (chave) => chavesDisponiveis.has(String(chave))
  );
  const selecionadas = new Set(estoqueState.importacoesXmlSelecionadas || []);
  const entradas = rows.filter((row) => row.tipo_movimento === "entrada").length;
  const saidas = rows.filter((row) => row.tipo_movimento === "saida").length;
  const itens = rows.reduce((total, row) => total + Number(row.itens_pendentes || 0), 0);
  resumo.textContent = `${rows.length} nota(s) pendente(s): ${entradas} entrada(s), ${saidas} saida(s), ${itens} item(ns). ${selecionadas.size} selecionada(s).`;
  body.innerHTML = rows.length ? rows.map((row) => {
    const duplicatas = Math.max(0, Number(row.arquivos_repetidos || 0) - 1);
    const fluxo = [row.emitente_nome, row.destinatario_nome].filter(Boolean).join(" -> ") || "-";
    const notaKey = String(row.nota_key || "");
    const selecionada = selecionadas.has(notaKey);
    return `
      <tr class="${selecionada ? "is-selected" : ""}">
        <td class="estoque-xml-selecao-col">
          <input type="checkbox" class="estoque-xml-selecao" aria-label="Selecionar nota ${_escAttr(row.numero_nota || notaKey)}" ${selecionada ? "checked" : ""} onchange="selecionarImportacaoXmlEstoque('${_escJsString(notaKey)}', this.checked)">
        </td>
        <td>${_escHtml(_fmtDateBr(row.data_emissao) || row.data_emissao || "-")}</td>
        <td>${_escHtml(row.numero_nota || row.chave_nfe || "-")}</td>
        <td><span class="estoque-movimento-badge is-${row.tipo_movimento === "saida" ? "saida" : "entrada"}">${row.tipo_movimento === "saida" ? "SAIDA" : "ENTRADA"}</span></td>
        <td>${_escHtml(fluxo)}</td>
        <td>${_escHtml(String(row.itens_pendentes || 0))}</td>
        <td>${_escHtml(String(duplicatas))}</td>
        <td><button type="button" onclick="abrirImportacaoXmlEstoque('${_escJsString(notaKey)}')">Abrir</button></td>
      </tr>
    `;
  }).join("") : `<tr><td colspan="8">Nenhuma importacao XML pendente para este filtro.</td></tr>`;
  _atualizarControlesLoteImportacoesXml(rows);
}

function _atualizarControlesLoteImportacoesXml(rowsVisiveis = null){
  const tipo = String(document.getElementById("estoqueXmlPendentesTipo")?.value || "");
  const rows = Array.isArray(rowsVisiveis)
    ? rowsVisiveis
    : (estoqueState.importacoesXml || []).filter((row) => !tipo || row.tipo_movimento === tipo);
  const selecionadas = new Set(estoqueState.importacoesXmlSelecionadas || []);
  const visiveisSelecionadas = rows.filter((row) => selecionadas.has(String(row.nota_key || ""))).length;
  const selecionarTodas = document.getElementById("estoqueXmlSelecionarTodas");
  if (selecionarTodas) {
    selecionarTodas.checked = rows.length > 0 && visiveisSelecionadas === rows.length;
    selecionarTodas.indeterminate = visiveisSelecionadas > 0 && visiveisSelecionadas < rows.length;
    selecionarTodas.disabled = !rows.length || estoqueState.importacoesXmlLoteExecutando;
  }
  const botao = document.getElementById("estoqueXmlImportarLoteBtn");
  if (botao) {
    const progresso = estoqueState.importacoesXmlLoteProgresso || {};
    botao.textContent = estoqueState.importacoesXmlLoteExecutando
      ? `Importando lote ${Number(progresso.loteAtual || 1)}/${Number(progresso.totalLotes || 1)}`
      : `Importar selecionadas (${selecionadas.size})`;
    botao.disabled = !selecionadas.size || estoqueState.importacoesXmlLoteExecutando;
  }
}

function _dividirImportacoesXmlEmLotes(chaves, tamanhoLote){
  const tamanho = Math.max(1, Number(tamanhoLote || 500));
  const lotes = [];
  for (let inicio = 0; inicio < chaves.length; inicio += tamanho) {
    lotes.push(chaves.slice(inicio, inicio + tamanho));
  }
  return lotes;
}

function _atualizarProgressoLoteImportacoesXml({
  fase = "importando",
  loteAtual = 1,
  totalLotes = 1,
  processadas = 0,
  total = 0,
  tamanhoLote = 0,
  mensagem = "",
} = {}){
  const painel = document.getElementById("estoqueXmlLoteProgresso");
  const texto = document.getElementById("estoqueXmlLoteProgressoTexto");
  const fill = document.getElementById("estoqueXmlLoteProgressoFill");
  const barra = painel?.querySelector('[role="progressbar"]');
  const percentual = total > 0
    ? Math.max(0, Math.min(100, Math.round((Number(processadas || 0) / total) * 100)))
    : 0;
  estoqueState.importacoesXmlLoteProgresso = {
    fase,
    loteAtual,
    totalLotes,
    processadas,
    total,
    tamanhoLote,
    percentual,
  };
  if (painel) painel.classList.remove("hidden");
  if (texto) {
    texto.textContent = mensagem || (
      `${fase === "preparando" ? "Preparando" : "Importando"} `
      + `${processadas} / ${total} notas - lote ${loteAtual} de ${totalLotes}`
      + `${tamanhoLote ? ` (${tamanhoLote} notas neste lote)` : ""}`
    );
  }
  if (fill) fill.style.width = `${percentual}%`;
  if (barra) barra.setAttribute("aria-valuenow", String(percentual));
  _atualizarControlesLoteImportacoesXml();
}

function selecionarImportacaoXmlEstoque(notaKey, selecionada){
  const chaves = new Set(estoqueState.importacoesXmlSelecionadas || []);
  if (selecionada) chaves.add(String(notaKey || ""));
  else chaves.delete(String(notaKey || ""));
  chaves.delete("");
  estoqueState.importacoesXmlSelecionadas = Array.from(chaves);
  renderImportacoesXmlEstoque();
}

function selecionarTodasImportacoesXmlEstoque(selecionar){
  const tipo = String(document.getElementById("estoqueXmlPendentesTipo")?.value || "");
  const rows = (estoqueState.importacoesXml || []).filter((row) => !tipo || row.tipo_movimento === tipo);
  const chaves = new Set(estoqueState.importacoesXmlSelecionadas || []);
  rows.forEach((row) => {
    const chave = String(row.nota_key || "");
    if (!chave) return;
    if (selecionar) chaves.add(chave);
    else chaves.delete(chave);
  });
  estoqueState.importacoesXmlSelecionadas = Array.from(chaves);
  renderImportacoesXmlEstoque();
}

async function carregarImportacoesXmlEstoque(){
  const body = document.getElementById("estoqueXmlPendentesBody");
  if (body) body.innerHTML = `<tr><td colspan="8">Carregando importacoes XML...</td></tr>`;
  const resp = await apiFetch("/api/estoque/importacoes-xml?status=pendente");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (body) body.innerHTML = `<tr><td colspan="8">${_escHtml(data?.erro || "Falha ao carregar importacoes XML.")}</td></tr>`;
    return;
  }
  estoqueState.importacoesXml = Array.isArray(data?.rows) ? data.rows : [];
  estoqueState.importacoesXmlMeta = data?.meta || {};
  renderImportacoesXmlEstoque();
}

async function importarSelecionadasXmlEstoque(){
  if (estoqueState.importacoesXmlLoteExecutando) return;
  const chaves = Array.from(new Set(estoqueState.importacoesXmlSelecionadas || [])).filter(Boolean);
  if (!chaves.length) {
    alert("Selecione ao menos uma NF-e para importar.");
    return;
  }
  if (estoqueState.importDraftDirty) {
    if (!confirm("Existe uma nota aberta com alteracoes em revisao. Deseja manter o lote e descartar essa revisao?")) {
      return;
    }
    estoqueState.importDraft = null;
    estoqueState.importDraftDirty = false;
    renderEstoqueImportPreview();
  }

  estoqueState.importacoesXmlLoteExecutando = true;
  const tamanhoLote = Math.max(1, Number(estoqueState.importacoesXmlMeta?.lote_maximo || 500));
  const lotesChaves = _dividirImportacoesXmlEmLotes(chaves, tamanhoLote);
  const totalLotes = lotesChaves.length;
  _atualizarControlesLoteImportacoesXml();
  const resumoEl = document.getElementById("estoqueXmlPendentesResumo");
  _atualizarProgressoLoteImportacoesXml({
    fase: "preparando",
    loteAtual: 1,
    totalLotes,
    processadas: 0,
    total: chaves.length,
    tamanhoLote: lotesChaves[0]?.length || 0,
  });
  if (resumoEl) {
    resumoEl.textContent = `Preparando ${chaves.length} nota(s) em ${totalLotes} lote(s) de ate ${tamanhoLote}.`;
  }
  try {
    try { await ensureProdutosEstoqueCache(); } catch {}
    const lotesPreparados = [];
    const errosPreparo = [];
    let preparadas = 0;
    for (let loteIndex = 0; loteIndex < lotesChaves.length; loteIndex += 1) {
      const chavesLote = lotesChaves[loteIndex];
      _atualizarProgressoLoteImportacoesXml({
        fase: "preparando",
        loteAtual: loteIndex + 1,
        totalLotes,
        processadas: preparadas,
        total: chaves.length,
        tamanhoLote: chavesLote.length,
      });
      const respPreparo = await apiFetch("/api/estoque/importacoes-xml/lote/preparar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chaves: chavesLote }),
      });
      const dataPreparo = await respPreparo.json().catch(() => ({}));
      if (!respPreparo.ok) {
        throw new Error(
          dataPreparo?.erro
          || `Falha ao preparar o lote ${loteIndex + 1} de ${totalLotes}.`
        );
      }
      (Array.isArray(dataPreparo?.erros) ? dataPreparo.erros : []).forEach((item) => {
        errosPreparo.push({ ...item, lote: loteIndex + 1 });
      });
      lotesPreparados.push(
        (dataPreparo?.previews || []).map((preview) => {
          const draft = _normalizarDraftImportacaoEstoque(preview);
          draft.itens = draft.itens.map((item) => _enriquecerItemImportacaoEstoque({
            ...item,
            quantidade_unidades: 0,
          }));
          return draft;
        })
      );
      preparadas += chavesLote.length;
      _atualizarProgressoLoteImportacoesXml({
        fase: "preparando",
        loteAtual: loteIndex + 1,
        totalLotes,
        processadas: preparadas,
        total: chaves.length,
        tamanhoLote: chavesLote.length,
      });
    }
    if (errosPreparo.length) {
      const detalhes = errosPreparo.slice(0, 12).map(
        (item) => `- Lote ${item.lote}: ${item.numero_nota || item.chave || "-"}: ${item.erro}`
      ).join("\n");
      const restante = errosPreparo.length > 12 ? `\n... e mais ${errosPreparo.length - 12} nota(s).` : "";
      _atualizarProgressoLoteImportacoesXml({
        ...(estoqueState.importacoesXmlLoteProgresso || {}),
        fase: "pendente",
        mensagem: (
          `Importacao nao iniciada: ${errosPreparo.length} nota(s) precisam `
          + "de revisao antes de processar os lotes."
        ),
      });
      alert(`O lote nao foi iniciado porque existem notas que precisam ser revisadas:\n${detalhes}${restante}`);
      return;
    }

    const drafts = lotesPreparados.flat();
    const bloqueios = [];
    let totalItens = 0;
    const conversoesParaConfirmar = [];
    drafts.forEach((draft) => {
      totalItens += draft.itens.length;
      const semFator = draft.itens.filter((item) => !(Number(item.fator_embalagem || 0) > 0));
      draft.itens.filter((item) => item.confirmacao_pendente).forEach((item) => {
        conversoesParaConfirmar.push({
          nota: draft.numero_nota || draft.chave_acesso || "-",
          item,
        });
      });
      if (!draft.itens.length) bloqueios.push(`${draft.numero_nota || draft.chave_acesso}: sem itens pendentes`);
      if (semFator.length) bloqueios.push(`${draft.numero_nota || draft.chave_acesso}: ${semFator.length} item(ns) sem fator de conversao`);
      if (draft.tipo_movimento === "saida" && !draft.dispensa_frete && !(Number(draft.frete_id || 0) > 0)) {
        bloqueios.push(`${draft.numero_nota || draft.chave_acesso}: saida sem frete/rota definido`);
      }
    });
    if (bloqueios.length) {
      _atualizarProgressoLoteImportacoesXml({
        ...(estoqueState.importacoesXmlLoteProgresso || {}),
        fase: "pendente",
        mensagem: (
          `Importacao nao iniciada: ${bloqueios.length} nota(s) precisam `
          + "de revisao de produto, conversao ou frete."
        ),
      });
      alert(`O lote nao foi iniciado. Abra e revise estas notas:\n- ${bloqueios.slice(0, 12).join("\n- ")}`);
      return;
    }
    if (!drafts.length) {
      _atualizarProgressoLoteImportacoesXml({
        ...(estoqueState.importacoesXmlLoteProgresso || {}),
        fase: "pendente",
        mensagem: "Nenhuma nota selecionada esta pronta para importacao.",
      });
      alert("Nenhuma nota selecionada esta pronta para importacao.");
      return;
    }

    const entradas = drafts.filter((draft) => draft.tipo_movimento === "entrada").length;
    const saidas = drafts.length - entradas;
    const detalhesConversao = conversoesParaConfirmar.slice(0, 8).map(({ nota, item }) => (
      `- NF-e ${nota}: ${_estoqueConfirmacaoLancamentoTexto(item).replace(/\n/g, " | ")}`
    )).join("\n");
    const restanteConversao = conversoesParaConfirmar.length > 8
      ? `\n... e mais ${conversoesParaConfirmar.length - 8} item(ns).`
      : "";
    const avisoConversao = conversoesParaConfirmar.length
      ? `\n${conversoesParaConfirmar.length} item(ns) usam conversao inferida ou cadastro ainda nao explicitado:\n${detalhesConversao}${restanteConversao}`
      : "";
    if (!confirm(
      `Confirmar importacao em massa de ${drafts.length} NF-e(s)?\n`
      + `${entradas} entrada(s), ${saidas} saida(s), ${totalItens} item(ns).`
      + `${avisoConversao}\nCada nota sera protegida contra duplicidade antes de contabilizar o saldo.`
    )) {
      _atualizarProgressoLoteImportacoesXml({
        fase: "cancelado",
        loteAtual: 1,
        totalLotes,
        processadas: 0,
        total: drafts.length,
        tamanhoLote: lotesPreparados[0]?.length || 0,
        mensagem: `Importacao cancelada antes de processar ${drafts.length} nota(s).`,
      });
      return;
    }

    const sucessos = [];
    const falhas = [];
    let processadas = 0;
    for (let loteIndex = 0; loteIndex < lotesPreparados.length; loteIndex += 1) {
      const draftsLote = lotesPreparados[loteIndex];
      for (const draft of draftsLote) {
        const numeroNota = draft.numero_nota || draft.chave_acesso || "-";
        _atualizarProgressoLoteImportacoesXml({
          fase: "importando",
          loteAtual: loteIndex + 1,
          totalLotes,
          processadas,
          total: drafts.length,
          tamanhoLote: draftsLote.length,
          mensagem: (
            `Importando ${processadas + 1} / ${drafts.length} notas - `
            + `lote ${loteIndex + 1} de ${totalLotes} `
            + `(${draftsLote.length} notas neste lote) - NF-e ${numeroNota}`
          ),
        });
        if (resumoEl) {
          resumoEl.textContent = (
            `Importando ${processadas + 1} de ${drafts.length}: `
            + `lote ${loteIndex + 1} de ${totalLotes}, NF-e ${numeroNota}`
          );
        }
        const itens = draft.itens.map((item) => {
          const normalizado = _enriquecerItemImportacaoEstoque(item);
          return {
            xml_item_id: Number(normalizado.xml_item_id || 0),
            produto_id: Number(normalizado.produto_id || 0),
            codigo_barras: normalizado.codigo_barras || "",
            quantidade: Number(normalizado.quantidade_unidades || normalizado.quantidade || 0),
            valor_unitario: Number(normalizado.valor_unitario || 0),
            embalagem_tipo: normalizado.embalagem_tipo || normalizado.unidade || "",
            fator_embalagem: Number(normalizado.fator_embalagem || 0),
            grupo_estoque: normalizado.grupo_estoque || "",
            produto_base_nome: normalizado.produto_base_nome || "",
          };
        });
        try {
          const resp = await apiFetch("/api/estoque/importacoes-xml/confirmar", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              chave: draft.importar_xml_chave || draft.chave_acesso,
              frete_id: Number(draft.frete_id || 0) || null,
              itens,
            }),
          });
          const data = await resp.json().catch(() => ({}));
          if (!resp.ok) throw new Error(data?.erro || "Falha ao confirmar a nota.");
          sucessos.push({
            chave: draft.importar_xml_chave,
            numero_nota: draft.numero_nota,
            movimentos: Number(data?.movimentos_criados || 0),
          });
        } catch (err) {
          falhas.push({
            chave: draft.importar_xml_chave,
            numero_nota: draft.numero_nota,
            erro: err?.message || "Falha desconhecida.",
          });
        }
        processadas += 1;
        _atualizarProgressoLoteImportacoesXml({
          fase: "importando",
          loteAtual: loteIndex + 1,
          totalLotes,
          processadas,
          total: drafts.length,
          tamanhoLote: draftsLote.length,
        });
      }
    }

    const chavesComSucesso = new Set(sucessos.map((item) => String(item.chave || "")));
    estoqueState.importacoesXmlSelecionadas = chaves.filter((chave) => !chavesComSucesso.has(String(chave)));
    estoqueState.importDraft = null;
    estoqueState.importDraftDirty = false;
    renderEstoqueImportPreview();
    await carregarEstoque();
    await carregarImportacoesXmlEstoque();
    const movimentos = sucessos.reduce((total, item) => total + item.movimentos, 0);
    const mensagemFalhas = falhas.length
      ? `\n${falhas.length} nota(s) ficaram pendentes:\n${falhas.slice(0, 10).map((item) => `- ${item.numero_nota || item.chave}: ${item.erro}`).join("\n")}`
      : "";
    _atualizarProgressoLoteImportacoesXml({
      fase: "concluido",
      loteAtual: totalLotes,
      totalLotes,
      processadas: drafts.length,
      total: drafts.length,
      mensagem: (
        `Importacao concluida: ${sucessos.length} de ${drafts.length} nota(s) importada(s) `
        + `em ${totalLotes} lote(s). ${falhas.length} pendente(s).`
      ),
    });
    alert(`${sucessos.length} nota(s) importada(s), com ${movimentos} movimento(s) contabilizado(s).${mensagemFalhas}`);
  } catch (err) {
    _atualizarProgressoLoteImportacoesXml({
      ...(estoqueState.importacoesXmlLoteProgresso || {}),
      fase: "erro",
      mensagem: `Importacao interrompida: ${err?.message || "falha desconhecida."}`,
    });
    alert(err?.message || "Falha ao executar a importacao em massa.");
  } finally {
    estoqueState.importacoesXmlLoteExecutando = false;
    _atualizarControlesLoteImportacoesXml();
    renderImportacoesXmlEstoque();
  }
}

async function abrirImportacaoXmlEstoque(notaKey){
  if (!notaKey) return;
  if (estoqueState.importDraftDirty && !confirm("Existe outra importacao com alteracoes em revisao. Deseja descarta-la e abrir esta nota?")) {
    return;
  }
  const resumo = document.getElementById("estoqueXmlPendentesResumo");
  if (resumo) resumo.textContent = "Abrindo importacao XML para revisao...";
  try { await ensureProdutosEstoqueCache(); } catch {}
  const resp = await apiFetch(`/api/estoque/importacoes-xml/detalhe?chave=${encodeURIComponent(notaKey)}`);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    alert(data?.erro || "Falha ao abrir a importacao XML.");
    await carregarImportacoesXmlEstoque();
    return;
  }
  estoqueState.importDraft = _normalizarDraftImportacaoEstoque(data.preview || {});
  if (estoqueState.importDraft.tipo_movimento === "saida" && !estoqueState.importDraft.dispensa_frete) {
    try {
      await carregarFretesImportacaoXml(true);
    } catch (err) {
      alert(err?.message || "Falha ao carregar os fretes ativos.");
    }
  }
  estoqueState.importDraftDirty = false;
  setEstoqueView("lancar");
  renderEstoqueImportPreview();
  document.getElementById("estoqueImportPreviewCard")?.scrollIntoView({ behavior: "smooth", block: "start" });
  renderImportacoesXmlEstoque();
}

function cancelarImportacaoNfeEstoque(){
  estoqueState.importDraft = null;
  estoqueState.importDraftDirty = false;
  estoqueState.lastPortalPreviewSignature = "";
  _revogarFotoManualItensEstoque();
  renderEstoqueImportPreview();
  const input = document.getElementById("estoqueNfeArquivo");
  if (input) input.value = "";
  const status = document.getElementById("estoqueNfeImportStatus");
  if (status) status.textContent = "Importacao cancelada. Selecione outro XML ou PDF para abrir uma nova confirmacao.";
}

async function confirmarImportacaoNfeEstoque(){
  const draftBruto = _coletarDraftImportacaoEstoqueForm();
  const draft = draftBruto ? _normalizarDraftImportacaoEstoque({
    ...draftBruto,
    itens: (draftBruto.itens || []).map((item) => {
      const norm = _enriquecerItemImportacaoEstoque(item);
      return {
        ...norm,
        unidade: norm.embalagem_tipo || norm.unidade || "UN",
        quantidade_embalagem: norm.quantidade_embalagem,
        fator_embalagem: norm.fator_embalagem,
        fator_inferido: norm.fator_inferido,
        quantidade_unidades: norm.quantidade_unidades,
        quantidade: norm.quantidade_unidades,
      };
    }),
  }) : null;
  if (!draft) {
    alert("Nenhuma NF-e em revisao.");
    return;
  }
  const itensInvalidos = (draft.itens || []).filter((item) => !(Number(item.fator_embalagem || 0) > 0));
  if (itensInvalidos.length) {
    alert(`Existem ${itensInvalidos.length} item(ns) sem fator de conversao valido. Revise o cadastro ou a embalagem antes de lancar a NF-e.`);
    return;
  }
  const itensPendentes = (draft.itens || []).filter((item) => item.confirmacao_pendente);
  if (itensPendentes.length) {
    const resumo = itensPendentes.slice(0, 4).map((item) => `- ${_estoqueConfirmacaoLancamentoTexto(item).replace(/\n/g, " | ")}`).join("\n");
    const restante = itensPendentes.length > 4 ? `\n... e mais ${itensPendentes.length - 4} item(ns).` : "";
    if (!confirm(`Ha itens com conversao inferida ou cadastro ainda nao explicitado.\nConfirme antes de lancar:\n${resumo}${restante}`)) {
      return;
    }
  }

  const status = document.getElementById("estoqueImportPreviewStatus");
  if (draft.source_type === "importar_xml") {
    const tipoLabel = draft.tipo_movimento === "saida" ? "SAIDA" : "ENTRADA";
    const freteSelecionado = draft.tipo_movimento === "saida" && !draft.dispensa_frete
      ? _freteImportacaoXmlPorId(draft.frete_id)
      : null;
    if (draft.tipo_movimento === "saida" && !draft.dispensa_frete && !freteSelecionado) {
      alert("Selecione o frete/rota da nota de saida antes de confirmar.");
      document.getElementById("estoqueXmlFreteSelect")?.focus();
      return;
    }
    const vinculoTexto = freteSelecionado
      ? `\nFrete/rota: ${_rotuloFreteImportacaoXml(freteSelecionado)}`
      : (draft.dispensa_frete ? "\nLogistica: retirada/transporte pelo cliente, sem frete da empresa." : "");
    if (!confirm(`Confirmar ${tipoLabel} da nota ${draft.numero_nota || draft.chave_acesso || "-"} com ${draft.itens.length} item(ns)?${vinculoTexto}\nO saldo e o vinculo serao registrados somente agora.`)) {
      return;
    }
    if (status) status.textContent = `Confirmando ${tipoLabel.toLowerCase()} reconhecida pelo Importar XML...`;
    const respXml = await apiFetch("/api/estoque/importacoes-xml/confirmar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chave: draft.importar_xml_chave || draft.chave_acesso,
        frete_id: Number(draft.frete_id || 0) || null,
        itens: (draft.itens || []).map((item) => ({
          xml_item_id: Number(item.xml_item_id || 0),
          produto_id: Number(item.produto_id || 0),
          codigo_barras: item.codigo_barras || "",
          quantidade: Number(item.quantidade || 0),
          valor_unitario: Number(item.valor_unitario || 0),
          embalagem_tipo: item.embalagem_tipo || item.unidade || "",
          fator_embalagem: Number(item.fator_embalagem || 0),
          grupo_estoque: item.grupo_estoque || "",
          produto_base_nome: item.produto_base_nome || "",
        })),
      }),
    });
    const dataXml = await respXml.json().catch(() => ({}));
    if (!respXml.ok) {
      if (status) status.textContent = dataXml?.erro || "Falha ao confirmar a importacao XML.";
      alert(dataXml?.erro || "Falha ao confirmar a importacao XML.");
      return;
    }

    estoqueState.importDraft = null;
    estoqueState.importDraftDirty = false;
    renderEstoqueImportPreview();
    const statusLancar = document.getElementById("estoqueNfeImportStatus");
    if (statusLancar) {
      const freteInfo = dataXml?.frete
        ? ` Vinculada ao frete ${dataXml.frete.nome || `#${dataXml.frete.id}`}${dataXml.frete.rota ? `, rota ${dataXml.frete.rota}` : ""}.`
        : (dataXml?.retirada_cliente ? " Transporte registrado como realizado pelo cliente, sem frete da empresa." : "");
      statusLancar.textContent = `${tipoLabel} confirmada: ${dataXml.movimentos_criados || 0} movimento(s) contabilizado(s), sem duplicar os dados do XML.${freteInfo}`;
    }
    await carregarEstoque();
    setEstoqueView("posicao");
    if (window.__dashView === "estoque") await renderDashboardEstoque();
    return;
  }

  if (status) status.textContent = "Confirmando importacao da NF-e...";
  const respImport = await apiFetch("/api/estoque/nfe/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      preview: draft,
      chave_acesso_esperada: _digitsOnly(document.getElementById("estoqueChaveAcesso")?.value || ""),
    }),
  });
  const dataImport = await respImport.json().catch(() => ({}));
  if (!respImport.ok) {
    if (status) status.textContent = dataImport?.erro || "Falha ao confirmar a importacao da NF-e.";
    alert(dataImport?.erro || "Falha ao confirmar a importacao da NF-e.");
    return;
  }

  const conferenciaId = Number(dataImport?.conferencia?.id || 0);
  if (status) status.textContent = "Lancando itens da NF-e no estoque...";
  const respConfirm = conferenciaId > 0 ? await apiFetch(`/api/estoque/conferencias/${conferenciaId}/confirmar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      origem_setor: "Fabrica",
      destino_setor: "Almoxarifado",
      itens: [],
    }),
  }) : null;
  const dataConfirm = respConfirm ? await respConfirm.json().catch(() => ({})) : {};
  if (respConfirm && !respConfirm.ok) {
    if (status) status.textContent = dataConfirm?.erro || "A NF-e foi importada, mas a consolidacao automatica falhou.";
    alert(dataConfirm?.erro || "A NF-e foi importada, mas a consolidacao automatica falhou.");
    return;
  }

  estoqueState.importDraft = null;
  estoqueState.importDraftDirty = false;
  estoqueState.lastPortalPreviewSignature = "";
  _revogarFotoManualItensEstoque();
  renderEstoqueImportPreview();
  const input = document.getElementById("estoqueNfeArquivo");
  const campoChave = document.getElementById("estoqueChaveAcesso");
  const statusLancar = document.getElementById("estoqueNfeImportStatus");
  if (input) input.value = "";
  if (campoChave) campoChave.value = "";
  if (statusLancar) {
    statusLancar.textContent = `NF-e lancada no estoque com sucesso. ${dataImport?.produtos_criados || 0} item(ns) cadastrados automaticamente.`;
  }

  await carregarEstoque();
  setEstoqueView("posicao");
  if (window.__dashView === "estoque") await renderDashboardEstoque();
}

function setEstoqueView(view){
  const nextView = view === "posicao"
    ? "posicao"
    : (view === "cadastrar" ? "cadastrar" : (view === "rastreio" ? "rastreio" : "lancar"));
  estoqueState.view = nextView;
  window.__estoqueView = nextView;

  const viewLancar = document.getElementById("estoqueViewLancar");
  const viewConferir = document.getElementById("estoqueViewConferir");
  const viewCadastrar = document.getElementById("estoqueViewCadastrar");
  const viewRastreio = document.getElementById("estoqueViewRastreio");
  const btnLancar = document.getElementById("estoqueViewBtnLancar");
  const btnConferir = document.getElementById("estoqueViewBtnConferir");
  const btnCadastrar = document.getElementById("estoqueViewBtnCadastrar");
  const btnRastreio = document.getElementById("estoqueViewBtnRastreio");

  if (viewLancar) viewLancar.classList.toggle("hidden", nextView !== "lancar");
  if (viewConferir) viewConferir.classList.toggle("hidden", nextView !== "posicao");
  if (viewCadastrar) viewCadastrar.classList.toggle("hidden", nextView !== "cadastrar");
  if (viewRastreio) viewRastreio.classList.toggle("hidden", nextView !== "rastreio");
  if (btnLancar) btnLancar.classList.toggle("active", nextView === "lancar");
  if (btnConferir) btnConferir.classList.toggle("active", nextView === "posicao");
  if (btnCadastrar) btnCadastrar.classList.toggle("active", nextView === "cadastrar");
  if (btnRastreio) btnRastreio.classList.toggle("active", nextView === "rastreio");

  renderEstoqueImportPreview();
  atualizarStatusCodbarSistema();
  if (nextView === "cadastrar") {
    carregarSaldoEstoque().catch((e) => {
      console.warn("saldo estoque erro:", e);
    });
    carregarProdutosEstoqueCadastro().catch((e) => {
      console.warn("cadastro estoque erro:", e);
    });
  } else if (nextView === "posicao") {
    carregarSaldoEstoque().catch((e) => {
      console.warn("posicao estoque erro:", e);
    });
    carregarMovimentosEstoque().catch((e) => {
      console.warn("movimentos estoque erro:", e);
    });
  } else if (nextView === "rastreio") {
    carregarSaldoEstoque().catch((e) => {
      console.warn("rastreio saldo erro:", e);
    });
    carregarMovimentosEstoque().catch((e) => {
      console.warn("rastreio movimentos erro:", e);
    });
  }
}

function limparProdutoEstoqueCadastro(){
  estoqueState.cadastroProdutoEditId = 0;
  const ids = [
    "estoqueCadastroCodigoBarras",
    "estoqueCadastroCodigoNfe",
    "estoqueCadastroNomeProduto",
    "estoqueCadastroGrupo",
    "estoqueCadastroBaseNome",
    "estoqueCadastroEmbalagem",
    "estoqueCadastroFator",
    "estoqueCadastroAjusteQuantidade",
    "estoqueCadastroAjusteMotivo",
  ];
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  const ajusteBox = document.getElementById("estoqueCadastroAjusteBox");
  const ajusteBtn = document.getElementById("estoqueCadastroAjusteBtn");
  if (ajusteBox) ajusteBox.classList.add("hidden");
  if (ajusteBtn) ajusteBtn.classList.add("hidden");
  const status = document.getElementById("estoqueCadastroStatus");
  if (status) status.textContent = "Cadastre o produto e o fator da embalagem para automatizar a conversao da NF-e. Ao editar, voce pode lancar um ajuste para corrigir a quantidade em estoque.";
}

async function carregarProdutosEstoqueCadastro(){
  const body = document.getElementById("estoqueCadastroProdutosBody");
  if (!body) return;
  try {
    await ensureProdutosEstoqueCache();
  } catch (err) {
    body.innerHTML = `<tr><td colspan="8">Falha ao carregar cadastros.</td></tr>`;
    return;
  }
  body.innerHTML = estoqueState.cadastroProdutos.length ? _estoqueLinhasAgrupadas(estoqueState.cadastroProdutos, (item) => `
    <tr class="estoque-cadastro-row${Number(estoqueState.cadastroProdutoEditId || 0) === Number(item.id || 0) ? " is-editing" : ""}">
      <td>${_escHtml(_estoqueGrupoLabel(item.grupo_estoque))}</td>
      <td>${_escHtml(item.nome_produto || "-")}${item.cadastro_explicitado ? "" : ' <span class="estoque-pack-hint">confirmar</span>'}</td>
      <td>${_escHtml(item.produto_base_nome || "-")}</td>
      <td>${_escHtml(item.codigo_barras || item.codigo_produto_nfe || "-")}</td>
      <td>${_escHtml(_estoqueFormatQtd(_saldoProdutoCadastroAtual(item)))}</td>
      <td>${_escHtml(item.embalagem_tipo_padrao || item.unidade || "UN")}</td>
      <td>${_escHtml(_estoqueFormatQtd(item.fator_embalagem_padrao || 0))}</td>
      <td>
        <button type="button" onclick="editarProdutoEstoqueCadastro(${Number(item.id || 0)})">Editar</button>
        <button type="button" onclick="excluirProdutoEstoqueCadastro(${Number(item.id || 0)})">Excluir</button>
      </td>
    </tr>
  `, 8) : `<tr><td colspan="8">Nenhum produto cadastrado.</td></tr>`;
}

async function ensureProdutosEstoqueCache(force = false){
  if (!force && Array.isArray(estoqueState.cadastroProdutos) && estoqueState.cadastroProdutos.length) {
    renderProdutosLancamentoEstoqueSelect();
    return estoqueState.cadastroProdutos;
  }
  const resp = await apiFetch("/api/estoque/produtos");
  if (!resp.ok) {
    throw new Error("Falha ao carregar produtos do estoque.");
  }
  const dados = await resp.json().catch(() => ([]));
  estoqueState.cadastroProdutos = _estoqueOrdenarPorGrupo(
    Array.isArray(dados) ? dados.map(_estoqueProdutoCadastroNormalizado) : []
  );
  renderProdutosLancamentoEstoqueSelect();
  return estoqueState.cadastroProdutos;
}

function _estoqueCodigoNormalizadoComparacao(valor = ""){
  const texto = String(valor || "").trim().toUpperCase();
  if (!texto) return "";
  if (/^\d+$/.test(texto)) return texto.replace(/^0+/, "") || "0";
  return texto.replace(/\s+/g, "");
}

function _saldoProdutoCadastroAtual(item = {}){
  const codigoBarras = _digitsOnly(item.codigo_barras || "");
  const codigoNfe = _estoqueCodigoNormalizadoComparacao(item.codigo_produto_nfe || "");
  const baseKey = _estoqueProdutoBaseKey(item);
  const nome = String(item.produto_base_nome || item.nome_produto || "").trim().toUpperCase();
  const rows = Array.isArray(estoqueState.posicaoRows) ? estoqueState.posicaoRows : [];
  const encontrado = rows.find((row) => {
    const rowCodigoBarras = _digitsOnly(row.codigo_barras || "");
    const rowCodigoNfe = _estoqueCodigoNormalizadoComparacao(row.codigo_produto_nfe || "");
    const rowNome = String(row.produto_base_nome || row.nome_produto || "").trim().toUpperCase();
    const rowBaseKey = _estoqueProdutoBaseKey(row);
    if (baseKey && rowBaseKey === baseKey) return true;
    return (codigoBarras && rowCodigoBarras === codigoBarras)
      || (codigoNfe && rowCodigoNfe === codigoNfe)
      || (nome && rowNome === nome);
  });
  return Number(encontrado?.quantidade_atual || 0) || 0;
}

function renderProdutosLancamentoEstoqueSelect(){
  const select = document.getElementById("estoqueProdutoSelect");
  if (!select) return;
  const valorAtual = String(select.value || "");
  const opcoes = ['<option value="">Selecione um produto cadastrado</option>'];
  let grupoAtual = "";
  _estoqueOrdenarPorGrupo(estoqueState.cadastroProdutos || [])
    .filter(_estoqueProdutoLancamentoCombinaFiltros)
    .forEach((item) => {
    const grupo = _estoqueGrupoNormalizado(item.grupo_estoque) || "OUTROS";
    if (grupo !== grupoAtual) {
      if (grupoAtual) opcoes.push("</optgroup>");
      grupoAtual = grupo;
      opcoes.push(`<optgroup label="${_escAttr(_estoqueGrupoLabel(grupo))}">`);
    }
    const saldoAtual = _estoqueFormatQtd(_saldoProdutoCadastroAtual(item));
    const embalagem = item.embalagem_tipo_padrao || item.unidade || "UN";
    const rotulo = `${item.produto_base_nome || item.nome_produto || item.codigo_barras || item.codigo_produto_nfe || `Produto ${item.id || ""}`} | ${embalagem} x ${_estoqueFormatQtd(item.fator_embalagem_padrao || 1)} | Saldo ${saldoAtual}`;
    opcoes.push(
      `<option value="${_escAttr(String(item.id || ""))}" data-codbarras="${_escAttr(item.codigo_barras || "")}" data-codnfe="${_escAttr(item.codigo_produto_nfe || "")}" data-nome="${_escAttr(item.nome_produto || "")}" data-base="${_escAttr(item.produto_base_nome || "")}" data-grupo="${_escAttr(item.grupo_estoque || "")}" data-emb="${_escAttr(embalagem)}" data-fator="${_escAttr(String(item.fator_embalagem_padrao || ""))}" data-explicito="${item.cadastro_explicitado ? "1" : "0"}" ${String(item.id || "") === valorAtual ? "selected" : ""}>${_escHtml(rotulo)}</option>`
    );
  });
  if (grupoAtual) opcoes.push("</optgroup>");
  select.innerHTML = opcoes.join("");
}

function _estoqueSetSelectOptions(id, options = [], placeholder = "", multiple = false){
  const el = document.getElementById(id);
  if (!el) return;
  if (String(el.tagName || "").toUpperCase() !== "SELECT") return;
  const selecionados = new Set(_estoqueValoresSelecionados(id));
  const html = [];
  if (!multiple) {
    html.push(`<option value="">${_escHtml(placeholder || "Todos")}</option>`);
  }
  options.forEach((opt) => {
    const value = String(opt.value || "").trim();
    if (!value) return;
    html.push(`<option value="${_escAttr(value)}" ${selecionados.has(value) ? "selected" : ""}>${_escHtml(opt.label || value)}</option>`);
  });
  if (multiple && !options.length) {
    html.push(`<option value="" disabled>Sem opcoes</option>`);
  }
  el.innerHTML = html.join("");
  if (!multiple && selecionados.size && !options.some((opt) => selecionados.has(String(opt.value || "")))) {
    el.value = "";
  }
}

function renderFiltrosEstoque(){
  const meta = estoqueState.posicaoMeta || {};
  const fornecedoresMap = new Map();
  const categorias = new Set(Array.isArray(meta.categorias_fornecedor) ? meta.categorias_fornecedor : []);
  (Array.isArray(meta.fornecedores) ? meta.fornecedores : []).forEach((fornecedor) => {
    const key = _estoqueFornecedorKey(fornecedor);
    if (!key) return;
    fornecedoresMap.set(key, fornecedor);
    if (fornecedor.categoria) categorias.add(String(fornecedor.categoria).toLowerCase());
  });
  (Array.isArray(estoqueState.movimentos) ? estoqueState.movimentos : []).forEach((mov) => {
    _estoqueFornecedoresItem(mov).forEach((fornecedor) => {
      const key = _estoqueFornecedorKey(fornecedor);
      if (!key) return;
      fornecedoresMap.set(key, fornecedor);
      if (fornecedor.categoria) categorias.add(String(fornecedor.categoria).toLowerCase());
    });
  });
  const categoriasOptions = [...categorias].sort().map((cat) => ({
    value: cat,
    label: _estoqueCategoriaFornecedorLabel(cat),
  }));
  const fornecedoresOptions = [...fornecedoresMap.values()]
    .sort((a, b) => `${_estoqueCategoriaFornecedorLabel(a.categoria)} ${a.nome || ""}`.localeCompare(`${_estoqueCategoriaFornecedorLabel(b.categoria)} ${b.nome || ""}`, "pt-BR"))
    .map((fornecedor) => ({
      value: _estoqueFornecedorKey(fornecedor),
      label: `${fornecedor.nome || fornecedor.cnpj || "Fornecedor"} (${_estoqueCategoriaFornecedorLabel(fornecedor.categoria)})`,
    }));
  const produtosOptions = _estoqueOrdenarPorGrupo(estoqueState.posicaoRows || []).map((row) => ({
    value: _estoqueProdutoBaseKey(row),
    label: `${row.produto_base_nome || row.nome_produto || "Produto"} | ${_estoqueCodigoReferencia(row)}`,
  }));

  ["Lancar", "Posicao", "Movimentos", "Rastreio"].forEach((escopo) => {
    _estoqueSetSelectOptions(`estoqueFiltroCategoria${escopo}`, categoriasOptions, "Todas as categorias de fornecedor");
    _estoqueSetSelectOptions(`estoqueFiltroFornecedor${escopo}`, fornecedoresOptions, "", true);
    _estoqueSetSelectOptions(`estoqueFiltroProduto${escopo}`, produtosOptions, "", true);
  });
}

function aplicarFiltrosEstoque(){
  renderProdutosLancamentoEstoqueSelect();
  renderSaldoEstoqueFiltrado();
  renderMovimentosEstoqueFiltrado();
  renderRastreioLotesEstoque();
}

function limparFiltrosEstoque(){
  [
    "estoqueFiltroCategoriaLancar",
    "estoqueFiltroCategoriaPosicao",
    "estoqueFiltroCategoriaMovimentos",
    "estoqueFiltroCategoriaRastreio",
    "estoqueFiltroProdutoLancar",
    "estoqueFiltroNotaRastreio",
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  [
    "estoqueFiltroFornecedorLancar",
    "estoqueFiltroFornecedorPosicao",
    "estoqueFiltroFornecedorMovimentos",
    "estoqueFiltroFornecedorRastreio",
    "estoqueFiltroProdutoPosicao",
    "estoqueFiltroProdutoMovimentos",
    "estoqueFiltroProdutoRastreio",
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    Array.from(el.options || []).forEach((opt) => { opt.selected = false; });
  });
  aplicarFiltrosEstoque();
}

function selecionarProdutoLancamentoEstoque(){
  const select = document.getElementById("estoqueProdutoSelect");
  const selected = select?.selectedOptions?.[0];
  if (!selected || !selected.value) {
    const codigoNfe = document.getElementById("estoqueCodigoProdutoNfe");
    if (codigoNfe) codigoNfe.value = "";
    const quantidade = document.getElementById("estoqueQuantidade");
    if (quantidade) {
      quantidade.placeholder = "Quantidade";
      quantidade.title = "";
    }
    return;
  }
  const codigoBarras = document.getElementById("estoqueCodigoBarras");
  const codigoNfe = document.getElementById("estoqueCodigoProdutoNfe");
  const nome = document.getElementById("estoqueNomeProduto");
  const nota = document.getElementById("estoqueNumeroNota");
  const quantidade = document.getElementById("estoqueQuantidade");
  if (codigoBarras) codigoBarras.value = selected.dataset.codbarras || "";
  if (codigoNfe) codigoNfe.value = selected.dataset.codnfe || "";
  if (nome) nome.value = selected.dataset.base || selected.dataset.nome || "";
  if (nota && !String(nota.value || "").trim()) nota.value = selected.dataset.codnfe || selected.dataset.codbarras || "";
  if (quantidade) {
    const emb = selected.dataset.emb || "UN";
    const fator = Number(selected.dataset.fator || 0) || 1;
    quantidade.placeholder = `Quantidade em ${emb}`;
    quantidade.title = `Este lancamento converte ${emb} em ${_estoqueFormatQtd(fator)} unidade(s) no estoque.`;
  }
  sincronizarNumeroNotaPorCodigo();
  document.getElementById("estoqueQuantidade")?.focus();
}

function _optionsProdutosEstoqueConferencia(selectedId, itemAtual = {}){
  const sel = selectedId == null ? "" : String(selectedId);
  const atualLabel = String(itemAtual.nome_produto || itemAtual.codigo_barras || itemAtual.codigo_produto_nfe || "-").trim() || "-";
  const base = [`<option value="" ${sel ? "" : "selected"}>Atual: ${_escHtml(atualLabel)}</option>`];
  return base.concat((estoqueState.cadastroProdutos || []).map((prod) => {
    const v = String(prod.id || "");
    const s = v === sel ? "selected" : "";
    const rotuloBase = String(prod.nome_produto || "").trim() || prod.codigo_barras || prod.codigo_produto_nfe || `Produto ${v}`;
    const emb = prod.embalagem_tipo_padrao ? ` | ${prod.embalagem_tipo_padrao}${prod.fator_embalagem_padrao ? ` ${_estoqueFormatQtd(prod.fator_embalagem_padrao)}` : ""}` : "";
    return `<option value="${_escAttr(v)}" ${s}>${_escHtml(rotuloBase + emb)}</option>`;
  })).join("");
}

function _optionsProdutosEstoqueImport(itemAtual = {}){
  const atual = _buscarProdutoCadastroEstoque(itemAtual);
  const atualLabel = String(atual?.nome_produto || itemAtual.nome_produto || itemAtual.codigo_barras || itemAtual.codigo_produto_nfe || "").trim();
  const opcoes = [];
  if (atualLabel && !atual) {
    opcoes.push(`<option value="${_escAttr(atualLabel)}" selected>Atual: ${_escHtml(atualLabel)}</option>`);
  } else {
    opcoes.push(`<option value="" ${atual ? "" : "selected"}>Selecione um produto</option>`);
  }
  let grupoAtual = "";
  _estoqueOrdenarPorGrupo(estoqueState.cadastroProdutos || []).forEach((prod) => {
    const grupo = _estoqueGrupoNormalizado(prod.grupo_estoque) || "OUTROS";
    if (grupo !== grupoAtual) {
      if (grupoAtual) opcoes.push("</optgroup>");
      grupoAtual = grupo;
      opcoes.push(`<optgroup label="${_escAttr(_estoqueGrupoLabel(grupo))}">`);
    }
    const rotuloBase = String(prod.produto_base_nome || prod.nome_produto || "").trim() || prod.codigo_barras || prod.codigo_produto_nfe || `Produto ${prod.id || ""}`;
    const emb = prod.embalagem_tipo_padrao ? ` | ${prod.embalagem_tipo_padrao} x ${_estoqueFormatQtd(prod.fator_embalagem_padrao || 1)}` : "";
    const selected = atual && Number(atual.id || 0) === Number(prod.id || 0) ? "selected" : "";
    opcoes.push(
      `<option value="${_escAttr(rotuloBase)}" data-produto-id="${_escAttr(String(prod.id || ""))}" data-codbarras="${_escAttr(prod.codigo_barras || "")}" data-codnfe="${_escAttr(prod.codigo_produto_nfe || "")}" data-nome="${_escAttr(prod.nome_produto || rotuloBase)}" data-base="${_escAttr(prod.produto_base_nome || "")}" data-grupo="${_escAttr(prod.grupo_estoque || "")}" data-emb="${_escAttr(prod.embalagem_tipo_padrao || "")}" data-fator="${_escAttr(String(prod.fator_embalagem_padrao || ""))}" data-explicito="${prod.cadastro_explicitado ? "1" : "0"}" ${selected}>${_escHtml(rotuloBase + emb)}</option>`
    );
  });
  if (grupoAtual) opcoes.push("</optgroup>");
  return opcoes.join("");
}

function sincronizarProdutoImportacaoEstoque(index){
  const row = document.querySelector(`#estoqueImportPreviewItemsBody tr[data-item-index="${Number(index || 0)}"]`);
  if (!row) return;
  const select = row.querySelector(".estoque-import-item-nome");
  const selected = select?.selectedOptions?.[0];
  if (!selected) return;
  const codBarEl = row.querySelector(".estoque-import-item-codbar");
  const codNfeEl = row.querySelector(".estoque-import-item-codnfe");
  const embEl = row.querySelector(".estoque-import-item-und");
  const fatorEl = row.querySelector(".estoque-import-item-fator");
  const limpar = !String(selected.value || "").trim();
  if (codBarEl) codBarEl.value = limpar ? "" : (selected.dataset.codbarras || codBarEl.value || "");
  if (codNfeEl) codNfeEl.value = limpar ? "" : (selected.dataset.codnfe || codNfeEl.value || "");
  if (embEl) embEl.value = limpar ? "" : (selected.dataset.emb || embEl.value || "");
  if (fatorEl) fatorEl.value = limpar ? "" : (selected.dataset.fator || fatorEl.value || "");
  estoqueState.importDraftDirty = true;
  atualizarTotaisImportacaoEstoque();
}

function editarProdutoEstoqueCadastro(id){
  const item = (estoqueState.cadastroProdutos || []).find((prod) => Number(prod.id || 0) === Number(id || 0));
  if (!item) return;
  estoqueState.cadastroProdutoEditId = Number(item.id || 0);
  const map = {
    estoqueCadastroCodigoBarras: item.codigo_barras || "",
    estoqueCadastroCodigoNfe: item.codigo_produto_nfe || "",
    estoqueCadastroNomeProduto: item.nome_produto || "",
    estoqueCadastroGrupo: item.grupo_estoque || "",
    estoqueCadastroBaseNome: item.produto_base_nome || "",
    estoqueCadastroEmbalagem: item.embalagem_tipo_padrao || item.unidade || "",
    estoqueCadastroFator: item.fator_embalagem_padrao || "",
    estoqueCadastroAjusteQuantidade: "",
    estoqueCadastroAjusteMotivo: "",
  };
  Object.entries(map).forEach(([idCampo, valor]) => {
    const el = document.getElementById(idCampo);
    if (el) el.value = valor;
  });
  const ajusteBox = document.getElementById("estoqueCadastroAjusteBox");
  const ajusteBtn = document.getElementById("estoqueCadastroAjusteBtn");
  if (ajusteBox) ajusteBox.classList.remove("hidden");
  if (ajusteBtn) ajusteBtn.classList.remove("hidden");
  const status = document.getElementById("estoqueCadastroStatus");
  if (status) {
    status.textContent = `Editando cadastro de embalagem: ${item.nome_produto || item.codigo_barras || item.codigo_produto_nfe || item.id} | Saldo atual: ${_estoqueFormatQtd(_saldoProdutoCadastroAtual(item))}`;
  }
}

async function salvarProdutoEstoqueCadastro(){
  const payload = {
    codigo_barras: _digitsOnly(document.getElementById("estoqueCadastroCodigoBarras")?.value || ""),
    codigo_produto_nfe: (document.getElementById("estoqueCadastroCodigoNfe")?.value || "").trim(),
    nome_produto: (document.getElementById("estoqueCadastroNomeProduto")?.value || "").trim(),
    grupo_estoque: (document.getElementById("estoqueCadastroGrupo")?.value || "").trim(),
    produto_base_nome: (document.getElementById("estoqueCadastroBaseNome")?.value || "").trim(),
    embalagem_tipo_padrao: (document.getElementById("estoqueCadastroEmbalagem")?.value || "").trim(),
    fator_embalagem_padrao: Number((document.getElementById("estoqueCadastroFator")?.value || "").trim() || 0),
  };
  if (!payload.nome_produto && !payload.codigo_barras && !payload.codigo_produto_nfe) {
    alert("Informe ao menos o produto, codigo de barras ou codigo NF-e.");
    return;
  }
  if (!payload.embalagem_tipo_padrao) {
    alert("Informe o tipo da embalagem.");
    return;
  }
  if (!(payload.fator_embalagem_padrao > 0)) {
    alert("Informe quantas unidades existem por embalagem.");
    return;
  }
  const editId = Number(estoqueState.cadastroProdutoEditId || 0);
  const resp = await apiFetch(editId > 0 ? `/api/estoque/produtos/${editId}` : "/api/estoque/produtos", {
    method: editId > 0 ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json().catch(() => ({}));
  const status = document.getElementById("estoqueCadastroStatus");
  if (!resp.ok) {
    if (status) status.textContent = data?.erro || "Falha ao salvar cadastro de embalagem.";
    alert(data?.erro || "Falha ao salvar cadastro de embalagem.");
    return;
  }
  limparProdutoEstoqueCadastro();
  if (status) status.textContent = "Cadastro de embalagem salvo com sucesso.";
  await carregarEstoque();
  if (window.__dashView === "estoque") await renderDashboardEstoque();
}

async function aplicarAjusteProdutoEstoqueCadastro(){
  const editId = Number(estoqueState.cadastroProdutoEditId || 0);
  const quantidade_ajuste = Number((document.getElementById("estoqueCadastroAjusteQuantidade")?.value || "").trim() || 0);
  const motivo_ajuste = (document.getElementById("estoqueCadastroAjusteMotivo")?.value || "").trim();
  const status = document.getElementById("estoqueCadastroStatus");
  if (!(editId > 0)) {
    alert("Selecione um produto cadastrado para aplicar o ajuste.");
    return;
  }
  if (!quantidade_ajuste) {
    alert("Informe uma quantidade de ajuste diferente de zero.");
    return;
  }

  const resp = await apiFetch(`/api/estoque/produtos/${editId}/ajuste`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ quantidade_ajuste, motivo_ajuste }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (status) status.textContent = data?.erro || "Falha ao aplicar ajuste de estoque.";
    alert(data?.erro || "Falha ao aplicar ajuste de estoque.");
    return;
  }

  const produtoLabel = data?.produto?.nome_produto || data?.produto?.codigo_barras || data?.produto?.codigo_produto_nfe || editId;
  if (status) {
    status.textContent = `Ajuste aplicado em ${produtoLabel}. Saldo: ${_estoqueFormatQtd(data?.saldo_antes)} -> ${_estoqueFormatQtd(data?.saldo_depois)}.`;
  }
  const qtdEl = document.getElementById("estoqueCadastroAjusteQuantidade");
  const motivoEl = document.getElementById("estoqueCadastroAjusteMotivo");
  if (qtdEl) qtdEl.value = "";
  if (motivoEl) motivoEl.value = "";
  await carregarEstoque();
  if (window.__dashView === "estoque") await renderDashboardEstoque();
  editarProdutoEstoqueCadastro(editId);
}

async function excluirProdutoEstoqueCadastro(id){
  const item = (estoqueState.cadastroProdutos || []).find((prod) => Number(prod.id || 0) === Number(id || 0));
  if (!item) return;
  if (!confirm(`Excluir o cadastro de embalagem de ${item.nome_produto || item.codigo_barras || item.codigo_produto_nfe || item.id}?`)) return;
  const resp = await apiFetch(`/api/estoque/produtos/${Number(id || 0)}`, { method: "DELETE" });
  const data = await resp.json().catch(() => ({}));
  const status = document.getElementById("estoqueCadastroStatus");
  if (!resp.ok) {
    if (status) status.textContent = data?.erro || "Falha ao excluir cadastro.";
    alert(data?.erro || "Falha ao excluir cadastro.");
    return;
  }
  if (Number(estoqueState.cadastroProdutoEditId || 0) === Number(id || 0)) {
    limparProdutoEstoqueCadastro();
  }
  if (status) status.textContent = "Cadastro excluido com sucesso.";
  await carregarEstoque();
  if (window.__dashView === "estoque") await renderDashboardEstoque();
}

function _pararCameraEstoque(){
  if (estoqueState.cameraTimer) {
    clearInterval(estoqueState.cameraTimer);
    estoqueState.cameraTimer = null;
  }
  if (estoqueState.cameraStream) {
    try {
      estoqueState.cameraStream.getTracks().forEach((track) => track.stop());
    } catch {}
    estoqueState.cameraStream = null;
  }
  estoqueState.scanningCamera = false;
  const video = document.getElementById("estoqueCameraVideo");
  if (video) {
    try { video.pause(); } catch {}
    video.srcObject = null;
  }
  estoqueState.cameraTargetFieldId = "";
}

async function _executarAcaoPosLeituraCameraEstoque(valor = ""){
  const action = estoqueState.cameraAfterScanAction;
  estoqueState.cameraAfterScanAction = null;
  if (!action || typeof action !== "object") return;
  if (action.type === "buscar_dfe_abastecimento" && action.id) {
    const chave = _digitsOnly(valor || document.getElementById(`abast_chave_${action.id}`)?.value || "");
    if (chave.length === 44) {
      await buscarNfeAbastecimento(action.id, { chave, origem: "camera" });
    }
  }
}

function _aplicarCodigoEscaneadoEstoque(codigo){
  const valor = String(codigo || "").trim();
  if (!valor) return { aplicado: false, mensagem: "Nenhum codigo foi identificado." };
  const digits = _digitsOnly(valor);
  const targetFieldId = estoqueState.cameraTargetFieldId || "";
  if (targetFieldId) {
    const campoAlvo = document.getElementById(targetFieldId);
    if (campoAlvo) {
      const targetLower = String(targetFieldId || "").toLowerCase();
      const esperaChaveNfe = targetLower.includes("chave") || targetLower.includes("acesso");
      if (esperaChaveNfe && digits.length !== 44) {
        return {
          aplicado: false,
          mensagem: "Codigo detectado, mas nao eh uma chave NF-e completa de 44 digitos. Tente Foto OCR.",
        };
      }
      campoAlvo.value = digits.length === 44 ? digits : valor;
      campoAlvo.dispatchEvent(new Event("input", { bubbles: true }));
      if (digits.length === 44) {
        normalizarChaveNfeCampo(campoAlvo, !targetLower.startsWith("abast_"));
      }
      campoAlvo.focus();
      return { aplicado: true, valor: campoAlvo.value };
    }
  }
  const campoCodigo = document.getElementById("estoqueCodigoBarras");
  const campoNota = document.getElementById("estoqueNumeroNota");
  const campoChave = document.getElementById("estoqueChaveAcesso");
  if (digits.length === 44 && campoChave) {
    campoChave.value = digits;
    campoChave.dispatchEvent(new Event("input", { bubbles: true }));
    normalizarChaveNfeCampo(campoChave, true);
    return { aplicado: true, valor: digits };
  }
  if (campoCodigo) campoCodigo.value = valor;
  if (campoNota && !campoNota.value.trim()) campoNota.value = valor;
  sincronizarNumeroNotaPorCodigo();
  document.getElementById("estoqueNomeProduto")?.focus();
  return { aplicado: true, valor };
}

function _resolverContextoFallbackCameraOcr(targetFieldId = ""){
  const target = String(targetFieldId || "").trim();
  const matchAbastecimento = target.match(/^abast_chave_(\d+)$/);
  if (matchAbastecimento) {
    return {
      tipo: "abastecimento_barcode",
      id: Number(matchAbastecimento[1] || 0),
    };
  }
  if (!target || target === "estoqueChaveAcesso") {
    return { tipo: "estoque" };
  }
  return null;
}

function _acionarFallbackCameraOcr(targetFieldId = ""){
  const context = _resolverContextoFallbackCameraOcr(targetFieldId);
  if (!context) return false;
  const modal = document.getElementById("estoqueCameraModal");
  _fecharPopupBloqueante(modal);
  _pararCameraEstoque();
  selecionarImagemNfeOcr(context);
  return true;
}

function usarFotoCameraEstoque(){
  const targetFieldId = String(estoqueState.cameraTargetFieldId || "").trim();
  if (_acionarFallbackCameraOcr(targetFieldId)) return;
  alert("Captura por foto indisponivel para este campo.");
}

async function abrirCameraEstoque(targetFieldId = ""){
  if (!navigator.mediaDevices?.getUserMedia) {
    if (_acionarFallbackCameraOcr(targetFieldId)) return;
    alert("Camera/webcam indisponivel neste navegador.");
    return;
  }

  const modal = document.getElementById("estoqueCameraModal");
  const video = document.getElementById("estoqueCameraVideo");
  const status = document.getElementById("estoqueCameraStatus");
  if (!modal || !video || !status) return;

  _pararCameraEstoque();
  estoqueState.cameraTargetFieldId = String(targetFieldId || "").trim();
  _abrirPopupBloqueante(modal);
  if (!window.BarcodeDetector) {
    status.textContent = "Este navegador nao suporta leitura continua por webcam. Abrindo captura de foto.";
    if (_acionarFallbackCameraOcr(targetFieldId)) return;
    status.textContent = "Camera aberta, mas este navegador nao suporta leitura automatica por webcam.";
    return;
  }
  status.textContent = "Iniciando camera/webcam...";

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 1280 },
        height: { ideal: 720 },
      },
      audio: false,
    });
    estoqueState.cameraStream = stream;
    video.srcObject = stream;
    await video.play();
  } catch (err) {
    status.textContent = "Nao foi possivel abrir a camera/webcam.";
    console.warn("camera estoque erro:", err);
    return;
  }

  let detector;
  try {
    const supported = BarcodeDetector.getSupportedFormats ? await BarcodeDetector.getSupportedFormats() : [];
    const desired = ["code_128", "ean_13", "ean_8", "upc_a", "upc_e", "code_39", "itf", "qr_code"];
    const formats = supported.length ? desired.filter((fmt) => supported.includes(fmt)) : desired;
    detector = formats.length ? new BarcodeDetector({ formats }) : new BarcodeDetector();
  } catch (err) {
    console.warn("barcode detector erro:", err);
    if (_acionarFallbackCameraOcr(targetFieldId)) return;
    status.textContent = "Camera aberta, mas a leitura automatica nao esta disponivel agora.";
    return;
  }

  status.textContent = "Aponte a camera para o codigo de barras da nota ou use Foto.";
  estoqueState.cameraTimer = setInterval(async () => {
    if (estoqueState.scanningCamera || !detector || !video.srcObject) return;
    estoqueState.scanningCamera = true;
    try {
      const codes = await detector.detect(video);
      const code = (codes || []).find((item) => (item?.rawValue || "").trim());
      if (code?.rawValue) {
        const leitura = _aplicarCodigoEscaneadoEstoque(code.rawValue);
        if (leitura?.aplicado) {
          status.textContent = `Codigo lido: ${leitura.valor || code.rawValue}`;
          _executarAcaoPosLeituraCameraEstoque(leitura.valor || code.rawValue).catch(() => {});
          fecharCameraEstoque();
        } else if (leitura?.mensagem) {
          status.textContent = leitura.mensagem;
        }
      }
    } catch (err) {
      console.warn("scan camera estoque erro:", err);
    } finally {
      estoqueState.scanningCamera = false;
    }
  }, ESTOQUE_CAMERA_SCAN_INTERVAL_MS);
}

function fecharCameraEstoque(ev){
  if (ev && ev.target && ev.currentTarget && ev.target !== ev.currentTarget) return;
  const modal = document.getElementById("estoqueCameraModal");
  if (String(estoqueState.cameraTargetFieldId || "").toLowerCase().startsWith("abast_chave_")) {
    estoqueState.cameraAfterScanAction = null;
  }
  _fecharPopupBloqueante(modal);
  _pararCameraEstoque();
}

function _formatarResumoOcrNfe(ocr){
  if (!ocr || typeof ocr !== "object") return "Nenhum dado identificado.";
  const partes = [];
  if (ocr.chave_acesso) partes.push(`Chave: ${ocr.chave_acesso}`);
  if (ocr.numero_nota) partes.push(`Nota: ${ocr.numero_nota}`);
  if (ocr.serie) partes.push(`Serie: ${ocr.serie}`);
  if (ocr.emitente_nome) partes.push(`Emitente: ${ocr.emitente_nome}`);
  if (ocr.data_emissao) partes.push(`Emissao: ${ocr.data_emissao}`);
  if (ocr.valor_total_label) partes.push(`Total: ${ocr.valor_total_label}`);
  return partes.join(" | ") || "A foto foi lida, mas nenhum campo principal foi identificado automaticamente.";
}

function _draftBaseImportacaoEstoque(){
  return _normalizarDraftImportacaoEstoque({
    source_type: "manual",
    arquivo_origem: "",
    numero_nota: (document.getElementById("estoqueNumeroNota")?.value || "").trim(),
    chave_acesso: _digitsOnly(document.getElementById("estoqueChaveAcesso")?.value || ""),
    itens: [],
    warnings: [],
  });
}

function _aplicarResultadoOcrEstoque(ocr){
  const campoChave = document.getElementById("estoqueChaveAcesso");
  const campoNumero = document.getElementById("estoqueNumeroNota");
  const status = document.getElementById("estoqueNfeImportStatus");
  const statusOcr = document.getElementById("estoqueNfeOcrStatus");

  if (campoChave && ocr?.chave_acesso) {
    campoChave.value = ocr.chave_acesso;
    campoChave.dispatchEvent(new Event("input", { bubbles: true }));
    normalizarChaveNfeCampo(campoChave, true);
  }
  if (campoNumero && ocr?.numero_nota) {
    campoNumero.value = ocr.numero_nota;
  }
  if (statusOcr) statusOcr.textContent = _formatarResumoOcrNfe(ocr);
  if (status) {
    status.textContent = ocr?.chave_acesso
      ? "Foto lida com OCR. Confira os campos e use o botao de DF-e para buscar o XML oficial pela chave."
      : "Foto lida com OCR. Confira os campos reconhecidos; se a chave nao aparecer, a importacao segue apenas como apoio manual.";
  }
}

function _aplicarPreviewItensOcrEstoque(preview){
  const atual = _coletarDraftImportacaoEstoqueForm() || estoqueState.importDraft || _draftBaseImportacaoEstoque();
  const draft = _normalizarDraftImportacaoEstoque({
    ...atual,
    source_type: "ocr",
    arquivo_origem: preview?.arquivo_origem || atual?.arquivo_origem || "OCR-Itens",
    warnings: Array.isArray(preview?.warnings) ? preview.warnings : [],
    itens: Array.isArray(preview?.itens) ? preview.itens : [],
  });
  if (!draft.itens.length) {
    alert("Nenhum item foi identificado na foto.");
    return;
  }
  estoqueState.importDraft = draft;
  estoqueState.importDraftDirty = false;
  estoqueState.lastPortalPreviewSignature = "";
  const status = document.getElementById("estoqueNfeImportStatus");
  const statusOcr = document.getElementById("estoqueNfeOcrStatus");
  if (status) status.textContent = `Itens da nota lidos por OCR. ${draft.itens.length} item(ns) carregado(s) para revisao.`;
  if (statusOcr) statusOcr.textContent = `Itens reconhecidos por OCR: ${draft.itens.length}. Revise codigo, descricao, quantidade e valor antes de confirmar.`;
  setEstoqueView("lancar");
  renderEstoqueImportPreview();
}

function _revogarFotoManualItensEstoque(){
  if (estoqueState.manualPhotoUrl) {
    try { URL.revokeObjectURL(estoqueState.manualPhotoUrl); } catch {}
  }
  estoqueState.manualPhotoUrl = "";
  estoqueState.manualPhotoName = "";
}

function selecionarFotoManualItensEstoque(){
  const input = document.getElementById("estoqueItensFotoInput");
  if (!input) {
    alert("Entrada de foto manual indisponivel nesta tela.");
    return;
  }
  input.value = "";
  input.click();
}

function processarFotoManualItensEstoqueInput(ev){
  const input = ev?.target;
  const file = input?.files?.[0];
  if (!file) return;

  _revogarFotoManualItensEstoque();
  estoqueState.manualPhotoUrl = URL.createObjectURL(file);
  estoqueState.manualPhotoName = file.name || "Foto dos itens";

  const atual = _coletarDraftImportacaoEstoqueForm() || estoqueState.importDraft || _draftBaseImportacaoEstoque();
  const itensAtuais = Array.isArray(atual?.itens) && atual.itens.length ? atual.itens : [_novoItemImportacaoEstoque(1)];
  estoqueState.importDraft = _normalizarDraftImportacaoEstoque({
    ...atual,
    source_type: "manual",
    arquivo_origem: estoqueState.manualPhotoName,
    warnings: [
      "Foto carregada como apoio visual. Digite os itens manualmente usando a imagem como referencia.",
      "Fluxo otimizado para desempenho: sem OCR, sem espera de processamento.",
    ],
    itens: itensAtuais,
  });
  estoqueState.importDraftDirty = false;
  estoqueState.lastPortalPreviewSignature = "";

  const status = document.getElementById("estoqueNfeImportStatus");
  const statusFoto = document.getElementById("estoqueNfeOcrStatus");
  if (status) status.textContent = "Foto dos itens carregada. Complete a grade manualmente e confirme a importacao.";
  if (statusFoto) statusFoto.textContent = "Foto pronta para apoio visual. Digite codigo, descricao, quantidade e valor na grade abaixo.";
  setEstoqueView("lancar");
  renderEstoqueImportPreview();
  document.querySelector("#estoqueImportPreviewItemsBody .estoque-import-item-codnfe")?.focus();
  if (input) input.value = "";
}

function limparFotoManualItensEstoque(){
  _revogarFotoManualItensEstoque();
  if (estoqueState.importDraft) {
    const draft = _coletarDraftImportacaoEstoqueForm() || estoqueState.importDraft;
    estoqueState.importDraft = _normalizarDraftImportacaoEstoque({
      ...draft,
      source_type: "manual",
      arquivo_origem: "",
      warnings: (draft?.warnings || []).filter((msg) => !String(msg || "").toLowerCase().includes("foto")),
    });
  }
  renderEstoqueImportPreview();
}

function _aplicarResumoNfeAbastecimento(id, nfe){
  const dados = nfe && typeof nfe === "object" ? nfe : {};
  const campoChave = document.getElementById(`abast_chave_${id}`);
  const campoNota = document.getElementById(`abast_nota_${id}`);
  const campoEmitente = document.getElementById(`abast_emitente_${id}`);
  const campoValor = document.getElementById(`abast_valor_${id}`);
  const campoQtd = document.getElementById(`abast_qtd_${id}`);
  const campoCombustivel = document.getElementById(`abast_combustivel_${id}`);

  const chave = _digitsOnly(dados.chave_acesso_nfe || dados.chave_acesso || "");
  if (campoChave && chave) {
    campoChave.value = chave;
    campoChave.dispatchEvent(new Event("input", { bubbles: true }));
    normalizarChaveNfeCampo(campoChave, false);
  }
  if (campoNota && dados.numero_nota) campoNota.value = String(dados.numero_nota);
  if (campoEmitente && dados.emitente_nome) campoEmitente.value = String(dados.emitente_nome);
  if (campoValor && dados.valor != null && dados.valor !== "") campoValor.value = String(dados.valor);
  if (campoQtd && dados.quantidade_litros != null && dados.quantidade_litros !== "") campoQtd.value = String(dados.quantidade_litros);
  if (campoCombustivel && dados.combustivel_tipo) campoCombustivel.value = _normalizarCombustivelTipo(dados.combustivel_tipo);
  _capturarDraftAbastecimentoDom(id);
}

function _aplicarResultadoOcrAbastecimento(id, ocr){
  const dados = ocr && typeof ocr === "object" ? ocr : {};
  _aplicarResumoNfeAbastecimento(id, {
    ...dados,
    chave_acesso_nfe: dados.chave_acesso_nfe || dados.chave_acesso || "",
    valor: dados.valor,
  });
  const resumo = _resumoNfeAbastecimentoFeedback(dados).replace(/^DF-e localizou\s*/i, "OCR localizou ");
  _setAbastecimentoFeedback(
    id,
    resumo || "OCR leu a nota. Revise os campos antes de concluir o abastecimento.",
    dados.quantidade_litros != null && dados.quantidade_litros !== "" ? "success" : "warning"
  );
  alert(`Foto lida com OCR. ${resumo || _formatarResumoOcrNfe(dados)}`);
}

function _aplicarResultadoBarcodeAbastecimento(id, ocr){
  estoqueState.cameraAfterScanAction = null;
  const dados = ocr && typeof ocr === "object" ? ocr : {};
  _aplicarResumoNfeAbastecimento(id, dados);
  const chave = _digitsOnly(dados.chave_acesso_nfe || dados.chave_acesso || "");
  const partes = [];
  if (chave) partes.push(`chave ${chave}`);
  if (dados.numero_nota) partes.push(`nota ${dados.numero_nota}`);
  if (dados.emitente_nome) partes.push(`emitente ${dados.emitente_nome}`);
  const completo = dados.quantidade_litros != null && dados.quantidade_litros !== "" && dados.valor != null && dados.valor !== "";
  if (completo) {
    partes.push(`qtd ${_fmtNumber(dados.quantidade_litros, 3)}`);
    partes.push(`valor R$ ${_fmtMoney(dados.valor)}`);
  }
  const resumo = partes.length
    ? `Chave/QR localizou ${partes.join(" | ")}.`
    : "Chave/QR lido. Revise os campos antes de concluir o abastecimento.";
  _setAbastecimentoFeedback(
    id,
    completo ? resumo : `${resumo} Se litros e valor nao vierem, use Foto OCR.`,
    completo ? "success" : "info"
  );
  alert(completo ? resumo : `${resumo} Se a NF-e vier parcial, use Foto OCR para completar litros e valor.`);
}

function _statusElementoOcr(context){
  if (context.tipo === "manutencao") return document.getElementById("manutOcrStatus");
  if (context.tipo === "estoque" || context.tipo === "estoque_itens" || context.tipo === "estoque_azure") {
    return document.getElementById("estoqueNfeOcrStatus");
  }
  return null;
}

function _setStatusProgressoOcr(context, { title = "", message = "", detail = "", tone = "info", progress = null, indeterminate = false } = {}){
  const status = _statusElementoOcr(context);
  if (status) {
    const hasProgress = progress != null || indeterminate;
    status.innerHTML = `<div class="ocr-status-card" data-tone="${_escAttr(tone)}">
      ${title ? `<div class="ocr-status-title">${_escHtml(title)}</div>` : ""}
      ${message ? `<div class="ocr-status-message">${_escHtml(message)}</div>` : ""}
      ${detail ? `<div class="ocr-status-detail">${_escHtml(detail)}</div>` : ""}
      ${hasProgress ? `
        <div class="ocr-status-progress" aria-hidden="true">
          <span class="ocr-status-progress-fill${indeterminate ? " is-indeterminate" : ""}" style="${indeterminate ? "" : `width:${_escAttr(String(progress || 0))}%`}"></span>
        </div>
      ` : ""}
    </div>`;
  }

  if ((context.tipo === "abastecimento" || context.tipo === "abastecimento_barcode") && context.id) {
    _setAbastecimentoFeedback(context.id, message || title, tone, {
      title,
      detail,
      progress,
      indeterminate,
    });
  }
}

function selecionarImagemNfeOcr(context = { tipo: "estoque" }){
  const input = document.getElementById("nfeOcrImagemInput");
  if (!input) {
    alert("Entrada de imagem para OCR indisponivel nesta tela.");
    return;
  }
  estoqueState.ocrContext = context && typeof context === "object" ? { ...context } : { tipo: "estoque" };
  input.value = "";
  input.click();
}

async function _compactarImagemParaOcr(file){
  if (!file || !String(file.type || "").startsWith("image/")) return file;
  if (file.size <= 2 * 1024 * 1024) return file;

  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("Falha ao ler a imagem."));
    reader.readAsDataURL(file);
  });

  const img = await new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Falha ao abrir a imagem para OCR."));
    image.src = dataUrl;
  });

  const maxLado = 1600;
  const maiorLado = Math.max(img.width || 0, img.height || 0) || 1;
  const fator = maiorLado > maxLado ? (maxLado / maiorLado) : 1;
  const largura = Math.max(1, Math.round((img.width || 1) * fator));
  const altura = Math.max(1, Math.round((img.height || 1) * fator));

  const canvas = document.createElement("canvas");
  canvas.width = largura;
  canvas.height = altura;
  const ctx = canvas.getContext("2d", { alpha: false });
  if (!ctx) return file;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, largura, altura);
  ctx.drawImage(img, 0, 0, largura, altura);

  const blob = await new Promise((resolve) => {
    canvas.toBlob((result) => resolve(result), "image/jpeg", 0.82);
  });
  if (!blob) return file;
  return new File([blob], (file.name || "ocr.jpg").replace(/\.\w+$/, "") + ".jpg", {
    type: "image/jpeg",
    lastModified: Date.now(),
  });
}

async function processarImagemNfeOcrInput(ev){
  const input = ev?.target;
  const file = input?.files?.[0];
  const context = estoqueState.ocrContext || { tipo: "estoque" };
  estoqueState.ocrContext = null;
  if (!file) return;

  _setStatusProgressoOcr(context, {
    title: context.tipo === "abastecimento_barcode"
      ? "Preparando leitura da chave"
      : context.tipo === "abastecimento"
        ? "Preparando OCR do abastecimento"
        : context.tipo === "estoque_itens"
          ? "Preparando OCR dos itens"
          : context.tipo === "estoque_azure"
            ? "Preparando Azure Document Intelligence"
            : context.tipo === "manutencao"
              ? "Preparando OCR da manutencao"
              : "Preparando OCR da nota",
    message: "Validando a foto selecionada.",
    detail: file?.name ? `Arquivo: ${file.name}` : "",
    tone: "info",
    progress: 5,
  });

  let arquivoOcr = file;
  try {
    _setStatusProgressoOcr(context, {
      title: "Compactando imagem",
      message: "Ajustando a foto para acelerar o OCR.",
      detail: "Se a imagem ja estiver leve, esta etapa termina quase na hora.",
      tone: "info",
      progress: 12,
    });
    arquivoOcr = await _compactarImagemParaOcr(file);
  } catch {}
  _setStatusProgressoOcr(context, {
    title: "Enviando foto",
    message: arquivoOcr !== file ? "Foto compactada. Iniciando upload para leitura." : "Iniciando upload da foto para leitura.",
    detail: arquivoOcr !== file ? `Tamanho enviado: ${_formatBytesProgress(arquivoOcr.size)}` : "",
    tone: "info",
    progress: 18,
  });

  const formData = new FormData();
  formData.append("arquivo", arquivoOcr);
  if ((context.tipo === "abastecimento" || context.tipo === "abastecimento_barcode") && context.id) {
    const combustivelTipo = (document.getElementById(`abast_combustivel_${context.id}`)?.value || "").trim();
    if (combustivelTipo) formData.append("combustivel_tipo", combustivelTipo);
  }
  const timeoutMs = (context.tipo === "estoque_itens" || context.tipo === "estoque_azure")
    ? 180000
    : context.tipo === "abastecimento_barcode"
      ? 45000
      : context.tipo === "abastecimento"
        ? 180000
      : 90000;
  let resp;
  let data = {};
  const url = context.tipo === "estoque_itens"
      ? "/api/estoque/nfe/ocr_itens"
      : context.tipo === "estoque_azure"
        ? "/api/estoque/nfe/azure_itens"
        : context.tipo === "abastecimento_barcode"
          ? "/api/abastecimentos/barcode_preview"
        : context.tipo === "abastecimento"
          ? "/api/abastecimentos/ocr_preview"
        : context.tipo === "manutencao"
          ? "/api/manutencoes/ocr_preview"
          : "/api/estoque/nfe/ocr";
  try {
    resp = await apiUploadWithProgress(url, {
      method: "POST",
      body: formData,
      timeoutMs,
      onProgress: (event) => {
        if (!event?.lengthComputable || !(event.total > 0)) return;
        const percent = Math.max(1, Math.min(100, Math.round((event.loaded / event.total) * 100)));
        _setStatusProgressoOcr(context, {
          title: "Enviando foto",
          message: `${percent}% do upload concluido.`,
          detail: `${_formatBytesProgress(event.loaded)} de ${_formatBytesProgress(event.total)} enviados.`,
          tone: "info",
          progress: Math.min(80, 18 + Math.round(percent * 0.62)),
        });
      },
      onUploadComplete: () => {
        _setStatusProgressoOcr(context, {
          title: context.tipo === "abastecimento_barcode"
            ? "Lendo chave da imagem"
            : context.tipo === "abastecimento"
              ? "Processando Quantidade e V.Total"
              : context.tipo === "estoque_itens"
                ? "Processando itens da nota"
                : context.tipo === "estoque_azure"
                  ? "Processando no Azure"
                  : context.tipo === "manutencao"
                    ? "Processando OCR da manutencao"
                    : "Processando OCR da nota",
          message: context.tipo === "abastecimento"
            ? "A imagem foi enviada. Agora o sistema esta procurando apenas Quantidade e V.Total."
            : "A imagem foi enviada. Aguarde a leitura da nota.",
          detail: context.tipo === "abastecimento"
            ? "A extracao prioriza a secao DADOS DOS PRODUTOS para reduzir variacao."
            : "",
          tone: "info",
          progress: 90,
          indeterminate: true,
        });
      },
    });
    data = await resp.json().catch(() => ({}));
  } catch (err) {
    const mensagem = err?.name === "AbortError"
      ? (context.tipo === "estoque_itens"
          ? "A leitura OCR dos itens demorou demais. Na primeira execucao o motor novo pode levar mais tempo; tente novamente com 5 a 10 linhas da tabela por vez."
          : context.tipo === "estoque_azure"
            ? "O Azure demorou demais para responder. Confira a configuracao em Config > NF-e ou tente outra foto."
            : context.tipo === "abastecimento_barcode"
              ? "A leitura do codigo de barras/QR demorou demais. Tente aproximar mais a imagem da chave."
            : context.tipo === "abastecimento"
              ? "A leitura OCR do abastecimento demorou demais. Tente uma foto mais focada so na secao DADOS DOS PRODUTOS."
            : context.tipo === "manutencao"
              ? "A leitura OCR da manutencao demorou demais. Tente uma foto mais reta e bem iluminada."
              : "A leitura OCR demorou demais para responder. Tente uma foto mais aproximada, reta e focada na grade dos itens.")
      : context.tipo === "abastecimento_barcode"
        ? "Falha ao enviar a imagem do codigo de barras/QR da nota."
      : context.tipo === "abastecimento"
        ? "Falha ao enviar a foto do OCR do abastecimento."
      : context.tipo === "manutencao"
        ? "Falha ao enviar a foto da nota de manutencao para OCR."
        : "Falha ao enviar a foto da nota para OCR.";
    _setStatusProgressoOcr(context, {
      title: "Falha no OCR",
      message: mensagem,
      tone: "error",
    });
    if (context.tipo === "abastecimento_barcode") estoqueState.cameraAfterScanAction = null;
    alert(mensagem);
    if (input) input.value = "";
    return;
  }
  if (!resp.ok) {
    const mensagem = data?.erro || (
      context.tipo === "abastecimento_barcode"
        ? "Falha ao ler o codigo de barras/QR da nota."
        : context.tipo === "abastecimento"
          ? "Falha ao ler a foto do OCR do abastecimento."
        : context.tipo === "manutencao"
          ? "Falha ao ler a foto da nota de manutencao."
          : "Falha ao ler a foto da nota."
    );
    _setStatusProgressoOcr(context, {
      title: "Falha no OCR",
      message: mensagem,
      tone: "error",
    });
    if (context.tipo === "abastecimento_barcode") estoqueState.cameraAfterScanAction = null;
    alert(mensagem);
    if (input) input.value = "";
    return;
  }

  if (context.tipo === "estoque_itens" || context.tipo === "estoque_azure") {
    _aplicarPreviewItensOcrEstoque(data?.preview || {});
  } else if (context.tipo === "manutencao") {
    _aplicarPreviewOcrManutencao(data?.preview || {});
  } else if (context.tipo === "abastecimento_barcode" && context.id) {
    _aplicarResultadoBarcodeAbastecimento(context.id, data?.ocr || {});
  } else if (context.tipo === "abastecimento" && context.id) {
    _aplicarResultadoOcrAbastecimento(context.id, data?.ocr || {});
  } else {
    _aplicarResultadoOcrEstoque(data?.ocr || {});
  }

  if (Array.isArray(data?.warnings) && data.warnings.length) {
    const aviso = data.warnings.join(" ");
    _setStatusProgressoOcr(context, {
      title: "OCR concluido",
      message: context.tipo === "abastecimento"
        ? `Leitura concluida. ${aviso}`
        : context.tipo === "abastecimento_barcode"
          ? `Leitura da chave concluida. ${aviso}`
          : context.tipo === "estoque_itens"
            ? `Itens lidos por OCR. ${aviso}`
            : context.tipo === "estoque_azure"
              ? `Itens lidos via Azure. ${aviso}`
              : context.tipo === "manutencao"
                ? `Nota de manutencao lida por OCR. ${aviso}`
                : `${_formatarResumoOcrNfe(data?.ocr || {})} Avisos: ${aviso}`,
      tone: "warning",
    });
  } else {
    _setStatusProgressoOcr(context, {
      title: "OCR concluido",
      message: context.tipo === "abastecimento"
        ? "Leitura concluida. Revise Quantidade e V.Total antes de confirmar."
        : context.tipo === "abastecimento_barcode"
          ? "Leitura da chave concluida."
          : context.tipo === "estoque_itens"
            ? "Itens lidos por OCR."
            : context.tipo === "estoque_azure"
              ? "Itens lidos via Azure."
              : context.tipo === "manutencao"
                ? "Nota de manutencao lida por OCR."
                : _formatarResumoOcrNfe(data?.ocr || {}),
      tone: "success",
    });
  }

  if (input) input.value = "";
}

function bindEstoqueScannerInput(){
  const codigo = document.getElementById("estoqueCodigoBarras");
  const nota = document.getElementById("estoqueNumeroNota");
  const nome = document.getElementById("estoqueNomeProduto");
  const campoChave = document.getElementById("estoqueChaveAcesso");
  const inputOcr = document.getElementById("nfeOcrImagemInput");
  const inputFotoManual = document.getElementById("estoqueItensFotoInput");
  if (!codigo || codigo.dataset.bound === "1") return;
  codigo.dataset.bound = "1";
  if (inputOcr && inputOcr.dataset.bound !== "1") {
    inputOcr.dataset.bound = "1";
    inputOcr.addEventListener("change", processarImagemNfeOcrInput);
  }
  if (inputFotoManual && inputFotoManual.dataset.bound !== "1") {
    inputFotoManual.dataset.bound = "1";
    inputFotoManual.addEventListener("change", processarFotoManualItensEstoqueInput);
  }
  if (campoChave && campoChave.dataset.bound !== "1") {
    campoChave.dataset.bound = "1";
    campoChave.addEventListener("input", () => {
      const digits = normalizarChaveNfeCampo(campoChave, false);
      if (digits.length === 44) {
        _processarChaveNfeLida(digits, "estoque").catch(() => {});
      }
    });
    campoChave.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        normalizarChaveNfeCampo(campoChave, true);
      }
    });
  }
  codigo.addEventListener("input", () => {
    const digits = _digitsOnly(codigo.value || "");
    if (digits.length === 44 && campoChave) {
      campoChave.value = digits;
      normalizarChaveNfeCampo(campoChave, true);
      return;
    }
    sincronizarNumeroNotaPorCodigo();
  });
  codigo.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      const digits = _digitsOnly(codigo.value || "");
      if (digits.length === 44 && campoChave) {
        campoChave.value = digits;
        normalizarChaveNfeCampo(campoChave, true);
        codigo.value = "";
        return;
      }
      sincronizarNumeroNotaPorCodigo();
      if (nota && !nota.value.trim()) nota.value = (codigo.value || "").trim();
      if (nome) nome.focus();
    }
  });
}

async function importarNfeEstoque(){
  const input = document.getElementById("estoqueNfeArquivo");
  const status = document.getElementById("estoqueNfeImportStatus");
  const campoChave = document.getElementById("estoqueChaveAcesso");
  const file = input?.files?.[0];
  const chave_acesso_esperada = _digitsOnly(campoChave?.value || "");
  if (!file) {
    alert("Selecione o XML ou PDF da NF-e.");
    return;
  }
  if (chave_acesso_esperada && chave_acesso_esperada.length !== 44) {
    alert("A chave de acesso da NF-e precisa ter 44 digitos.");
    return;
  }
  if (estoqueState.importDraft && !confirm("Ja existe uma importacao em revisao. Deseja substituir pelos dados deste arquivo?")) {
    return;
  }

  const formData = new FormData();
  formData.append("arquivo", file);
  if (chave_acesso_esperada) formData.append("chave_acesso_esperada", chave_acesso_esperada);
  if (status) status.textContent = "Lendo arquivo da NF-e...";

  const resp = await apiFetch("/api/estoque/nfe/preview", {
    method: "POST",
    body: formData,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (status) status.textContent = data?.erro || "Falha ao ler a NF-e.";
    alert(data?.erro || "Falha ao ler a NF-e.");
    return;
  }

  const draft = _normalizarDraftImportacaoEstoque(data?.preview || {});
  if (!draft.itens.length) draft.itens = [_novoItemImportacaoEstoque(1)];
  estoqueState.importDraft = draft;
  estoqueState.importDraftDirty = false;
  estoqueState.lastPortalPreviewSignature = "";
  if (input) input.value = "";
  if (campoChave && draft.chave_acesso) campoChave.value = draft.chave_acesso;
  if (status) {
    status.textContent = draft.source_type === "dfe"
      ? "Arquivo recebido. A chave foi usada para buscar o XML oficial via DF-e; revise os dados na confirmacao antes de importar."
      : "Arquivo lido. Revise os dados na confirmacao antes de importar.";
  }
  setEstoqueView("lancar");
  renderEstoqueImportPreview();
  document.getElementById("estoquePreviewNumeroNota")?.focus();
}

async function importarXmlFabricaEstoque(){
  const input = document.getElementById("estoqueXmlFabricaArquivo");
  const status = document.getElementById("estoqueNfeImportStatus");
  const origemSetor = document.getElementById("estoqueOrigemSetor");
  const destinoSetor = document.getElementById("estoqueDestinoSetor");
  const file = input?.files?.[0] || null;

  if (estoqueState.importDraft && !confirm("Ja existe uma importacao em revisao. Deseja substituir pelos dados do XML da fabrica?")) {
    return;
  }

  const formData = new FormData();
  if (file) formData.append("arquivo", file, file.name || "transferencia.xml");
  if (status) {
    status.textContent = file
      ? "Lendo XML da fabrica..."
      : "Buscando o XML mais recente da fabrica para transferencia...";
  }

  const resp = await apiFetch("/api/estoque/nfe/preview_fabrica", {
    method: "POST",
    body: formData,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (status) status.textContent = data?.erro || "Falha ao ler o XML da fabrica.";
    alert(data?.erro || "Falha ao ler o XML da fabrica.");
    return;
  }

  const draft = _normalizarDraftImportacaoEstoque(data?.preview || {});
  if (!draft.itens.length) draft.itens = [_novoItemImportacaoEstoque(1)];
  estoqueState.importDraft = draft;
  estoqueState.importDraftDirty = false;
  estoqueState.lastPortalPreviewSignature = "";
  if (input) input.value = "";
  if (origemSetor) origemSetor.value = "Fabrica";
  if (destinoSetor) destinoSetor.value = "Central";
  if (status) {
    status.textContent = "XML da fabrica carregado. Revise a transferencia para a central antes de confirmar a conferencia.";
  }
  setEstoqueView("lancar");
  renderEstoqueImportPreview();
  document.getElementById("estoquePreviewNumeroNota")?.focus();
}

async function importarHtmlPortalClipboardEstoque(){
  const status = document.getElementById("estoqueNfeImportStatus");
  const campoChave = document.getElementById("estoqueChaveAcesso");
  const chave_acesso_esperada = _digitsOnly(campoChave?.value || "");
  if (chave_acesso_esperada && chave_acesso_esperada.length !== 44) {
    alert("A chave de acesso da NF-e precisa ter 44 digitos.");
    return;
  }
  if (estoqueState.importDraft && !confirm("Ja existe uma importacao em revisao. Deseja substituir pelos dados do portal?")) {
    return;
  }
  if (!navigator.clipboard?.readText) {
    alert("Este navegador nao permite ler a area de transferencia. Use o upload do HTML salvo da consulta publica.");
    return;
  }

  let htmlText = "";
  try {
    if (status) status.textContent = "Lendo o HTML da consulta publica pela area de transferencia...";
    htmlText = await navigator.clipboard.readText();
  } catch (err) {
    console.warn("clipboard html portal erro:", err);
    if (status) status.textContent = "Nao foi possivel ler a area de transferencia. Copie o HTML da pagina do portal e tente novamente.";
    alert("Nao foi possivel ler a area de transferencia. Copie o HTML da pagina do portal e tente novamente.");
    return;
  }

  if (!String(htmlText || "").trim()) {
    if (status) status.textContent = "A area de transferencia esta vazia.";
    alert("A area de transferencia esta vazia.");
    return;
  }

  if (!/XSLTNFeResumida|tabNFe|Consulta NF-e|Nota Fiscal Eletr[oô]nica/i.test(htmlText)) {
    if (status) status.textContent = "O conteudo copiado nao parece ser o HTML da consulta publica da NF-e.";
    alert("O conteudo copiado nao parece ser o HTML da consulta publica da NF-e.");
    return;
  }

  const resp = await apiFetch("/api/estoque/nfe/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      html_text: htmlText,
      arquivo_origem: "consulta_nfe_clipboard.html",
      chave_acesso_esperada,
    }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (status) status.textContent = data?.erro || "Falha ao importar o HTML da consulta publica.";
    alert(data?.erro || "Falha ao importar o HTML da consulta publica.");
    return;
  }

  const draft = _normalizarDraftImportacaoEstoque(data?.preview || {});
  if (!draft.itens.length) draft.itens = [_novoItemImportacaoEstoque(1)];
  estoqueState.importDraft = draft;
  estoqueState.importDraftDirty = false;
  estoqueState.lastPortalPreviewSignature = "";
  if (campoChave && draft.chave_acesso) campoChave.value = draft.chave_acesso;
  if (status) {
    status.textContent = draft.itens.length
      ? "HTML da consulta publica importado. Os itens foram carregados para revisao."
      : "HTML da consulta publica importado. Revise os dados; os itens nao vieram completos.";
  }
  setEstoqueView("lancar");
  renderEstoqueImportPreview();
  document.getElementById("estoquePreviewNumeroNota")?.focus();
}

function _aplicarPreviewPortalNfeEstoque(preview, statusMensagem = "") {
  const status = document.getElementById("estoqueNfeImportStatus");
  const campoChave = document.getElementById("estoqueChaveAcesso");
  if (estoqueState.importDraft && estoqueState.importDraftDirty) {
    if (status) status.textContent = "Retorno do portal recebido, mas a importacao atual tem alteracoes locais. Conclua ou cancele antes de substituir.";
    return;
  }
  const draft = _normalizarDraftImportacaoEstoque(preview || {});
  if (!draft.itens.length) draft.itens = [_novoItemImportacaoEstoque(1)];
  estoqueState.importDraft = draft;
  estoqueState.importDraftDirty = false;
  estoqueState.lastPortalPreviewSignature = draft.__signature || "";
  if (campoChave && draft.chave_acesso) campoChave.value = draft.chave_acesso;
  if (status) {
    status.textContent = statusMensagem
      || (draft.itens.length
        ? "Consulta publica recebida do portal. Os itens foram carregados para revisao."
        : "Consulta publica recebida do portal. Revise os dados e complete os itens se necessario.");
  }
  setEstoqueView("lancar");
  renderEstoqueImportPreview();
  document.getElementById("estoquePreviewNumeroNota")?.focus();
}

async function copiarBookmarkletPortalNfe(){
  const campoChave = document.getElementById("estoqueChaveAcesso");
  const chave = _digitsOnly(campoChave?.value || "");
  const endpoint = `${window.location.origin}/api/estoque/nfe/portal_retorno`;
  const origin = window.location.origin;
  const bookmarklet = `javascript:(function(){try{var d=document;var f=d.createElement('form');f.method='POST';f.action=${JSON.stringify(endpoint)};f.acceptCharset='UTF-8';var add=function(n,v){var i=d.createElement('textarea');i.name=n;i.value=v;f.appendChild(i);};add('html_text',d.documentElement.outerHTML||'');add('origin',${JSON.stringify(origin)});add('arquivo_origem','consulta_nfe_portal.html');add('chave_acesso_esperada',${JSON.stringify(chave)});d.body.appendChild(f);f.submit();}catch(e){alert('Falha ao enviar o HTML do portal: '+e);}})();`;
  try {
    if (!navigator.clipboard?.writeText) {
      throw new Error("clipboard indisponivel");
    }
    await navigator.clipboard.writeText(bookmarklet);
    alert("Bookmarklet copiado. Crie um favorito no navegador e cole este codigo no campo URL do favorito.");
  } catch (err) {
    console.warn("bookmarklet portal copia erro:", err);
    prompt("Copie o bookmarklet abaixo e cole na URL de um favorito do navegador:", bookmarklet);
  }
}

async function buscarNfeEstoquePorChave(options = {}) {
  const status = document.getElementById("estoqueNfeImportStatus");
  const campoChave = document.getElementById("estoqueChaveAcesso");
  const opts = options && typeof options === "object" ? options : {};
  const autoTriggered = !!opts.autoTriggered;
  const chave_acesso = _digitsOnly(opts.chave_acesso || campoChave?.value || "");
  if (campoChave && chave_acesso) campoChave.value = chave_acesso;
  if (chave_acesso.length !== 44) {
    const mensagem = "A chave de acesso da NF-e precisa ter 44 digitos.";
    if (status) status.textContent = mensagem;
    if (!autoTriggered) alert(mensagem);
    return;
  }
  if (estoqueState.importDraft && !confirm("Ja existe uma importacao em revisao. Deseja substituir pelos dados buscados no DF-e?")) {
    if (autoTriggered && status) status.textContent = "A chave foi lida, mas a NF-e atual em revisao foi mantida.";
    return;
  }

  if (status) {
    status.textContent = autoTriggered
      ? "Chave lida. Buscando automaticamente os dados oficiais da NF-e via DF-e..."
      : "Buscando XML oficial da NF-e via DF-e...";
  }
  const resp = await apiFetch("/api/estoque/nfe/preview_dfe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chave_acesso }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const mensagem = (data?.erro || "Falha ao consultar DF-e.") + _resumoLimiteConsultasDfe(data?.limite_consultas);
    if (status) status.textContent = mensagem;
    if (!autoTriggered) alert(mensagem);
    return;
  }

  const draft = _normalizarDraftImportacaoEstoque(data?.preview || {});
  if (!draft.itens.length) draft.itens = [_novoItemImportacaoEstoque(1)];
  estoqueState.importDraft = draft;
  estoqueState.importDraftDirty = false;
  estoqueState.lastPortalPreviewSignature = "";
  if (campoChave && draft.chave_acesso) campoChave.value = draft.chave_acesso;
  if (status) {
    const motivo = data?.dfe?.manifestado ? " XML liberado apos manifestacao." : "";
    const limiteResumo = _resumoLimiteConsultasDfe(data?.limite_consultas);
    const limitacao = (data?.limitation_message || draft.limitation_message || "").trim();
    if (draft.preview_tipo === "parcial") {
      status.textContent = autoTriggered
        ? `NF-e localizada automaticamente pelo DF-e, mas sem XML completo.${motivo} ${limitacao || "Os itens nao vieram nesta consulta."} Revise os dados na confirmacao e complete os itens por outro meio.${limiteResumo}`
        : `Documento localizado no DF-e, mas sem XML completo.${motivo} ${limitacao || "Os itens nao vieram nesta consulta."} Revise os dados na confirmacao e complete os itens por outro meio.${limiteResumo}`;
    } else {
      status.textContent = autoTriggered
        ? `NF-e localizada automaticamente pelo DF-e.${motivo} Revise os dados na confirmacao antes de importar.${limiteResumo}`
        : `XML oficial carregado pelo DF-e.${motivo} Revise os dados na confirmacao antes de importar.${limiteResumo}`;
    }
  }
  setEstoqueView("lancar");
  renderEstoqueImportPreview();
  document.getElementById("estoquePreviewNumeroNota")?.focus();
}

async function carregarConferenciasEstoque(selecionarId = null){
  const body = document.getElementById("estoqueConferenciasBody");
  if (!body) return;
  const resp = await apiFetch("/api/estoque/conferencias");
  if (!resp.ok) {
    body.innerHTML = `<tr><td colspan="5">Erro ao carregar conferencias do estoque.</td></tr>`;
    return;
  }
  const dados = await resp.json();
  estoqueState.conferencias = Array.isArray(dados) ? dados : [];

  body.innerHTML = estoqueState.conferencias.length ? estoqueState.conferencias.map((c) => {
    const selecionado = String(estoqueState.conferenciaAtual?.conferencia?.id || selecionarId || "") === String(c.id);
    return `
      <tr class="${selecionado ? "estoque-select-row is-selected" : "estoque-select-row"}">
        <td>${_escHtml(c.numero_nota || c.chave_acesso || "-")}</td>
        <td>${_escHtml(c.emitente_nome || "-")}</td>
        <td>${_escHtml(String(c.total_itens || 0))}</td>
        <td>${_escHtml(c.status || "pendente")}</td>
        <td><button type="button" onclick="selecionarConferenciaEstoque(${c.id})">Abrir</button></td>
      </tr>
    `;
  }).join("") : `<tr><td colspan="5">Sem NF-e para conferir.</td></tr>`;

  if (selecionarId) {
    await selecionarConferenciaEstoque(selecionarId);
    return;
  }

  const atualId = estoqueState.conferenciaAtual?.conferencia?.id;
  if (atualId && estoqueState.conferencias.some((c) => String(c.id) === String(atualId))) {
    await selecionarConferenciaEstoque(atualId);
    return;
  }

  if (!estoqueState.conferencias.length) {
    estoqueState.conferenciaAtual = null;
    const resumo = document.getElementById("estoqueConferenciaResumo");
    const itensBody = document.getElementById("estoqueConferenciaItensBody");
    if (resumo) resumo.textContent = "Selecione uma NF-e para conferir e consolidar.";
    if (itensBody) itensBody.innerHTML = `<tr><td colspan="7">Nenhuma NF-e selecionada.</td></tr>`;
  }
}

async function selecionarConferenciaEstoque(id){
  const conferenciaId = Number(id || 0);
  if (!(conferenciaId > 0)) return;
  try { await ensureProdutosEstoqueCache(); } catch {}

  const resumo = document.getElementById("estoqueConferenciaResumo");
  const itensBody = document.getElementById("estoqueConferenciaItensBody");
  if (resumo) resumo.textContent = "Carregando conferencia...";
  if (itensBody) itensBody.innerHTML = `<tr><td colspan="7">Carregando itens...</td></tr>`;

  const resp = await apiFetch(`/api/estoque/conferencias/${conferenciaId}`);
  if (!resp.ok) {
    if (resumo) resumo.textContent = "Nao foi possivel carregar a conferencia.";
    if (itensBody) itensBody.innerHTML = `<tr><td colspan="7">Falha ao carregar itens.</td></tr>`;
    return;
  }

  const data = await resp.json();
  estoqueState.conferenciaAtual = data;
  const conf = data?.conferencia || {};
  const itens = Array.isArray(data?.itens) ? data.itens : [];

  if (resumo) {
    resumo.innerHTML = `
      <div><b>Nota:</b> ${_escHtml(conf.numero_nota || conf.chave_acesso || "-")}</div>
      <div><b>Emitente:</b> ${_escHtml(conf.emitente_nome || "-")}</div>
      <div><b>Destinatario:</b> ${_escHtml(conf.destinatario_nome || "-")}</div>
      <div><b>Emissao:</b> ${_escHtml(_fmtDateBr(conf.data_emissao) || conf.data_emissao || "-")}</div>
      <div><b>Status:</b> ${_escHtml(conf.status || "pendente")}</div>
    `;
  }

  if (itensBody) {
    itensBody.innerHTML = itens.length ? itens.map((item) => `
      <tr>
        <td>
          <select class="estoque-produto-conferencia" data-item-id="${_escAttr(String(item.id || 0))}">
            ${_optionsProdutosEstoqueConferencia(item.produto_id, item)}
          </select>
        </td>
        <td>${_escHtml(item.codigo_barras || item.codigo_produto_nfe || "-")}</td>
        <td>
          <div class="estoque-total-un-cell">
            <span>${_escHtml(item.embalagem_tipo || item.unidade || "UN")}</span>
            ${item.fator_inferido ? '<span class="estoque-pack-hint">inferido</span>' : ""}
          </div>
        </td>
        <td>${_escHtml(_estoqueFormatQtd(item.quantidade_embalagem || item.quantidade_nfe))}</td>
        <td><span class="${item.fator_inferido ? "estoque-import-item-total-un is-inferred" : ""}">${_escHtml(_estoqueFormatQtd(item.quantidade_nfe))}</span></td>
        <td><input type="number" class="estoque-qtd-conferida" data-item-id="${_escAttr(String(item.id))}" min="0" step="0.001" value="${_escAttr(String(item.quantidade_conferida || item.quantidade_nfe || 0))}"></td>
        <td>R$ ${_escHtml(_fmtMoney(item.valor_unitario))}</td>
      </tr>
    `).join("") : `<tr><td colspan="7">Nenhum item encontrado para esta NF-e.</td></tr>`;
  }

  document.querySelectorAll("#estoqueConferenciasBody tr").forEach((row) => row.classList.remove("is-selected"));
  document.querySelectorAll("#estoqueConferenciasBody button").forEach((btn) => {
    const onclick = btn.getAttribute("onclick") || "";
    if (onclick.includes(`(${conferenciaId})`)) {
      btn.closest("tr")?.classList.add("is-selected");
    }
  });
}

async function confirmarConferenciaEstoque(){
  const atual = estoqueState.conferenciaAtual;
  if (!atual?.conferencia?.id) {
    alert("Selecione uma NF-e para conferir.");
    return;
  }

  const itens = Array.from(document.querySelectorAll(".estoque-qtd-conferida")).map((input) => ({
    id: Number(input.dataset.itemId || 0),
    quantidade_conferida: Number((input.value || "").trim() || 0),
    produto_id: Number(document.querySelector(`.estoque-produto-conferencia[data-item-id="${input.dataset.itemId || 0}"]`)?.value || 0),
  }));
  const origem_setor = (document.getElementById("estoqueOrigemSetor")?.value || "").trim() || "Fabrica";
  const destino_setor = (document.getElementById("estoqueDestinoSetor")?.value || "").trim() || "Almoxarifado";

  const resp = await apiFetch(`/api/estoque/conferencias/${atual.conferencia.id}/confirmar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ itens, origem_setor, destino_setor }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    alert(data?.erro || "Falha ao consolidar a conferencia.");
    return;
  }

  estoqueState.conferenciaAtual = data;
  alert("Conferencia consolidada com sucesso no almoxarifado.");
  await Promise.all([
    carregarSaldoEstoque(),
    carregarMovimentosEstoque(),
    carregarConferenciasEstoque(data?.conferencia?.id || null),
  ]);
  if (window.__dashView === "estoque") await renderDashboardEstoque();
}

async function carregarSaldoEstoque(){
  const body = document.getElementById("estoqueSaldoBody");
  const resumo = document.getElementById("estoqueConferenciaResumo");
  if (!body) return;
  const resp = await apiFetch("/api/estoque/posicao");
  if (!resp.ok) {
    body.innerHTML = `<tr><td colspan="9">Erro ao carregar posicao do estoque.</td></tr>`;
    if (resumo) resumo.textContent = "Nao foi possivel carregar a posicao atual do estoque.";
    return;
  }
  const payload = await resp.json();
  const dados = _estoqueRowsPayload(payload);
  const meta = _estoqueMetaPayload(payload);
  estoqueState.posicaoRows = dados;
  estoqueState.posicaoMeta = meta;
  renderFiltrosEstoque();
  renderProdutosLancamentoEstoqueSelect();
  if (resumo) {
    resumo.textContent = [
      `Referencia: ${_fmtDataCurtaBr(meta.data_referencia || "")}`,
      `Pendentes: ${meta.cargas_pendentes || 0}`,
      `Baixadas: ${meta.cargas_baixadas || 0}`,
      `Vendas dia: ${_estoqueFormatQtd(meta.vendas_dia_total || 0)}`,
      `Saidas dia: ${_estoqueFormatQtd(meta.saidas_dia_total || 0)}`,
    ].join(" | ");
  }
  renderSaldoEstoqueFiltrado();
}

function renderSaldoEstoqueFiltrado(){
  const body = document.getElementById("estoqueSaldoBody");
  if (!body) return;
  const dados = Array.isArray(estoqueState.posicaoRows) ? estoqueState.posicaoRows : [];
  const filtros = _estoqueFiltrosEscopo("Posicao");
  const filtrados = dados.filter((row) => _estoqueItemCombinaFiltros(row, filtros));
  body.innerHTML = filtrados.length ? _estoqueLinhasAgrupadas(filtrados, (r) => `
    <tr>
      <td>${_escHtml(r.produto_base_nome || r.nome_produto || "-")}</td>
      <td>${_escHtml(_estoqueCodigoReferencia(r))}</td>
      <td>${_escHtml(_estoqueFornecedorResumo(r))}</td>
      <td>${_escHtml(_estoqueCategoriaFornecedorResumo(r))}</td>
      <td>${_escHtml(_estoqueFormatQtd(r.entradas_total))}</td>
      <td>${_escHtml(_estoqueFormatQtd(r.saidas_total))}</td>
      <td>${_escHtml(_estoqueFormatQtd(r.quantidade_atual))}</td>
      <td>R$ ${_escHtml(_fmtMoney(r.ultimo_valor))}</td>
      <td>${_escHtml(_fmtDateBr(r.ultima_movimentacao))}</td>
    </tr>
  `, 9) : `<tr><td colspan="9">Sem itens no estoque para os filtros selecionados.</td></tr>`;
}

async function carregarMovimentosEstoque(){
  const body = document.getElementById("estoqueMovimentosBody");
  if (!body) return;
  const resp = await apiFetch("/api/estoque?limit=2000");
  if (!resp.ok) {
    body.innerHTML = `<tr><td colspan="12">Erro ao carregar historico do estoque.</td></tr>`;
    return;
  }
  const dados = await resp.json();
  estoqueState.movimentos = Array.isArray(dados) ? dados : [];
  renderFiltrosEstoque();
  renderMovimentosEstoqueFiltrado();
  renderRastreioLotesEstoque();
}

function renderMovimentosEstoqueFiltrado(){
  const body = document.getElementById("estoqueMovimentosBody");
  if (!body) return;
  const filtros = _estoqueFiltrosEscopo("Movimentos");
  const dados = (Array.isArray(estoqueState.movimentos) ? estoqueState.movimentos : [])
    .filter((row) => _estoqueItemCombinaFiltros(row, filtros));
  body.innerHTML = dados.length ? dados.map((r) => `
    <tr>
      <td>${_escHtml(_fmtDateBr(r.data_registro))}</td>
      <td>${_escHtml(r.numero_nota || "-")}</td>
      <td>${_escHtml(_estoqueCodigoReferencia(r))}</td>
      <td>${_escHtml(r.produto_base_nome || r.nome_produto || "-")}</td>
      <td>${_escHtml(_estoqueFornecedorResumo(r))}</td>
      <td>${_escHtml(_estoqueCategoriaFornecedorResumo(r))}</td>
      <td>${_escHtml(r.tipo_movimento || "entrada")}</td>
      <td>${_escHtml(_estoqueFormatQtd(r.quantidade))}</td>
      <td>R$ ${_escHtml(_fmtMoney(r.valor_unitario))}</td>
      <td>${_escHtml(_estoqueResumoFluxo(r))}</td>
      <td>${_escHtml(r.usuario_registro || "-")}</td>
      <td>
        ${r.referencia_tipo
          ? `<span class="hint-chip">${r.referencia_tipo === "importar_xml" ? "Confirmado via XML" : "Lancamento vinculado"}</span>`
          : `<button type="button" onclick="editarMovimentoEstoque(${Number(r.id || 0)})">Editar</button>
             <button type="button" onclick="excluirMovimentoEstoque(${Number(r.id || 0)})">Excluir</button>`}
      </td>
    </tr>
  `).join("") : `<tr><td colspan="12">Sem lancamentos de estoque para os filtros selecionados.</td></tr>`;
}

function renderRastreioLotesEstoque(){
  const body = document.getElementById("estoqueRastreioBody");
  const resumo = document.getElementById("estoqueRastreioResumo");
  if (!body) return;
  const filtros = _estoqueFiltrosEscopo("Rastreio");
  const dados = (Array.isArray(estoqueState.movimentos) ? estoqueState.movimentos : [])
    .filter((row) => _estoqueItemCombinaFiltros(row, filtros));
  const entradas = dados.filter((row) => String(row.tipo_movimento || "entrada").toLowerCase() === "entrada")
    .reduce((total, row) => total + (Number(row.quantidade || 0) || 0), 0);
  const saidas = dados.filter((row) => String(row.tipo_movimento || "entrada").toLowerCase() === "saida")
    .reduce((total, row) => total + (Number(row.quantidade || 0) || 0), 0);
  if (resumo) {
    resumo.textContent = `${dados.length} lancamento(s) rastreados | Entradas ${_estoqueFormatQtd(entradas)} | Saidas ${_estoqueFormatQtd(saidas)}`;
  }
  body.innerHTML = dados.length ? dados.map((r) => `
    <tr>
      <td>${_escHtml(_fmtDateBr(r.data_registro))}</td>
      <td>${_escHtml(r.numero_nota || "-")}</td>
      <td>${_escHtml(r.produto_base_nome || r.nome_produto || "-")}</td>
      <td>${_escHtml(_estoqueCodigoReferencia(r))}</td>
      <td>${_escHtml(_estoqueFornecedorResumo(r))}</td>
      <td>${_escHtml(_estoqueCategoriaFornecedorResumo(r))}</td>
      <td>${_escHtml(r.tipo_movimento || "entrada")}</td>
      <td>${_escHtml(_estoqueFormatQtd(r.quantidade))}</td>
      <td>R$ ${_escHtml(_fmtMoney(r.valor_unitario))}</td>
      <td>${_escHtml(_estoqueResumoFluxo(r))}</td>
    </tr>
  `).join("") : `<tr><td colspan="10">Sem lotes para os filtros selecionados.</td></tr>`;
}

async function editarMovimentoEstoque(id){
  const resp = await apiFetch("/api/estoque");
  if (!resp.ok) return alert("Nao foi possivel carregar o lancamento.");
  const dados = await resp.json();
  const item = (dados || []).find((r) => Number(r.id) === Number(id));
  if (!item) return alert("Lancamento nao encontrado.");

  const numero_nota = prompt("Numero da nota:", item.numero_nota || "");
  if (numero_nota == null) return;
  const codigoReferencia = prompt("Codigo:", item.codigo_produto_nfe || item.codigo_barras || "");
  if (codigoReferencia == null) return;
  const nome_produto = prompt("Produto:", item.nome_produto || "");
  if (nome_produto == null) return;
  const quantidadeTxt = prompt("Quantidade:", String(item.quantidade || 0));
  if (quantidadeTxt == null) return;
  const valorTxt = prompt("Valor unitario:", String(item.valor_unitario || 0));
  if (valorTxt == null) return;

  const up = await apiFetch(`/api/estoque/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      numero_nota,
      codigo_barras: item.codigo_barras ? codigoReferencia : "",
      codigo_produto_nfe: item.codigo_produto_nfe || !item.codigo_barras ? codigoReferencia : "",
      nome_produto,
      quantidade: Number(String(quantidadeTxt).replace(",", ".")),
      valor_unitario: Number(String(valorTxt).replace(",", ".")),
      tipo_movimento: item.tipo_movimento || "entrada",
      origem_setor: item.origem_setor || "Fabrica",
      destino_setor: item.destino_setor || "Almoxarifado",
    }),
  });
  const data = await up.json().catch(() => ({}));
  if (!up.ok) return alert(data?.erro || "Erro ao editar lancamento.");
  await carregarEstoque();
  if (window.__dashView === "estoque") await renderDashboardEstoque();
}

async function excluirMovimentoEstoque(id){
  if (!confirm("Deseja realmente excluir este item lancado?")) return;
  const resp = await apiFetch(`/api/estoque/${id}`, { method: "DELETE" });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao excluir lancamento.");
  await carregarEstoque();
  if (window.__dashView === "estoque") await renderDashboardEstoque();
}

async function carregarEstoque(){
  renderEstoqueImportPreview();
  atualizarStatusCodbarSistema();
  await Promise.all([
    carregarSaldoEstoque(),
    carregarMovimentosEstoque(),
    ensureProdutosEstoqueCache(),
    carregarImportacoesXmlEstoque(),
  ]);
  renderProdutosLancamentoEstoqueSelect();
  await carregarProdutosEstoqueCadastro();
}

async function salvarMovimentoEstoque(){
  const produtoId = Number(document.getElementById("estoqueProdutoSelect")?.value || 0);
  const codigo_barras = (document.getElementById("estoqueCodigoBarras")?.value || "").trim();
  const codigo_produto_nfe = (document.getElementById("estoqueCodigoProdutoNfe")?.value || "").trim();
  const numero_nota = ((document.getElementById("estoqueNumeroNota")?.value || "").trim() || codigo_produto_nfe || codigo_barras);
  const nome_produto = (document.getElementById("estoqueNomeProduto")?.value || "").trim();
  const tipo_movimento = (document.getElementById("estoqueTipoMovimento")?.value || "entrada").trim().toLowerCase() === "saida" ? "saida" : "entrada";
  const quantidadeDigitada = Number((document.getElementById("estoqueQuantidade")?.value || "").trim() || 0);
  const valor_unitario = Number((document.getElementById("estoqueValor")?.value || "").trim() || 0);
  const codigoDigits = _digitsOnly(codigo_barras);
  const produtoSelecionado = produtoId > 0
    ? (estoqueState.cadastroProdutos || []).find((item) => Number(item.id || 0) === produtoId) || null
    : null;
  const metaLancamento = _estoqueResolverFatorProduto({
    produto_id: produtoId,
    codigo_barras,
    codigo_produto_nfe,
    nome_produto,
  }, produtoSelecionado);
  const quantidade = produtoSelecionado
    ? Number((quantidadeDigitada * (Number(metaLancamento.fator_embalagem || 0) || 0)).toFixed(3))
    : quantidadeDigitada;

  if (codigoDigits.length === 44) {
    return alert("Esse codigo parece ser a chave da NF-e. Use o campo de importacao do XML para lancar a nota completa.");
  }
  if (!nome_produto) return alert("Informe o nome do produto.");
  if (!(quantidadeDigitada > 0)) return alert("Informe uma quantidade valida.");
  if (produtoSelecionado && metaLancamento.bloqueado) {
    return alert("Esse produto ainda nao tem um fator explicito para a apresentacao selecionada. Revise o cadastro antes de lancar.");
  }
  if (produtoSelecionado && metaLancamento.confirmacao_pendente) {
    if (!confirm(`${tipo_movimento === "saida" ? "Confirmar a saida" : "Confirmar a entrada"} deste produto?\n${_estoqueConfirmacaoLancamentoTexto({
      nome_produto,
      quantidade_embalagem: quantidadeDigitada,
      quantidade_unidades: quantidade,
      embalagem_tipo: metaLancamento.embalagem_tipo,
      fator_embalagem: metaLancamento.fator_embalagem,
      motivo_confirmacao: metaLancamento.motivo_confirmacao,
      grupo_estoque: metaLancamento.grupo_estoque,
      produto_base_nome: metaLancamento.produto_base_nome,
    }, metaLancamento)}`)) {
      return;
    }
  } else if (!produtoSelecionado) {
    if (!confirm(`Produto sem cadastro explicito selecionado.\nO sistema vai lancar ${_estoqueFormatQtd(quantidadeDigitada)} unidade(s) exatamente como informado.\nConfirma o lancamento?`)) {
      return;
    }
  }

  const resp = await apiFetch("/api/estoque", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      produto_id: produtoId || null,
      codigo_barras,
      codigo_produto_nfe,
      numero_nota,
      nome_produto,
      quantidade,
      valor_unitario,
      tipo_movimento,
      origem_setor: tipo_movimento === "saida" ? "Almoxarifado" : "Fabrica",
      destino_setor: tipo_movimento === "saida" ? "Saida" : "Almoxarifado",
    }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao registrar item no estoque.");

  const importStatus = document.getElementById("estoqueNfeImportStatus");
  if (importStatus && data?.produto_criado) {
    importStatus.textContent = `Produto "${nome_produto}" cadastrado automaticamente no estoque.`;
  }

  const numeroNotaEl = document.getElementById("estoqueNumeroNota");
  const quantidadeEl = document.getElementById("estoqueQuantidade");
  const valorEl = document.getElementById("estoqueValor");
  if (numeroNotaEl) numeroNotaEl.value = "";
  if (quantidadeEl) quantidadeEl.value = "";
  if (valorEl) valorEl.value = "";
  if (produtoId > 0) {
    selecionarProdutoLancamentoEstoque();
  } else {
    ["estoqueCodigoBarras", "estoqueCodigoProdutoNfe", "estoqueNomeProduto"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = "";
    });
  }

  await carregarEstoque();
  if (window.__dashView === "estoque") await renderDashboardEstoque();
  document.getElementById("estoqueQuantidade")?.focus();
}

async function renderFretes() {
  await ensureCadastrosCache();

  const presentes = new Set();
  fretes.forEach((f) => {
    if (_freteOcultoNoKanban(f)) return;
    if (!_freteCombinaBusca(f, freteKanbanFiltro)) return;
    presentes.add(String(f.id));
    _renderOrUpdateFreteCard(f);
  });

  document.querySelectorAll(".card[data-frete-id]").forEach((card) => {
    const id = card.dataset.freteId || "";
    if (presentes.has(id) || _isFreteCardLocked(id)) return;
    const state = freteDraftState.get(_freteKey(id));
    if (state) _clearFreteSaveTimer(state);
    freteDraftState.delete(_freteKey(id));
    card.remove();
  });

  ativarDragDrop();
  ativarDragDropMobile();
  _agendarEqualizacaoAlturaKanban();
}

async function carregarFretes() {
  const r = await apiFetch("/api/fretes");
  if (!r.ok) throw new Error("Erro ao carregar fretes.");
  fretes = await r.json();
  // Arquivar automaticamente cards elegíveis
  await _arquivarFretesAutomaticamente();
  await renderFretes();
  if (window.__cargasView === "escala") {
    await renderEscala();
  }
}

window.onload = async () => {

  // 1) Menu mobile: bind IMEDIATO (não depende de API)
  const toggle = document.getElementById("menuToggle");
  const overlay = document.querySelector(".menu-overlay");

  if (toggle) {
    toggle.textContent = "☰";
    toggle.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); toggleMenuMobile(); });
    toggle.addEventListener("touchstart", (e) => { e.preventDefault(); e.stopPropagation(); toggleMenuMobile(); }, { passive:false });
  }
  if (overlay) {
    overlay.addEventListener("click", () => toggleMenuMobile(false));
    overlay.addEventListener("touchstart", () => toggleMenuMobile(false), { passive:true });
  }

  // Failsafe de inicialização: evita tela escurecida caso algum overlay tenha ficado ativo.
  try {
    toggleMenuMobile(false);
    document.querySelectorAll(".foto-modal").forEach((m) => m.classList.add("hidden"));
    document.body.classList.remove("menu-open");
  } catch {}
  _syncBlockingPopupState();
  bindEstoqueScannerInput();
  alternarModoNovaCameraConfig();
  verificarRetornoPortalNfePendente();
  setEstoqueView(window.__estoqueView || "lancar");
  renderFiltrosRelatorioFretes();

  // 2) Status pode rodar sem travar nada
  verificarStatus();
  setInterval(verificarStatus, 5000);

  // 3) Sessão antes dos demais fetches, para o usuário logado aparecer imediatamente.
  let okSessao = false;
  try { okSessao = await restaurarSessaoLogin(); } catch {}
  if (LOGIN_BYPASS) {
    fecharLoginModal();
    atualizarUsuarioLogadoUI();
  } else if (!okSessao) {
    abrirLoginModal();
  } else {
    fecharLoginModal();
    atualizarUsuarioLogadoUI();
  }

  // 4) Carregar dados EM PARALELO (não sequencial)
  Promise.allSettled([
    carregarSelectsNovoFrete(),
    carregarFretes(),
    carregarEstoque(),
    renderCadastros(),
    carregarPontosVenda(),
    carregarDevolucoes(),
    atualizarDash(),
    carregarComissaoLancamentos(),
    carregarComissaoCadastros()
  ]).then(() => {
    // Drag&drop depois que o kanban estiver renderizado
    try { ativarDragDrop(); } catch {}
    try { _agendarEqualizacaoAlturaKanban(0); } catch {}
    try { initChatInterno(); } catch {}
  });

  ensureCadastrosCache().catch(()=>{});
  // 5) Auto-atualização (não precisa esperar o resto)
  setInterval(async () => {
    try {
      const tarefas = [carregarFretes(), atualizarDash()];
      if (window.__dashView === "frota") {
        tarefas.push(renderDashboardFrota());
      } else if (window.__dashView === "estoque") {
        tarefas.push(renderDashboardEstoque());
      }
      const secEstoque = document.getElementById("estoque");
      if (secEstoque && secEstoque.classList.contains("activeSection")) {
        tarefas.push(carregarEstoque());
      }
      await Promise.all(tarefas);
    } catch (e) {
      console.warn("Falha ao atualizar automaticamente:", e);
    }
  }, 20000);

  setInterval(async () => {
    try {
      const sec = document.getElementById("config");
      if (sec && sec.classList.contains("activeSection")) {
        const v = window.__configView || "status";
        if (v === "logs") {
          await carregarLogsExclusoes();
        } else if (v === "cameras") {
          await Promise.all([verificarStatus(), carregarConfigCameras()]);
        } else {
          await verificarStatus();
        }
      }
    } catch {}
  }, 7000);
};

window.addEventListener("resize", () => {
  _agendarEqualizacaoAlturaKanban(60);
});
