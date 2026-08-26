(() => {
  "use strict";

  const API = "/apps/chamados/api";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const state = {
    bootstrap: null, tickets: [], documents: [], agenda: [], current: null, detail: null,
    editingIntervention: null, editingDocument: null, editingAgenda: null,
  };
  let suggestionTimer = null;
  let filterTimer = null;

  const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);
  const label = (value) => String(value || "").replaceAll("_", " ").toLowerCase().replace(/(^|\s)\S/g, (char) => char.toUpperCase());
  const dateTime = (value) => value ? new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value)) : "—";
  const dateTimeLocalValue = (value) => {
    const date = value ? new Date(value) : new Date(Date.now() + 60 * 60 * 1000);
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
  };
  const duration = (minutes) => {
    const total = Number(minutes || 0);
    if (total < 60) return `${total} min`;
    const hours = Math.floor(total / 60);
    const rest = total % 60;
    return rest ? `${hours}h ${rest}min` : `${hours}h`;
  };

  async function request(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
    const response = await fetch(`${API}${path}`, { cache: "no-store", ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.erro || "Não foi possível concluir a operação.");
    return data;
  }

  function toast(message, error = false) {
    const element = $("#toast");
    element.textContent = message;
    element.classList.toggle("error", error);
    element.classList.remove("hidden");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => element.classList.add("hidden"), 4200);
  }

  function optionHtml(items, valueKey, labelFn, empty = "") {
    return `${empty ? `<option value="">${esc(empty)}</option>` : ""}${items.map((item) => {
      const value = typeof item === "string" ? item : item[valueKey];
      return `<option value="${esc(value)}">${esc(labelFn(item))}</option>`;
    }).join("")}`;
  }

  function fillSelects() {
    const { categories, priorities, statuses, interventionTypes, users, devices, currentUser } = state.bootstrap;
    $$("select[name='category']").forEach((select) => { select.innerHTML = optionHtml(categories, "", label); });
    $$("select[name='priority']").forEach((select) => { select.innerHTML = optionHtml(priorities, "", label); });
    $$("select[name='status'], select[name='newStatus']").forEach((select) => { select.innerHTML = optionHtml(statuses, "", label); });
    $("select[name='type']", $("#interventionForm")).innerHTML = optionHtml(interventionTypes, "", label);
    $("#ticketStatusFilter").insertAdjacentHTML("beforeend", optionHtml(statuses, "", label));
    [$("#ticketCategoryFilter"), $("#solutionCategory"), $("#documentCategoryFilter")].forEach((select) => {
      select.insertAdjacentHTML("beforeend", optionHtml(categories, "", label));
    });
    const usersHtml = optionHtml(users, "id", (user) => `${user.nome} (${user.login})`);
    $$('select[name="requesterId"]').forEach((select) => { select.innerHTML = usersHtml; });
    $$("select[name='assigneeId']").forEach((select) => {
      select.innerHTML = `<option value="">A definir</option>${usersHtml}`;
    });
    const deviceHtml = optionHtml(devices, "id", (device) => `${device.name} · ${device.type}${device.host ? ` · ${device.host}` : ""}`);
    $$("select[name='deviceId']").forEach((select) => {
      const empty = select.closest("#documentForm") ? "Documento geral" : (select.closest("#ticketForm") ? "Sem equipamento vinculado" : "Sem equipamento");
      select.innerHTML = `<option value="">${empty}</option>${deviceHtml}`;
    });
    $("#solutionDevice").insertAdjacentHTML("beforeend", deviceHtml);
    $("select[name='requesterId']", $("#ticketForm")).value = String(currentUser.id);
  }

  function setView(view, updateUrl = true) {
    const allowed = ["dashboard", "chamados", "agenda", "historico", "documentos"];
    const selected = allowed.includes(view) ? view : "chamados";
    $$('[data-page]').forEach((page) => { page.hidden = page.dataset.page !== selected; });
    $$('[data-view]').forEach((button) => button.classList.toggle("active", button.dataset.view === selected));
    if (updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set("view", selected);
      history.replaceState({}, "", url);
    }
    if (selected === "documentos") loadDocuments();
    if (selected === "agenda") loadAgenda();
    if (selected === "historico") searchSolutions();
  }

  function priorityBadge(ticket) {
    return `<span class="badge priority-${esc(ticket.priority)}">${esc(label(ticket.priority))}</span>`;
  }

  function statusBadge(status) {
    return `<span class="badge status">${esc(label(status))}</span>`;
  }

  function renderSummary() {
    const summary = state.bootstrap.summary;
    $("#kpiOpen").textContent = summary.open;
    $("#kpiProgress").textContent = summary.inProgress;
    $("#kpiResolved").textContent = summary.resolved;
    $("#kpiTime").textContent = duration(summary.minutesSpent);
    const attention = state.tickets
      .filter((ticket) => !["RESOLVIDO", "FECHADO", "CANCELADO"].includes(ticket.status))
      .slice(0, 8);
    $("#attentionTickets").innerHTML = attention.length ? attention.map((ticket) => `
      <article class="compactTicket" data-ticket-id="${ticket.id}" tabindex="0">
        ${priorityBadge(ticket)}
        <div><strong>${esc(ticket.title)}</strong><small>${esc(ticket.protocol)} · ${esc(ticket.deviceName || ticket.location || label(ticket.category))}</small></div>
        ${statusBadge(ticket.status)}
      </article>`).join("") : '<p class="emptyState">Nenhum chamado pendente.</p>';
  }

  function renderTickets() {
    $("#ticketTable").innerHTML = state.tickets.length ? state.tickets.map((ticket) => `
      <tr class="ticketRow" data-ticket-id="${ticket.id}" tabindex="0">
        <td><div class="ticketTitle"><strong>${esc(ticket.title)}</strong><small>${esc(ticket.protocol)} · ${esc(dateTime(ticket.createdAt))}</small></div></td>
        <td>${priorityBadge(ticket)}<div class="ticketMeta">${esc(label(ticket.category))}${ticket.deviceName ? ` · ${esc(ticket.deviceName)}` : ticket.location ? ` · ${esc(ticket.location)}` : ""}</div></td>
        <td>${esc(ticket.requesterName || "—")}</td>
        <td>${esc(ticket.assigneeName || "A definir")}</td>
        <td>${esc(duration(ticket.minutesSpent))}</td>
        <td>${statusBadge(ticket.status)}</td>
      </tr>`).join("") : '<tr><td colspan="6" class="emptyState">Nenhum chamado encontrado.</td></tr>';
  }

  async function loadTickets() {
    const params = new URLSearchParams();
    const search = $("#ticketSearch").value.trim();
    const status = $("#ticketStatusFilter").value;
    const category = $("#ticketCategoryFilter").value;
    if (search) params.set("search", search);
    if (status) params.set("status", status);
    if (category) params.set("category", category);
    const data = await request(`/tickets?${params}`);
    state.tickets = data.tickets;
    fillAgendaTicketOptions();
    renderTickets();
    renderSummary();
  }

  function fillAgendaTicketOptions() {
    const select = $("select[name='ticketId']", $("#agendaForm"));
    const selected = select.value;
    select.innerHTML = `<option value="">Sem chamado relacionado</option>${state.tickets.map((ticket) => `<option value="${ticket.id}">${esc(ticket.protocol)} · ${esc(ticket.title)}</option>`).join("")}`;
    select.value = selected;
  }

  function agendaStatusActions(item) {
    if (item.status !== "PENDENTE") {
      return `<button class="documentEdit" type="button" data-agenda-status="PENDENTE" data-agenda-id="${item.id}">Reabrir</button>`;
    }
    return `<button class="documentEdit" type="button" data-agenda-status="CONCLUIDA" data-agenda-id="${item.id}">Concluir</button><button class="documentEdit dangerText" type="button" data-agenda-status="CANCELADA" data-agenda-id="${item.id}">Cancelar</button>`;
  }

  function renderAgenda() {
    $("#agendaList").innerHTML = state.agenda.length ? state.agenda.map((item) => {
      const emailState = item.emailSentAt
        ? `Aviso enviado em ${dateTime(item.emailSentAt)}`
        : (item.lastError ? `Falha no aviso: ${item.lastError}` : `Aviso programado para ${dateTime(item.notifyAt)}`);
      const related = item.ticketProtocol ? `${item.ticketProtocol} · ${item.ticketTitle}` : "Sem chamado relacionado";
      return `<article class="agendaCard status-${esc(item.status)}">
        <div class="agendaDate"><strong>${esc(dateTime(item.scheduledAt))}</strong><span>${esc(label(item.type))}</span></div>
        <div class="agendaBody"><div class="solutionMeta"><span>${esc(label(item.status))}</span><span>${esc(related)}</span></div><h3>${esc(item.title)}</h3>${item.description ? `<p>${esc(item.description)}</p>` : ""}<small class="${item.lastError ? "errorText" : ""}">${esc(emailState)} · ${esc(item.recipients.join(", "))}</small></div>
        <div class="agendaActions"><button class="documentEdit" type="button" data-edit-agenda="${item.id}">Editar</button>${agendaStatusActions(item)}</div>
      </article>`;
    }).join("") : '<p class="emptyState">Nenhuma tarefa encontrada na agenda.</p>';
  }

  async function loadAgenda() {
    const params = new URLSearchParams();
    if ($("#agendaStatusFilter").value) params.set("status", $("#agendaStatusFilter").value);
    try {
      const data = await request(`/agenda?${params}`);
      state.agenda = data.items || [];
      renderAgenda();
    } catch (error) { $("#agendaList").innerHTML = `<p class="emptyState">${esc(error.message)}</p>`; }
  }

  function resetAgendaForm() {
    const form = $("#agendaForm");
    form.reset();
    state.editingAgenda = null;
    form.elements.scheduledAt.value = dateTimeLocalValue();
    form.elements.reminderMinutes.value = "60";
    $("#agendaFormEyebrow").textContent = "Novo compromisso";
    $("#agendaFormTitle").textContent = "Agendar tarefa";
    $("#agendaSubmitButton").textContent = "Agendar tarefa";
    $("#cancelAgendaEdit").classList.add("hidden");
    $("#agendaMessage").textContent = "";
  }

  function editAgenda(agendaId) {
    const item = state.agenda.find((entry) => entry.id === agendaId);
    if (!item) return;
    const form = $("#agendaForm");
    state.editingAgenda = item.id;
    form.elements.type.value = item.type;
    form.elements.title.value = item.title;
    form.elements.scheduledAt.value = dateTimeLocalValue(item.scheduledAt);
    const reminder = Math.max(0, Math.round((new Date(item.scheduledAt) - new Date(item.notifyAt)) / 60000));
    if (![...form.elements.reminderMinutes.options].some((option) => Number(option.value) === reminder)) {
      form.elements.reminderMinutes.add(new Option(`${reminder} minutos`, String(reminder)));
    }
    form.elements.reminderMinutes.value = String(reminder);
    form.elements.recipients.value = item.recipients.join(", ");
    form.elements.ticketId.value = item.ticketId || "";
    form.elements.description.value = item.description || "";
    $("#agendaFormEyebrow").textContent = "Editar compromisso";
    $("#agendaFormTitle").textContent = "Editar tarefa agendada";
    $("#agendaSubmitButton").textContent = "Salvar alterações";
    $("#cancelAgendaEdit").classList.remove("hidden");
    $("#agendaMessage").textContent = "";
    form.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function submitAgenda(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const message = $("#agendaMessage");
    message.textContent = "Salvando...";
    try {
      const payload = ticketPayload(form);
      const scheduledAt = new Date(payload.scheduledAt);
      if (Number.isNaN(scheduledAt.getTime())) throw new Error("Informe uma data e hora válidas.");
      payload.scheduledAt = scheduledAt.toISOString();
      payload.reminderMinutes = Number(payload.reminderMinutes);
      const editingId = state.editingAgenda;
      await request(editingId ? `/agenda/${editingId}` : "/agenda", {
        method: editingId ? "PUT" : "POST", body: JSON.stringify(payload),
      });
      resetAgendaForm();
      toast(editingId ? "Tarefa agendada atualizada." : "Tarefa agendada com aviso por e-mail.");
      await loadAgenda();
    } catch (error) { message.textContent = error.message; }
  }

  async function updateAgendaStatus(agendaId, status) {
    try {
      await request(`/agenda/${agendaId}`, { method: "PUT", body: JSON.stringify({ status }) });
      toast(status === "CONCLUIDA" ? "Tarefa concluída." : (status === "CANCELADA" ? "Tarefa cancelada." : "Tarefa reaberta."));
      await loadAgenda();
    } catch (error) { toast(error.message, true); }
  }

  function openTicketModal() {
    const form = $("#ticketForm");
    form.reset();
    form.elements.category.value = "TI";
    form.elements.priority.value = "MEDIA";
    form.elements.requesterId.value = String(state.bootstrap.currentUser.id);
    $("#ticketFormMessage").textContent = "";
    $("#newTicketSuggestions").innerHTML = "";
    $("#ticketModal").classList.remove("hidden");
    form.elements.title.focus();
  }

  function closeModal(selector) { $(selector).classList.add("hidden"); }

  function ticketPayload(form) {
    const data = new FormData(form);
    return Object.fromEntries([...data.entries()].map(([key, value]) => [key, typeof value === "string" ? value.trim() : value]));
  }

  async function submitTicket(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const message = $("#ticketFormMessage");
    message.textContent = "Abrindo chamado...";
    try {
      const data = await request("/tickets", { method: "POST", body: JSON.stringify(ticketPayload(form)) });
      closeModal("#ticketModal");
      toast(`${data.ticket.protocol} aberto com sucesso.`);
      await refreshAll();
      openTicket(data.ticket.id);
    } catch (error) { message.textContent = error.message; }
  }

  async function showNewTicketSuggestions() {
    const form = $("#ticketForm");
    const text = `${form.elements.title.value} ${form.elements.description.value} ${form.elements.symptoms.value}`.trim();
    if (text.length < 12) { $("#newTicketSuggestions").innerHTML = ""; return; }
    const params = new URLSearchParams({ text, category: form.elements.category.value });
    if (form.elements.subcategory.value) params.set("subcategory", form.elements.subcategory.value);
    if (form.elements.deviceId.value) params.set("deviceId", form.elements.deviceId.value);
    try {
      const data = await request(`/similar?${params}`);
      const tickets = data.tickets || [];
      $("#newTicketSuggestions").innerHTML = tickets.length ? `
        <strong>${tickets.length} solução(ões) semelhante(s) encontrada(s) antes da abertura:</strong>
        ${tickets.slice(0, 3).map((ticket) => `<button class="suggestionLink" type="button" data-ticket-id="${ticket.id}">${esc(ticket.protocol)} · ${esc(ticket.title)} — ${esc(ticket.resolution || "ver histórico")}</button>`).join("")}` : "";
    } catch { $("#newTicketSuggestions").innerHTML = ""; }
  }

  function renderSuggestionBlocks(suggestions) {
    const tickets = suggestions?.tickets || [];
    const documents = suggestions?.documents || [];
    if (!tickets.length && !documents.length) return '<p class="emptyState">Nenhum caso resolvido semelhante ainda.</p>';
    return `${tickets.map((ticket) => `
      <article class="solutionCard" data-ticket-id="${ticket.id}">
        <div class="solutionMeta"><span>${esc(ticket.protocol)}</span><span>${esc(label(ticket.category))}</span><span>${esc(duration(ticket.minutesSpent))}</span></div>
        <h3>${esc(ticket.title)}</h3>
        ${ticket.rootCause ? `<p><strong>Causa:</strong> ${esc(ticket.rootCause)}</p>` : ""}
        <p class="solutionText"><strong>Solução:</strong> ${esc(ticket.resolution || "Consulte o histórico do chamado.")}</p>
        <div class="solutionMeta">${(ticket.similarityReasons || []).map((reason) => `<span>${esc(reason)}</span>`).join("")}</div>
      </article>`).join("")}
      ${documents.length ? `<h3>Documentação relacionada</h3>${documents.map(documentCard).join("")}` : ""}`;
  }

  async function searchSolutions() {
    const text = $("#solutionSearch").value.trim();
    const params = new URLSearchParams({ text, history: "1" });
    if ($("#solutionCategory").value) params.set("category", $("#solutionCategory").value);
    if ($("#solutionDevice").value) params.set("deviceId", $("#solutionDevice").value);
    $("#solutionResults").innerHTML = '<p class="emptyState">Consultando o histórico...</p>';
    try {
      const data = await request(`/similar?${params}`);
      const hasResults = (data.tickets || []).length || (data.documents || []).length;
      $("#solutionResults").innerHTML = hasResults
        ? renderSuggestionBlocks(data)
        : '<p class="emptyState">Nenhuma solução registrada corresponde aos filtros.</p>';
    } catch (error) { $("#solutionResults").innerHTML = `<p class="emptyState">${esc(error.message)}</p>`; }
  }

  function documentCard(document, editable = false) {
    const meta = [label(document.category), document.deviceName, document.fileName, document.sizeBytes ? `${Math.ceil(document.sizeBytes / 1024)} KB` : ""].filter(Boolean).join(" · ");
    return `<article class="documentCard">
      <span class="documentIcon">${document.externalUrl ? "↗" : "DOC"}</span>
      <div><strong>${esc(document.title)}</strong><small>${esc(meta || document.description || "Documento geral")}</small></div>
      <div class="documentActions">
        ${editable ? `<button class="documentEdit" type="button" data-edit-document="${document.id}">Editar</button>` : ""}
        <a href="${esc(document.downloadUrl)}" target="_blank" rel="noopener">Abrir</a>
      </div>
    </article>`;
  }

  async function loadDocuments() {
    const params = new URLSearchParams();
    if ($("#documentSearch").value.trim()) params.set("search", $("#documentSearch").value.trim());
    if ($("#documentCategoryFilter").value) params.set("category", $("#documentCategoryFilter").value);
    try {
      const data = await request(`/documents?${params}`);
      state.documents = data.documents;
      $("#documentList").innerHTML = state.documents.length
        ? state.documents.map((document) => documentCard(document, true)).join("")
        : '<p class="emptyState">Nenhum manual ou documento cadastrado.</p>';
    } catch (error) { $("#documentList").innerHTML = `<p class="emptyState">${esc(error.message)}</p>`; }
  }

  async function submitDocument(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const message = $("#documentMessage");
    const body = new FormData(form);
    message.textContent = "Salvando...";
    try {
      const editingId = state.editingDocument;
      await request(editingId ? `/documents/${editingId}` : "/documents", { method: editingId ? "PUT" : "POST", body });
      resetDocumentForm();
      message.textContent = editingId ? "Documento atualizado." : "Documento salvo.";
      await loadDocuments();
    } catch (error) { message.textContent = error.message; }
  }

  function resetDocumentForm() {
    const form = $("#documentForm");
    form.reset();
    state.editingDocument = null;
    form.elements.category.value = "TI";
    $("#documentFormEyebrow").textContent = "Novo conteúdo";
    $("#documentFormTitle").textContent = "Adicionar documento";
    $("#documentFileHint").textContent = "Anexe um arquivo ou informe um link.";
    $("#documentSubmitButton").textContent = "Salvar documento";
    $("#cancelDocumentEdit").classList.add("hidden");
    $("#documentMessage").textContent = "";
  }

  function editDocument(documentId) {
    const item = state.documents.find((document) => document.id === documentId);
    if (!item) return;
    const form = $("#documentForm");
    state.editingDocument = item.id;
    form.elements.title.value = item.title || "";
    form.elements.category.value = item.category || "GERAL";
    form.elements.deviceId.value = item.deviceId || "";
    form.elements.description.value = item.description || "";
    form.elements.externalUrl.value = item.externalUrl || "";
    form.elements.file.value = "";
    $("#documentFormEyebrow").textContent = "Editar conteúdo";
    $("#documentFormTitle").textContent = "Editar manual ou documentação";
    $("#documentFileHint").textContent = item.fileName
      ? `Arquivo atual: ${item.fileName}. Selecione outro somente para substituí-lo.`
      : "Este registro usa um link externo. Você também pode anexar um arquivo.";
    $("#documentSubmitButton").textContent = "Salvar alterações";
    $("#cancelDocumentEdit").classList.remove("hidden");
    $("#documentMessage").textContent = "";
    form.scrollIntoView({ behavior: "smooth", block: "start" });
    form.elements.title.focus();
  }

  function renderTimeline(items) {
    $("#timeline").innerHTML = items.length ? [...items].reverse().map((item) => `
      <article class="timelineItem">
        <div class="timelineHead">
          <strong>${esc(label(item.type))}${item.minutesSpent ? ` · ${esc(duration(item.minutesSpent))}` : ""}</strong>
          <button class="timelineEdit" type="button" data-edit-intervention="${item.id}">Editar</button>
        </div>
        <p>${esc(item.description)}</p>
        ${item.resolution ? `<p class="timelineResolution"><strong>Solução:</strong> ${esc(item.resolution)}</p>` : ""}
        <small>${esc(item.authorName)} · ${esc(dateTime(item.createdAt))}${item.previousStatus && item.newStatus && item.previousStatus !== item.newStatus ? ` · ${esc(label(item.previousStatus))} → ${esc(label(item.newStatus))}` : ""}</small>
      </article>`).join("") : '<p class="emptyState">Sem registros.</p>';
  }

  function fillDetail(data) {
    state.detail = data;
    state.editingIntervention = null;
    const ticket = data.ticket;
    const form = $("#detailForm");
    $("#detailProtocol").textContent = ticket.protocol;
    $("#detailTitle").textContent = ticket.title;
    $("#detailSummary").innerHTML = [
      label(ticket.category), ticket.subcategory, ticket.requesterName ? `Solicitante: ${ticket.requesterName}` : "",
      ticket.deviceName ? `${ticket.deviceName}${ticket.deviceHost ? ` · ${ticket.deviceHost}` : ""}` : ticket.location,
      `Tempo: ${duration(ticket.minutesSpent)}`, `Aberto: ${dateTime(ticket.createdAt)}`,
    ].filter(Boolean).map((item) => `<span>${esc(item)}</span>`).join("");
    form.elements.title.value = ticket.title || "";
    form.elements.category.value = ticket.category;
    form.elements.subcategory.value = ticket.subcategory || "";
    form.elements.status.value = ticket.status;
    form.elements.priority.value = ticket.priority;
    form.elements.requesterId.value = ticket.requesterId || "";
    form.elements.assigneeId.value = ticket.assigneeId || "";
    form.elements.deviceId.value = ticket.deviceId || "";
    form.elements.location.value = ticket.location || "";
    form.elements.description.value = ticket.description || "";
    form.elements.symptoms.value = ticket.symptoms || "";
    form.elements.rootCause.value = ticket.rootCause || "";
    form.elements.resolution.value = ticket.resolution || "";
    resetInterventionForm();
    $("#detailSuggestions").innerHTML = renderSuggestionBlocks(data.suggestions);
    $("#ticketDocuments").innerHTML = data.documents.length ? data.documents.map(documentCard).join("") : '<p class="emptyState">Nenhum anexo.</p>';
    renderTimeline(data.interventions);
  }

  async function openTicket(ticketId) {
    closeModal("#ticketModal");
    $("#detailModal").classList.remove("hidden");
    $("#detailTitle").textContent = "Carregando...";
    try {
      const data = await request(`/tickets/${ticketId}`);
      state.current = ticketId;
      fillDetail(data);
    } catch (error) { closeModal("#detailModal"); toast(error.message, true); }
  }

  async function saveDetail(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const message = $("#detailFormMessage");
    message.textContent = "Salvando...";
    try {
      await request(`/tickets/${state.current}`, { method: "PUT", body: JSON.stringify(ticketPayload(form)) });
      message.textContent = "Chamado atualizado.";
      await refreshAll();
      fillDetail(await request(`/tickets/${state.current}`));
    } catch (error) { message.textContent = error.message; }
  }

  async function submitIntervention(event) {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      const editingId = state.editingIntervention;
      const path = editingId
        ? `/tickets/${state.current}/interventions/${editingId}`
        : `/tickets/${state.current}/interventions`;
      await request(path, { method: editingId ? "PUT" : "POST", body: JSON.stringify(ticketPayload(form)) });
      toast(editingId ? "Registro do histórico atualizado." : "Intervenção registrada.");
      await refreshAll();
      fillDetail(await request(`/tickets/${state.current}`));
    } catch (error) { toast(error.message, true); }
  }

  function resetInterventionForm() {
    const form = $("#interventionForm");
    form.reset();
    state.editingIntervention = null;
    form.elements.minutesSpent.value = "0";
    form.elements.newStatus.disabled = false;
    form.elements.newStatus.value = state.detail?.ticket.status || "ABERTO";
    $("#interventionFormTitle").textContent = "Registrar intervenção";
    $("#interventionFormHint").textContent = "Tempo e conhecimento executado";
    $("#interventionSubmitButton").textContent = "Adicionar ao histórico";
    $("#cancelInterventionEdit").classList.add("hidden");
  }

  function editIntervention(interventionId) {
    const item = state.detail?.interventions.find((intervention) => intervention.id === interventionId);
    if (!item) return;
    const form = $("#interventionForm");
    state.editingIntervention = item.id;
    form.elements.type.value = item.type;
    form.elements.minutesSpent.value = String(item.minutesSpent || 0);
    form.elements.description.value = item.description || "";
    form.elements.resolution.value = item.resolution || "";
    form.elements.newStatus.value = item.newStatus || state.detail.ticket.status;
    form.elements.newStatus.disabled = true;
    $("#interventionFormTitle").textContent = "Editar registro do histórico";
    $("#interventionFormHint").textContent = "O status histórico permanece preservado";
    $("#interventionSubmitButton").textContent = "Salvar correção";
    $("#cancelInterventionEdit").classList.remove("hidden");
    form.scrollIntoView({ behavior: "smooth", block: "center" });
    form.elements.description.focus();
  }

  async function submitTicketDocument(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const body = new FormData(form);
    body.set("ticketId", String(state.current));
    body.set("category", state.detail.ticket.category);
    if (state.detail.ticket.deviceId) body.set("deviceId", String(state.detail.ticket.deviceId));
    try {
      await request("/documents", { method: "POST", body });
      form.reset();
      toast("Anexo adicionado.");
      fillDetail(await request(`/tickets/${state.current}`));
    } catch (error) { toast(error.message, true); }
  }

  async function refreshAll() {
    state.bootstrap = await request("/bootstrap");
    await loadTickets();
  }

  function bindEvents() {
    $("#newTicketButton").addEventListener("click", openTicketModal);
    $$('[data-view]').forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
    $$('[data-open-view]').forEach((button) => button.addEventListener("click", () => setView(button.dataset.openView)));
    $$('[data-close-modal]').forEach((button) => button.addEventListener("click", () => closeModal("#ticketModal")));
    $$('[data-close-detail]').forEach((button) => button.addEventListener("click", () => closeModal("#detailModal")));
    $("#ticketModal").addEventListener("click", (event) => { if (event.target === event.currentTarget) closeModal("#ticketModal"); });
    $("#detailModal").addEventListener("click", (event) => { if (event.target === event.currentTarget) closeModal("#detailModal"); });
    $("#ticketForm").addEventListener("submit", submitTicket);
    $("#detailForm").addEventListener("submit", saveDetail);
    $("#interventionForm").addEventListener("submit", submitIntervention);
    $("#cancelInterventionEdit").addEventListener("click", resetInterventionForm);
    $("#documentForm").addEventListener("submit", submitDocument);
    $("#cancelDocumentEdit").addEventListener("click", resetDocumentForm);
    $("#agendaForm").addEventListener("submit", submitAgenda);
    $("#cancelAgendaEdit").addEventListener("click", resetAgendaForm);
    $("#agendaStatusFilter").addEventListener("change", loadAgenda);
    $("#documentForm").elements.file.addEventListener("change", (event) => {
      if (event.currentTarget.files.length) $("#documentForm").elements.externalUrl.value = "";
    });
    $("#documentForm").elements.externalUrl.addEventListener("input", (event) => {
      if (event.currentTarget.value.trim()) $("#documentForm").elements.file.value = "";
    });
    $("#ticketDocumentForm").addEventListener("submit", submitTicketDocument);
    $("#solutionSearchButton").addEventListener("click", searchSolutions);
    $("#solutionSearch").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); searchSolutions(); } });
    [$("#ticketSearch"), $("#ticketStatusFilter"), $("#ticketCategoryFilter")].forEach((input) => input.addEventListener("input", () => {
      clearTimeout(filterTimer); filterTimer = setTimeout(() => loadTickets().catch((error) => toast(error.message, true)), 250);
    }));
    [$("#documentSearch"), $("#documentCategoryFilter")].forEach((input) => input.addEventListener("input", () => {
      clearTimeout(filterTimer); filterTimer = setTimeout(loadDocuments, 250);
    }));
    ["title", "description", "symptoms", "category", "subcategory", "deviceId"].forEach((name) => {
      $("#ticketForm").elements[name].addEventListener("input", () => {
        clearTimeout(suggestionTimer); suggestionTimer = setTimeout(showNewTicketSuggestions, 450);
      });
    });
    document.addEventListener("click", (event) => {
      const agendaStatusTarget = event.target.closest("[data-agenda-status]");
      if (agendaStatusTarget) {
        updateAgendaStatus(Number(agendaStatusTarget.dataset.agendaId), agendaStatusTarget.dataset.agendaStatus);
        return;
      }
      const agendaEditTarget = event.target.closest("[data-edit-agenda]");
      if (agendaEditTarget) {
        editAgenda(Number(agendaEditTarget.dataset.editAgenda));
        return;
      }
      const documentTarget = event.target.closest("[data-edit-document]");
      if (documentTarget) {
        editDocument(Number(documentTarget.dataset.editDocument));
        return;
      }
      const editTarget = event.target.closest("[data-edit-intervention]");
      if (editTarget) {
        editIntervention(Number(editTarget.dataset.editIntervention));
        return;
      }
      const target = event.target.closest("[data-ticket-id]");
      if (target) openTicket(Number(target.dataset.ticketId));
    });
    document.addEventListener("keydown", (event) => {
      if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-ticket-id]")) openTicket(Number(event.target.dataset.ticketId));
      if (event.key === "Escape") { closeModal("#ticketModal"); closeModal("#detailModal"); }
    });
  }

  async function init() {
    try {
      state.bootstrap = await request("/bootstrap");
      fillSelects();
      bindEvents();
      resetAgendaForm();
      await loadTickets();
      const initial = new URL(window.location.href).searchParams.get("view") || "chamados";
      setView(initial, false);
    } catch (error) {
      toast(error.message, true);
      $("#ticketTable").innerHTML = `<tr><td colspan="6" class="emptyState">${esc(error.message)}</td></tr>`;
    }
  }

  init();
})();
