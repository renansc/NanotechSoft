(function () {
  const DOCS = [
    {
      file: "ARQUITETURA_SISTEMA.md",
      title: "Arquitetura",
      description: "Visao geral da arquitetura, modulos e integracoes.",
    },
    {
      file: "DIAGRAMAS_E_PROCESSOS.md",
      title: "Diagramas",
      description: "Fluxogramas e sequencias Mermaid dos processos principais.",
    },
    {
      file: "OPERACAO_E_DEPLOY.md",
      title: "Operacao e Deploy",
      description: "Runbook operacional, certificados, backup e troubleshooting.",
    },
    {
      file: "NFE_RECEITA_E_INTEGRACAO.md",
      title: "NF-e e Receita",
      description: "Passo a passo operacional da NF-e, portal assistido e limites atuais da integracao.",
    },
    {
      file: "API_E_DADOS.md",
      title: "API e Dados",
      description: "Referencia de API, payloads e modelo de dados.",
    },
    {
      file: "AI_CONTEXT.md",
      title: "AI Context",
      description: "Resumo rapido para agentes, comandos uteis e mapa do projeto.",
    },
  ];

  const byFile = Object.fromEntries(DOCS.map((doc) => [doc.file, doc]));

  function slugify(text) {
    return String(text || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .replace(/-{2,}/g, "-");
  }

  function rewriteMdLinks(container) {
    container.querySelectorAll('a[href$=".md"]').forEach((anchor) => {
      const href = anchor.getAttribute("href") || "";
      const normalized = href.split("/").pop();
      if (!byFile[normalized]) return;
      anchor.setAttribute("href", `documentacao.html?doc=${encodeURIComponent(normalized)}`);
    });
  }

  function enhanceRenderedContent(container) {
    const usedIds = new Set();
    container.querySelectorAll("h1, h2, h3").forEach((heading) => {
      const base = slugify(heading.textContent) || "secao";
      let id = base;
      let seq = 2;
      while (usedIds.has(id)) {
        id = `${base}-${seq++}`;
      }
      usedIds.add(id);
      heading.id = id;
    });

    container.querySelectorAll("pre > code").forEach((codeEl) => {
      const className = codeEl.className || "";
      if (!/\blanguage-mermaid\b/.test(className)) return;
      const pre = codeEl.parentElement;
      if (!pre) return;
      const wrapper = document.createElement("div");
      wrapper.className = "mermaid";
      wrapper.textContent = codeEl.textContent || "";
      pre.replaceWith(wrapper);
    });

    rewriteMdLinks(container);
  }

  async function renderMermaid(container) {
    if (!window.mermaid) return;
    const blocks = container.querySelectorAll(".mermaid");
    if (!blocks.length) return;
    try {
      window.mermaid.initialize({
        startOnLoad: false,
        securityLevel: "loose",
        theme: "default",
        flowchart: { useMaxWidth: true, htmlLabels: true },
      });
      await window.mermaid.run({ nodes: blocks });
    } catch (err) {
      console.error("Mermaid render error:", err);
    }
  }

  function buildDocNav(currentFile) {
    const nav = document.getElementById("docsNav");
    if (!nav) return;
    nav.innerHTML = DOCS.map((doc) => `
      <a href="documentacao.html?doc=${encodeURIComponent(doc.file)}" class="${doc.file === currentFile ? "active" : ""}">
        <strong>${doc.title}</strong>
        <small>${doc.description}</small>
      </a>
    `).join("");
  }

  function buildToc(container) {
    const toc = document.getElementById("docsTocList");
    const tocWrap = document.getElementById("docsToc");
    if (!toc || !tocWrap) return;
    const headings = Array.from(container.querySelectorAll("h1, h2, h3"));
    if (!headings.length) {
      tocWrap.style.display = "none";
      return;
    }
    tocWrap.style.display = "";
    toc.innerHTML = headings
      .filter((node) => node.id)
      .map((node) => {
        const level = node.tagName.toLowerCase() === "h3" ? "level-3" : "";
        return `<a class="${level}" href="#${node.id}">${node.textContent}</a>`;
      })
      .join("");
  }

  function setDocMeta(file) {
    const titleEl = document.getElementById("docsTitle");
    const descEl = document.getElementById("docsDescription");
    const rawEl = document.getElementById("docsRawLink");
    const fileEl = document.getElementById("docsFileName");
    const doc = byFile[file] || { title: file, description: "" };
    if (titleEl) titleEl.textContent = doc.title;
    if (descEl) descEl.textContent = doc.description || "";
    if (rawEl) rawEl.href = file;
    if (fileEl) fileEl.textContent = file;
    document.title = `${doc.title} | Documentacao RioBranco`;
  }

  function defaultDocFromPage() {
    const body = document.body;
    const bodyDefault = body.getAttribute("data-default-doc");
    if (bodyDefault && byFile[bodyDefault]) return bodyDefault;
    return DOCS[0].file;
  }

  function resolveDocFromLocation() {
    const params = new URLSearchParams(window.location.search);
    const queryDoc = params.get("doc");
    if (queryDoc && byFile[queryDoc]) return queryDoc;
    return defaultDocFromPage();
  }

  async function loadDoc(file) {
    const target = document.getElementById("docsContent");
    if (!target) return;
    target.innerHTML = `<div class="docs-loading">Carregando ${file}...</div>`;

    try {
      const resp = await fetch(file, { cache: "no-store" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const markdown = await resp.text();
      if (!window.marked || !window.marked.parse) throw new Error("marked.min.js nao carregado");
      target.innerHTML = window.marked.parse(markdown, { gfm: true, breaks: false });
      enhanceRenderedContent(target);
      await renderMermaid(target);
      buildDocNav(file);
      buildToc(target);
      setDocMeta(file);
    } catch (err) {
      console.error(err);
      target.innerHTML = `<div class="docs-error">Nao foi possivel carregar <code>${file}</code>: ${String(err.message || err)}</div>`;
    }
  }

  async function bootViewer() {
    buildDocNav(resolveDocFromLocation());
    await loadDoc(resolveDocFromLocation());
  }

  window.DOCS_RIOBRANCO = DOCS;
  window.addEventListener("DOMContentLoaded", bootViewer);
})();
