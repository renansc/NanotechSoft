(() => {
  "use strict";

  const API = "/apps/tecnologia/api";
  const state = { devices: [], diagnosis: [], emailAlerts: null, alertConfiguration: null, linkUsage: null, linkUsageReport: null, monitorIntervalSeconds: 60, speed: null, metrics: [], speedMetrics: [], printerUsage: {}, backups: [], backupRuns: [] };
  let editingId = null;
  let editingBackupId = null;
  let detailDeviceId = null;
  let toastTimer = null;
  let alertConfigDirty = false;

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
  const target = (device) => {
    const additional = Math.max(0, (device.networkAddresses?.length || 1) - 1);
    return `${device.host}${device.porta ? `:${device.porta}` : ""}${additional ? ` +${additional} IP${additional > 1 ? "s" : ""}` : ""}`;
  };
  const addressesToText = (addresses = []) => addresses
    .filter((item) => !item.primary)
    .map((item) => `${item.label} = ${item.host}`)
    .join("\n");
  const addressesFromText = (value) => String(value || "").split(/\r?\n/).map((line, index) => {
    const text = line.trim();
    if (!text) return null;
    const separator = text.indexOf("=");
    return separator >= 0
      ? { label: text.slice(0, separator).trim(), host: text.slice(separator + 1).trim() }
      : { label: `Interface ${index + 1}`, host: text };
  }).filter(Boolean);
  const statusKey = (metric) => ({ OK: "online", FALHA: "offline" })[metric?.status] || (metric?.status || "PENDING").toLowerCase();
  const statusLabel = (metric) => ({ ONLINE: "Online", DEGRADADO: "Instável", OFFLINE: "Offline", PENDING: "Aguardando", OK: "Normal", FALHA: "Falhou" })[metric?.status || "PENDING"] || metric?.status;
  const statusBadge = (metric) => `<span class="status ${statusKey(metric)}">${statusLabel(metric)}</span>`;
  const dateTime = (value) => value ? new Date(value).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "medium" }) : "—";
  const bytes = (value) => {
    if (value == null) return "—";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let amount = Number(value);
    let unit = 0;
    while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
    return `${number(amount, amount >= 100 ? 0 : 1)} ${units[unit]}`;
  };
  const duration = (value) => {
    if (value == null) return "—";
    const seconds = Math.max(0, Number(value));
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return [days ? `${days}d` : "", hours ? `${hours}h` : "", `${minutes}min`].filter(Boolean).join(" ");
  };

  function renderPrinterUsage(usage) {
    if (!usage || usage.loading) return '<div class="detailSection printerUsage"><h3>Impressões das últimas 4 semanas</h3><p class="muted">Calculando páginas impressas...</p></div>';
    if (usage.error) return `<div class="detailSection printerUsage"><h3>Impressões das últimas 4 semanas</h3><div class="detailNotice warning"><span>${esc(usage.error)}</span></div></div>`;
    if (!usage.hasComparisons) return '<div class="detailSection printerUsage"><h3>Impressões das últimas 4 semanas</h3><p class="muted">Aguardando pelo menos duas leituras do contador de páginas.</p></div>';

    const weeks = usage.weeks || [];
    const chartWidth = 640;
    const chartHeight = 150;
    const left = 34;
    const right = 16;
    const top = 24;
    const bottom = 42;
    const plotWidth = chartWidth - left - right;
    const plotHeight = chartHeight - top - bottom;
    const maximum = Math.max(1, ...weeks.map((week) => Number(week.pages || 0)));
    const points = weeks.map((week, index) => {
      const x = weeks.length === 1 ? left + (plotWidth / 2) : left + ((plotWidth * index) / (weeks.length - 1));
      const y = top + plotHeight - ((Number(week.pages || 0) / maximum) * plotHeight);
      return { ...week, x, y };
    });
    const polyline = points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
    const period = `${new Date(`${usage.historyStart || usage.periodStart}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })} a ${new Date(`${usage.periodEnd}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })}`;
    const coverageNote = !usage.todayComplete && usage.coverageStartedAt
      ? `<p class="printerUsageNote">Contagem disponível desde ${esc(dateTime(usage.coverageStartedAt))}; páginas anteriores à primeira leitura SNMP não podem ser recuperadas.</p>`
      : "";
    const pointMarkup = points.map((point) => `<g>
      <circle cx="${point.x}" cy="${point.y}" r="4"></circle>
      <text class="printerChartValue" x="${point.x}" y="${Math.max(12, point.y - 9)}">${Number(point.pages || 0).toLocaleString("pt-BR")}</text>
      <text class="printerChartLabel" x="${point.x}" y="${chartHeight - 12}">${esc(point.label)}${point.current ? " *" : ""}</text>
    </g>`).join("");
    return `<div class="detailSection printerUsage">
      <div class="detailSectionHead"><h3>Impressões das últimas 4 semanas</h3><span>${esc(period)}</span></div>
      <div class="printerUsageSummary">
        <div><span>Impressas hoje</span><strong>${Number(usage.todayPages || 0).toLocaleString("pt-BR")}</strong><small>páginas</small></div>
        <div><span>Total da semana</span><strong>${Number(usage.weekPages || 0).toLocaleString("pt-BR")}</strong><small>páginas</small></div>
        <div><span>Total em 4 semanas</span><strong>${Number(usage.fourWeekPages || 0).toLocaleString("pt-BR")}</strong><small>páginas</small></div>
      </div>
      <div class="printerChartWrap"><svg class="printerChart" viewBox="0 0 ${chartWidth} ${chartHeight}" role="img" aria-label="Páginas impressas nas últimas quatro semanas">
        <line x1="${left}" y1="${top + plotHeight}" x2="${chartWidth - right}" y2="${top + plotHeight}"></line>
        ${points.length > 1 ? `<polyline points="${polyline}"></polyline>` : ""}
        ${pointMarkup}
      </svg></div><p class="printerUsageNote">* semana atual em andamento.</p>${coverageNote}
    </div>`;
  }

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
    $("#kpiDownload").textContent = state.speed?.downloadMbps == null ? "—" : `${number(state.speed.downloadMbps)} Mbps`;
    $("#kpiUpload").textContent = state.speed?.uploadMbps == null ? "—" : `${number(state.speed.uploadMbps)} Mbps`;
  }

  function renderDiagnosis() {
    $("#diagnosisList").innerHTML = state.diagnosis.length
      ? state.diagnosis.map((item) => {
        const details = [item.detail, item.checkedAt ? `Medição: ${dateTime(item.checkedAt)}` : "", item.deviceId ? "Abrir histórico deste equipamento" : ""].filter(Boolean).join(" · ");
        const content = `<span>${esc(item.text)}${details ? `<small>${esc(details)}</small>` : ""}</span>`;
        return item.deviceId
          ? `<button class="diag ${esc(item.level)}" data-history-device="${Number(item.deviceId)}" type="button">${content}</button>`
          : `<div class="diag ${esc(item.level)}">${content}</div>`;
      }).join("")
      : '<div class="diag info">Ainda não há diagnóstico disponível.</div>';
  }

  function renderEmailAlerts() {
    const alert = state.emailAlerts;
    if (!alert) {
      $("#emailAlertStatus").textContent = "Ainda não há informações da configuração.";
      return;
    }
    const configuration = alert.configured
      ? '<span class="status online">Envio configurado</span>'
      : '<span class="status degradado">Aguardando SMTP</span>';
    const lastError = alert.lastError
      ? `<div class="emailAlertError"><strong>Última falha</strong><span>${esc(alert.lastError)}</span></div>`
      : "";
    const sender = alert.sender
      ? `Remetente: ${alert.sender}${alert.accountName ? ` · ${alert.accountName}` : ""}`
      : "Nenhuma conta remetente disponível";
    $("#emailAlertStatus").innerHTML = `<div class="emailAlertSummary">
      <div>${configuration}<small>${esc(sender)}</small></div>
      <div><span>Destinatário</span><strong>${esc(alert.recipient)}</strong></div>
      <div><span>Alertas ativos</span><strong>${Number(alert.activeCount || 0)}</strong></div>
      <div><span>Último envio</span><strong>${esc(dateTime(alert.lastEmailAt))}</strong></div>
    </div>${lastError}`;
  }

  function renderAlertConfiguration() {
    const config = state.alertConfiguration;
    if (config && !alertConfigDirty) {
      [
        "notifyInternetDown", "notifyLinkSlow", "notifyLinkUsage", "notifyGateway",
        "notifyCpu", "notifyMemory", "notifyDisk", "notifyDeviceNetwork", "includeConsumers",
      ].forEach((key) => { $(`#${key}`).checked = Boolean(config[key]); });
      $("#linkDownloadCapacity").value = Number(config.linkDownloadCapacityMbps || 0);
      $("#linkUploadCapacity").value = Number(config.linkUploadCapacityMbps || 0);
      $("#linkUsageThreshold").value = Number(config.linkUsageThresholdPct || 80);
    }
    const usage = state.linkUsage;
    const summary = $("#linkUsageSummary");
    const table = $("#linkConsumersTable");
    if (!usage) {
      summary.textContent = "Aguardando telemetria...";
      return;
    }
    if (usage.usagePct == null) {
      summary.innerHTML = '<span class="status pending">Sem percentual</span><small>Informe a capacidade do link</small>';
    } else {
      const direction = usage.direction === "upload" ? "upload" : "download";
      const threshold = Number(config?.linkUsageThresholdPct || 80);
      const status = Number(usage.usagePct) >= threshold ? "degradado" : "online";
      summary.innerHTML = `<span class="status ${status}">${number(usage.usagePct)}%</span><small>maior ocupação no ${direction}</small>`;
    }
    table.innerHTML = (usage.contributors || []).map((item) => `<tr>
      <td><strong>${esc(item.name)}</strong><br><small class="muted">${esc(item.host)}</small></td>
      <td>${number(item.downloadMbps, 3)} Mbps</td>
      <td>${number(item.uploadMbps, 3)} Mbps</td>
      <td>${item.networkPct == null ? "—" : `${number(item.networkPct)}%`}</td>
      <td>${esc(dateTime(item.measuredAt))}</td>
    </tr>`).join("") || '<tr><td colspan="5" class="muted">Nenhum equipamento com exporter ou SNMP forneceu tráfego ainda.</td></tr>';
  }

  function renderCards() {
    const active = state.devices.filter((device) => device.ativo);
    $("#deviceCards").innerHTML = active.length ? active.map((device) => {
      const metric = device.ultimaMetrica;
      const telemetry = metric?.telemetry;
      const isSnmpNvr = device.tipo === "NVR" && String(telemetry?.protocol || device.sonda || "").toUpperCase().startsWith("SNMP");
      const resourceLine = telemetry ? (isSnmpNvr ? `<div class="resourceLine">
        <span>Modelo <strong>${esc(telemetry.model || "—")}</strong></span>
        <span>Canais <strong>${telemetry.channelCapacity == null ? "—" : number(telemetry.channelCapacity, 0)}</strong></span>
        <span>CPU <strong>${telemetry.cpuPct == null ? "Não exposto" : `${number(telemetry.cpuPct)}%`}</strong></span>
        <span>Disco <strong>${telemetry.diskPct == null ? "Não exposto" : `${number(telemetry.diskPct)}%`}</strong></span>
        <span>Interfaces <strong>${number(telemetry.interfaceCount ?? telemetry.interfaces?.length, 0)}</strong></span>
        <span>Rede ↓ <strong>${telemetry.downloadMbps == null ? "Aguardando" : `${number(telemetry.downloadMbps, 3)} Mbps`}</strong></span>
        <span>Rede ↑ <strong>${telemetry.uploadMbps == null ? "Aguardando" : `${number(telemetry.uploadMbps, 3)} Mbps`}</strong></span>
      </div>` : `<div class="resourceLine">
        <span>CPU <strong>${number(telemetry.cpuPct)}%</strong></span>
        <span>Memória <strong>${number(telemetry.memoryPct)}%</strong></span>
        <span>Disco <strong>${number(telemetry.diskPct)}%</strong></span>
        <span>Uso rede <strong>${number(telemetry.networkPct)}%</strong></span>
        <span>Rede ↓ <strong>${number(telemetry.downloadMbps)} Mbps</strong></span>
        <span>Rede ↑ <strong>${number(telemetry.uploadMbps)} Mbps</strong></span>
      </div>`) : "";
      return `<article class="deviceCard clickableDevice" data-details="${device.id}" tabindex="0" role="button" aria-label="Abrir detalhes de ${esc(device.nome)}">
        <div class="deviceCardHead">
          <div><h3>${esc(device.nome)}</h3><span class="target">${esc(target(device))}</span></div>
          ${statusBadge(metric)}
        </div>
        <div class="metricLine">
          <div><span>Latência</span><strong>${number(metric?.latencyMs)} ms</strong></div>
          <div><span>Perda</span><strong>${number(metric?.packetLossPct)}%</strong></div>
          <div><span>Jitter</span><strong>${number(metric?.jitterMs)} ms</strong></div>
        </div>
        ${resourceLine}
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
    $("#deviceTable").innerHTML = state.devices.map((device) => `<tr class="clickableDevice" data-details="${device.id}" tabindex="0" aria-label="Abrir detalhes de ${esc(device.nome)}">
      <td><strong>${esc(device.nome)}</strong><br><small class="muted">${esc(device.tipo)}</small></td>
      <td>${esc(device.sonda)}${device.hasSnmpCommunity ? '<br><small class="muted">SNMP configurado</small>' : ""}${device.agentPort ? `<br><small class="muted">Exporter :${device.agentPort}</small>` : ""}${device.critico ? '<br><small class="muted">Crítico</small>' : ""}</td>
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
    renderEmailAlerts();
    renderAlertConfiguration();
    renderCards();
    renderQualityTable();
    renderDeviceTable();
    renderHistoryOptions();
    if (detailDeviceId) renderDeviceDetails();
  }

  function renderDeviceDetails() {
    const device = state.devices.find((item) => item.id === detailDeviceId);
    if (!device) return closeDeviceDetails();
    const metric = device.ultimaMetrica;
    const telemetry = metric?.telemetry;
    const endpointHost = telemetry?.endpointHost || metric?.activeAddress || device.host;
    const protocol = telemetry?.protocol || device.sonda;
    const isSnmp = String(protocol).toUpperCase().startsWith("SNMP");
    const isPrinter = isSnmp && device.tipo === "IMPRESSORA";
    const isNvr = isSnmp && device.tipo === "NVR";
    const collectionEndpoint = isSnmp
      ? `udp://${endpointHost}:${device.snmpPort || 161}`
      : device.agentPort ? `http://${endpointHost}:${device.agentPort}${device.agentPath || "/metrics"}` : "Não configurado";
    $("#deviceDetailsTitle").textContent = device.nome;
    $("#deviceDetailsSubtitle").textContent = `${device.tipo} · ${target(device)}`;
    const genericResourceCards = [
      ["CPU", telemetry?.cpuPct == null ? "—" : `${number(telemetry.cpuPct)}%`],
      ["Memória", telemetry?.memoryPct == null ? "—" : `${number(telemetry.memoryPct)}%`],
      ["Disco", telemetry?.diskPct == null ? "—" : `${number(telemetry.diskPct)}%`],
      ["Uso da rede", telemetry?.networkPct == null ? "—" : `${number(telemetry.networkPct)}%`],
      ["Capacidade da rede", telemetry?.networkCapacityMbps == null ? "—" : `${number(telemetry.networkCapacityMbps)} Mbps`],
      ["Rede recebida", telemetry?.downloadMbps == null ? "Aguardando 2ª coleta" : `${number(telemetry.downloadMbps, 3)} Mbps`],
      ["Rede enviada", telemetry?.uploadMbps == null ? "Aguardando 2ª coleta" : `${number(telemetry.uploadMbps, 3)} Mbps`],
    ];
    const printerResourceCards = [
      ["Estado", telemetry?.printerStatus || "Não informado"],
      ["Total de páginas", telemetry?.pageCount == null ? "—" : number(telemetry.pageCount, 0)],
      ["Uso da rede", telemetry?.networkPct == null ? "—" : `${number(telemetry.networkPct)}%`],
      ["Rede recebida", telemetry?.downloadMbps == null ? "Aguardando 2ª coleta" : `${number(telemetry.downloadMbps, 3)} Mbps`],
      ["Rede enviada", telemetry?.uploadMbps == null ? "Aguardando 2ª coleta" : `${number(telemetry.uploadMbps, 3)} Mbps`],
    ];
    const nvrResourceCards = [
      ["Modelo", telemetry?.model || "—"],
      ["Capacidade de canais", telemetry?.channelCapacity == null ? "—" : number(telemetry.channelCapacity, 0)],
      ["CPU", telemetry?.cpuPct == null ? "Não exposto via SNMP" : `${number(telemetry.cpuPct)}%`],
      ["Disco", telemetry?.diskPct == null ? "Não exposto via SNMP" : `${number(telemetry.diskPct)}%`],
      ["Interfaces", telemetry?.interfaceCount ?? telemetry?.interfaces?.length ?? "—"],
      ["Capacidade da rede", telemetry?.networkCapacityMbps == null ? "—" : `${number(telemetry.networkCapacityMbps)} Mbps`],
      ["Rede recebida", telemetry?.downloadMbps == null ? "Aguardando 2ª coleta" : `${number(telemetry.downloadMbps, 3)} Mbps`],
      ["Rede enviada", telemetry?.uploadMbps == null ? "Aguardando 2ª coleta" : `${number(telemetry.uploadMbps, 3)} Mbps`],
    ];
    const resourceCards = (isPrinter ? printerResourceCards : isNvr ? nvrResourceCards : genericResourceCards)
      .map(([label, value]) => `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");
    const genericIdentity = [
      ["Nome do sistema", telemetry?.systemName || "—"],
      ["Sistema operacional", telemetry?.osName || "—"],
      ["Versão", telemetry?.osVersion || "—"],
      ["Build", telemetry?.osBuild || "—"],
      ["Arquitetura", telemetry?.architecture || "—"],
      ["Processadores lógicos", telemetry?.cpuCores ?? "—"],
      ["Memória instalada", bytes(telemetry?.memoryTotalBytes)],
      ["Tempo ligado", duration(telemetry?.uptimeSeconds)],
    ];
    const printerIdentity = [
      ["Nome do sistema", telemetry?.systemName || "—"],
      ["Modelo / descrição", telemetry?.description || "—"],
      ["Número de série", telemetry?.serialNumber || "—"],
      ["Tempo ligado", duration(telemetry?.uptimeSeconds)],
      ["Interfaces", telemetry?.interfaceCount ?? telemetry?.interfaces?.length ?? "—"],
    ];
    const nvrIdentity = [
      ["Modelo", telemetry?.model || "—"],
      ["Família", telemetry?.productFamily || "—"],
      ["Padrão de vídeo", telemetry?.videoStandard || "—"],
      ["Número de série", telemetry?.serialNumber || "—"],
      ["Firmware", telemetry?.firmwareVersion || "—"],
      ["Sistema operacional", [telemetry?.osName, telemetry?.osVersion].filter(Boolean).join(" ") || "—"],
      ["Tempo ligado", duration(telemetry?.uptimeSeconds)],
    ];
    const identity = (isPrinter ? printerIdentity : isNvr ? nvrIdentity : genericIdentity)
      .map(([label, value]) => `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");
    const disks = telemetry?.disks?.length ? `<div class="detailSection"><h3>Discos</h3><div class="detailTableWrap"><table><thead><tr><th>Volume</th><th>Uso</th><th>Livre</th><th>Total</th></tr></thead><tbody>${telemetry.disks.map((disk) => `<tr><td>${esc(disk.name)}</td><td>${number(disk.usedPct)}%</td><td>${esc(bytes(disk.freeBytes))}</td><td>${esc(bytes(disk.sizeBytes))}</td></tr>`).join("")}</tbody></table></div></div>` : "";
    const unavailableNvrResources = isNvr ? [
      telemetry?.cpuPct == null ? "CPU" : "",
      telemetry?.diskPct == null ? "armazenamento" : "",
    ].filter(Boolean) : [];
    const nvrResourceNotice = unavailableNvrResources.length ? `<div class="detailNotice warning"><strong>Métricas não fornecidas pelo NVR</strong><span>O agente SNMP deste firmware não expõe ${esc(unavailableNvrResources.join(" nem "))} nas tabelas padrão. O monitoramento de disponibilidade, rede e identificação continua funcionando normalmente.</span></div>` : "";
    const interfaces = telemetry?.interfaces?.length ? `<div class="detailSection"><h3>Interfaces monitoradas</h3><div class="detailTags">${telemetry.interfaces.map((name) => `<span>${esc(name)}</span>`).join("")}</div></div>` : "";
    const supplies = telemetry?.supplies?.length ? `<div class="detailSection"><h3>Suprimentos</h3><div class="detailTableWrap"><table><thead><tr><th>Item</th><th>Nível</th><th>Atual</th><th>Capacidade</th></tr></thead><tbody>${telemetry.supplies.map((supply) => `<tr><td>${esc(supply.name)}</td><td>${supply.pct == null ? esc(supply.status || "Não informado") : `${number(supply.pct)}%`}</td><td>${supply.level == null || supply.level < 0 ? "—" : number(supply.level, 0)}</td><td>${supply.capacity == null || supply.capacity < 0 ? "—" : number(supply.capacity, 0)}</td></tr>`).join("")}</tbody></table></div></div>` : "";
    const printerUsage = isPrinter ? renderPrinterUsage(state.printerUsage[device.id]) : "";
    const addressRows = (metric?.addresses?.length ? metric.addresses : device.networkAddresses || []).map((address) => {
      const reachable = address.reachable;
      const stateClass = reachable === true ? "online" : reachable === false ? "offline" : "pending";
      const stateLabel = reachable === true ? "Acessível" : reachable === false ? "Sem resposta" : "Aguardando";
      return `<tr><td><strong>${esc(address.label)}</strong>${address.primary ? '<br><small class="muted">Principal</small>' : ""}</td><td><code>${esc(address.host)}</code></td><td>${address.latencyMs == null ? "—" : `${number(address.latencyMs)} ms`}</td><td><span class="status ${stateClass}">${stateLabel}</span>${address.active ? '<br><small class="muted">em uso</small>' : ""}</td></tr>`;
    }).join("");
    const addresses = `<div class="detailSection"><h3>Endereços e caminhos de rede</h3><div class="detailTableWrap"><table><thead><tr><th>Interface</th><th>IP ou host</th><th>Latência</th><th>Situação</th></tr></thead><tbody>${addressRows}</tbody></table></div></div>`;
    const collectionSummary = isSnmp ? `${telemetry?.interfaceCount ?? telemetry?.interfaces?.length ?? 0} interfaces consultadas` : `${number(telemetry?.series, 0)} séries coletadas`;
    const telemetryBlock = telemetry ? `<div class="detailSection"><div class="detailSectionHead"><h3>${esc(protocol)}</h3><span>${esc(collectionSummary)}</span></div><div class="detailResources">${resourceCards}</div></div>${nvrResourceNotice}<div class="detailSection"><h3>Identificação do equipamento</h3><div class="detailIdentity">${identity}</div></div>${printerUsage}${supplies}${disks}${interfaces}` : `<div class="detailNotice warning"><strong>Sem métricas de ${esc(protocol)} nesta coleta.</strong><span>${esc(metric?.message || "Aguardando a primeira coleta.")}</span><small>${isSnmp ? `Confirme o SNMP somente leitura na porta ${esc(device.snmpPort || 161)} e permita consultas do servidor 192.168.200.254.` : `Confirme se o exporter está iniciado e se a porta ${esc(device.agentPort || 9182)} aceita conexão do servidor 192.168.200.254.`}</small></div>`;
    $("#deviceDetailsBody").innerHTML = `<div class="detailStatus"><div>${statusBadge(metric)}<span>${esc(metric?.message || "Aguardando medição")}</span></div><small>Última coleta: ${esc(dateTime(metric?.checkedAt))}</small></div><div class="detailEndpoint"><span>Coleta</span><strong>${esc(protocol)}</strong><span>Endpoint ativo</span><code>${esc(collectionEndpoint)}</code></div>${addresses}${telemetryBlock}`;
  }

  function openDeviceDetails(id) {
    detailDeviceId = Number(id);
    renderDeviceDetails();
    $("#deviceDetailsModal").classList.remove("hidden");
    $("#refreshDeviceDetails").focus();
    const device = state.devices.find((item) => item.id === detailDeviceId);
    if (device?.tipo === "IMPRESSORA") loadPrinterUsage(detailDeviceId);
  }

  function closeDeviceDetails() {
    $("#deviceDetailsModal").classList.add("hidden");
    detailDeviceId = null;
  }

  async function loadPrinterUsage(deviceId, force = false) {
    if (!force && state.printerUsage[deviceId] && !state.printerUsage[deviceId].error) return;
    state.printerUsage[deviceId] = { loading: true };
    if (detailDeviceId === deviceId) renderDeviceDetails();
    try {
      state.printerUsage[deviceId] = await request(`/devices/${deviceId}/print-usage`);
    } catch (error) {
      state.printerUsage[deviceId] = { error: error.message };
    }
    if (detailDeviceId === deviceId) renderDeviceDetails();
  }

  async function refreshDeviceDetails() {
    const button = $("#refreshDeviceDetails");
    if (!detailDeviceId) return;
    button.disabled = true;
    button.textContent = "Coletando...";
    try {
      const data = await request("/probe", { method: "POST", body: JSON.stringify({ deviceIds: [detailDeviceId] }) });
      state.devices = data.devices || [];
      state.diagnosis = data.diagnosis || [];
      state.speed = data.speed || state.speed;
      renderAll();
      const refreshed = state.devices.find((item) => item.id === detailDeviceId);
      if (refreshed?.tipo === "IMPRESSORA") await loadPrinterUsage(detailDeviceId, true);
      showToast("Informações do equipamento atualizadas.");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = "Atualizar agora";
    }
  }

  async function loadOverview({ quiet = false } = {}) {
    try {
      const data = await request("/overview");
      state.devices = data.devices || [];
      state.diagnosis = data.diagnosis || [];
      state.speed = data.speed || null;
      state.emailAlerts = data.emailAlerts || null;
      state.alertConfiguration = data.alertConfiguration || null;
      state.linkUsage = data.linkUsage || null;
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
      state.speed = data.speed || state.speed;
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

  async function testAlertEmail() {
    const button = $("#testAlertEmail");
    button.disabled = true;
    button.textContent = "Enviando...";
    try {
      const data = await request("/alerts/test-email", { method: "POST", body: "{}" });
      showToast(`E-mail de teste enviado para ${data.recipient}.`);
      await loadOverview({ quiet: true });
    } catch (error) {
      showToast(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = "Enviar e-mail de teste";
    }
  }

  async function saveAlertConfiguration(event) {
    event.preventDefault();
    const button = $("#saveAlertConfig");
    button.disabled = true;
    button.textContent = "Salvando...";
    const payload = {
      notifyInternetDown: $("#notifyInternetDown").checked,
      notifyLinkSlow: $("#notifyLinkSlow").checked,
      notifyLinkUsage: $("#notifyLinkUsage").checked,
      notifyGateway: $("#notifyGateway").checked,
      notifyCpu: $("#notifyCpu").checked,
      notifyMemory: $("#notifyMemory").checked,
      notifyDisk: $("#notifyDisk").checked,
      notifyDeviceNetwork: $("#notifyDeviceNetwork").checked,
      includeConsumers: $("#includeConsumers").checked,
      linkDownloadCapacityMbps: Number($("#linkDownloadCapacity").value || 0),
      linkUploadCapacityMbps: Number($("#linkUploadCapacity").value || 0),
      linkUsageThresholdPct: Number($("#linkUsageThreshold").value || 80),
    };
    try {
      const data = await request("/alerts/config", { method: "PUT", body: JSON.stringify(payload) });
      state.alertConfiguration = data.configuration;
      state.linkUsage = data.linkUsage;
      alertConfigDirty = false;
      renderAlertConfiguration();
      showToast("Configuração de alertas salva para este ambiente.");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = "Salvar configuração";
    }
  }

  async function runSpeedTest() {
    const button = $("#speedTest");
    button.disabled = true;
    button.textContent = "Medindo...";
    try {
      const data = await request("/speed-test", { method: "POST", body: "{}" });
      state.speed = data.speed || null;
      state.diagnosis = data.diagnosis || [];
      renderAll();
      showToast(`Velocidade medida: ${number(state.speed?.downloadMbps)} Mbps ↓ / ${number(state.speed?.uploadMbps)} Mbps ↑.`);
    } catch (error) {
      showToast(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = "Testar velocidade";
    }
  }

  const backupHealthLabel = {
    ONLINE: "Conectado", WARNING: "Atenção", OFFLINE: "Sem contato",
    WAITING: "Aguardando agente", DISABLED: "Inativo",
  };
  const backupRunLabel = { RUNNING: "Executando", SUCCESS: "Concluído", FAILED: "Falhou", SKIPPED: "Ignorado" };
  const backupWeekdayLabel = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
  const backupStatusClass = (value) => ({ ONLINE: "online", SUCCESS: "online", WARNING: "degradado", RUNNING: "degradado", OFFLINE: "offline", FAILED: "offline", WAITING: "pending", DISABLED: "pending", SKIPPED: "pending" })[value] || "pending";
  const backupBadge = (value, labels = backupHealthLabel) => `<span class="status ${backupStatusClass(value)}">${esc(labels[value] || value || "Aguardando")}</span>`;

  function backupWindowSummary(windows) {
    const entries = Object.entries(windows || {}).sort(([left], [right]) => Number(left) - Number(right));
    if (!entries.length) return "Todos os dias, sem limite de janela";
    return entries.map(([day, window]) => {
      const schedule = Array.isArray(window.times) && window.times.length ? `${window.times.join(", ")} ` : "";
      return `${backupWeekdayLabel[Number(day)]}: ${schedule}(${window.start}–${window.end})`;
    }).join(" · ");
  }

  function downloadJson(fileName, payload) {
    const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  function renderBackups() {
    const active = state.backups.filter((job) => job.active);
    const warning = active.filter((job) => ["WARNING", "OFFLINE", "WAITING"].includes(job.health));
    const successes = state.backupRuns.filter((run) => run.status === "SUCCESS" && run.completedAt);
    $("#backupKpiActive").textContent = active.length;
    $("#backupKpiWarning").textContent = warning.length;
    $("#backupKpiLastSuccess").textContent = successes.length ? dateTime(successes[0].completedAt) : "—";
    $("#backupTable").innerHTML = state.backups.map((job) => `<tr>
      <td><strong>${esc(job.name)}</strong><br><small class="muted">${esc(job.machine)} · ${job.databaseType === "FILES" ? `Arquivos: ${(job.sourcePaths || []).map(esc).join(", ")}` : `${esc(job.databaseType)} ${esc(job.databaseHost)}:${Number(job.databasePort)}/${esc(job.databaseName)}`}</small></td>
      <td><strong>${job.times.map(esc).join(" · ")}</strong><br><small class="muted">${esc(backupWindowSummary(job.operatingWindows))}</small><br><small class="muted">Próximo: ${esc(dateTime(job.nextRunAt))}</small></td>
      <td><span class="backupPath">${esc(job.destinationPath)}</span>${job.cloudSyncPath ? `<br><small class="muted">Nuvem: ${esc(job.cloudSyncPath)}</small>` : ""}</td>
      <td>${backupBadge(job.health)}<br><small class="muted">${job.lastSeenAt ? `Contato: ${esc(dateTime(job.lastSeenAt))}` : esc(job.agentId)}</small></td>
      <td>${job.lastRun ? `${backupBadge(job.lastRun.status, backupRunLabel)}<br><small class="muted">${esc(dateTime(job.lastRun.completedAt))} · ${esc(bytes(job.lastRun.sizeBytes))}</small>` : '<span class="muted">Nenhuma execução</span>'}</td>
      <td><div class="tableActions"><button class="smallButton" data-backup-edit="${job.id}" type="button">Editar</button><button class="smallButton" data-backup-token="${job.id}" type="button">Novo JSON</button><button class="smallButton danger" data-backup-delete="${job.id}" type="button">Excluir</button></div></td>
    </tr>`).join("") || '<tr><td colspan="6" class="muted">Nenhum plano de backup configurado.</td></tr>';
    $("#backupRunsTable").innerHTML = state.backupRuns.map((run) => `<tr>
      <td>${esc(dateTime(run.completedAt || run.startedAt))}</td><td><strong>${esc(run.jobName)}</strong><br><small class="muted">${esc(run.machine)}</small></td>
      <td>${backupBadge(run.status, backupRunLabel)}</td><td>${run.tiers.length ? run.tiers.map((tier) => `<span class="backupTier">${esc(tier)}</span>`).join(" ") : "—"}</td>
      <td>${esc(bytes(run.sizeBytes))}</td><td title="${esc(run.filePath)}">${esc(run.message || "—")}</td>
    </tr>`).join("") || '<tr><td colspan="6" class="muted">O agente ainda não reportou execuções.</td></tr>';
  }

  async function loadBackups(options = {}) {
    try {
      const data = await request("/backup/jobs");
      state.backups = data.jobs || [];
      state.backupRuns = data.executions || [];
      renderBackups();
    } catch (error) {
      if (!options.quiet) showToast(error.message, true);
    }
  }

  function openBackup(job = null) {
    editingBackupId = job?.id || null;
    $("#backupModalTitle").textContent = job ? "Editar plano de backup" : "Novo plano de backup";
    $("#backupId").value = job?.id || "";
    $("#backupName").value = job?.name || "Backup banco NanotechSoft";
    $("#backupMachine").value = job?.machine || "";
    $("#backupDatabaseType").value = job?.databaseType || "MYSQL";
    $("#backupDatabaseHost").value = job?.databaseHost || "127.0.0.1";
    $("#backupDatabasePort").value = job?.databasePort || 3306;
    $("#backupDatabaseName").value = job?.databaseName || "notechsoft";
    $("#backupDatabaseUser").value = job?.databaseUser || "";
    $("#backupPasswordEnv").value = job?.passwordEnv || "NANOTECH_BACKUP_DB_PASSWORD";
    $("#backupSourcePaths").value = (job?.sourcePaths || []).join("\n");
    $("#backupDestination").value = job?.destinationPath || "";
    $("#backupCloudPath").value = job?.cloudSyncPath || "";
    $("#backupTimes").value = (job?.times || ["08:00", "16:00"]).join(", ");
    $("#backupTimezone").value = job?.timezone || "America/Sao_Paulo";
    $("#backupDailyRetention").value = job?.dailyRetentionDays || 7;
    $("#backupWeeklyRetention").value = job?.weeklyRetentionWeeks || 5;
    $("#backupMonthlyRetention").value = job?.monthlyRetentionMonths || 12;
    $("#backupActive").checked = job ? Boolean(job.active) : true;
    let windows = job?.operatingWindows || {};
    if (job && !Object.keys(windows).length) {
      windows = Object.fromEntries(backupWeekdayLabel.map((_label, day) => [String(day), {start: "00:00", end: "23:59"}]));
    } else if (!job) {
      windows = Object.fromEntries(backupWeekdayLabel.slice(0, 5).map((_label, day) => [String(day), {start: "07:00", end: "17:00", times: ["08:00", "16:00"]}]));
      windows["5"] = {start: "09:30", end: "11:00", times: ["10:00"]};
    }
    $$('[data-backup-weekday]').forEach((row) => {
      const day = String(row.dataset.backupWeekday);
      const window = windows[day];
      row.querySelector('[data-backup-day-enabled]').checked = Boolean(window);
      row.querySelector('[data-backup-day-times]').value = (window?.times || job?.times || (day === "5" || day === "6" ? ["10:00"] : ["08:00", "16:00"])).join(", ");
      row.querySelector('[data-backup-day-start]').value = window?.start || (day === "5" || day === "6" ? "09:30" : "07:00");
      row.querySelector('[data-backup-day-end]').value = window?.end || (day === "5" || day === "6" ? "11:00" : "17:00");
    });
    toggleBackupWindows();
    toggleBackupFields();
    $("#backupModal").classList.remove("hidden");
    $("#backupName").focus();
  }

  function toggleBackupFields() {
    const files = $("#backupDatabaseType").value === "FILES";
    $$('[data-backup-files]').forEach((element) => element.classList.toggle("hidden", !files));
    $$('[data-backup-database]').forEach((element) => element.classList.toggle("hidden", files));
    $$('[data-backup-db-required]').forEach((element) => { element.required = !files; });
    $("#backupSourcePaths").required = files;
  }

  function toggleBackupWindows() {
    $$('[data-backup-weekday]').forEach((row) => {
      const enabled = row.querySelector('[data-backup-day-enabled]').checked;
      row.classList.toggle("disabled", !enabled);
      row.querySelectorAll('input[type="time"]').forEach((input) => { input.disabled = !enabled; });
    });
  }

  function closeBackup() {
    $("#backupModal").classList.add("hidden");
    editingBackupId = null;
  }

  async function saveBackup(event) {
    event.preventDefault();
    const operatingWindows = {};
    $$('[data-backup-weekday]').forEach((row) => {
      if (!row.querySelector('[data-backup-day-enabled]').checked) return;
      operatingWindows[String(row.dataset.backupWeekday)] = {
        start: row.querySelector('[data-backup-day-start]').value,
        end: row.querySelector('[data-backup-day-end]').value,
        times: row.querySelector('[data-backup-day-times]').value.split(",").map((item) => item.trim()).filter(Boolean),
      };
    });
    const payload = {
      name: $("#backupName").value, machine: $("#backupMachine").value,
      databaseType: $("#backupDatabaseType").value, databaseHost: $("#backupDatabaseHost").value,
      databasePort: Number($("#backupDatabasePort").value), databaseName: $("#backupDatabaseName").value,
      databaseUser: $("#backupDatabaseUser").value, passwordEnv: $("#backupPasswordEnv").value,
      sourcePaths: $("#backupSourcePaths").value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
      destinationPath: $("#backupDestination").value, cloudSyncPath: $("#backupCloudPath").value,
      times: $("#backupTimes").value.split(",").map((item) => item.trim()).filter(Boolean),
      operatingWindows,
      timezone: $("#backupTimezone").value,
      dailyRetentionDays: Number($("#backupDailyRetention").value),
      weeklyRetentionWeeks: Number($("#backupWeeklyRetention").value),
      monthlyRetentionMonths: Number($("#backupMonthlyRetention").value),
      active: $("#backupActive").checked,
    };
    try {
      const data = await request(editingBackupId ? `/backup/jobs/${editingBackupId}` : "/backup/jobs", {
        method: editingBackupId ? "PUT" : "POST", body: JSON.stringify(payload),
      });
      if (data.setup) {
        downloadJson(data.setup.fileName, data.setup.bootstrap);
        showToast("Plano salvo. O JSON confidencial do agente foi baixado.");
      } else {
        showToast("Plano de backup atualizado.");
      }
      closeBackup();
      await loadBackups({ quiet: true });
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function rotateBackupToken(id) {
    const job = state.backups.find((item) => item.id === id);
    if (!job || !window.confirm(`Gerar um novo JSON para ${job.name}? O token anterior deixará de funcionar.`)) return;
    try {
      const data = await request(`/backup/jobs/${id}/rotate-token`, { method: "POST", body: "{}" });
      downloadJson(data.setup.fileName, data.setup.bootstrap);
      await loadBackups({ quiet: true });
      showToast("Novo JSON baixado; substitua o arquivo na máquina executora.");
    } catch (error) { showToast(error.message, true); }
  }

  async function deleteBackup(id) {
    const job = state.backups.find((item) => item.id === id);
    if (!job || !window.confirm(`Excluir o plano ${job.name} e seu histórico? Os arquivos já gravados não serão removidos.`)) return;
    try {
      await request(`/backup/jobs/${id}`, { method: "DELETE" });
      await loadBackups({ quiet: true });
      showToast("Plano excluído; os arquivos externos foram preservados.");
    } catch (error) { showToast(error.message, true); }
  }

  function setView(view, updateHash = true) {
    const known = ["dashboard", "equipamentos", "protocolos", "backup", "historico", "ocupacao-link", "config"];
    if (!known.includes(view)) view = "dashboard";
    $$(".techView").forEach((element) => element.classList.toggle("hidden", element.dataset.page !== view));
    $$(".tab").forEach((element) => element.classList.toggle("active", element.dataset.view === view));
    if (updateHash) history.replaceState(null, "", view === "dashboard" ? location.pathname : `#${view}`);
    if (view === "historico") loadHistory();
    if (view === "ocupacao-link") loadLinkUsageReport();
    if (view === "backup") loadBackups();
  }

  function openDevice(device = null) {
    editingId = device?.id || null;
    $("#deviceModalTitle").textContent = device ? "Editar equipamento" : "Novo equipamento";
    $("#deviceId").value = device?.id || "";
    $("#deviceName").value = device?.nome || "";
    $("#deviceType").value = device?.tipo || "OUTRO";
    $("#deviceHost").value = device?.host || "";
    $("#deviceAddresses").value = addressesToText(device?.networkAddresses || []);
    $("#devicePort").value = device?.porta || "";
    $("#deviceProbe").value = device?.sonda || "ICMP";
    $("#deviceLocation").value = device?.localizacao || "";
    $("#deviceLatency").value = device?.latenciaAlertaMs ?? 80;
    $("#deviceLoss").value = device?.perdaAlertaPct ?? 5;
    $("#deviceDownload").value = device?.downloadAlertMbps ?? 50;
    $("#deviceUpload").value = device?.uploadAlertMbps ?? 10;
    $("#deviceCpu").value = device?.cpuAlertPct ?? 90;
    $("#deviceMemory").value = device?.memoryAlertPct ?? 90;
    $("#deviceDisk").value = device?.diskAlertPct ?? 90;
    $("#deviceTraffic").value = device?.trafficAlertMbps ?? 100;
    $("#deviceSnmpCommunity").value = "";
    $("#deviceSnmpCommunity").placeholder = device?.hasSnmpCommunity ? "Configurada — deixe vazio para manter" : "Comunidade somente leitura";
    $("#deviceSnmpPort").value = device?.snmpPort ?? 161;
    $("#deviceAgentPort").value = device?.agentPort || "";
    $("#deviceAgentPath").value = device?.agentPath || "/metrics";
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
      networkAddresses: addressesFromText($("#deviceAddresses").value),
      porta: $("#devicePort").value ? Number($("#devicePort").value) : null,
      sonda: $("#deviceProbe").value,
      localizacao: $("#deviceLocation").value,
      latenciaAlertaMs: Number($("#deviceLatency").value),
      perdaAlertaPct: Number($("#deviceLoss").value),
      downloadAlertMbps: Number($("#deviceDownload").value),
      uploadAlertMbps: Number($("#deviceUpload").value),
      cpuAlertPct: Number($("#deviceCpu").value),
      memoryAlertPct: Number($("#deviceMemory").value),
      diskAlertPct: Number($("#deviceDisk").value),
      trafficAlertMbps: Number($("#deviceTraffic").value),
      snmpCommunity: $("#deviceSnmpCommunity").value,
      snmpPort: Number($("#deviceSnmpPort").value || 161),
      agentPort: $("#deviceAgentPort").value ? Number($("#deviceAgentPort").value) : null,
      agentPath: $("#deviceAgentPath").value || "/metrics",
      preserveSnmpCommunity: Boolean(editingId),
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
      const ignored = Number(data.ignoredRegistered || 0);
      results.classList.toggle("muted", !found.length);
      const ignoredText = ignored ? `<p class="discoveryNote">${ignored} endereço${ignored > 1 ? "s" : ""} já cadastrado${ignored > 1 ? "s" : ""} foi${ignored > 1 ? "ram" : ""} ignorado${ignored > 1 ? "s" : ""}.</p>` : "";
      results.innerHTML = found.length ? `${found.map((item) => `<div class="discoveryItem">
        <div><strong>${esc(item.host)}</strong><br><small class="muted">Portas: ${item.ports.map(esc).join(", ")}</small></div>
        ${item.registered ? '<span class="status online">Cadastrada</span>' : `<button class="smallButton" data-add-printer="${esc(item.host)}" data-printer-port="${Number(item.suggestedPort)}" type="button">Cadastrar</button>`}
      </div>`).join("")}${ignoredText}` : `Nenhuma nova impressora foi encontrada.${ignoredText}`;
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

  async function discoverComputers() {
    const button = $("#discoverComputers");
    const results = $("#computerDiscoveryResults");
    button.disabled = true;
    button.textContent = "Procurando...";
    results.classList.add("muted");
    results.textContent = "Consultando ICMP, NetBIOS e serviços de Windows/Linux...";
    try {
      const data = await request("/discover-computers", {
        method: "POST",
        body: JSON.stringify({ subnet: $("#computerDiscoverySubnet").value }),
      });
      const found = data.devices || [];
      results.classList.toggle("muted", !found.length);
      results.innerHTML = found.length ? found.map((item) => `<div class="discoveryItem">
        <div><strong>${esc(item.name)}</strong> <span class="muted">${esc(item.host)}</span><br><small class="muted">${esc(item.osFamily)} · portas: ${item.ports.length ? item.ports.map(esc).join(", ") : "nenhuma porta TCP identificada"}</small></div>
        ${item.registered ? `<span class="status online">${esc(item.registeredName || "Cadastrado")}</span>` : `<button class="smallButton" data-add-computer="${esc(item.host)}" data-computer-name="${esc(item.name)}" data-computer-type="${esc(item.suggestedType)}" data-computer-os="${esc(item.osFamily)}" type="button">Cadastrar</button>`}
      </div>`).join("") : "Nenhum computador respondeu aos testes desta varredura.";
    } catch (error) {
      results.textContent = error.message;
      showToast(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = "Varrer Windows e Linux";
    }
  }

  async function addComputer(button) {
    try {
      await request("/devices", {
        method: "POST",
        body: JSON.stringify({
          nome: button.dataset.computerName, tipo: button.dataset.computerType,
          identityName: button.dataset.computerName,
          host: button.dataset.addComputer, porta: null, sonda: "ICMP",
          localizacao: "Rede principal", observacoes: `${button.dataset.computerOs} localizado pela descoberta da rede`,
          critico: false, ativo: true, latenciaAlertaMs: 30, perdaAlertaPct: 5,
          downloadAlertMbps: 50, uploadAlertMbps: 10, cpuAlertPct: 90,
          memoryAlertPct: 90, diskAlertPct: 90, trafficAlertMbps: 100,
          snmpPort: 161, agentPort: null, agentPath: "/metrics",
        }),
      });
      await loadOverview();
      await discoverComputers();
      showToast("Computador cadastrado.");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  function renderLinkUsageChart(report) {
    const svg = $("#linkUsageChart");
    const timeline = report?.timeline || [];
    if (!timeline.length || !report?.capacityConfigured) {
      const message = report?.capacityConfigured ? "Sem telemetria no período" : "Configure a largura contratada do link";
      svg.innerHTML = `<text x="500" y="135" text-anchor="middle" fill="#66736e" font-size="18">${esc(message)}</text>`;
      return;
    }
    const values = timeline.flatMap((item) => [Number(item.downloadPct || 0), Number(item.uploadPct || 0)]);
    const maximum = Math.max(100, ...values) * 1.08;
    const xAt = (index) => timeline.length === 1 ? 500 : 24 + index * (952 / (timeline.length - 1));
    const points = (field) => timeline.map((item, index) => {
      const y = 235 - Math.min(maximum, Number(item[field] || 0)) / maximum * 205;
      return `${xAt(index).toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    const grid = [30, 81, 133, 184, 235].map((y, index) => {
      const label = number(maximum * (4 - index) / 4, 0);
      return `<line class="chartGrid" x1="24" y1="${y}" x2="976" y2="${y}"/><text class="linkChartAxis" x="20" y="${y + 4}" text-anchor="end">${label}%</text>`;
    }).join("");
    const tickCount = Math.min(6, timeline.length);
    const tickIndexes = tickCount === 1 ? [0] : Array.from(
      { length: tickCount }, (_, index) => Math.round(index * (timeline.length - 1) / (tickCount - 1)),
    );
    const ticks = [...new Set(tickIndexes)].map((itemIndex, tickIndex, allTicks) => {
      const x = xAt(itemIndex);
      const at = new Date(timeline[itemIndex].checkedAt);
      const label = at.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
      const anchor = tickIndex === 0 ? "start" : tickIndex === allTicks.length - 1 ? "end" : "middle";
      return `<line class="chartTimeGrid" x1="${x}" y1="30" x2="${x}" y2="235"/><text class="chartTime" x="${x}" y="260" text-anchor="${anchor}">${esc(label)}</text>`;
    }).join("");
    svg.innerHTML = `${grid}${ticks}<polyline class="linkChartDownload" points="${points("downloadPct")}"/><polyline class="linkChartUpload" points="${points("uploadPct")}"/>`;
  }

  function renderLinkUsageReport() {
    const report = state.linkUsageReport;
    if (!report) return;
    $("#linkReportSummary").innerHTML = [
      `<article class="kpi speed"><span>Link contratado</span><strong>${number(report.downloadCapacityMbps)} Mbps ↓</strong><small>${number(report.uploadCapacityMbps)} Mbps ↑</small></article>`,
      `<article class="kpi"><span>Ocupação média</span><strong>${report.averageUsagePct == null ? "—" : `${number(report.averageUsagePct)}%`}</strong><small>maior direção de cada intervalo</small></article>`,
      `<article class="kpi warning"><span>Pico do período</span><strong>${report.peakUsagePct == null ? "—" : `${number(report.peakUsagePct)}%`}</strong><small>da largura total configurada</small></article>`,
      `<article class="kpi"><span>Dispositivos</span><strong>${Number(report.devices?.length || 0).toLocaleString("pt-BR")}</strong><small>com telemetria de rede</small></article>`,
    ].join("");
    renderLinkUsageChart(report);

    const devices = report.devices || [];
    $("#linkDeviceSummaryTable").innerHTML = devices.map((item) => `<tr>
      <td><strong>${esc(item.name)}</strong><br><small class="muted">${esc(item.host)}</small></td>
      <td>${number(item.averageDownloadMbps, 3)} Mbps<br><small class="muted">${item.averageDownloadPct == null ? "capacidade não configurada" : `${number(item.averageDownloadPct)}% do link`}</small></td>
      <td>${number(item.peakDownloadMbps, 3)} Mbps<br><strong>${item.peakDownloadPct == null ? "—" : `${number(item.peakDownloadPct)}%`}</strong></td>
      <td>${number(item.averageUploadMbps, 3)} Mbps<br><small class="muted">${item.averageUploadPct == null ? "capacidade não configurada" : `${number(item.averageUploadPct)}% do link`}</small></td>
      <td>${number(item.peakUploadMbps, 3)} Mbps<br><strong>${item.peakUploadPct == null ? "—" : `${number(item.peakUploadPct)}%`}</strong></td>
      <td>${Number(item.sampleCount || 0).toLocaleString("pt-BR")}<br><small class="muted">até ${esc(dateTime(item.lastMeasuredAt))}</small></td>
    </tr>`).join("") || '<tr><td colspan="6" class="muted">Nenhum dispositivo enviou telemetria de rede neste período.</td></tr>';

    const deviceSelect = $("#linkReportDevice");
    const selected = deviceSelect.value;
    deviceSelect.innerHTML = `<option value="">Todos os dispositivos</option>${devices.map((item) => `<option value="${item.deviceId}">${esc(item.name)} — ${esc(item.host)}</option>`).join("")}`;
    if (devices.some((item) => String(item.deviceId) === selected)) deviceSelect.value = selected;
    const selectedDevice = deviceSelect.value;
    const samples = [...(report.samples || [])]
      .filter((item) => !selectedDevice || String(item.deviceId) === selectedDevice)
      .reverse()
      .slice(0, 1000);
    $("#linkUsageHistoryTable").innerHTML = samples.map((item) => `<tr>
      <td>${esc(dateTime(item.checkedAt))}</td><td><strong>${esc(item.name)}</strong><br><small class="muted">${esc(item.host)}</small></td>
      <td>${number(item.downloadMbps, 3)} Mbps</td><td><strong>${item.downloadPct == null ? "—" : `${number(item.downloadPct)}%`}</strong></td>
      <td>${number(item.uploadMbps, 3)} Mbps</td><td><strong>${item.uploadPct == null ? "—" : `${number(item.uploadPct)}%`}</strong></td>
      <td>${Number(item.sampleCount || 0).toLocaleString("pt-BR")}</td>
    </tr>`).join("") || '<tr><td colspan="7" class="muted">Sem amostras para o filtro selecionado.</td></tr>';
  }

  async function loadLinkUsageReport() {
    const button = $("#refreshLinkReport");
    button.disabled = true;
    button.textContent = "Carregando...";
    try {
      const hours = Number($("#linkReportHours").value || 168);
      state.linkUsageReport = await request(`/link-usage-history?hours=${hours}`);
      renderLinkUsageReport();
    } catch (error) {
      showToast(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = "Atualizar relatório";
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
      <td>${esc(metric.message || "—")}</td>
    </tr>`).join("") || '<tr><td colspan="7" class="muted">Ainda não há medições neste período.</td></tr>';
    $("#speedHistoryTable").innerHTML = [...state.speedMetrics].reverse().slice(0, 300).map((metric) => `<tr>
      <td>${esc(dateTime(metric.checkedAt))}</td><td>${statusBadge(metric)}</td>
      <td>${number(metric.downloadMbps)} Mbps</td><td>${number(metric.uploadMbps)} Mbps</td>
      <td>${number(metric.latencyMs)} ms</td>
    </tr>`).join("") || '<tr><td colspan="5" class="muted">Ainda não há testes de velocidade neste período.</td></tr>';
  }

  function renderChart(metrics) {
    const svg = $("#historyChart");
    if (!metrics.length) {
      svg.innerHTML = '<text x="500" y="135" text-anchor="middle" fill="#66736e" font-size="18">Sem dados no período</text>';
      return;
    }
    const latencyMax = Math.max(10, ...metrics.map((item) => Number(item.latencyMs || 0))) * 1.1;
    const xAt = (index) => metrics.length === 1 ? 500 : 24 + index * (952 / (metrics.length - 1));
    const point = (item, index, field, max) => {
      const x = xAt(index);
      const y = 235 - Math.min(max, Number(item[field] || 0)) / max * 205;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    };
    const latency = metrics.map((item, index) => point(item, index, "latencyMs", latencyMax)).join(" ");
    const loss = metrics.map((item, index) => point(item, index, "packetLossPct", 100)).join(" ");
    const grid = [30, 81, 133, 184, 235].map((y) => `<line class="chartGrid" x1="24" y1="${y}" x2="976" y2="${y}" />`).join("");
    const firstAt = new Date(metrics[0].checkedAt);
    const lastAt = new Date(metrics[metrics.length - 1].checkedAt);
    const showDate = lastAt - firstAt > 36 * 60 * 60 * 1000;
    const tickCount = Math.min(6, metrics.length);
    const tickIndexes = tickCount === 1 ? [0] : Array.from(
      { length: tickCount },
      (_, index) => Math.round(index * (metrics.length - 1) / (tickCount - 1)),
    );
    const timeTicks = [...new Set(tickIndexes)].map((metricIndex, tickIndex, allTicks) => {
      const x = xAt(metricIndex);
      const at = new Date(metrics[metricIndex].checkedAt);
      const label = at.toLocaleString("pt-BR", showDate
        ? { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }
        : { hour: "2-digit", minute: "2-digit" });
      const anchor = allTicks.length === 1 ? "middle" : tickIndex === 0 ? "start" : tickIndex === allTicks.length - 1 ? "end" : "middle";
      return `<line class="chartTimeGrid" x1="${x}" y1="30" x2="${x}" y2="235"/><text class="chartTime" x="${x}" y="260" text-anchor="${anchor}">${esc(label)}</text>`;
    }).join("");
    svg.innerHTML = `${grid}${timeTicks}<polyline class="chartLatency" points="${latency}"/><polyline class="chartLoss" points="${loss}"/>`;
  }

  async function loadHistory() {
    const deviceId = Number($("#historyDevice").value || state.devices[0]?.id || 0);
    if (!deviceId) { state.metrics = []; renderHistory(); return; }
    try {
      const hours = Number($("#historyHours").value || 24);
      const [data, speedData] = await Promise.all([
        request(`/history?deviceId=${deviceId}&hours=${hours}`),
        request(`/speed-history?hours=${hours}`),
      ]);
      state.metrics = data.metrics || [];
      state.speedMetrics = speedData.metrics || [];
      renderHistory();
    } catch (error) {
      showToast(error.message, true);
    }
  }

  $("#probeAll").addEventListener("click", probeAll);
  $("#speedTest").addEventListener("click", runSpeedTest);
  $("#testAlertEmail").addEventListener("click", testAlertEmail);
  $("#alertConfigForm").addEventListener("submit", saveAlertConfiguration);
  $("#alertConfigForm").addEventListener("input", () => { alertConfigDirty = true; });
  $("#newDevice").addEventListener("click", () => openDevice());
  $("#newBackup").addEventListener("click", () => openBackup());
  $("#refreshBackups").addEventListener("click", () => loadBackups());
  $("#backupForm").addEventListener("submit", saveBackup);
  $("#backupDatabaseType").addEventListener("change", toggleBackupFields);
  $("#backupOperatingWindows").addEventListener("change", toggleBackupWindows);
  $("#closeBackupModal").addEventListener("click", closeBackup);
  $("#cancelBackup").addEventListener("click", closeBackup);
  $("#backupModal").addEventListener("click", (event) => { if (event.target.id === "backupModal") closeBackup(); });
  $("#deviceForm").addEventListener("submit", saveDevice);
  $("#closeDeviceModal").addEventListener("click", closeDevice);
  $("#cancelDevice").addEventListener("click", closeDevice);
  $("#deviceModal").addEventListener("click", (event) => { if (event.target.id === "deviceModal") closeDevice(); });
  $("#closeDeviceDetails").addEventListener("click", closeDeviceDetails);
  $("#closeDeviceDetailsFooter").addEventListener("click", closeDeviceDetails);
  $("#refreshDeviceDetails").addEventListener("click", refreshDeviceDetails);
  $("#deviceDetailsModal").addEventListener("click", (event) => { if (event.target.id === "deviceDetailsModal") closeDeviceDetails(); });
  $("#discoverPrinters").addEventListener("click", discover);
  $("#discoverComputers").addEventListener("click", discoverComputers);
  $("#historyDevice").addEventListener("change", loadHistory);
  $("#historyHours").addEventListener("change", loadHistory);
  $("#linkReportHours").addEventListener("change", loadLinkUsageReport);
  $("#refreshLinkReport").addEventListener("click", loadLinkUsageReport);
  $("#linkReportDevice").addEventListener("change", renderLinkUsageReport);
  $$(".tab").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  $$('[data-open-view]').forEach((button) => button.addEventListener("click", () => setView(button.dataset.openView)));
  $("#deviceTable").addEventListener("click", (event) => {
    const edit = event.target.closest("[data-edit]");
    const remove = event.target.closest("[data-delete]");
    if (edit) return openDevice(state.devices.find((device) => device.id === Number(edit.dataset.edit)));
    if (remove) return deleteDevice(Number(remove.dataset.delete));
    const details = event.target.closest("[data-details]");
    if (details) openDeviceDetails(details.dataset.details);
  });
  $("#deviceTable").addEventListener("keydown", (event) => {
    if (!["Enter", " "].includes(event.key) || event.target.closest("button")) return;
    const details = event.target.closest("[data-details]");
    if (details) { event.preventDefault(); openDeviceDetails(details.dataset.details); }
  });
  $("#deviceCards").addEventListener("click", (event) => {
    const details = event.target.closest("[data-details]");
    if (details) openDeviceDetails(details.dataset.details);
  });
  $("#deviceCards").addEventListener("keydown", (event) => {
    if (!["Enter", " "].includes(event.key)) return;
    const details = event.target.closest("[data-details]");
    if (details) { event.preventDefault(); openDeviceDetails(details.dataset.details); }
  });
  $("#discoveryResults").addEventListener("click", (event) => {
    const button = event.target.closest("[data-add-printer]");
    if (button) addPrinter(button.dataset.addPrinter, Number(button.dataset.printerPort));
  });
  $("#computerDiscoveryResults").addEventListener("click", (event) => {
    const button = event.target.closest("[data-add-computer]");
    if (button) addComputer(button);
  });
  $("#diagnosisList").addEventListener("click", (event) => {
    const item = event.target.closest("[data-history-device]");
    if (!item) return;
    $("#historyDevice").value = item.dataset.historyDevice;
    setView("historico");
  });
  $("#backupTable").addEventListener("click", (event) => {
    const edit = event.target.closest("[data-backup-edit]");
    const rotate = event.target.closest("[data-backup-token]");
    const remove = event.target.closest("[data-backup-delete]");
    if (edit) return openBackup(state.backups.find((job) => job.id === Number(edit.dataset.backupEdit)));
    if (rotate) return rotateBackupToken(Number(rotate.dataset.backupToken));
    if (remove) return deleteBackup(Number(remove.dataset.backupDelete));
  });
  window.addEventListener("hashchange", () => setView(location.hash.slice(1) || "dashboard", false));
  window.addEventListener("keydown", (event) => { if (event.key === "Escape") { closeDevice(); closeDeviceDetails(); closeBackup(); } });

  setView(location.hash.slice(1) || "dashboard", false);
  loadOverview();
  window.setInterval(() => loadOverview({ quiet: true }), 15000);
  window.setInterval(() => { if (location.hash === "#backup") loadBackups({ quiet: true }); }, 30000);
})();
