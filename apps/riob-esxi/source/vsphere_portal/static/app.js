const state = {
    activePage: "vsphere",
    connection: null,
    inventory: null,
    vms: [],
    hosts: [],
    selectedHostId: null,
    selectedHostDetails: null,
    selectedVmId: null,
    selectedVmDetails: null,
    isoFiles: [],
    dockerConnection: null,
    dockerOverview: null,
    containers: [],
    selectedContainerId: null,
    selectedContainerDetails: null,
};

const APP_BASE_URL = new URL("./", window.location.href);

const elements = {};
const sshTerminalState = {
    term: null,
    sessionId: null,
    cursor: 0,
    pollTimer: null,
    inputFlushTimer: null,
    pendingInput: "",
    vmId: null,
    resizeBound: false,
};

document.addEventListener("DOMContentLoaded", () => {
    bindElements();
    bindEvents();
    initialize();
});

function bindElements() {
    elements.loginScreen = document.getElementById("login-screen");
    elements.appShell = document.getElementById("app-shell");
    elements.loginForm = document.getElementById("login-form");
    elements.loginState = document.getElementById("login-state");
    elements.uiLogoutButton = document.getElementById("ui-logout-button");
    elements.pageSwitchButtons = Array.from(document.querySelectorAll("[data-page-target]"));
    elements.pageVsphere = document.getElementById("page-vsphere");
    elements.pageContainers = document.getElementById("page-containers");
    elements.connectForm = document.getElementById("connect-form");
    elements.disconnectButton = document.getElementById("disconnect-button");
    elements.refreshButton = document.getElementById("refresh-button");
    elements.connectionChip = document.getElementById("connection-chip");
    elements.connectionMeta = document.getElementById("connection-meta");
    elements.summaryCards = document.getElementById("summary-cards");
    elements.vmTableBody = document.getElementById("vm-table-body");
    elements.hostTableBody = document.getElementById("host-table-body");
    elements.selectedHostTitle = document.getElementById("selected-host-title");
    elements.selectedHostSubtitle = document.getElementById("selected-host-subtitle");
    elements.hostOverviewCards = document.getElementById("host-overview-cards");
    elements.hostLicenseSummary = document.getElementById("host-license-summary");
    elements.hostNetworkSummary = document.getElementById("host-network-summary");
    elements.hostUplinkBody = document.getElementById("host-uplink-body");
    elements.hostSwitchList = document.getElementById("host-switch-list");
    elements.hostDatastoreList = document.getElementById("host-datastore-list");
    elements.hostVmList = document.getElementById("host-vm-list");
    elements.selectedVmTitle = document.getElementById("selected-vm-title");
    elements.selectedVmSubtitle = document.getElementById("selected-vm-subtitle");
    elements.vmOverviewCards = document.getElementById("vm-overview-cards");
    elements.vmNetworkList = document.getElementById("vm-network-list");
    elements.vmStorageList = document.getElementById("vm-storage-list");
    elements.remoteAccessForm = document.getElementById("remote-access-form");
    elements.remoteAccessSummary = document.getElementById("remote-access-summary");
    elements.remoteAccessNotes = document.getElementById("remote-access-notes");
    elements.remoteGuestUsername = document.getElementById("remote-guest-username");
    elements.remoteGuestPassword = document.getElementById("remote-guest-password");
    elements.remoteGuestIp = document.getElementById("remote-guest-ip");
    elements.remoteGuestPort = document.getElementById("remote-guest-port");
    elements.remoteLegacyCompat = document.getElementById("remote-legacy-compat");
    elements.openVmrcLink = document.getElementById("open-vmrc-link");
    elements.openWebSshButton = document.getElementById("open-web-ssh-button");
    elements.closeWebSshButton = document.getElementById("close-web-ssh-button");
    elements.copySshButton = document.getElementById("copy-ssh-button");
    elements.downloadRdpButton = document.getElementById("download-rdp-button");
    elements.webSshStatus = document.getElementById("web-ssh-status");
    elements.webSshTerminal = document.getElementById("web-ssh-terminal");
    elements.renameForm = document.getElementById("rename-form");
    elements.hardwareForm = document.getElementById("hardware-form");
    elements.snapshotForm = document.getElementById("snapshot-form");
    elements.snapshotList = document.getElementById("snapshot-list");
    elements.cloneForm = document.getElementById("clone-form");
    elements.cloneFolder = document.getElementById("clone-folder");
    elements.clonePool = document.getElementById("clone-pool");
    elements.cloneDatastore = document.getElementById("clone-datastore");
    elements.createVmForm = document.getElementById("create-vm-form");
    elements.createVmHost = document.getElementById("create-vm-host");
    elements.createVmDatastore = document.getElementById("create-vm-datastore");
    elements.createVmFolder = document.getElementById("create-vm-folder");
    elements.createVmPool = document.getElementById("create-vm-pool");
    elements.createVmNetwork = document.getElementById("create-vm-network");
    elements.createVmIsoDatastore = document.getElementById("create-vm-iso-datastore");
    elements.createVmIsoPath = document.getElementById("create-vm-iso-path");
    elements.clearCreateVmIsoButton = document.getElementById("clear-create-vm-iso-button");
    elements.isoUploadForm = document.getElementById("iso-upload-form");
    elements.isoDatastoreSelect = document.getElementById("iso-datastore-select");
    elements.isoFolderPath = document.getElementById("iso-folder-path");
    elements.isoFileInput = document.getElementById("iso-file-input");
    elements.isoSourceUrl = document.getElementById("iso-source-url");
    elements.isoOverwrite = document.getElementById("iso-overwrite");
    elements.refreshIsoButton = document.getElementById("refresh-iso-button");
    elements.isoLibraryList = document.getElementById("iso-library-list");
    elements.vmMediaSummary = document.getElementById("vm-media-summary");
    elements.dockerConnectForm = document.getElementById("docker-connect-form");
    elements.dockerDisconnectButton = document.getElementById("docker-disconnect-button");
    elements.dockerRefreshButton = document.getElementById("docker-refresh-button");
    elements.dockerCreateForm = document.getElementById("docker-create-form");
    elements.dockerCommandForm = document.getElementById("docker-command-form");
    elements.dockerCommandPreset = document.getElementById("docker-command-preset");
    elements.dockerCommandInput = document.getElementById("docker-command-input");
    elements.dockerCommandContext = document.getElementById("docker-command-context");
    elements.dockerCommandOutput = document.getElementById("docker-command-output");
    elements.dockerClearCommandOutputButton = document.getElementById("docker-clear-command-output-button");
    elements.dockerConnectionChip = document.getElementById("docker-connection-chip");
    elements.dockerConnectionMeta = document.getElementById("docker-connection-meta");
    elements.dockerOverviewCards = document.getElementById("docker-overview-cards");
    elements.dockerContainerTableBody = document.getElementById("docker-container-table-body");
    elements.selectedContainerTitle = document.getElementById("selected-container-title");
    elements.selectedContainerSubtitle = document.getElementById("selected-container-subtitle");
    elements.dockerContainerMetrics = document.getElementById("docker-container-metrics");
    elements.dockerContainerNetworks = document.getElementById("docker-container-networks");
    elements.dockerContainerMounts = document.getElementById("docker-container-mounts");
    elements.dockerContainerEnv = document.getElementById("docker-container-env");
    elements.dockerContainerLogs = document.getElementById("docker-container-logs");
    elements.toast = document.getElementById("toast");
}

function bindEvents() {
    if (elements.loginForm) {
        elements.loginForm.addEventListener("submit", onUiLogin);
    }
    if (elements.uiLogoutButton) {
        elements.uiLogoutButton.addEventListener("click", onUiLogout);
    }
    elements.pageSwitchButtons.forEach((button) => {
        button.addEventListener("click", () => {
            setActivePage(button.dataset.pageTarget || "vsphere");
        });
    });
    elements.connectForm.addEventListener("submit", onConnect);
    elements.disconnectButton.addEventListener("click", onDisconnect);
    elements.refreshButton.addEventListener("click", refreshData);
    elements.renameForm.addEventListener("submit", onRenameVm);
    elements.hardwareForm.addEventListener("submit", onUpdateHardware);
    elements.snapshotForm.addEventListener("submit", onCreateSnapshot);
    elements.cloneForm.addEventListener("submit", onCloneVm);
    elements.createVmForm.addEventListener("submit", onCreateVm);
    elements.clearCreateVmIsoButton.addEventListener("click", clearCreateVmIsoSelection);
    elements.isoUploadForm.addEventListener("submit", onUploadIso);
    elements.refreshIsoButton.addEventListener("click", onRefreshIsos);
    elements.isoDatastoreSelect.addEventListener("change", () => {
        state.isoFiles = [];
        renderIsoLibrary();
    });
    elements.openWebSshButton.addEventListener("click", onOpenWebSsh);
    elements.closeWebSshButton.addEventListener("click", onCloseWebSsh);
    elements.copySshButton.addEventListener("click", onCopySshCommand);
    elements.downloadRdpButton.addEventListener("click", onDownloadRdpFile);
    elements.openVmrcLink.addEventListener("click", onOpenVmrc);
    elements.dockerConnectForm.addEventListener("submit", onDockerConnect);
    elements.dockerDisconnectButton.addEventListener("click", onDockerDisconnect);
    elements.dockerRefreshButton.addEventListener("click", refreshDockerData);
    elements.dockerCreateForm.addEventListener("submit", onDockerCreateContainer);
    elements.dockerCommandForm.addEventListener("submit", onDockerRunCommand);
    elements.dockerCommandPreset.addEventListener("change", onDockerCommandPresetChange);
    elements.dockerClearCommandOutputButton.addEventListener("click", clearDockerCommandOutput);

    document.querySelectorAll(".docker-action").forEach((button) => {
        button.addEventListener("click", async () => {
            if (!state.selectedContainerId) {
                showToast("Selecione um container antes de executar uma acao.", true);
                return;
            }
            await postJson(`/api/docker/containers/${encodeURIComponent(state.selectedContainerId)}/action`, {
                action: button.dataset.dockerAction,
            });
            showToast("Acao do container enviada.");
            await refreshDockerData();
        });
    });

    document.querySelectorAll(".vm-action").forEach((button) => {
        button.addEventListener("click", async () => {
            if (!state.selectedVmId) {
                showToast("Selecione uma VM antes de executar uma acao.", true);
                return;
            }
            await postJson(`/api/vms/${state.selectedVmId}/power`, { action: button.dataset.action });
            showToast("Acao enviada para a VM.");
            await refreshData();
        });
    });

    elements.hostTableBody.addEventListener("click", async (event) => {
        const button = event.target.closest("button[data-host-action]");
        if (button) {
            event.stopPropagation();

            const moid = button.dataset.hostMoid;
            const action = button.dataset.hostAction;
            if (!moid || !action) {
                return;
            }

            if (action === "enter_maintenance") {
                await postJson(`/api/hosts/${moid}/maintenance`, { enabled: true });
                showToast("Host enviado para maintenance mode.");
            } else if (action === "exit_maintenance") {
                await postJson(`/api/hosts/${moid}/maintenance`, { enabled: false });
                showToast("Host retirado do maintenance mode.");
            } else {
                await postJson(`/api/hosts/${moid}/power`, { action });
                showToast("Acao enviada para o host.");
            }
            await refreshData();
            return;
        }

        const row = event.target.closest("tr[data-host-moid]");
        if (!row) {
            return;
        }

        const moid = row.dataset.hostMoid;
        state.selectedHostId = moid;
        renderHostTable();
        await refreshHostDetails(moid);
    });

    elements.snapshotList.addEventListener("click", async (event) => {
        const actionButton = event.target.closest("button[data-snapshot-action]");
        if (!actionButton || !state.selectedVmId) {
            return;
        }

        const snapshotMoid = actionButton.dataset.snapshotMoid;
        const action = actionButton.dataset.snapshotAction;
        if (!snapshotMoid || !action) {
            return;
        }

        if (action === "revert") {
            await postJson(`/api/vms/${state.selectedVmId}/snapshots/${snapshotMoid}/revert`, {});
            showToast("Snapshot revertido.");
        }

        if (action === "delete") {
            await fetchJson(`/api/vms/${state.selectedVmId}/snapshots/${snapshotMoid}`, { method: "DELETE" });
            showToast("Snapshot removido.");
        }

        await refreshVmDetails(state.selectedVmId);
        await refreshData({ preserveDetails: true });
    });

    elements.isoLibraryList.addEventListener("click", async (event) => {
        const actionButton = event.target.closest("button[data-iso-action]");
        if (!actionButton) {
            return;
        }

        const isoPath = actionButton.dataset.isoPath || "";
        const datastoreMoid = actionButton.dataset.datastoreMoid || "";
        if (!isoPath || !datastoreMoid) {
            return;
        }

        if (actionButton.dataset.isoAction === "use-create-vm") {
            applyIsoToCreateVm(datastoreMoid, isoPath);
            showToast("ISO enviada para o formulario da nova VM.");
            return;
        }

        if (actionButton.dataset.isoAction === "mount-vm") {
            if (!state.selectedVmId) {
                showToast("Selecione uma VM antes de montar uma ISO.", true);
                return;
            }
            const data = await postJson(`/api/vms/${state.selectedVmId}/media/iso`, {
                datastore_moid: datastoreMoid,
                iso_path: isoPath,
                connect_at_power_on: true,
            });
            state.selectedVmDetails = data.vm;
            renderSelectedVm();
            showToast(data.message || "ISO montada na VM.");
        }
    });

    elements.vmMediaSummary.addEventListener("click", async (event) => {
        const button = event.target.closest("button[data-media-action='eject-iso']");
        if (!button || !state.selectedVmId) {
            return;
        }
        const data = await fetchJson(`/api/vms/${state.selectedVmId}/media/iso`, { method: "DELETE" });
        state.selectedVmDetails = data.vm;
        renderSelectedVm();
        showToast(data.message || "ISO ejetada.");
    });
}

async function initialize() {
    disableVmActions(true);
    disableDockerActions(true);
    disableDockerCommandForms(true);
    setActivePage(state.activePage);
    await loadSession();
}

async function loadSession() {
    const [vsphereData, dockerData] = await Promise.all([
        fetchJson("/api/session"),
        fetchJson("/api/docker/session"),
    ]);

    setAuthenticated(vsphereData.authenticated !== false);

    state.connection = vsphereData.connection;
    state.dockerConnection = dockerData.connection;
    renderConnection();
    renderDockerConnection();
    renderDockerCommandContext();

    if (vsphereData.connected) {
        try {
            await refreshData();
        } catch (error) {
            console.error("Falha ao carregar dados da sessao ativa.", error);
        }
    } else {
        renderDisconnectedState();
    }

    if (dockerData.connected) {
        try {
            await refreshDockerData();
        } catch (error) {
            console.error("Falha ao carregar dados da sessao Docker.", error);
        }
    } else {
        renderDockerDisconnectedState();
    }
}

async function onConnect(event) {
    event.preventDefault();
    const formData = new FormData(elements.connectForm);
    const payload = {
        host: formData.get("host"),
        port: formData.get("port"),
        username: formData.get("username"),
        password: formData.get("password"),
        verify_ssl: formData.get("verify_ssl") === "on",
    };

    const data = await postJson("/api/session/connect", payload);
    state.connection = data.connection;
    state.selectedHostId = null;
    state.selectedHostDetails = null;
    state.selectedVmId = null;
    state.selectedVmDetails = null;
    renderConnection();
    showToast(data.message || "Conexao estabelecida.");
    try {
        await refreshData();
    } catch (error) {
        console.error("Falha ao carregar dados apos conectar.", error);
        showToast(`Conectado, mas houve falha ao carregar os dados: ${error.message}`, true);
    }
}

async function onUiLogin(event) {
    event.preventDefault();
    const formData = new FormData(elements.loginForm);
    const payload = {
        username: formData.get("username"),
        password: formData.get("password"),
    };

    try {
        const data = await postJson("/api/login", payload);
        if (elements.loginState) {
            elements.loginState.textContent = data.message || "Sessao iniciada.";
        }
        window.location.reload();
    } catch (error) {
        if (elements.loginState) {
            elements.loginState.textContent = error.message;
        }
    }
}

async function onUiLogout() {
    try {
        await postJson("/api/logout", {});
    } finally {
        window.location.reload();
    }
}

async function onDisconnect() {
    const data = await postJson("/api/session/disconnect", {});
    await closeEmbeddedSsh({ silent: true, preserveOutput: false });
    state.connection = null;
    state.inventory = null;
    state.vms = [];
    state.hosts = [];
    state.selectedHostId = null;
    state.selectedHostDetails = null;
    state.selectedVmId = null;
    state.selectedVmDetails = null;
    state.isoFiles = [];
    renderConnection();
    renderDisconnectedState();
    showToast(data.message || "Conexao encerrada.");
}

async function onDockerConnect(event) {
    event.preventDefault();
    const formData = new FormData(elements.dockerConnectForm);
    const payload = {
        host: formData.get("host"),
        port: formData.get("port"),
        username: formData.get("username"),
        password: formData.get("password"),
        legacy_compat: formData.get("legacy_compat") === "on",
    };

    const data = await postJson("/api/docker/session/connect", payload);
    state.dockerConnection = data.connection;
    state.selectedContainerId = null;
    state.selectedContainerDetails = null;
    renderDockerConnection();
    renderDockerCommandContext();
    showToast(data.message || "Conexao Docker estabelecida.");
    await refreshDockerData();
}

async function onDockerDisconnect() {
    const data = await postJson("/api/docker/session/disconnect", {});
    state.dockerConnection = null;
    state.dockerOverview = null;
    state.containers = [];
    state.selectedContainerId = null;
    state.selectedContainerDetails = null;
    renderDockerConnection();
    renderDockerDisconnectedState();
    showToast(data.message || "Conexao Docker encerrada.");
}

async function onDockerCreateContainer(event) {
    event.preventDefault();
    if (!state.dockerConnection) {
        showToast("Conecte em um host Docker antes de criar um novo container.", true);
        return;
    }

    const formData = new FormData(elements.dockerCreateForm);
    const payload = {
        image: formData.get("image"),
        name: formData.get("name"),
        network: formData.get("network"),
        restart_policy: formData.get("restart_policy"),
        ports: formData.get("ports"),
        environment: formData.get("environment"),
        volumes: formData.get("volumes"),
        command: formData.get("command"),
        extra_args: formData.get("extra_args"),
        detach: formData.get("detach") === "on",
    };

    setDockerCommandOutput("Criando container remoto...");
    const data = await postJson("/api/docker/containers", payload);
    setDockerCommandOutput(buildDockerCommandOutput(data.command, data.output));
    showToast(data.message || "Container criado.");

    elements.dockerCreateForm.reset();
    elements.dockerCreateForm.elements.restart_policy.value = "unless-stopped";
    elements.dockerCreateForm.elements.detach.checked = true;

    if (data.container?.id) {
        state.selectedContainerId = data.container.id;
    }

    await refreshDockerData();
}

async function onDockerRunCommand(event) {
    event.preventDefault();
    if (!state.dockerConnection) {
        showToast("Conecte em um host Docker antes de executar comandos.", true);
        return;
    }

    const rawCommand = String(new FormData(elements.dockerCommandForm).get("command") || "").trim();
    if (!rawCommand) {
        showToast("Informe o comando Docker para executar.", true);
        return;
    }

    let resolvedCommand = rawCommand;
    if (resolvedCommand.includes("{{container}}")) {
        if (!state.selectedContainerId) {
            showToast("Selecione um container ou remova {{container}} do comando.", true);
            return;
        }
        resolvedCommand = resolvedCommand.replaceAll("{{container}}", state.selectedContainerId);
    }

    setDockerCommandOutput(`$ ${resolvedCommand}\n\nExecutando...`);
    const data = await postJson("/api/docker/commands", { command: resolvedCommand });
    setDockerCommandOutput(buildDockerCommandOutput(data.command, data.output));
    showToast(data.message || "Comando Docker executado.");
    await refreshDockerData();
}

function onDockerCommandPresetChange() {
    const preset = getDockerCommandPreset(elements.dockerCommandPreset.value);
    if (!preset) {
        return;
    }
    elements.dockerCommandInput.value = preset;
}

function clearDockerCommandOutput(message = null) {
    const fallback = state.dockerConnection
        ? "A saida dos comandos Docker remotos aparecera aqui."
        : "Conecte em um host Docker para executar comandos remotos.";
    elements.dockerCommandOutput.textContent = message || fallback;
}

function setDockerCommandOutput(message) {
    if (!elements.dockerCommandOutput) {
        return;
    }
    elements.dockerCommandOutput.textContent = String(message || "(sem saida)");
}

async function refreshData(options = {}) {
    if (!state.connection) {
        renderDisconnectedState();
        return;
    }

    const [inventoryData, vmData, hostData] = await Promise.all([
        fetchJson("/api/inventory"),
        fetchJson("/api/vms"),
        fetchJson("/api/hosts"),
    ]);

    state.inventory = inventoryData.inventory;
    state.vms = vmData.vms;
    state.hosts = hostData.hosts;

    renderSummary();
    renderVmTable();
    renderHostTable();
    populateCloneSelectors();
    populateCreateVmSelectors();
    disableVmActions(!state.selectedVmId);

    if (state.selectedVmId && !options.preserveDetails) {
        await refreshVmDetails(state.selectedVmId);
    } else if (!state.selectedVmId) {
        renderNoVmSelected();
    }

    if (state.selectedHostId) {
        await refreshHostDetails(state.selectedHostId);
    } else {
        renderNoHostSelected();
    }

    if (elements.isoDatastoreSelect.value) {
        renderIsoLibrary();
    }
}

async function refreshDockerData(options = {}) {
    if (!state.dockerConnection) {
        renderDockerDisconnectedState();
        return;
    }

    const [overviewData, containerData] = await Promise.all([
        fetchJson("/api/docker/overview"),
        fetchJson("/api/docker/containers"),
    ]);

    state.dockerOverview = overviewData.overview;
    state.containers = containerData.containers || [];
    if (state.selectedContainerId && !state.containers.some((item) => item.id === state.selectedContainerId)) {
        state.selectedContainerId = null;
        state.selectedContainerDetails = null;
    }
    renderDockerOverview();
    renderDockerContainerTable();
    disableDockerActions(!state.selectedContainerId);
    disableDockerCommandForms(false);
    renderDockerCommandContext();

    if (state.selectedContainerId && !options.preserveDetails) {
        await refreshDockerContainerDetails(state.selectedContainerId);
    } else if (!state.selectedContainerId) {
        renderNoDockerContainerSelected();
    }
}

async function refreshVmDetails(moid) {
    if (!moid) {
        renderNoVmSelected();
        return;
    }

    const data = await fetchJson(`/api/vms/${moid}`);
    state.selectedVmDetails = data.vm;
    state.selectedVmId = moid;
    renderSelectedVm();
    disableVmActions(false);
}

async function refreshHostDetails(moid) {
    if (!moid) {
        renderNoHostSelected();
        return;
    }

    const data = await fetchJson(`/api/hosts/${moid}`);
    state.selectedHostDetails = data.host;
    state.selectedHostId = moid;
    renderSelectedHost();
}

function renderConnection() {
    if (!state.connection) {
        elements.connectionChip.textContent = "offline";
        elements.connectionChip.className = "chip chip-offline";
        elements.connectionMeta.innerHTML = `
            <div><dt>Endpoint</dt><dd>Sem conexao ativa</dd></div>
            <div><dt>API</dt><dd>-</dd></div>
            <div><dt>Usuario</dt><dd>-</dd></div>
        `;
        return;
    }

    elements.connectionChip.textContent = "online";
    elements.connectionChip.className = "chip chip-online";
    elements.connectionMeta.innerHTML = `
        <div><dt>Endpoint</dt><dd>${escapeHtml(state.connection.endpoint_name)}</dd></div>
        <div><dt>API</dt><dd>${escapeHtml(state.connection.api_type)} ${escapeHtml(state.connection.api_version)}</dd></div>
        <div><dt>Usuario</dt><dd>${escapeHtml(state.connection.username)}@${escapeHtml(state.connection.host)}</dd></div>
    `;
}

function renderDockerConnection() {
    if (!state.dockerConnection) {
        elements.dockerConnectionChip.textContent = "offline";
        elements.dockerConnectionChip.className = "chip chip-offline";
        elements.dockerConnectionMeta.innerHTML = `
            <div><dt>Host</dt><dd>Sem conexao Docker</dd></div>
            <div><dt>Engine</dt><dd>-</dd></div>
            <div><dt>SO</dt><dd>-</dd></div>
        `;
        disableDockerCommandForms(true);
        renderDockerCommandContext();
        return;
    }

    elements.dockerConnectionChip.textContent = "online";
    elements.dockerConnectionChip.className = "chip chip-online";
    elements.dockerConnectionMeta.innerHTML = `
        <div><dt>Host</dt><dd>${escapeHtml(state.dockerConnection.username)}@${escapeHtml(state.dockerConnection.host)}:${escapeHtml(String(state.dockerConnection.port))}</dd></div>
        <div><dt>Engine</dt><dd>${escapeHtml(state.dockerConnection.server_version || "-")}</dd></div>
        <div><dt>SO</dt><dd>${escapeHtml(state.dockerConnection.operating_system || "-")}</dd></div>
    `;
    disableDockerCommandForms(false);
    renderDockerCommandContext();
}

function setActivePage(pageName) {
    state.activePage = pageName === "containers" ? "containers" : "vsphere";
    elements.pageSwitchButtons.forEach((button) => {
        button.classList.toggle("is-active", button.dataset.pageTarget === state.activePage);
    });
    elements.pageVsphere.classList.toggle("page-shell-hidden", state.activePage !== "vsphere");
    elements.pageContainers.classList.toggle("page-shell-hidden", state.activePage !== "containers");
}

function renderDisconnectedState() {
    state.isoFiles = [];
    elements.summaryCards.innerHTML = buildEmptyCards();
    elements.vmTableBody.innerHTML = `<tr><td colspan="7" class="empty">Conecte para listar as VMs.</td></tr>`;
    elements.hostTableBody.innerHTML = `<tr><td colspan="4" class="empty">Conecte para carregar os hosts.</td></tr>`;
    renderNoVmSelected();
    renderNoHostSelected();
    populateCloneSelectors();
    populateCreateVmSelectors();
    renderIsoLibrary();
    disableVmActions(true);
}

function setAuthenticated(isAuthenticated) {
    if (elements.loginScreen) {
        elements.loginScreen.classList.toggle("hidden", isAuthenticated);
    }
    if (elements.appShell) {
        elements.appShell.classList.toggle("hidden", !isAuthenticated);
    }
}

function renderDockerDisconnectedState() {
    elements.dockerOverviewCards.innerHTML = `<p class="empty-card metric-empty">Conecte em um host Docker para carregar o resumo.</p>`;
    elements.dockerContainerTableBody.innerHTML = `<tr><td colspan="6" class="empty">Conecte em um host Docker para listar os containers.</td></tr>`;
    renderNoDockerContainerSelected();
    disableDockerActions(true);
    disableDockerCommandForms(true);
    clearDockerCommandOutput("Conecte em um host Docker para executar comandos remotos.");
}

function renderSummary() {
    if (!state.inventory) {
        elements.summaryCards.innerHTML = buildEmptyCards();
        return;
    }

    const metrics = [
        ["Datacenters", state.inventory.summary.datacenters],
        ["Clusters", state.inventory.summary.clusters],
        ["Hosts", state.inventory.summary.hosts],
        ["VMs", state.inventory.summary.virtual_machines],
        ["Datastores", state.inventory.summary.datastores],
        ["Networks", state.inventory.summary.networks],
    ];

    elements.summaryCards.innerHTML = metrics.map(([label, value]) => `
        <article class="metric-card">
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(String(value))}</strong>
        </article>
    `).join("");
}

function renderVmTable() {
    if (!state.vms.length) {
        elements.vmTableBody.innerHTML = `<tr><td colspan="7" class="empty">Nenhuma VM encontrada.</td></tr>`;
        return;
    }

    elements.vmTableBody.innerHTML = state.vms.map((vm) => `
        <tr data-vm-moid="${escapeHtml(vm.moid)}" class="${vm.moid === state.selectedVmId ? "selected" : ""}">
            <td>
                <strong>${escapeHtml(vm.name)}</strong><br>
                <span class="hint mono">${escapeHtml(vm.moid)}</span>
            </td>
            <td>${buildStatusPill(vm.power_state)}</td>
            <td>${escapeHtml(vm.guest_full_name || vm.guest_state || "-")}</td>
            <td>${escapeHtml(String(vm.cpu_count ?? "-"))}</td>
            <td>${escapeHtml(formatMemory(vm.memory_mb))}</td>
            <td>${escapeHtml(vm.host_name || "-")}</td>
            <td class="mono">${escapeHtml(vm.ip_address || "-")}</td>
        </tr>
    `).join("");

    elements.vmTableBody.querySelectorAll("tr[data-vm-moid]").forEach((row) => {
        row.addEventListener("click", async () => {
            const moid = row.dataset.vmMoid;
            if (sshTerminalState.sessionId && moid !== state.selectedVmId) {
                await closeEmbeddedSsh({ silent: true, preserveOutput: false });
            }
            state.selectedVmId = moid;
            renderVmTable();
            await refreshVmDetails(moid);
        });
    });
}

function renderHostTable() {
    if (!state.hosts.length) {
        elements.hostTableBody.innerHTML = `<tr><td colspan="4" class="empty">Nenhum host encontrado.</td></tr>`;
        return;
    }

    elements.hostTableBody.innerHTML = state.hosts.map((host) => `
        <tr data-host-moid="${escapeHtml(host.moid)}" class="${host.moid === state.selectedHostId ? "selected" : ""}">
            <td>
                <strong>${escapeHtml(host.name)}</strong><br>
                <span class="hint">${escapeHtml(host.cluster_name || host.product_name || "-")}</span><br>
                <span class="hint">${escapeHtml(formatCompactUsage(host.cpu_usage_percent, host.memory_usage_percent))}</span>
            </td>
            <td>${buildStatusPill(host.connection_state)}</td>
            <td>${host.in_maintenance_mode ? "Sim" : "Nao"}</td>
            <td>
                <div class="host-actions">
                    <button class="button button-ghost" type="button" data-host-action="enter_maintenance" data-host-moid="${escapeHtml(host.moid)}">Entrar</button>
                    <button class="button button-ghost" type="button" data-host-action="exit_maintenance" data-host-moid="${escapeHtml(host.moid)}">Sair</button>
                    <button class="button button-secondary" type="button" data-host-action="reboot" data-host-moid="${escapeHtml(host.moid)}">Reboot</button>
                    <button class="button button-secondary" type="button" data-host-action="shutdown" data-host-moid="${escapeHtml(host.moid)}">Shutdown</button>
                </div>
            </td>
        </tr>
    `).join("");
}

function renderSelectedVm() {
    const vm = state.selectedVmDetails;
    if (!vm) {
        renderNoVmSelected();
        return;
    }

    elements.selectedVmTitle.textContent = vm.name;
    elements.selectedVmSubtitle.innerHTML = `
        ${buildStatusPill(vm.power_state)}
        <span class="mono">${escapeHtml(vm.moid)}</span>
        <span>${escapeHtml(vm.host_name || "-")}</span>
    `;

    elements.renameForm.elements.name.value = vm.name || "";
    elements.hardwareForm.elements.cpu.value = vm.cpu_count || "";
    elements.hardwareForm.elements.memory_mb.value = vm.memory_mb || "";
    renderVmOverview(vm);
    renderRemoteAccess(vm);
    renderVmMediaSummary(vm);
    renderSnapshots(vm.snapshots || []);
    renderIsoLibrary();
}

function renderNoVmSelected() {
    elements.selectedVmTitle.textContent = "Nenhuma VM selecionada";
    elements.selectedVmSubtitle.textContent = "Selecione uma VM para habilitar as acoes.";
    elements.renameForm.reset();
    elements.hardwareForm.reset();
    elements.snapshotForm.reset();
    elements.vmOverviewCards.innerHTML = buildInfoMetricCards([], "Selecione uma VM para ver CPU, RAM, rede e disco.");
    elements.vmNetworkList.innerHTML = `<p class="empty-card">Selecione uma VM para ver interfaces e uso de rede.</p>`;
    elements.vmStorageList.innerHTML = `<p class="empty-card">Selecione uma VM para ver espaco e volumes.</p>`;
    renderRemoteAccess(null);
    renderVmMediaSummary(null);
    elements.snapshotList.innerHTML = `<p class="empty-card">Selecione uma VM para listar snapshots.</p>`;
    renderIsoLibrary();
}

function renderSnapshots(snapshots) {
    if (!snapshots.length) {
        elements.snapshotList.innerHTML = `<p class="empty-card">Nenhum snapshot encontrado para esta VM.</p>`;
        return;
    }

    elements.snapshotList.innerHTML = snapshots.map((snapshot) => `
        <article class="snapshot-card">
            <strong>${escapeHtml(snapshot.name)}</strong>
            <div class="snapshot-meta">
                <span>${escapeHtml(snapshot.path)}</span>
                <span>${escapeHtml(snapshot.state || "unknown")}</span>
                <span>${escapeHtml(snapshot.created_at || "-")}</span>
            </div>
            <p>${escapeHtml(snapshot.description || "Sem descricao.")}</p>
            <div class="snapshot-actions">
                <button class="button button-primary" type="button" data-snapshot-action="revert" data-snapshot-moid="${escapeHtml(snapshot.moid)}">Reverter</button>
                <button class="button button-secondary" type="button" data-snapshot-action="delete" data-snapshot-moid="${escapeHtml(snapshot.moid)}">Remover</button>
            </div>
        </article>
    `).join("");
}

function renderVmOverview(vm) {
    const performance = vm.performance || {};
    elements.vmOverviewCards.innerHTML = buildInfoMetricCards([
        {
            label: "CPU",
            value: formatPercent(vm.cpu_usage_percent),
            note: vm.cpu_usage_mhz ? `${escapeHtml(String(vm.cpu_usage_mhz))} MHz` : "Sem telemetria",
        },
        {
            label: "RAM",
            value: formatMemory(vm.host_memory_usage_mb),
            note: vm.memory_mb ? `${formatMemory(vm.memory_mb)} alocados` : "Sem alocacao",
        },
        {
            label: "Rede",
            value: formatPerfValue(performance.network_usage),
            note: performance.sample_time ? `Amostra ${escapeHtml(formatTimestamp(performance.sample_time))}` : "Sem amostra",
        },
        {
            label: "Disco",
            value: formatPerfValue(performance.disk_usage),
            note: vm.storage_used_gb != null ? `${formatStorage(vm.storage_used_gb)} usados` : "Sem inventario",
        },
        {
            label: "Provisionado",
            value: formatStorage(vm.storage_gb),
            note: vm.guest_disk_free_gb != null ? `${formatStorage(vm.guest_disk_free_gb)} livres no guest` : "Sem VMware Tools",
        },
        {
            label: "Uptime",
            value: formatUptime(vm.uptime_seconds),
            note: vm.boot_time ? `Boot ${escapeHtml(formatTimestamp(vm.boot_time))}` : "Sem boot time",
        },
    ], "Selecione uma VM para ver CPU, RAM, rede e disco.");

    elements.vmNetworkList.innerHTML = buildInfoCards(
        (vm.network_adapters || []).map((adapter) => ({
            title: adapter.label || adapter.network_name || adapter.mac || "NIC",
            meta: [
                adapter.network_name || adapter.guest_network || "Rede nao identificada",
                adapter.connected ? "Conectada" : "Desconectada",
                adapter.mac || "Sem MAC",
            ],
            body: (adapter.ip_addresses || []).length ? adapter.ip_addresses.join(", ") : "Sem IP informado",
        })),
        "Nenhuma interface de rede encontrada para esta VM."
    );

    const diskItems = (vm.guest_disks || []).map((disk) => ({
        title: disk.path || "Volume guest",
        meta: [
            `${formatStorage(disk.used_space_gb)} usados`,
            `${formatStorage(disk.free_space_gb)} livres`,
            `${formatStorage(disk.capacity_gb)} total`,
        ],
    }));

    if (!diskItems.length) {
        if (vm.storage_gb != null) {
            diskItems.push({
                title: "Storage provisionado",
                meta: [
                    `${formatStorage(vm.storage_used_gb)} comprometidos`,
                    `${formatStorage(vm.storage_gb)} provisionados`,
                ],
                body: "Use VMware Tools na VM para ver os volumes do sistema operacional.",
            });
        }
    }

    elements.vmStorageList.innerHTML = buildInfoCards(
        diskItems,
        "Nenhum volume guest encontrado. Instale VMware Tools para ver espaco dentro da VM."
    );
}

function renderRemoteAccess(vm) {
    const access = vm?.remote_access || null;
    const previousDetectedHost = elements.remoteGuestIp.dataset.detectedHost || "";
    const currentHostValue = (elements.remoteGuestIp.value || "").trim();
    const preserveCustomHost = Boolean(currentHostValue && currentHostValue !== previousDetectedHost);
    if (!access) {
        elements.remoteAccessSummary.innerHTML = `<p class="empty-card">Selecione uma VM para montar os atalhos de acesso remoto.</p>`;
        elements.remoteAccessNotes.innerHTML = `<p class="empty-card">VMRC exige o cliente VMware Remote Console instalado. VNC depende de servidor dentro da VM.</p>`;
        if (!(elements.remoteGuestPort.value || "").trim()) {
            elements.remoteGuestPort.value = 22;
        }
        if (!elements.remoteLegacyCompat.checked) {
            elements.remoteLegacyCompat.checked = true;
        }
        if (!preserveCustomHost) {
            elements.remoteGuestIp.value = "";
        }
        elements.remoteGuestIp.dataset.detectedHost = "";
        setVmrcLinkState(null);
        elements.openWebSshButton.disabled = !(elements.remoteGuestIp.value || "").trim();
        elements.closeWebSshButton.disabled = !sshTerminalState.sessionId;
        elements.copySshButton.disabled = !(elements.remoteGuestIp.value || "").trim();
        elements.downloadRdpButton.disabled = true;
        updateWebSshStatus(
            (elements.remoteGuestIp.value || "").trim()
                ? "Informe usuario e senha para abrir o terminal no host/IP manual."
                : "Selecione uma VM Linux/Unix com IP ou informe manualmente um host/IP para abrir o terminal."
        );
        if (sshTerminalState.term) {
            sshTerminalState.term.clear();
            sshTerminalState.term.writeln("Selecione uma VM ou informe manualmente um host/IP para abrir o terminal SSH embutido.");
        }
        return;
    }

    const suggestedUser = access.default_guest_user || guessGuestAccessUser(vm);
    const preserveCurrentValues = sshTerminalState.vmId === vm.moid;
    elements.remoteGuestUsername.value = preserveCurrentValues
        ? (elements.remoteGuestUsername.value || suggestedUser || "")
        : (suggestedUser || "");
    elements.remoteGuestUsername.placeholder = suggestedUser || "root ou Administrator";
    if (!preserveCustomHost || currentHostValue === previousDetectedHost) {
        elements.remoteGuestIp.value = access.guest_ip || "";
    }
    elements.remoteGuestIp.dataset.detectedHost = access.guest_ip || "";
    elements.remoteGuestPort.value = preserveCurrentValues
        ? (elements.remoteGuestPort.value || 22)
        : 22;
    setVmrcLinkState(access.vmrc_url);
    elements.openWebSshButton.disabled = !(elements.remoteGuestIp.value || "").trim();
    elements.closeWebSshButton.disabled = !sshTerminalState.sessionId;
    elements.copySshButton.disabled = !(elements.remoteGuestIp.value || "").trim();
    elements.downloadRdpButton.disabled = !access.rdp_available;

    elements.remoteAccessSummary.innerHTML = buildInfoCards([
        {
            title: "Console VMware",
            meta: [
                access.management_host || "-",
                access.management_port != null ? `Porta ${access.management_port}` : "Sem porta",
                access.management_username || "Sem usuario",
            ],
            body: access.vmrc_note || "Abre a VM pelo console VMware nativo.",
        },
        {
            title: "SSH",
            meta: [
                access.guest_ip || "Sem IP",
                access.ssh_available ? "Disponivel" : "Nao recomendado",
                access.guest_platform || "unknown",
            ],
            body: access.guest_ip
                ? "O terminal web e o botao de copia usam o IP detectado da VM."
                : "SSH depende de IP valido e normalmente faz sentido para VMs Linux ou Unix.",
        },
        {
            title: "RDP",
            meta: [
                access.guest_ip || "Sem IP",
                access.rdp_available ? "Disponivel" : "Nao recomendado",
                access.guest_platform || "unknown",
            ],
            body: access.rdp_available
                ? "O botao gera um arquivo .rdp com o IP atual da VM."
                : "RDP foi reservado para VMs Windows com IP conhecido.",
        },
    ], "Nenhum atalho de acesso remoto disponivel para esta VM.");

    elements.remoteAccessNotes.innerHTML = buildInfoCards([
        {
            title: "VNC",
            meta: [
                access.vnc_available ? "Disponivel" : "Nao nativo",
            ],
            body: access.vnc_note || "VNC exige servidor no guest.",
        },
        {
            title: "Terminal web",
            meta: [
                vm.guest_full_name || "Sistema nao identificado",
                vm.tools_status || "Tools desconhecido",
            ],
            body: access.guest_ip
                ? "O terminal embutido usa o cliente OpenSSH local do servidor Flask. Em hosts antigos, marque a compatibilidade legada."
                : "Sem IP conhecido. Use VMRC para acessar a VM mesmo sem rede funcional.",
        },
    ], "Sem observacoes de acesso remoto.");

    if (sshTerminalState.term && !sshTerminalState.sessionId) {
        sshTerminalState.term.clear();
        sshTerminalState.term.writeln("Terminal SSH pronto. Informe a senha e clique em 'Terminal web SSH'.");
    }
    updateWebSshStatus(
        (elements.remoteGuestIp.value || "").trim()
            ? "Informe a senha SSH do guest ou do host manual para abrir o terminal embutido."
            : "Sem IP detectado. Informe manualmente um host/IP para usar o terminal web SSH."
    );
}

function renderVmMediaSummary(vm) {
    if (!vm) {
        elements.vmMediaSummary.innerHTML = `<p class="empty-card">Selecione uma VM para ver o CD/DVD atual ou usar as ISOs abaixo.</p>`;
        return;
    }

    const cdroms = vm.cdroms || [];
    if (!cdroms.length) {
        elements.vmMediaSummary.innerHTML = buildInfoCards([
            {
                title: "Midia da VM",
                meta: [vm.name || "VM", "Sem dispositivo CD/DVD detectado"],
                body: "Use a lista de ISOs abaixo para criar ou adicionar uma unidade de CD/DVD com imagem ISO.",
            },
        ], "Sem informacoes de midia.");
        return;
    }

    elements.vmMediaSummary.innerHTML = cdroms.map((device) => `
        <article class="info-card">
            <strong>${escapeHtml(device.label || "CD/DVD")}</strong>
            <div class="info-meta">
                <span>${escapeHtml(device.backing_type || "unknown")}</span>
                <span>${device.connected ? "Conectado" : "Desconectado"}</span>
                <span>${device.start_connected ? "Auto-connect" : "Sem auto-connect"}</span>
            </div>
            <p>${escapeHtml(device.iso_path || device.summary || "Sem ISO montada.")}</p>
            <div class="snapshot-actions">
                <button class="button button-ghost" type="button" data-media-action="eject-iso">Ejetar ISO</button>
            </div>
        </article>
    `).join("");
}

function renderSelectedHost() {
    const host = state.selectedHostDetails;
    if (!host) {
        renderNoHostSelected();
        return;
    }

    elements.selectedHostTitle.textContent = host.name;
    elements.selectedHostSubtitle.innerHTML = `
        ${buildStatusPill(host.connection_state)}
        <span>${escapeHtml(host.product_name || host.model || "-")}</span>
        <span>${escapeHtml(host.cluster_name || "Standalone")}</span>
    `;

    const performance = host.performance || {};
    elements.hostOverviewCards.innerHTML = buildInfoMetricCards([
        {
            label: "CPU",
            value: formatPercent(host.cpu_usage_percent),
            note: host.cpu_usage_mhz ? `${escapeHtml(String(host.cpu_usage_mhz))} MHz` : "Sem telemetria",
        },
        {
            label: "RAM",
            value: formatMemory(host.memory_usage_mb),
            note: host.memory_total_mb ? `${formatMemory(host.memory_total_mb)} total` : "Sem total",
        },
        {
            label: "Rede",
            value: formatPerfValue(performance.network_usage),
            note: performance.sample_time ? `Amostra ${escapeHtml(formatTimestamp(performance.sample_time))}` : "Sem amostra",
        },
        {
            label: "Disco",
            value: formatStorage(host.storage_free_gb),
            note: host.storage_capacity_gb != null ? `${formatStorage(host.storage_capacity_gb)} total` : "Sem datastore",
        },
        {
            label: "VMs",
            value: host.vm_count != null ? escapeHtml(String(host.vm_count)) : "-",
            note: host.datastore_count != null ? `${escapeHtml(String(host.datastore_count))} datastores` : "Sem datastores",
        },
        {
            label: "Uptime",
            value: formatUptime(host.uptime_seconds),
            note: host.boot_time ? `Boot ${escapeHtml(formatTimestamp(host.boot_time))}` : "Sem boot time",
        },
    ], "Selecione um host para ver rede, licenca e consumo.");

    const license = host.license || {};
    elements.hostLicenseSummary.innerHTML = buildInfoCards([
        {
            title: license.edition || "Licenca do host",
            meta: [
                license.assigned_license?.license?.name || "Sem licenca atribuida",
                license.expires_on ? `Expira ${formatTimestamp(license.expires_on)}` : "Sem expiracao informada",
                license.remaining_hours != null ? `${escapeHtml(String(license.remaining_hours))} h restantes` : "Horas restantes indisponiveis",
            ],
            body: license.assigned_license?.license?.license_key
                ? `Chave ${maskLicenseKey(license.assigned_license.license.license_key)}`
                : "Ambientes em avaliacao podem expor expiracao pelas features e nao por chave atribuida.",
        },
    ], "Nenhuma informacao de licenca disponivel para este host.");

    const network = host.network || {};
    const summaryItems = [
        {
            title: "Gerenciamento",
            meta: [
                network.default_gateway || "Sem gateway",
                network.domain_name || "Sem dominio",
                (network.dns_servers || []).length ? `${network.dns_servers.length} DNS` : "Sem DNS",
            ],
            body: (network.dns_servers || []).join(", ") || "Nenhum servidor DNS configurado.",
        },
        ...(network.vmkernel_nics || []).map((nic) => ({
            title: nic.device || "vmk",
            meta: [
                nic.portgroup || "Sem portgroup",
                nic.ip_address || "Sem IP",
                nic.dhcp ? "DHCP" : (nic.subnet_mask || "IP estatico"),
            ],
            body: nic.mac || "Sem MAC",
        })),
    ];
    elements.hostNetworkSummary.innerHTML = buildInfoCards(
        summaryItems,
        "Nenhuma informacao de rede disponivel para este host."
    );

    const physicalNics = network.physical_nics || [];
    elements.hostUplinkBody.innerHTML = physicalNics.length
        ? physicalNics.map((nic) => `
            <tr>
                <td>
                    <strong>${escapeHtml(nic.device || "-")}</strong><br>
                    <span class="hint mono">${escapeHtml(nic.mac || "-")}</span>
                </td>
                <td>${nic.link_up ? "Up" : "Down"}</td>
                <td>${escapeHtml(formatLinkSpeed(nic.link_speed_mbps, nic.duplex))}</td>
                <td>${escapeHtml([nic.lldp_device, nic.lldp_port].filter(Boolean).join(" / ") || "-")}</td>
            </tr>
        `).join("")
        : `<tr><td colspan="4" class="empty">Nenhum uplink fisico encontrado.</td></tr>`;

    const switchItems = [
        ...(network.vswitches || []).map((item) => ({
            title: item.name || "vSwitch",
            meta: [
                item.mtu ? `MTU ${escapeHtml(String(item.mtu))}` : "MTU padrao",
                (item.uplinks || []).length ? `Uplinks: ${item.uplinks.join(", ")}` : "Sem uplinks",
                item.teaming?.policy || "Teaming nao informado",
            ],
            body: buildTeamingSummary(item.teaming, item.security),
        })),
        ...(network.portgroups || []).map((item) => ({
            title: item.name || "Portgroup",
            meta: [
                item.vswitch_name || "Sem vSwitch",
                item.vlan_id != null ? `VLAN ${escapeHtml(String(item.vlan_id))}` : "Sem VLAN",
                item.teaming?.policy || "Sem policy",
            ],
            body: buildTeamingSummary(item.teaming, item.security),
        })),
    ];
    elements.hostSwitchList.innerHTML = buildInfoCards(
        switchItems,
        "Nenhuma configuracao de vSwitch ou portgroup encontrada."
    );

    elements.hostDatastoreList.innerHTML = buildInfoCards(
        (host.datastores || []).map((item) => ({
            title: item.name || "Datastore",
            meta: [
                item.type || "Tipo desconhecido",
                `${formatStorage(item.free_space_gb)} livres`,
                `${formatStorage(item.capacity_gb)} total`,
            ],
        })),
        "Nenhum datastore encontrado para este host."
    );

    elements.hostVmList.innerHTML = buildInfoCards(
        (host.virtual_machines || []).map((item) => ({
            title: item.name || "VM",
            meta: [
                item.power_state || "unknown",
                item.moid || "-",
            ],
        })),
        "Nenhuma VM vinculada a este host."
    );
}

function renderNoHostSelected() {
    elements.selectedHostTitle.textContent = "Nenhum host selecionado";
    elements.selectedHostSubtitle.textContent = "Selecione um host para ver rede, licenca e consumo.";
    elements.hostOverviewCards.innerHTML = buildInfoMetricCards([], "Selecione um host para ver rede, licenca e consumo.");
    elements.hostLicenseSummary.innerHTML = `<p class="empty-card">Selecione um host para ver a licenca.</p>`;
    elements.hostNetworkSummary.innerHTML = `<p class="empty-card">Selecione um host para ver vmnic, vmk e uplinks.</p>`;
    elements.hostUplinkBody.innerHTML = `<tr><td colspan="4" class="empty">Selecione um host para listar uplinks.</td></tr>`;
    elements.hostSwitchList.innerHTML = `<p class="empty-card">Selecione um host para ver balanceamento e uplinks.</p>`;
    elements.hostDatastoreList.innerHTML = `<p class="empty-card">Selecione um host para ver espaco em disco.</p>`;
    elements.hostVmList.innerHTML = `<p class="empty-card">Selecione um host para ver as VMs vinculadas.</p>`;
}

async function refreshDockerContainerDetails(containerId) {
    if (!containerId) {
        renderNoDockerContainerSelected();
        return;
    }

    const [detailData, logsData] = await Promise.all([
        fetchJson(`/api/docker/containers/${encodeURIComponent(containerId)}`),
        fetchJson(`/api/docker/containers/${encodeURIComponent(containerId)}/logs?tail=200`),
    ]);

    state.selectedContainerId = containerId;
    state.selectedContainerDetails = {
        ...detailData.container,
        logs: logsData.logs,
    };
    renderSelectedDockerContainer();
    disableDockerActions(false);
}

function renderDockerOverview() {
    const overview = state.dockerOverview;
    if (!overview) {
        elements.dockerOverviewCards.innerHTML = `<p class="empty-card metric-empty">Conecte em um host Docker para carregar o resumo.</p>`;
        return;
    }

    elements.dockerOverviewCards.innerHTML = buildInfoMetricCards([
        {
            label: "Containers",
            value: escapeHtml(String(overview.containers ?? "-")),
            note: overview.containers_running != null ? `${escapeHtml(String(overview.containers_running))} running` : "Sem leitura",
        },
        {
            label: "Imagens",
            value: escapeHtml(String(overview.images ?? "-")),
            note: overview.driver || "Sem storage driver",
        },
        {
            label: "CPU",
            value: overview.cpus != null ? escapeHtml(String(overview.cpus)) : "-",
            note: overview.architecture || "Sem arquitetura",
        },
        {
            label: "Memoria",
            value: formatBytes(overview.memory_total_bytes),
            note: overview.operating_system || "Sem sistema operacional",
        },
    ], "Conecte em um host Docker para carregar o resumo.");
}

function renderDockerContainerTable() {
    if (!state.containers.length) {
        elements.dockerContainerTableBody.innerHTML = `<tr><td colspan="6" class="empty">Nenhum container encontrado.</td></tr>`;
        return;
    }

    elements.dockerContainerTableBody.innerHTML = state.containers.map((container) => `
        <tr data-container-id="${escapeHtml(container.id)}" class="${container.id === state.selectedContainerId ? "selected" : ""}">
            <td>
                <strong>${escapeHtml(container.name || container.short_id || "container")}</strong><br>
                <span class="hint mono">${escapeHtml(container.short_id || container.id || "-")}</span>
            </td>
            <td>${buildStatusPill(container.state || container.status || "unknown")}</td>
            <td>${escapeHtml(container.image || "-")}</td>
            <td>${escapeHtml(container.cpu_percent || "-")}</td>
            <td>${escapeHtml(container.memory_usage || "-")}</td>
            <td>${escapeHtml(container.ports || "-")}</td>
        </tr>
    `).join("");

    elements.dockerContainerTableBody.querySelectorAll("tr[data-container-id]").forEach((row) => {
        row.addEventListener("click", async () => {
            const containerId = row.dataset.containerId;
            state.selectedContainerId = containerId;
            renderDockerContainerTable();
            await refreshDockerContainerDetails(containerId);
        });
    });
}

function renderSelectedDockerContainer() {
    const container = state.selectedContainerDetails;
    if (!container) {
        renderNoDockerContainerSelected();
        return;
    }

    elements.selectedContainerTitle.textContent = container.name || "Container";
    elements.selectedContainerSubtitle.innerHTML = `
        ${buildStatusPill(container.state?.status || "unknown")}
        <span class="mono">${escapeHtml((container.id || "").slice(0, 12) || "-")}</span>
        <span>${escapeHtml(container.image || "-")}</span>
    `;

    const summary = state.containers.find((item) => item.id === container.id) || {};
    elements.dockerContainerMetrics.innerHTML = buildInfoMetricCards([
        {
            label: "CPU",
            value: summary.cpu_percent || "-",
            note: summary.pids ? `${escapeHtml(String(summary.pids))} PIDs` : "Sem leitura",
        },
        {
            label: "RAM",
            value: summary.memory_usage || "-",
            note: summary.memory_percent || "Sem leitura",
        },
        {
            label: "Rede",
            value: summary.net_io || "-",
            note: summary.block_io || "Sem IO",
        },
        {
            label: "Restart",
            value: escapeHtml(container.restart_policy || "-"),
            note: container.state?.exit_code != null ? `Exit ${escapeHtml(String(container.state.exit_code))}` : "Sem exit code",
        },
    ], "Selecione um container para ver CPU, RAM e estado.");

    elements.dockerContainerNetworks.innerHTML = buildInfoCards(
        Object.entries(container.networks || {}).map(([name, network]) => ({
            title: name,
            meta: [
                network.ip_address || "Sem IP",
                network.gateway || "Sem gateway",
                network.mac_address || "Sem MAC",
            ],
            body: (network.aliases || []).length ? network.aliases.join(", ") : "Sem aliases",
        })),
        "Nenhuma rede vinculada a este container."
    );

    elements.dockerContainerMounts.innerHTML = buildInfoCards(
        (container.mounts || []).map((mount) => ({
            title: mount.destination || mount.type || "Mount",
            meta: [
                mount.type || "-",
                mount.rw ? "RW" : "RO",
                mount.mode || "-",
            ],
            body: mount.source || "Sem origem",
        })),
        "Nenhum mount encontrado para este container."
    );

    elements.dockerContainerEnv.innerHTML = buildInfoCards(
        (container.env || []).map((item) => ({
            title: item,
            meta: [],
        })),
        "Nenhuma variavel de ambiente encontrada para este container."
    );

    elements.dockerContainerLogs.textContent = container.logs || "Sem logs recentes.";
    renderDockerCommandContext();
}

function renderNoDockerContainerSelected() {
    elements.selectedContainerTitle.textContent = "Nenhum container selecionado";
    elements.selectedContainerSubtitle.textContent = "Selecione um container para ver redes, mounts e logs.";
    elements.dockerContainerMetrics.innerHTML = `<p class="empty-card metric-empty">Selecione um container para ver CPU, RAM e estado.</p>`;
    elements.dockerContainerNetworks.innerHTML = `<p class="empty-card">Selecione um container para ver IP, gateway e aliases.</p>`;
    elements.dockerContainerMounts.innerHTML = `<p class="empty-card">Selecione um container para ver volumes e bind mounts.</p>`;
    elements.dockerContainerEnv.innerHTML = `<p class="empty-card">Selecione um container para ver as variaveis de ambiente.</p>`;
    elements.dockerContainerLogs.textContent = "Selecione um container para carregar os logs.";
    renderDockerCommandContext();
}

function renderDockerCommandContext() {
    if (!elements.dockerCommandContext) {
        return;
    }

    if (!state.dockerConnection) {
        elements.dockerCommandContext.textContent = "Conecte em um host Docker para liberar a criacao guiada e a CLI remota.";
        return;
    }

    if (!state.selectedContainerId) {
        elements.dockerCommandContext.textContent = "Use {{container}} para inserir o ID do container selecionado automaticamente, ou informe o ID manualmente no comando.";
        return;
    }

    const selected = state.selectedContainerDetails
        || state.containers.find((item) => item.id === state.selectedContainerId)
        || null;
    const label = selected?.name || (state.selectedContainerId || "").slice(0, 12) || "container";
    elements.dockerCommandContext.textContent = `Container selecionado: ${label}. Use {{container}} para reaproveitar esse alvo na CLI remota.`;
}

function populateCloneSelectors() {
    const inventory = state.inventory;
    const folders = inventory?.folders || [];
    const pools = inventory?.resource_pools || [];
    const datastores = inventory?.datastores || [];

    elements.cloneFolder.innerHTML = `
        <option value="">Pasta atual</option>
        ${folders.map((item) => `<option value="${escapeHtml(item.moid)}">${escapeHtml(item.name)}${item.parent_name ? ` / ${escapeHtml(item.parent_name)}` : ""}</option>`).join("")}
    `;

    elements.clonePool.innerHTML = `
        <option value="">Pool atual</option>
        ${pools.map((item) => `<option value="${escapeHtml(item.moid)}">${escapeHtml(item.name)}${item.parent_name ? ` / ${escapeHtml(item.parent_name)}` : ""}</option>`).join("")}
    `;

    elements.cloneDatastore.innerHTML = `
        <option value="">Padrao da VM origem</option>
        ${datastores.map((item) => `<option value="${escapeHtml(item.moid)}">${escapeHtml(item.name)} (${escapeHtml(String(item.free_space_gb))} GB livre)</option>`).join("")}
    `;
}

function populateCreateVmSelectors() {
    const inventory = state.inventory;
    const folders = inventory?.folders || [];
    const pools = inventory?.resource_pools || [];
    const datastores = inventory?.datastores || [];
    const hosts = inventory?.hosts || [];
    const networks = inventory?.networks || [];

    elements.createVmHost.innerHTML = `
        <option value="">Selecione um host</option>
        ${hosts.map((item) => `<option value="${escapeHtml(item.moid)}">${escapeHtml(item.name)}</option>`).join("")}
    `;

    elements.createVmFolder.innerHTML = `
        <option value="">Padrao do host/datacenter</option>
        ${folders.map((item) => `<option value="${escapeHtml(item.moid)}">${escapeHtml(item.name)}${item.parent_name ? ` / ${escapeHtml(item.parent_name)}` : ""}</option>`).join("")}
    `;

    elements.createVmPool.innerHTML = `
        <option value="">Padrao do host</option>
        ${pools.map((item) => `<option value="${escapeHtml(item.moid)}">${escapeHtml(item.name)}${item.parent_name ? ` / ${escapeHtml(item.parent_name)}` : ""}</option>`).join("")}
    `;

    const datastoreOptions = datastores.map((item) => `<option value="${escapeHtml(item.moid)}">${escapeHtml(item.name)} (${escapeHtml(String(item.free_space_gb))} GB livre)</option>`).join("");
    elements.createVmDatastore.innerHTML = `
        <option value="">Selecione um datastore</option>
        ${datastoreOptions}
    `;
    elements.createVmIsoDatastore.innerHTML = `
        <option value="">Mesmo datastore da VM</option>
        ${datastoreOptions}
    `;
    elements.isoDatastoreSelect.innerHTML = `
        <option value="">Selecione um datastore</option>
        ${datastoreOptions}
    `;

    elements.createVmNetwork.innerHTML = `
        <option value="">Sem placa de rede inicial</option>
        ${networks.map((item) => `<option value="${escapeHtml(item.moid)}">${escapeHtml(item.name)}</option>`).join("")}
    `;
}

function renderIsoLibrary() {
    if (!state.connection) {
        elements.isoLibraryList.innerHTML = `<p class="empty-card">Conecte no vSphere para listar as ISOs do datastore.</p>`;
        return;
    }
    if (!elements.isoDatastoreSelect.value) {
        elements.isoLibraryList.innerHTML = `<p class="empty-card">Selecione um datastore e clique em atualizar para listar as ISOs.</p>`;
        return;
    }
    if (!state.isoFiles.length) {
        elements.isoLibraryList.innerHTML = `<p class="empty-card">Nenhuma ISO encontrada para esse datastore ou pasta.</p>`;
        return;
    }

    elements.isoLibraryList.innerHTML = state.isoFiles.map((item) => `
        <article class="info-card">
            <strong>${escapeHtml(item.path || "-")}</strong>
            <div class="info-meta">
                <span>${escapeHtml(item.datastore_name || "-")}</span>
                <span>${formatBytes(item.size_bytes)}</span>
                <span>${escapeHtml(item.modified_at ? formatTimestamp(item.modified_at) : "Sem data")}</span>
            </div>
            <p>${escapeHtml(item.full_path || item.path || "-")}</p>
            <div class="snapshot-actions">
                <button class="button button-primary" type="button" data-iso-action="use-create-vm" data-datastore-moid="${escapeHtml(item.datastore_moid)}" data-iso-path="${escapeHtml(item.path)}">Usar na nova VM</button>
                <button class="button button-ghost" type="button" data-iso-action="mount-vm" data-datastore-moid="${escapeHtml(item.datastore_moid)}" data-iso-path="${escapeHtml(item.path)}" ${state.selectedVmId ? "" : "disabled"}>Montar na VM</button>
            </div>
        </article>
    `).join("");
}

async function onRenameVm(event) {
    event.preventDefault();
    if (!state.selectedVmId) {
        showToast("Selecione uma VM antes de renomear.", true);
        return;
    }

    const payload = {
        name: new FormData(elements.renameForm).get("name"),
    };

    const data = await postJson(`/api/vms/${state.selectedVmId}/rename`, payload);
    showToast(data.message || "VM renomeada.");
    await refreshData();
}

async function onUpdateHardware(event) {
    event.preventDefault();
    if (!state.selectedVmId) {
        showToast("Selecione uma VM antes de alterar hardware.", true);
        return;
    }

    const formData = new FormData(elements.hardwareForm);
    const payload = {
        cpu: formData.get("cpu"),
        memory_mb: formData.get("memory_mb"),
    };

    const data = await postJson(`/api/vms/${state.selectedVmId}/hardware`, payload);
    showToast(data.message || "Hardware atualizado.");
    await refreshData();
}

async function onCreateSnapshot(event) {
    event.preventDefault();
    if (!state.selectedVmId) {
        showToast("Selecione uma VM antes de criar snapshot.", true);
        return;
    }

    const formData = new FormData(elements.snapshotForm);
    const payload = {
        name: formData.get("name"),
        description: formData.get("description"),
        include_memory: formData.get("include_memory") === "on",
        quiesce: formData.get("quiesce") === "on",
    };

    const data = await postJson(`/api/vms/${state.selectedVmId}/snapshots`, payload);
    showToast(data.message || "Snapshot criado.");
    elements.snapshotForm.reset();
    await refreshData();
}

async function onCloneVm(event) {
    event.preventDefault();
    if (!state.selectedVmId) {
        showToast("Selecione uma VM antes de clonar.", true);
        return;
    }

    const formData = new FormData(elements.cloneForm);
    const payload = {
        name: formData.get("name"),
        folder_moid: formData.get("folder_moid"),
        resource_pool_moid: formData.get("resource_pool_moid"),
        datastore_moid: formData.get("datastore_moid"),
        power_on: formData.get("power_on") === "on",
        as_template: formData.get("as_template") === "on",
    };

    const data = await postJson(`/api/vms/${state.selectedVmId}/clone`, payload);
    showToast(data.message || "Clone criado.");
    elements.cloneForm.reset();
    await refreshData();
}

async function onCreateVm(event) {
    event.preventDefault();
    if (!state.connection) {
        showToast("Conecte no vSphere antes de criar uma nova VM.", true);
        return;
    }

    const formData = new FormData(elements.createVmForm);
    const payload = {
        name: formData.get("name"),
        guest_id: formData.get("guest_id"),
        host_moid: formData.get("host_moid"),
        folder_moid: formData.get("folder_moid"),
        resource_pool_moid: formData.get("resource_pool_moid"),
        datastore_moid: formData.get("datastore_moid"),
        network_moid: formData.get("network_moid"),
        iso_datastore_moid: formData.get("iso_datastore_moid"),
        iso_path: formData.get("iso_path"),
        cpu: formData.get("cpu"),
        memory_mb: formData.get("memory_mb"),
        disk_gb: formData.get("disk_gb"),
        power_on: formData.get("power_on") === "on",
    };

    const data = await postJson("/api/vms", payload);
    showToast(data.message || "Nova VM criada.");
    elements.createVmForm.reset();
    elements.createVmIsoPath.value = "";
    await refreshData();
}

function clearCreateVmIsoSelection() {
    elements.createVmIsoDatastore.value = "";
    elements.createVmIsoPath.value = "";
}

function applyIsoToCreateVm(datastoreMoid, isoPath) {
    elements.createVmIsoDatastore.value = datastoreMoid;
    elements.createVmIsoPath.value = isoPath;
}

async function onRefreshIsos() {
    if (!state.connection) {
        showToast("Conecte no vSphere antes de listar ISOs.", true);
        return;
    }
    const datastoreMoid = elements.isoDatastoreSelect.value;
    if (!datastoreMoid) {
        showToast("Selecione um datastore para listar as ISOs.", true);
        return;
    }

    const folder = (elements.isoFolderPath.value || "").trim();
    const url = buildAppUrl(`/api/datastores/${datastoreMoid}/isos`);
    if (folder) {
        url.searchParams.set("folder", folder);
    }

    const data = await fetchJson(url.toString());
    state.isoFiles = data.isos || [];
    renderIsoLibrary();
    showToast("Lista de ISO atualizada.");
}

async function onUploadIso(event) {
    event.preventDefault();
    if (!state.connection) {
        showToast("Conecte no vSphere antes de enviar uma ISO.", true);
        return;
    }
    const datastoreMoid = elements.isoDatastoreSelect.value;
    if (!datastoreMoid) {
        showToast("Selecione um datastore para receber a ISO.", true);
        return;
    }
    const hasLocalFile = Boolean(elements.isoFileInput.files?.length);
    const hasSourceUrl = Boolean((elements.isoSourceUrl.value || "").trim());
    if (!hasLocalFile && !hasSourceUrl) {
        showToast("Selecione um arquivo ISO local ou informe uma URL HTTP/HTTPS.", true);
        return;
    }

    const formData = new FormData(elements.isoUploadForm);
    showToast(hasLocalFile ? "Enviando ISO para o datastore..." : "Baixando ISO da URL e enviando para o datastore...");
    const data = await submitForm(`/api/datastores/${datastoreMoid}/isos`, formData);
    showToast(data.message || "ISO enviada.");
    elements.isoFileInput.value = "";
    elements.isoSourceUrl.value = "";
    await onRefreshIsos();
    if (data.iso) {
        applyIsoToCreateVm(data.iso.datastore_moid, data.iso.path);
    }
}

async function onCopySshCommand() {
    const vm = state.selectedVmDetails;
    const access = vm?.remote_access;
    const sshHost = (elements.remoteGuestIp.value || "").trim() || access?.guest_ip || "";
    if (!sshHost) {
        showToast("Informe um host/IP manual ou selecione uma VM com IP conhecido para montar o comando SSH.", true);
        return;
    }

    const guestUser = (elements.remoteGuestUsername.value || "").trim()
        || access?.default_guest_user
        || guessGuestAccessUser(vm);
    const target = guestUser ? `${guestUser}@${sshHost}` : sshHost;
    const guestPort = Number(elements.remoteGuestPort.value || 22);
    const legacyCompat = elements.remoteLegacyCompat.checked;
    const parts = ["ssh"];
    if (legacyCompat) {
        parts.push("-o", "HostKeyAlgorithms=+ssh-rsa", "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa");
    }
    if (guestPort && guestPort !== 22) {
        parts.push("-p", String(guestPort));
    }
    parts.push(target);
    const command = parts.join(" ");

    try {
        await copyTextToClipboard(command);
        showToast(`Comando copiado: ${command}`);
    } catch (error) {
        showToast(`Nao foi possivel copiar. Use manualmente: ${command}`, true);
    }
}

function onDownloadRdpFile() {
    const vm = state.selectedVmDetails;
    const access = vm?.remote_access;
    if (!access?.rdp_available) {
        showToast("RDP foi habilitado apenas para VMs Windows com IP conhecido.", true);
        return;
    }

    const url = buildAppUrl(`/api/vms/${state.selectedVmId}/remote-access/rdp`);
    const guestUser = (elements.remoteGuestUsername.value || "").trim();
    if (guestUser) {
        url.searchParams.set("username", guestUser);
    }

    const link = document.createElement("a");
    link.href = url.toString();
    link.click();
}

function onOpenVmrc(event) {
    if (elements.openVmrcLink.dataset.disabled === "true") {
        event.preventDefault();
        showToast("Selecione uma VM para abrir o console VMware.", true);
    }
}

async function onOpenWebSsh() {
    const vm = state.selectedVmDetails;
    const access = vm?.remote_access;
    const sshHost = (elements.remoteGuestIp.value || "").trim() || access?.guest_ip || "";
    if (!sshHost) {
        showToast("Informe um host/IP manual ou selecione uma VM com IP conhecido para abrir o terminal SSH embutido.", true);
        return;
    }

    const guestUser = (elements.remoteGuestUsername.value || "").trim()
        || access?.default_guest_user
        || guessGuestAccessUser(vm);
    const guestPassword = elements.remoteGuestPassword.value || "";
    const guestPort = Number(elements.remoteGuestPort.value || 22);
    const legacyCompat = elements.remoteLegacyCompat.checked;

    if (!guestUser || !guestPassword) {
        showToast("Informe usuario e senha SSH do guest.", true);
        return;
    }

    try {
        ensureWebTerminal();
        sshTerminalState.term.clear();
        sshTerminalState.term.writeln(`Conectando em ${sshHost}:${guestPort} como ${guestUser}...`);
        updateWebSshStatus("Abrindo sessao SSH...");

        if (sshTerminalState.sessionId) {
            await closeEmbeddedSsh({ silent: true, preserveOutput: false });
        }

        const data = await postJson("/api/terminals", {
            host: sshHost,
            port: guestPort,
            username: guestUser,
            password: guestPassword,
            legacy_compat: legacyCompat,
        });
        sshTerminalState.sessionId = data.terminal.sid;
        sshTerminalState.cursor = 0;
        sshTerminalState.pendingInput = "";
        sshTerminalState.vmId = state.selectedVmId;
        elements.closeWebSshButton.disabled = false;
        updateWebSshStatus(`Terminal conectado em ${sshHost}:${guestPort}.`);
        elements.remoteGuestPassword.value = "";
        void resizeEmbeddedSsh();
        pollEmbeddedSshOutput();
        sshTerminalState.term.focus();
    } catch (error) {
        updateWebSshStatus(`Falha ao abrir terminal: ${error.message}`, true);
    }
}

async function onCloseWebSsh() {
    await closeEmbeddedSsh();
}

async function closeEmbeddedSsh(options = {}) {
    const { silent = false, preserveOutput = true } = options;

    if (sshTerminalState.inputFlushTimer) {
        window.clearTimeout(sshTerminalState.inputFlushTimer);
        sshTerminalState.inputFlushTimer = null;
    }
    if (sshTerminalState.pollTimer) {
        window.clearTimeout(sshTerminalState.pollTimer);
        sshTerminalState.pollTimer = null;
    }

    const sid = sshTerminalState.sessionId;
    sshTerminalState.sessionId = null;
    sshTerminalState.cursor = 0;
    sshTerminalState.pendingInput = "";
    sshTerminalState.vmId = null;
    elements.closeWebSshButton.disabled = true;

    if (sid) {
        try {
            await fetchJson(`/api/terminals/${sid}`, { method: "DELETE" });
        } catch (error) {
            if (!silent) {
                showToast(error.message, true);
            }
        }
    }

    if (sshTerminalState.term) {
        if (!preserveOutput) {
            sshTerminalState.term.clear();
        }
        if (!silent) {
            sshTerminalState.term.writeln("\r\n[terminal encerrado]");
        }
    }

    if (!silent) {
        updateWebSshStatus("Terminal SSH encerrado.");
    }
}

function ensureWebTerminal() {
    if (sshTerminalState.term) {
        return sshTerminalState.term;
    }
    if (!window.Terminal) {
        throw new Error("Biblioteca do terminal web nao foi carregada.");
    }

    const term = new window.Terminal({
        cursorBlink: true,
        fontFamily: '"IBM Plex Mono", "Cascadia Code", monospace',
        fontSize: 14,
        rows: 24,
        cols: 100,
        theme: {
            background: "#121a17",
            foreground: "#eef6f3",
            cursor: "#d97706",
            selectionBackground: "rgba(217, 119, 6, 0.24)",
        },
    });
    term.open(elements.webSshTerminal);
    term.writeln("Selecione uma VM para abrir o terminal SSH embutido.");
    term.onData((data) => {
        if (!sshTerminalState.sessionId) {
            return;
        }
        sshTerminalState.pendingInput += data;
        scheduleEmbeddedSshFlush();
    });

    if (!sshTerminalState.resizeBound) {
        window.addEventListener("resize", () => {
            if (sshTerminalState.sessionId) {
                void resizeEmbeddedSsh();
            }
        });
        sshTerminalState.resizeBound = true;
    }

    sshTerminalState.term = term;
    return term;
}

function scheduleEmbeddedSshFlush() {
    if (sshTerminalState.inputFlushTimer || !sshTerminalState.sessionId) {
        return;
    }
    sshTerminalState.inputFlushTimer = window.setTimeout(() => {
        sshTerminalState.inputFlushTimer = null;
        void flushEmbeddedSshInput();
    }, 35);
}

async function flushEmbeddedSshInput() {
    if (!sshTerminalState.sessionId || !sshTerminalState.pendingInput) {
        return;
    }
    const sid = sshTerminalState.sessionId;
    const payload = sshTerminalState.pendingInput;
    sshTerminalState.pendingInput = "";

    try {
        await postJson(`/api/terminals/${sid}/input`, { data: payload });
    } catch (error) {
        updateWebSshStatus(`Falha ao enviar dados ao terminal: ${error.message}`, true);
        await closeEmbeddedSsh({ silent: true, preserveOutput: true });
    }
}

async function pollEmbeddedSshOutput() {
    if (!sshTerminalState.sessionId) {
        return;
    }

    const sid = sshTerminalState.sessionId;
    try {
        const data = await fetchJson(`/api/terminals/${sid}/output?cursor=${sshTerminalState.cursor}`);
        if (sid !== sshTerminalState.sessionId) {
            return;
        }
        sshTerminalState.cursor = data.cursor;
        if (data.data) {
            ensureWebTerminal().write(data.data);
        }
        if (data.closed) {
            sshTerminalState.sessionId = null;
            sshTerminalState.vmId = null;
            elements.closeWebSshButton.disabled = true;
            updateWebSshStatus(`Terminal encerrado${data.returncode != null ? ` (codigo ${data.returncode})` : ""}.`);
            return;
        }
    } catch (error) {
        if (sid === sshTerminalState.sessionId) {
            sshTerminalState.sessionId = null;
            sshTerminalState.vmId = null;
            elements.closeWebSshButton.disabled = true;
            updateWebSshStatus(`Falha ao consultar o terminal: ${error.message}`, true);
        }
        return;
    }

    sshTerminalState.pollTimer = window.setTimeout(() => {
        void pollEmbeddedSshOutput();
    }, 180);
}

async function resizeEmbeddedSsh() {
    if (!sshTerminalState.sessionId || !sshTerminalState.term) {
        return;
    }
    try {
        await postJson(`/api/terminals/${sshTerminalState.sessionId}/resize`, {
            cols: sshTerminalState.term.cols,
            rows: sshTerminalState.term.rows,
        });
    } catch (error) {
        updateWebSshStatus(`Nao foi possivel atualizar o tamanho do terminal: ${error.message}`, true);
    }
}

function updateWebSshStatus(message, isError = false) {
    elements.webSshStatus.textContent = message;
    elements.webSshStatus.classList.toggle("terminal-status-error", isError);
}

function disableDockerCommandForms(disabled) {
    setFormDisabled(elements.dockerCreateForm, disabled);
    setFormDisabled(elements.dockerCommandForm, disabled);
    if (elements.dockerClearCommandOutputButton) {
        elements.dockerClearCommandOutputButton.disabled = disabled;
    }
}

function disableDockerActions(disabled) {
    document.querySelectorAll(".docker-action").forEach((button) => {
        button.disabled = disabled;
    });
}

function disableVmActions(disabled) {
    document.querySelectorAll(".vm-action").forEach((button) => {
        button.disabled = disabled;
    });
    [elements.renameForm, elements.hardwareForm, elements.snapshotForm, elements.cloneForm].forEach((form) => {
        setFormDisabled(form, disabled);
    });
}

function setFormDisabled(form, disabled) {
    if (!form) {
        return;
    }
    Array.from(form.elements).forEach((field) => {
        if (field instanceof HTMLElement) {
            field.disabled = disabled;
        }
    });
}

async function fetchJson(url, options = {}) {
    const response = await fetch(resolveAppUrl(url), {
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {}),
        },
        ...options,
    });

    const data = await response.json().catch(() => ({ ok: false, error: "Resposta invalida do servidor." }));

    if (!response.ok || data.ok === false) {
        const message = data.error || `Erro HTTP ${response.status}`;
        showToast(message, true);
        throw new Error(message);
    }

    return data;
}

function postJson(url, payload) {
    return fetchJson(url, {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

async function submitForm(url, formData, options = {}) {
    const response = await fetch(resolveAppUrl(url), {
        method: options.method || "POST",
        body: formData,
        ...options,
    });

    const data = await response.json().catch(() => ({ ok: false, error: "Resposta invalida do servidor." }));
    if (!response.ok || data.ok === false) {
        const message = data.error || `Erro HTTP ${response.status}`;
        showToast(message, true);
        throw new Error(message);
    }

    return data;
}

function buildAppUrl(path = "") {
    return new URL(String(path || "").replace(/^\/+/, ""), APP_BASE_URL);
}

function resolveAppUrl(url) {
    if (url instanceof URL) {
        return url.toString();
    }

    const raw = String(url || "");
    if (/^[a-z][a-z0-9+.-]*:/i.test(raw)) {
        return raw;
    }

    return buildAppUrl(raw).toString();
}

function getDockerCommandPreset(key) {
    const presets = {
        list: "docker ps -a",
        images: "docker images",
        logs: "docker logs --tail 200 {{container}}",
        inspect: "docker inspect {{container}}",
        "exec-sh": "docker exec {{container}} sh -lc \"ls -la\"",
        "compose-ps": "docker compose ps",
        "system-df": "docker system df",
    };
    return presets[key] || "";
}

function buildDockerCommandOutput(command, output) {
    const chunks = [];
    if (command) {
        chunks.push(`$ ${command}`);
    }
    chunks.push(output || "(sem saida)");
    return chunks.join("\n\n");
}

function buildStatusPill(value) {
    const normalized = String(value || "unknown").replace(/\s+/g, "");
    return `<span class="status-pill status-${escapeHtml(normalized)}">${escapeHtml(value || "unknown")}</span>`;
}

function buildEmptyCards() {
    return ["Datacenters", "Clusters", "Hosts", "VMs", "Datastores", "Networks"].map((label) => `
        <article class="metric-card">
            <span>${escapeHtml(label)}</span>
            <strong>-</strong>
        </article>
    `).join("");
}

function formatMemory(memoryMb) {
    if (memoryMb == null || memoryMb === "") {
        return "-";
    }
    const gb = Number(memoryMb) / 1024;
    return `${gb.toFixed(gb >= 10 ? 0 : 1)} GB`;
}

function formatStorage(storageGb) {
    if (storageGb == null || storageGb === "") {
        return "-";
    }
    const value = Number(storageGb);
    return `${value.toFixed(value >= 10 ? 0 : 1)} GB`;
}

function formatBytes(value) {
    if (value == null || value === "" || Number.isNaN(Number(value))) {
        return "-";
    }
    const bytes = Number(value);
    if (bytes < 1024) {
        return `${bytes} B`;
    }
    const units = ["KB", "MB", "GB", "TB"];
    let size = bytes / 1024;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex += 1;
    }
    return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

function formatPercent(value) {
    if (value == null || value === "") {
        return "-";
    }
    return `${Number(value).toFixed(1)}%`;
}

function formatPerfValue(metric) {
    if (!metric || metric.value == null) {
        return "-";
    }
    return `${Number(metric.value).toFixed(metric.unit === "%" ? 1 : 2)} ${escapeHtml(metric.unit || "")}`.trim();
}

function formatUptime(seconds) {
    if (seconds == null || seconds === "") {
        return "-";
    }
    const total = Number(seconds);
    const days = Math.floor(total / 86400);
    const hours = Math.floor((total % 86400) / 3600);
    if (days > 0) {
        return `${days}d ${hours}h`;
    }
    const minutes = Math.floor((total % 3600) / 60);
    return `${hours}h ${minutes}m`;
}

function formatTimestamp(value) {
    if (!value) {
        return "-";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return String(value);
    }
    return date.toLocaleString("pt-BR");
}

function formatCompactUsage(cpuPercent, memoryPercent) {
    return `CPU ${formatPercent(cpuPercent)} / RAM ${formatPercent(memoryPercent)}`;
}

function formatLinkSpeed(speedMbps, duplex) {
    if (!speedMbps) {
        return "-";
    }
    return `${speedMbps} Mb ${duplex || ""}`.trim();
}

function buildInfoMetricCards(items, emptyText) {
    if (!items.length) {
        return `<p class="empty-card metric-empty">${escapeHtml(emptyText)}</p>`;
    }

    return items.map((item) => `
        <article class="metric-card">
            <span>${escapeHtml(item.label)}</span>
            <strong>${item.value || "-"}</strong>
            <span class="metric-note">${escapeHtml(item.note || "")}</span>
        </article>
    `).join("");
}

function buildInfoCards(items, emptyText) {
    if (!items.length) {
        return `<p class="empty-card">${escapeHtml(emptyText)}</p>`;
    }

    return items.map((item) => `
        <article class="info-card">
            <strong>${escapeHtml(item.title || "-")}</strong>
            <div class="info-meta">
                ${(item.meta || []).map((meta) => `<span>${escapeHtml(String(meta || "-"))}</span>`).join("")}
            </div>
            ${item.body ? `<p>${escapeHtml(String(item.body))}</p>` : ""}
        </article>
    `).join("");
}

function buildTeamingSummary(teaming, security) {
    const parts = [];
    if (teaming?.active_nics?.length) {
        parts.push(`Ativas: ${teaming.active_nics.join(", ")}`);
    }
    if (teaming?.standby_nics?.length) {
        parts.push(`Standby: ${teaming.standby_nics.join(", ")}`);
    }
    if (security) {
        parts.push(
            `Seguranca promisc=${boolLabel(security.allow_promiscuous)}, mac=${boolLabel(security.mac_changes)}, forged=${boolLabel(security.forged_transmits)}`
        );
    }
    return parts.join(" | ") || "Sem detalhes de teaming.";
}

function setVmrcLinkState(url) {
    if (url) {
        elements.openVmrcLink.href = url;
        elements.openVmrcLink.dataset.disabled = "false";
        elements.openVmrcLink.classList.remove("button-link-disabled");
        return;
    }

    elements.openVmrcLink.href = "#";
    elements.openVmrcLink.dataset.disabled = "true";
    elements.openVmrcLink.classList.add("button-link-disabled");
}

function guessGuestAccessUser(vm) {
    const os = String(vm?.guest_full_name || "").toLowerCase();
    if (os.includes("windows")) {
        return "Administrator";
    }
    if (os) {
        return "root";
    }
    return "";
}

async function copyTextToClipboard(text) {
    if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
    }

    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "absolute";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    document.body.removeChild(textarea);
}

function boolLabel(value) {
    if (value === true) {
        return "on";
    }
    if (value === false) {
        return "off";
    }
    return "-";
}

function maskLicenseKey(value) {
    const text = String(value || "");
    if (text.length <= 6) {
        return text || "-";
    }
    return `${text.slice(0, 4)}...${text.slice(-4)}`;
}

let toastTimer = null;

function showToast(message, isError = false) {
    elements.toast.textContent = message;
    elements.toast.className = `toast visible${isError ? " error" : ""}`;
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => {
        elements.toast.className = "toast";
    }, 2800);
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}
