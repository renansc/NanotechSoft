//////////////////////////////////////////////////////
// SISTEMA RIO BRANCO - VERSÃO API (MENU MOBILE FIX + ANIMAÇÃO)
//////////////////////////////////////////////////////

let fretes = [];
let freteKanbanFiltro = "";
const FRETE_AUTO_SAVE_DELAY_MS = 900;
const ESTOQUE_CAMERA_SCAN_INTERVAL_MS = 450;
const freteDraftState = new Map();

let cacheCadastros = {
  motoristas: null,
  veiculos: null,
  cargas: null,
  conferentes: null,
};

let cacheUsuarios = null;
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
let nfePortalState = { lastKey: "", lastAt: 0, lastMode: "", lastContext: "" };
let vendasState = {
  view: "relatorio",
  lastPayload: null,
};
let estoqueState = {
  view: "lancar",
  conferencias: [],
  conferenciaAtual: null,
  importDraft: null,
  importDraftDirty: false,
  lastPortalPreviewSignature: "",
  cadastroProdutos: [],
  cadastroProdutoEditId: 0,
  manualPhotoUrl: "",
  manualPhotoName: "",
  cameraStream: null,
  cameraTimer: null,
  scanningCamera: false,
  cameraTargetFieldId: "",
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
async function apiFetch(url, options={}){
  const h = { ...(options.headers || {}) };
  if (usuarioLogado?.id) h["X-Usuario-Id"] = String(usuarioLogado.id);
  if (usuarioLogado?.nome) h["X-Usuario-Nome"] = String(usuarioLogado.nome);
  if (usuarioLogado?.login) h["X-Usuario-Login"] = String(usuarioLogado.login);
  if (!h["X-Usuario-Logado"] && (usuarioLogado?.nome || usuarioLogado?.login)) {
    h["X-Usuario-Logado"] = `${usuarioLogado?.nome || ""} (${usuarioLogado?.login || ""})`.trim();
  }
  const opt = {
    cache: 'no-store',
    headers: { ...h, 'Cache-Control':'no-cache' },
    ...options,
  };
  return fetch(url + (url.includes('?') ? '&' : '?') + '_=' + Date.now(), opt);
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

  await fetch(`/api/${tipo}/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nome: novoNome }),
  });

  await renderCadastros();
  await carregarSelectsNovoFrete();
}

async function salvarCadastro(tipo, inputId) {
  const inp = document.getElementById(inputId);
  const nome = (inp?.value || "").trim();
  if (!nome) return alert("Informe um nome.");

  const resp = await apiFetch(`/api/${tipo}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nome }),
  });

  if (!resp.ok) {
    const t = await resp.text();
    console.log("ERRO ao salvar cadastro:", resp.status, t);
    alert("Erro ao salvar (veja o console F12).");
    return;
  }

  if (inp) inp.value = "";

  // Invalida cache (para selects e cards)
  cacheCadastros[tipo] = null;

  await renderCadastros();
  await carregarSelectsNovoFrete();

  // Se este cadastro impacta a devolução (conferentes), atualiza também
  try { await carregarSelectsDevolucao?.(); } catch {}
}

async function carregarUsuariosCadastro() {
  const resp = await apiFetch("/api/usuarios");
  if (!resp.ok) return [];
  return await resp.json();
}

function _usuarioSipPayloadFromInputs(prefix = "novoUsuario") {
  return {
    sip_habilitado: !!document.getElementById(`${prefix}SipHabilitado`)?.checked,
    sip_usuario: (document.getElementById(`${prefix}SipUsuario`)?.value || "").trim(),
    sip_senha: (document.getElementById(`${prefix}SipSenha`)?.value || "").trim(),
    sip_ramal: (document.getElementById(`${prefix}SipRamal`)?.value || "").trim(),
    codbar_modo: (document.getElementById(`${prefix}CodbarModo`)?.value || "bip").trim() || "bip",
  };
}

async function salvarUsuarioCadastro() {
  try {
    const nome = (document.getElementById("novoUsuarioNome")?.value || "").trim();
    const login = (document.getElementById("novoUsuarioLogin")?.value || "").trim();
    const senha = (document.getElementById("novoUsuarioSenha")?.value || "").trim();
    const sip = _usuarioSipPayloadFromInputs("novoUsuario");

    if (!nome || !login || !senha) {
      alert("Informe nome, login e senha.");
      return;
    }

    const resp = await apiFetch("/api/usuarios", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nome, login, senha, ...sip }),
    });

    if (!resp.ok) {
      const j = await resp.json().catch(() => null);
      alert(j?.erro || "Erro ao cadastrar usuário.");
      return;
    }

    const nomeEl = document.getElementById("novoUsuarioNome");
    const loginEl = document.getElementById("novoUsuarioLogin");
    const senhaEl = document.getElementById("novoUsuarioSenha");
    const sipHabEl = document.getElementById("novoUsuarioSipHabilitado");
    const sipUsuarioEl = document.getElementById("novoUsuarioSipUsuario");
    const sipSenhaEl = document.getElementById("novoUsuarioSipSenha");
    const sipRamalEl = document.getElementById("novoUsuarioSipRamal");
    const codbarEl = document.getElementById("novoUsuarioCodbarModo");
    if (nomeEl) nomeEl.value = "";
    if (loginEl) loginEl.value = "";
    if (senhaEl) senhaEl.value = "";
    if (sipHabEl) sipHabEl.checked = false;
    if (sipUsuarioEl) sipUsuarioEl.value = "";
    if (sipSenhaEl) sipSenhaEl.value = "";
    if (sipRamalEl) sipRamalEl.value = "";
    if (codbarEl) codbarEl.value = "bip";

    cacheUsuarios = null;
    await renderUsuariosCadastro();
    await carregarUsuariosChat(true);

    // Failsafe: garante que nenhum overlay de UI fique travado.
    try { toggleMenuMobile(false); } catch {}
    try {
      document.querySelectorAll(".foto-modal").forEach((m) => m.classList.add("hidden"));
    } catch {}
  } catch (error) {
    console.error("Erro ao cadastrar usuario:", error);
    alert(error?.message || "Erro inesperado ao cadastrar usuario.");
  }
}

async function editarUsuarioCadastro(id) {
  try {
    let user = (cacheUsuarios || []).find((u) => String(u.id) === String(id));
    if (!user) {
      const respUser = await apiFetch(`/api/usuarios/${id}`);
      if (!respUser.ok) {
        alert("Usuario nao encontrado.");
        return;
      }
      user = await respUser.json().catch(() => null);
    }
    if (!user) {
      alert("Usuario nao encontrado.");
      return;
    }

    const novoNome = prompt("Editar nome do usuario:", user.nome || "");
    if (novoNome === null) return;

    const novoLogin = prompt("Editar login:", user.login || "");
    if (novoLogin === null) return;

    const novaSenha = prompt("Nova senha (deixe em branco para manter):", "");
    if (novaSenha === null) return;

    const novoSipHabilitado = prompt("Permitir discagem externa para este usuario? (s/n)", user.sip_habilitado ? "s" : "n");
    if (novoSipHabilitado === null) return;

    const novoSipUsuario = prompt("Usuario SIP (vazio usa o login):", user.sip_usuario || user.login || "");
    if (novoSipUsuario === null) return;

    const novoSipRamal = prompt("Ramal interno de 4 digitos (vazio gera automatico):", user.sip_ramal || "");
    if (novoSipRamal === null) return;

    const novaSipSenha = prompt("Senha SIP (vazio mantém/usa a senha do login):", "");
    if (novaSipSenha === null) return;

    const novoCodbarModo = prompt("CODBAR deste usuario? (bip/camera)", user.codbar_modo || "bip");
    if (novoCodbarModo === null) return;

    const payload = {
      nome: (novoNome || "").trim(),
      login: (novoLogin || "").trim(),
      sip_habilitado: ["s", "sim", "y", "yes", "1", "true"].includes(String(novoSipHabilitado || "").trim().toLowerCase()),
      sip_usuario: (novoSipUsuario || "").trim(),
      sip_ramal: (novoSipRamal || "").trim(),
      codbar_modo: String(novoCodbarModo || "bip").trim().toLowerCase() === "camera" ? "camera" : "bip",
    };
    if ((novaSenha || "").trim()) payload.senha = novaSenha.trim();
    if ((novaSipSenha || "").trim()) payload.sip_senha = novaSipSenha.trim();

    const resp = await apiFetch(`/api/usuarios/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      const j = await resp.json().catch(() => null);
      alert(j?.erro || "Erro ao atualizar usuario.");
      return;
    }

    cacheUsuarios = null;
    await renderUsuariosCadastro();
    await carregarUsuariosChat(true);
    if (String(usuarioLogado?.id || "") === String(id)) {
      usuarioLogado = { ...(usuarioLogado || {}), ...payload, id: user.id };
      _salvarSessaoLogin(usuarioLogado);
      atualizarUsuarioLogadoUI();
      await initSipClient(true).catch(() => {});
    }
  } catch (error) {
    console.error("Erro ao atualizar usuario:", error);
    alert(error?.message || "Erro inesperado ao atualizar usuario.");
  }
}

async function deletarUsuarioCadastro(id) {
  if (!confirm("Deseja excluir este usuário?")) return;

  const resp = await apiFetch(`/api/usuarios/${id}`, { method: "DELETE" });
  if (!resp.ok) {
    const j = await resp.json().catch(() => null);
    alert(j?.erro || "Erro ao excluir usuário.");
    return;
  }

  cacheUsuarios = null;
  await renderUsuariosCadastro();
  await carregarUsuariosChat(true);
  if (String(usuarioLogado?.id || "") === String(id)) {
    _logoutSessaoLocal(true, "Usuario removido. Faca login novamente.");
    return;
  }
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

  if (!nome) return alert("Informe o nome do veículo.");

  await fetch(`/api/veiculos`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nome, placa, modelo, km_atual, intervalo_manut_km, intervalo_oleo_km }),
  });

  if (document.getElementById("novoVeiculoNome")) document.getElementById("novoVeiculoNome").value = "";
  if (document.getElementById("frota_placa")) document.getElementById("frota_placa").value = "";
  if (document.getElementById("frota_modelo")) document.getElementById("frota_modelo").value = "";
  if (document.getElementById("frota_km")) document.getElementById("frota_km").value = "";
  if (document.getElementById("frota_int_manut")) document.getElementById("frota_int_manut").value = "";
  if (document.getElementById("frota_int_oleo")) document.getElementById("frota_int_oleo").value = "";

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
  return await r.json();
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

  if (!nome) return alert("Informe o nome do veículo.");

  const resp = await fetch(`/api/veiculos/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nome, placa, modelo, km_atual, intervalo_manut_km, intervalo_oleo_km }),
  });

  if (!resp.ok) {
    const t = await resp.text();
    console.log("ERRO ao salvar veículo:", resp.status, t);
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
        <input id="v_modelo_${v.id}" value="${_escAttr(modelo)}" placeholder="Modelo" style="width:170px;">
        <input id="v_km_${v.id}" value="${_escAttr(km)}" placeholder="KM" type="number" style="width:110px;">
        <input id="v_int_manut_${v.id}" value="${_escAttr(v.intervalo_manut_km ?? '')}" placeholder="Int. Manut (KM)" type="number" style="width:140px;">
        <input id="v_int_oleo_${v.id}" value="${_escAttr(v.intervalo_oleo_km ?? '')}" placeholder="Int. Óleo (KM)" type="number" style="width:140px;">
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

async function renderCadastros() {
  const tipos = [
    { tipo: "motoristas", listaId: "listaMotoristas" },
    { tipo: "veiculos", listaId: "listaVeiculos" },
    { tipo: "conferentes", listaId: "listaConferentes" },
    { tipo: "cargas", listaId: "listaCargas" },
  ];
  const emptyMap = {
    motoristas: "Nenhum motorista cadastrado.",
    veiculos: "Nenhum veiculo cadastrado.",
    conferentes: "Nenhum conferente cadastrado.",
    cargas: "Nenhuma carga cadastrada.",
  };

  for (let item of tipos) {
    let dados = _ordenarListaNatural(await carregarCadastro(item.tipo));
    let lista = document.getElementById(item.listaId);
    if (!lista) continue;

    if (item.tipo === "veiculos") {
      lista.innerHTML = dados.length ? dados.map(veiculoRowTemplate).join("") : cadastroEmptyItem(emptyMap[item.tipo]);
    } else {
      lista.innerHTML = dados.length ? dados
        .map(
          (d) => `
          <li>
            <span>${_escHtml(d.nome)}</span>
            <div>
              <button onclick="editarCadastro('${item.tipo}', ${d.id}, '${_escJsString(d.nome)}')">✏</button>
              <button onclick="deletar('${item.tipo}', ${d.id})">❌</button>
            </div>
          </li>
        `
        )
        .join("") : cadastroEmptyItem(emptyMap[item.tipo]);
    }
  }

  try { await renderUsuariosCadastro(); } catch (e) { console.warn("usuarios cadastro erro:", e); }
}

function _escJsString(v) {
  return String(v ?? "").replaceAll("\\", "\\\\").replaceAll("'", "\\'");
}

async function renderUsuariosCadastro() {
  if (!cacheUsuarios) {
    cacheUsuarios = await carregarUsuariosCadastro();
  }

  const lista = document.getElementById("listaUsuarios");
  if (!lista) return;

  const usuarios = cacheUsuarios || [];
  lista.innerHTML = usuarios.length ? usuarios
    .map((u) => {
      const ramal = _escHtml(u.sip_ramal || u.sip_usuario || "pendente");
      const permissaoExterna = u.sip_habilitado ? "externo liberado" : "interno apenas";
      const codbar = (u.codbar_modo || "bip") === "camera" ? "camera/webcam" : "bip/leitor";
      const sipLabel = ` | Ramal: ${ramal} | ${permissaoExterna} | CODBAR: ${_escHtml(codbar)}`;
      return `
        <li>
          <span>${_escHtml(u.nome)} (${_escHtml(u.login)})${sipLabel}</span>
          <div>
            <button onclick="editarUsuarioCadastro(${u.id})">✏</button>
            <button onclick="deletarUsuarioCadastro(${u.id})">❌</button>
          </div>
        </li>
      `;
    })
    .join("") : cadastroEmptyItem("Nenhum usuario cadastrado.");
}

async function ensureCadastrosCache() {
  if (!cacheCadastros.motoristas) {
    cacheCadastros.motoristas = _ordenarListaNatural(await (await apiFetch("/api/motoristas")).json());
  }
  if (!cacheCadastros.veiculos) {
    cacheCadastros.veiculos = _ordenarListaNatural(await (await apiFetch("/api/veiculos")).json());
  }
  if (!cacheCadastros.cargas) {
    cacheCadastros.cargas = _ordenarListaNatural(await (await apiFetch("/api/cargas")).json());
  }  if (!cacheCadastros.conferentes) {
    cacheCadastros.conferentes = _ordenarListaNatural(await (await apiFetch("/api/conferentes")).json());
  }
}

function optionsFrom(lista, selectedId) {
  const sel = selectedId == null ? "" : String(selectedId);
  return `<option value="">-</option>` + _ordenarListaNatural(lista)
    .map((i) => {
      const v = String(i.id);
      const s = v === sel ? "selected" : "";
      return `<option value="${v}" ${s}>${i.nome}</option>`;
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
  let data = {};
  try {
    data = await resp.json();
  } catch {}
  if (!resp.ok || data?.ok === false) {
    throw new Error(data?.erro || "Erro ao atualizar frete.");
  }
  if (data?.frete) _setFreteLocal(data.frete);
  await atualizarDash();
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
function toggleDashboardSubmenu(ev){
  // No desktop, hover resolve. No mobile, toca para abrir/fechar.
  if (!ev) return;
  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (!isMobile) { openDashboardView(null,'resumo'); return; } // desktop: clique abre resumo
  ev.preventDefault();
  ev.stopPropagation();
  const mi = ev.currentTarget;
  if (mi && mi.classList.contains("has-submenu")) {
    mi.classList.toggle("open");
  }
}

function openDashboardView(ev, view){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  // ativa tab dashboard
  const dashMenu = document.querySelector('.menu-item.has-submenu[data-tab="dashboard"]');
  showTab("dashboard", dashMenu);

  // marca submenu ativo
  document.querySelectorAll("#submenuDashboard .submenu-item").forEach(x=>x.classList.remove("active"));
  const target = (view === "frota") ? 1 : 0;
  const items = document.querySelectorAll("#submenuDashboard .submenu-item");
  if (items && items[target]) items[target].classList.add("active");

  setDashboardView(view);

  // fecha submenu no mobile
  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && dashMenu) dashMenu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
}

function setDashboardView(view){
  window.__dashView = view;
  const vResumo = document.getElementById("dashViewResumo");
  const vFrota = document.getElementById("dashViewFrota");
  if (vResumo) vResumo.classList.toggle("hidden", view === "frota");
  if (vFrota) vFrota.classList.toggle("hidden", view !== "frota");

  if (view === "frota") {
    renderDashboardFrota().catch(e=>console.warn("dash frota erro:", e));
  } else {
    // mantém o dash principal
    atualizarDash().catch(()=>{});
  }
}

function toggleCadastrosSubmenu(ev){
  if (!ev) return;
  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (!isMobile) { openCadastrosView(null, window.__cadastrosView || "motoristas"); return; }
  ev.preventDefault();
  ev.stopPropagation();
  const mi = ev.currentTarget;
  if (mi && mi.classList.contains("has-submenu")) mi.classList.toggle("open");
}

function openCadastrosView(ev, view){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const menu = document.querySelector('.menu-item.has-submenu[data-tab="cadastros"]');
  window.__cadastrosView = view;
  showTab("cadastros", menu);

  document.querySelectorAll("#submenuCadastros .submenu-item").forEach((x) => x.classList.remove("active"));
  const map = { motoristas: 0, conferentes: 1, veiculos: 2, usuarios: 3, comissao: 4 };
  const target = map[view] ?? 0;
  const items = document.querySelectorAll("#submenuCadastros .submenu-item");
  if (items && items[target]) items[target].classList.add("active");

  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && menu) menu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
}

function setCadastrosView(view){
  window.__cadastrosView = view;
  const views = {
    motoristas: document.getElementById("cadastrosViewMotoristas"),
    conferentes: document.getElementById("cadastrosViewConferentes"),
    veiculos: document.getElementById("cadastrosViewVeiculos"),
    usuarios: document.getElementById("cadastrosViewUsuarios"),
    comissao: document.getElementById("cadastrosViewComissao"),
  };
  Object.entries(views).forEach(([key, el]) => {
    if (el) el.classList.toggle("hidden", key !== view);
  });
  document.querySelectorAll("#submenuCadastros .submenu-item").forEach((item) => item.classList.remove("active"));
  const map = { motoristas: 0, conferentes: 1, veiculos: 2, usuarios: 3, comissao: 4 };
  const items = document.querySelectorAll("#submenuCadastros .submenu-item");
  const target = map[view] ?? 0;
  if (items && items[target]) items[target].classList.add("active");
  if (view === "comissao") {
    carregarComissaoCadastros().catch(() => {});
  }
}

function toggleGestaoFrotaSubmenu(ev){
  if (!ev) return;
  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (!isMobile) { openGestaoFrotaView(null, "registrar"); return; }
  ev.preventDefault();
  ev.stopPropagation();
  const mi = ev.currentTarget;
  if (mi && mi.classList.contains("has-submenu")) mi.classList.toggle("open");
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
}

function toggleComissaoSubmenu(ev){
  if (!ev) return;
  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (!isMobile) { openComissaoView(null, "lancamento"); return; }
  ev.preventDefault();
  ev.stopPropagation();
  const mi = ev.currentTarget;
  if (mi && mi.classList.contains("has-submenu")) mi.classList.toggle("open");
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
  if (!ev) return;
  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (!isMobile) { openVendasView(null, "relatorio"); return; }
  ev.preventDefault();
  ev.stopPropagation();
  const mi = ev.currentTarget;
  if (mi && mi.classList.contains("has-submenu")) mi.classList.toggle("open");
}

function openVendasView(ev, view){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const menu = document.querySelector('.menu-item.has-submenu[data-tab="vendas"]');
  window.__vendasView = "relatorio";
  showTab("vendas", menu);

  document.querySelectorAll("#submenuVendas .submenu-item").forEach((x) => x.classList.remove("active"));
  const items = document.querySelectorAll("#submenuVendas .submenu-item");
  if (items && items[0]) items[0].classList.add("active");

  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && menu) menu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
}

function setVendasView(view){
  window.__vendasView = "relatorio";
  vendasState.view = "relatorio";
  const rel = document.getElementById("vendasViewRelatorio");
  if (rel) rel.classList.toggle("hidden", false);
  carregarRelatorioVendas().catch((err) => {
    console.warn("relatorio vendas erro:", err);
  });
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

function selecionarVendedorRelatorioVendas(chave = ""){
  const select = document.getElementById("vendasRelVendedor");
  if (select) select.value = chave || "";
  carregarRelatorioVendas().catch(() => {});
}

function renderRelatorioVendas(payload = {}){
  vendasState.lastPayload = payload;
  const resumo = payload?.resumo_geral || {};
  const vendedores = Array.isArray(payload?.vendedores) ? payload.vendedores : [];
  const cidades = Array.isArray(payload?.cidades) ? payload.cidades : [];
  const produtos = Array.isArray(payload?.produtos) ? payload.produtos : [];
  const detalhes = Array.isArray(payload?.detalhes_vendedor) ? payload.detalhes_vendedor : [];
  const arquivo = payload?.arquivo || {};

  const infoEl = document.getElementById("vendasRelArquivoInfo");
  if (infoEl) {
    const vendedorFiltro = document.getElementById("vendasRelVendedor")?.value || "";
    const escopo = vendedorFiltro ? `Filtro de vendedor aplicado: ${vendedorFiltro}.` : "Visao geral de todos os vendedores.";
    infoEl.textContent = `Arquivo: ${arquivo.nome || "-"} | Atualizado em: ${arquivo.atualizado_em || "-"} | ${escopo}`;
  }

  const cardsEl = document.getElementById("vendasRelResumoCards");
  if (cardsEl) {
    cardsEl.innerHTML = [
      _resumoCardVendas("Valor liquido", _fmtMoneyVendas(resumo.valor_liquido)),
      _resumoCardVendas("Valor venda", _fmtMoneyVendas(resumo.valor_venda)),
      _resumoCardVendas("Valor devolvido", _fmtMoneyVendas(resumo.valor_devolvido)),
      _resumoCardVendas("Notas", _fmtNumVendas(resumo.notas)),
      _resumoCardVendas("Clientes", _fmtNumVendas(resumo.clientes)),
      _resumoCardVendas("Itens", _fmtNumVendas(resumo.itens)),
    ].join("");
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
    const vendedorFiltro = document.getElementById("vendasRelVendedor")?.value || "";
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
  if (infoEl) infoEl.textContent = "Carregando relatorio de vendas...";

  const params = new URLSearchParams();
  const vendedor = document.getElementById("vendasRelVendedor")?.value || "";
  const dataInicio = document.getElementById("vendasRelDataInicio")?.value || "";
  const dataFim = document.getElementById("vendasRelDataFim")?.value || "";
  if (vendedor) params.set("vendedor", vendedor);
  if (dataInicio) params.set("data_inicio", dataInicio);
  if (dataFim) params.set("data_fim", dataFim);
  if (vendedor) params.set("limite", "300");

  const resp = await apiFetch(`/api/vendas/relatorio?${params.toString()}`);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (infoEl) infoEl.textContent = data?.erro || "Falha ao carregar relatorio de vendas.";
    alert(data?.erro || "Falha ao carregar relatorio de vendas.");
    return;
  }
  renderRelatorioVendas(data || {});
}

function limparFiltrosRelatorioVendas(){
  const dataInicio = document.getElementById("vendasRelDataInicio");
  const dataFim = document.getElementById("vendasRelDataFim");
  const vendedor = document.getElementById("vendasRelVendedor");
  if (dataInicio) dataInicio.value = "";
  if (dataFim) dataFim.value = "";
  if (vendedor) vendedor.value = "";
  carregarRelatorioVendas().catch(() => {});
}

const MONITOR_APPS = {
  esxi: () => `/monitor/esxi/`,
  cameras: () => `/monitor/cameras/`,
};

function toggleMonitorSubmenu(ev){
  if (!ev) return;
  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (!isMobile) { openMonitorView(null, "esxi"); return; }
  ev.preventDefault();
  ev.stopPropagation();
  const mi = ev.currentTarget;
  if (mi && mi.classList.contains("has-submenu")) mi.classList.toggle("open");
}

function openMonitorView(ev, view){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const menu = document.querySelector('.menu-item.has-submenu[data-tab="monitor"]');
  window.__monitorView = (view === "cameras") ? "cameras" : "esxi";
  showTab("monitor", menu);

  document.querySelectorAll("#submenuMonitor .submenu-item").forEach(x=>x.classList.remove("active"));
  const items = document.querySelectorAll("#submenuMonitor .submenu-item");
  const target = window.__monitorView === "cameras" ? 1 : 0;
  if (items && items[target]) items[target].classList.add("active");

  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && menu) menu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
}

function setMonitorView(view){
  window.__monitorView = (view === "cameras") ? "cameras" : "esxi";
  const appLabel = document.getElementById("monitorAppLabel");
  const frame = document.getElementById("monitorFrame");
  const urlFactory = MONITOR_APPS[window.__monitorView];
  const url = urlFactory ? urlFactory() : "";
  if (appLabel) appLabel.textContent = window.__monitorView === "cameras" ? "Cameras" : "ESXi";

  const loadFrame = () => {
    if (!frame || !url) return;
    if (frame.dataset.src !== url) {
      frame.src = url;
      frame.dataset.src = url;
    }
  };

  apiFetch("/api/monitor_boot")
    .then(() => setTimeout(loadFrame, 350))
    .catch(() => loadFrame());
}

function openMonitorExternal(){
  const view = window.__monitorView || "esxi";
  const urlFactory = MONITOR_APPS[view];
  const url = urlFactory ? urlFactory() : "";
  if (!url) return;
  window.open(url, "_blank", "noopener");
}

function toggleConfigSubmenu(ev){
  if (!ev) return;
  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (!isMobile) { openConfigView(null, "status"); return; }
  ev.preventDefault();
  ev.stopPropagation();
  const mi = ev.currentTarget;
  if (mi && mi.classList.contains("has-submenu")) mi.classList.toggle("open");
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

function preencherConfigVendas(cfg = {}, fonte = {}, imports = []){
  vendasConfigState = cfg || {};
  const habilitado = document.getElementById("vendasConfigHabilitado");
  const sourceType = document.getElementById("vendasConfigSourceType");
  const csvDir = document.getElementById("vendasConfigCsvDir");
  const fbHost = document.getElementById("vendasConfigFirebirdHost");
  const fbPort = document.getElementById("vendasConfigFirebirdPort");
  const fbDb = document.getElementById("vendasConfigFirebirdDatabase");
  const fbUser = document.getElementById("vendasConfigFirebirdUser");
  const fbPass = document.getElementById("vendasConfigFirebirdPassword");
  const fbQuery = document.getElementById("vendasConfigFirebirdQuery");
  const resumo = document.getElementById("vendasConfigResumo");
  const fonteEl = document.getElementById("vendasConfigFonte");
  const body = document.getElementById("vendasCacheBody");

  if (habilitado) habilitado.checked = !!cfg.habilitado;
  if (sourceType) sourceType.value = cfg.source_type || "csv_relatorios_dir";
  if (csvDir) csvDir.value = cfg.csv_dir || "";
  if (fbHost) fbHost.value = cfg.firebird_host || "";
  if (fbPort) fbPort.value = cfg.firebird_port || 3050;
  if (fbDb) fbDb.value = cfg.firebird_database || "";
  if (fbUser) fbUser.value = cfg.firebird_user || "";
  if (fbPass) fbPass.value = cfg.firebird_password || "";
  if (fbQuery) fbQuery.value = cfg.firebird_query || "";

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
        <td>${_escHtml(item.status || "-")}</td>
        <td><button type="button" onclick="excluirCacheVendas('${_escJsString(item.id || "")}')">Excluir</button></td>
      </tr>
    `).join("") : '<tr><td colspan="6">Nenhum cache importado ainda.</td></tr>';
  }
}

async function carregarConfigVendas(){
  const resumo = document.getElementById("vendasConfigResumo");
  if (resumo) resumo.textContent = "Carregando configuracao de vendas...";
  const resp = await apiFetch("/api/vendas/config");
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (resumo) resumo.textContent = data?.erro || "Erro ao carregar configuracao de vendas.";
    return;
  }
  preencherConfigVendas(data?.config || {}, data?.fonte || {}, data?.imports || []);
}

async function salvarConfigVendas(){
  const payload = {
    habilitado: !!document.getElementById("vendasConfigHabilitado")?.checked,
    source_type: document.getElementById("vendasConfigSourceType")?.value || "csv_relatorios_dir",
    csv_dir: (document.getElementById("vendasConfigCsvDir")?.value || "").trim(),
    firebird_host: (document.getElementById("vendasConfigFirebirdHost")?.value || "").trim(),
    firebird_port: Number(document.getElementById("vendasConfigFirebirdPort")?.value || 3050) || 3050,
    firebird_database: (document.getElementById("vendasConfigFirebirdDatabase")?.value || "").trim(),
    firebird_user: (document.getElementById("vendasConfigFirebirdUser")?.value || "").trim(),
    firebird_password: document.getElementById("vendasConfigFirebirdPassword")?.value || "",
    firebird_query: (document.getElementById("vendasConfigFirebirdQuery")?.value || "").trim(),
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
  preencherConfigVendas(data?.config || payload, data?.fonte || {}, data?.imports || []);
}

async function importarCacheVendas(){
  const resumo = document.getElementById("vendasConfigResumo");
  if (resumo) resumo.textContent = "Importando relatorio de vendas para o banco...";
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
  preencherConfigVendas(data?.config || vendasConfigState || {}, data?.fonte || {}, data?.imports || []);
  if (window.__vendasView === "relatorio") carregarRelatorioVendas().catch(()=>{});
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
  preencherConfigVendas(data?.config || vendasConfigState || {}, data?.fonte || {}, data?.imports || []);
  if (window.__vendasView === "relatorio") carregarRelatorioVendas().catch(()=>{});
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
  preencherConfigVendas(data?.config || vendasConfigState || {}, data?.fonte || {}, data?.imports || []);
  if (window.__vendasView === "relatorio") carregarRelatorioVendas().catch(()=>{});
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
// =====================================================================
// Adicione esta função antes de renderDashboardFrota()
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

// Depois use na renderização:
async function renderDashboardFrota(){
  // ... código anterior ...
  const status = d.frete_status || "-";
  
  return `
    <tr class="${cls}">
      <td>${_escHtml(veiculo)}</td>
      <td>${_escHtml(motorista)}</td>
      <td>${_escHtml(frete)}</td>
      <td>${getStatusBadge(status)}</td>  <!-- COM CORES -->
      <td>${_escHtml(media.toString())}</td>
      <td>${_escHtml(faltaManut.toString())} km</td>
      <td>${_escHtml(faltaOleo.toString())} km</td>
    </tr>
  `;
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
    // mantém a última view selecionada (default: resumo)
    if (!window.__dashView) window.__dashView = "resumo";
    setDashboardView(window.__dashView);
    if (window.__dashView === "frota") {
      renderDashboardFrota().catch(()=>{});
    }
  }
  if (tabId === "comissao") {
    if (!window.__comissaoView || !["lancamento", "relatorios"].includes(window.__comissaoView)) {
      window.__comissaoView = "lancamento";
    }
    setComissaoView(window.__comissaoView);
  }
  if (tabId === "vendas") {
    if (!window.__vendasView || !["relatorio"].includes(window.__vendasView)) {
      window.__vendasView = "relatorio";
    }
    setVendasView(window.__vendasView);
  }
  if (tabId === "monitor") {
    if (!window.__monitorView || !["esxi", "cameras"].includes(window.__monitorView)) {
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
  if (tabId === "estoque") {
    if (!window.__estoqueView || !["lancar", "conferir"].includes(window.__estoqueView)) {
      window.__estoqueView = "lancar";
    }
    setEstoqueView(window.__estoqueView);
  }
  if (tabId === "cadastros") {
    if (!window.__cadastrosView) window.__cadastrosView = "motoristas";
    setCadastrosView(window.__cadastrosView);
  }
  if (tabId === "fretes") {
    _agendarEqualizacaoAlturaKanban(0);
  } else {
    _atualizarScrollbarAuxiliarKanban();
  }

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
  if (btn) btn.disabled = !ok;
  if (input) input.disabled = !ok;
  if (attachBtn) attachBtn.disabled = !ok;
  if (attachInput) attachInput.disabled = !ok;
  atualizarEstadoSipChat();
}

function atualizarCabecalhoChat() {
  const nomeEl = document.getElementById("chatContatoAtualNome");
  const statusEl = document.getElementById("chatContatoAtualStatus");
  const avatarEl = document.getElementById("chatContatoAvatar");
  if (!nomeEl) return;
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
  const contatos = usuarios.filter((u) => String(u.id) !== eu);

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
    const badge = qtd > 0 ? `<span class="chat-contato-badge">${qtd > 99 ? "99+" : qtd}</span>` : "";
    const subtitulo = qtd > 0
      ? `${qtd} ${qtd === 1 ? "mensagem nao lida" : "mensagens nao lidas"}`
      : (u.sip_ramal ? `Ramal ${_escHtml(String(u.sip_ramal))}` : (u.login ? `Login ${_escHtml(String(u.login))}` : "Clique para conversar"));
    return `
      <button type="button" class="chat-contato ${active}" onclick="selecionarContatoChat(${u.id})" title="Abrir conversa com ${_escHtml(u.nome)}">
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
  const contatos = (cacheUsuarios || []).filter((u) => String(u.id) !== String(chatState.usuarioId));
  if (!manterSelecao || !contatos.some((u) => String(u.id) === String(chatState.contatoId))) {
    chatState.contatoId = contatos[0] ? String(contatos[0].id) : "";
  }
  renderListaContatosChat();
  atualizarCabecalhoChat();
  atualizarEstadoEnvioChat();
}

async function selecionarContatoChat(contatoId) {
  limparAnexoChat();
  chatState.contatoId = String(contatoId || "");
  await marcarLidasContatoChat(chatState.contatoId);
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

  await marcarLidasContatoChat(chatState.contatoId);
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
  if (!mensagem && !anexo) return;

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
    if (chatState.contatoId) await marcarLidasContatoChat(chatState.contatoId).catch(() => {});
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
  if (modal) modal.classList.remove("hidden");
  if (msg) msg.textContent = showMsg || "";
  try { loginInput?.focus(); } catch {}
  setTimeout(() => { try { loginInput?.focus(); } catch {} }, 40);
}

function fecharLoginModal() {
  const modal = document.getElementById("loginModal");
  if (modal) modal.classList.add("hidden");
  document.body.classList.remove("login-active");
}

function bindLoginSubmitOnEnter() {
  ["loginUsuario", "loginSenha"].forEach((id) => {
    const el = document.getElementById(id);
    if (!el || el.dataset.loginEnterBound === "1") return;
    el.dataset.loginEnterBound = "1";
    el.addEventListener("keydown", async (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        await fazerLoginSistema();
      }
    });
  });
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
  usuarioLogado = j.usuario || null;
  chatState.usuarioId = usuarioLogado ? String(usuarioLogado.id) : "";
  chatState.lastSeenMessageId = 0;
  if (usuarioLogado?.id) _salvarSessaoLogin(usuarioLogado);
  fecharLoginModal();
  atualizarUsuarioLogadoUI();
  await initSipClient(true).catch(() => {});
  await carregarUsuariosChat(false);
  await carregarNaoLidasChat();
  renderListaContatosChat();
}

async function restaurarSessaoLogin() {
  if (LOGIN_BYPASS) return true;
  try {
    const portalResp = await apiFetch("/api/status");
    if (portalResp.ok) {
      const statusPayload = await portalResp.json();
      if (statusPayload?.usuario_logado?.id) {
        usuarioLogado = {
          id: statusPayload.usuario_logado.id,
          nome: statusPayload.usuario_logado.nome,
          login: statusPayload.usuario_logado.login,
          codbar_modo: statusPayload.usuario_logado.codbar_modo || "bip",
        };
        chatState.usuarioId = String(usuarioLogado.id);
        chatState.lastSeenMessageId = 0;
        _salvarSessaoLogin(usuarioLogado);
        atualizarUsuarioLogadoUI();
        await initSipClient(true).catch(() => {});
        return true;
      }
    }
  } catch {}

  const sessao = _sessaoObjFromStorage();
  if (!sessao) return false;
  if (_sessaoExpirada(sessao)) {
    _logoutSessaoLocal(false, "");
    return false;
  }
  try {
    const uid = sessao?.usuario?.id;
    if (!uid) return false;
    const resp = await apiFetch(`/api/usuarios/${encodeURIComponent(uid)}`);
    if (!resp.ok) return false;
    const user = await resp.json();
    usuarioLogado = {
      id: user.id,
      nome: user.nome,
      login: user.login,
      codbar_modo: user.codbar_modo || "bip",
    };
    chatState.usuarioId = String(user.id);
    chatState.lastSeenMessageId = 0;
    _salvarSessaoLogin(usuarioLogado); // renova por mais 8h após revalidação
    atualizarUsuarioLogadoUI();
    await initSipClient(true).catch(() => {});
    return true;
  } catch {
    return false;
  }
}

function initChatInterno() {
  if (window.__chatIniciado) return;
  window.__chatIniciado = true;
  renderAnexoPendenteChat();

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

  bindLoginSubmitOnEnter();

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

function _freteKey(id){
  return String(id ?? "");
}

function _findFreteById(id){
  return fretes.find((f) => String(f.id) === String(id)) || null;
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
  ].map((v) => (v || "").toString().toLowerCase()).join(" ");
  return alvo.includes(filtro);
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

function _cloneFretePayload(frete = {}){
  const motoristaId = frete.motorista_id ? Number(frete.motorista_id) : null;
  return {
    nome: (frete.nome || "").toString().trim(),
    cidade: (frete.cidade || "").toString().trim(),
    data_carga: _normalizarDataFreteInput(frete.data_carga || frete.created_at || ""),
    status: (frete.status || "liberado").toString(),
    veiculo_id: frete.veiculo_id ? Number(frete.veiculo_id) : null,
    motorista_id: motoristaId,
    entregador_id: frete.entregador_id ? Number(frete.entregador_id) : motoristaId,
    carga_id: frete.carga_id ? Number(frete.carga_id) : null,
    km_atual: Number(frete.km_atual || 0) || 0,
    peso: Number(frete.peso || 0) || 0,
    qtd_entregas: Number(frete.qtd_entregas || 0) || 0,
    observacao: (frete.observacao || "").toString(),
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
    frete.motorista_id || "",
    frete.entregador_id || "",
    frete.veiculo_id || "",
    frete.carga_id || "",
    frete.observacao || "",
    Number(frete.km_atual || 0),
    Number(frete.peso || 0),
    Number(frete.qtd_entregas || 0),
    frete.updated_at || "",
    frete.finalizado_em || "",
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
  const inpNome = card.querySelector(".frete-nome");
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
  return {
    nome: (inpNome?.value || freteBase?.nome || "").toString().trim(),
    cidade: (freteBase?.cidade || "").toString().trim(),
    data_carga: _normalizarDataFreteInput(inpDataCarga?.value || freteBase?.data_carga || freteBase?.created_at || ""),
    status: (freteBase?.status || "liberado").toString(),
    veiculo_id: selVeiculo?.value ? Number(selVeiculo.value) : null,
    motorista_id: motoristaId,
    entregador_id: selEntregador?.value ? Number(selEntregador.value) : motoristaId,
    carga_id: selCarga?.value ? Number(selCarga.value) : null,
    km_atual: inpKmAtual && inpKmAtual.value.trim() !== "" ? Number(inpKmAtual.value) : 0,
    peso: inpPeso && inpPeso.value.trim() !== "" ? Number(inpPeso.value) : 0,
    qtd_entregas: inpEntregas && inpEntregas.value.trim() !== "" ? Number(inpEntregas.value) : 0,
    observacao: (txtObs?.value || "").trim(),
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
    state.error = "Falha ao salvar";
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
  const card = _getFreteCard(id);
  const payload = card
    ? _coletarPayloadFreteDoCard(card, freteAtual)
    : _cloneFretePayload(freteAtual);
  payload.status = novoStatus;
  return _salvarFreteAutomaticamente(id, { payloadOverride: payload });
}

function _freteCardTemplate(frete){
  const data = _cloneFretePayload(frete);
  return `
    <div class="card-header" draggable="true" data-frete-id="${_escAttr(String(frete.id))}">Segure e arraste</div>
    <div class="card-body">
      <div class="frete-card-grid">
        <div class="crud-field crud-field--full">
          <span>Nome</span>
          <input type="text" class="frete-nome" value="${_escAttr(String(data.nome || ""))}" placeholder="Nome do frete">
        </div>
        <div class="crud-field">
          <span>Data carga</span>
          <input type="date" class="frete-data-carga" value="${_escAttr(String(data.data_carga || ""))}">
        </div>
        <div class="crud-field">
          <span>Veiculo</span>
          <select class="frete-veiculo">
            ${optionsFrom(cacheCadastros.veiculos, data.veiculo_id)}
          </select>
        </div>
        <div class="crud-field">
          <span>Motorista</span>
          <select class="frete-motorista">
            ${optionsFrom(cacheCadastros.motoristas, data.motorista_id)}
          </select>
        </div>
        <div class="crud-field">
          <span>Entregador</span>
          <select class="frete-entregador">
            ${optionsFrom(cacheCadastros.motoristas, data.entregador_id)}
          </select>
        </div>
        <div class="crud-field">
          <span>Carga</span>
          <select class="frete-carga">
            ${optionsFrom(cacheCadastros.cargas, data.carga_id)}
          </select>
        </div>
        <div class="crud-field">
          <span>KM atual</span>
          <input type="number" class="frete-km-atual" min="0" value="${_escAttr(String(data.km_atual))}">
        </div>
        <div class="crud-field">
          <span>Peso</span>
          <input type="number" class="frete-peso" min="0" step="0.001" value="${_escAttr(String(data.peso))}">
        </div>
        <div class="crud-field">
          <span>Entregas</span>
          <input type="number" class="frete-qtd-entregas" min="0" value="${_escAttr(String(data.qtd_entregas))}">
        </div>
        <div class="crud-field crud-field--full">
          <span>Observacao</span>
          <textarea class="frete-obs" rows="2" placeholder="Digite uma observacao...">${_escHtml(data.observacao)}</textarea>
        </div>
      </div>
      <div class="crud-actions">
        <span class="frete-save-status" data-tone="saved">Salvo automaticamente</span>
        <button class="btn-mover-mobile" type="button">Mover</button>
        <button class="btn-excluir" type="button">Excluir</button>
      </div>
    </div>
  `;
}

function _preencherFreteCard(card, frete){
  const state = _ensureFreteDraftState(frete);
  const data = _cloneFretePayload(state.dirty ? state.draft : frete);
  const header = card.querySelector(".card-header");
  if (header) {
    header.textContent = "Segure e arraste";
    header.dataset.freteId = String(frete.id);
    header.title = frete.nome || "(sem nome)";
  }

  const inpNome = card.querySelector(".frete-nome");
  const inpDataCarga = card.querySelector(".frete-data-carga");
  const selVeiculo = card.querySelector(".frete-veiculo");
  const selMotorista = card.querySelector(".frete-motorista");
  const selEntregador = card.querySelector(".frete-entregador");
  const selCarga = card.querySelector(".frete-carga");
  const inpKmAtual = card.querySelector(".frete-km-atual");
  const inpPeso = card.querySelector(".frete-peso");
  const inpEntregas = card.querySelector(".frete-qtd-entregas");
  const txtObs = card.querySelector(".frete-obs");

  if (inpNome) inpNome.value = data.nome || "";
  if (inpDataCarga) inpDataCarga.value = data.data_carga || "";
  if (selVeiculo) selVeiculo.innerHTML = optionsFrom(cacheCadastros.veiculos, data.veiculo_id);
  if (selMotorista) selMotorista.innerHTML = optionsFrom(cacheCadastros.motoristas, data.motorista_id);
  if (selEntregador) selEntregador.innerHTML = optionsFrom(cacheCadastros.motoristas, data.entregador_id);
  if (selCarga) selCarga.innerHTML = optionsFrom(cacheCadastros.cargas, data.carga_id);
  if (inpKmAtual) {
    const kmCadastro = _kmAtualCadastroVeiculo(data.veiculo_id);
    const kmFrete = Number(data.km_atual ?? 0) || 0;
    const usaKmCadastro = kmFrete <= 0 && kmCadastro > 0;
    inpKmAtual.value = String(usaKmCadastro ? kmCadastro : kmFrete);
    inpKmAtual.dataset.autoFromVehicle = usaKmCadastro ? "1" : "0";
  }
  if (inpPeso) inpPeso.value = String(data.peso ?? 0);
  if (inpEntregas) inpEntregas.value = String(data.qtd_entregas ?? 0);
  if (txtObs) txtObs.value = data.observacao || "";
}

function _bindFreteCardEvents(card){
  const id = card.dataset.freteId;
  const state = _ensureFreteDraftState(_findFreteById(id) || { id });
  const header = card.querySelector(".card-header");
  const selVeiculo = card.querySelector(".frete-veiculo");
  const inpKmAtual = card.querySelector(".frete-km-atual");
  if (header) {
    header.draggable = true;
    header.ondragstart = (e) => e.dataTransfer.setData("id", id);
  }

  card.addEventListener("focusin", () => {
    const current = freteDraftState.get(_freteKey(id));
    if (!current) return;
    current.focused = true;
    current.error = "";
    _renderFreteSaveStatus(card, id);
  });

  card.addEventListener("focusout", () => {
    setTimeout(() => {
      const currentCard = _getFreteCard(id);
      const current = freteDraftState.get(_freteKey(id));
      if (!current) return;
      current.focused = !!(currentCard && currentCard.contains(document.activeElement));
      if (!current.focused) {
        _atualizarDraftFreteDoCard(id);
        if (current.dirty) _agendarAutoSaveFrete(id, 120);
      }
      _renderFreteSaveStatus(currentCard, id);
    }, 0);
  });

  const onInput = () => {
    _atualizarDraftFreteDoCard(id);
    const currentName = (card.querySelector(".frete-nome")?.value || "").trim();
    const headerEl = card.querySelector(".card-header");
    if (headerEl) headerEl.title = currentName || "(sem nome)";
    _agendarAutoSaveFrete(id);
  };
  const onChange = () => {
    _atualizarDraftFreteDoCard(id);
    _agendarAutoSaveFrete(id, 150);
  };

  if (inpKmAtual) {
    inpKmAtual.addEventListener("input", () => {
      inpKmAtual.dataset.autoFromVehicle = "0";
    });
    inpKmAtual.addEventListener("change", () => {
      inpKmAtual.dataset.autoFromVehicle = "0";
    });
  }

  card.querySelectorAll("input, textarea").forEach((field) => {
    field.addEventListener("input", onInput);
    field.addEventListener("change", onChange);
  });
  card.querySelectorAll("select").forEach((field) => {
    if (field === selVeiculo) return;
    field.addEventListener("change", onChange);
  });
  if (selVeiculo) {
    selVeiculo.addEventListener("change", () => {
      _sincronizarKmAtualComVeiculo(selVeiculo, inpKmAtual, { force: true });
      onChange();
    });
  }

  const btnMoverMobile = card.querySelector(".btn-mover-mobile");
  if (btnMoverMobile) {
    btnMoverMobile.onclick = async () => {
      const freteAtual = _findFreteById(id);
      if (!freteAtual) return;
      await moverFreteMobile(freteAtual);
    };
    btnMoverMobile.style.display = window.matchMedia("(max-width: 768px)").matches ? "" : "none";
  }

  const btnExcluir = card.querySelector(".btn-excluir");
  if (btnExcluir) {
    btnExcluir.onclick = async () => {
      await excluirFrete(id);
    };
  }

  _clearFreteSaveTimer(state);
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

  if (card && locked && !force) {
    _renderFreteSaveStatus(card, frete.id);
    return card;
  }

  if (!card) {
    card = document.createElement("div");
    card.className = "card";
    card.dataset.freteId = String(frete.id);
    card.innerHTML = _freteCardTemplate(frete);
    _bindFreteCardEvents(card);
  } else if (!force && card.dataset.remoteSignature === signature) {
    if (!mesmaColuna) targetCol.appendChild(card);
    _renderFreteSaveStatus(card, frete.id);
    _agendarEqualizacaoAlturaKanban();
    return card;
  }

  _preencherFreteCard(card, frete);
  card.dataset.remoteSignature = signature;
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
    `Mover "${frete.nome || "Frete"}" para:\n\n${opcoes}\n\nDigite o numero do destino:`,
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
    🚛 ${frete.veiculo_nome || "-"} |
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

  if (!nome || !motorista || !veiculo || !carga) return alert("Preencha todos os campos");

  const resp = await apiFetch("/api/fretes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      nome: nome,
      data_carga: dataCarga || _hojeInputDate(),
      motorista_id: motorista,
      entregador_id: entregador || motorista,
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
    select.innerHTML += `<option value="${item.id}">${item.nome}</option>`;
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
  await preencherSelect("motoristas", "novoFreteMotorista", "Selecione motorista");
  await preencherSelect("motoristas", "novoFreteEntregador", "Selecione entregador");
  await preencherSelect("veiculos", "novoFreteVeiculo", "Selecione veículo");
  await preencherSelect("cargas", "novoFreteCarga", "Selecione carga");
  _bindNovoFreteKmAtual();
}

async function renderFretes() {
  await ensureCadastrosCache();

  const colunas = {
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

  Object.values(colunas).forEach((col) => col && (col.innerHTML = ""));

  fretes.forEach((f) => {
    const col = colunas[f.status];
    if (!col) return;

    const card = document.createElement("div");
    card.className = "card";
    card.dataset.freteId = String(f.id);

    const header = document.createElement("div");
    header.className = "card-header";
    header.draggable = true;
    header.dataset.freteId = String(f.id); // ✅ usado no touch (celular)
    header.ondragstart = (e) => e.dataTransfer.setData("id", f.id);
    header.innerText = f.nome || "(sem nome)";

    const body = document.createElement("div");
    body.className = "card-body";

    const nomeVal = (f.nome || "").toString();
    const obsVal = (f.observacao || "").toString();

    body.innerHTML = `
      <div class="crud-row">
        <label>Nome</label>
        <input type="text" class="frete-nome" value="${nomeVal.replaceAll('"', "&quot;")}">
      </div>

      <div class="crud-row-line1">
        <div class="crud-field">
          <span>🚛</span>
          <select class="frete-veiculo">
            ${optionsFrom(cacheCadastros.veiculos, f.veiculo_id)}
          </select>
        </div>

        <div class="crud-field">
          <span>👤</span>
          <select class="frete-motorista">
            ${optionsFrom(cacheCadastros.motoristas, f.motorista_id)}
          </select>
        </div>

        <div class="crud-field">
          <span>📦</span>
          <select class="frete-carga">
            ${optionsFrom(cacheCadastros.cargas, f.carga_id)}
          </select>
        </div>
      </div>

      <div class="crud-row">
        <label>Observação</label>
        <textarea class="frete-obs" rows="2" placeholder="Digite uma observação...">${obsVal}</textarea>
      </div>

      <div class="crud-actions">
        <button class="btn-mover-mobile">↔ Mover</button>
        <button class="btn-salvar">💾 Salvar</button>
        <button class="btn-excluir">🗑 Excluir</button>
      </div>
    `;

    const inpNome = body.querySelector(".frete-nome");
    const selVeiculo = body.querySelector(".frete-veiculo");
    const selMotorista = body.querySelector(".frete-motorista");
    const selCarga = body.querySelector(".frete-carga");
    const txtObs = body.querySelector(".frete-obs");
    const btnMoverMobile = body.querySelector(".btn-mover-mobile");

    if (btnMoverMobile) {
      btnMoverMobile.onclick = async () => {
        await moverFreteMobile(f);
      };
      btnMoverMobile.style.display = window.matchMedia("(max-width: 768px)").matches ? "" : "none";
    }

    body.querySelector(".btn-salvar").onclick = async () => {
      const payload = {
        nome: (inpNome.value || "").trim(),
        status: f.status,
        veiculo_id: selVeiculo.value ? Number(selVeiculo.value) : null,
        motorista_id: selMotorista.value ? Number(selMotorista.value) : null,
        carga_id: selCarga.value ? Number(selCarga.value) : null,
        observacao: (txtObs.value || "").trim(),
      };

      if (!payload.nome) return alert("Nome do frete é obrigatório.");
      await atualizarFreteCompleto(f.id, payload);
    };

    body.querySelector(".btn-excluir").onclick = async () => {
      await excluirFrete(f.id);
    };

    card.appendChild(header);
    card.appendChild(body);
    col.appendChild(card);
  });

  ativarDragDrop();
  ativarDragDropMobile(); // ✅ touch drag no celular
}

async function carregarFretes() {
  let r = await apiFetch("/api/fretes");
  fretes = await r.json();
  renderFretes();
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
  
  // Recarrega do servidor
  await renderCadastros();
  
  // Se tipo é "veiculos", recarrega os fretes também
  if (tipo === "veiculos") {
    await carregarSelectsNovoFrete();
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
    modal.classList.remove("hidden");
    return;
  }

  const j = await r.json();
  const fotos = j.fotos || [];

  if (!fotos.length) {
    body.innerHTML = "Nenhuma foto anexada.";
    modal.classList.remove("hidden");
    return;
  }

  body.innerHTML = fotos
    .map((url) => `<img src="${url}" alt="Foto devolução ${id}">`)
    .join("");

  modal.classList.remove("hidden");
}

function fecharFotosDevolucao(e) {
  // se clicar no fundo (overlay), fecha também
  const modal = document.getElementById("fotoModal");
  if (!modal) return;
  modal.classList.add("hidden");
}

function fecharHistoricoFrota(e) {
  const modal = document.getElementById("frotaHistoricoModal");
  if (!modal) return;
  modal.classList.add("hidden");
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

async function abrirHistoricoFrota(veiculoId) {
  const modal = document.getElementById("frotaHistoricoModal");
  const body = document.getElementById("frotaHistoricoBody");
  if (!modal || !body) return;
  if (!(Number(veiculoId) > 0)) return;

  body.innerHTML = "Carregando historico...";
  modal.classList.remove("hidden");

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

  const titulo = `${v.placa || "-"} ${v.modelo || v.nome || ""}`.trim();
  const mediaKm = (resumo.media_km !== null && resumo.media_km !== undefined && Number.isFinite(Number(resumo.media_km)))
    ? Number(resumo.media_km).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "-";

  const manutRows = manutencoes.map((m) => `
    <tr>
      <td>${_escHtml(_fmtDateBr(m.data_manutencao))}</td>
      <td>${_escHtml(m.tipo || "-")}</td>
      <td>${_escHtml(String(m.km || 0))}</td>
      <td>R$ ${_escHtml(_fmtMoney(m.valor))}</td>
    </tr>
  `);

  const oleoRows = trocasOleo.map((o) => `
    <tr>
      <td>${_escHtml(_fmtDateBr(o.data_troca))}</td>
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
    return `
      <tr>
        <td>${_escHtml(_fmtDateBr(a.data_abastecimento || a.data_liberacao))}</td>
        <td>${_escHtml(a.status || "-")}</td>
        <td>${_escHtml(_combustivelLabel(a.combustivel_tipo))}</td>
        <td>${_escHtml(String(a.km || 0))}</td>
        <td>${_escHtml(postoEmitente)}</td>
        <td>${_escHtml(nota)}</td>
        <td>${_escHtml(_fmtNumber(a.quantidade_litros, 3))}</td>
        <td>R$ ${_escHtml(_fmtMoney(a.valor))}</td>
        <td>${_escHtml(_fmtNumber(a.km_l, 2))}</td>
      </tr>
    `;
  });

  body.innerHTML = `
    <div class="frota-historico-card">
      <h4>${_escHtml(titulo || "Historico do Caminhao")}</h4>
      <div class="frota-historico-kv">
        ${_frotaHistoricoResumoRow("Placa", v.placa || "-")}
        ${_frotaHistoricoResumoRow("Modelo", v.modelo || v.nome || "-")}
        ${_frotaHistoricoResumoRow("KM atual", v.km_atual ?? 0)}
        ${_frotaHistoricoResumoRow("Media KM/L", mediaKm)}
        ${_frotaHistoricoResumoRow("Falta p/ manutencao", `${resumo.falta_manut_km ?? "-"} km`)}
        ${_frotaHistoricoResumoRow("Falta p/ oleo", `${resumo.falta_oleo_km ?? "-"} km`)}
        ${_frotaHistoricoResumoRow("Motorista atual", frete.motorista_nome || "-")}
        ${_frotaHistoricoResumoRow("Frete atual", frete.nome || "-")}
        ${_frotaHistoricoResumoRow("Status frete", frete.status || "-")}
      </div>
    </div>

    <div class="frota-historico-grid">
      <div class="frota-historico-card">
        <h4>Manutencoes</h4>
        ${_frotaHistoricoTable(["Data", "Tipo", "KM", "Valor"], manutRows, "Sem manutencoes registradas.")}
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
        ${_frotaHistoricoTable(["Data", "Status", "Comb.", "KM", "Posto / Emitente", "NF-e", "Qtd", "Valor", "KM/L"], abastRows, "Sem abastecimentos registrados.")}
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
    console.log("Erro ao salvar devolução:", resp.status, t);
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
    await preencherSelect("conferentes", "dev_conf", "Selecione conferente");
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



// =====================================================
// GESTÃO DE FROTA (PERSISTÊNCIA EM BANCO)
// =====================================================
async function carregarFrotaResumo(){
  // popula selects de manutenção/óleo e tabela resumo
  const [veiculosResp, resumoResp] = await Promise.allSettled([
    fetch("/api/veiculos"),
    fetch("/api/frota_resumo"),
  ]);

  let veiculos = [];
  if (veiculosResp.status === "fulfilled") {
    try { veiculos = await veiculosResp.value.json(); } catch {}
  }

  // Selects
  const selManut = document.getElementById("manut_veiculo");
  const selOleo = document.getElementById("oleo_veiculo");
  const selPneu = document.getElementById("pneu_veiculo");
  const selAbast = document.getElementById("abast_veiculo");
  const opt = (v)=>`<option value="${v.id}">${_escHtml(v.nome || (v.placa||'') || ('Veículo '+v.id))}</option>`;
  if (selManut) selManut.innerHTML = `<option value="">Selecione...</option>` + veiculos.map(opt).join("");
  if (selOleo) selOleo.innerHTML = `<option value="">Selecione...</option>` + veiculos.map(opt).join("");
  if (selPneu) selPneu.innerHTML = `<option value="">Selecione...</option>` + veiculos.map(opt).join("");
  if (selAbast) selAbast.innerHTML = `<option value="">Selecione...</option>` + veiculos.map(opt).join("");

  // Tabela
  const tbody = document.getElementById("tabelaFrota");
  if (!tbody) return;
  if (resumoResp.status !== "fulfilled") {
    tbody.innerHTML = `<tr><td colspan="6">Erro ao carregar frota.</td></tr>`;
    return;
  }
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
      </tr>
    `;
  }).join("");

  await carregarAbastecimentos();
  await carregarTrocasPneu();
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

function _fmtDateBr(v){
  if (!v) return "-";
  const d = new Date(String(v).replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return _escHtml(String(v));
  return d.toLocaleString("pt-BR");
}

function _digitsOnly(v){
  return String(v ?? "").replace(/\D+/g, "");
}

function _combustivelLabel(v){
  return String(v || "").toLowerCase() === "arla" ? "Arla" : "Diesel";
}

async function liberarAbastecimento(){
  const veiculo_id = Number((document.getElementById("abast_veiculo")?.value || "").trim());
  const km = Number((document.getElementById("abast_km")?.value || "").trim() || 0);
  const posto = (document.getElementById("abast_posto")?.value || "").trim();
  const combustivel_tipo = (document.getElementById("abast_combustivel")?.value || "diesel").trim() || "diesel";

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

  if (document.getElementById("abast_km")) document.getElementById("abast_km").value = "";
  if (document.getElementById("abast_posto")) document.getElementById("abast_posto").value = "";
  if (document.getElementById("abast_combustivel")) document.getElementById("abast_combustivel").value = "diesel";

  await Promise.all([carregarFrotaResumo(), carregarAbastecimentos()]);
  if (window.__dashView === "frota") await renderDashboardFrota();
  if (data?.pdf_url) {
    window.open(data.pdf_url, "_blank");
  }
}

async function concluirAbastecimento(id){
  const valor = Number((document.getElementById(`abast_valor_${id}`)?.value || "").trim() || 0);
  const quantidade_litros = Number((document.getElementById(`abast_qtd_${id}`)?.value || "").trim() || 0);
  const combustivel_tipo = (document.getElementById(`abast_combustivel_${id}`)?.value || "diesel").trim() || "diesel";
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

  await Promise.all([carregarFrotaResumo(), carregarAbastecimentos()]);
  if (window.__dashView === "frota") await renderDashboardFrota();
}

async function importarNfeAbastecimento(id){
  const fileInput = document.getElementById(`abast_xml_${id}`);
  const file = fileInput?.files?.[0];
  const chave_acesso_esperada = _digitsOnly(document.getElementById(`abast_chave_${id}`)?.value || "");
  const combustivel_tipo = (document.getElementById(`abast_combustivel_${id}`)?.value || "diesel").trim() || "diesel";

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
  await Promise.all([carregarFrotaResumo(), carregarAbastecimentos()]);
  if (window.__dashView === "frota") await renderDashboardFrota();
  alert(`NF-e importada com sucesso para ${_combustivelLabel(data?.combustivel_tipo)}. Nota: ${data?.numero_nota || data?.chave_acesso_nfe || "-"}.`);
}

async function buscarNfeAbastecimento(id) {
  const chave_acesso_esperada = _digitsOnly(document.getElementById(`abast_chave_${id}`)?.value || "");
  const combustivel_tipo = (document.getElementById(`abast_combustivel_${id}`)?.value || "diesel").trim() || "diesel";
  if (chave_acesso_esperada.length !== 44) {
    return alert("A chave de acesso da NF-e precisa ter 44 digitos.");
  }

  const resp = await apiFetch(`/api/abastecimentos/${id}/importar_nfe_dfe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chave_acesso_esperada, combustivel_tipo }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao consultar DF-e do abastecimento.");

  await Promise.all([carregarFrotaResumo(), carregarAbastecimentos()]);
  if (window.__dashView === "frota") await renderDashboardFrota();
  alert(`NF-e obtida via DF-e e importada com sucesso para ${_combustivelLabel(data?.combustivel_tipo)}. Nota: ${data?.numero_nota || data?.chave_acesso_nfe || "-"}.`);
}

async function excluirAbastecimento(id){
  if (!confirm("Excluir este lancamento de abastecimento?")) return;

  const resp = await apiFetch(`/api/abastecimentos/${id}`, { method: "DELETE" });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao excluir abastecimento.");

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
    if (histBody) histBody.innerHTML = `<tr><td colspan="11">Erro ao carregar historico.</td></tr>`;
    return;
  }
  const dados = await resp.json();
  const pendentes = (dados || []).filter((x) => (x.status || "").toLowerCase() === "liberado");
  const historico = (dados || []).filter((x) => (x.status || "").toLowerCase() === "abastecido");

  if (pendBody) {
    pendBody.innerHTML = pendentes.length ? pendentes.map((r) => {
      const v = `${r.placa || ""} ${r.modelo || r.veiculo_nome || ""}`.trim();
      const combustivel = String(r.combustivel_tipo || "diesel").toLowerCase() === "arla" ? "arla" : "diesel";
      return `
        <tr>
          <td>${_escHtml(v || ("Veiculo " + r.veiculo_id))}</td>
          <td>${_escHtml(String(r.km || 0))}</td>
          <td>${_escHtml(r.posto || "-")}</td>
          <td>
            <select id="abast_combustivel_${r.id}">
              <option value="diesel" ${combustivel === "diesel" ? "selected" : ""}>Diesel</option>
              <option value="arla" ${combustivel === "arla" ? "selected" : ""}>Arla</option>
            </select>
          </td>
          <td>
            <div class="abastecimento-inline">
              <input id="abast_chave_${r.id}" class="barcode-input" type="text" maxlength="44" value="${_escAttr(r.chave_acesso_nfe || "")}" placeholder="Bipe a chave" oninput="normalizarChaveNfeCampo(this,false)" onkeydown="if(event.key==='Enter'){event.preventDefault(); normalizarChaveNfeCampo(this,true);}">
              <button type="button" onclick="abrirCameraEstoque('abast_chave_${r.id}')">Camera</button>
            </div>
          </td>
          <td><input id="abast_xml_${r.id}" type="file" accept=".xml,text/xml,application/xml"></td>
          <td>
            <div class="abastecimento-manual-grid">
              <input id="abast_nota_${r.id}" type="text" value="${_escAttr(r.numero_nota || "")}" placeholder="Numero da nota">
              <input id="abast_emitente_${r.id}" type="text" value="${_escAttr(r.emitente_nome || "")}" placeholder="Emitente">
            </div>
          </td>
          <td><input id="abast_valor_${r.id}" type="number" step="0.01" min="0" placeholder="0,00" value="${_escAttr(r.valor != null ? String(r.valor) : "")}"></td>
          <td><input id="abast_qtd_${r.id}" type="number" step="0.001" min="0" placeholder="${_escAttr(combustivel === "arla" ? "Qtd" : "Litros")}" value="${_escAttr(r.quantidade_litros != null ? String(r.quantidade_litros) : "")}"></td>
          <td class="abastecimento-actions">
            <button type="button" onclick="concluirAbastecimento(${r.id})">Marcar abastecido</button>
            <button type="button" onclick="importarNfeAbastecimento(${r.id})">Importar XML</button>
            <button type="button" onclick="buscarNfeAbastecimento(${r.id})">Buscar DF-e</button>
            <button type="button" onclick="selecionarImagemNfeOcr({ tipo: 'abastecimento', id: ${r.id} })">Foto OCR</button>
            <button type="button" onclick="window.open('/api/abastecimentos/${r.id}/pdf','_blank')">PDF</button>
            <button type="button" onclick="excluirAbastecimento(${r.id})">Excluir</button>
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
      return `
        <tr>
          <td>${_escHtml(_fmtDateBr(r.data_abastecimento || r.data_liberacao))}</td>
          <td>${_escHtml(v || ("Veiculo " + r.veiculo_id))}</td>
          <td>${_escHtml(_combustivelLabel(r.combustivel_tipo))}</td>
          <td>${_escHtml(String(r.km || 0))}</td>
          <td>${_escHtml(postoEmitente)}</td>
          <td>${_escHtml(nota)}</td>
          <td>${_escHtml(_fmtNumber(r.quantidade_litros, 3))}</td>
          <td>R$ ${_escHtml(_fmtMoney(r.valor))}</td>
          <td>${_escHtml(_fmtNumber(r.km_l, 2))}</td>
          <td>${_escHtml(r.status || "-")}</td>
          <td class="abastecimento-actions">
            <button type="button" onclick="window.open('/api/abastecimentos/${r.id}/pdf','_blank')">PDF</button>
            <button type="button" onclick="excluirAbastecimento(${r.id})">Excluir</button>
          </td>
        </tr>
      `;
    }).join("") : `<tr><td colspan="11">Sem abastecimentos concluidos.</td></tr>`;
  }
}

async function addManutencao(){
  const veiculo_id = Number((document.getElementById("manut_veiculo")?.value || "").trim());
  const tipo = (document.getElementById("manut_tipo")?.value || "").trim();
  const km = Number((document.getElementById("manut_km")?.value || "").trim() || 0);
  const valor = Number((document.getElementById("manut_valor")?.value || "").trim() || 0);

  if (!veiculo_id) return alert("Selecione o veiculo.");
  await fetch("/api/manutencoes", {
    method:"POST",
    headers:{ "Content-Type":"application/json" },
    body: JSON.stringify({ veiculo_id, tipo, km, valor })
  });

  // limpa
  if (document.getElementById("manut_tipo")) document.getElementById("manut_tipo").value="";
  if (document.getElementById("manut_km")) document.getElementById("manut_km").value="";
  if (document.getElementById("manut_valor")) document.getElementById("manut_valor").value="";

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

function gerarRelatorioFrota(){
  // Relatório simples: abre a tabela atual para imprimir
  const tbody = document.getElementById("tabelaFrota");
  if (!tbody) return;

  const html = `
    <html><head><title>Relatório Frota</title></head>
    <body>
      <h2>Relatório Frota</h2>
      <table border="1" cellpadding="6" cellspacing="0">
        ${tbody.parentElement?.outerHTML || ""}
      </table>
      <script>window.onload=()=>{window.print();}</script>
    </body></html>
  `;
  const w = window.open("", "_blank");
  if (w) { w.document.write(html); w.document.close(); }
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
async function gerarBackup() {
  const resp = await fetch("/api/backup");

  if (!resp.ok) {
    let j = null;
    try { j = await resp.json(); } catch {}
    alert("Erro no backup:\n" + (j?.detalhes || j?.erro || `HTTP ${resp.status}`));
    return;
  }

  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `backup_${new Date().toISOString().slice(0, 19).replaceAll(":", "-")}.sql`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
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
    body.innerHTML = `<tr><td colspan="5">Erro ao carregar manutencoes.</td></tr>`;
    return;
  }

  const dados = await resp.json();
  body.innerHTML = (dados || []).length ? (dados || []).map((r) => `
    <tr>
      <td>${_escHtml(_fmtDateBr(r.data_registro))}</td>
      <td>${_escHtml(_veiculoFrotaLabel(r))}</td>
      <td>${_escHtml(r.tipo || "-")}</td>
      <td>${_escHtml(String(r.km || 0))}</td>
      <td>R$ ${_escHtml(_fmtMoney(r.valor))}</td>
    </tr>
  `).join("") : `<tr><td colspan="5">Sem manutencoes registradas.</td></tr>`;
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
  modal.classList.remove("hidden");

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
    return `
      <tr>
        <td>${_escHtml(_fmtDateBr(a.data_abastecimento || a.data_liberacao))}</td>
        <td>${_escHtml(a.status || "-")}</td>
        <td>${_escHtml(_combustivelLabel(a.combustivel_tipo))}</td>
        <td>${_escHtml(String(a.km || 0))}</td>
        <td>${_escHtml(postoEmitente)}</td>
        <td>${_escHtml(nota)}</td>
        <td>${_escHtml(_fmtNumber(a.quantidade_litros, 3))}</td>
        <td>R$ ${_escHtml(_fmtMoney(a.valor))}</td>
        <td>${_escHtml(_fmtNumber(a.km_l, 2))}</td>
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
        ${_frotaHistoricoTable(["Data", "Tipo", "KM", "Valor"], manutRows, "Sem manutencoes registradas.")}
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
        ${_frotaHistoricoTable(["Data", "Status", "Comb.", "KM", "Posto / Emitente", "NF-e", "Qtd", "Valor", "KM/L"], abastRows, "Sem abastecimentos registrados.")}
      </div>
      <div class="frota-historico-card">
        <h4>Lavagens</h4>
        ${_frotaHistoricoTable(["Data", "KM", "Local", "Valor", "Observacao"], lavagemRows, "Sem lavagens registradas.")}
      </div>
    </div>
  `;
}

const RELATORIO_FRETE_TIPOS_FILTRAVEIS = new Set(["escala", "historico_fretes"]);

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

  window.open(`/api/frota_relatorio?${params.toString()}`, "_blank", "noopener");
}

function _estoqueFormatQtd(v){
  const n = Number(v || 0);
  if (!Number.isFinite(n)) return "0";
  const casas = Number.isInteger(n) ? 0 : 3;
  return n.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: 3 });
}

function sincronizarNumeroNotaPorCodigo(){
  const codigo = document.getElementById("estoqueCodigoBarras");
  const nota = document.getElementById("estoqueNumeroNota");
  if (!codigo || !nota) return;
  if (!nota.value.trim()) nota.value = (codigo.value || "").trim();
}

function bindEstoqueScannerInput(){
  const codigo = document.getElementById("estoqueCodigoBarras");
  const nota = document.getElementById("estoqueNumeroNota");
  const nome = document.getElementById("estoqueNomeProduto");
  if (!codigo || codigo.dataset.bound === "1") return;
  codigo.dataset.bound = "1";
  codigo.addEventListener("input", () => sincronizarNumeroNotaPorCodigo());
  codigo.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      sincronizarNumeroNotaPorCodigo();
      if (nota && !nota.value.trim()) nota.value = (codigo.value || "").trim();
      if (nome) nome.focus();
    }
  });
}

async function carregarSaldoEstoque(){
  const body = document.getElementById("estoqueSaldoBody");
  if (!body) return;
  const resp = await apiFetch("/api/estoque/saldo");
  if (!resp.ok) {
    body.innerHTML = `<tr><td colspan="5">Erro ao carregar saldo do estoque.</td></tr>`;
    return;
  }
  const dados = await resp.json();
  body.innerHTML = (dados || []).length ? (dados || []).map((r) => `
    <tr>
      <td>${_escHtml(r.nome_produto || "-")}</td>
      <td>${_escHtml(r.codigo_barras || "-")}</td>
      <td>${_escHtml(_estoqueFormatQtd(r.quantidade_atual))}</td>
      <td>R$ ${_escHtml(_fmtMoney(r.ultimo_valor))}</td>
      <td>${_escHtml(_fmtDateBr(r.ultima_movimentacao))}</td>
    </tr>
  `).join("") : `<tr><td colspan="5">Sem itens no estoque.</td></tr>`;
}

async function carregarMovimentosEstoque(){
  const body = document.getElementById("estoqueMovimentosBody");
  if (!body) return;
  const resp = await apiFetch("/api/estoque");
  if (!resp.ok) {
    body.innerHTML = `<tr><td colspan="7">Erro ao carregar histórico do estoque.</td></tr>`;
    return;
  }
  const dados = await resp.json();
  body.innerHTML = (dados || []).length ? (dados || []).map((r) => `
    <tr>
      <td>${_escHtml(_fmtDateBr(r.data_registro))}</td>
      <td>${_escHtml(r.numero_nota || "-")}</td>
      <td>${_escHtml(r.codigo_barras || "-")}</td>
      <td>${_escHtml(r.nome_produto || "-")}</td>
      <td>${_escHtml(r.tipo_movimento || "entrada")}</td>
      <td>${_escHtml(_estoqueFormatQtd(r.quantidade))}</td>
      <td>R$ ${_escHtml(_fmtMoney(r.valor_unitario))}</td>
    </tr>
  `).join("") : `<tr><td colspan="7">Sem lançamentos de estoque.</td></tr>`;
}

async function carregarEstoque(){
  await Promise.all([
    carregarSaldoEstoque(),
    carregarMovimentosEstoque()
  ]);
}

async function salvarMovimentoEstoque(){
  const codigo_barras = (document.getElementById("estoqueCodigoBarras")?.value || "").trim();
  const numero_nota = ((document.getElementById("estoqueNumeroNota")?.value || "").trim() || codigo_barras);
  const nome_produto = (document.getElementById("estoqueNomeProduto")?.value || "").trim();
  const quantidade = Number((document.getElementById("estoqueQuantidade")?.value || "").trim() || 0);
  const valor_unitario = Number((document.getElementById("estoqueValor")?.value || "").trim() || 0);

  if (!nome_produto) return alert("Informe o nome do produto.");
  if (!(quantidade > 0)) return alert("Informe uma quantidade válida.");

  const resp = await fetch("/api/estoque", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      codigo_barras,
      numero_nota,
      nome_produto,
      quantidade,
      valor_unitario,
      tipo_movimento: "entrada",
    }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao registrar item no estoque.");

  ["estoqueCodigoBarras", "estoqueNumeroNota", "estoqueNomeProduto", "estoqueQuantidade", "estoqueValor"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });

  await carregarEstoque();
  if (window.__dashView === "estoque") await renderDashboardEstoque();
  document.getElementById("estoqueCodigoBarras")?.focus();
}

async function renderDashboardEstoque(){
  const body = document.getElementById("dashEstoqueBody");
  if (!body) return;
  const resp = await apiFetch("/api/dashboard_estoque");
  if (!resp.ok) {
    body.innerHTML = `<tr><td colspan="5">Erro ao carregar dashboard do estoque.</td></tr>`;
    return;
  }
  const dados = await resp.json();
  body.innerHTML = (dados || []).length ? (dados || []).map((r) => `
    <tr>
      <td>${_escHtml(r.nome_produto || "-")}</td>
      <td>${_escHtml(r.codigo_barras || "-")}</td>
      <td>${_escHtml(_estoqueFormatQtd(r.quantidade_atual))}</td>
      <td>R$ ${_escHtml(_fmtMoney(r.ultimo_valor))}</td>
      <td>${_escHtml(_fmtDateBr(r.ultima_movimentacao))}</td>
    </tr>
  `).join("") : `<tr><td colspan="5">Sem itens cadastrados no estoque.</td></tr>`;
}

function _estoqueResumoFluxo(item){
  const origem = (item?.origem_setor || "").trim();
  const destino = (item?.destino_setor || "").trim();
  if (origem && destino) return `${origem} -> ${destino}`;
  return origem || destino || "-";
}

function _novoItemImportacaoEstoque(seq = 1){
  return {
    item_seq: String(seq || 1),
    codigo_produto_nfe: "",
    codigo_barras: "",
    nome_produto: "",
    unidade: "",
    quantidade: "",
    quantidade_embalagem: "",
    embalagem_tipo: "",
    fator_embalagem: "",
    fator_inferido: false,
    quantidade_unidades: "",
    valor_unitario: "",
  };
}

function _estoqueEmbalagemPadrao(valor = ""){
  const raw = String(valor || "").trim().toUpperCase();
  if (!raw) return "UN";
  if (raw.includes("CX48")) return "CX48";
  if (raw.includes("CX24")) return "CX24";
  if (/^CX\b/.test(raw) || raw.includes("CAIXA")) return "CX";
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
  return {
    id: Number(item.id || 0) || 0,
    codigo_barras: _digitsOnly(item.codigo_barras || ""),
    codigo_produto_nfe: String(item.codigo_produto_nfe || "").trim(),
    nome_produto: String(item.nome_produto || "").trim(),
    unidade: String(item.unidade || "").trim(),
    embalagem_tipo_padrao: _estoqueEmbalagemPadrao(item.embalagem_tipo_padrao || item.embalagem_tipo || item.unidade || ""),
    fator_embalagem_padrao: Number(item.fator_embalagem_padrao || item.fator_embalagem || 0) || 0,
  };
}

function _buscarProdutoCadastroEstoque(item = {}){
  const codigoBarras = _digitsOnly(item.codigo_barras || "");
  const codigoNfe = String(item.codigo_produto_nfe || "").trim().toUpperCase();
  const nome = String(item.nome_produto || "").trim().toUpperCase();
  const lista = Array.isArray(estoqueState.cadastroProdutos) ? estoqueState.cadastroProdutos : [];
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
  return null;
}

function _estoqueInferirFatorEmbalagem(item = {}){
  const embalagem = _estoqueEmbalagemPadrao(item.embalagem_tipo || item.unidade || "");
  const nome = String(item.nome_produto || "").toUpperCase();
  const unidade = String(item.unidade || "").toUpperCase();
  const candidatos = [embalagem, unidade, nome];
  for (const texto of candidatos) {
    const mCx = texto.match(/CX\s*0*48|CX48|C\/48|\b48\s*UN\b/);
    if (mCx) return 48;
    const mCx24 = texto.match(/CX\s*0*24|CX24|C\/24|\b24\s*UN\b/);
    if (mCx24) return 24;
  }
  for (const texto of candidatos) {
    const mPct = texto.match(/(?:PCT|PAC|PCT|C\/|COM|X)\s*0*([1-9]\d{0,2})/);
    if (mPct) return Number(mPct[1] || 0) || 1;
  }
  const fatorInformado = Number(item.fator_embalagem || 0);
  if (fatorInformado > 0) return fatorInformado;
  if (embalagem === "CX48") return 48;
  if (embalagem === "CX24") return 24;
  if (embalagem === "UN") return 1;
  const fallbackValor = Number(item.valor_unitario || 0);
  if (embalagem === "PCT" && fallbackValor > 0 && fallbackValor <= 200) return fallbackValor;
  return 1;
}

function _enriquecerItemImportacaoEstoque(item = {}){
  const cadastro = _buscarProdutoCadastroEstoque(item);
  let unidadeRaw = String(item.unidade || "").trim();
  if (/^\d[\d.,]*$/.test(unidadeRaw)) {
    unidadeRaw = "";
  }
  const embalagemInicial = item.embalagem_tipo || cadastro?.embalagem_tipo_padrao || unidadeRaw || "";
  const embalagemBase = _estoqueEmbalagemPadrao(embalagemInicial);
  const quantidade_embalagem = Number(item.quantidade_embalagem ?? item.quantidade ?? 0) || 0;
  const fatorInformado = Number(item.fator_embalagem || cadastro?.fator_embalagem_padrao || 0) || 0;
  const fator_embalagem = fatorInformado > 0
    ? fatorInformado
    : _estoqueInferirFatorEmbalagem({ ...item, unidade: unidadeRaw, embalagem_tipo: embalagemBase });
  const embalagem_tipo = _estoqueAjustarEmbalagemPorFator(embalagemBase, fator_embalagem);
  const quantidade_unidades = Number(item.quantidade_unidades ?? 0) || (quantidade_embalagem * (fator_embalagem > 0 ? fator_embalagem : 1));
  const fator_inferido = item.fator_inferido === true || item.fator_inferido === 1 || item.fator_inferido === "1"
    ? true
    : (fatorInformado <= 0 && fator_embalagem > 1 && embalagem_tipo !== "UN");
  return {
    ...item,
    unidade: unidadeRaw,
    embalagem_tipo,
    quantidade_embalagem,
    fator_embalagem: fator_embalagem > 0 ? fator_embalagem : 1,
    fator_inferido,
    quantidade_unidades,
  };
}

function _normalizarDraftImportacaoEstoque(draft){
  const base = draft || {};
  const itens = Array.isArray(base.itens) ? base.itens.map((item, idx) => ({
    item_seq: String(item?.item_seq || (idx + 1)).trim() || String(idx + 1),
    codigo_produto_nfe: (item?.codigo_produto_nfe || "").trim(),
    codigo_barras: (item?.codigo_barras || "").trim(),
    nome_produto: (item?.nome_produto || "").trim(),
    unidade: (item?.unidade || "").trim(),
    quantidade: item?.quantidade ?? "",
    quantidade_embalagem: item?.quantidade_embalagem ?? item?.quantidade ?? "",
    embalagem_tipo: (item?.embalagem_tipo || "").trim(),
    fator_embalagem: item?.fator_embalagem ?? "",
    fator_inferido: item?.fator_inferido === true || item?.fator_inferido === 1 || item?.fator_inferido === "1",
    quantidade_unidades: item?.quantidade_unidades ?? "",
    valor_unitario: item?.valor_unitario ?? "",
  })).map((item) => _enriquecerItemImportacaoEstoque(item)).filter((item) => (
    item.nome_produto || item.codigo_produto_nfe || item.codigo_barras || String(item.quantidade || "").trim() || String(item.valor_unitario || "").trim()
  )) : [];
  const sourceType = String(base.source_type || "xml").toLowerCase();

  return {
    source_type: sourceType === "pdf" || sourceType === "dfe" || sourceType === "portal" || sourceType === "ocr" || sourceType === "manual" ? sourceType : "xml",
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
    ? Array.from(body.querySelectorAll("tr[data-item-index]")).map((row, idx) => ({
        item_seq: row.querySelector(".estoque-import-item-seq")?.value || String(idx + 1),
        codigo_produto_nfe: row.querySelector(".estoque-import-item-codnfe")?.value || "",
        codigo_barras: row.querySelector(".estoque-import-item-codbar")?.value || "",
        nome_produto: row.querySelector(".estoque-import-item-nome")?.value || "",
        unidade: row.querySelector(".estoque-import-item-und")?.value || "",
        embalagem_tipo: row.querySelector(".estoque-import-item-und")?.value || "",
        quantidade: row.querySelector(".estoque-import-item-qtd")?.value || "",
        quantidade_embalagem: row.querySelector(".estoque-import-item-qtd")?.value || "",
        fator_embalagem: row.querySelector(".estoque-import-item-fator")?.value || "",
        fator_inferido: row.querySelector(".estoque-import-item-total-un")?.dataset.inferred === "1",
        quantidade_unidades: row.querySelector(".estoque-import-item-total-un")?.dataset.value || "",
        valor_unitario: row.querySelector(".estoque-import-item-valor")?.value || "",
      }))
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
    itens,
  });
}

function renderEstoqueImportPreview(){
  const card = document.getElementById("estoqueImportPreviewCard");
  const fonte = document.getElementById("estoqueImportPreviewFonte");
  const status = document.getElementById("estoqueImportPreviewStatus");
  const body = document.getElementById("estoqueImportPreviewItemsBody");
  const fotoPanel = document.getElementById("estoqueManualFotoPanel");
  const fotoImg = document.getElementById("estoqueManualFotoImg");
  const fotoNome = document.getElementById("estoqueManualFotoNome");
  if (!card || !fonte || !status || !body) return;

  const draft = estoqueState.importDraft ? _normalizarDraftImportacaoEstoque(estoqueState.importDraft) : null;
  if (!draft) {
    card.classList.add("hidden");
    body.innerHTML = `<tr><td colspan="10">Nenhum item carregado.</td></tr>`;
    if (fotoPanel) fotoPanel.classList.add("hidden");
    if (fotoImg) fotoImg.removeAttribute("src");
    if (fotoNome) fotoNome.textContent = "Nenhuma foto carregada.";
    return;
  }

  estoqueState.importDraft = draft;
  card.classList.remove("hidden");
  fonte.textContent = `Arquivo: ${draft.arquivo_origem || "-"} | Origem: ${_nfeImportSourceLabel(draft.source_type)}${draft.preview_tipo === "parcial" ? " (preview parcial)" : ""}`;
  status.textContent = draft.warnings.length
    ? draft.warnings.join(" | ")
    : "Revise os dados abaixo e confirme a importacao quando estiver tudo certo.";

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
    <tr data-item-index="${idx}">
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
      <td><input type="number" class="estoque-import-item-fator" min="1" step="1" value="${_escAttr(String(item.fator_embalagem ?? 1))}" oninput="atualizarTotaisImportacaoEstoque()"></td>
      <td>
        <div class="estoque-total-un-cell">
          <span class="estoque-import-item-total-un${item.fator_inferido ? " is-inferred" : ""}" data-value="${_escAttr(String(item.quantidade_unidades ?? 0))}" data-inferred="${item.fator_inferido ? "1" : "0"}">${_escHtml(_estoqueFormatQtd(item.quantidade_unidades ?? 0))}</span>
          ${item.fator_inferido ? '<span class="estoque-pack-hint">inferido</span>' : ""}
        </div>
      </td>
      <td><input type="number" class="estoque-import-item-valor" min="0" step="0.01" value="${_escAttr(String(item.valor_unitario ?? ""))}"></td>
      <td class="estoque-item-action"><button type="button" onclick="removerItemImportacaoEstoque(${idx})">Remover</button></td>
    </tr>
  `).join("");
  atualizarTotaisImportacaoEstoque(false);
}

function atualizarTotaisImportacaoEstoque(markDirty = true){
  document.querySelectorAll("#estoqueImportPreviewItemsBody tr[data-item-index]").forEach((row) => {
    const undEl = row.querySelector(".estoque-import-item-und");
    const qtdEl = row.querySelector(".estoque-import-item-qtd");
    const fatorEl = row.querySelector(".estoque-import-item-fator");
    const totalEl = row.querySelector(".estoque-import-item-total-un");
    if (!totalEl) return;
    const item = _enriquecerItemImportacaoEstoque({
      unidade: undEl?.value || "",
      embalagem_tipo: undEl?.value || "",
      quantidade: qtdEl?.value || "",
      quantidade_embalagem: qtdEl?.value || "",
      fator_embalagem: fatorEl?.value || "",
      fator_inferido: totalEl?.dataset.inferred === "1",
    });
    if (fatorEl && (!String(fatorEl.value || "").trim() || Number(fatorEl.value || 0) <= 0)) {
      fatorEl.value = String(item.fator_embalagem || 1);
    }
    totalEl.dataset.value = String(item.quantidade_unidades || 0);
    totalEl.dataset.inferred = item.fator_inferido ? "1" : "0";
    totalEl.classList.toggle("is-inferred", !!item.fator_inferido);
    totalEl.textContent = _estoqueFormatQtd(item.quantidade_unidades || 0);
    const cell = totalEl.closest(".estoque-total-un-cell");
    if (cell) {
      let hint = cell.querySelector(".estoque-pack-hint");
      if (item.fator_inferido) {
        if (!hint) {
          hint = document.createElement("span");
          hint.className = "estoque-pack-hint";
          hint.textContent = "inferido";
          cell.appendChild(hint);
        }
      } else if (hint) {
        hint.remove();
      }
    }
  });
  if (markDirty) estoqueState.importDraftDirty = true;
}

function adicionarItemImportacaoEstoque(){
  const draftAtual = _coletarDraftImportacaoEstoqueForm() || _normalizarDraftImportacaoEstoque(estoqueState.importDraft || {});
  const itens = Array.isArray(draftAtual.itens) ? [...draftAtual.itens] : [];
  itens.push(_novoItemImportacaoEstoque(itens.length + 1));
  estoqueState.importDraft = { ...draftAtual, itens };
  estoqueState.importDraftDirty = true;
  renderEstoqueImportPreview();
}

function removerItemImportacaoEstoque(index){
  const draftAtual = _coletarDraftImportacaoEstoqueForm();
  if (!draftAtual) return;
  const itens = (draftAtual.itens || []).filter((_, idx) => idx !== Number(index));
  estoqueState.importDraft = { ...draftAtual, itens };
  estoqueState.importDraftDirty = true;
  renderEstoqueImportPreview();
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

  const status = document.getElementById("estoqueImportPreviewStatus");
  if (status) status.textContent = "Confirmando importacao da NF-e...";
  const resp = await apiFetch("/api/estoque/nfe/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      preview: draft,
      chave_acesso_esperada: _digitsOnly(document.getElementById("estoqueChaveAcesso")?.value || ""),
    }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (status) status.textContent = data?.erro || "Falha ao confirmar a importacao da NF-e.";
    alert(data?.erro || "Falha ao confirmar a importacao da NF-e.");
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
    const conferenciaId = data?.conferencia?.id ? `Conferencia #${data.conferencia.id}` : "conferencia criada";
    statusLancar.textContent = `NF-e importada com sucesso. ${data?.produtos_criados || 0} item(ns) cadastrados automaticamente. ${conferenciaId}.`;
  }

  setEstoqueView("conferir");
  await carregarConferenciasEstoque(data?.conferencia?.id || null);
  if (data?.conferencia?.id) {
    await selecionarConferenciaEstoque(data.conferencia.id);
  }
}

function setEstoqueView(view){
  const nextView = view === "conferir" ? "conferir" : (view === "cadastrar" ? "cadastrar" : "lancar");
  estoqueState.view = nextView;
  window.__estoqueView = nextView;

  const viewLancar = document.getElementById("estoqueViewLancar");
  const viewConferir = document.getElementById("estoqueViewConferir");
  const viewCadastrar = document.getElementById("estoqueViewCadastrar");
  const btnLancar = document.getElementById("estoqueViewBtnLancar");
  const btnConferir = document.getElementById("estoqueViewBtnConferir");
  const btnCadastrar = document.getElementById("estoqueViewBtnCadastrar");

  if (viewLancar) viewLancar.classList.toggle("hidden", nextView !== "lancar");
  if (viewConferir) viewConferir.classList.toggle("hidden", nextView !== "conferir");
  if (viewCadastrar) viewCadastrar.classList.toggle("hidden", nextView !== "cadastrar");
  if (btnLancar) btnLancar.classList.toggle("active", nextView === "lancar");
  if (btnConferir) btnConferir.classList.toggle("active", nextView === "conferir");
  if (btnCadastrar) btnCadastrar.classList.toggle("active", nextView === "cadastrar");

  renderEstoqueImportPreview();
  atualizarStatusCodbarSistema();
  if (nextView === "conferir") {
    carregarConferenciasEstoque(estoqueState.conferenciaAtual?.conferencia?.id || null).catch((e) => {
      console.warn("conferencias estoque erro:", e);
    });
  } else if (nextView === "cadastrar") {
    carregarProdutosEstoqueCadastro().catch((e) => {
      console.warn("cadastro estoque erro:", e);
    });
  }
}

function limparProdutoEstoqueCadastro(){
  estoqueState.cadastroProdutoEditId = 0;
  const ids = [
    "estoqueCadastroCodigoBarras",
    "estoqueCadastroCodigoNfe",
    "estoqueCadastroNomeProduto",
    "estoqueCadastroEmbalagem",
    "estoqueCadastroFator",
  ];
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  const status = document.getElementById("estoqueCadastroStatus");
  if (status) status.textContent = "Cadastre o produto e o fator da embalagem para automatizar a conversao da NF-e.";
}

async function carregarProdutosEstoqueCadastro(){
  const body = document.getElementById("estoqueCadastroProdutosBody");
  if (!body) return;
  try {
    await ensureProdutosEstoqueCache();
  } catch (err) {
    body.innerHTML = `<tr><td colspan="5">Falha ao carregar cadastros.</td></tr>`;
    return;
  }
  body.innerHTML = estoqueState.cadastroProdutos.length ? estoqueState.cadastroProdutos.map((item) => `
    <tr class="estoque-cadastro-row${Number(estoqueState.cadastroProdutoEditId || 0) === Number(item.id || 0) ? " is-editing" : ""}">
      <td>${_escHtml(item.nome_produto || "-")}</td>
      <td>${_escHtml(item.codigo_barras || item.codigo_produto_nfe || "-")}</td>
      <td>${_escHtml(item.embalagem_tipo_padrao || item.unidade || "UN")}</td>
      <td>${_escHtml(_estoqueFormatQtd(item.fator_embalagem_padrao || 0))}</td>
      <td>
        <button type="button" onclick="editarProdutoEstoqueCadastro(${Number(item.id || 0)})">Editar</button>
        <button type="button" onclick="excluirProdutoEstoqueCadastro(${Number(item.id || 0)})">Excluir</button>
      </td>
    </tr>
  `).join("") : `<tr><td colspan="5">Nenhum produto cadastrado.</td></tr>`;
}

async function ensureProdutosEstoqueCache(force = false){
  if (!force && Array.isArray(estoqueState.cadastroProdutos) && estoqueState.cadastroProdutos.length) {
    return estoqueState.cadastroProdutos;
  }
  const resp = await apiFetch("/api/estoque/produtos");
  if (!resp.ok) {
    throw new Error("Falha ao carregar produtos do estoque.");
  }
  const dados = await resp.json().catch(() => ([]));
  estoqueState.cadastroProdutos = _ordenarListaNatural(
    Array.isArray(dados) ? dados.map(_estoqueProdutoCadastroNormalizado) : [],
    (item) => item?.nome_produto || item?.codigo_barras || item?.codigo_produto_nfe || ""
  );
  return estoqueState.cadastroProdutos;
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
  const atualLabel = String(itemAtual.nome_produto || itemAtual.codigo_barras || itemAtual.codigo_produto_nfe || "").trim();
  const opcoes = [];
  if (atualLabel) {
    opcoes.push(`<option value="${_escAttr(atualLabel)}" selected>Atual: ${_escHtml(atualLabel)}</option>`);
  } else {
    opcoes.push(`<option value="" selected>Selecione um produto</option>`);
  }
  (estoqueState.cadastroProdutos || []).forEach((prod) => {
    const rotuloBase = String(prod.nome_produto || "").trim() || prod.codigo_barras || prod.codigo_produto_nfe || `Produto ${prod.id || ""}`;
    const emb = prod.embalagem_tipo_padrao ? ` | ${prod.embalagem_tipo_padrao}${prod.fator_embalagem_padrao ? ` ${_estoqueFormatQtd(prod.fator_embalagem_padrao)}` : ""}` : "";
    const selected = rotuloBase === atualLabel ? "selected" : "";
    opcoes.push(
      `<option value="${_escAttr(rotuloBase)}" data-produto-id="${_escAttr(String(prod.id || ""))}" data-codbarras="${_escAttr(prod.codigo_barras || "")}" data-codnfe="${_escAttr(prod.codigo_produto_nfe || "")}" data-emb="${_escAttr(prod.embalagem_tipo_padrao || "")}" data-fator="${_escAttr(String(prod.fator_embalagem_padrao || ""))}" ${selected}>${_escHtml(rotuloBase + emb)}</option>`
    );
  });
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
  if (codBarEl && selected.dataset.codbarras) codBarEl.value = selected.dataset.codbarras;
  if (codNfeEl && selected.dataset.codnfe) codNfeEl.value = selected.dataset.codnfe;
  if (embEl && selected.dataset.emb) embEl.value = selected.dataset.emb;
  if (fatorEl && selected.dataset.fator) fatorEl.value = selected.dataset.fator;
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
    estoqueCadastroEmbalagem: item.embalagem_tipo_padrao || item.unidade || "",
    estoqueCadastroFator: item.fator_embalagem_padrao || "",
  };
  Object.entries(map).forEach(([idCampo, valor]) => {
    const el = document.getElementById(idCampo);
    if (el) el.value = valor;
  });
  const status = document.getElementById("estoqueCadastroStatus");
  if (status) status.textContent = `Editando cadastro de embalagem: ${item.nome_produto || item.codigo_barras || item.codigo_produto_nfe || item.id}`;
}

async function salvarProdutoEstoqueCadastro(){
  const payload = {
    codigo_barras: _digitsOnly(document.getElementById("estoqueCadastroCodigoBarras")?.value || ""),
    codigo_produto_nfe: (document.getElementById("estoqueCadastroCodigoNfe")?.value || "").trim(),
    nome_produto: (document.getElementById("estoqueCadastroNomeProduto")?.value || "").trim(),
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
  await carregarProdutosEstoqueCadastro();
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
  await carregarProdutosEstoqueCadastro();
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

function _aplicarCodigoEscaneadoEstoque(codigo){
  const valor = String(codigo || "").trim();
  if (!valor) return;
  const digits = _digitsOnly(valor);
  const targetFieldId = estoqueState.cameraTargetFieldId || "";
  if (targetFieldId) {
    const campoAlvo = document.getElementById(targetFieldId);
    if (campoAlvo) {
      campoAlvo.value = digits.length === 44 ? digits : valor;
      campoAlvo.dispatchEvent(new Event("input", { bubbles: true }));
      if (digits.length === 44) {
        normalizarChaveNfeCampo(campoAlvo, true);
      }
      campoAlvo.focus();
      return;
    }
  }
  const campoCodigo = document.getElementById("estoqueCodigoBarras");
  const campoNota = document.getElementById("estoqueNumeroNota");
  const campoChave = document.getElementById("estoqueChaveAcesso");
  if (digits.length === 44 && campoChave) {
    campoChave.value = digits;
    campoChave.dispatchEvent(new Event("input", { bubbles: true }));
    normalizarChaveNfeCampo(campoChave, true);
    return;
  }
  if (campoCodigo) campoCodigo.value = valor;
  if (campoNota && !campoNota.value.trim()) campoNota.value = valor;
  sincronizarNumeroNotaPorCodigo();
  document.getElementById("estoqueNomeProduto")?.focus();
}

async function abrirCameraEstoque(targetFieldId = ""){
  if (!navigator.mediaDevices?.getUserMedia) {
    alert("Camera/webcam indisponivel neste navegador.");
    return;
  }

  const modal = document.getElementById("estoqueCameraModal");
  const video = document.getElementById("estoqueCameraVideo");
  const status = document.getElementById("estoqueCameraStatus");
  if (!modal || !video || !status) return;

  _pararCameraEstoque();
  estoqueState.cameraTargetFieldId = String(targetFieldId || "").trim();
  modal.classList.remove("hidden");
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

  if (!window.BarcodeDetector) {
    status.textContent = "Camera aberta, mas este navegador nao suporta leitura automatica por webcam.";
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
    status.textContent = "Camera aberta, mas a leitura automatica nao esta disponivel agora.";
    return;
  }

  status.textContent = "Aponte a camera para o codigo de barras da nota.";
  estoqueState.cameraTimer = setInterval(async () => {
    if (estoqueState.scanningCamera || !detector || !video.srcObject) return;
    estoqueState.scanningCamera = true;
    try {
      const codes = await detector.detect(video);
      const code = (codes || []).find((item) => (item?.rawValue || "").trim());
      if (code?.rawValue) {
        _aplicarCodigoEscaneadoEstoque(code.rawValue);
        status.textContent = `Codigo lido: ${code.rawValue}`;
        fecharCameraEstoque();
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
  if (modal) modal.classList.add("hidden");
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
  setEstoqueView("conferir");
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
  setEstoqueView("conferir");
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

function _aplicarResultadoOcrAbastecimento(id, ocr){
  const campoChave = document.getElementById(`abast_chave_${id}`);
  const campoNota = document.getElementById(`abast_nota_${id}`);
  const campoEmitente = document.getElementById(`abast_emitente_${id}`);
  const campoValor = document.getElementById(`abast_valor_${id}`);

  if (campoChave && ocr?.chave_acesso) {
    campoChave.value = ocr.chave_acesso;
    campoChave.dispatchEvent(new Event("input", { bubbles: true }));
    normalizarChaveNfeCampo(campoChave, true);
  }
  if (campoNota && ocr?.numero_nota) campoNota.value = ocr.numero_nota;
  if (campoEmitente && ocr?.emitente_nome) campoEmitente.value = ocr.emitente_nome;
  if (campoValor && ocr?.valor_total != null && ocr?.valor_total !== "") {
    campoValor.value = String(ocr.valor_total);
  }

  alert(
    ocr?.chave_acesso
      ? `Foto lida com OCR. ${_formatarResumoOcrNfe(ocr)}`
      : `Foto lida com OCR. ${_formatarResumoOcrNfe(ocr)}`
  );
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

  const status = document.getElementById("estoqueNfeOcrStatus");
  if ((context.tipo === "estoque" || context.tipo === "estoque_itens" || context.tipo === "estoque_azure") && status) {
    status.textContent = context.tipo === "estoque_itens"
      ? "Enviando foto da grade de itens para OCR..."
      : context.tipo === "estoque_azure"
        ? "Enviando foto para o Azure Document Intelligence..."
      : "Enviando foto da nota para leitura OCR...";
  }

  let arquivoOcr = file;
  try {
    arquivoOcr = await _compactarImagemParaOcr(file);
  } catch {}
  if ((context.tipo === "estoque" || context.tipo === "estoque_itens" || context.tipo === "estoque_azure") && status && arquivoOcr !== file) {
    status.textContent = context.tipo === "estoque_itens"
      ? "Foto compactada. Enviando grade de itens para OCR..."
      : context.tipo === "estoque_azure"
        ? "Foto compactada. Enviando itens para o Azure..."
      : "Foto compactada. Enviando nota para OCR...";
  }

  const formData = new FormData();
  formData.append("arquivo", arquivoOcr);
  const controller = new AbortController();
  const timeoutMs = (context.tipo === "estoque_itens" || context.tipo === "estoque_azure") ? 180000 : 90000;
  const timeoutHandle = setTimeout(() => controller.abort(), timeoutMs);
  let resp;
  let data = {};
  const url = context.tipo === "estoque_itens"
    ? "/api/estoque/nfe/ocr_itens"
    : context.tipo === "estoque_azure"
      ? "/api/estoque/nfe/azure_itens"
      : "/api/estoque/nfe/ocr";
  try {
    resp = await apiFetch(url, {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });
    data = await resp.json().catch(() => ({}));
  } catch (err) {
    clearTimeout(timeoutHandle);
    const mensagem = err?.name === "AbortError"
      ? (context.tipo === "estoque_itens"
          ? "A leitura OCR dos itens demorou demais. Na primeira execucao o motor novo pode levar mais tempo; tente novamente com 5 a 10 linhas da tabela por vez."
          : context.tipo === "estoque_azure"
            ? "O Azure demorou demais para responder. Confira a configuracao em Config > NF-e ou tente outra foto."
            : "A leitura OCR demorou demais para responder. Tente uma foto mais aproximada, reta e focada na grade dos itens.")
      : "Falha ao enviar a foto da nota para OCR.";
    if ((context.tipo === "estoque" || context.tipo === "estoque_itens" || context.tipo === "estoque_azure") && status) status.textContent = mensagem;
    alert(mensagem);
    if (input) input.value = "";
    return;
  }
  clearTimeout(timeoutHandle);
  if (!resp.ok) {
    const mensagem = data?.erro || "Falha ao ler a foto da nota.";
    if ((context.tipo === "estoque" || context.tipo === "estoque_itens" || context.tipo === "estoque_azure") && status) status.textContent = mensagem;
    alert(mensagem);
    if (input) input.value = "";
    return;
  }

  if (context.tipo === "estoque_itens" || context.tipo === "estoque_azure") {
    _aplicarPreviewItensOcrEstoque(data?.preview || {});
  } else if (context.tipo === "abastecimento" && context.id) {
    _aplicarResultadoOcrAbastecimento(context.id, data?.ocr || {});
  } else {
    _aplicarResultadoOcrEstoque(data?.ocr || {});
  }

  if (Array.isArray(data?.warnings) && data.warnings.length) {
    const aviso = data.warnings.join(" ");
    if ((context.tipo === "estoque" || context.tipo === "estoque_itens" || context.tipo === "estoque_azure") && status) {
      status.textContent = context.tipo === "estoque_itens"
        ? `Itens lidos por OCR. Avisos: ${aviso}`
        : context.tipo === "estoque_azure"
          ? `Itens lidos via Azure. Avisos: ${aviso}`
        : `${_formatarResumoOcrNfe(data?.ocr || {})} Avisos: ${aviso}`;
    }
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
  setEstoqueView("conferir");
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
  setEstoqueView("conferir");
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
  setEstoqueView("conferir");
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
  setEstoqueView("conferir");
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
  if (!body) return;
  const resp = await apiFetch("/api/estoque/saldo");
  if (!resp.ok) {
    body.innerHTML = `<tr><td colspan="5">Erro ao carregar saldo do estoque.</td></tr>`;
    return;
  }
  const dados = await resp.json();
  body.innerHTML = (dados || []).length ? (dados || []).map((r) => `
    <tr>
      <td>${_escHtml(r.nome_produto || "-")}</td>
      <td>${_escHtml(r.codigo_barras || "-")}</td>
      <td>${_escHtml(_estoqueFormatQtd(r.quantidade_atual))}</td>
      <td>R$ ${_escHtml(_fmtMoney(r.ultimo_valor))}</td>
      <td>${_escHtml(_fmtDateBr(r.ultima_movimentacao))}</td>
    </tr>
  `).join("") : `<tr><td colspan="5">Sem itens no estoque.</td></tr>`;
}

async function carregarMovimentosEstoque(){
  const body = document.getElementById("estoqueMovimentosBody");
  if (!body) return;
  const resp = await apiFetch("/api/estoque");
  if (!resp.ok) {
    body.innerHTML = `<tr><td colspan="10">Erro ao carregar historico do estoque.</td></tr>`;
    return;
  }
  const dados = await resp.json();
  body.innerHTML = (dados || []).length ? (dados || []).map((r) => `
    <tr>
      <td>${_escHtml(_fmtDateBr(r.data_registro))}</td>
      <td>${_escHtml(r.numero_nota || "-")}</td>
      <td>${_escHtml(r.codigo_barras || "-")}</td>
      <td>${_escHtml(r.nome_produto || "-")}</td>
      <td>${_escHtml(r.tipo_movimento || "entrada")}</td>
      <td>${_escHtml(_estoqueFormatQtd(r.quantidade))}</td>
      <td>R$ ${_escHtml(_fmtMoney(r.valor_unitario))}</td>
      <td>${_escHtml(_estoqueResumoFluxo(r))}</td>
      <td>${_escHtml(r.usuario_registro || "-")}</td>
      <td>
        <button type="button" onclick="editarMovimentoEstoque(${Number(r.id || 0)})">Editar</button>
        <button type="button" onclick="excluirMovimentoEstoque(${Number(r.id || 0)})">Excluir</button>
      </td>
    </tr>
  `).join("") : `<tr><td colspan="10">Sem lancamentos de estoque.</td></tr>`;
}

async function editarMovimentoEstoque(id){
  const resp = await apiFetch("/api/estoque");
  if (!resp.ok) return alert("Nao foi possivel carregar o lancamento.");
  const dados = await resp.json();
  const item = (dados || []).find((r) => Number(r.id) === Number(id));
  if (!item) return alert("Lancamento nao encontrado.");

  const numero_nota = prompt("Numero da nota:", item.numero_nota || "");
  if (numero_nota == null) return;
  const codigo_barras = prompt("Codigo:", item.codigo_barras || "");
  if (codigo_barras == null) return;
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
      codigo_barras,
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
}

async function excluirMovimentoEstoque(id){
  if (!confirm("Deseja realmente excluir este item lancado?")) return;
  const resp = await apiFetch(`/api/estoque/${id}`, { method: "DELETE" });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao excluir lancamento.");
  await carregarEstoque();
}

async function carregarEstoque(){
  renderEstoqueImportPreview();
  atualizarStatusCodbarSistema();
  const tarefas = [
    carregarSaldoEstoque(),
    carregarMovimentosEstoque(),
    carregarProdutosEstoqueCadastro(),
  ];
  if ((window.__estoqueView || estoqueState.view) === "conferir") {
    tarefas.push(carregarConferenciasEstoque(estoqueState.conferenciaAtual?.conferencia?.id || null));
  }
  await Promise.all(tarefas);
}

async function salvarMovimentoEstoque(){
  const codigo_barras = (document.getElementById("estoqueCodigoBarras")?.value || "").trim();
  const numero_nota = ((document.getElementById("estoqueNumeroNota")?.value || "").trim() || codigo_barras);
  const nome_produto = (document.getElementById("estoqueNomeProduto")?.value || "").trim();
  const quantidade = Number((document.getElementById("estoqueQuantidade")?.value || "").trim() || 0);
  const valor_unitario = Number((document.getElementById("estoqueValor")?.value || "").trim() || 0);
  const codigoDigits = _digitsOnly(codigo_barras);

  if (codigoDigits.length === 44) {
    return alert("Esse codigo parece ser a chave da NF-e. Use o campo de importacao do XML para lancar a nota completa.");
  }
  if (!nome_produto) return alert("Informe o nome do produto.");
  if (!(quantidade > 0)) return alert("Informe uma quantidade valida.");

  const resp = await apiFetch("/api/estoque", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      codigo_barras,
      numero_nota,
      nome_produto,
      quantidade,
      valor_unitario,
      tipo_movimento: "entrada",
      origem_setor: "Fabrica",
      destino_setor: "Almoxarifado",
    }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return alert(data?.erro || "Erro ao registrar item no estoque.");

  const importStatus = document.getElementById("estoqueNfeImportStatus");
  if (importStatus && data?.produto_criado) {
    importStatus.textContent = `Produto "${nome_produto}" cadastrado automaticamente no estoque.`;
  }

  ["estoqueCodigoBarras", "estoqueNomeProduto", "estoqueQuantidade", "estoqueValor"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });

  await carregarEstoque();
  if (window.__dashView === "estoque") await renderDashboardEstoque();
  document.getElementById("estoqueCodigoBarras")?.focus();
}

function openDashboardView(ev, view){
  if (ev){ ev.preventDefault(); ev.stopPropagation(); }
  const dashMenu = document.querySelector('.menu-item.has-submenu[data-tab="dashboard"]');
  showTab("dashboard", dashMenu);

  document.querySelectorAll("#submenuDashboard .submenu-item").forEach(x=>x.classList.remove("active"));
  const map = { resumo: 0, frota: 1, estoque: 2 };
  const target = map[view] ?? 0;
  const items = document.querySelectorAll("#submenuDashboard .submenu-item");
  if (items && items[target]) items[target].classList.add("active");

  setDashboardView(view);

  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile && dashMenu) dashMenu.classList.remove("open");
  try{ toggleMenuMobile(false); }catch{}
}

function setDashboardView(view){
  window.__dashView = view;
  const vResumo = document.getElementById("dashViewResumo");
  const vFrota = document.getElementById("dashViewFrota");
  const vEstoque = document.getElementById("dashViewEstoque");
  if (vResumo) vResumo.classList.toggle("hidden", view !== "resumo");
  if (vFrota) vFrota.classList.toggle("hidden", view !== "frota");
  if (vEstoque) vEstoque.classList.toggle("hidden", view !== "estoque");

  if (view === "frota") {
    renderDashboardFrota().catch(e=>console.warn("dash frota erro:", e));
  } else if (view === "estoque") {
    renderDashboardEstoque().catch(e=>console.warn("dash estoque erro:", e));
  } else {
    atualizarDash().catch(()=>{});
  }
}

async function renderFretes() {
  await ensureCadastrosCache();

  const colunas = {
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

  Object.values(colunas).forEach((col) => col && (col.innerHTML = ""));

  fretes.forEach((f) => {
    const col = colunas[f.status];
    if (!col) return;

    const card = document.createElement("div");
    card.className = "card";
    card.dataset.freteId = String(f.id);

    const header = document.createElement("div");
    header.className = "card-header";
    header.draggable = true;
    header.dataset.freteId = String(f.id);
    header.ondragstart = (e) => e.dataTransfer.setData("id", f.id);
    header.innerText = f.nome || "(sem nome)";

    const body = document.createElement("div");
    body.className = "card-body";

    const nomeVal = (f.nome || "").toString();
    const obsVal = (f.observacao || "").toString();
    const kmAtualVal = Number(f.km_atual || 0);
    const pesoVal = Number(f.peso || 0);
    const qtdEntregasVal = Number(f.qtd_entregas || 0);

    body.innerHTML = `
      <div class="crud-row">
        <label>Nome</label>
        <input type="text" class="frete-nome" value="${nomeVal.replaceAll('"', "&quot;")}">
      </div>

      <div class="crud-row-line1">
        <div class="crud-field">
          <span>Veiculo</span>
          <select class="frete-veiculo">
            ${optionsFrom(cacheCadastros.veiculos, f.veiculo_id)}
          </select>
        </div>

        <div class="crud-field">
          <span>Motorista</span>
          <select class="frete-motorista">
            ${optionsFrom(cacheCadastros.motoristas, f.motorista_id)}
          </select>
        </div>

        <div class="crud-field">
          <span>Entregador</span>
          <select class="frete-entregador">
            ${optionsFrom(cacheCadastros.motoristas, f.entregador_id || f.motorista_id)}
          </select>
        </div>
      </div>

      <div class="crud-row-line2">
        <div class="crud-field">
          <span>KM atual</span>
          <input type="number" class="frete-km-atual" min="0" value="${_escHtml(String(kmAtualVal))}">
        </div>

        <div class="crud-field">
          <span>Peso</span>
          <input type="number" class="frete-peso" min="0" step="0.001" value="${_escHtml(String(pesoVal))}">
        </div>

        <div class="crud-field">
          <span>Qtd. entregas</span>
          <input type="number" class="frete-qtd-entregas" min="0" value="${_escHtml(String(qtdEntregasVal))}">
        </div>

        <div class="crud-field">
          <span>Carga</span>
          <select class="frete-carga">
            ${optionsFrom(cacheCadastros.cargas, f.carga_id)}
          </select>
        </div>
      </div>

      <div class="crud-row">
        <label>Observacao</label>
        <textarea class="frete-obs" rows="2" placeholder="Digite uma observacao...">${obsVal}</textarea>
      </div>

      <div class="crud-actions">
        <button class="btn-mover-mobile">Mover</button>
        <button class="btn-salvar">Salvar</button>
        <button class="btn-excluir">Excluir</button>
      </div>
    `;

    const inpNome = body.querySelector(".frete-nome");
    const selVeiculo = body.querySelector(".frete-veiculo");
    const selMotorista = body.querySelector(".frete-motorista");
    const selEntregador = body.querySelector(".frete-entregador");
    const selCarga = body.querySelector(".frete-carga");
    const inpKmAtual = body.querySelector(".frete-km-atual");
    const inpPeso = body.querySelector(".frete-peso");
    const inpQtdEntregas = body.querySelector(".frete-qtd-entregas");
    const txtObs = body.querySelector(".frete-obs");
    const btnMoverMobile = body.querySelector(".btn-mover-mobile");

    if (btnMoverMobile) {
      btnMoverMobile.onclick = async () => {
        await moverFreteMobile(f);
      };
      btnMoverMobile.style.display = window.matchMedia("(max-width: 768px)").matches ? "" : "none";
    }

    body.querySelector(".btn-salvar").onclick = async () => {
      const payload = {
        nome: (inpNome.value || "").trim(),
        status: f.status,
        veiculo_id: selVeiculo.value ? Number(selVeiculo.value) : null,
        motorista_id: selMotorista.value ? Number(selMotorista.value) : null,
        entregador_id: selEntregador.value ? Number(selEntregador.value) : (selMotorista.value ? Number(selMotorista.value) : null),
        carga_id: selCarga.value ? Number(selCarga.value) : null,
        km_atual: inpKmAtual.value.trim() === "" ? 0 : Number(inpKmAtual.value),
        peso: inpPeso.value.trim() === "" ? 0 : Number(inpPeso.value),
        qtd_entregas: inpQtdEntregas.value.trim() === "" ? 0 : Number(inpQtdEntregas.value),
        observacao: (txtObs.value || "").trim(),
      };

      if (!payload.nome) return alert("Nome do frete e obrigatorio.");
      await atualizarFreteCompleto(f.id, payload);
    };

    body.querySelector(".btn-excluir").onclick = async () => {
      await excluirFrete(f.id);
    };

    card.appendChild(header);
    card.appendChild(body);
    col.appendChild(card);
  });

  ativarDragDrop();
  ativarDragDropMobile();
}

async function renderFretes() {
  await ensureCadastrosCache();

  const presentes = new Set();
  fretes.forEach((f) => {
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
  await renderFretes();
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
  bindLoginSubmitOnEnter();
  bindEstoqueScannerInput();
  alternarModoNovaCameraConfig();
  verificarRetornoPortalNfePendente();
  setEstoqueView(window.__estoqueView || "lancar");
  renderFiltrosRelatorioFretes();

  // 2) Status pode rodar sem travar nada
  verificarStatus();
  setInterval(verificarStatus, 5000);

  // 3) Carregar dados EM PARALELO (não sequencial)
  Promise.allSettled([
    carregarSelectsNovoFrete(),
    carregarFretes(),
    carregarEstoque(),
    renderCadastros(),
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

  let okSessao = false;
  try { okSessao = await restaurarSessaoLogin(); } catch {}
  if (LOGIN_BYPASS) {
    fecharLoginModal();
    atualizarUsuarioLogadoUI();
  } else if (!okSessao) {
    abrirLoginModal();
  } else {
    fecharLoginModal();
    try {
      await carregarUsuariosChat(false);
      await carregarNaoLidasChat();
      atualizarUsuarioLogadoUI();
    } catch {}
  }

  ensureCadastrosCache().catch(()=>{});
  // 4) Auto-atualização (não precisa esperar o resto)
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
