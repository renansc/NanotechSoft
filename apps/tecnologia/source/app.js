(() => {
  "use strict";

  const API = "/apps/tecnologia/api";
  const state = { devices: [], diagnosis: [], monitorIntervalSeconds: 60, metrics: [] };
  let editingId = null;
  let toastTimer = null;

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);

  async function request(path, options = {}) {
    const response = await fetch(`${API}${path}`, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.erro || `Falha HTTP ${response.status}`);
    return data;
  }

  function showToast(message, error = false) {
    const toast = $("#toast");
    toast.textContent = message;
    toast.classList.toggle("error", error);
    toast.classList.remove("hidden");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.add("hidden"), 4300);
  }

  const number = (value, digits = 1) => value == null ? "—" : Number(value).toLocaleString("pt-BR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  const target = (device) => `${device.host}${device.porta ? `:${device.porta}` : ""}`;
  const statusKey = (metric) => (metric?.status || "PENDING").toLowerCase();
  const statusLabel = (metric) => ({ ONLINE: "Online", DEGRADADO: "Instável", OFFLINE: "Offline", PENDING: "Aguardando" })[metric?.status || "PENDING"];
  const statusBadge = (metric) => `<span class="status ${statusKey(metric)}">${statusLabel(metric)}</span>`;
  const dateTime = (value) => value ? new Date(value).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "medium" }) : "—";

  function renderKpis() {
    const active = state.devices.filter((device) => device.ativo);
    const count = (status) => active.filter((device) => device.ultimaMetrica?.status === status).length;
    const availabilities = active.map((device) => device.availability24h).filter((value) => value != null);
    const availability = availabilities.length
      ? availabilities.reduce((total, value) => total + Number(value), 0) / availabilities.length
      : null;
    $("#kpiOnline").textContent = count("ONLINE");
    $("#kpiDegraded").textContent = count("DEGRADADO");
    $("#kpiOffline").textContent = count("OFFLINE");
    $("#kpiAvailability").textContent = availability == null ? "—" : `${number(availability, 1)}%`;
  }

  function renderDiagnosis() {
    $("#diagnosisList").innerHTML = state.diagnosis.length
      ? state.diagnosis.map((item) => `<div class="diag ${esc(item.level)}">${esc(item.text)}</div>`).join("")
      : '<div class="diag info">Ainda não há diagnóstico disponível.</div>';
  }

  function renderCards() {
    const active = state.devices.filter((device) => device.ativo);
    $("#deviceCards").innerHTML = active.length ? active.map((device) => {
      const metric = device.ultimaMetrica;
      return `<article class="deviceCard">
        <div class="deviceCardHead">
          <div><h3>${esc(device.nome)}</h3><span class="target">${esc(target(device))}</span></div>
          ${statusBadge(metric)}
        </div>
        <div class="metricLine">
          <div><span>Latência</span><strong>${number(metric?.latencyMs)} ms</strong></div>
          <div><span>Perda</span><strong>${number(metric?.packetLossPct)}%</strong></div>
          <div><span>Jitter</span><strong>${number(metric?.jitterMs)} ms</strong></div>
        </div>
        <p class="deviceMessage">${esc(metric?.message || "Aguardando primeira medição")}${metric?.checkedAt ? ` · ${esc(dateTime(metric.checkedAt))}` : ""}</p>
      </article>`;
    }).join("") : '<p class="muted">Nenhum equipamento ativo.</p>';
  }

  function renderQualityTable() {
    $("#qualityTable").innerHTML = state.devices.filter((device) => device.ativo).map((device) => `<tr>
      <td><strong>${esc(device.nome)}</strong><br><small class="muted">${esc(target(device))}</small></td>
      <td>${device.availability24h == null ? "—" : `${number(device.availability24h, 1)}%`}</td>
      <td>${device.avgLatency24h == null ? "—" : `${number(device.avgLatency24h)} ms`}</td>
      <td>${device.avgLoss24h == null ? "—" : `${number(device.avgLoss24h)}%`}</td>
      <td>${device.checks24h}</td>
    </tr>`).join("") || '<tr><td colspan="5" class="muted">Sem medições nas últimas 24 horas.</td></tr>';
  }

  function renderDeviceTable() {
    $("#deviceTable").innerHTML = state.devices.map((device) => `<tr>
      <td><strong>${esc(device.nome)}</strong><br><small class="muted">${esc(device.tipo)}</small></td>
      <td>${esc(device.sonda)}${device.critico ? '<br><small class="muted">Crítico</small>' : ""}</td>
      <td><span class="target">${esc(target(device))}</span></td>
      <td>${esc(device.localizacao || "—")}</td>
      <td>${number(device.latenciaAlertaMs, 0)} ms / ${number(device.perdaAlertaPct)}%</td>
      <td>${device.ativo ? statusBadge(device.ultimaMetrica) : '<span class="status pending">Inativo</span>'}</td>
      <td><div class="tableActions"><button class="smallButton" data-edit="${device.id}" type="button">Editar</button><button class="smallButton danger" data-delete="${device.id}" type="button">Excluir</button></div></td>
    </tr>`).join("") || '<tr><td colspan="7" class="muted">Nenhum equipamento cadastrado.</td></tr>';
  }

  function renderHistoryOptions() {
    const select = $("#historyDevice");
    const selected = select.value;
    select.innerHTML = state.devices.map((device) => `<option value="${device.id}">${esc(device.nome)} — ${esc(device.host)}</option>`).join("");
    if (state.devices.some((device) => String(device.id) === selected)) select.value = selected;
  }

  function renderAll() {
    renderKpis();
    renderDiagnosis();
    renderCards();
    renderQualityTable();
    renderDeviceTable();
    renderHistoryOptions();
  }

  async function loadOverview({ quiet = false } = {}) {
    try {
      const data = await request("/overview");
      state.devices = data.devices || [];
      state.diagnosis = data.diagnosis || [];
      state.monitorIntervalSeconds = data.monitorIntervalSeconds || 60;
      $("#monitorState").textContent = `Coleta automática a cada ${state.monitorIntervalSeconds}s`;
      renderAll();
    } catch (error) {
      $("#monitorState").textContent = "Monitor indisponível";
      if (!quiet) showToast(error.message, true);
    }
  }

  async function probeAll() {
    const button = $("#probeAll");
    button.disabled = true;
    button.textContent = "Verificando...";
    try {
      const data = await request("/probe", { method: "POST", body: "{}" });
      state.devices = data.devices || [];
      state.diagnosis = data.diagnosis || [];
      renderAll();
      if (!$("[data-page='historico']").classList.contains("hidden")) await loadHistory();
      showToast("Verificação concluída.");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = "Verificar agora";
    }
  }

  function setView(view, updateHash = true) {
    const known = ["dashboard", "equipamentos", "historico"];
    if (!known.includes(view)) view = "dashboard";
    $$(".techView").forEach((element) => element.classList.toggle("hidden", element.dataset.page !== view));
    $$(".tab").forEach((element) => element.classList.toggle("active", element.dataset.view === view));
    if (updateHash) history.replaceState(null, "", view === "dashboard" ? location.pathname : `#${view}`);
    if (view === "historico") loadHistory();
  }

  function openDevice(device = null) {
    editingId = device?.id || null;
    $("#deviceModalTitle").textContent = device ? "Editar equipamento" : "Novo equipamento";
    $("#deviceId").value = device?.id || "";
    $("#deviceName").value = device?.nome || "";
    $("#deviceType").value = device?.tipo || "OUTRO";
    $("#deviceHost").value = device?.host || "";
    $("#devicePort").value = device?.porta || "";
    $("#deviceProbe").value = device?.sonda || "ICMP";
    $("#deviceLocation").value = device?.localizacao || "";
    $("#deviceLatency").value = device?.latenciaAlertaMs ?? 80;
    $("#deviceLoss").value = device?.perdaAlertaPct ?? 5;
    $("#deviceNotes").value = device?.observacoes || "";
    $("#deviceCritical").checked = Boolean(device?.critico);
    $("#deviceActive").checked = device ? Boolean(device.ativo) : true;
    $("#deviceModal").classList.remove("hidden");
    $("#deviceName").focus();
  }

  function closeDevice() {
    $("#deviceModal").classList.add("hidden");
    editingId = null;
  }

  async function saveDevice(event) {
    event.preventDefault();
    const payload = {
      nome: $("#deviceName").value,
      tipo: $("#deviceType").value,
      host: $("#deviceHost").value,
      porta: $("#devicePort").value ? Number($("#devicePort").value) : null,
      sonda: $("#deviceProbe").value,
      localizacao: $("#deviceLocation").value,
      latenciaAlertaMs: Number($("#deviceLatency").value),
      perdaAlertaPct: Number($("#deviceLoss").value),
      observacoes: $("#deviceNotes").value,
      critico: $("#deviceCritical").checked,
      ativo: $("#deviceActive").checked,
    };
    try {
      await request(editingId ? `/devices/${editingId}` : "/devices", {
        method: editingId ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      closeDevice();
      await loadOverview();
      showToast("Equipamento salvo.");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function deleteDevice(id) {
    const device = state.devices.find((item) => item.id === id);
    if (!device || !window.confirm(`Excluir ${device.nome} e todo o histórico de medições?`)) return;
    try {
      await request(`/devices/${id}`, { method: "DELETE" });
      await loadOverview();
      showToast("Equipamento excluído.");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function discover() {
    const button = $("#discoverPrinters");
    const results = $("#discoveryResults");
    button.disabled = true;
    button.textContent = "Procurando...";
    results.classList.add("muted");
    results.textContent = "Testando as portas 9100, 631 e 515 nos endereços da sub-rede...";
    try {
      const data = await request("/discover-printers", {
        method: "POST",
        body: JSON.stringify({ subnet: $("#discoverySubnet").value }),
      });
      const found = data.devices || [];
      results.classList.toggle("muted", !found.length);
      results.innerHTML = found.length ? found.map((item) => `<div class="discoveryItem">
        <div><strong>${esc(item.host)}</strong><br><small class="muted">Portas: ${item.ports.map(esc).join(", ")}</small></div>
        ${item.registered ? '<span class="status online">Cadastrada</span>' : `<button class="smallButton" data-add-printer="${esc(item.host)}" data-printer-port="${Number(item.suggestedPort)}" type="button">Cadastrar</button>`}
      </div>`).join("") : "Nenhuma impressora respondeu nessas portas.";
    } catch (error) {
      results.textContent = error.message;
      showToast(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = "Varrer portas de impressão";
    }
  }

  async function addPrinter(host, port) {
    const octet = host.split(".").pop();
    try {
      await request("/devices", {
        method: "POST",
        body: JSON.stringify({
          nome: `Impressora ${octet}`, tipo: "IMPRESSORA", host, porta: port,
          sonda: "ICMP", localizacao: "A identificar", observacoes: "Localizada pela descoberta da rede",
          critico: false, ativo: true, latenciaAlertaMs: 80, perdaAlertaPct: 5,
        }),
      });
      await loadOverview();
      await discover();
      showToast("Impressora cadastrada.");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  function renderHistory() {
    const metrics = state.metrics;
    const online = metrics.filter((item) => item.status !== "OFFLINE").length;
    const latencies = metrics.map((item) => item.latencyMs).filter((value) => value != null);
    const losses = metrics.map((item) => Number(item.packetLossPct || 0));
    const average = (values) => values.length ? values.reduce((total, value) => total + Number(value), 0) / values.length : null;
    $("#historySummary").innerHTML = [
      `<span class="summaryPill"><strong>${metrics.length}</strong> medições</span>`,
      `<span class="summaryPill"><strong>${metrics.length ? number(online / metrics.length * 100, 1) : "—"}%</strong> disponibilidade</span>`,
      `<span class="summaryPill"><strong>${number(average(latencies))} ms</strong> latência média</span>`,
      `<span class="summaryPill"><strong>${number(average(losses))}%</strong> perda média</span>`,
    ].join("");
    renderChart(metrics);
    $("#historyTable").innerHTML = [...metrics].reverse().slice(0, 300).map((metric) => `<tr>
      <td>${esc(dateTime(metric.checkedAt))}</td><td>${statusBadge(metric)}</td>
      <td>${number(metric.latencyMs)} ms</td><td>${number(metric.packetLossPct)}%</td>
      <td>${number(metric.jitterMs)} ms</td><td>${metric.serviceOk == null ? "—" : (metric.serviceOk ? "Disponível" : "Falhou")}</td>
    </tr>`).join("") || '<tr><td colspan="6" class="muted">Ainda não há medições neste período.</td></tr>';
  }

  function renderChart(metrics) {
    const svg = $("#historyChart");
    if (!metrics.length) {
      svg.innerHTML = '<text x="500" y="135" text-anchor="middle" fill="#66736e" font-size="18">Sem dados no período</text>';
      return;
    }
    const latencyMax = Math.max(10, ...metrics.map((item) => Number(item.latencyMs || 0))) * 1.1;
    const point = (item, index, field, max) => {
      const x = metrics.length === 1 ? 500 : 24 + index * (952 / (metrics.length - 1));
      const y = 235 - Math.min(max, Number(item[field] || 0)) / max * 205;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    };
    const latency = metrics.map((item, index) => point(item, index, "latencyMs", latencyMax)).join(" ");
    const loss = metrics.map((item, index) => point(item, index, "packetLossPct", 100)).join(" ");
    const grid = [30, 81, 133, 184, 235].map((y) => `<line class="chartGrid" x1="24" y1="${y}" x2="976" y2="${y}" />`).join("");
    svg.innerHTML = `${grid}<polyline class="chartLatency" points="${latency}"/><polyline class="chartLoss" points="${loss}"/>`;
  }

  async function loadHistory() {
    const deviceId = Number($("#historyDevice").value || state.devices[0]?.id || 0);
    if (!deviceId) { state.metrics = []; renderHistory(); return; }
    try {
      const data = await request(`/history?deviceId=${deviceId}&hours=${Number($("#historyHours").value || 24)}`);
      state.metrics = data.metrics || [];
      renderHistory();
    } catch (error) {
      showToast(error.message, true);
    }
  }

  $("#probeAll").addEventListener("click", probeAll);
  $("#newDevice").addEventListener("click", () => openDevice());
  $("#deviceForm").addEventListener("submit", saveDevice);
  $("#closeDeviceModal").addEventListener("click", closeDevice);
  $("#cancelDevice").addEventListener("click", closeDevice);
  $("#deviceModal").addEventListener("click", (event) => { if (event.target.id === "deviceModal") closeDevice(); });
  $("#discoverPrinters").addEventListener("click", discover);
  $("#historyDevice").addEventListener("change", loadHistory);
  $("#historyHours").addEventListener("change", loadHistory);
  $$(".tab").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  $$('[data-open-view]').forEach((button) => button.addEventListener("click", () => setView(button.dataset.openView)));
  $("#deviceTable").addEventListener("click", (event) => {
    const edit = event.target.closest("[data-edit]");
    const remove = event.target.closest("[data-delete]");
    if (edit) openDevice(state.devices.find((device) => device.id === Number(edit.dataset.edit)));
    if (remove) deleteDevice(Number(remove.dataset.delete));
  });
  $("#discoveryResults").addEventListener("click", (event) => {
    const button = event.target.closest("[data-add-printer]");
    if (button) addPrinter(button.dataset.addPrinter, Number(button.dataset.printerPort));
  });
  window.addEventListener("hashchange", () => setView(location.hash.slice(1) || "dashboard", false));
  window.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDevice(); });

  setView(location.hash.slice(1) || "dashboard", false);
  loadOverview();
  window.setInterval(() => loadOverview({ quiet: true }), 15000);
})();
