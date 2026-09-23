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

function bindConfigViews() {
  const panels = [...document.querySelectorAll('[data-config-view]')];
  if (!panels.length) return;
  function select() {
    const requested = location.hash.slice(1) || 'minha-conta';
    const view = panels.some(panel => panel.dataset.configView === requested) ? requested : 'minha-conta';
    panels.forEach(panel => { panel.hidden = panel.dataset.configView !== view; });
  }
  window.addEventListener('hashchange', select);
  select();
}

function bindLogo() {
  const form = qs("[data-logo-form]");
  if (!form) return;
  const input = form.elements.logo;
  const preview = qs("[data-logo-preview]");
  const remove = qs("[data-logo-remove]");
  let previewUrl = "";
  input.addEventListener("change", () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = "";
    const file = input.files[0];
    if (file && file.size > 2 * 1024 * 1024) {
      input.value = "";
      setMessage("#logoMsg", "A imagem deve ter no maximo 2 MB.", "error");
    } else {
      setMessage("#logoMsg", "", "");
      if (file) previewUrl = URL.createObjectURL(file);
    }
    preview.src = previewUrl || qs("[data-logo-image]").getAttribute("src") || "";
    preview.hidden = !preview.getAttribute("src");
  });
  async function save(method) {
    const controls = [...form.querySelectorAll("input, button")];
    controls.forEach(control => { control.disabled = true; });
    setMessage("#logoMsg", "Salvando...", "");
    try {
      const body = new FormData();
      if (method === "POST") {
        if (input.files[0]) body.append("logo", input.files[0]);
        body.append("logo_url", form.elements.logo_url.value.trim());
      }
      const response = await fetch("/api/config/logo", { method, ...(method === "POST" ? { body } : {}) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.erro || "Nao foi possivel salvar a logo.");
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = "";
      preview.src = data.logo_data;
      preview.hidden = !data.logo_data;
      qs("[data-logo-image]").src = data.logo_data;
      qs("[data-logo-image]").hidden = !data.logo_data;
      qs("[data-logo-fallback]").hidden = !!data.logo_data;
      const link = qs("[data-topbar-logo]");
      link.href = data.logo_data && data.logo_url ? data.logo_url : link.dataset.defaultUrl;
      form.elements.logo_url.value = data.logo_url || "";
      input.value = "";
      window.dispatchEvent(new Event("resize"));
      setMessage("#logoMsg", method === "DELETE" ? "Logo removida." : "Logo salva.", "success");
    } catch (err) {
      setMessage("#logoMsg", err.message, "error");
    } finally {
      controls.forEach(control => { control.disabled = false; });
      remove.disabled = !qs("[data-logo-image]").getAttribute("src");
    }
  }
  form.addEventListener("submit", event => { event.preventDefault(); save("POST"); });
  remove.addEventListener("click", () => save("DELETE"));
}

function bindMenu() {
  const menu = qs("[data-menu]");
  const overlay = qs("[data-menu-overlay]");
  const toggle = qs("[data-menu-toggle]");
  const topbar = toggle?.closest(".topo");
  function open(next) {
    if (!menu || !overlay) return;
    menu.classList.toggle("show", next);
    overlay.classList.toggle("show", next);
    document.body.classList.toggle("menu-open", next);
    toggle?.setAttribute("aria-expanded", String(next));
    toggle?.setAttribute("aria-label", next ? "Fechar menu" : "Abrir menu");
  }
  toggle?.addEventListener("click", () => open(!menu.classList.contains("show")));
  overlay?.addEventListener("click", () => open(false));
  menu?.addEventListener("click", (event) => {
    if (event.target.closest("a, [data-logout]")) open(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && menu?.classList.contains("show")) {
      open(false);
      toggle?.focus();
    }
  });
  if (!topbar || !menu) return;
  function fitMenu() {
    topbar.classList.remove("compact-menu");
    const compact = window.innerWidth <= 760 || menu.scrollWidth > menu.clientWidth;
    topbar.classList.toggle("compact-menu", compact);
    if (!compact) open(false);
  }
  new ResizeObserver(fitMenu).observe(topbar);
  window.addEventListener("resize", fitMenu);
  document.fonts?.ready.then(fitMenu);
  fitMenu();
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
    if (location.pathname.includes("/documentacao")) {
      section = document.querySelector('[data-menu-section="docs"] a[href="/apps/automacao/documentacao"]') ? "docs" : "module-automacao";
    } else if (location.pathname.includes("/motores") || location.pathname.includes("/motor") || location.pathname.includes("/sensores/drivers")) {
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
  if (location.pathname.startsWith("/apps/riob")) {
    const riobSections = {
      dashboard: "dashboards",
      "dashboard:frota": "dashboards",
      "dashboard:estoque": "dashboards",
      "dashboard:vendas_diario": "dashboards",
      "dashboard:bonificacoes": "dashboards",
      "dashboard:variacao_preco": "dashboards",
      "dashboard:grupos_embalagem": "dashboards",
      "dashboard:comissoes": "dashboards",
      fretes: "workflow",
      "vendas:diario": "relatorios",
      "vendas:kanban": "workflow",
      "vendas:importar": "import_export",
      devolucoes: "workflow",
      comissao: "workflow",
      "comissao:relatorios": "relatorios",
      gestaofrota: "workflow",
      "gestaofrota:registrar": "workflow",
      "gestaofrota:lista": "workflow",
      "gestaofrota:relatorios": "relatorios",
      "gestaofrota:cargas": "cadastros",
      "gestaofrota:escala": "cadastros",
      cadastros: "cadastros",
      "cadastros:colaboradores": "cadastros",
      "cadastros:veiculos": "cadastros",
      "cadastros:comissao": "cadastros",
      estoque: "estoque",
      "estoque:posicao": "estoque",
      "estoque:movimentar": "estoque",
      "estoque:cadastrar": "estoque",
      "estoque:rastreio": "estoque",
      "estoque:acerto": "estoque",
      "estoque:importar_xml": "compras",
      vendas: "vendas",
      "vendas:orcamento": "vendas",
      "vendas:relatorio": "vendas",
      agentia: "dashboards",
      comunicacao: "workflow",
      "config:status": "config",
      "config:logs": "config",
      "config:cameras": "config",
      "config:sip": "config",
      "config:nfe": "config",
      "config:vendas": "config",
      "monitor:cameras": "workflow",
      "monitor:esxi": "dashboards",
      "monitor:automacao": "automacao",
      "monitor:gestor_emails": "import_export",
    };
    section = riobSections[hash] || section;
  }
  // O destino efetivo identifica o modulo mesmo nas antigas rotas por tarefa.
  const current = new URL(window.location.href);
  const matchingLink = [...document.querySelectorAll("[data-menu] .submenu-item[href]")].find((link) => {
    const target = new URL(link.href, current);
    return target.pathname === current.pathname && target.search === current.search && target.hash === current.hash;
  });
  if (matchingLink) section = matchingLink.closest("[data-menu-section]")?.dataset.menuSection || section;
  if (!section && current.pathname.startsWith("/apps/")) section = "module-" + current.pathname.split("/")[2];
  if (!section) return;
  document.querySelectorAll("[data-menu-section]").forEach((item) => {
    item.classList.toggle("active", item.dataset.menuSection === section);
  });
}

// A escolha de tema fica somente na pagina Config.
function bindTheme() {
  const button = qs("[data-save-theme]");
  if (button) {
    button.addEventListener("click", async () => {
      const tema = qs("#temaSelect")?.value || "rio_branco";
      setMessage("#themeMsg", "Salvando...", "");
      try {
        await saveTheme(tema);
        setMessage("#themeMsg", "Tema salvo.", "ok");
      } catch (err) {
        setMessage("#themeMsg", err.message, "error");
      }
    });
  }

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

function bindUserAdmin() {
  const root = qs("[data-user-admin]");
  if (!root) return;

  const form = root.querySelector("[data-user-form]");
  const userSelect = root.querySelector("[data-user-select]");
  const profileSelect = root.querySelector("[data-user-store-profile]");
  const deleteButton = root.querySelector("[data-user-delete]");
  let state = { usuarios: [], nanostore_perfis: [], catalogo_acessos: [] };
  let creating = false;
  const permissionsList = root.querySelector("[data-user-permissions-list]");
  function renderPermissions(user) {
    root.querySelector('[data-user-menu-search]').value = '';
    permissionsList.replaceChildren();
    for (const module of state.catalogo_acessos || []) {
      const section = document.createElement("fieldset");
      const legend = document.createElement("legend");
      legend.textContent = module.nome;
      section.append(legend);
      const grants = user.permissoes?.[module.app_key] || [];
      const choices = user.permissoes_menu?.[module.app_key] || {};
      for (const item of module.menus || []) {
        const label = document.createElement('label');
        label.className = 'user-menu-choice';
        label.dataset.menuSearch = `${module.nome} ${item.nome} ${item.grupos.join(' ')}`.toLocaleLowerCase();
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.dataset.accessApp = module.app_key;
        input.dataset.accessMenu = item.key;
        const inherited = item.authenticated || grants.includes('*') || grants.includes(item.recurso);
        input.checked = user.perfil === 'admin' || (!item.admin_only && (choices[item.key] ?? inherited));
        input.disabled = user.perfil === 'admin' || item.admin_only;
        const text = document.createElement('span');
        text.textContent = item.nome;
        const path = document.createElement('small');
        path.textContent = `${item.grupos.join(' / ')} > ${module.nome}${item.admin_only ? ' — exclusivo de administrador' : ''}`;
        text.append(path);
        label.append(input, text);
        section.append(label);
      }
      const legacy = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = 'Permissoes gerais e acoes internas existentes';
      legacy.append(summary);
      for (const resource of module.recursos) {
        const label = document.createElement("label");
        label.className = "inline-check";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.dataset.accessApp = module.app_key;
        input.dataset.accessResource = resource.key;
        input.checked = (user.permissoes?.[module.app_key] || []).includes(resource.key);
        label.append(input, document.createTextNode(resource.nome));
        legacy.append(label);
      }
      section.append(legacy);
      permissionsList.append(section);
    }
  }
  root.querySelector('[data-user-menu-search]')?.addEventListener('input', event => {
    const query = event.target.value.toLocaleLowerCase().trim();
    for (const label of permissionsList.querySelectorAll('[data-menu-search]')) label.hidden = !label.dataset.menuSearch.includes(query);
    for (const section of permissionsList.children) {
      section.hidden = Boolean(query) && !section.querySelector('[data-menu-search]:not([hidden])');
    }
  });

  function selectedUser() {
    return creating ? { ativo: true, perfil: "usuario", permissoes: {} } : state.usuarios.find((item) => String(item.id) === userSelect.value) || state.usuarios[0] || null;
  }

  function fillForm() {
    const user = selectedUser();
    if (!user || !form) return;
    form.elements.nome.value = user.nome || "";
    form.elements.login.value = user.login || "";
    form.elements.perfil.value = user.perfil || "usuario";
    form.elements.nanostore_perfil.value = user.nanostore_perfil || "";
    form.elements.senha.value = "";
    form.elements.ativo.checked = Boolean(user.ativo);
    deleteButton.disabled = creating;
    renderPermissions(user);
  }

  function render() {
    const selectedId = userSelect.value || root.dataset.currentUser;
    userSelect.replaceChildren(...state.usuarios.map((user) => new Option(
      `${user.nome} (${user.login})`, String(user.id), false, String(user.id) === selectedId
    )));
    profileSelect.replaceChildren(
      new Option("Sem acesso", ""),
      ...state.nanostore_perfis.map((profile) => new Option(profile.name, profile.key))
    );
    if (!userSelect.value && state.usuarios[0]) userSelect.value = String(state.usuarios[0].id);
    fillForm();
  }

  async function load() {
    const resp = await fetch("/api/usuarios", { cache: "no-store", headers: { Accept: "application/json" } });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.erro || "Falha ao carregar usuarios");
    state = data;
    render();
  }

  root.querySelector("[data-user-new]")?.addEventListener("click", () => { creating = true; fillForm(); });
  qs("[data-edit-current-user]")?.addEventListener("click", (event) => {
    creating = false;
    userSelect.value = event.currentTarget.dataset.editCurrentUser;
    fillForm();
  });
  userSelect?.addEventListener("change", () => {
    creating = false;
    setMessage("#userAdminMsg", "", "");
    fillForm();
  });
  form.elements.perfil.addEventListener('change', () => {
    const user = selectedUser();
    const choices = structuredClone(user.permissoes_menu || {});
    for (const input of permissionsList.querySelectorAll('input[data-access-menu]:not(:disabled)')) {
      (choices[input.dataset.accessApp] ||= {})[input.dataset.accessMenu] = input.checked;
    }
    renderPermissions({ ...user, perfil: form.elements.perfil.value, permissoes_menu: choices });
  });

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const user = selectedUser();
    if (!user) return;
    const payload = {
      nome: form.elements.nome.value.trim(),
      login: form.elements.login.value.trim(),
      perfil: form.elements.perfil.value,
      nanostore_perfil: form.elements.nanostore_perfil.value,
      senha: form.elements.senha.value,
      ativo: form.elements.ativo.checked,
    };
    payload.permissoes = {};
    for (const input of permissionsList.querySelectorAll("input[data-access-resource]:checked")) {
      (payload.permissoes[input.dataset.accessApp] ||= []).push(input.dataset.accessResource);
    }
    payload.permissoes_menu = {};
    for (const input of permissionsList.querySelectorAll('input[data-access-menu]:not(:disabled)')) {
      (payload.permissoes_menu[input.dataset.accessApp] ||= {})[input.dataset.accessMenu] = input.checked;
    }
    setMessage("#userAdminMsg", "Salvando...", "");
    try {
      const resp = await fetch(creating ? "/api/usuarios" : `/api/usuarios/${user.id}`, {
        method: creating ? "POST" : "PUT",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.erro || "Falha ao salvar usuario");
      state = data;
      creating = false;
      render();
      setMessage("#userAdminMsg", "Usuario salvo.", "ok");
    } catch (err) {
      setMessage("#userAdminMsg", err.message, "error");
    }
  });

  deleteButton?.addEventListener("click", async () => {
    const user = selectedUser();
    if (!user) return;
    if (!window.confirm(`Excluir permanentemente o usuario ${user.nome} (${user.login})?`)) return;
    setMessage("#userAdminMsg", "Excluindo...", "");
    try {
      const resp = await fetch(`/api/usuarios/${user.id}`, {
        method: "DELETE",
        headers: { Accept: "application/json" },
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.erro || "Falha ao excluir usuario");
      state = data;
      render();
      setMessage("#userAdminMsg", "Usuario excluido.", "ok");
    } catch (err) {
      setMessage("#userAdminMsg", err.message, "error");
    }
  });

  load().catch((err) => setMessage("#userAdminMsg", err.message, "error"));
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
        hrefEnv: module.hrefEnv || "",
        status: ["importar", "externo", "cache-leitura"].includes(module.status)
          ? module.status
          : "contratado",
      }));
    const externalModules = (selectedClient()?.modules || [])
      .filter((module) => module.status === "externo");
    return {
      nome: String(data.get("nome") || "").trim(),
      id: slugify(data.get("id") || data.get("nome")),
      status: String(data.get("status") || "ativo"),
      databaseKey: String(data.get("databaseKey") || "").trim(),
      observacao: String(data.get("observacao") || "").trim(),
      allModules,
      modules: allModules ? externalModules : modules,
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
bindConfigViews();
bindLogo();
bindMenu();
bindTheme();
bindPortalBackup();
bindUserAdmin();
bindClientAdmin();
bindKanban();
syncMenuSection();
window.addEventListener("hashchange", syncMenuSection);
window.addEventListener("nanotech:navigation", syncMenuSection);
