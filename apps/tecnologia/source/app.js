(() => {
  "use strict";

  const API = "/apps/tecnologia/api";
  const state = { devices: [], diagnosis: [], emailAlerts: null, monitorIntervalSeconds: 60, speed: null, metrics: [], speedMetrics: [], printerUsage: {} };
  let editingId = null;
  let detailDeviceId = null;
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
    if (!usage || usage.loading) return '<div class="detailSection printerUsage"><h3>Impressões da semana</h3><p class="muted">Calculando páginas impressas...</p></div>';
    if (usage.error) return `<div class="detailSection printerUsage"><h3>Impressões da semana</h3><div class="detailNotice warning"><span>${esc(usage.error)}</span></div></div>`;
    if (!usage.hasComparisons) return '<div class="detailSection printerUsage"><h3>Impressões da semana</h3><p class="muted">Aguardando pelo menos duas leituras do contador de páginas.</p></div>';

    const days = usage.days || [];
    const chartWidth = 640;
    const chartHeight = 150;
    const left = 34;
    const right = 16;
    const top = 24;
    const bottom = 42;
    const plotWidth = chartWidth - left - right;
    const plotHeight = chartHeight - top - bottom;
    const maximum = Math.max(1, ...days.map((day) => Number(day.pages || 0)));
    const points = days.map((day, index) => {
      const x = days.length === 1 ? left + (plotWidth / 2) : left + ((plotWidth * index) / (days.length - 1));
      const y = top + plotHeight - ((Number(day.pages || 0) / maximum) * plotHeight);
      return { ...day, x, y };
    });
    const polyline = points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
    const period = `${new Date(`${usage.periodStart}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })} a ${new Date(`${usage.periodEnd}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })}`;
    const coverageNote = !usage.todayComplete && usage.coverageStartedAt
      ? `<p class="printerUsageNote">Contagem disponível desde ${esc(dateTime(usage.coverageStartedAt))}; páginas anteriores à primeira leitura SNMP não podem ser recuperadas.</p>`
      : "";
    const pointMarkup = points.map((point) => `<g>
      <circle cx="${point.x}" cy="${point.y}" r="4"></circle>
      <text class="printerChartValue" x="${point.x}" y="${Math.max(12, point.y - 9)}">${Number(point.pages || 0).toLocaleString("pt-BR")}</text>
      <text class="printerChartLabel" x="${point.x}" y="${chartHeight - 12}">${esc(point.label)}</text>
    </g>`).join("");
    return `<div class="detailSection printerUsage">
      <div class="detailSectionHead"><h3>Impressões da semana</h3><span>${esc(period)}</span></div>
      <div class="printerUsageSummary">
        <div><span>Impressas hoje</span><strong>${Number(usage.todayPages || 0).toLocaleString("pt-BR")}</strong><small>páginas</small></div>
        <div><span>Total da semana</span><strong>${Number(usage.weekPages || 0).toLocaleString("pt-BR")}</strong><small>páginas</small></div>
      </div>
      <div class="printerChartWrap"><svg class="printerChart" viewBox="0 0 ${chartWidth} ${chartHeight}" role="img" aria-label="Páginas impressas por dia nesta semana">
        <line x1="${left}" y1="${top + plotHeight}" x2="${chartWidth - right}" y2="${top + plotHeight}"></line>
        ${points.length > 1 ? `<polyline points="${polyline}"></polyline>` : ""}
        ${pointMarkup}
      </svg></div>${coverageNote}
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

  function setView(view, updateHash = true) {
    const known = ["dashboard", "equipamentos", "protocolos", "historico"];
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
  $("#newDevice").addEventListener("click", () => openDevice());
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
  window.addEventListener("hashchange", () => setView(location.hash.slice(1) || "dashboard", false));
  window.addEventListener("keydown", (event) => { if (event.key === "Escape") { closeDevice(); closeDeviceDetails(); } });

  setView(location.hash.slice(1) || "dashboard", false);
  loadOverview();
  window.setInterval(() => loadOverview({ quiet: true }), 15000);
})();
