const workflowStages = [
  { key: "draft", label: "Cadastro" },
  { key: "scheduled", label: "Na worklist" },
  { key: "arrived", label: "Chegou" },
  { key: "started", label: "Em execucao" },
  { key: "executed", label: "Executado" },
  { key: "reporting", label: "Laudando" },
  { key: "finalized", label: "Finalizado" },
  { key: "cancelled", label: "Cancelado" },
  { key: "removed", label: "Removido" },
];

const bootstrap = window.__APP_BOOTSTRAP__ || {};

const reportCatalog = [
  { key: "financeiro", label: "Resumo financeiro", description: "Pagos, em aberto e formas de pagamento." },
  { key: "convenio", label: "Por convênio", description: "Quantidade e valor agrupados por convênio." },
  { key: "paciente", label: "Por paciente", description: "Quantidade e valor agrupados por paciente." },
  { key: "comissao_tecnico", label: "Comissão do técnico", description: "Valor fixo por exame e total a pagar ao técnico." },
];

const state = {
  overview: null,
  kanban: { stages: [] },
  patients: [],
  procedures: [],
  exams: [],
  examHistory: [],
  reportingWorkspace: null,
  selectedWorkspaceExamId: "",
  selectedViewerAsset: "",
  selectedViewerType: "image",
  selectedViewerLabel: "",
  budgetItems: [],
  invoices: [],
  finance: null,
  worklist: { items: [], local_exams: [] },
  storage: null,
  backups: { database: [], images: [], backup_root: "" },
  integrationConfig: null,
  integrationStatus: null,
  pricingConfig: null,
  pricingOverrides: { items: [] },
  panel: { config: {}, items: [], history: [], summary: {} },
  reports: { type: "financeiro", preview: null, loading: false },
  departments: [],
  chatMessages: [],
  examDialog: { open: false, activeTab: "launch", examId: "" },
  adminUnlocked: Boolean(bootstrap.adminUnlocked || bootstrap.userRole === "admin"),
  userRole: String(bootstrap.userRole || "technician"),
  currentOperatorId: String(bootstrap.departmentId || ""),
  currentDepartmentName: String(bootstrap.departmentName || ""),
  currentContactId: "",
  activeSection: "kanban",
  examPricingTable: "PARTICULAR",
  examWorkbenchTarget: "form",
  examLookupFocus: false,
};

const ui = {
  chatPoll: null,
  panelPoll: null,
  workflowPoll: null,
  workflowSyncInFlight: false,
  lastPanelAlertId: null,
  lastPanelSpokenId: null,
  sidebarCollapsed: false,
  navGroups: { cadastros: false },
  configTab: "integrations",
  pricingDrafts: [],
  pricingRemovedCodes: [],
};

async function api(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (!isFormData && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, {
    headers,
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "Erro na requisicao.");
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function showFlash(message, error = false) {
  const flash = document.getElementById("flash");
  flash.textContent = message;
  flash.classList.remove("hidden", "error");
  if (error) flash.classList.add("error");
  window.clearTimeout(showFlash.timer);
  showFlash.timer = window.setTimeout(() => flash.classList.add("hidden"), 3600);
}

function setSidebarCollapsed(collapsed) {
  ui.sidebarCollapsed = Boolean(collapsed);
  document.body.classList.toggle("sidebar-collapsed", ui.sidebarCollapsed);
  const button = document.querySelector("[data-sidebar-toggle]");
  if (button) {
    button.setAttribute("aria-label", ui.sidebarCollapsed ? "Expandir menu" : "Minimizar menu");
    button.title = ui.sidebarCollapsed ? "Expandir menu" : "Minimizar menu";
  }
  try {
    window.localStorage.setItem("raiox.sidebarCollapsed", ui.sidebarCollapsed ? "1" : "0");
  } catch (error) {
    console.warn("Nao foi possivel salvar o estado do menu lateral.", error);
  }
}

function toggleSidebarCollapsed() {
  setSidebarCollapsed(!ui.sidebarCollapsed);
}

function setNavGroupCollapsed(group, collapsed) {
  ui.navGroups = { ...ui.navGroups, [group]: Boolean(collapsed) };
  document.body.classList.toggle(`nav-group-${group}-collapsed`, Boolean(collapsed));
  const toggle = document.querySelector(`[data-nav-toggle="${group}"]`);
  if (toggle) {
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
  }
  try {
    window.localStorage.setItem(`raiox.nav.${group}`, collapsed ? "1" : "0");
  } catch (error) {
    console.warn("Nao foi possivel salvar o estado do menu.", error);
  }
}

function toggleNavGroup(group) {
  setNavGroupCollapsed(group, !ui.navGroups[group]);
}

function setExamPricingTable(mode) {
  state.examPricingTable = mode === "CONVENIOS" ? "CONVENIOS" : "PARTICULAR";
  const select = document.getElementById("examListConvenioFilter");
  if (select && select.value !== state.examPricingTable) {
    select.value = state.examPricingTable;
  }
}

function setExamWorkbenchTarget(target) {
  state.examWorkbenchTarget = target === "values" ? "values" : "form";
}

function setConfigTab(tab) {
  const nextTab = ["integrations", "pricing", "status", "deploy"].includes(tab) ? tab : "integrations";
  ui.configTab = nextTab;
  document.querySelectorAll("[data-config-tab]").forEach((button) => {
    const isActive = button.dataset.configTab === nextTab;
    button.classList.toggle("primary", isActive);
    button.classList.toggle("ghost", !isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
  document.querySelectorAll("[data-config-panel]").forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.configPanel !== nextTab);
  });
  try {
    window.localStorage.setItem("raiox.config.tab", nextTab);
  } catch (error) {
    console.warn("Nao foi possivel salvar a aba de configuracao.", error);
  }
}

function makePricingDraft() {
  const suffix = Math.random().toString(16).slice(2, 8);
  return {
    draftId: `draft-${Date.now()}-${suffix}`,
    code: "",
    name: "",
    prices: { 1: 0, 2: 0, 3: 0 },
    commission_amount: 6,
    draft: true,
  };
}

function makeBudgetItem() {
  const suffix = Math.random().toString(16).slice(2, 8);
  return {
    draftId: `budget-${Date.now()}-${suffix}`,
    procedure_id: "",
    incidences_count: "1",
    price: 0,
    scheduled_at: "",
    priority: "ROUTINE",
    notes: "",
  };
}

function removePricingConvenio(code) {
  const normalized = String(code || "").trim().toUpperCase();
  if (!normalized || normalized === "PARTICULAR") return;
  ui.pricingRemovedCodes = [...new Set([...(ui.pricingRemovedCodes || []), normalized])];
  renderPricingConfig();
}

function restorePricingConvenio(code) {
  const normalized = String(code || "").trim().toUpperCase();
  ui.pricingRemovedCodes = (ui.pricingRemovedCodes || []).filter((item) => item !== normalized);
  renderPricingConfig();
}

function money(value) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(Number(value || 0));
}

function dateLabel(value) {
  if (!value) return "-";
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return new Date(`${text}T00:00:00`).toLocaleDateString("pt-BR");
  }
  return new Date(text).toLocaleDateString("pt-BR");
}

function dateTimeLabel(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString("pt-BR");
}

function formatCurrencyBRL(value) {
  let number = typeof value === "number" ? value : null;
  if (number === null) {
    const text = String(value ?? "").trim();
    const digits = text.replace(/\D/g, "");
    if (!text) {
      number = 0;
    } else if (digits && /R\$|\d+[,.]\d{1,2}/i.test(text)) {
      number = Number(digits) / 100;
    } else {
      number = Number(text.replace(/[^\d,-]/g, "").replace(/\./g, "").replace(",", "."));
    }
  }
  if (!Number.isFinite(number)) number = 0;
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(number);
}

function parseCurrencyBRL(value) {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  const text = String(value ?? "").trim();
  if (!text) return 0;
  const digits = text.replace(/\D/g, "");
  if (digits) {
    return Number(digits) / 100;
  }
  const normalized = Number(text.replace(/\./g, "").replace(",", "."));
  return Number.isFinite(normalized) ? normalized : 0;
}

function setCurrencyFieldValue(field, value) {
  if (!field) return;
  field.value = formatCurrencyBRL(value);
  field.dataset.currencyValue = String(parseCurrencyBRL(value));
}

function maskCurrencyField(field) {
  if (!field) return;
  setCurrencyFieldValue(field, field.value);
}

function formatFileSize(bytes) {
  const value = Number(bytes || 0);
  if (!value) return "0 B";
  if (value >= 1024 ** 3) return `${(value / (1024 ** 3)).toFixed(2)} GB`;
  if (value >= 1024 ** 2) return `${(value / (1024 ** 2)).toFixed(2)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(2)} KB`;
  return `${value} B`;
}

function toDateTimeInputValue(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (number) => String(number).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function htmlCard(label, value, detail = "") {
  return `<div class="card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></div>`;
}

function htmlMetric(label, value, meta = "") {
  return `<div class="metric-row"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span>${meta ? `<small>${escapeHtml(meta)}</small>` : ""}</div>`;
}

function htmlListRow(title, subtitle, meta = "") {
  return `<div class="list-row"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(subtitle)}</span><small>${escapeHtml(meta)}</small></div>`;
}

function financeStatusLabel(status) {
  const labels = {
    paid: "Pago",
    open: "Em aberto",
    pending: "Pendente",
    ready: "Pronto para faturar",
    cancelled: "Cancelado",
    canceled: "Cancelado",
  };
  const key = String(status || "").trim().toLowerCase();
  return labels[key] || status || "-";
}

function statusPill(label) {
  return `<span class="status-pill">${escapeHtml(financeStatusLabel(label))}</span>`;
}

function boolTone(ok) {
  return ok ? "ok" : "error";
}

function modeLabel(mode) {
  return String(mode || "local").toLowerCase() === "external" ? "Externo" : "Local";
}

function endpointLabel(item, database = false) {
  if (!item) return "-";
  const host = item.effective_host || item.host || item.database || item.name || "-";
  const port = item.effective_port || item.port || "-";
  const suffix = database ? `${host}:${port} / ${item.database || "-"}` : `${host}:${port}`;
  return suffix;
}

function statusLine(label, item, database = false) {
  const tone = boolTone(Boolean(item?.ok));
  const detail = database
    ? `Banco: ${endpointLabel(item, true)}`
    : `Endereco: ${endpointLabel(item, false)} | AE: ${item?.effective_ae_title || item?.ae_title || "-"}`;
  const latency = item?.latency_ms ? ` | Latencia: ${item.latency_ms} ms` : "";
  return `
    <div class="status-card ${tone}">
      <strong>${escapeHtml(label)}</strong>
      <span>${escapeHtml(detail)}</span>
      <small>${escapeHtml((item?.message || "-") + latency)}</small>
    </div>
  `;
}

function canSyncWorklist(exam) {
  return !["cancelled"].includes(String(exam?.workflow_stage || ""));
}

function worklistSyncLabel(exam) {
  return ["draft", "removed"].includes(String(exam?.workflow_stage || "")) ? "Publicar" : "Reespelhar";
}

function normalizeConvenioCode(value) {
  return String(value || "PARTICULAR").trim().toUpperCase() || "PARTICULAR";
}

function normalizePaymentMethod(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (["dinheiro", "pix", "cartao", "cheque"].includes(normalized)) return normalized;
  if (normalized === "cash") return "dinheiro";
  if (normalized === "card") return "cartao";
  return normalized || "dinheiro";
}

function paymentMethodLabel(value) {
  return ({
    dinheiro: "Dinheiro",
    pix: "Pix",
    cartao: "Cartao",
    cheque: "Cheque",
  }[normalizePaymentMethod(value)] || "Dinheiro");
}

function reportTypeConfig(type) {
  return reportCatalog.find((item) => item.key === String(type || "financeiro")) || reportCatalog[0];
}

function reportPeriodText(mode, value) {
  if (mode === "day") {
    return value ? dateLabel(value) : dateLabel(new Date().toISOString().slice(0, 10));
  }
  return value ? value.replace(/^(\d{4})-(\d{2})$/, "$2/$1") : new Date().toLocaleDateString("pt-BR", { month: "2-digit", year: "numeric" });
}

function reportMoney(value) {
  return money(value || 0);
}

function reportFilterSummary(filters) {
  const parts = [`Periodo: ${filters?.period_label || "-"}`];
  if (filters?.convenio_label) parts.push(`Convenio: ${filters.convenio_label}`);
  if (filters?.patient_label) parts.push(`Paciente: ${filters.patient_label}`);
  return parts.join(" | ");
}

function currentDateInputValue(reference = new Date()) {
  const local = new Date(reference.getTime() - reference.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function currentMonthInputValue(reference = new Date()) {
  return currentDateInputValue(reference).slice(0, 7);
}

function reportPeriodValueFromForm(form) {
  const mode = form?.querySelector('[name="period_mode"]')?.value || "month";
  if (mode === "day") {
    return form?.querySelector('[name="period_date"]')?.value || "";
  }
  return form?.querySelector('[name="period_month"]')?.value || "";
}

function setReportPeriodVisibility(mode) {
  document.querySelectorAll("[data-report-period]").forEach((field) => {
    const visible = field.dataset.reportPeriod === String(mode || "month");
    field.classList.toggle("hidden", !visible);
  });
}

function buildReportQuery(form) {
  const mode = form.querySelector('[name="period_mode"]')?.value || "month";
  const periodValue = reportPeriodValueFromForm(form);
  const query = new URLSearchParams({
    period_mode: mode,
    period_value: periodValue,
  });
  const reportType = form.querySelector('[name="report_type"]')?.value || "financeiro";
  const convenioCode = form.querySelector('[name="convenio_code"]')?.value || "";
  const patientId = form.querySelector('[name="patient_id"]')?.value || "";
  if (convenioCode) query.set("convenio_code", convenioCode);
  if (patientId) query.set("patient_id", patientId);
  return { reportType, mode, periodValue, query };
}

function examInvoice(examId) {
  const exam = findExamById(examId);
  if (exam?.order_id) {
    const orderInvoice = (state.invoices || []).find((invoice) => String(invoice.order_id) === String(exam.order_id));
    if (orderInvoice) return orderInvoice;
  }
  return (state.invoices || []).find((invoice) => String(invoice.exam_id) === String(examId)) || null;
}

function selectedDialogExam() {
  return findExamById(state.examDialog?.examId || "");
}

function findExamById(examId) {
  const targetId = String(examId || "");
  return [...(state.exams || []), ...(state.examHistory || [])].find((item) => String(item.id) === targetId) || null;
}

function findPatientById(patientId) {
  const targetId = String(patientId || "");
  return (state.patients || []).find((item) => String(item.id) === targetId) || null;
}

function promptPatientRegistrationFromExam() {
  setExamDialogTab("patient");
  populateExamDialogPatientForm(null);
  window.requestAnimationFrame(() => {
    document.querySelector('#examDialogPatientForm [name="full_name"]')?.focus();
  });
  showFlash("Selecione um paciente cadastrado. Se ele nao estiver na lista, cadastre o paciente agora.", true);
}

function openExamDialog(examOrMode, activeTab = "launch") {
  const exam = typeof examOrMode === "object" && examOrMode ? examOrMode : null;
  state.examDialog = {
    open: true,
    activeTab,
    examId: exam ? String(exam.id) : "",
  };
  const dialog = document.getElementById("examDialog");
  if (dialog) {
    dialog.classList.remove("hidden");
    dialog.setAttribute("aria-hidden", "false");
  }
  if (exam) {
    populateExamForm(exam);
    populateExamDialogPatientForm(selectedDialogPatient());
  } else {
    resetManagedForm("examForm");
    fillForm("examForm", {
      id: "",
      patient_id: "",
      procedure_id: "",
      convenio_code: "PARTICULAR",
      incidences_count: "1",
      modality: "DR",
      priority: "ROUTINE",
      workflow_stage: "scheduled",
      notes: "",
      price: "",
    });
    populateExamDialogPatientForm(null);
  }
  renderExamDialog();
  if (!exam) updateExamPriceField();
}

function closeExamDialog() {
  state.examDialog = { open: false, activeTab: "launch", examId: "" };
  const dialog = document.getElementById("examDialog");
  if (dialog) {
    dialog.classList.add("hidden");
    dialog.setAttribute("aria-hidden", "true");
  }
}

function setExamDialogTab(tab) {
  state.examDialog.activeTab = tab;
  renderExamDialog();
}

function formToObject(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function fillForm(formId, payload) {
  const form = document.getElementById(formId);
  if (!form) return;
  Object.entries(payload || {}).forEach(([key, value]) => {
    const field = form.querySelector(`[name="${key}"]`);
    if (!field) return;
    if (field.type === "checkbox") field.checked = Boolean(value);
    else field.value = value ?? "";
  });
}

function resetManagedForm(formId) {
  const form = document.getElementById(formId);
  if (!form) return;
  form.reset();
  const hidden = form.querySelector('input[type="hidden"][name="id"]');
  if (hidden) hidden.value = "";
}

function resetBudgetForm() {
  resetManagedForm("budgetForm");
  const patientId = document.getElementById("budgetPatientId");
  if (patientId) patientId.value = "";
  state.budgetItems = [makeBudgetItem()];
  renderBudget();
}

function setSelectOptions(selectId, items, labelBuilder, includeBlank = true) {
  const select = document.getElementById(selectId);
  if (!select) return;
  const current = select.value;
  select.innerHTML = `${includeBlank ? '<option value="">Selecione</option>' : ""}${
    items.map((item) => `<option value="${item.id}">${escapeHtml(labelBuilder(item))}</option>`).join("")
  }`;
  if ([...select.options].some((option) => option.value === current)) select.value = current;
}

function procedureDisplayName(procedure) {
  const name = String(procedure?.name || "").trim();
  const modality = String(procedure?.modality || "").trim();
  if (!name || !modality) return name;
  const escapedModality = modality.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const suffix = new RegExp(`\\s*[-•]\\s*${escapedModality}\\s*$`, "i");
  return name.replace(suffix, "").trim();
}

function currentOperator() {
  return state.departments.find((item) => String(item.id) === String(state.currentOperatorId)) || null;
}

function currentContact() {
  return state.departments.find((item) => String(item.id) === String(state.currentContactId)) || null;
}

function pricingConvenios() {
  return state.pricingConfig?.convenios || [];
}

function pricingOverrides() {
  return state.pricingOverrides?.items || [];
}

function pricingOverrideMap(convenioCode) {
  const selectedCode = normalizeConvenioCode(convenioCode);
  return pricingOverrides().reduce((map, item) => {
    if (normalizeConvenioCode(item.convenio_code) !== selectedCode) return map;
    map[String(item.procedure_id)] = item;
    return map;
  }, {});
}

function pricingOverridePrice(convenioCode, procedureId, incidence) {
  const item = pricingOverrideMap(convenioCode)[String(procedureId)];
  if (!item || !item.prices || !(String(incidence) in item.prices)) return null;
  const price = Number(item?.prices?.[String(incidence)] || 0);
  return Number.isFinite(price) ? price : null;
}

function currentProcedure() {
  return state.procedures.find((item) => String(item.id) === String(document.getElementById("examProcedure")?.value || "")) || null;
}

function resolveExamPricePreview(procedure, convenioCode, incidencesCount) {
  const selectedProcedure = procedure || null;
  if (!selectedProcedure) return "";
  const code = String(convenioCode || "PARTICULAR").trim().toUpperCase();
  const overridePrice = pricingOverridePrice(code, selectedProcedure.id, incidencesCount);
  if (overridePrice !== null) {
    return overridePrice;
  }
  const convenio = pricingConvenios().find((item) => String(item.code || "").toUpperCase() === code);
  const price = Number(convenio?.prices?.[String(Math.min(Math.max(Number(incidencesCount || 1), 1), 3))] || 0);
  if (price > 0) {
    return price;
  }
  if (code === "PARTICULAR") {
    return Number(selectedProcedure.default_price || 0);
  }
  return 0;
}

function resolveProcedurePrice(procedureId, convenioCode, incidencesCount) {
  const procedure = state.procedures.find((item) => String(item.id) === String(procedureId));
  return resolveExamPricePreview(procedure, convenioCode, incidencesCount) || 0;
}

function updateExamPriceField() {
  const procedure = currentProcedure();
  const convenioCode = document.getElementById("examConvenio")?.value || "PARTICULAR";
  const incidencesCount = document.getElementById("examIncidences")?.value || "1";
  const priceField = document.querySelector('#examForm [name="price"]');
  if (!priceField) return;
  const price = resolveExamPricePreview(procedure, convenioCode, incidencesCount);
  setCurrencyFieldValue(priceField, price !== "" && price !== null && price !== undefined ? price : 0);
}

function buildPricingConfigPayload(form) {
  const cards = [...form.querySelectorAll("[data-pricing-card]")];
  const convenios = cards.map((card) => {
    const cardKey = card.dataset.pricingCard || "";
    const code = String(form.querySelector(`[name="pricing_code_${cardKey}"]`)?.value || "").trim().toUpperCase();
    if (!code) return null;
    const fallbackName = code.replace(/_/g, " ").replace(/\s+/g, " ").trim() || code;
    return {
      code,
      name: String(form.querySelector(`[name="pricing_name_${cardKey}"]`)?.value || fallbackName).trim() || fallbackName,
      commission_amount: form.querySelector(`[name="pricing_${cardKey}_commission_amount"]`)?.value || (code === "PARTICULAR" ? 10 : 6),
      prices: {
        1: form.querySelector(`[name="pricing_${cardKey}_1"]`)?.value || 0,
        2: form.querySelector(`[name="pricing_${cardKey}_2"]`)?.value || 0,
        3: form.querySelector(`[name="pricing_${cardKey}_3"]`)?.value || 0,
      },
    };
  }).filter(Boolean);
  return { convenios };
}

function renderExamPricingOptions() {
  const convenioSelect = document.getElementById("examConvenio");
  if (convenioSelect) {
    const current = convenioSelect.value || "PARTICULAR";
    const convenios = pricingConvenios();
    convenioSelect.innerHTML = convenios
      .map((item) => `<option value="${escapeHtml(item.code)}">${escapeHtml(item.name || item.code)}</option>`)
      .join("");
    if ([...convenioSelect.options].some((option) => option.value === current)) {
      convenioSelect.value = current;
    } else if (convenios[0]) {
      convenioSelect.value = convenios[0].code;
    }
  }

  const incidenceSelect = document.getElementById("examIncidences");
  if (incidenceSelect) {
    const current = incidenceSelect.value || "1";
    if ([...incidenceSelect.options].some((option) => option.value === current)) {
      incidenceSelect.value = current;
    } else {
      incidenceSelect.value = "1";
    }
  }
}

function renderExamPricingMatrix() {
  const filterSelect = document.getElementById("examListConvenioFilter");
  if (filterSelect) {
    const current = filterSelect.value || "ALL";
    const convenios = pricingConvenios();
    filterSelect.innerHTML = `<option value="ALL">Todos os convenios</option>${
      convenios.map((item) => `<option value="${escapeHtml(item.code)}">${escapeHtml(item.name || item.code)}</option>`).join("")
    }`;
    if ([...filterSelect.options].some((option) => option.value === current)) {
      filterSelect.value = current;
    } else if (convenios[0]) {
      filterSelect.value = convenios[0].code;
    }
  }

  const container = document.getElementById("examPricingMatrix");
  if (!container) return;
  const convenioCode = normalizeConvenioCode(document.getElementById("examListConvenioFilter")?.value || "ALL");
  const activeProcedures = state.procedures.filter((procedure) => procedure.active !== false);
  if (!activeProcedures.length) {
    container.innerHTML = htmlListRow("Sem procedimentos", "Cadastre um procedimento antes de ver a matriz de preços.");
    return;
  }

  const rows = activeProcedures.map((procedure) => {
    const price1 = resolveExamPricePreview(procedure, convenioCode === "ALL" ? "PARTICULAR" : convenioCode, 1);
    const price2 = resolveExamPricePreview(procedure, convenioCode === "ALL" ? "PARTICULAR" : convenioCode, 2);
    const price3 = resolveExamPricePreview(procedure, convenioCode === "ALL" ? "PARTICULAR" : convenioCode, 3);
    return `
      <tr>
        <td>${escapeHtml(procedure.name)}</td>
        <td>${escapeHtml(procedure.modality || "-")}</td>
        <td>${escapeHtml(money(price1))}</td>
        <td>${escapeHtml(money(price2))}</td>
        <td>${escapeHtml(money(price3))}</td>
      </tr>
    `;
  }).join("");
  container.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Procedimento</th>
          <th>Modalidade</th>
          <th>1 incidencia</th>
          <th>2 incidencias</th>
          <th>3 incidencias</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderExamDialog() {
  const dialog = document.getElementById("examDialog");
  if (!dialog) return;
  const exam = selectedDialogExam();
  const activeTab = state.examDialog?.activeTab || "launch";
  dialog.classList.toggle("hidden", !state.examDialog?.open);
  dialog.setAttribute("aria-hidden", state.examDialog?.open ? "false" : "true");

  document.querySelectorAll("[data-exam-dialog-panel]").forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.examDialogPanel !== activeTab);
  });
  document.querySelectorAll("[data-exam-dialog-tab]").forEach((button) => {
    button.classList.toggle("primary", button.dataset.examDialogTab === activeTab);
    button.classList.toggle("ghost", button.dataset.examDialogTab !== activeTab);
  });

  const title = document.getElementById("examDialogTitle");
  const subtitle = document.getElementById("examDialogSubtitle");
  if (title) title.textContent = exam ? `Exame ${exam.accession_number || exam.id}` : "Novo lancamento";
  if (subtitle) {
    subtitle.textContent = exam
      ? `${exam.patient_name || "-"} • ${exam.procedure_name || "-"} • ${exam.workflow_label || exam.workflow_stage || "-"}`
      : "Criar, editar e movimentar o exame sem sair da tela.";
  }

  const summary = document.getElementById("examDialogSummary");
  if (summary) {
    summary.innerHTML = exam
      ? [
          htmlCard("Paciente", exam.patient_name || "-"),
          htmlCard("Procedimento", exam.procedure_name || "-"),
          htmlCard("Convênio", exam.convenio_label || exam.convenio_code || "PARTICULAR"),
          htmlCard("Fluxo", exam.workflow_label || exam.workflow_stage || "-"),
          htmlCard("Worklist", exam.worklist_status_label || exam.worklist_status || "-"),
          htmlCard("Preço", money(exam.price || 0)),
        ].join("")
      : [
          htmlCard("Novo", "Lancamento"),
          htmlCard("Convênio", "Particular"),
          htmlCard("Preço", "Automatico"),
        ].join("");
  }

  const patientSummary = document.getElementById("examDialogPatientSummary");
  if (patientSummary) {
    if (!exam) {
      patientSummary.innerHTML = htmlListRow("Paciente ainda nao selecionado", "Cadastre o paciente aqui e ele sera selecionado no lancamento.");
    } else {
      patientSummary.innerHTML = [
        htmlMetric("Paciente", exam.patient_name || "-"),
        htmlMetric("CPF", exam.patient_cpf || "-"),
        htmlMetric("Nascimento", exam.patient_birth_date || "-"),
        htmlMetric("Contato", exam.patient_phone || exam.patient_email || "-"),
        htmlMetric("Exame", exam.procedure_name || "-"),
      ].join("");
    }
  }

  const worklistSummary = document.getElementById("examDialogWorklistSummary");
  if (worklistSummary) {
    if (!exam) {
      worklistSummary.innerHTML = htmlListRow("Sem exame selecionado", "O menu manual de worklist aparece quando um card e aberto.");
    } else {
      worklistSummary.innerHTML = [
        htmlMetric("Etapa", exam.workflow_label || exam.workflow_stage || "-"),
        htmlMetric("MWL", exam.worklist_status_label || exam.worklist_status || "-"),
        htmlMetric("Ticket", exam.ticket_number || "-"),
        htmlMetric("Modalidade", exam.modality || exam.procedure_modality || "-"),
      ].join("");
    }
  }

  const reportingSummary = document.getElementById("examDialogReportingSummary");
  if (reportingSummary) {
    const workspaceExamId = String(state.reportingWorkspace?.exam?.id || state.selectedWorkspaceExamId || "");
    if (!exam) {
      reportingSummary.innerHTML = htmlListRow("Sem exame selecionado", "Abra um card do kanban para acessar laudos e viewer.");
    } else if (workspaceExamId && workspaceExamId !== String(exam.id)) {
      reportingSummary.innerHTML = htmlListRow("Workspace desatualizado", "Abra o workspace deste exame para ver laudos e anexos.");
    } else {
      const attachments = state.reportingWorkspace?.attachments?.length || 0;
      const dicomObjects = state.reportingWorkspace?.dicom_objects?.length || 0;
      const report = state.reportingWorkspace?.report || {};
      reportingSummary.innerHTML = [
        htmlMetric("Paciente", exam.patient_name || "-"),
        htmlMetric("Procedimento", exam.procedure_name || "-"),
        htmlMetric("Anexos", attachments),
        htmlMetric("DICOM", dicomObjects),
        htmlMetric("Status do laudo", report.status || exam.workflow_label || "-"),
      ].join("");
    }
  }

  const panelSummary = document.getElementById("examDialogPanelSummary");
  if (panelSummary) {
    if (!exam) {
      panelSummary.innerHTML = htmlListRow("Sem exame selecionado", "Abra um card para acessar o painel embutido.");
    } else {
      panelSummary.innerHTML = [
        htmlMetric("Senha", exam.ticket_number || "-"),
        htmlMetric("Status", exam.queue_status_label || exam.queue_status || "-"),
        htmlMetric("Destino", exam.queue_destination || "-"),
        htmlMetric("Paciente", exam.patient_name || "-"),
      ].join("");
    }
  }
  const panelDestination = document.getElementById("examDialogPanelDestination");
  if (panelDestination) {
    const currentExamId = panelDestination.dataset.examId || "";
    const nextValue = exam ? (exam.queue_destination || state.currentDepartmentName || "") : "";
    if (!exam) {
      panelDestination.value = "";
      panelDestination.dataset.examId = "";
    } else if (currentExamId !== String(exam.id) || !panelDestination.value) {
      panelDestination.value = nextValue;
      panelDestination.dataset.examId = String(exam.id);
    }
  }

  const financeSummary = document.getElementById("examDialogFinanceSummary");
  const invoice = exam ? examInvoice(exam.id) : null;
  const orderItems = exam?.order_id
    ? (state.exams || []).filter((item) => String(item.order_id) === String(exam.order_id))
    : (exam ? [exam] : []);
  const orderItemsEl = document.getElementById("examDialogOrderItems");
  if (orderItemsEl) {
    orderItemsEl.innerHTML = orderItems.length > 1 ? `
      <table>
        <thead><tr><th>Exame</th><th>Incid.</th><th>Valor</th><th>Acoes</th></tr></thead>
        <tbody>
          ${orderItems.map((item) => `
            <tr>
              <td>${escapeHtml(item.procedure_name || "-")}</td>
              <td>${escapeHtml(item.incidences_count || 1)}</td>
              <td>${escapeHtml(money(item.price || 0))}</td>
              <td><button class="mini" type="button" data-open-exam-dialog="${item.id}" data-open-exam-tab="launch">Editar</button></td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    ` : "";
  }
  const orderDiscountField = document.getElementById("examOrderDiscount");
  if (orderDiscountField && document.activeElement !== orderDiscountField) {
    orderDiscountField.value = formatCurrencyBRL(exam?.order_discount || invoice?.discount || 0);
  }
  const orderProcedureSelect = document.getElementById("examOrderProcedure");
  if (orderProcedureSelect) {
    const current = orderProcedureSelect.value;
    const activeProcedures = state.procedures.filter((procedure) => procedure.active !== false);
    orderProcedureSelect.innerHTML = `<option value="">Somente desconto</option>` + activeProcedures
      .map((procedure) => `<option value="${procedure.id}">${escapeHtml(procedureDisplayName(procedure))}</option>`)
      .join("");
    if ([...orderProcedureSelect.options].some((option) => option.value === current)) orderProcedureSelect.value = current;
  }
  const orderIncidences = document.getElementById("examOrderIncidences");
  const orderPrice = document.getElementById("examOrderPrice");
  if (orderPrice && document.activeElement !== orderPrice) {
    const procedureId = orderProcedureSelect?.value || "";
    const incidences = orderIncidences?.value || 1;
    const convenioCode = exam?.convenio_code || "PARTICULAR";
    orderPrice.value = procedureId ? formatCurrencyBRL(resolveProcedurePrice(procedureId, convenioCode, incidences)) : formatCurrencyBRL(0);
  }
  if (financeSummary) {
    if (!exam) {
      financeSummary.innerHTML = htmlListRow("Sem exame selecionado", "Abra um card para ver a fatura deste exame.");
    } else if (!invoice) {
      financeSummary.innerHTML = htmlListRow("Sem fatura localizada", "A fatura do exame ainda nao foi gerada.");
    } else {
      financeSummary.innerHTML = [
        htmlMetric("Fatura", invoice.invoice_number || "-"),
        htmlMetric("Status", financeStatusLabel(invoice.status)),
        htmlMetric("Subtotal", money(invoice.amount || 0)),
        htmlMetric("Desconto", money(invoice.discount || 0)),
        htmlMetric("Valor", money(invoice.net_amount || 0)),
        htmlMetric("Forma atual", paymentMethodLabel(invoice.payment_method || "dinheiro")),
      ].join("");
    }
  }
  const paymentMethodSelect = document.getElementById("examDialogPaymentMethod");
  if (paymentMethodSelect) {
    paymentMethodSelect.value = normalizePaymentMethod(invoice?.payment_method || "dinheiro");
    paymentMethodSelect.disabled = !invoice || invoice.status === "paid";
  }
  const financeMarkPaidButton = document.querySelector("[data-exam-finance-mark-paid]");
  if (financeMarkPaidButton) {
    financeMarkPaidButton.disabled = !invoice || invoice.status === "paid";
    financeMarkPaidButton.textContent = invoice?.status === "paid" ? "Pago" : "Marcar pago";
  }
  const financeUndoPaidButton = document.querySelector("[data-exam-finance-undo-paid]");
  if (financeUndoPaidButton) {
    financeUndoPaidButton.disabled = !invoice || invoice.status !== "paid";
  }

  const patientAction = document.querySelector("[data-open-selected-patient]");
  if (patientAction) {
    patientAction.disabled = !exam;
  }
  document.querySelectorAll("[data-exam-worklist-action], [data-exam-worklist-move], [data-open-exam-workspace], [data-open-exam-viewer], [data-exam-panel-call], [data-exam-panel-open], [data-exam-order-apply-discount], [data-exam-order-add-item]").forEach((button) => {
    button.disabled = !exam;
  });
}

async function moveExamStageByDelta(examId, delta) {
  const exam = state.exams.find((item) => String(item.id) === String(examId));
  if (!exam) return;
  const currentIndex = workflowStages.findIndex((stage) => stage.key === String(exam.workflow_stage || ""));
  const nextIndex = currentIndex + delta;
  if (nextIndex < 0 || nextIndex >= workflowStages.length) return;
  await moveExamIdsToStage([exam.id], workflowStages[nextIndex].key, false);
  await loadAll();
}

async function moveExamIdsToStage(examIds, stage, reload = true) {
  const ids = [...new Set((examIds || []).map((item) => String(item || "").trim()).filter(Boolean))];
  for (const examId of ids) {
    await api(`/api/exams/${examId}/workflow-stage`, {
      method: "PUT",
      body: JSON.stringify({ stage }),
    });
  }
  if (reload) {
    await loadAll();
  }
}

async function moveExamIdsByDelta(examIds, delta) {
  const firstExam = state.exams.find((item) => String(item.id) === String((examIds || [])[0]));
  if (!firstExam) return;
  const currentIndex = workflowStages.findIndex((stage) => stage.key === String(firstExam.workflow_stage || ""));
  const nextIndex = currentIndex + delta;
  if (nextIndex < 0 || nextIndex >= workflowStages.length) return;
  await moveExamIdsToStage(examIds, workflowStages[nextIndex].key);
}

function parseExamIds(value) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

function budgetTotals() {
  const convenioCode = document.getElementById("budgetConvenio")?.value || "PARTICULAR";
  const subtotal = state.budgetItems.reduce((total, item) => {
    const price = Number(item.price || resolveProcedurePrice(item.procedure_id, convenioCode, item.incidences_count) || 0);
    return total + price;
  }, 0);
  const discount = parseCurrencyBRL(document.getElementById("budgetDiscount")?.value || 0);
  return { subtotal, discount, total: Math.max(subtotal - discount, 0) };
}

function renderBudgetSummary() {
  const totals = budgetTotals();
  const summary = document.getElementById("budgetSummary");
  if (summary) {
    summary.innerHTML = [
      htmlMetric("Exames", state.budgetItems.length),
      htmlMetric("Subtotal", money(totals.subtotal)),
      htmlMetric("Desconto", money(totals.discount)),
      htmlMetric("Total", money(totals.total)),
    ].join("");
  }
}

function updateBudgetItem(draftId, field, value, shouldRender = true) {
  const convenioCode = document.getElementById("budgetConvenio")?.value || "PARTICULAR";
  state.budgetItems = state.budgetItems.map((item) => {
    if (item.draftId !== draftId) return item;
    const next = { ...item, [field]: value };
    if (field === "procedure_id" || field === "incidences_count") {
      next.price = resolveProcedurePrice(next.procedure_id, convenioCode, next.incidences_count);
    }
    if (field === "price") {
      next.price = parseCurrencyBRL(value);
    }
    return next;
  });
  if (shouldRender) renderBudget();
  else renderBudgetSummary();
}

function buildBudgetPayload() {
  const form = document.getElementById("budgetForm");
  const payload = formToObject(form);
  const convenioCode = payload.convenio_code || "PARTICULAR";
  const items = state.budgetItems.map((item) => ({
    procedure_id: Number(item.procedure_id || 0),
    convenio_code: convenioCode,
    incidences_count: Number(item.incidences_count || 1),
    price: Number(item.price || resolveProcedurePrice(item.procedure_id, convenioCode, item.incidences_count) || 0),
    scheduled_at: item.scheduled_at || "",
    priority: item.priority || "ROUTINE",
    notes: item.notes || "",
  })).filter((item) => item.procedure_id > 0);
  return {
    patient_id: Number(payload.patient_id || 0),
    patient_name: String(payload.patient_name || "").trim(),
    reference: payload.reference || "",
    notes: payload.notes || "",
    discount: parseCurrencyBRL(payload.discount),
    status: "budget",
    items,
  };
}

function renderDashboard() {
  const summary = state.overview?.summary || {};
  const finance = state.overview?.finance || state.finance || {};
  const financeTotals = finance.totals || {};
  const financeMethodCards = [
    htmlCard("Pagas", financeTotals.paid_invoices || 0, money(financeTotals.paid_total || 0)),
    htmlCard("Em aberto", financeTotals.open_invoices || 0, money(financeTotals.open_total || 0)),
    ...(finance.payment_methods || []).slice(0, 4).map((item) => htmlCard(paymentMethodLabel(item.payment_method), item.total_invoices || 0, money(item.total_value || 0))),
  ];
  document.getElementById("dashboardCards").innerHTML = [
    htmlCard("Pacientes", summary.patients || 0, "Base da clinica"),
    htmlCard("Exames", summary.exams || 0, "Fluxo radiologico"),
    htmlCard("Pendentes worklist", summary.pending_worklist || 0, "Ainda fora da MWL local"),
    htmlCard("MWL local ativa", summary.local_worklist_active || 0, "Servida pela aplicacao"),
    htmlCard("Mensagens nao lidas", summary.unread_messages || 0, "Comunicacao interna"),
    htmlCard("Chamadas aguardando", summary.waiting_calls || 0, "Fila do painel"),
    htmlCard("Departamentos", summary.departments || 0, "Chat por setor"),
  ].join("");

  document.getElementById("workflowCounters").innerHTML = workflowStages
    .map((stage) => htmlMetric(stage.label, state.overview?.workflow_counts?.[stage.key] || 0))
    .join("");

  document.getElementById("latestExams").innerHTML = (state.overview?.latest_exams || [])
    .map((exam) => htmlListRow(exam.patient_name, `${exam.procedure_name} • ${exam.workflow_label}`, exam.accession_number))
    .join("") || htmlListRow("Nenhum exame", "Cadastre um exame para iniciar o fluxo.");

  document.getElementById("latestMessages").innerHTML = (state.overview?.latest_messages || [])
    .map((message) => htmlListRow(message.sender_name, message.body, dateTimeLabel(message.created_at)))
    .join("") || htmlListRow("Sem mensagens", "O chat entre setores aparece aqui.");

  document.getElementById("departmentsSummary").innerHTML = [
    htmlMetric("Chamadas em curso", state.overview?.calls?.summary?.called || 0),
    htmlMetric("Em atendimento", state.overview?.calls?.summary?.in_service || 0),
    htmlMetric("Departamentos", state.overview?.summary?.departments || 0),
    htmlMetric("Disco usado", `${state.overview?.storage?.disk_used_percent || 0}%`),
  ].join("");

  const dashboardFinanceCards = document.getElementById("dashboardFinanceCards");
  if (dashboardFinanceCards) {
    dashboardFinanceCards.innerHTML = financeMethodCards.join("") || htmlCard("Sem dados", 0, "Financeiro nao disponivel");
  }
}

function renderPatients() {
  document.getElementById("patientsTable").innerHTML = `<table><thead><tr><th>Nome</th><th>CPF</th><th>Nascimento</th><th>Exames</th><th>Acoes</th></tr></thead><tbody>${
    state.patients.map((patient) => `
      <tr>
        <td>${escapeHtml(patient.full_name)}</td>
        <td>${escapeHtml(patient.cpf || "-")}</td>
        <td>${escapeHtml(patient.birth_date || "-")}</td>
        <td>${escapeHtml(patient.exam_count || 0)}</td>
        <td><button class="mini edit-patient" data-id="${patient.id}">Editar</button></td>
      </tr>
    `).join("")
  }</tbody></table>`;
  setSelectOptions("examPatient", state.patients, (item) => `${item.full_name}${item.cpf ? ` • CPF ${item.cpf}` : ""}`);
}

function renderProcedures() {
  const canEdit = Boolean(state.adminUnlocked);
  const procedureActions = (procedure) => canEdit
    ? [
        `<button class="mini edit-procedure" data-id="${procedure.id}">Editar</button>`,
        `<button class="mini danger delete-procedure" data-id="${procedure.id}" data-name="${escapeHtml(procedureDisplayName(procedure))}">Excluir</button>`,
      ].join(" ")
    : `<span class="muted">Somente leitura</span>`;
  document.getElementById("proceduresTable").innerHTML = `<table><thead><tr><th>Descricao</th><th>Modalidade</th><th>Acoes</th></tr></thead><tbody>${
    state.procedures.map((procedure) => `
      <tr>
        <td>${escapeHtml(procedureDisplayName(procedure))}</td>
        <td>${escapeHtml(procedure.modality || "-")}</td>
        <td>${procedureActions(procedure)}</td>
      </tr>
    `).join("")
  }</tbody></table>`;
  const activeProcedures = state.procedures.filter((procedure) => procedure.active !== false);
  setSelectOptions("examProcedure", activeProcedures, procedureDisplayName);
}

function renderBudget() {
  const patientInput = document.getElementById("budgetPatientName");
  const patientId = document.getElementById("budgetPatientId");
  const patientSuggestions = document.getElementById("budgetPatientSuggestions");
  if (patientSuggestions) {
    patientSuggestions.innerHTML = (state.patients || [])
      .map((item) => `<option value="${escapeHtml(item.full_name || "")}">${escapeHtml(item.cpf ? `CPF ${item.cpf}` : "")}</option>`)
      .join("");
  }
  if (patientInput && patientId) {
    const match = (state.patients || []).find((item) => String(item.full_name || "").trim().toLowerCase() === patientInput.value.trim().toLowerCase());
    patientId.value = match ? String(match.id) : "";
  }

  const convenioSelect = document.getElementById("budgetConvenio");
  if (convenioSelect) {
    const current = convenioSelect.value || "PARTICULAR";
    const convenios = pricingConvenios();
    convenioSelect.innerHTML = convenios
      .map((item) => `<option value="${escapeHtml(item.code)}">${escapeHtml(item.name || item.code)}</option>`)
      .join("");
    if ([...convenioSelect.options].some((option) => option.value === current)) {
      convenioSelect.value = current;
    } else if (convenios[0]) {
      convenioSelect.value = convenios[0].code;
    }
  }

  if (!state.budgetItems.length) {
    state.budgetItems = [makeBudgetItem()];
  }

  const convenioCode = document.getElementById("budgetConvenio")?.value || "PARTICULAR";
  const activeProcedures = state.procedures.filter((procedure) => procedure.active !== false);
  const rows = state.budgetItems.map((item, index) => {
    const price = Number(item.price || resolveProcedurePrice(item.procedure_id, convenioCode, item.incidences_count) || 0);
    return `
      <div class="budget-item" data-budget-item="${escapeHtml(item.draftId)}">
        <label><span>Procedimento</span><select data-budget-field="procedure_id">
          <option value="">Selecione</option>
          ${activeProcedures.map((procedure) => `<option value="${procedure.id}" ${String(item.procedure_id) === String(procedure.id) ? "selected" : ""}>${escapeHtml(procedureDisplayName(procedure))}</option>`).join("")}
        </select></label>
        <label><span>Incidências</span><select data-budget-field="incidences_count">
          ${[1, 2, 3].map((count) => `<option value="${count}" ${String(item.incidences_count || "1") === String(count) ? "selected" : ""}>${count}</option>`).join("")}
        </select></label>
        <label><span>Preço</span><input data-budget-field="price" type="text" inputmode="numeric" value="${escapeHtml(formatCurrencyBRL(price))}" /></label>
        <label><span>Agendamento</span><input data-budget-field="scheduled_at" type="datetime-local" value="${escapeHtml(item.scheduled_at || "")}" /></label>
        <label><span>Prioridade</span><select data-budget-field="priority">
          <option value="ROUTINE" ${item.priority === "ROUTINE" ? "selected" : ""}>Rotina</option>
          <option value="HIGH" ${item.priority === "HIGH" ? "selected" : ""}>Alta</option>
          <option value="STAT" ${item.priority === "STAT" ? "selected" : ""}>STAT</option>
        </select></label>
        <label><span>Obs.</span><input data-budget-field="notes" value="${escapeHtml(item.notes || "")}" /></label>
        <button class="mini danger" type="button" data-remove-budget-item="${escapeHtml(item.draftId)}">Remover</button>
      </div>
    `;
  }).join("");

  const budgetItems = document.getElementById("budgetItems");
  if (budgetItems) budgetItems.innerHTML = rows;

  renderBudgetSummary();
}

function renderExams() {
  const canEditExam = Boolean(state.adminUnlocked);
  const workbenchTarget = state.examWorkbenchTarget === "values" ? "values" : "form";
  document.querySelectorAll("[data-exam-workbench-target]").forEach((button) => {
    const isActive = button.dataset.examWorkbenchTarget === workbenchTarget;
    button.classList.toggle("primary", isActive);
    button.classList.toggle("ghost", !isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
  document.querySelectorAll("[data-exam-workbench-panel]").forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.examWorkbenchPanel !== workbenchTarget);
  });

  const typeSelect = document.getElementById("examListTypeFilter");
  if (typeSelect) {
    const current = String(typeSelect.value || "ALL").toUpperCase();
    if ([...typeSelect.options].some((option) => option.value === current)) {
      typeSelect.value = current;
    } else {
      typeSelect.value = "ALL";
    }
  }

  const convenioSelect = document.getElementById("examListConvenioFilter");
  if (convenioSelect) {
    const current = String(convenioSelect.value || state.examPricingTable || "PARTICULAR").toUpperCase();
    convenioSelect.innerHTML = `
      <option value="PARTICULAR">Particular</option>
      <option value="CONVENIOS">Convenios</option>
    `;
    if ([...convenioSelect.options].some((option) => option.value === current)) {
      convenioSelect.value = current;
    } else {
      convenioSelect.value = state.examPricingTable || "PARTICULAR";
    }
    setExamPricingTable(convenioSelect.value);
  } else {
    setExamPricingTable(state.examPricingTable || "PARTICULAR");
  }

  const examLookupSearch = document.getElementById("examLookupSearch");
  if (state.examLookupFocus && examLookupSearch) {
    window.setTimeout(() => {
      examLookupSearch.focus();
      state.examLookupFocus = false;
    }, 0);
  }

  const selectedPricingTable = normalizeConvenioCode(document.getElementById("examListConvenioFilter")?.value || state.examPricingTable || "PARTICULAR");
  const selectedType = String(document.getElementById("examListTypeFilter")?.value || "ALL").toUpperCase();
  const proceduresToRender = state.procedures.filter((procedure) => {
    if (procedure.active === false) return false;
    const procedureType = normalizeConvenioCode(procedure.modality || "DR");
    return selectedType === "ALL" || procedureType === selectedType;
  });

  const maintenanceTable = document.getElementById("examsTable");
  if (maintenanceTable) {
    const rows = proceduresToRender.map((procedure) => {
      const current1 = resolveExamPricePreview(procedure, selectedPricingTable, 1);
      const current2 = resolveExamPricePreview(procedure, selectedPricingTable, 2);
      const current3 = resolveExamPricePreview(procedure, selectedPricingTable, 3);
      return `
        <tr data-pricing-row="${procedure.id}">
          <td>${escapeHtml(procedure.name)}</td>
          <td>${escapeHtml(procedure.modality || "-")}</td>
          <td><input class="inline-input" data-pricing-incidence="1" data-procedure-id="${procedure.id}" data-convenio-code="${escapeHtml(selectedPricingTable)}" type="number" step="0.01" min="0" value="${escapeHtml(current1)}" ${canEditExam ? "" : "disabled"} /></td>
          <td><input class="inline-input" data-pricing-incidence="2" data-procedure-id="${procedure.id}" data-convenio-code="${escapeHtml(selectedPricingTable)}" type="number" step="0.01" min="0" value="${escapeHtml(current2)}" ${canEditExam ? "" : "disabled"} /></td>
          <td><input class="inline-input" data-pricing-incidence="3" data-procedure-id="${procedure.id}" data-convenio-code="${escapeHtml(selectedPricingTable)}" type="number" step="0.01" min="0" value="${escapeHtml(current3)}" ${canEditExam ? "" : "disabled"} /></td>
          <td>
            ${canEditExam ? `<button class="mini save-pricing-override" type="button" data-procedure-id="${procedure.id}" data-convenio-code="${escapeHtml(selectedPricingTable)}">Salvar valores</button>` : "-"}
          </td>
        </tr>
      `;
    }).join("");
    maintenanceTable.innerHTML = `<table><thead><tr><th>Procedimento</th><th>Tipo</th><th>1 incidencia</th><th>2 incidencias</th><th>3 incidencias</th><th>Acoes</th></tr></thead><tbody>${rows || ""}</tbody></table>`;
    if (!rows) {
      maintenanceTable.innerHTML = htmlListRow("Sem procedimentos", "Cadastre um procedimento antes de editar precos.");
    }
  }

  const lookupInput = document.getElementById("examLookupSearch");
  const lookupNormalized = String(lookupInput?.value || "").trim().toLowerCase();
  const lookupSuggestions = document.getElementById("examLookupSuggestions");
  const lookupResults = document.getElementById("examLookupResults");
  const lookupSourceMap = new Map();
  proceduresToRender.forEach((procedure) => {
    if (!procedure || lookupSourceMap.has(String(procedure.id))) return;
    lookupSourceMap.set(String(procedure.id), procedure);
  });
  const lookupSource = [...lookupSourceMap.values()].sort((left, right) => {
    return String(left.name || "").localeCompare(String(right.name || ""), "pt-BR", { sensitivity: "base" });
  });

  if (lookupSuggestions) {
    lookupSuggestions.innerHTML = lookupSource.slice(0, 30).map((procedure) => {
      const value = [
        procedure.name,
        procedure.modality,
      ].filter(Boolean).join(" • ");
      return `<option value="${escapeHtml(value)}"></option>`;
    }).join("");
  }

  const lookupSelect = document.getElementById("examLookupSelect");
  if (lookupSelect) {
    const filteredSelectRows = lookupSource.filter((procedure) => {
      if (!lookupNormalized) return true;
      const haystack = [
        procedure.name,
        procedure.modality,
        procedure.duration_minutes,
        procedure.active ? "ativo" : "inativo",
      ].join(" ").toLowerCase();
      return haystack.includes(lookupNormalized);
    });
    lookupSelect.innerHTML = filteredSelectRows
      .map((procedure) => {
        const label = [
          procedure.name,
          procedure.modality,
          procedure.active ? "Ativo" : "Inativo",
        ].filter(Boolean).join(" • ");
        return `<option value="${escapeHtml(procedure.id)}">${escapeHtml(label || `Procedimento ${procedure.id}`)}</option>`;
      })
      .join("") || `<option value="">Nenhum procedimento encontrado</option>`;
  }

  if (lookupResults) {
    const lookupRows = lookupSource.filter((procedure) => {
      if (!lookupNormalized) return true;
      const haystack = [
        procedure.name,
        procedure.modality,
        procedure.duration_minutes,
        procedure.active ? "ativo" : "inativo",
      ].join(" ").toLowerCase();
      return haystack.includes(lookupNormalized);
    });

    lookupResults.innerHTML = lookupRows.length
      ? `<table><thead><tr><th>Procedimento</th><th>Modalidade</th><th>Status</th><th>Acoes</th></tr></thead><tbody>${
          lookupRows.map((procedure) => `
            <tr>
              <td>${escapeHtml(procedure.name || "-")}<br/><small>${escapeHtml(procedure.duration_minutes ? `${procedure.duration_minutes} min` : "Sem duracao")}</small></td>
              <td>${escapeHtml(procedure.modality || "-")}</td>
              <td>${statusPill(procedure.active === false ? "Inativo" : "Ativo")}</td>
              <td>
                ${canEditExam ? `
                  <button class="mini edit-procedure-quick" type="button" data-procedure-id="${procedure.id}">Editar</button>
                  <button class="mini danger delete-procedure" type="button" data-id="${procedure.id}" data-name="${escapeHtml(procedureDisplayName(procedure))}">Excluir</button>
                ` : `<span class="muted">Somente leitura</span>`}
              </td>
            </tr>
          `).join("")
        }</tbody></table>`
      : htmlListRow("Sem resultado", "Digite o nome do procedimento para localizar e editar.");
  }
}

function renderFinance() {
  const totals = state.finance?.totals || {};
  document.getElementById("financeCards").innerHTML = [
    htmlCard("Faturas", totals.total_invoices || 0),
    htmlCard("Abertas", totals.open_invoices || 0, money(totals.open_total || 0)),
    htmlCard("Pagas", totals.paid_invoices || 0, money(totals.paid_total || 0)),
    htmlCard("Descontos", money(totals.discount_total || 0)),
  ].join("");

  document.getElementById("invoiceTable").innerHTML = `<table><thead><tr><th>Numero</th><th>Paciente</th><th>Procedimento</th><th>Subtotal</th><th>Desconto</th><th>Total</th><th>Status</th><th>Forma</th><th>Acoes</th></tr></thead><tbody>${
    state.invoices.map((invoice) => `
      <tr>
        <td>${escapeHtml(invoice.invoice_number)}</td>
        <td>${escapeHtml(invoice.patient_name)}</td>
        <td>${escapeHtml(invoice.procedure_name || (invoice.order_id ? `Ordem #${invoice.order_id}` : "-"))}</td>
        <td>${escapeHtml(money(invoice.amount || 0))}</td>
        <td>${escapeHtml(money(invoice.discount || 0))}</td>
        <td>${escapeHtml(money(invoice.net_amount || 0))}</td>
        <td>${statusPill(invoice.status)}</td>
        <td>${invoice.status === "paid" ? paymentMethodLabel(invoice.payment_method) : `<select class="inline-select" data-payment-method="${invoice.id}"><option value="dinheiro" ${normalizePaymentMethod(invoice.payment_method) === "dinheiro" ? "selected" : ""}>Dinheiro</option><option value="pix" ${normalizePaymentMethod(invoice.payment_method) === "pix" ? "selected" : ""}>Pix</option><option value="cartao" ${normalizePaymentMethod(invoice.payment_method) === "cartao" ? "selected" : ""}>Cartao</option><option value="cheque" ${normalizePaymentMethod(invoice.payment_method) === "cheque" ? "selected" : ""}>Cheque</option></select>`}</td>
        <td>
          ${invoice.order_id ? `<button class="mini" type="button" data-order-pdf="${invoice.order_id}">PDF</button>` : ""}
          ${invoice.status === "paid" ? "" : `<button class="mini mark-paid" data-id="${invoice.id}">Marcar pago</button>`}
          ${invoice.status === "paid" ? `<button class="mini undo-paid" type="button" data-id="${invoice.id}">Desfazer pagamento</button>` : ""}
          ${invoice.order_id && invoice.status !== "paid" ? `<button class="mini danger" type="button" data-delete-order="${invoice.order_id}">Excluir</button>` : ""}
        </td>
      </tr>
    `).join("")
  }</tbody></table>`;
}

function renderReports() {
  const reportType = state.reports.type || state.reports.preview?.report_type || "financeiro";
  const config = reportTypeConfig(reportType);
  const preview = state.reports.preview;
  const finance = state.overview?.finance || state.finance || {};
  const financeTotals = finance.totals || {};
  const summary = preview?.summary || {
    total_exams: financeTotals.total_invoices || 0,
    paid_exams: financeTotals.paid_invoices || 0,
    open_exams: financeTotals.open_invoices || 0,
    total_value: financeTotals.gross_total || 0,
    paid_value: financeTotals.paid_total || 0,
    open_value: financeTotals.open_total || 0,
  };

  const catalogEl = document.getElementById("reportCatalog");
  if (catalogEl) {
    catalogEl.innerHTML = reportCatalog
      .map((item) => `
        <button class="report-card ${item.key === reportType ? "active" : ""}" type="button" data-report-type="${item.key}">
          <strong>${escapeHtml(item.label)}</strong>
          <span>${escapeHtml(item.description)}</span>
        </button>
      `)
      .join("");
  }

  const form = document.getElementById("reportFilterForm");
  if (form) {
    form.querySelector('[name="report_type"]').value = reportType;
    const periodModeField = form.querySelector('[name="period_mode"]');
    if (periodModeField && !periodModeField.value) periodModeField.value = preview?.period_mode || "month";
    if (periodModeField) setReportPeriodVisibility(periodModeField.value || "month");
    const monthField = form.querySelector('[name="period_month"]');
    const dayField = form.querySelector('[name="period_date"]');
    const currentMonth = currentMonthInputValue();
    const currentDay = currentDateInputValue();
    if (monthField && !monthField.value) monthField.value = preview?.filters?.period_mode === "month" ? (preview?.filters?.period_value || currentMonth) : currentMonth;
    if (dayField && !dayField.value) dayField.value = preview?.filters?.period_mode === "day" ? (preview?.filters?.period_value || currentDay) : currentDay;
    const convenioField = form.querySelector('[name="convenio_code"]');
    const patientField = form.querySelector('[name="patient_id"]');
    if (convenioField) {
      const current = preview?.filters?.convenio_code || convenioField.value || "";
      const convenios = [...new Set((state.exams || []).map((exam) => String(exam.convenio_code || "PARTICULAR").trim().toUpperCase() || "PARTICULAR"))].sort();
      convenioField.innerHTML = `<option value="">Todos</option>${convenios.map((code) => {
        const label = code === "PARTICULAR" ? "Particular" : code.replace(/_/g, " ");
        return `<option value="${escapeHtml(code)}" ${code === current ? "selected" : ""}>${escapeHtml(label)}</option>`;
      }).join("")}`;
      convenioField.value = current;
    }
    if (patientField) {
      const current = preview?.filters?.patient_id ? String(preview.filters.patient_id) : patientField.value || "";
      patientField.innerHTML = `<option value="">Todos</option>${state.patients.map((item) => {
        const label = `${item.full_name}${item.cpf ? ` • CPF ${item.cpf}` : ""}`;
        return `<option value="${escapeHtml(item.id)}" ${String(item.id) === current ? "selected" : ""}>${escapeHtml(label)}</option>`;
      }).join("")}`;
      patientField.value = current;
    }
  }

  const reportDescription = document.getElementById("reportDescription");
  if (reportDescription) {
    reportDescription.innerHTML = `
      <strong>${escapeHtml(config.label)}</strong>
      ${escapeHtml(preview ? `• ${preview.description}` : `• ${config.description}`)}
      ${preview?.filters?.summary_label ? `<br/><small>${escapeHtml(preview.filters.summary_label)}</small>` : ""}
    `;
  }

  const summaryCards = document.getElementById("reportSummary");
  if (summaryCards) {
    summaryCards.innerHTML = [
      htmlMetric("Exames", summary.total_exams || 0),
      htmlMetric("Pagos", `${summary.paid_exams || 0} • ${money(summary.paid_value || 0)}`),
      htmlMetric("Em aberto", `${summary.open_exams || 0} • ${money(summary.open_value || 0)}`),
      htmlMetric("Valor total", money(summary.total_value || 0)),
      summary.commission_value !== null && summary.commission_value !== undefined
        ? htmlMetric("Comissão", money(summary.commission_value || 0), `Pagos: ${money(summary.paid_commission_value || 0)} • Em aberto: ${money(summary.open_commission_value || 0)}`)
        : "",
    ].join("");
  }

  const breakdownRows = preview?.grouped?.length ? preview.grouped : (reportType === "financeiro" ? (finance.payment_methods || []).map((item) => ({
    label: paymentMethodLabel(item.payment_method),
    total_exams: item.total_invoices || 0,
    total_value: item.total_value || 0,
    paid_exams: item.total_invoices || 0,
    paid_value: item.total_value || 0,
    open_exams: 0,
    open_value: 0,
  })) : []);
  const breakdownEl = document.getElementById("reportBreakdown");
  if (breakdownEl) {
    const isCommissionReport = preview?.report_type === "comissao_tecnico" || reportType === "comissao_tecnico";
    breakdownEl.innerHTML = breakdownRows.length ? `
      <table>
        <thead>
          <tr>
            <th>${escapeHtml(preview?.group_label || "Forma de pagamento")}</th>
            <th>Exames</th>
            <th>Pagos</th>
            <th>Em aberto</th>
            <th>Valor</th>
            ${isCommissionReport ? "<th>Valor fixo</th><th>Comissão</th>" : ""}
          </tr>
        </thead>
        <tbody>
          ${breakdownRows.map((row) => `
            <tr>
              <td>${escapeHtml(row.label)}</td>
              <td>${escapeHtml(row.total_exams || 0)}</td>
              <td>${escapeHtml(row.paid_exams || 0)}</td>
              <td>${escapeHtml(row.open_exams || 0)}</td>
              <td>${escapeHtml(money(row.total_value || 0))}</td>
              ${isCommissionReport ? `<td>${escapeHtml(money(row.commission_amount ?? row.commission_rate ?? 0))}</td><td>${escapeHtml(money(row.commission_value || 0))}</td>` : ""}
            </tr>
          `).join("")}
        </tbody>
      </table>
    ` : htmlListRow("Sem dados", "Gere um relatório para ver o agrupamento.");
  }

  const detailRows = preview?.details || [];
  const detailsEl = document.getElementById("reportDetails");
  if (detailsEl) {
    const isCommissionReport = preview?.report_type === "comissao_tecnico" || reportType === "comissao_tecnico";
    detailsEl.innerHTML = detailRows.length ? `
      <table>
        <thead>
          <tr>
            <th>Data</th>
            <th>Paciente</th>
            <th>Procedimento</th>
            <th>Convênio</th>
            <th>Status</th>
            <th>Forma</th>
            <th>Valor</th>
            ${isCommissionReport ? "<th>Valor fixo</th><th>Comissão</th><th>Cálculo</th>" : ""}
          </tr>
        </thead>
        <tbody>
          ${detailRows.map((row) => `
            <tr>
              <td>${escapeHtml(dateTimeLabel(row.report_at))}</td>
              <td>${escapeHtml(row.patient_name || "-")}</td>
              <td>${escapeHtml(row.procedure_name || "-")}</td>
              <td>${escapeHtml(row.convenio_code || "-")}</td>
              <td>${statusPill(row.invoice_status_label || row.invoice_status || "-")}</td>
              <td>${escapeHtml(row.payment_method || "-")}</td>
              <td>${escapeHtml(money(row.net_amount || 0))}</td>
              ${isCommissionReport ? `
                <td>${escapeHtml(money(row.commission_amount ?? row.commission_rate ?? 0))}</td>
                <td>${escapeHtml(money(row.commission_value || 0))}</td>
                <td>${escapeHtml(row.commission_formula || "-")}</td>
              ` : ""}
            </tr>
          `).join("")}
        </tbody>
      </table>
    ` : htmlListRow("Sem detalhes", "Gere o PDF para carregar os dados do periodo.");
  }
}

function renderWorklist() {
  const canEditExam = Boolean(state.adminUnlocked);
  document.getElementById("localWorklist").innerHTML = `<table><thead><tr><th>Paciente</th><th>Procedimento</th><th>Agenda</th><th>MWL</th><th>Movimento</th><th>Acoes</th></tr></thead><tbody>${
    (state.worklist.local_exams || []).map((exam) => `
      <tr>
        <td>${escapeHtml(exam.patient_name)}<br/><small>${escapeHtml(exam.accession_number)}</small></td>
        <td>${escapeHtml(exam.procedure_name)}</td>
        <td>${escapeHtml(dateTimeLabel(exam.scheduled_at))}</td>
        <td>${statusPill(exam.worklist_status_label || exam.worklist_status)}</td>
        <td>${exam.manual_transition_allowed ? "Livre" : escapeHtml(exam.manual_transition_reason || "Travado")}</td>
        <td>
          ${canSyncWorklist(exam) ? `<button class="mini publish-worklist" data-id="${exam.id}">${worklistSyncLabel(exam)}</button>` : ""}
          ${exam.local_worklist_active ? `<button class="mini danger remove-worklist" data-id="${exam.id}">Retirar</button>` : ""}
          ${canEditExam ? `<button class="mini danger remove-exam" data-id="${exam.id}">Remover</button>` : ""}
        </td>
      </tr>
    `).join("")
  }</tbody></table>`;

  document.getElementById("pacsWorklist").innerHTML = `<table><thead><tr><th>Accession</th><th>Paciente</th><th>Modalidade</th><th>Status SCP</th><th>Data</th><th>Estacao</th></tr></thead><tbody>${
    (state.worklist.items || []).map((item) => `
      <tr>
        <td>${escapeHtml(item.accessionnumber)}</td>
        <td>${escapeHtml(item.patientname || "-")}</td>
        <td>${escapeHtml(item.modality || "-")}</td>
        <td>${statusPill(item.spsstatus || "-")}</td>
        <td>${escapeHtml(item.spsdate || "-")}</td>
        <td>${escapeHtml(item.scheduledstation || "-")}</td>
      </tr>
    `).join("")
  }</tbody></table>`;
}

function renderSidebarStatus() {
  const storage = state.storage || {};
  const integrations = state.integrationStatus || {};
  const config = state.integrationConfig || {};
  const publicUrl = config.web?.public_url || window.location.origin || "-";
  const runtimeInfo = document.getElementById("configRuntimeInfo");
  if (runtimeInfo) {
    runtimeInfo.innerHTML = [
      htmlMetric("Departamento", currentOperator()?.name || state.currentDepartmentName || "-"),
      htmlMetric("Acesso admin", state.adminUnlocked ? "Liberado" : "Bloqueado"),
      htmlMetric("PACS Web", publicUrl),
      htmlMetric("Banco", integrations.database?.database || config.database?.database || "-"),
      htmlMetric("DICOM AE", `${config.pacs?.effective_ae_title || storage.pacs_ae_title || "-"}:${config.pacs?.effective_port || storage.dicom_port || "-"}`),
      htmlMetric("MWL AE", `${config.worklist?.effective_ae_title || storage.worklist_ae_title || "-"}:${config.worklist?.effective_port || storage.worklist_port || "-"}`),
      htmlMetric("Imagebox", storage.imagebox_path || "-"),
    ].join("");
  }

  const connectionInfo = document.getElementById("configConnectionInfo");
  if (connectionInfo) {
    connectionInfo.innerHTML = [
      `<div class="config-note"><strong>Status dos servicos</strong> ${escapeHtml(integrations.external_enabled ? "Modo misto/local + externo" : "Operacao local")}</div>`,
      statusLine("Banco", integrations.database, true),
      statusLine("PACS", integrations.pacs),
      statusLine("Worklist", integrations.worklist),
    ].join("");
  }
}

function renderStorage() {
  const storage = state.storage || {};
  const backups = state.backups || { database: [], images: [], backup_root: "" };
  const integrations = state.integrationStatus || {};
  document.getElementById("storageCards").innerHTML = [
    htmlCard("Disco total", `${storage.disk_total_gb || 0} GB`),
    htmlCard("Disco usado", `${storage.disk_used_gb || 0} GB`, `${storage.disk_used_percent || 0}%`),
    htmlCard("Livre", `${storage.disk_free_gb || 0} GB`),
    htmlCard("Imagebox", `${storage.imagebox_size_gb || 0} GB`, storage.imagebox_exists ? "Ativo" : "Nao encontrado"),
  ].join("");

  document.getElementById("storageDetails").innerHTML = [
    htmlMetric("Path", storage.imagebox_path || "-"),
    htmlMetric("Runtime", storage.runtime_root || "-"),
    htmlMetric("Studies", storage.study_count || 0),
    htmlMetric("Series", storage.series_count || 0),
    htmlMetric("Objects", storage.object_count || 0),
    htmlMetric("PACS efetivo", endpointLabel(integrations.pacs)),
    htmlMetric("MWL efetiva", endpointLabel(integrations.worklist)),
    htmlMetric("Banco ativo", endpointLabel(integrations.database, true)),
    htmlMetric("Modo PACS", modeLabel(integrations.pacs?.mode)),
    htmlMetric("Modo Worklist", modeLabel(integrations.worklist?.mode)),
  ].join("");

  document.getElementById("backupCards").innerHTML = [
    htmlCard("Backups banco", backups.database?.length || 0, dateTimeLabel(backups.database?.[0]?.created_at)),
    htmlCard("Backups imagens", backups.images?.length || 0, dateTimeLabel(backups.images?.[0]?.created_at)),
    htmlCard("Estrategia DB", backups.database_strategy || "-", backups.backup_root || "-"),
  ].join("");

  document.getElementById("backupDetails").innerHTML = [
    htmlMetric("Diretorio", backups.backup_root || "-"),
    htmlMetric("Ultimo DB", dateTimeLabel(backups.database?.[0]?.created_at)),
    htmlMetric("Ultimas imagens", dateTimeLabel(backups.images?.[0]?.created_at)),
    htmlMetric("Imagebox", storage.imagebox_path || "-"),
    htmlMetric("Anexos", `${storage.runtime_root || "-"} / exam_attachments`),
    htmlMetric("Runtime", storage.runtime_root || "-"),
  ].join("");

  const renderBackupRows = (items, emptyTitle, emptySubtitle) => items.map((item) => `
    <div class="list-row">
      <strong>${escapeHtml(item.filename)}</strong>
      <span>${escapeHtml(`${dateTimeLabel(item.created_at)} • ${item.strategy || item.kind || "-"}`)}</span>
      <small>${escapeHtml(formatFileSize(item.file_size_bytes || 0))}${item.warning ? ` • ${escapeHtml(item.warning)}` : ""}</small>
      <div class="actions">
        <a class="mini" href="${escapeHtml(item.download_path || "#")}" target="_blank" rel="noreferrer">Baixar</a>
      </div>
    </div>
  `).join("") || htmlListRow(emptyTitle, emptySubtitle);

  document.getElementById("databaseBackupList").innerHTML = renderBackupRows(
    backups.database || [],
    "Sem backup do banco",
    "Gere um backup antes de enviar para GitHub ou publicar no Render.",
  );
  document.getElementById("imagesBackupList").innerHTML = renderBackupRows(
    backups.images || [],
    "Sem backup das imagens",
    "Gere um pacote das imagens e anexos antes do deploy.",
  );
}

function renderConfig() {
  const config = state.integrationConfig || {};
  const status = state.integrationStatus || {};
  fillForm("integrationConfigForm", {
    pacs_mode: config.pacs?.mode || "local",
    pacs_host: config.pacs?.host || "",
    pacs_port: config.pacs?.effective_port || config.pacs?.port || "",
    pacs_ae_title: config.pacs?.effective_ae_title || config.pacs?.ae_title || "",
    worklist_mode: config.worklist?.mode || "local",
    worklist_host: config.worklist?.host || "",
    worklist_port: config.worklist?.effective_port || config.worklist?.port || "",
    worklist_ae_title: config.worklist?.effective_ae_title || config.worklist?.ae_title || "",
    public_url: config.web?.public_url || window.location.origin || "",
  });

  document.getElementById("configStatusCards").innerHTML = [
    htmlCard("Banco", status.database?.ok ? "Online" : "Falha", modeLabel(status.database?.mode)),
    htmlCard("PACS", status.pacs?.ok ? "Online" : "Falha", modeLabel(status.pacs?.mode)),
    htmlCard("Worklist", status.worklist?.ok ? "Online" : "Falha", modeLabel(status.worklist?.mode)),
  ].join("");

  document.getElementById("configDbInfo").innerHTML = [
    htmlMetric("Host", status.database?.host || "-"),
    htmlMetric("Porta", status.database?.port || "-"),
    htmlMetric("Banco", status.database?.database || "-"),
    htmlMetric("Usuario", status.database?.user || "-"),
    htmlMetric("SSL", status.database?.sslmode || "padrao"),
    htmlMetric("Origem", status.database?.managed_via || "ambiente"),
  ].join("");

  document.getElementById("deployReadiness").innerHTML = [
    htmlListRow("Web local", "Use o `first_boot` ou `up.sh` para subir a interface HTTP.", status.database?.message || "Banco nao verificado."),
    htmlListRow("PostgreSQL local", endpointLabel(status.database, true), "Preencha `PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE` ou `DATABASE_URL`."),
    htmlListRow("PACS externo", endpointLabel(status.pacs), `${modeLabel(status.pacs?.mode)} | ${status.pacs?.message || "-"}`),
    htmlListRow("Worklist externa", endpointLabel(status.worklist), `${modeLabel(status.worklist?.mode)} | ${status.worklist?.message || "-"}`),
  ].join("");

  setConfigTab(ui.configTab || "integrations");
  renderSidebarStatus();
  renderPricingConfig();
  renderExamPricingOptions();
  syncConfigAccessState();
}

function renderPricingConfig() {
  const container = document.getElementById("pricingConfigEditor");
  if (!container) return;
  const removedCodes = new Set((ui.pricingRemovedCodes || []).map((item) => String(item).toUpperCase()));
  const removedItems = (pricingConvenios() || []).filter((item) => removedCodes.has(String(item.code || "").toUpperCase()));
  const convenios = [
    ...(pricingConvenios() || []).filter((item) => !removedCodes.has(String(item.code || "").toUpperCase())).map((item) => ({
      ...item,
      draft: false,
      draftId: item.code,
    })),
    ...(ui.pricingDrafts || []),
  ];
  if (!convenios.length) {
    container.innerHTML = htmlListRow("Sem convênios", "Aguarde o carregamento da configuração de preços.");
    return;
  }

  const removedHtml = removedItems.length
    ? `
      <div class="config-note">
        <strong>Convênios removidos</strong>
        <div class="stack-list">
          ${removedItems.map((item) => `
            <div class="list-row">
              <strong>${escapeHtml(item.name || item.code)}</strong>
              <span>${escapeHtml(item.code || "")}</span>
              <small>Será excluído ao salvar.</small>
              <div class="actions">
                <button class="ghost restore-pricing-convenio" type="button" data-pricing-code="${escapeHtml(item.code)}">Restaurar</button>
              </div>
            </div>
          `).join("")}
        </div>
      </div>
    `
    : "";

  container.innerHTML = `${removedHtml}${convenios.map((item) => {
    const cardKey = String(item.draftId || item.code || "").trim() || `card-${Math.random().toString(16).slice(2, 8)}`;
    const title = item.code ? `${item.name || item.code}` : "Novo convênio";
    return `
      <article class="pricing-card panel" data-pricing-card="${escapeHtml(cardKey)}" data-pricing-draft="${item.draft ? "true" : "false"}">
        <div class="panel-head">
          <h4>${escapeHtml(title)}</h4>
          <div class="actions">
            <span class="muted">${escapeHtml(item.code || "Novo")}</span>
            ${item.code && item.code !== "PARTICULAR" ? `<button class="ghost remove-pricing-convenio" type="button" data-pricing-code="${escapeHtml(item.code)}">Remover</button>` : ""}
          </div>
        </div>
        <div class="form-grid">
          <label><span>Código</span><input name="pricing_code_${cardKey}" value="${escapeHtml(item.code || "")}" placeholder="UNIMED" ${item.draft ? "" : "readonly"} /></label>
          <label class="span-2"><span>Nome</span><input name="pricing_name_${cardKey}" value="${escapeHtml(item.name || item.code || "")}" placeholder="Nome do convênio" /></label>
          <label><span>Comissão técnico (R$)</span><input type="number" step="0.01" min="0" name="pricing_${cardKey}_commission_amount" value="${escapeHtml(Number(item.commission_amount ?? item.commission_rate ?? (item.code === "PARTICULAR" ? 10 : 6)).toFixed(2))}" /></label>
          <label><span>1 incidência</span><input type="number" step="0.01" min="0" name="pricing_${cardKey}_1" value="${escapeHtml(Number(item.prices?.["1"] || 0).toFixed(2))}" /></label>
          <label><span>2 incidências</span><input type="number" step="0.01" min="0" name="pricing_${cardKey}_2" value="${escapeHtml(Number(item.prices?.["2"] || 0).toFixed(2))}" /></label>
          <label><span>3 incidências</span><input type="number" step="0.01" min="0" name="pricing_${cardKey}_3" value="${escapeHtml(Number(item.prices?.["3"] || 0).toFixed(2))}" /></label>
          ${item.draft ? `<div class="actions span-2"><button class="ghost remove-pricing-draft" type="button" data-pricing-card="${escapeHtml(cardKey)}">Remover rascunho</button></div>` : ""}
        </div>
      </article>
    `;
  }).join("")}`;
}

function addPricingConvenioDraft() {
  ui.pricingDrafts = [...(ui.pricingDrafts || []), makePricingDraft()];
  renderPricingConfig();
  window.requestAnimationFrame(() => {
    const lastDraft = ui.pricingDrafts[ui.pricingDrafts.length - 1];
    if (lastDraft) {
      document.querySelector(`[name="pricing_code_${lastDraft.draftId}"]`)?.focus();
    }
  });
}

function removePricingConvenioDraft(cardKey) {
  ui.pricingDrafts = (ui.pricingDrafts || []).filter((item) => String(item.draftId) !== String(cardKey));
  renderPricingConfig();
}

function renderDeployAutomationHints() {
  const container = document.getElementById("deployHints");
  if (!container) return;
  container.innerHTML = [
    htmlListRow("GitHub Actions", "Deploy automatico por branch (`develop` e `main`).", "Secrets: `RENDER_DEPLOY_HOOK_HOMOLOG` e `RENDER_DEPLOY_HOOK_PRODUCTION`."),
    htmlListRow("Backups antes do deploy", "Use a aba Storage para gerar backup do banco e das imagens.", "Arquivos ficam em `runtime/backups` e podem ser baixados pela interface."),
  ].join("");
}

function syncConfigAccessState() {
  const locked = !state.adminUnlocked;

  [document.getElementById("integrationConfigForm"), document.getElementById("panelConfigForm"), document.getElementById("procedureForm"), document.getElementById("pricingConfigForm")].forEach((form) => {
    if (!form) return;
    form.querySelectorAll("input, select, textarea, button").forEach((field) => {
      field.disabled = locked;
    });
  });
}

function renderReporting() {
  const queue = [...state.exams].sort((left, right) => {
    const leftDate = new Date(left.scheduled_at || left.created_at || 0).getTime();
    const rightDate = new Date(right.scheduled_at || right.created_at || 0).getTime();
    return rightDate - leftDate;
  });

  document.getElementById("reportingQueue").innerHTML = `<table><thead><tr><th>Paciente</th><th>Procedimento</th><th>Fluxo</th><th>PACS</th><th>Acoes</th></tr></thead><tbody>${
    queue.map((exam) => `
      <tr>
        <td>${escapeHtml(exam.patient_name)}<br/><small>${escapeHtml(exam.accession_number)}</small></td>
        <td>${escapeHtml(exam.procedure_name)}<br/><small>${escapeHtml(dateTimeLabel(exam.scheduled_at))}</small></td>
        <td>${statusPill(exam.workflow_label || exam.workflow_stage)}</td>
        <td>${statusPill(exam.live_status || "-")}</td>
        <td>
          <button class="mini open-workspace" data-id="${exam.id}">Abrir</button>
          <a class="mini" href="/viewer/exams/${exam.id}#viewerShareCard" target="_blank" rel="noreferrer">Viewer / Compartilhar</a>
        </td>
      </tr>
    `).join("")
  }</tbody></table>`;

  const workspace = state.reportingWorkspace;
  if (!workspace?.exam) {
    document.getElementById("reportingSummary").innerHTML = htmlListRow("Nenhum exame aberto", "Escolha um exame para laudo e visualizacao.");
    document.getElementById("reportingViewerStage").innerHTML = `<div class="viewer-empty"><strong>Viewer aguardando selecao</strong><span>Abra um exame e anexe uma imagem ou consulte os objetos DICOM.</span></div>`;
    document.getElementById("reportingThumbs").innerHTML = "";
    document.getElementById("reportingDicomObjects").innerHTML = "";
    document.getElementById("reportingAttachments").innerHTML = htmlListRow("Sem anexos", "Nenhum exame selecionado.");
    fillForm("reportForm", { exam_id: "", doctor_name: "", status: "draft", title: "", body: "", impression: "" });
    document.querySelector('#attachmentForm [name="exam_id"]').value = "";
    return;
  }

  const report = workspace.report || {};
  const pacs = workspace.pacs || { study: null, series: [], instances: [] };
  const attachments = workspace.attachments || [];
  fillForm("reportForm", {
    exam_id: workspace.exam.id,
    doctor_name: report.doctor_name || "",
    status: report.status || "draft",
    title: report.title || "",
    body: report.body || "",
    impression: report.impression || "",
  });
  document.querySelector('#attachmentForm [name="exam_id"]').value = String(workspace.exam.id);

  document.getElementById("reportingSummary").innerHTML = [
    htmlMetric("Paciente", workspace.exam.patient_name || "-"),
    htmlMetric("Procedimento", workspace.exam.procedure_name || "-"),
    htmlMetric("Status do laudo", report.status || "draft"),
    htmlMetric("Objetos DICOM", pacs.instances?.length || 0),
    htmlMetric("Series", pacs.series?.length || 0),
    htmlMetric("Imagens anexadas", attachments.length || 0),
  ].join("");

  const imageAttachments = attachments.filter((item) => item.is_image);
  if (!state.selectedViewerAsset && imageAttachments[0]) {
    state.selectedViewerAsset = `/media/exam-attachments/${imageAttachments[0].id}`;
    state.selectedViewerType = "image";
    state.selectedViewerLabel = imageAttachments[0].original_name || "Imagem do exame";
  }
  if (!imageAttachments.some((item) => `/media/exam-attachments/${item.id}` === state.selectedViewerAsset)) {
    state.selectedViewerAsset = imageAttachments[0] ? `/media/exam-attachments/${imageAttachments[0].id}` : "";
    state.selectedViewerType = imageAttachments[0] ? "image" : "empty";
    state.selectedViewerLabel = imageAttachments[0]?.original_name || "";
  }

  document.getElementById("reportingViewerStage").innerHTML = state.selectedViewerAsset
    ? `
      <div class="viewer-frame">
        <div class="viewer-frame-head">
          <strong>${escapeHtml(state.selectedViewerLabel || "Imagem do exame")}</strong>
          <a class="mini" href="${escapeHtml(state.selectedViewerAsset)}" target="_blank" rel="noreferrer">Abrir em aba</a>
        </div>
        <img src="${escapeHtml(state.selectedViewerAsset)}" alt="${escapeHtml(state.selectedViewerLabel || "Imagem do exame")}" />
      </div>
    `
    : `<div class="viewer-empty"><strong>Sem preview web</strong><span>Anexe uma imagem JPG/PNG/WEBP ao exame para visualizar aqui. Os objetos DICOM continuam disponiveis abaixo para download.</span></div>`;

  document.getElementById("reportingThumbs").innerHTML = imageAttachments.map((item) => {
    const assetUrl = `/media/exam-attachments/${item.id}`;
    const active = assetUrl === state.selectedViewerAsset;
    return `
      <button class="viewer-thumb ${active ? "active" : ""}" type="button" data-view-url="${assetUrl}" data-view-type="image" data-view-label="${escapeHtml(item.original_name || item.stored_name)}">
        <img src="${assetUrl}" alt="${escapeHtml(item.original_name || item.stored_name)}" />
        <span>${escapeHtml(item.original_name || item.stored_name)}</span>
      </button>
    `;
  }).join("");

  document.getElementById("reportingAttachments").innerHTML = attachments.map((item) => htmlListRow(
    item.original_name || item.stored_name,
    item.mime_type || item.kind || "arquivo",
    `${dateTimeLabel(item.created_at)} • ${item.file_size || 0} bytes`,
  )).join("") || htmlListRow("Sem anexos web", "Envie JPG, PNG, WEBP, GIF, BMP ou DICOM.");

  document.getElementById("reportingDicomObjects").innerHTML = `<table><thead><tr><th>Instancia</th><th>Serie</th><th>Recebido</th><th>Acoes</th></tr></thead><tbody>${
    (pacs.instances || []).map((instance) => `
      <tr>
        <td>${escapeHtml(instance.sopinstanceuid)}<br/><small>${escapeHtml(instance.sopclassuid || "-")}</small></td>
        <td>${escapeHtml(instance.imagenumber || "-")}</td>
        <td>${escapeHtml(dateTimeLabel(instance.receivedat))}</td>
        <td><a class="mini" href="/media/pacs/objects/${encodeURIComponent(instance.sopinstanceuid)}?download=1" target="_blank" rel="noreferrer">Baixar DICOM</a></td>
      </tr>
    `).join("")
  }</tbody></table>`;
}

function kanbanCardsForColumn(items) {
  const cards = [];
  const orderGroups = new Map();
  (items || []).forEach((exam) => {
    if (!exam.order_id) {
      cards.push({ type: "exam", exam, exams: [exam] });
      return;
    }
    const key = `${exam.order_id}:${exam.workflow_stage || ""}`;
    if (!orderGroups.has(key)) {
      orderGroups.set(key, {
        type: "order",
        order_id: exam.order_id,
        exam,
        exams: [],
      });
      cards.push(orderGroups.get(key));
    }
    orderGroups.get(key).exams.push(exam);
  });
  return cards;
}

function renderKanbanCard(card) {
  const exam = card.exam;
  const exams = card.exams || [exam];
  const isOrder = card.type === "order";
  const allAllowed = exams.every((item) => item.manual_transition_allowed);
  const canDeleteKanbanCard = state.adminUnlocked || ["technician", "tecnico"].includes(state.userRole);
  const procedureLabel = isOrder
    ? exams.map((item) => item.procedure_name).filter(Boolean).join(", ")
    : exam.procedure_name;
  const orderLine = isOrder
    ? `<div class="kanban-order-line"><span>Ordem #${escapeHtml(exam.order_id)} · ${exams.length} exames</span><span>${escapeHtml(money(exam.order_net_amount || 0))}</span><small>Desconto ${escapeHtml(money(exam.order_discount || 0))}</small></div>`
    : (exam.order_id ? `<div class="kanban-order-line"><span>Ordem #${escapeHtml(exam.order_id)}</span><span>${escapeHtml(money(exam.order_net_amount || 0))}</span><small>Desconto ${escapeHtml(money(exam.order_discount || 0))}</small></div>` : "");
  return `
    <article class="kanban-card kanban-card-clickable ${allAllowed ? "" : "locked"}" draggable="${allAllowed ? "true" : "false"}" data-id="${exam.id}" data-exam-ids="${escapeHtml(exams.map((item) => item.id).join(","))}" data-order-id="${escapeHtml(exam.order_id || "")}">
      <strong>${escapeHtml(exam.patient_name)}</strong>
      <span>${escapeHtml(procedureLabel)}</span>
      ${orderLine}
      <div class="kanban-meta">
        <span>${escapeHtml(exam.ticket_number || "-")}</span>
        <span>${escapeHtml(exam.worklist_status_label || "-")}</span>
        <span>${escapeHtml(exam.queue_status || "-")}</span>
        <span>${escapeHtml(dateTimeLabel(exam.scheduled_at))}</span>
      </div>
      <div class="kanban-card-actions">
        <button class="mini" type="button" data-open-exam-dialog="${exam.id}">Abrir</button>
        ${allAllowed ? `<button class="mini" type="button" data-exam-move="${exam.id}" data-exam-ids="${escapeHtml(exams.map((item) => item.id).join(","))}" data-direction="prev">←</button><button class="mini" type="button" data-exam-move="${exam.id}" data-exam-ids="${escapeHtml(exams.map((item) => item.id).join(","))}" data-direction="next">→</button>` : ""}
        ${canDeleteKanbanCard ? (isOrder ? `<button class="mini danger" type="button" data-delete-order="${exam.order_id}">Excluir</button>` : `<button class="mini danger" type="button" data-delete-exam="${exam.id}">Excluir</button>`) : ""}
      </div>
      ${allAllowed ? "" : `<small>${escapeHtml(exam.manual_transition_reason || "")}</small>`}
    </article>
  `;
}

function renderKanban() {
  document.getElementById("kanbanBoard").innerHTML = (state.kanban?.stages || []).map((column) => `
    <div class="kanban-column" data-stage="${column.key}">
      <h4><span>${escapeHtml(column.label)}</span><span>${escapeHtml(column.count || 0)}</span></h4>
      ${kanbanCardsForColumn(column.items || []).map(renderKanbanCard).join("")}
    </div>
  `).join("");
}

function renderOperators() {
  const departments = (state.departments || []).filter((item) => item.active !== false);
  state.currentDepartmentName = currentOperator()?.name || state.currentDepartmentName || departments[0]?.name || "";
  const departmentLabel = document.getElementById("currentDepartmentLabel");
  if (departmentLabel) {
    departmentLabel.textContent = state.currentDepartmentName || "-";
  }

  const recipientOptions = departments.filter((item) => String(item.id) !== String(state.currentOperatorId));
  const summary = document.getElementById("chatSummary");
  if (summary) {
    summary.innerHTML = [
      htmlMetric("Departamentos", departments.length),
      htmlMetric("Nao lidas", (state.overview?.summary?.unread_messages || 0)),
      htmlMetric("Departamento atual", currentOperator()?.name || "-"),
    ].join("");
  }

  document.getElementById("chatContacts").innerHTML = recipientOptions.map((contact) => `
    <button class="chat-contact ${String(contact.id) === String(state.currentContactId) ? "active" : ""}" data-contact-id="${contact.id}" type="button">
      <strong>${escapeHtml(contact.name)}</strong>
      <span>${escapeHtml(contact.pending_messages ? `${contact.pending_messages} nao lida(s)` : "Sem pendencias")}</span>
      <small>${escapeHtml(contact.sector || contact.role || "-")}</small>
    </button>
  `).join("") || htmlListRow("Sem departamentos", "Cadastre os setores para habilitar o chat.");
}

function renderChatMessages() {
  const container = document.getElementById("chatMessages");
  container.innerHTML = (state.chatMessages || []).map((message) => {
    const mine = String(message.sender_operator_id) === String(state.currentOperatorId);
    return `
      <div class="chat-bubble ${mine ? "me" : "other"}">
        <strong>${escapeHtml(mine ? "Voce" : message.sender_name)}</strong>
        <span>${escapeHtml(message.body || "")}</span>
        <small>${escapeHtml(dateTimeLabel(message.created_at))}</small>
      </div>
    `;
  }).join("") || `<div class="list-row"><strong>Sem conversa ativa</strong><span>Escolha um contato para iniciar o chat interno.</span></div>`;
  container.scrollTop = container.scrollHeight;
}

function renderCommunication() {
  renderOperators();
  renderChatMessages();
}

function parseYoutubeEmbed(url) {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();
    let id = "";
    if (host.includes("youtu.be")) id = parsed.pathname.replace("/", "");
    if (host.includes("youtube.com")) id = parsed.searchParams.get("v") || parsed.pathname.split("/")[2] || "";
    if (!id) return "";
    return `https://www.youtube-nocookie.com/embed/${id}?autoplay=1&mute=1&controls=0&loop=1&playlist=${id}&rel=0&modestbranding=1`;
  } catch {
    return "";
  }
}

function applyPanelVideo() {
  const frame = document.getElementById("panelVideoFrame");
  const localVideo = document.getElementById("panelVideoLocal");
  const raw = String(state.panel?.config?.video_url || "").trim();
  const youtube = parseYoutubeEmbed(raw);
  frame.src = "";
  frame.style.display = "none";
  localVideo.pause();
  localVideo.removeAttribute("src");
  localVideo.style.display = "none";
  if (!raw) return;
  if (youtube) {
    frame.src = youtube;
    frame.style.display = "block";
    return;
  }
  localVideo.src = raw;
  localVideo.style.display = "block";
  localVideo.play().catch(() => {});
}

function announceCall(item) {
  if (!("speechSynthesis" in window) || !item) return;
  const text = `Paciente ${item.patient_name}, senha ${item.ticket_number}, dirigir-se a ${item.destination || "atendimento"}.`;
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = "pt-BR";
  utter.rate = 0.95;
  window.speechSynthesis.speak(utter);
}

function isPanelFullscreen() {
  return document.fullscreenElement === document.getElementById("callPanelScreen");
}

function showCurrentCallAlert(item, prefix = "Chamada atual") {
  if (!item) return;
  document.getElementById("currentCallAlertTime").textContent = `${prefix} - ${dateTimeLabel(item.created_at || item.called_at)}`;
  document.getElementById("currentCallAlertTitle").textContent = `Senha ${item.ticket_number} - ${item.patient_name}`;
  document.getElementById("currentCallAlertPlace").textContent = `Dirigir-se a ${item.destination || "atendimento"}`;
  const alert = document.getElementById("currentCallAlert");
  alert.classList.remove("show");
  void alert.offsetWidth;
  alert.classList.add("show");
}

function renderPanel() {
  const panel = state.panel || { config: {}, items: [], history: [], summary: {} };
  document.getElementById("panelDisplayTitle").textContent = panel.config?.title || "Painel de Chamadas";
  document.getElementById("panelDisplaySubtitle").textContent = panel.config?.subtitle || "Clinica de Radiologia";
  fillForm("panelConfigForm", {
    title: panel.config?.title || "",
    subtitle: panel.config?.subtitle || "",
    video_url: panel.config?.video_url || "",
    destinations: (panel.config?.destinations || []).join(", "),
    auto_announce: String(panel.config?.auto_announce !== false),
  });

  document.getElementById("panelSummary").innerHTML = [
    htmlCard("Aguardando", panel.summary?.waiting || 0),
    htmlCard("Chamados", panel.summary?.called || 0),
    htmlCard("Em atendimento", panel.summary?.in_service || 0),
    htmlCard("Finalizados", panel.summary?.done || 0),
  ].join("");

  const destinations = panel.config?.destinations || [];
  document.getElementById("panelQueueTable").innerHTML = `<table><thead><tr><th>Senha</th><th>Paciente</th><th>Exame</th><th>Status</th><th>Destino</th><th>Acoes</th></tr></thead><tbody>${
    (panel.items || []).map((item) => `
      <tr>
        <td>${escapeHtml(item.ticket_number)}</td>
        <td>${escapeHtml(item.patient_name)}</td>
        <td>${escapeHtml(item.procedure_name)}</td>
        <td>${statusPill(item.status)}</td>
        <td>
          <select class="inline-select" data-ticket-destination="${item.id}">
            ${destinations.map((destination) => `<option value="${escapeHtml(destination)}" ${destination === item.destination ? "selected" : ""}>${escapeHtml(destination)}</option>`).join("")}
          </select>
        </td>
        <td>
          <button class="mini call-ticket" data-id="${item.id}">Chamar</button>
          <button class="mini ticket-status" data-id="${item.id}" data-status="in_service">Atender</button>
          <button class="mini ticket-status" data-id="${item.id}" data-status="done">Finalizar</button>
        </td>
      </tr>
    `).join("")
  }</tbody></table>`;

  document.getElementById("panelHistory").innerHTML = (panel.history || [])
    .map((item) => htmlListRow(`Senha ${item.ticket_number} - ${item.patient_name}`, item.destination || "atendimento", `${dateTimeLabel(item.created_at)} • ${item.called_by_name}`))
    .join("") || htmlListRow("Sem chamadas", "O historico do painel aparece aqui.");

  const latest = panel.history?.[0];
  document.getElementById("lastCall").textContent = latest
    ? `Senha ${latest.ticket_number} - ${latest.patient_name} -> ${latest.destination || "atendimento"}`
    : "Nenhuma chamada realizada";
  document.getElementById("panelQueue").innerHTML = (panel.items || [])
    .filter((item) => item.status === "waiting")
    .slice(0, 6)
    .map((item) => `<li>Senha ${escapeHtml(item.ticket_number)} - ${escapeHtml(item.patient_name)}</li>`)
    .join("");
  document.getElementById("calledHistory").innerHTML = (panel.history || [])
    .slice(0, 8)
    .map((item) => `<li>${escapeHtml(dateTimeLabel(item.created_at))} - Senha ${escapeHtml(item.ticket_number)} (${escapeHtml(item.patient_name)}) -> ${escapeHtml(item.destination || "atendimento")}</li>`)
    .join("");

  applyPanelVideo();
  if (latest && latest.id !== ui.lastPanelAlertId) {
    ui.lastPanelAlertId = latest.id;
    showCurrentCallAlert(latest, "Ultima chamada");
  }
  if (latest && latest.id !== ui.lastPanelSpokenId && panel.config?.auto_announce !== false && (state.activeSection === "panel" || isPanelFullscreen())) {
    ui.lastPanelSpokenId = latest.id;
    announceCall(latest);
    showCurrentCallAlert(latest, "Chamada no painel");
  }
}

function renderAll() {
  renderSidebarStatus();
  renderDashboard();
  renderKanban();
  renderPatients();
  renderProcedures();
  renderBudget();
  renderExams();
  renderReports();
  renderReporting();
  renderFinance();
  renderCommunication();
  renderPanel();
  renderWorklist();
  renderStorage();
  renderConfig();
  renderDeployAutomationHints();
  renderExamDialog();
}

async function loadAll() {
  const [overview, kanban, patients, procedures, exams, examHistory, invoices, finance, worklist, storage, backups, integrationConfig, integrationStatus, pricingConfig, pricingOverrides, departments, panel] = await Promise.all([
    api("/api/overview"),
    api("/api/kanban"),
    api("/api/patients"),
    api("/api/procedures"),
    api("/api/exams"),
    api("/api/exams/history"),
    api("/api/finance/invoices"),
    api("/api/finance/overview"),
    api("/api/worklist"),
    api("/api/storage"),
    api("/api/backups"),
    api("/api/integrations/config"),
    api("/api/integrations/status"),
    api("/api/pricing/config"),
    api("/api/pricing/overrides"),
    api("/api/chat/departments"),
    api("/api/panel"),
  ]);
  state.overview = overview;
  state.kanban = kanban;
  state.patients = patients.items || [];
  state.procedures = procedures.items || [];
  state.exams = exams.items || [];
  state.examHistory = examHistory.items || [];
  state.invoices = invoices.items || [];
  state.finance = finance;
  state.worklist = worklist;
  state.storage = storage;
  state.backups = backups;
  state.integrationConfig = integrationConfig;
  state.integrationStatus = integrationStatus;
  state.pricingConfig = pricingConfig;
  state.pricingOverrides = pricingOverrides;
  state.departments = departments.items || [];
  state.panel = panel;

  const activeOperators = state.departments.filter((item) => item.active !== false);
  if (!activeOperators.some((item) => String(item.id) === String(state.currentOperatorId))) {
    state.currentOperatorId = activeOperators[0] ? String(activeOperators[0].id) : "";
  }
  state.currentDepartmentName = activeOperators.find((item) => String(item.id) === String(state.currentOperatorId))?.name || activeOperators[0]?.name || "";
  const availableContacts = activeOperators.filter((item) => String(item.id) !== String(state.currentOperatorId));
  if (!availableContacts.some((item) => String(item.id) === String(state.currentContactId))) {
    state.currentContactId = availableContacts[0] ? String(availableContacts[0].id) : "";
  }
  if (state.currentOperatorId && state.currentContactId) {
    await loadChatData();
  } else {
    state.chatMessages = [];
  }
  if (state.selectedWorkspaceExamId) {
    try {
      state.reportingWorkspace = await api(`/api/exams/${state.selectedWorkspaceExamId}/workspace`);
    } catch (error) {
      state.reportingWorkspace = null;
      state.selectedWorkspaceExamId = "";
      state.selectedViewerAsset = "";
      state.selectedViewerType = "image";
      state.selectedViewerLabel = "";
    }
  }
  renderAll();
}

async function refreshBackupData() {
  const [storage, backups] = await Promise.all([
    api("/api/storage"),
    api("/api/backups"),
  ]);
  state.storage = storage;
  state.backups = backups;
  renderStorage();
  renderSidebarStatus();
}

function setActiveSection(sectionName) {
  if (state.examDialog?.open) closeExamDialog();
  document.querySelectorAll(".nav-link").forEach((item) => item.classList.toggle("active", item.dataset.section === sectionName));
  document.querySelectorAll(".section").forEach((section) => section.classList.toggle("active", section.dataset.section === sectionName));
  state.activeSection = sectionName;
  if (state.activeSection === "exams") renderExams();
  if (state.activeSection === "panel") renderPanel();
  if (state.activeSection === "reports") renderReports();
  if (state.activeSection === "reporting") renderReporting();
  if (state.activeSection === "config") {
    renderConfig();
    renderDeployAutomationHints();
  }
}

async function openExamWorkspace(examId, switchSection = true) {
  const workspace = await api(`/api/exams/${examId}/workspace`);
  state.reportingWorkspace = workspace;
  state.selectedWorkspaceExamId = String(examId);
  const firstImage = (workspace.attachments || []).find((item) => item.is_image);
  state.selectedViewerAsset = firstImage ? `/media/exam-attachments/${firstImage.id}` : "";
  state.selectedViewerType = firstImage ? "image" : "empty";
  state.selectedViewerLabel = firstImage?.original_name || "";
  if (switchSection) setActiveSection("reporting");
  renderReporting();
}

async function refreshWorkflowData() {
  if (ui.workflowSyncInFlight || document.hidden) return { updated: 0, skipped: true };
  ui.workflowSyncInFlight = true;
  try {
    let syncResult = { updated: 0 };
    try {
      syncResult = await api("/api/exams/sync", { method: "POST" });
    } catch (error) {
      console.warn("Falha ao sincronizar fluxo automaticamente.", error);
    }

    const [overview, kanban, exams, examHistory, invoices, finance, worklist, storage] = await Promise.all([
      api("/api/overview"),
      api("/api/kanban"),
      api("/api/exams"),
      api("/api/exams/history"),
      api("/api/finance/invoices"),
      api("/api/finance/overview"),
      api("/api/worklist"),
      api("/api/storage"),
    ]);
    state.overview = overview;
    state.kanban = kanban;
    state.exams = exams.items || [];
    state.examHistory = examHistory.items || [];
    state.invoices = invoices.items || [];
    state.finance = finance;
    state.worklist = worklist;
    state.storage = storage;

    renderDashboard();
    renderKanban();
    renderExams();
    renderFinance();
    renderReports();
    renderReporting();
    renderWorklist();
    renderStorage();
    renderSidebarStatus();
    renderExamDialog();
    if (state.selectedWorkspaceExamId) {
      try {
        state.reportingWorkspace = await api(`/api/exams/${state.selectedWorkspaceExamId}/workspace`);
        renderReporting();
      } catch (error) {
        console.warn("Falha ao atualizar workspace do exame.", error);
      }
    }
    return syncResult;
  } finally {
    ui.workflowSyncInFlight = false;
  }
}

async function refreshPanelData() {
  state.panel = await api("/api/panel");
  renderPanel();
}

async function loadChatData() {
  if (!state.currentOperatorId || !state.currentContactId) {
    state.chatMessages = [];
    return;
  }
  const [conversation, departments, unread] = await Promise.all([
    api(`/api/chat/conversation?operator_id=${encodeURIComponent(state.currentOperatorId)}&contact_id=${encodeURIComponent(state.currentContactId)}`),
    api(`/api/chat/departments?operator_id=${encodeURIComponent(state.currentOperatorId)}`),
    api(`/api/chat/unread?operator_id=${encodeURIComponent(state.currentOperatorId)}`),
  ]);
  state.chatMessages = conversation.items || [];
  state.departments = (departments.items || []).map((operator) => ({
    ...operator,
    pending_messages: unread.counts?.[String(operator.id)] || 0,
  }));
  renderCommunication();
}

async function refreshUnreadChat() {
  if (!state.currentOperatorId) return;
  const [unread, departments] = await Promise.all([
    api(`/api/chat/unread?operator_id=${encodeURIComponent(state.currentOperatorId)}`),
    api(`/api/chat/departments?operator_id=${encodeURIComponent(state.currentOperatorId)}`),
  ]);
  state.departments = (departments.items || []).map((operator) => ({
    ...operator,
    pending_messages: unread.counts?.[String(operator.id)] || 0,
  }));
  renderCommunication();
}

async function saveWithMethod(formId, path, buildPayload) {
  const form = document.getElementById(formId);
  const payload = buildPayload(formToObject(form));
  const id = payload.id;
  delete payload.id;
  const method = id ? "PUT" : "POST";
  const url = id ? `${path}/${id}` : path;
  return api(url, { method, body: JSON.stringify(payload) });
}

function populatePatientForm(patient) {
  fillForm("patientForm", patient);
}

function populateProcedureForm(procedure) {
  fillForm("procedureForm", { ...procedure, active: String(Boolean(procedure.active)) });
}

function openProcedureEditor(procedure) {
  if (!procedure) return;
  populateProcedureForm(procedure);
  setExamWorkbenchTarget("form");
  renderExams();
  window.requestAnimationFrame(() => {
    document.getElementById("procedureForm")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

function populateExamForm(exam) {
  fillForm("examForm", {
    id: exam.id,
    patient_id: exam.patient_id,
    procedure_id: exam.procedure_id,
    convenio_code: exam.convenio_code || "PARTICULAR",
    incidences_count: String(exam.incidences_count || 1),
    modality: exam.modality || "",
    priority: exam.priority || "ROUTINE",
    referring_physician: exam.referring_physician || "",
    performing_physician: exam.performing_physician || "",
    workflow_stage: exam.workflow_stage || "draft",
    notes: exam.notes || "",
  });
  setCurrencyFieldValue(document.querySelector('#examForm [name="price"]'), exam.price || 0);
}

function populateExamDialogPatientForm(patient) {
  fillForm("examDialogPatientForm", {
    id: patient?.id || "",
    full_name: patient?.full_name || "",
    birth_date: patient?.birth_date || "",
    sex: patient?.sex || "",
    cpf: patient?.cpf || "",
    phone: patient?.phone || "",
    email: patient?.email || "",
    notes: patient?.notes || "",
  });
}

function selectedDialogPatient() {
  const exam = selectedDialogExam();
  if (!exam) return null;
  return state.patients.find((item) => String(item.id) === String(exam.patient_id)) || null;
}

function bindNavigation() {
  document.querySelectorAll(".nav-link").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.docsLink === "true") {
        window.open("/docs/index.html", "_blank", "noopener");
        return;
      }
      if (button.dataset.navToggle) {
        toggleNavGroup(button.dataset.navToggle);
        return;
      }
      if (button.dataset.configTab) {
        setConfigTab(button.dataset.configTab);
        setActiveSection("config");
        return;
      }
      if (!button.dataset.section) return;
      if (button.dataset.examsFocus) {
        state.examLookupFocus = true;
        setExamWorkbenchTarget("values");
      }
      setActiveSection(button.dataset.section);
    });
  });

  document.querySelectorAll("[data-config-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      setConfigTab(button.dataset.configTab);
      setActiveSection("config");
    });
  });
}

function bindKanban() {
  document.body.addEventListener("dragstart", (event) => {
    const card = event.target.closest(".kanban-card");
    if (!card) return;
    if (card.getAttribute("draggable") !== "true") {
      event.preventDefault();
      return;
    }
    card.classList.add("dragging");
    event.dataTransfer.setData("text/plain", card.dataset.examIds || card.dataset.id);
  });

  document.body.addEventListener("dragend", (event) => {
    const card = event.target.closest(".kanban-card");
    if (card) card.classList.remove("dragging");
    document.querySelectorAll(".kanban-column").forEach((col) => col.classList.remove("drag-over"));
  });

  document.body.addEventListener("dragover", (event) => {
    const column = event.target.closest(".kanban-column");
    if (!column) return;
    event.preventDefault();
    column.classList.add("drag-over");
  });

  document.body.addEventListener("dragleave", (event) => {
    const column = event.target.closest(".kanban-column");
    if (column) column.classList.remove("drag-over");
  });

  document.body.addEventListener("drop", async (event) => {
    const column = event.target.closest(".kanban-column");
    if (!column) return;
    event.preventDefault();
    column.classList.remove("drag-over");
    const examIds = parseExamIds(event.dataTransfer.getData("text/plain"));
    if (!examIds.length) return;
    try {
      await moveExamIdsToStage(examIds, column.dataset.stage);
      showFlash("Kanban atualizado.");
    } catch (error) {
      showFlash(error.message, true);
    }
  });
}

function bindForms() {
  document.getElementById("patientForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await saveWithMethod("patientForm", "/api/patients", (payload) => payload);
      resetManagedForm("patientForm");
      await loadAll();
      showFlash("Paciente salvo com sucesso.");
    } catch (error) {
      showFlash(error.message, true);
    }
  });

  document.getElementById("procedureForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.adminUnlocked) {
      showFlash("Desbloqueie a configuracao com a senha admin antes de salvar procedimento.", true);
      return;
    }
    try {
      await saveWithMethod("procedureForm", "/api/procedures", (payload) => ({ ...payload, active: payload.active === "true" }));
      resetManagedForm("procedureForm");
      await loadAll();
      showFlash("Procedimento salvo com sucesso.");
    } catch (error) {
      showFlash(error.message, true);
    }
  });

  document.getElementById("examForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const selectedPatientId = document.getElementById("examPatient")?.value || "";
    if (!selectedPatientId || !findPatientById(selectedPatientId)) {
      promptPatientRegistrationFromExam();
      return;
    }
    try {
      const saved = await saveWithMethod("examForm", "/api/exams", (payload) => ({
        ...payload,
        price: parseCurrencyBRL(payload.price),
      }));
      resetManagedForm("examForm");
      await loadAll();
      if (saved?.id) openExamDialog(saved, "launch");
      showFlash("Exame salvo com sucesso.");
    } catch (error) {
      showFlash(error.message, true);
    }
  });

  document.getElementById("budgetForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const payload = buildBudgetPayload();
      if (!payload.patient_id && !payload.patient_name) {
        showFlash("Digite o nome do paciente para gerar o orçamento.", true);
        return;
      }
      if (!payload.items.length) {
        showFlash("Adicione pelo menos um exame ao orçamento.", true);
        return;
      }
      const order = await api("/api/exam-orders", { method: "POST", body: JSON.stringify(payload) });
      resetBudgetForm();
      await loadAll();
      window.open(`/exam-orders/${order.id}.pdf`, "_blank", "noopener");
      setActiveSection("finance");
      showFlash(`Orçamento #${order.id} gerado com ${order.exam_count || payload.items.length} exames.`);
    } catch (error) {
      showFlash(error.message, true);
    }
  });

  const examPriceField = document.querySelector('#examForm [name="price"]');
  if (examPriceField) {
    examPriceField.addEventListener("input", () => maskCurrencyField(examPriceField));
    examPriceField.addEventListener("blur", () => setCurrencyFieldValue(examPriceField, parseCurrencyBRL(examPriceField.value)));
  }

  document.getElementById("examDialogPatientForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const currentExam = selectedDialogExam();
    const patient = selectedDialogPatient();
    try {
      const saved = await saveWithMethod("examDialogPatientForm", "/api/patients", (payload) => ({
        ...payload,
        id: patient ? payload.id : payload.id,
      }));
      populateExamDialogPatientForm(saved);
      await loadAll();
      const updatedExam = currentExam ? state.exams.find((item) => String(item.id) === String(currentExam.id)) || currentExam : null;
      if (updatedExam) {
        openExamDialog(updatedExam, "patient");
      } else {
        document.getElementById("examPatient").value = String(saved.id || "");
        setExamDialogTab("launch");
        renderExamDialog();
      }
      showFlash(updatedExam ? "Paciente salvo no popup." : "Paciente cadastrado e selecionado para o exame.");
    } catch (error) {
      showFlash(error.message, true);
    }
  });

  document.getElementById("reportForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = formToObject(event.currentTarget);
    if (!payload.exam_id) {
      showFlash("Abra um exame antes de salvar o laudo.", true);
      return;
    }
    try {
      state.reportingWorkspace = await api(`/api/exams/${payload.exam_id}/report`, {
        method: "PUT",
        body: JSON.stringify({
          doctor_name: payload.doctor_name,
          status: payload.status,
          title: payload.title,
          body: payload.body,
          impression: payload.impression,
        }),
      });
      state.selectedWorkspaceExamId = String(payload.exam_id);
      await loadAll();
      showFlash("Laudo salvo com sucesso.");
    } catch (error) {
      showFlash(error.message, true);
    }
  });

  document.getElementById("attachmentForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const examId = form.querySelector('[name="exam_id"]').value;
    const fileInput = form.querySelector('[name="file"]');
    if (!examId) {
      showFlash("Abra um exame antes de anexar imagem.", true);
      return;
    }
    if (!fileInput?.files?.length) {
      showFlash("Selecione um arquivo para anexar.", true);
      return;
    }
    try {
      const formData = new FormData();
      formData.append("file", fileInput.files[0]);
      state.reportingWorkspace = await api(`/api/exams/${examId}/attachments`, {
        method: "POST",
        body: formData,
      });
      state.selectedWorkspaceExamId = String(examId);
      fileInput.value = "";
      await loadAll();
      showFlash("Arquivo inserido no exame.");
    } catch (error) {
      showFlash(error.message, true);
    }
  });

  const reportCatalogEl = document.getElementById("reportCatalog");
  if (reportCatalogEl) {
    reportCatalogEl.addEventListener("click", (event) => {
      const button = event.target.closest("[data-report-type]");
      if (!button) return;
      state.reports.type = button.dataset.reportType || "financeiro";
      state.reports.preview = null;
      renderReports();
    });
  }

  const reportFilterForm = document.getElementById("reportFilterForm");
  if (reportFilterForm) {
    const periodModeField = reportFilterForm.querySelector('[name="period_mode"]');
    if (periodModeField) {
      periodModeField.addEventListener("change", () => setReportPeriodVisibility(periodModeField.value));
    }
    const resetButton = reportFilterForm.querySelector("[data-report-reset]");
    if (resetButton) {
      resetButton.addEventListener("click", () => {
        reportFilterForm.reset();
        const currentMonth = currentMonthInputValue();
        const currentDay = currentDateInputValue();
        reportFilterForm.querySelector('[name="period_mode"]').value = "month";
        reportFilterForm.querySelector('[name="period_month"]').value = currentMonth;
        reportFilterForm.querySelector('[name="period_date"]').value = currentDay;
        reportFilterForm.querySelector('[name="convenio_code"]').value = "";
        reportFilterForm.querySelector('[name="patient_id"]').value = "";
        state.reports.type = "financeiro";
        state.reports.preview = null;
        setReportPeriodVisibility("month");
        renderReports();
      });
    }
    reportFilterForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const submitButton = form.querySelector('button[type="submit"]');
      const originalLabel = submitButton?.textContent || "Gerar PDF";
      const { reportType, query } = buildReportQuery(form);
      const queryText = query.toString();
      const pdfUrl = `/reports/${encodeURIComponent(reportType)}.pdf?${queryText}`;
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = "Gerando...";
      }
      try {
        window.open(pdfUrl, "_blank", "noopener");
        state.reports.loading = true;
        state.reports.type = reportType;
        state.reports.preview = await api(`/api/reports/${encodeURIComponent(reportType)}?${queryText}`);
        renderReports();
        showFlash("Relatorio gerado com sucesso.");
      } catch (error) {
        showFlash(error.message, true);
      } finally {
        state.reports.loading = false;
        if (submitButton) {
          submitButton.disabled = false;
          submitButton.textContent = originalLabel;
        }
      }
    });
  }

  document.getElementById("chatForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.currentOperatorId || !state.currentContactId) return;
    const payload = formToObject(event.currentTarget);
    try {
      await api("/api/chat/messages", {
        method: "POST",
        body: JSON.stringify({
          sender_operator_id: Number(state.currentOperatorId),
          recipient_operator_id: Number(state.currentContactId),
          body: payload.body,
        }),
      });
      event.currentTarget.reset();
      await loadChatData();
      showFlash("Mensagem enviada.");
    } catch (error) {
      showFlash(error.message, true);
    }
  });

  document.getElementById("panelConfigForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.adminUnlocked) {
      showFlash("Desbloqueie a configuracao com a senha admin antes de salvar o painel.", true);
      return;
    }
    const payload = formToObject(event.currentTarget);
    try {
      await api("/api/panel/config", {
        method: "PUT",
        body: JSON.stringify({
          title: payload.title,
          subtitle: payload.subtitle,
          video_url: payload.video_url,
          destinations: payload.destinations,
          auto_announce: payload.auto_announce === "true",
        }),
      });
      await refreshPanelData();
      showFlash("Painel atualizado.");
    } catch (error) {
      showFlash(error.message, true);
    }
  });

  document.getElementById("pricingConfigForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.adminUnlocked) {
      showFlash("Desbloqueie a configuracao com a senha admin antes de salvar os valores.", true);
      return;
    }
    const payload = buildPricingConfigPayload(event.currentTarget);
    try {
      state.pricingConfig = await api("/api/pricing/config", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      ui.pricingDrafts = [];
      ui.pricingRemovedCodes = [];
      renderConfig();
      renderExams();
      renderExamDialog();
      showFlash("Valores por convenio salvos.");
    } catch (error) {
      showFlash(error.message, true);
    }
  });

  document.getElementById("integrationConfigForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.adminUnlocked) {
      showFlash("Desbloqueie a configuracao com a senha admin antes de salvar.", true);
      return;
    }
    const payload = formToObject(event.currentTarget);
    try {
      state.integrationConfig = await api("/api/integrations/config", {
        method: "PUT",
        body: JSON.stringify({
          pacs: {
            mode: payload.pacs_mode,
            host: payload.pacs_host,
            port: payload.pacs_port,
            ae_title: payload.pacs_ae_title,
          },
          worklist: {
            mode: payload.worklist_mode,
            host: payload.worklist_host,
            port: payload.worklist_port,
            ae_title: payload.worklist_ae_title,
          },
          web: {
            public_url: payload.public_url,
          },
        }),
      });
      state.integrationStatus = await api("/api/integrations/status");
      renderSidebarStatus();
      renderStorage();
      renderConfig();
      renderDeployAutomationHints();
      showFlash("Configuracao de integracao salva.");
    } catch (error) {
      showFlash(error.message, true);
    }
  });

  document.getElementById("runDatabaseBackup").addEventListener("click", async () => {
    try {
      const result = await api("/api/backups/database", { method: "POST" });
      await refreshBackupData();
      showFlash(`Backup do banco gerado: ${result.filename}`);
    } catch (error) {
      showFlash(error.message, true);
    }
  });

  document.getElementById("runImagesBackup").addEventListener("click", async () => {
    try {
      const result = await api("/api/backups/images", { method: "POST" });
      await refreshBackupData();
      showFlash(`Backup das imagens gerado: ${result.filename}`);
    } catch (error) {
      showFlash(error.message, true);
    }
  });

  document.getElementById("refreshAll").addEventListener("click", async () => {
    try {
      await loadAll();
      showFlash("Painel atualizado.");
    } catch (error) {
      showFlash(error.message, true);
    }
  });

  document.getElementById("syncPacs").addEventListener("click", async () => {
    try {
      const result = await api("/api/exams/sync", { method: "POST" });
      await loadAll();
      showFlash(`Sincronizacao concluida. ${result.updated} exame(s) atualizados.`);
    } catch (error) {
      showFlash(error.message, true);
    }
  });

  document.getElementById("panelFullscreenBtn").addEventListener("click", async () => {
    const screen = document.getElementById("callPanelScreen");
    if (document.fullscreenElement === screen) {
      await document.exitFullscreen();
    } else {
      await screen.requestFullscreen().catch(() => {});
    }
  });

  document.body.addEventListener("click", async (event) => {
    const target = event.target;

    const openExamDialogButton = target.closest("[data-open-exam-dialog]");
    if (openExamDialogButton) {
      const examId = String(openExamDialogButton.dataset.openExamDialog || "");
      if (examId && examId !== "new") {
        const exam = findExamById(examId);
        if (exam) openExamDialog(exam, "launch");
        else openExamDialog(null, "launch");
      } else {
        openExamDialog(null, "launch");
      }
      return;
    }

    const closeExamDialogButton = target.closest("[data-close-exam-dialog]");
    if (closeExamDialogButton) {
      closeExamDialog();
      return;
    }

    const examDialogTab = target.closest("[data-exam-dialog-tab]");
    if (examDialogTab) {
      const tab = examDialogTab.dataset.examDialogTab || "launch";
      const exam = selectedDialogExam();
      if (tab === "reporting" && exam) {
        try {
          await openExamWorkspace(exam.id, false);
        } catch (error) {
          console.warn("Falha ao carregar workspace do exame.", error);
        }
      }
      setExamDialogTab(tab);
      return;
    }

    const examWorkbenchButton = target.closest("[data-exam-workbench-target]");
    if (examWorkbenchButton) {
      const targetName = examWorkbenchButton.dataset.examWorkbenchTarget || "form";
      setExamWorkbenchTarget(targetName);
      renderExams();
      window.requestAnimationFrame(() => {
        if (targetName === "values") {
          document.getElementById("examLookupSearch")?.focus();
          document.getElementById("examLookupSearch")?.scrollIntoView({ behavior: "smooth", block: "center" });
        } else {
          document.getElementById("procedureForm")?.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
      return;
    }

    const addPricingConvenioButton = target.closest("[data-add-pricing-convenio]");
    if (addPricingConvenioButton) {
      addPricingConvenioDraft();
      return;
    }

    const removePricingConvenioButton = target.closest(".remove-pricing-convenio");
    if (removePricingConvenioButton) {
      removePricingConvenio(removePricingConvenioButton.dataset.pricingCode || "");
      return;
    }

    const restorePricingConvenioButton = target.closest(".restore-pricing-convenio");
    if (restorePricingConvenioButton) {
      restorePricingConvenio(restorePricingConvenioButton.dataset.pricingCode || "");
      return;
    }

    const addBudgetItemButton = target.closest("[data-add-budget-item]");
    if (addBudgetItemButton) {
      state.budgetItems.push(makeBudgetItem());
      renderBudget();
      return;
    }

    const removeBudgetItemButton = target.closest("[data-remove-budget-item]");
    if (removeBudgetItemButton) {
      state.budgetItems = state.budgetItems.filter((item) => item.draftId !== removeBudgetItemButton.dataset.removeBudgetItem);
      if (!state.budgetItems.length) state.budgetItems = [makeBudgetItem()];
      renderBudget();
      return;
    }

    const resetBudgetButton = target.closest("[data-reset-budget]");
    if (resetBudgetButton) {
      resetBudgetForm();
      return;
    }

    const removePricingDraftButton = target.closest(".remove-pricing-draft");
    if (removePricingDraftButton) {
      removePricingConvenioDraft(removePricingDraftButton.dataset.pricingCard || "");
      return;
    }

    const examPanelCall = target.closest("[data-exam-panel-call]");
    if (examPanelCall) {
      const exam = selectedDialogExam();
      if (!exam?.ticket_id) {
        showFlash("Abra um exame com senha gerada antes de chamar no painel.", true);
        return;
      }
      try {
        await api(`/api/panel/tickets/${exam.ticket_id}/call`, {
          method: "POST",
          body: JSON.stringify({
            operator_id: Number(state.currentOperatorId || 0),
            destination: document.getElementById("examDialogPanelDestination")?.value || exam.queue_destination || "",
          }),
        });
        await refreshPanelData();
        showFlash("Paciente chamado no painel.");
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const examPanelOpen = target.closest("[data-exam-panel-open]");
    if (examPanelOpen) {
      closeExamDialog();
      setActiveSection("panel");
      return;
    }

    const examFinanceMarkPaid = target.closest("[data-exam-finance-mark-paid]");
    if (examFinanceMarkPaid) {
      const exam = selectedDialogExam();
      const invoice = exam ? examInvoice(exam.id) : null;
      if (!invoice) {
        showFlash("Sem fatura para marcar pagamento.", true);
        return;
      }
      try {
        await api(`/api/finance/invoices/${invoice.id}/mark-paid`, {
          method: "POST",
          body: JSON.stringify({
            payment_method: normalizePaymentMethod(document.getElementById("examDialogPaymentMethod")?.value || "dinheiro"),
          }),
        });
        await loadAll();
        openExamDialog(findExamById(exam.id) || exam, "finance");
        showFlash("Fatura marcada como paga.");
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const examFinanceUndoPaid = target.closest("[data-exam-finance-undo-paid]");
    if (examFinanceUndoPaid) {
      const exam = selectedDialogExam();
      const invoice = exam ? examInvoice(exam.id) : null;
      if (!invoice) {
        showFlash("Sem fatura para desfazer pagamento.", true);
        return;
      }
      if (!window.confirm("Desfazer este pagamento e reabrir a fatura para correcao?")) return;
      try {
        await api(`/api/finance/invoices/${invoice.id}/reopen-payment`, { method: "POST" });
        await loadAll();
        openExamDialog(findExamById(exam.id) || exam, "finance");
        showFlash("Pagamento desfeito. Agora voce pode aplicar desconto ou corrigir o lancamento.");
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const orderDiscountButton = target.closest("[data-exam-order-apply-discount]");
    const orderAddItemButton = target.closest("[data-exam-order-add-item]");
    if (orderDiscountButton || orderAddItemButton) {
      const exam = selectedDialogExam();
      if (!exam) {
        showFlash("Abra um exame do kanban para atualizar a ordem.", true);
        return;
      }
      const procedureId = document.getElementById("examOrderProcedure")?.value || "";
      if (orderAddItemButton && !procedureId) {
        showFlash("Selecione um procedimento para incluir.", true);
        return;
      }
      try {
        const payload = {
          discount: parseCurrencyBRL(document.getElementById("examOrderDiscount")?.value || 0),
          procedure_id: orderAddItemButton ? Number(procedureId || 0) : 0,
          incidences_count: Number(document.getElementById("examOrderIncidences")?.value || 1),
          price: parseCurrencyBRL(document.getElementById("examOrderPrice")?.value || 0),
          convenio_code: exam.convenio_code || "PARTICULAR",
        };
        await api(`/api/exams/${exam.id}/order-items`, { method: "POST", body: JSON.stringify(payload) });
        await loadAll();
        openExamDialog(findExamById(exam.id) || exam, "finance");
        showFlash(orderAddItemButton ? "Exame incluído na ordem." : "Desconto aplicado.");
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const openSectionButton = target.closest("[data-open-section]");
    if (openSectionButton) {
      closeExamDialog();
      setActiveSection(openSectionButton.dataset.openSection);
      return;
    }

    const openPatientButton = target.closest("[data-open-selected-patient]");
    if (openPatientButton) {
      const patient = selectedDialogPatient();
      populateExamDialogPatientForm(patient);
      setExamDialogTab("patient");
      renderExamDialog();
      const patientForm = document.getElementById("examDialogPatientForm");
      if (patientForm) {
        patientForm.querySelector('[name="id"]').value = patient?.id || "";
      }
      return;
    }

    const newPatientButton = target.closest("[data-exam-patient-new]");
    if (newPatientButton) {
      populateExamDialogPatientForm(null);
      setExamDialogTab("patient");
      renderExamDialog();
      return;
    }

    const examWorklistAction = target.closest("[data-exam-worklist-action]");
    if (examWorklistAction) {
      const exam = selectedDialogExam();
      if (!exam) return;
      try {
        if (examWorklistAction.dataset.examWorklistAction === "publish") {
          await api(`/api/exams/${exam.id}/publish-worklist`, { method: "POST" });
        } else if (examWorklistAction.dataset.examWorklistAction === "remove") {
          await api(`/api/exams/${exam.id}/remove-worklist`, { method: "POST" });
        }
        await loadAll();
        openExamDialog(findExamById(exam.id) || exam, "worklist");
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const openExamWorkspaceButton = target.closest("[data-open-exam-workspace]");
    if (openExamWorkspaceButton) {
      const exam = selectedDialogExam();
      if (!exam) return;
      try {
        await openExamWorkspace(exam.id, true);
        showFlash("Workspace do exame aberto.");
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const openExamViewerButton = target.closest("[data-open-exam-viewer]");
    if (openExamViewerButton) {
      const exam = selectedDialogExam();
      if (!exam) return;
      try {
        await openExamWorkspace(exam.id, true);
        showFlash("Viewer do exame aberto.");
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const examWorklistMove = target.closest("[data-exam-worklist-move]");
    if (examWorklistMove) {
      const exam = selectedDialogExam();
      if (!exam) return;
      try {
        await moveExamStageByDelta(exam.id, examWorklistMove.dataset.examWorklistMove === "next" ? 1 : -1);
        const updated = findExamById(exam.id);
        if (updated) openExamDialog(updated, "worklist");
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const examMoveButton = target.closest("[data-exam-move]");
    if (examMoveButton) {
      try {
        await moveExamIdsByDelta(parseExamIds(examMoveButton.dataset.examIds || examMoveButton.dataset.examMove), examMoveButton.dataset.direction === "next" ? 1 : -1);
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const deleteExamButton = target.closest("[data-delete-exam]");
    if (deleteExamButton) {
      const confirmed = window.confirm("Remover este exame? A acao apaga anexos, espelho PACS e o cadastro do exame.");
      if (!confirmed) return;
      try {
        const result = await api(`/api/exams/${deleteExamButton.dataset.deleteExam}`, { method: "DELETE" });
        await loadAll();
        showFlash(`Exame removido${result.accession_number ? ` (${result.accession_number})` : ""}.`);
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const resetButton = target.closest("[data-reset-form]");
    if (resetButton) {
      if (resetButton.dataset.resetForm === "integrationConfigForm") {
        renderConfig();
        renderDeployAutomationHints();
      } else if (resetButton.dataset.resetForm === "pricingConfigForm") {
        ui.pricingDrafts = [];
        ui.pricingRemovedCodes = [];
        renderConfig();
      } else if (resetButton.dataset.resetForm === "panelConfigForm") {
        renderPanel();
      } else {
        resetManagedForm(resetButton.dataset.resetForm);
      }
      return;
    }

    const contactButton = target.closest("[data-contact-id]");
    if (contactButton) {
      state.currentContactId = contactButton.dataset.contactId;
      await loadChatData();
      return;
    }

    const publishButton = target.closest(".publish-worklist");
    if (publishButton) {
      try {
        const result = await api(`/api/exams/${publishButton.dataset.id}/publish-worklist`, { method: "POST" });
        await loadAll();
        showFlash(result.mirror_sync?.message || "Exame publicado na worklist local.");
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const removeWorklist = target.closest(".remove-worklist");
    if (removeWorklist) {
      try {
        const result = await api(`/api/exams/${removeWorklist.dataset.id}/remove-worklist`, { method: "POST" });
        await loadAll();
        showFlash(result.mirror_sync?.message || "Exame retirado da worklist.");
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const removeExam = target.closest(".remove-exam");
    if (removeExam) {
      const confirmed = window.confirm("Remover este exame teste? A ação apaga anexos, espelho PACS e o cadastro do exame.");
      if (!confirmed) return;
      try {
        const result = await api(`/api/exams/${removeExam.dataset.id}`, { method: "DELETE" });
        await loadAll();
        showFlash(`Exame removido${result.accession_number ? ` (${result.accession_number})` : ""}.`);
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const payButton = target.closest(".mark-paid");
    if (payButton) {
      try {
        const paymentMethod = normalizePaymentMethod(document.querySelector(`[data-payment-method="${payButton.dataset.id}"]`)?.value || "dinheiro");
        await api(`/api/finance/invoices/${payButton.dataset.id}/mark-paid`, {
          method: "POST",
          body: JSON.stringify({ payment_method: paymentMethod }),
        });
        await loadAll();
        showFlash("Fatura marcada como paga.");
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const undoPaidButton = target.closest(".undo-paid");
    if (undoPaidButton) {
      if (!window.confirm("Desfazer este pagamento e reabrir a fatura para correcao?")) return;
      try {
        await api(`/api/finance/invoices/${undoPaidButton.dataset.id}/reopen-payment`, { method: "POST" });
        await loadAll();
        showFlash("Pagamento desfeito. A fatura voltou para aberto.");
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const orderPdfButton = target.closest("[data-order-pdf]");
    if (orderPdfButton) {
      window.open(`/exam-orders/${orderPdfButton.dataset.orderPdf}.pdf`, "_blank", "noopener");
      return;
    }

    const deleteOrderButton = target.closest("[data-delete-order]");
    if (deleteOrderButton) {
      if (!window.confirm(`Excluir ordem/orçamento #${deleteOrderButton.dataset.deleteOrder}? A acao apaga os exames vinculados.`)) return;
      try {
        await api(`/api/exam-orders/${deleteOrderButton.dataset.deleteOrder}`, { method: "DELETE" });
        await loadAll();
        showFlash("Ordem/orçamento excluído.");
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const savePricingOverride = target.closest(".save-pricing-override");
    if (savePricingOverride) {
      const procedureId = savePricingOverride.dataset.procedureId;
      const convenioCode = savePricingOverride.dataset.convenioCode || "PARTICULAR";
      const row = savePricingOverride.closest("tr") || document.querySelector(`[data-pricing-row="${procedureId}"]`);
      if (!row) return;
      const prices = {
        1: row.querySelector('[data-pricing-incidence="1"]')?.value || 0,
        2: row.querySelector('[data-pricing-incidence="2"]')?.value || 0,
        3: row.querySelector('[data-pricing-incidence="3"]')?.value || 0,
      };
      try {
        await api("/api/pricing/overrides", {
          method: "PUT",
          body: JSON.stringify({
            convenio_code: convenioCode,
            procedure_id: Number(procedureId),
            prices,
          }),
        });
        await loadAll();
        showFlash("Valores individuais salvos.");
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const editPatient = target.closest(".edit-patient");
    if (editPatient) populatePatientForm(state.patients.find((item) => String(item.id) === editPatient.dataset.id));

    const editProcedure = target.closest(".edit-procedure");
    if (editProcedure) {
      openProcedureEditor(state.procedures.find((item) => String(item.id) === editProcedure.dataset.id));
      return;
    }

    const deleteProcedure = target.closest(".delete-procedure");
    if (deleteProcedure) {
      if (!state.adminUnlocked) {
        showFlash("Acesso admin necessario para excluir procedimento.", true);
        return;
      }
      const procedureName = deleteProcedure.dataset.name || "este procedimento";
      if (!window.confirm(`Excluir ${procedureName}? A exclusao so sera permitida se nao houver exame ou valor financeiro vinculado.`)) return;
      try {
        await api(`/api/procedures/${deleteProcedure.dataset.id}`, { method: "DELETE" });
        resetManagedForm("procedureForm");
        await loadAll();
        showFlash("Procedimento excluido com sucesso.");
      } catch (error) {
        showFlash(error.message, true);
      }
      return;
    }

    const editProcedureQuick = target.closest(".edit-procedure-quick");
    if (editProcedureQuick) {
      openProcedureEditor(state.procedures.find((item) => String(item.id) === editProcedureQuick.dataset.procedureId));
      return;
    }

    const editExam = target.closest(".edit-exam");
    if (editExam) {
      const exam = findExamById(editExam.dataset.id);
      if (exam) openExamDialog(exam, "launch");
      return;
    }

    const openWorkspace = target.closest(".open-workspace");
    if (openWorkspace) {
      try {
        await openExamWorkspace(openWorkspace.dataset.id);
      } catch (error) {
        showFlash(error.message, true);
      }
    }

    const viewerThumb = target.closest(".viewer-thumb");
    if (viewerThumb) {
      state.selectedViewerAsset = viewerThumb.dataset.viewUrl || "";
      state.selectedViewerType = viewerThumb.dataset.viewType || "image";
      state.selectedViewerLabel = viewerThumb.dataset.viewLabel || "";
      renderReporting();
    }

    const kanbanCard = target.closest(".kanban-card");
    if (kanbanCard && !target.closest("button, a, input, select, textarea")) {
      const exam = findExamById(kanbanCard.dataset.id);
      if (exam) openExamDialog(exam, "launch");
      return;
    }

    const callTicket = target.closest(".call-ticket");
    if (callTicket) {
      const select = document.querySelector(`[data-ticket-destination="${callTicket.dataset.id}"]`);
      try {
        await api(`/api/panel/tickets/${callTicket.dataset.id}/call`, {
          method: "POST",
          body: JSON.stringify({
            operator_id: Number(state.currentOperatorId || 0),
            destination: select?.value || "",
          }),
        });
        await refreshPanelData();
        showFlash("Chamada enviada ao painel.");
      } catch (error) {
        showFlash(error.message, true);
      }
    }

    const ticketStatus = target.closest(".ticket-status");
    if (ticketStatus) {
      const select = document.querySelector(`[data-ticket-destination="${ticketStatus.dataset.id}"]`);
      try {
        await api(`/api/panel/tickets/${ticketStatus.dataset.id}/status`, {
          method: "POST",
          body: JSON.stringify({
            status: ticketStatus.dataset.status,
            destination: select?.value || "",
          }),
        });
        await refreshPanelData();
        showFlash("Status da senha atualizado.");
      } catch (error) {
        showFlash(error.message, true);
      }
    }
  });

  document.body.addEventListener("change", (event) => {
    const field = event.target.closest("[data-budget-field]");
    if (field) {
      const item = field.closest("[data-budget-item]");
      if (!item) return;
      updateBudgetItem(item.dataset.budgetItem, field.dataset.budgetField, field.value);
      return;
    }
    if (event.target.id === "budgetConvenio") {
      state.budgetItems = state.budgetItems.map((item) => ({
        ...item,
        price: resolveProcedurePrice(item.procedure_id, event.target.value, item.incidences_count),
      }));
      renderBudget();
    }
  });

  document.body.addEventListener("input", (event) => {
    const field = event.target.closest("[data-budget-field]");
    if (field?.dataset.budgetField === "price") {
      maskCurrencyField(field);
      const item = field.closest("[data-budget-item]");
      if (item) updateBudgetItem(item.dataset.budgetItem, "price", field.value, false);
      return;
    }
    if (field) {
      const item = field.closest("[data-budget-item]");
      if (item) updateBudgetItem(item.dataset.budgetItem, field.dataset.budgetField, field.value, false);
      return;
    }
    if (event.target.id === "budgetDiscount") {
      maskCurrencyField(event.target);
      renderBudgetSummary();
      return;
    }
    if (event.target.id === "budgetPatientName") {
      const patientId = document.getElementById("budgetPatientId");
      const match = (state.patients || []).find((item) => String(item.full_name || "").trim().toLowerCase() === event.target.value.trim().toLowerCase());
      if (patientId) patientId.value = match ? String(match.id) : "";
    }
    if (event.target.id === "examOrderDiscount" || event.target.id === "examOrderPrice") {
      maskCurrencyField(event.target);
    }
    if (event.target.id === "examOrderProcedure" || event.target.id === "examOrderIncidences") {
      const exam = selectedDialogExam();
      const procedureId = document.getElementById("examOrderProcedure")?.value || "";
      const incidences = document.getElementById("examOrderIncidences")?.value || 1;
      const price = document.getElementById("examOrderPrice");
      if (price) price.value = procedureId ? formatCurrencyBRL(resolveProcedurePrice(procedureId, exam?.convenio_code || "PARTICULAR", incidences)) : formatCurrencyBRL(0);
    }
  });

  document.getElementById("examProcedure").addEventListener("change", (event) => {
    const procedure = state.procedures.find((item) => String(item.id) === event.target.value);
    if (!procedure) return;
    document.querySelector('#examForm [name="modality"]').value = procedure.modality || "";
    updateExamPriceField();
  });

  document.getElementById("examProcedure").addEventListener("change", updateExamPriceField);
  document.getElementById("examConvenio").addEventListener("change", updateExamPriceField);
  document.getElementById("examIncidences").addEventListener("change", updateExamPriceField);
  const examListConvenioFilter = document.getElementById("examListConvenioFilter");
  if (examListConvenioFilter) {
    examListConvenioFilter.addEventListener("change", (event) => {
      setExamPricingTable(event.target.value);
      renderExams();
    });
  }
  const examListTypeFilter = document.getElementById("examListTypeFilter");
  if (examListTypeFilter) {
    examListTypeFilter.addEventListener("change", () => {
      renderExams();
    });
  }
  const examLookupSearch = document.getElementById("examLookupSearch");
  if (examLookupSearch) {
    examLookupSearch.addEventListener("input", () => renderExams());
  }
  const examLookupSelect = document.getElementById("examLookupSelect");
  if (examLookupSelect) {
    examLookupSelect.addEventListener("change", () => {
      const procedure = state.procedures.find((item) => String(item.id) === String(examLookupSelect.value));
      if (procedure) openProcedureEditor(procedure);
    });
  }
}

function startPollers() {
  if (ui.chatPoll) clearInterval(ui.chatPoll);
  if (ui.panelPoll) clearInterval(ui.panelPoll);
  if (ui.workflowPoll) clearInterval(ui.workflowPoll);
  ui.chatPoll = setInterval(() => {
    refreshUnreadChat().catch(() => {});
    if (state.currentOperatorId && state.currentContactId) loadChatData().catch(() => {});
  }, 6000);
  ui.panelPoll = setInterval(() => {
    refreshPanelData().catch(() => {});
  }, 4000);
  ui.workflowPoll = setInterval(() => {
    refreshWorkflowData().catch(() => {});
  }, 8000);
}

async function initialize() {
  try {
    setSidebarCollapsed(window.localStorage.getItem("raiox.sidebarCollapsed") === "1");
  } catch (error) {
    setSidebarCollapsed(false);
  }
  try {
    const savedCadastros = window.localStorage.getItem("raiox.nav.cadastros");
    setNavGroupCollapsed("cadastros", savedCadastros === null ? true : savedCadastros === "1");
  } catch (error) {
    setNavGroupCollapsed("cadastros", true);
  }
  try {
    const savedConfigTab = window.localStorage.getItem("raiox.config.tab");
    ui.configTab = ["integrations", "pricing", "status", "deploy"].includes(savedConfigTab || "") ? savedConfigTab : "integrations";
  } catch (error) {
    ui.configTab = "integrations";
  }
  bindNavigation();
  bindKanban();
  bindForms();
  setActiveSection("kanban");
  const sidebarToggle = document.querySelector("[data-sidebar-toggle]");
  if (sidebarToggle) {
    sidebarToggle.addEventListener("click", toggleSidebarCollapsed);
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshWorkflowData().catch(() => {});
  });
  try {
    await loadAll();
    startPollers();
  } catch (error) {
    showFlash(error.message, true);
  }
}

initialize();
