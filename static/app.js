function qs(selector) {
  return document.querySelector(selector);
}

function setMessage(selector, text, kind) {
  const el = qs(selector);
  if (!el) return;
  el.textContent = text || "";
  el.dataset.kind = kind || "";
}

async function postJson(url, payload) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.erro || "Falha na requisicao");
  }
  return data;
}

function filenameFromDisposition(value, fallback) {
  const match = String(value || "").match(/filename="?([^"]+)"?/i);
  return match ? match[1] : fallback;
}

function bindLogin() {
  const form = qs("#loginForm");
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setMessage("#loginMsg", "Entrando...", "");
    const login = qs("#loginUsuario")?.value.trim();
    const senha = qs("#loginSenha")?.value.trim();
    try {
      await postJson("/api/login", { login, senha });
      window.location.href = "/";
    } catch (err) {
      setMessage("#loginMsg", err.message, "error");
    }
  });
}

function bindLogout() {
  document.querySelectorAll("[data-logout]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await postJson("/api/logout", {});
      } finally {
        window.location.href = "/login";
      }
    });
  });
}

function bindMenu() {
  const menu = qs("[data-menu]");
  const overlay = qs("[data-menu-overlay]");
  const toggle = qs("[data-menu-toggle]");
  function open(next) {
    if (!menu || !overlay) return;
    menu.classList.toggle("show", next);
    overlay.classList.toggle("show", next);
    document.body.classList.toggle("menu-open", next);
  }
  toggle?.addEventListener("click", () => open(!menu.classList.contains("show")));
  overlay?.addEventListener("click", () => open(false));
}

function syncMenuSection() {
  let section = null;
  const hash = (location.hash || "").replace("#", "");
  if (location.pathname === "/") section = "portal";
  if (location.pathname.startsWith("/config")) section = "config";
  if (location.pathname.startsWith("/workflow/")) section = "workflow";
  if (location.pathname.startsWith("/apps/financeiro")) {
    const params = new URLSearchParams(location.search);
    const view = params.get("view") || hash || "dashboard";
    const financeSections = {
      dashboard: "dashboards",
      categorias: "cadastros",
      conciliacao: "workflow",
      compras: "compras",
      contas: "financeiro",
      pagar: "financeiro",
      receber: "financeiro",
      lancamentos: "relatorios",
      importar: "import_export",
      config: "config",
    };
    section = financeSections[view] || "dashboards";
  }
  if (location.pathname.startsWith("/apps/automacao")) {
    if (location.pathname.includes("/motores") || location.pathname.includes("/motor") || location.pathname.includes("/sensores/drivers")) {
      section = "cadastros";
    } else if (location.pathname.includes("/alarmes")) {
      section = "workflow";
    } else if (location.pathname.includes("/historico")) {
      section = "relatorios";
    } else if (location.pathname.includes("/setores")) {
      section = "config";
    } else {
      section = "dashboards";
    }
  }
  if (location.pathname.startsWith("/apps/nanoponto")) {
    const params = new URLSearchParams(location.search);
    const panel = params.get("panel") || "";
    const pointSections = {
      "justify-card": "workflow",
      "medical-certificate-card": "workflow",
      "agenda-card": "workflow",
      "settings-card": "config",
      "email-card": "config",
    };
    section = pointSections[panel] || "ponto";
  }
  if (location.pathname.startsWith("/apps/zap")) {
    if (location.pathname.startsWith("/apps/zap/settings") || location.pathname.startsWith("/apps/zap/docs")) {
      section = "config";
    } else if (location.pathname.startsWith("/apps/zap/calendar") || location.pathname.startsWith("/apps/zap/agenda")) {
      section = "cadastros";
    } else {
      section = "workflow";
    }
  }
  if (location.pathname.startsWith("/apps/nanostore")) {
    const nanostoreSections = {
      workflow: "workflow",
      cadastros: "cadastros",
      lancamentos: "compras",
      compras: "compras",
      financeiro: "financeiro",
      relatorios: "relatorios",
      config: "config",
      configuracao: "config",
    };
    section = nanostoreSections[hash] || "dashboards";
  }
  if (location.pathname.startsWith("/apps/gpsmusical")) {
    const gpsSections = {
      editor: "cadastros",
      backup: "import_export",
      config: "config",
      docs: "config",
    };
    section = gpsSections[hash] || "dashboards";
  }
  if (location.pathname.startsWith("/apps/bpa")) section = "cadastros";
  if (location.pathname.startsWith("/apps/tatoo")) {
    const tatooSections = {
      clientes: "cadastros",
      sessoes: "cadastros",
      consentimentos: "cadastros",
      financeiro: "financeiro",
      dados: "import_export",
    };
    section = tatooSections[hash] || "dashboards";
  }
  if (location.pathname.startsWith("/apps/riob")) {
    const riobSections = {
      dashboard: "dashboards",
      estoque: "compras",
      vendas: "relatorios",
      agentia: "dashboards",
      comunicacao: "workflow",
      "config:status": "config",
      "config:cameras": "config",
      "config:sip": "config",
      "config:nfe": "config",
      "monitor:cameras": "dashboards",
      "monitor:esxi": "dashboards",
    };
    section = riobSections[hash] || section;
  }
  if (!section) return;
  document.querySelectorAll("[data-menu-section]").forEach((item) => {
    item.classList.toggle("active", item.dataset.menuSection === section);
  });
}

// Sincroniza tanto o seletor da pagina Config quanto o atalho de tema do topo.
function bindTheme() {
  const button = qs("[data-save-theme]");
  if (button) {
    button.addEventListener("click", async () => {
      const tema = qs("#temaSelect")?.value || "rio_branco";
      setMessage("#themeMsg", "Salvando...", "");
      try {
        const data = await saveTheme(tema);
        setMessage("#themeMsg", "Tema salvo.", "ok");
        setActiveThemeOptions(data.tema);
      } catch (err) {
        setMessage("#themeMsg", err.message, "error");
      }
    });
  }

  document.querySelectorAll("[data-theme-toggle]").forEach((toggle) => {
    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      const wrap = toggle.closest("[data-theme-switcher]");
      document.querySelectorAll("[data-theme-switcher].open").forEach((item) => {
        if (item !== wrap) item.classList.remove("open");
      });
      wrap?.classList.toggle("open");
    });
  });

  document.querySelectorAll("[data-theme-option]").forEach((option) => {
    option.addEventListener("click", async (event) => {
      event.stopPropagation();
      if (option.disabled) return;
      const tema = option.dataset.themeOption || "rio_branco";
      try {
        const data = await saveTheme(tema);
        setActiveThemeOptions(data.tema);
        option.closest("[data-theme-switcher]")?.classList.remove("open");
      } catch (err) {
        alert(err.message);
      }
    });
  });

  document.addEventListener("click", () => {
    document.querySelectorAll("[data-theme-switcher].open").forEach((item) => {
      item.classList.remove("open");
    });
  });
}

// Salva o tema no backend e troca somente a classe theme-* do body.
async function saveTheme(tema) {
  const data = await postJson("/api/config/theme", { tema });
  document.body.classList.forEach((className) => {
    if (className.startsWith("theme-")) document.body.classList.remove(className);
  });
  document.body.classList.add(`theme-${data.tema}`);
  const select = qs("#temaSelect");
  if (select) select.value = data.tema;
  return data;
}

function setActiveThemeOptions(tema) {
  document.querySelectorAll("[data-theme-option]").forEach((option) => {
    option.classList.toggle("active", option.dataset.themeOption === tema);
  });
}

function bindPortalBackup() {
  const exportButton = qs("[data-backup-export]");
  const importButton = qs("[data-backup-import]");
  const fileInput = qs("#portalBackupFile");

  exportButton?.addEventListener("click", async () => {
    setMessage("#backupMsg", "Gerando backup...", "");
    try {
      const resp = await fetch("/api/backup/export", { headers: { Accept: "application/json" } });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.erro || "Falha ao exportar backup");
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filenameFromDisposition(
        resp.headers.get("Content-Disposition"),
        `nanotechsoft-backup_${new Date().toISOString().slice(0, 10)}.json`
      );
      link.click();
      URL.revokeObjectURL(url);
      setMessage("#backupMsg", "Backup exportado.", "ok");
    } catch (err) {
      setMessage("#backupMsg", err.message, "error");
    }
  });

  importButton?.addEventListener("click", async () => {
    const file = fileInput?.files?.[0];
    if (!file) {
      setMessage("#backupMsg", "Selecione um arquivo JSON.", "error");
      return;
    }
    if (!confirm("Importar este backup vai substituir os dados atuais. Continuar?")) return;

    setMessage("#backupMsg", "Importando backup...", "");
    try {
      const form = new FormData();
      form.append("backup", file);
      const resp = await fetch("/api/backup/import", { method: "POST", body: form });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.erro || "Falha ao importar backup");
      const total = Object.values(data.restored || {}).reduce((sum, value) => sum + Number(value || 0), 0);
      setMessage("#backupMsg", `Backup importado. ${total} registros restaurados.`, "ok");
    } catch (err) {
      setMessage("#backupMsg", err.message, "error");
    }
  });
}

function slugify(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function bindClientAdmin() {
  const root = qs("[data-client-admin]");
  if (!root) return;

  const seed = qs("#clientContractsSeed");
  const list = qs("[data-client-list]");
  const form = qs("[data-client-form]");
  const modulePicker = qs("[data-module-picker]");
  const deleteButton = qs("[data-client-delete]");
  const newButton = qs("[data-client-new]");
  let state = { clients: [], catalog: [], activeClientId: "" };
  let selectedId = "";
  let draft = null;

  function loadSeed() {
    try {
      state = JSON.parse(seed?.textContent || "{}");
    } catch {
      state = { clients: [], catalog: [], activeClientId: "" };
    }
    selectedId = state.activeClientId || state.clients?.[0]?.id || "";
  }

  function clientsForRender() {
    return draft ? [...(state.clients || []), draft] : (state.clients || []);
  }

  function renderList() {
    if (!list) return;
    list.innerHTML = clientsForRender().map((client) => {
      const active = client.id === selectedId;
      const modules = client.allModules ? "Todos apps" : `${client.modules?.length || 0} modulo(s)`;
      const deploy = state.activeClientId === client.id && state.selectedByEnv ? " / Deploy" : "";
      return `
        <button type="button" class="${active ? "active" : ""}" data-client-id="${client.id}">
          <span>${client.status || "ativo"}${deploy}</span>
          <strong>${client.nome}</strong>
          <small>${modules}</small>
        </button>
      `;
    }).join("");
  }

  function renderModules(client) {
    if (!modulePicker) return;
    const selected = new Set((client.modules || []).map((item) => item.slug));
    modulePicker.innerHTML = (state.catalog || []).map((module) => {
      const checked = client.allModules || selected.has(module.slug);
      return `
        <label class="module-choice">
          <input type="checkbox" value="${module.slug}" data-client-module ${checked ? "checked" : ""}>
          <span>
            <strong>${module.nome}</strong>
            <small>${module.slug}</small>
          </span>
        </label>
      `;
    }).join("");
  }

  function selectedClient() {
    return clientsForRender().find((client) => client.id === selectedId) || clientsForRender()[0] || null;
  }

  function fillForm(client) {
    if (!form || !client) return;
    form.elements.nome.value = client.nome || "";
    form.elements.id.value = client.id || "";
    form.elements.status.value = client.status || "ativo";
    form.elements.databaseKey.value = client.databaseKey || "";
    form.elements.observacao.value = client.observacao || "";
    form.elements.allModules.checked = Boolean(client.allModules);
    deleteButton.disabled = Boolean(client.isDraft);
    renderModules(client);
  }

  function render() {
    renderList();
    fillForm(selectedClient());
  }

  function payloadFromForm() {
    const data = new FormData(form);
    const catalog = new Map((state.catalog || []).map((module) => [module.slug, module]));
    const allModules = form.elements.allModules.checked;
    const modules = [...form.querySelectorAll("[data-client-module]:checked")]
      .map((input) => catalog.get(input.value))
      .filter(Boolean)
      .map((module) => ({
        slug: module.slug,
        nome: module.nome,
        descricao: module.descricao || "",
        href: module.href || "",
        status: module.status === "importar" ? "importar" : "contratado",
      }));
    return {
      nome: String(data.get("nome") || "").trim(),
      id: slugify(data.get("id") || data.get("nome")),
      status: String(data.get("status") || "ativo"),
      databaseKey: String(data.get("databaseKey") || "").trim(),
      observacao: String(data.get("observacao") || "").trim(),
      allModules,
      modules: allModules ? [] : modules,
    };
  }

  async function requestClient(url, options) {
    const resp = await fetch(url, {
      cache: "no-store",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      ...options,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.erro || "Falha ao salvar cliente");
    state = data;
    draft = null;
    return data;
  }

  list?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-client-id]");
    if (!button) return;
    selectedId = button.dataset.clientId;
    setMessage("#clientAdminMsg", "", "");
    render();
  });

  newButton?.addEventListener("click", () => {
    draft = {
      id: "novo-cliente",
      nome: "Novo cliente",
      status: "ativo",
      databaseKey: "",
      observacao: "",
      allModules: false,
      modules: [],
      isDraft: true,
    };
    selectedId = draft.id;
    setMessage("#clientAdminMsg", "", "");
    render();
  });

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = payloadFromForm();
    if (!payload.nome || !payload.id) {
      setMessage("#clientAdminMsg", "Informe nome e ID.", "error");
      return;
    }
    const isDraft = draft && selectedId === draft.id;
    const url = isDraft ? "/api/clientes-modulos/clientes" : `/api/clientes-modulos/clientes/${encodeURIComponent(selectedId)}`;
    try {
      await requestClient(url, { method: isDraft ? "POST" : "PUT", body: JSON.stringify(payload) });
      selectedId = payload.id;
      setMessage("#clientAdminMsg", "Cliente salvo no JSON.", "ok");
      render();
    } catch (err) {
      setMessage("#clientAdminMsg", err.message, "error");
    }
  });

  deleteButton?.addEventListener("click", async () => {
    if (draft && selectedId === draft.id) {
      draft = null;
      selectedId = state.clients?.[0]?.id || "";
      render();
      return;
    }
    const client = selectedClient();
    if (!client || !confirm(`Excluir ${client.nome}?`)) return;
    try {
      await requestClient(`/api/clientes-modulos/clientes/${encodeURIComponent(client.id)}`, { method: "DELETE" });
      selectedId = state.activeClientId || state.clients?.[0]?.id || "";
      setMessage("#clientAdminMsg", "Cliente excluido do JSON.", "ok");
      render();
    } catch (err) {
      setMessage("#clientAdminMsg", err.message, "error");
    }
  });

  loadSeed();
  render();
}

function bindKanban() {
  const board = qs("[data-kanban-board]");
  if (!board) return;
  const seedEl = qs("#kanbanSeed");
  const storageKey = `notechsoft:kanban:${board.dataset.boardKey || "default"}`;
  const statuses = ["todo", "today", "waiting"];
  const labels = { todo: "A fazer", today: "Em andamento", waiting: "Aguardando" };
  const modal = qs("[data-kanban-modal]");
  const form = qs("[data-kanban-form]");
  const deleteBtn = qs("[data-kanban-delete]");

  function seedCards() {
    try {
      return JSON.parse(seedEl?.textContent || "[]").map((card, index) => ({
        id: card.id || `seed-${index + 1}`,
        nome: card.nome || "Card",
        tipo: card.tipo || card.app || "Workflow",
        url: card.url || "",
        descricao: card.descricao || "Funcao importada do app.",
        status: card.status || "todo",
        created: card.created || Date.now() + index,
      }));
    } catch {
      return [];
    }
  }

  function loadCards() {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "null");
      if (Array.isArray(saved)) return saved;
    } catch {}
    const cards = seedCards();
    localStorage.setItem(storageKey, JSON.stringify(cards));
    return cards;
  }

  let cards = loadCards();
  let draggingId = "";

  function saveCards() {
    localStorage.setItem(storageKey, JSON.stringify(cards));
  }

  function cardTemplate(card) {
    return `
      <article class="kanban-card" draggable="true" data-kanban-card="${card.id}">
        <span>${escapeText(card.tipo || "Workflow")} · ${escapeText(labels[card.status] || card.status)}</span>
        <strong>${escapeText(card.nome)}</strong>
        <small>${escapeText(card.descricao || "Clique para ver os dados do card.")}</small>
      </article>
    `;
  }

  function render() {
    statuses.forEach((status) => {
      const zone = document.querySelector(`[data-kanban-dropzone="${status}"]`);
      if (!zone) return;
      const items = cards
        .filter((card) => card.status === status)
        .sort((a, b) => Number(a.created || 0) - Number(b.created || 0));
      zone.innerHTML = items.length
        ? items.map(cardTemplate).join("")
        : `<div class="kanban-placeholder">Sem cards em ${labels[status].toLowerCase()}.</div>`;
    });
  }

  function escapeText(value) {
    return String(value || "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    }[char]));
  }

  function openModal(card) {
    const current = card || {
      id: `card-${Date.now()}`,
      nome: "",
      tipo: board.dataset.boardKey || "Workflow",
      status: "todo",
      url: "",
      descricao: "",
      created: Date.now(),
    };
    form.elements.id.value = current.id;
    form.elements.nome.value = current.nome || "";
    form.elements.tipo.value = current.tipo || "";
    form.elements.status.value = current.status || "todo";
    form.elements.url.value = current.url || "";
    form.elements.descricao.value = current.descricao || "";
    deleteBtn.hidden = !cards.some((item) => item.id === current.id);
    modal.classList.remove("hidden");
  }

  function closeModal() {
    modal.classList.add("hidden");
  }

  board.addEventListener("dragstart", (event) => {
    const card = event.target.closest("[data-kanban-card]");
    if (!card) return;
    draggingId = card.dataset.kanbanCard;
    card.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", draggingId);
  });

  board.addEventListener("dragend", (event) => {
    event.target.closest("[data-kanban-card]")?.classList.remove("dragging");
    document.querySelectorAll(".kanban-column.drag-over").forEach((column) => {
      column.classList.remove("drag-over");
    });
  });

  board.addEventListener("dragover", (event) => {
    const zone = event.target.closest("[data-kanban-dropzone]");
    if (!zone) return;
    event.preventDefault();
    zone.closest(".kanban-column")?.classList.add("drag-over");
  });

  board.addEventListener("dragleave", (event) => {
    const column = event.target.closest(".kanban-column");
    if (column && !column.contains(event.relatedTarget)) column.classList.remove("drag-over");
  });

  board.addEventListener("drop", (event) => {
    const zone = event.target.closest("[data-kanban-dropzone]");
    if (!zone) return;
    event.preventDefault();
    const id = event.dataTransfer.getData("text/plain") || draggingId;
    const card = cards.find((item) => item.id === id);
    if (card) {
      card.status = zone.dataset.kanbanDropzone;
      saveCards();
      render();
    }
    zone.closest(".kanban-column")?.classList.remove("drag-over");
  });

  board.addEventListener("click", (event) => {
    const cardEl = event.target.closest("[data-kanban-card]");
    if (!cardEl) return;
    const card = cards.find((item) => item.id === cardEl.dataset.kanbanCard);
    if (card) openModal(card);
  });

  qs("[data-kanban-new]")?.addEventListener("click", () => openModal(null));
  qs("[data-kanban-close]")?.addEventListener("click", closeModal);
  modal?.addEventListener("click", (event) => {
    if (event.target === modal) closeModal();
  });

  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    const existing = cards.find((item) => item.id === data.id);
    if (existing) {
      Object.assign(existing, data);
    } else {
      cards.push({ ...data, created: Date.now() });
    }
    saveCards();
    render();
    closeModal();
  });

  deleteBtn?.addEventListener("click", () => {
    const id = form.elements.id.value;
    cards = cards.filter((item) => item.id !== id);
    saveCards();
    render();
    closeModal();
  });

  render();
}

bindLogin();
bindLogout();
bindMenu();
bindTheme();
bindPortalBackup();
bindClientAdmin();
bindKanban();
syncMenuSection();
window.addEventListener("hashchange", syncMenuSection);
