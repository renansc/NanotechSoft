(function () {
  const root = document.body;
  const viewerMode = root.dataset.viewerMode || "internal";
  const initialExamId = String(root.dataset.examId || "");
  const shareSlug = String(root.dataset.shareSlug || "");

  const state = {
    viewerMode,
    selectedExamId: initialExamId,
    workspace: null,
    shares: [],
    share: null,
    shareExams: [],
    lastCreatedShare: null,
    shareFormExamId: "",
    assets: [],
    seriesGroups: [],
    seriesFilter: "all",
    selectedAssetKey: "",
    previewObjectUrl: "",
    previewToken: 0,
    previewDebounce: null,
    zoom: 1,
    panX: 0,
    panY: 0,
    invert: false,
    wc: null,
    ww: null,
    defaultWc: null,
    defaultWw: null,
    windowDirty: false,
    dragging: false,
    dragStartX: 0,
    dragStartY: 0,
    dragOriginX: 0,
    dragOriginY: 0,
  };

  const ui = {
    title: document.getElementById("viewerTitle"),
    subtitle: document.getElementById("viewerSubtitle"),
    examPickerWrap: document.getElementById("viewerExamPickerWrap"),
    examPicker: document.getElementById("viewerExamPicker"),
    studyMeta: document.getElementById("viewerStudyMeta"),
    seriesRail: document.getElementById("viewerSeriesRail"),
    statusLine: document.getElementById("viewerStatusLine"),
    stageEmpty: document.getElementById("viewerStageEmpty"),
    canvas: document.getElementById("viewerCanvas"),
    image: document.getElementById("viewerImage"),
    filmstrip: document.getElementById("viewerFilmstrip"),
    toast: document.getElementById("viewerToast"),
    refreshBtn: document.getElementById("viewerRefresh"),
    invertBtn: document.getElementById("invertBtn"),
    zoomInBtn: document.getElementById("zoomInBtn"),
    zoomOutBtn: document.getElementById("zoomOutBtn"),
    zoomResetBtn: document.getElementById("zoomResetBtn"),
    fitBtn: document.getElementById("fitBtn"),
    wcSlider: document.getElementById("wcSlider"),
    wwSlider: document.getElementById("wwSlider"),
    wcValue: document.getElementById("wcValue"),
    wwValue: document.getElementById("wwValue"),
    dicomDownloadLink: document.getElementById("dicomDownloadLink"),
    reportForm: document.getElementById("viewerReportForm"),
    uploadForm: document.getElementById("viewerUploadForm"),
    shareForm: document.getElementById("viewerShareForm"),
    attachmentList: document.getElementById("viewerAttachmentList"),
    shareCreated: document.getElementById("viewerShareCreated"),
    shareList: document.getElementById("viewerShareList"),
    shareInfo: document.getElementById("viewerShareInfo"),
  };

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>\"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[char]));
  }

  function showToast(message, error = false) {
    if (!ui.toast) return;
    ui.toast.textContent = message;
    ui.toast.classList.remove("hidden");
    ui.toast.style.background = error ? "rgba(150, 28, 49, 0.95)" : "rgba(45, 24, 32, 0.94)";
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => ui.toast.classList.add("hidden"), 3600);
  }

  function setStatus(message, error = false) {
    if (!ui.statusLine) return;
    ui.statusLine.textContent = message || "";
    ui.statusLine.classList.toggle("error", Boolean(error));
  }

  function dateTimeLabel(value) {
    if (!value) return "-";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return parsed.toLocaleString("pt-BR");
  }

  async function api(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
    if (!isFormData && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    const response = await fetch(path, { ...options, headers });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401 && viewerMode === "share") {
        window.location.href = `/share/${encodeURIComponent(shareSlug)}`;
        throw new Error("Sessao expirada.");
      }
      throw new Error(payload.error || "Erro ao carregar o viewer.");
    }
    return payload;
  }

  function metaItem(label, value) {
    return `<div class="meta-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "-")}</strong></div>`;
  }

  function attachmentUrl(attachmentId) {
    return viewerMode === "share"
      ? `/share/${encodeURIComponent(shareSlug)}/media/exam-attachments/${attachmentId}`
      : `/media/exam-attachments/${attachmentId}`;
  }

  function dicomPreviewUrl(sopInstanceUid, extra = {}) {
    const params = new URLSearchParams();
    Object.entries(extra).forEach(([key, value]) => {
      if (value === null || value === undefined || value === "") return;
      params.set(key, String(value));
    });
    const base = viewerMode === "share"
      ? `/share/${encodeURIComponent(shareSlug)}/media/pacs/objects/${encodeURIComponent(sopInstanceUid)}/preview.png`
      : `/media/pacs/objects/${encodeURIComponent(sopInstanceUid)}/preview.png`;
    const query = params.toString();
    return query ? `${base}?${query}` : base;
  }

  function dicomDownloadUrl(sopInstanceUid) {
    return `/media/pacs/objects/${encodeURIComponent(sopInstanceUid)}?download=1`;
  }

  function getWorkspaceExam() {
    return state.workspace?.exam || null;
  }

  function buildAssets() {
    const workspace = state.workspace || {};
    const pacs = workspace.pacs || {};
    const seriesById = new Map((pacs.series || []).map((series) => [String(series.seriesinstanceuid || ""), series]));

    const dicomAssets = (pacs.instances || [])
      .slice()
      .sort((left, right) => {
        const leftSeries = String(left.seriesinstanceuid || "");
        const rightSeries = String(right.seriesinstanceuid || "");
        if (leftSeries !== rightSeries) return leftSeries.localeCompare(rightSeries);
        return Number(left.imagenumber || 0) - Number(right.imagenumber || 0);
      })
      .map((instance, index) => {
        const seriesUid = String(instance.seriesinstanceuid || "");
        const series = seriesById.get(seriesUid) || {};
        return {
          key: `dicom:${instance.sopinstanceuid}`,
          groupKey: seriesUid ? `series:${seriesUid}` : "series:ungrouped",
          type: "dicom",
          sopInstanceUid: String(instance.sopinstanceuid),
          label: series.seriesdescription
            ? `${series.seriesdescription} • IMG ${instance.imagenumber || index + 1}`
            : `Instancia DICOM ${instance.imagenumber || index + 1}`,
          shortLabel: `IMG ${instance.imagenumber || index + 1}`,
          meta: `${series.modality || getWorkspaceExam()?.modality || "-"} • ${dateTimeLabel(instance.receivedat)}`,
          thumbUrl: "",
          downloadUrl: viewerMode === "internal" ? dicomDownloadUrl(instance.sopinstanceuid) : "",
          receivedAt: instance.receivedat,
        };
      });

    const imageAttachments = (workspace.attachments || [])
      .filter((attachment) => attachment.is_image && attachment.is_available !== false)
      .map((attachment) => ({
        key: `attachment:${attachment.id}`,
        groupKey: "attachments",
        type: "image",
        attachmentId: attachment.id,
        label: attachment.original_name || attachment.stored_name || `Anexo ${attachment.id}`,
        shortLabel: attachment.original_name || attachment.stored_name || `Anexo ${attachment.id}`,
        meta: `${attachment.mime_type || "imagem"} • ${dateTimeLabel(attachment.created_at)}`,
        thumbUrl: attachmentUrl(attachment.id),
        sourceUrl: attachmentUrl(attachment.id),
      }));

    return [...dicomAssets, ...imageAttachments];
  }

  function buildSeriesGroups() {
    const groups = [{ key: "all", label: "Tudo", detail: `${state.assets.length} item(ns)` }];
    const series = state.workspace?.pacs?.series || [];
    series.forEach((item) => {
      const key = `series:${item.seriesinstanceuid || "ungrouped"}`;
      const count = state.assets.filter((asset) => asset.groupKey === key).length;
      if (!count) return;
      groups.push({
        key,
        label: item.seriesdescription || `Serie ${item.seriesnumber || "-"}`,
        detail: `${count} imagem(ns) • ${item.modality || "-"}`,
      });
    });
    const attachmentCount = state.assets.filter((asset) => asset.groupKey === "attachments").length;
    if (attachmentCount) {
      groups.push({
        key: "attachments",
        label: "Anexos Web",
        detail: `${attachmentCount} imagem(ns)`,
      });
    }
    return groups;
  }

  function filteredAssets() {
    if (state.seriesFilter === "all") return state.assets;
    return state.assets.filter((asset) => asset.groupKey === state.seriesFilter);
  }

  function currentAsset() {
    return state.assets.find((asset) => asset.key === state.selectedAssetKey) || null;
  }

  function revokePreviewObjectUrl() {
    if (state.previewObjectUrl) {
      URL.revokeObjectURL(state.previewObjectUrl);
      state.previewObjectUrl = "";
    }
  }

  function resetViewport() {
    state.zoom = 1;
    state.panX = 0;
    state.panY = 0;
    if (ui.zoomResetBtn) ui.zoomResetBtn.textContent = "100%";
    applyTransform();
  }

  function applyTransform() {
    if (!ui.image) return;
    ui.image.style.transform = `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})`;
  }

  function updateWindowControls() {
    const asset = currentAsset();
    const isDicom = asset?.type === "dicom";
    ui.invertBtn.disabled = !isDicom;
    ui.wcSlider.disabled = !isDicom;
    ui.wwSlider.disabled = !isDicom;
    ui.dicomDownloadLink.classList.toggle("hidden", !(isDicom && viewerMode === "internal" && asset.downloadUrl));
    if (isDicom && asset.downloadUrl) ui.dicomDownloadLink.href = asset.downloadUrl;

    if (!isDicom) {
      ui.wcValue.textContent = "-";
      ui.wwValue.textContent = "-";
      return;
    }

    const baseWc = Number.isFinite(state.defaultWc) ? state.defaultWc : 40;
    const baseWw = Number.isFinite(state.defaultWw) ? Math.max(state.defaultWw, 1) : 400;
    const wcMin = Math.round(baseWc - Math.max(baseWw * 2, 1024));
    const wcMax = Math.round(baseWc + Math.max(baseWw * 2, 1024));
    const wwMax = Math.max(Math.round(baseWw * 4), 256);
    ui.wcSlider.min = String(wcMin);
    ui.wcSlider.max = String(wcMax);
    ui.wwSlider.min = "1";
    ui.wwSlider.max = String(wwMax);
    ui.wcSlider.value = String(Math.round(Number.isFinite(state.wc) ? state.wc : baseWc));
    ui.wwSlider.value = String(Math.round(Number.isFinite(state.ww) ? state.ww : baseWw));
    ui.wcValue.textContent = String(Math.round(Number.isFinite(state.wc) ? state.wc : baseWc));
    ui.wwValue.textContent = String(Math.round(Number.isFinite(state.ww) ? state.ww : baseWw));
  }

  function renderExamPicker() {
    if (!ui.examPickerWrap || !ui.examPicker) return;
    const show = viewerMode === "share" && (state.shareExams || []).length > 1;
    ui.examPickerWrap.classList.toggle("hidden", !show);
    if (!show) return;
    ui.examPicker.innerHTML = (state.shareExams || []).map((exam) => `
      <option value="${exam.id}">${escapeHtml(exam.patient_name)} • ${escapeHtml(exam.procedure_name)} • ${escapeHtml(exam.accession_number)}</option>
    `).join("");
    ui.examPicker.value = String(state.selectedExamId || "");
  }

  function renderStudyMeta() {
    const exam = getWorkspaceExam();
    const study = state.workspace?.pacs?.study || {};
    const report = state.workspace?.report || {};
    const attachments = (state.workspace?.attachments || []).filter((item) => item.is_image && item.is_available !== false);
    ui.title.textContent = exam
      ? `${exam.patient_name || "-"} • ${exam.procedure_name || "-"}`
      : "Nenhum exame selecionado";
    ui.subtitle.textContent = exam
      ? `Accession ${exam.accession_number || "-"} • Fluxo ${exam.workflow_label || exam.workflow_stage || "-"}`
      : "Aguardando selecao do estudo.";
    ui.studyMeta.innerHTML = exam ? [
      metaItem("Paciente", exam.patient_name || "-"),
      metaItem("Procedimento", exam.procedure_name || "-"),
      metaItem("Modalidade", exam.modality || exam.procedure_modality || study.studymodality || "-"),
      metaItem("Agenda", dateTimeLabel(exam.scheduled_at)),
      metaItem("Estacao", exam.station_aet || study.stationname || "-"),
      metaItem("Study UID", state.workspace?.study_instance_uid || "-"),
      metaItem("Series", String(state.workspace?.pacs?.series?.length || 0)),
      metaItem("Imagens", String(state.assets.length || 0)),
      metaItem("Laudo", report.status || "draft"),
      metaItem("Objetos PACS", String(state.workspace?.pacs?.instances?.length || 0)),
      metaItem("Anexos Web", String(attachments.length || 0)),
      metaItem("Recebido", dateTimeLabel(study.last_received_at || state.workspace?.pacs?.instances?.[0]?.receivedat)),
    ].join("") : metaItem("Status", "Sem estudo");
  }

  function renderSeriesRail() {
    ui.seriesRail.innerHTML = state.seriesGroups.map((group) => `
      <button class="series-button ${group.key === state.seriesFilter ? "active" : ""}" type="button" data-series-key="${escapeHtml(group.key)}">
        <strong>${escapeHtml(group.label)}</strong>
        <small>${escapeHtml(group.detail)}</small>
      </button>
    `).join("") || `<div class="list-row"><strong>Sem series</strong><span>Envie imagens para montar a navegacao.</span></div>`;
  }

  function renderFilmstrip() {
    const items = filteredAssets();
    ui.filmstrip.innerHTML = items.map((asset) => `
      <button class="thumb-card ${asset.key === state.selectedAssetKey ? "active" : ""}" type="button" data-asset-key="${escapeHtml(asset.key)}">
        ${asset.thumbUrl
          ? `<img src="${escapeHtml(asset.thumbUrl)}" alt="${escapeHtml(asset.label)}" loading="lazy" />`
          : `<div class="thumb-placeholder"><strong>DICOM</strong><span>${escapeHtml(asset.shortLabel)}</span></div>`}
        <div class="thumb-caption">
          <strong>${escapeHtml(asset.shortLabel)}</strong>
          <small>${escapeHtml(asset.meta)}</small>
        </div>
      </button>
    `).join("") || `<div class="list-row"><strong>Sem imagens nesta selecao</strong><span>Troque a serie ou envie novas imagens para o exame.</span></div>`;
  }

  function renderAttachmentList() {
    if (!ui.attachmentList) return;
    const attachments = state.workspace?.attachments || [];
    ui.attachmentList.innerHTML = attachments.map((item) => `
      <div class="list-row">
        <strong>${escapeHtml(item.original_name || item.stored_name || `Anexo ${item.id}`)}</strong>
        <span>${escapeHtml(item.is_available === false ? "Arquivo ausente no disco" : (item.mime_type || item.kind || "-"))}</span>
      </div>
    `).join("") || `<div class="list-row"><strong>Sem anexos</strong><span>Use o upload para adicionar JPG, PNG ou DICOM.</span></div>`;
  }

  function renderShareInfo() {
    if (!ui.shareInfo || viewerMode !== "share") return;
    ui.shareInfo.innerHTML = [
      metaItem("Escopo", state.share?.scope_type || "-"),
      metaItem("Usuario", state.share?.username || "-"),
      metaItem("Expira em", dateTimeLabel(state.share?.expires_at)),
      metaItem("Ultimo acesso", dateTimeLabel(state.share?.last_login_at)),
    ].join("");
  }

  function shareLink(slug) {
    return `${window.location.origin}/share/${slug}`;
  }

  function renderShareCreated() {
    if (!ui.shareCreated || viewerMode !== "internal") return;
    const share = state.lastCreatedShare;
    ui.shareCreated.classList.toggle("hidden", !share);
    if (!share) {
      ui.shareCreated.innerHTML = "";
      return;
    }
    ui.shareCreated.innerHTML = `
      <div class="share-row">
        <strong>Acesso gerado agora</strong>
        <span>Escopo: ${escapeHtml(share.scopeLabel || "-")}</span>
        <span>Usuario: <code>${escapeHtml(share.username || "-")}</code></span>
        <span>Senha: <code>${escapeHtml(share.password || "-")}</code></span>
        <span>Link: <code>${escapeHtml(share.url || "-")}</code></span>
        <div class="share-actions">
          <button class="mini" type="button" data-copy-share="${escapeHtml(share.username || "")}">Copiar usuario</button>
          <button class="mini" type="button" data-copy-share="${escapeHtml(share.password || "")}">Copiar senha</button>
          <button class="mini" type="button" data-copy-share="${escapeHtml(share.url || "")}">Copiar link</button>
          <a class="mini" href="${escapeHtml(share.url || "#")}" target="_blank" rel="noreferrer">Abrir</a>
        </div>
      </div>
    `;
  }

  function renderShareList() {
    if (!ui.shareList || viewerMode !== "internal") return;
    ui.shareList.innerHTML = (state.shares || []).map((share) => `
      <div class="share-row">
        <strong>${escapeHtml(share.scope_type === "patient" ? "Paciente inteiro" : "Exame atual")}</strong>
        <span>Usuario: <code>${escapeHtml(share.username)}</code></span>
        <span>Link: <code>${escapeHtml(shareLink(share.slug))}</code></span>
        <span>${escapeHtml(share.note || "Sem observacao")}</span>
        <div class="share-actions">
          <a class="mini" href="${escapeHtml(shareLink(share.slug))}" target="_blank" rel="noreferrer">Abrir</a>
          <button class="mini" type="button" data-copy-share="${escapeHtml(shareLink(share.slug))}">Copiar link</button>
        </div>
      </div>
    `).join("") || `<div class="list-row"><strong>Sem compartilhamentos</strong><span>Crie um usuario e senha para liberar as imagens deste exame ou paciente.</span></div>`;
  }

  function fillInternalForms() {
    if (viewerMode !== "internal" || !state.workspace?.exam) return;
    const exam = state.workspace.exam;
    const report = state.workspace.report || {};
    if (ui.reportForm) {
      ui.reportForm.querySelector('[name="exam_id"]').value = exam.id;
      ui.reportForm.querySelector('[name="doctor_name"]').value = report.doctor_name || "";
      ui.reportForm.querySelector('[name="status"]').value = report.status || "draft";
      ui.reportForm.querySelector('[name="title"]').value = report.title || "";
      ui.reportForm.querySelector('[name="body"]').value = report.body || "";
      ui.reportForm.querySelector('[name="impression"]').value = report.impression || "";
    }
    if (ui.uploadForm) {
      ui.uploadForm.querySelector('[name="exam_id"]').value = exam.id;
    }
    if (ui.shareForm) {
      const usernameInput = ui.shareForm.querySelector('[name="username"]');
      const passwordInput = ui.shareForm.querySelector('[name="password"]');
      const suggestion = state.workspace?.share_suggestion || {};
      const examChanged = state.shareFormExamId !== String(exam.id);
      ui.shareForm.querySelector('[name="exam_id"]').value = exam.id;
      ui.shareForm.querySelector('[name="patient_id"]').value = exam.patient_id;
      if (examChanged) {
        ui.shareForm.querySelector('[name="scope_type"]').value = "exam";
        usernameInput.value = suggestion.username || "";
        passwordInput.value = suggestion.password || "";
        state.shareFormExamId = String(exam.id);
        state.lastCreatedShare = null;
      } else {
        if (!usernameInput.value && suggestion.username) usernameInput.value = suggestion.username;
        if (!passwordInput.value && suggestion.password) passwordInput.value = suggestion.password;
      }
    }
  }

  function renderAll() {
    renderExamPicker();
    renderStudyMeta();
    renderSeriesRail();
    renderFilmstrip();
    renderAttachmentList();
    fillInternalForms();
    renderShareCreated();
    renderShareList();
    renderShareInfo();
    updateWindowControls();
  }

  function prepareSelection() {
    state.assets = buildAssets();
    state.seriesGroups = buildSeriesGroups();
    const availableGroupKeys = new Set(state.seriesGroups.map((group) => group.key));
    if (!availableGroupKeys.has(state.seriesFilter)) {
      state.seriesFilter = "all";
    }
    const filtered = filteredAssets();
    if (!filtered.some((asset) => asset.key === state.selectedAssetKey)) {
      state.selectedAssetKey = filtered[0]?.key || state.assets[0]?.key || "";
    }
  }

  function resetDicomWindow() {
    state.invert = false;
    state.windowDirty = false;
    state.wc = null;
    state.ww = null;
    state.defaultWc = null;
    state.defaultWw = null;
  }

  function showImage(url) {
    revokePreviewObjectUrl();
    ui.image.src = url || "";
    ui.image.classList.toggle("hidden", !url);
    ui.stageEmpty.classList.toggle("hidden", Boolean(url));
    applyTransform();
  }

  async function loadCurrentAsset() {
    const asset = currentAsset();
    if (!asset) {
      revokePreviewObjectUrl();
      ui.image.removeAttribute("src");
      ui.image.classList.add("hidden");
      ui.stageEmpty.classList.remove("hidden");
      updateWindowControls();
      setStatus("Nenhuma imagem selecionada.");
      return;
    }

    if (asset.type === "image") {
      showImage(asset.sourceUrl);
      updateWindowControls();
      setStatus(`Visualizando ${asset.label}.`);
      return;
    }

    const token = ++state.previewToken;
    const query = {};
    if (state.windowDirty) {
      query.wc = Math.round(state.wc ?? 0);
      query.ww = Math.round(Math.max(state.ww ?? 1, 1));
    }
    if (state.invert) query.invert = 1;
    query.size = 1200;
    query.v = token;
    const previewUrl = dicomPreviewUrl(asset.sopInstanceUid, query);

    showImage(previewUrl);
    updateWindowControls();
    setStatus("Gerando preview DICOM...");
    try {
      const response = await fetch(previewUrl, { method: "HEAD", headers: { Accept: "image/png" } });
      if (!response.ok) {
        if (response.status === 401 && viewerMode === "share") {
          window.location.href = `/share/${encodeURIComponent(shareSlug)}`;
          return;
        }
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || "Falha ao renderizar o DICOM.");
      }
      if (token !== state.previewToken) return;
      const headerWc = Number.parseFloat(response.headers.get("X-Window-Center") || "");
      const headerWw = Number.parseFloat(response.headers.get("X-Window-Width") || "");
      if (Number.isFinite(headerWc)) state.defaultWc = headerWc;
      if (Number.isFinite(headerWw)) state.defaultWw = headerWw;
      if (!state.windowDirty) {
        state.wc = Number.isFinite(headerWc) ? headerWc : state.wc;
        state.ww = Number.isFinite(headerWw) ? headerWw : state.ww;
      }
      updateWindowControls();
      setStatus(`Preview DICOM carregado: ${asset.label}.`);
    } catch (error) {
      ui.image.removeAttribute("src");
      ui.image.classList.add("hidden");
      ui.stageEmpty.classList.remove("hidden");
      setStatus(error.message || "Falha ao renderizar o DICOM.", true);
      showToast(error.message || "Falha ao renderizar o DICOM.", true);
    }
  }

  function selectAsset(assetKey) {
    if (!assetKey || assetKey === state.selectedAssetKey) return;
    state.selectedAssetKey = assetKey;
    resetViewport();
    resetDicomWindow();
    renderFilmstrip();
    updateWindowControls();
    loadCurrentAsset();
  }

  async function loadViewer(targetExamId = "") {
    setStatus("Carregando estudo...");
    const examId = String(targetExamId || state.selectedExamId || "");
    const payload = viewerMode === "internal"
      ? await api(`/api/viewer/exams/${encodeURIComponent(examId)}`)
      : await api(`/api/share/${encodeURIComponent(shareSlug)}/workspace${examId ? `?exam_id=${encodeURIComponent(examId)}` : ""}`);

    if (viewerMode === "internal") {
      state.workspace = payload.workspace || null;
      state.shares = payload.shares || [];
      state.selectedExamId = String(payload.workspace?.exam?.id || examId || "");
    } else {
      state.workspace = payload.workspace || null;
      state.share = payload.share || null;
      state.shareExams = payload.exams || [];
      state.selectedExamId = String(payload.selected_exam_id || payload.workspace?.exam?.id || examId || "");
    }

    prepareSelection();
    renderAll();
    resetViewport();
    resetDicomWindow();
    await loadCurrentAsset();
  }

  function clampZoom(value) {
    return Math.min(8, Math.max(0.2, value));
  }

  function setZoom(value) {
    state.zoom = clampZoom(value);
    applyTransform();
    ui.zoomResetBtn.textContent = `${Math.round(state.zoom * 100)}%`;
  }

  function debouncePreviewReload() {
    window.clearTimeout(state.previewDebounce);
    state.previewDebounce = window.setTimeout(() => loadCurrentAsset(), 140);
  }

  async function saveReport(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const examId = form.querySelector('[name="exam_id"]').value;
    if (!examId) {
      showToast("Abra um exame antes de salvar o laudo.", true);
      return;
    }
    try {
      await api(`/api/exams/${examId}/report`, {
        method: "PUT",
        body: JSON.stringify({
          doctor_name: form.querySelector('[name="doctor_name"]').value,
          status: form.querySelector('[name="status"]').value,
          title: form.querySelector('[name="title"]').value,
          body: form.querySelector('[name="body"]').value,
          impression: form.querySelector('[name="impression"]').value,
        }),
      });
      await loadViewer(examId);
      showToast("Laudo salvo com sucesso.");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function uploadAttachment(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const examId = form.querySelector('[name="exam_id"]').value;
    const fileInput = form.querySelector('[name="file"]');
    if (!examId || !fileInput?.files?.length) {
      showToast("Selecione o arquivo e o exame antes do envio.", true);
      return;
    }
    try {
      const formData = new FormData();
      formData.append("file", fileInput.files[0]);
      await api(`/api/exams/${examId}/attachments`, { method: "POST", body: formData });
      fileInput.value = "";
      await loadViewer(examId);
      showToast("Arquivo inserido no exame.");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function createShare(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = {
      scope_type: form.querySelector('[name="scope_type"]').value,
      exam_id: Number(form.querySelector('[name="exam_id"]').value || 0),
      patient_id: Number(form.querySelector('[name="patient_id"]').value || 0),
      username: form.querySelector('[name="username"]').value,
      password: form.querySelector('[name="password"]').value,
      expires_at: form.querySelector('[name="expires_at"]').value,
      note: form.querySelector('[name="note"]').value,
    };
    try {
      const share = await api("/api/viewer/shares", { method: "POST", body: JSON.stringify(payload) });
      const created = share.created_credentials || {};
      state.lastCreatedShare = {
        username: created.username || payload.username,
        password: created.password || payload.password,
        url: share.share_url || shareLink(share.slug),
        scopeLabel: share.scope_type === "patient" ? "Paciente inteiro" : "Exame atual",
      };
      form.reset();
      form.querySelector('[name="scope_type"]').value = payload.scope_type || "exam";
      form.querySelector('[name="exam_id"]').value = payload.exam_id;
      form.querySelector('[name="patient_id"]').value = payload.patient_id;
      await loadViewer(String(payload.exam_id));
      form.querySelector('[name="username"]').value = state.lastCreatedShare.username || "";
      form.querySelector('[name="password"]').value = state.lastCreatedShare.password || "";
      renderShareCreated();
      showToast(`Acesso compartilhado criado para ${state.lastCreatedShare.username || "o paciente"}.`);
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function copyShareLink(text) {
    try {
      await navigator.clipboard.writeText(text);
      showToast("Informacao copiada.");
    } catch {
      showToast("Nao foi possivel copiar a informacao.", true);
    }
  }

  function bindEvents() {
    ui.image?.addEventListener("load", () => {
      if (!ui.image?.src) return;
      ui.image.classList.remove("hidden");
      ui.stageEmpty?.classList.add("hidden");
    });

    ui.image?.addEventListener("error", () => {
      ui.image.removeAttribute("src");
      ui.image.classList.add("hidden");
      ui.stageEmpty?.classList.remove("hidden");
      setStatus("Nao foi possivel abrir a imagem deste exame.", true);
    });

    ui.refreshBtn?.addEventListener("click", () => {
      loadViewer(state.selectedExamId).catch((error) => showToast(error.message, true));
    });

    ui.examPicker?.addEventListener("change", (event) => {
      state.selectedExamId = String(event.target.value || "");
      loadViewer(state.selectedExamId).catch((error) => showToast(error.message, true));
    });

    ui.zoomInBtn?.addEventListener("click", () => setZoom(state.zoom + 0.15));
    ui.zoomOutBtn?.addEventListener("click", () => setZoom(state.zoom - 0.15));
    ui.zoomResetBtn?.addEventListener("click", () => setZoom(1));
    ui.fitBtn?.addEventListener("click", () => {
      resetViewport();
      setZoom(1);
    });

    ui.invertBtn?.addEventListener("click", () => {
      const asset = currentAsset();
      if (asset?.type !== "dicom") return;
      state.invert = !state.invert;
      debouncePreviewReload();
    });

    ui.wcSlider?.addEventListener("input", (event) => {
      state.windowDirty = true;
      state.wc = Number(event.target.value || 0);
      ui.wcValue.textContent = String(Math.round(state.wc));
      debouncePreviewReload();
    });

    ui.wwSlider?.addEventListener("input", (event) => {
      state.windowDirty = true;
      state.ww = Number(event.target.value || 1);
      ui.wwValue.textContent = String(Math.round(state.ww));
      debouncePreviewReload();
    });

    ui.canvas?.addEventListener("wheel", (event) => {
      event.preventDefault();
      const delta = event.deltaY > 0 ? -0.12 : 0.12;
      setZoom(state.zoom + delta);
    }, { passive: false });

    ui.canvas?.addEventListener("pointerdown", (event) => {
      state.dragging = true;
      state.dragStartX = event.clientX;
      state.dragStartY = event.clientY;
      state.dragOriginX = state.panX;
      state.dragOriginY = state.panY;
      ui.canvas.classList.add("dragging");
    });

    window.addEventListener("pointermove", (event) => {
      if (!state.dragging) return;
      state.panX = state.dragOriginX + (event.clientX - state.dragStartX);
      state.panY = state.dragOriginY + (event.clientY - state.dragStartY);
      applyTransform();
    });

    window.addEventListener("pointerup", () => {
      state.dragging = false;
      ui.canvas?.classList.remove("dragging");
    });

    ui.reportForm?.addEventListener("submit", saveReport);
    ui.uploadForm?.addEventListener("submit", uploadAttachment);
    ui.shareForm?.addEventListener("submit", createShare);

    document.body.addEventListener("click", (event) => {
      const thumb = event.target.closest("[data-asset-key]");
      if (thumb) {
        selectAsset(thumb.dataset.assetKey);
        return;
      }

      const series = event.target.closest("[data-series-key]");
      if (series) {
        state.seriesFilter = series.dataset.seriesKey || "all";
        const filtered = filteredAssets();
        state.selectedAssetKey = filtered[0]?.key || state.assets[0]?.key || "";
        renderSeriesRail();
        renderFilmstrip();
        resetViewport();
        resetDicomWindow();
        loadCurrentAsset();
        return;
      }

      const copyButton = event.target.closest("[data-copy-share]");
      if (copyButton) {
        copyShareLink(copyButton.dataset.copyShare || "");
      }
    });
  }

  window.addEventListener("beforeunload", revokePreviewObjectUrl);

  bindEvents();
  loadViewer(state.selectedExamId).catch((error) => {
    setStatus(error.message || "Falha ao carregar o viewer.", true);
    showToast(error.message || "Falha ao carregar o viewer.", true);
  });
})();
