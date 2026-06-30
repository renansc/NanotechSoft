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
bindKanban();
syncMenuSection();
window.addEventListener("hashchange", syncMenuSection);
