#!/usr/bin/env python3
"""Helpers to build a compact, repo-aware task brief for RioBranco."""

from __future__ import annotations

from functools import lru_cache
import getpass
import os
import re
import platform
import subprocess
import socket
import unicodedata
from pathlib import Path

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency
    yaml = None


ROOT = Path(__file__).resolve().parents[1]

DOC_ORDER = [
    "docs/README.md",
    "docs/ARQUITETURA_SISTEMA.md",
    "docs/DIAGRAMAS_E_PROCESSOS.md",
    "docs/OPERACAO_E_DEPLOY.md",
    "docs/NFE_RECEITA_E_INTEGRACAO.md",
    "docs/API_E_DADOS.md",
    "docs/AI_CONTEXT.md",
    "docs/PLANO_REFATORACAO_E_PENDENCIAS.md",
]

SYSTEM_OVERVIEW_MODULES = [
    {
        "name": "Base da aplicacao",
        "summary": "Flask em `server.py`, frontend em `RioBranco.html`, `script.js` e `style.css`, com Nginx e Docker Compose no runtime.",
        "files": ["server.py", "RioBranco.html", "script.js", "style.css", "docker-compose.yml", "Dockerfile"],
    },
    {
        "name": "Operacao e deploy",
        "summary": "Scripts e rotinas para subir, derrubar, atualizar, salvar backup e diagnosticar o ambiente.",
        "files": ["up.sh", "down.sh", "update.sh", "tools/riob_agent.py", "tools/riob_agent_web.py", "docs/OPERACAO_E_DEPLOY.md"],
    },
    {
        "name": "Fretes e kanban",
        "summary": "Cadastro, atualizacao, historico e movimentacao de fretes nos status operacionais do dashboard.",
        "files": ["server.py", "dashboards.html", "docs/DIAGRAMAS_E_PROCESSOS.md", "docs/API_E_DADOS.md"],
    },
    {
        "name": "Devolucoes e anexos",
        "summary": "Pasta de fotos de devolucao, anexos do chat e demais arquivos persistidos em `app_data`.",
        "files": ["server.py", "docs/OPERACAO_E_DEPLOY.md", "docker-compose.yml"],
    },
    {
        "name": "Estoque e NF-e",
        "summary": "Fluxos de estoque, conferencia, leitura de XML/PDF/foto, DF-e, OCR e integracoes da NF-e.",
        "files": ["server.py", "nfe_ws.py", "docs/NFE_RECEITA_E_INTEGRACAO.md", "docs/API_E_DADOS.md"],
    },
    {
        "name": "Vendas e relatórios",
        "summary": "Importacao de CSV, relatorio persistido e configuracao operacional do modulo de vendas.",
        "files": ["server.py", "docs/README.md", "docs/API_E_DADOS.md"],
    },
    {
        "name": "Chat e I.A-Rio",
        "summary": "Chat interno, wrapper web, contexto local do repositorio e respostas com fontes.",
        "files": ["tools/riob_agent_web.py", "tools/riob_context.py", "docs/AI_CONTEXT.md"],
    },
    {
        "name": "SIP, cameras e monitoramento",
        "summary": "Bootstrap de SIP/FreePBX, cameras e monitor ESXi/operacao de infra.",
        "files": ["server.py", "docs/ARQUITETURA_SISTEMA.md", "docs/README.md"],
    },
]

TOPIC_HINTS = [
    (
        "frontend",
        [
            r"\bfrontend\b",
            r"\bui\b",
            r"\btela\b",
            r"\bhtml\b",
            r"\bcss\b",
            r"\bscript\.js\b",
            r"\brio?branco\.html\b",
            r"\bkanban\b",
            r"\bdashboard\b",
            r"\bmodal\b",
        ],
        [
            "RioBranco.html",
            "script.js",
            "style.css",
            "docs/ARQUITETURA_SISTEMA.md",
            "docs/DIAGRAMAS_E_PROCESSOS.md",
        ],
    ),
    (
        "backend",
        [
            r"\bbackend\b",
            r"\bapi\b",
            r"\brota\b",
            r"\bendpoint\b",
            r"\bflask\b",
            r"\bmaria(db)?\b",
            r"\bmysql\b",
            r"\bbanco\b",
            r"\bsql\b",
        ],
        [
            "server.py",
            "docs/API_E_DADOS.md",
            "docs/ARQUITETURA_SISTEMA.md",
        ],
    ),
    (
        "nfe",
        [
            r"\bnfe\b",
            r"\bnota fiscal\b",
            r"\bdf-?e\b",
            r"\bsefaz\b",
            r"\bdanfe\b",
            r"\bxml\b",
            r"\bocr\b",
            r"\bcertifica",
        ],
        [
            "server.py",
            "nfe_ws.py",
            "docs/NFE_RECEITA_E_INTEGRACAO.md",
            "docs/API_E_DADOS.md",
        ],
    ),
    (
        "deploy",
        [
            r"\bdeploy\b",
            r"\bsubir\b",
            r"\bupdate\b",
            r"\bredeploy\b",
            r"\bdocker\b",
            r"\bcompose\b",
            r"\bnginx\b",
            r"\bbackup\b",
            r"\brestore\b",
            r"\bcert",
        ],
        [
            "up.sh",
            "down.sh",
            "update.sh",
            "docker-compose.yml",
            "Dockerfile",
            "deploy/",
            "tools/riob_agent.py",
            "tools/riob_agent_web.py",
            "docs/OPERACAO_E_DEPLOY.md",
        ],
    ),
    (
        "agent",
        [
            r"\bagent\b",
            r"\bcontinue\b",
            r"\bollama\b",
            r"\bcodex\b",
            r"\bbrief\b",
            r"\banalis",
            r"\bplanej",
            r"\bcontext",
        ],
        [
            ".continue/config.yaml",
            ".continue/rules/riob.md",
            "docs/AI_CONTEXT.md",
            "tools/riob_agent.py",
            "tools/riob_agent_web.py",
        ],
    ),
    (
        "tests",
        [
            r"\btest",
            r"\bunittest\b",
            r"\bvalid",
            r"\bcompile",
            r"\blint\b",
        ],
        [
            "tests/",
            "requirements.txt",
        ],
    ),
]

INTENT_RULES = [
    ("debug", [r"\berr(o|or)\b", r"\bbug\b", r"\bfalha\b", r"\bquebr", r"\bnao funciona\b", r"\btraceback\b"]),
    ("ops", [r"\bdeploy\b", r"\bbackup\b", r"\bupdate\b", r"\bstatus\b", r"\bgit\b", r"\bpush\b", r"\bpull\b"]),
    ("change", [r"\badicionar\b", r"\bimplementar\b", r"\bcriar\b", r"\bnovo\b", r"\bnova\b", r"\bajustar\b"]),
    ("refactor", [r"\brefator", r"\bmelhorar\b", r"\botimiz", r"\blimpar\b", r"\bsimplific"]),
    ("docs", [r"\bdocument", r"\bmanual\b", r"\bexplic", r"\breadme\b"]),
]

SEARCHABLE_SUFFIXES = {
    ".env",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sql",
    ".sh",
    ".css",
    ".html",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
    ".cfg",
    ".conf",
    ".ps1",
}

SEARCHABLE_FILENAMES = {
    "Dockerfile",
    "Makefile",
    ".env",
    ".env.example",
}

CORE_CONTEXT_FILES = [
    ".env",
    ".env.example",
    "docker-compose.yml",
    "server.py",
    "tools/riob_agent_web.py",
    "tools/riob_agent.py",
    "docs/AI_CONTEXT.md",
    "docs/README.md",
    "docs/OPERACAO_E_DEPLOY.md",
    "RioBranco.html",
    "script.js",
]

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    "backupsSql",
    "backups sql",
    "sync-backups",
    "sync-import",
    "Relatorios",
    "RequisicoesAbastecimento",
}

MAX_SEARCHABLE_FILE_BYTES = 400_000


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9À-ÿ_.\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def classify_intent(message: str) -> str:
    text = normalize(message)
    for intent, patterns in INTENT_RULES:
        if any(re.search(pattern, text) for pattern in patterns):
            return intent
    return "general"


def repo_changed_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
    except Exception:
        return []
    files = []
    for raw_line in result.stdout.splitlines():
        if not raw_line.strip():
            continue
        path = raw_line[3:].strip() if len(raw_line) > 3 else ""
        if path:
            files.append(path)
    return files


@lru_cache(maxsize=1)
def _repo_searchable_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.name not in SEARCHABLE_FILENAMES and path.suffix.lower() not in SEARCHABLE_SUFFIXES:
            continue
        try:
            if path.stat().st_size > MAX_SEARCHABLE_FILE_BYTES:
                continue
        except Exception:
            continue
        files.append(path)
    return sorted(files, key=lambda item: str(item.relative_to(ROOT)))


def _repo_query_terms(message: str) -> list[str]:
    normalized = normalize(message)
    words = [word for word in normalized.split() if word]
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        term = normalize(term)
        if not term or term in seen:
            return
        seen.add(term)
        terms.append(term)

    for word in words:
        if len(word) >= 3 or word in {"ip", "ui", "id", "cnpj"}:
            add(word)

    lowered_words = set(words)

    if lowered_words & {"ip", "interno", "internal", "host", "url", "porta", "endereco", "endereco"}:
        for alias in (
            "RB_INTERNAL_IP",
            "RB_PUBLIC_BASE_URL",
            "RB_SERVER_NAME",
            "host.docker.internal",
            "192.168.",
        ):
            add(alias)

    if lowered_words & {"cnpj", "empresa", "razao", "social", "nome", "projeto"}:
        for alias in (
            "RB_COMPANY_CNPJ",
            "RB_COMPANY_NAME",
            "RB_PROJECT_NAME",
            "CNPJ",
            "20.984.401/0001-30",
            "RioBranco",
        ):
            add(alias)

    if lowered_words & {"ollama", "ia", "agent", "llm"}:
        for alias in (
            "RB_AGENT_LLM_PROVIDER",
            "RB_AGENT_OLLAMA_URL",
            "RB_AGENT_OLLAMA_MODEL",
            "RB_AGENT_OLLAMA_TIMEOUT",
        ):
            add(alias)

    if lowered_words & {"sip", "ramal", "wss", "webrtc"}:
        for alias in (
            "RB_SIP_FREEPBX_WS_URL",
            "RB_SIP_FREEPBX_DOMINIO",
            "RB_FREEPBX_HOST",
            "RB_FREEPBX_PJSIP_TRANSPORT",
        ):
            add(alias)

    if lowered_words & {
        "sistema",
        "sist",
        "aplicacao",
        "aplicacao",
        "aplicativo",
        "projeto",
        "plataforma",
        "arquitetura",
        "funcionamento",
        "completo",
        "tudo",
        "inteiro",
        "geral",
    }:
        for alias in (
            "docs/README.md",
            "docs/ARQUITETURA_SISTEMA.md",
            "docs/DIAGRAMAS_E_PROCESSOS.md",
            "docs/API_E_DADOS.md",
            "docs/NFE_RECEITA_E_INTEGRACAO.md",
            "docs/OPERACAO_E_DEPLOY.md",
            "docs/AI_CONTEXT.md",
            "docs/PLANO_REFATORACAO_E_PENDENCIAS.md",
            ".env",
            ".env.example",
            "docker-compose.yml",
            "Dockerfile",
            "server.py",
            "nfe_ws.py",
            "RioBranco.html",
            "script.js",
            "style.css",
            "dashboards.html",
            "up.sh",
            "down.sh",
            "update.sh",
            "riob-agent.sh",
            "riob-agent-web.sh",
            "tools/riob_agent.py",
            "tools/riob_agent_web.py",
            "tools/riob_context.py",
        ):
            add(alias)

    if lowered_words & {
        "planejamento",
        "planejar",
        "execucao",
        "execuicao",
        "contexto",
        "funcionamento",
        "fluxo",
        "arquitetura",
        "processo",
        "operacao",
        "operacao",
        "como",
        "rodar",
        "subir",
        "deploy",
        "update",
        "backup",
    }:
        for alias in (
            "docs/AI_CONTEXT.md",
            "docs/ARQUITETURA_SISTEMA.md",
            "docs/DIAGRAMAS_E_PROCESSOS.md",
            "docs/OPERACAO_E_DEPLOY.md",
            "docs/API_E_DADOS.md",
            "server.py",
            "tools/riob_context.py",
            "tools/riob_agent_web.py",
            "docker-compose.yml",
            "up.sh",
            "down.sh",
            "update.sh",
        ):
            add(alias)

    if lowered_words & {"foto", "fotos", "devolucao", "devolucoes", "anexo", "anexos", "upload", "uploads", "pasta", "diretorio", "armazen", "armazenadas"}:
        for alias in (
            "FOTOS_DIR",
            "CHAT_ATTACHMENTS_DIR",
            "VENDAS_UPLOADS_DIR",
            "REQ_ABAST_DIR",
            "DATA_ROOT",
            "app_data/FotosDevolucoes",
            "app_data/ChatAnexos",
            "app_data/RequisicoesAbastecimento",
            "app_data/nfe-cache",
            "app_data/vendas-cache/uploads",
            "backupsSql",
        ):
            add(alias)

    return terms


def _needle_matches_line(needle: str, line_lower: str) -> bool:
    term = normalize(needle)
    if not term:
        return False
    if len(term) <= 3 and term.isalpha():
        return re.search(rf"\b{re.escape(term)}\b", line_lower) is not None
    return term in line_lower


def _repo_match_snippets(path: Path, needles: list[str], max_snippets: int = 3) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    lines = text.splitlines()
    candidates: list[tuple[int, int, list[str]]] = []
    for index, line in enumerate(lines):
        lowered = line.lower()
        matched_needles = [needle for needle in needles if _needle_matches_line(needle, lowered)]
        if not matched_needles:
            continue
        score = 0
        for needle in matched_needles:
            needle_norm = normalize(needle)
            if needle_norm.startswith("rb_") or needle_norm in {"cnpj", "public_base_url", "internal_ip", "server_name"}:
                score += 4
            elif needle_norm in {"192.168.", "host.docker.internal"}:
                score += 3
            elif len(needle_norm) <= 3 and needle_norm.isalpha():
                score += 2
            else:
                score += 1
        candidates.append((score, index, matched_needles))

    candidates.sort(key=lambda item: (-item[0], item[1]))

    matched: list[dict] = []
    seen_indexes: set[int] = set()
    for _, index, _ in candidates:
        if index in seen_indexes:
            continue
        start = max(0, index - 1)
        end = min(len(lines), index + 2)
        excerpt = " | ".join(part.strip() for part in lines[start:end] if part.strip())
        excerpt = re.sub(r"\s+", " ", excerpt).strip()
        if not excerpt:
            continue
        matched.append({
            "line": index + 1,
            "text": excerpt[:240],
        })
        seen_indexes.update(range(start, end))
        if len(matched) >= max_snippets:
            break
    return matched


def build_repo_context(message: str, max_files: int = 12) -> dict:
    needles = _repo_query_terms(message)
    if not needles:
        return {
            "query": message.strip(),
            "needles": [],
            "files": [],
        }

    files: list[dict] = []
    ordered_paths: list[Path] = []
    seen_paths: set[str] = set()

    def add_relpath(rel: str) -> None:
        path = ROOT / rel
        if not path.exists() or not path.is_file():
            return
        rel_norm = str(path.relative_to(ROOT))
        if rel_norm in seen_paths:
            return
        seen_paths.add(rel_norm)
        ordered_paths.append(path)

    for rel in CORE_CONTEXT_FILES:
        add_relpath(rel)

    for rel in suggest_files(message):
        add_relpath(rel)

    for rel in repo_changed_files()[:10]:
        add_relpath(rel)

    for path in _repo_searchable_files():
        rel = str(path.relative_to(ROOT))
        if rel in seen_paths:
            continue
        ordered_paths.append(path)

    for path in ordered_paths:
        snippets = _repo_match_snippets(path, needles)
        if not snippets:
            continue
        files.append({
            "path": str(path.relative_to(ROOT)),
            "snippets": snippets,
        })
        if len(files) >= max_files:
            break

    return {
        "query": message.strip(),
        "needles": needles,
        "files": files,
    }


def format_repo_context(context: dict) -> str:
    files = context.get("files") or []
    if not files:
        return ""

    lines: list[str] = []
    lines.append("Contexto local encontrado no repositorio:")
    for item in files:
        path = str(item.get("path") or "").strip()
        snippets = item.get("snippets") or []
        if not path or not snippets:
            continue
        lines.append(f"- {path}")
        for snippet in snippets:
            line_no = snippet.get("line")
            text = str(snippet.get("text") or "").strip()
            if not text:
                continue
            prefix = f"  - L{line_no}: " if line_no else "  - "
            lines.append(f"{prefix}{text}")
    return "\n".join(lines).strip()


def format_repo_sources(context: dict, limit: int = 4) -> str:
    files = context.get("files") or []
    paths: list[str] = []
    seen: set[str] = set()
    for item in files:
        path = str(item.get("path") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
        if len(paths) >= limit:
            break
    if not paths:
        return ""
    label = "Fonte" if len(paths) == 1 else "Fontes"
    return f"{label}: " + ", ".join(paths)


def _file_summary_items(path: Path, max_items: int = 6) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    suffix = path.suffix.lower()
    name = path.name.lower()
    items: list[str] = []

    if suffix == ".py" or name == "dockerfile":
        defs = re.findall(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text, re.MULTILINE)
        classes = re.findall(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|:)", text, re.MULTILINE)
        routes = re.findall(r"@(?:app|bp)\.route\(\s*['\"]([^'\"]+)['\"]", text)
        for item in routes[:3]:
            items.append(f"route {item}")
        for item in defs[:max_items]:
            if item not in items:
                items.append(f"def {item}")
            if len(items) >= max_items:
                break
        for item in classes[:2]:
            if len(items) >= max_items:
                break
            if f"class {item}" not in items:
                items.append(f"class {item}")
        return items[:max_items]

    if suffix in {".md", ".txt"}:
        headings = re.findall(r"^#{1,3}\s+(.+)$", text, re.MULTILINE)
        bullets = re.findall(r"^-\s+(.+)$", text, re.MULTILINE)
        for item in headings[:max_items]:
            items.append(item.strip())
        if len(items) < max_items:
            for item in bullets[:max_items - len(items)]:
                items.append(item.strip())
        return items[:max_items]

    if suffix in {".js", ".html", ".css"}:
        funcs = re.findall(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text, re.MULTILINE)
        ids = re.findall(r"id=[\"']([A-Za-z_][A-Za-z0-9_\-]*)[\"']", text)
        for item in funcs[:max_items]:
            items.append(f"function {item}")
        if len(items) < max_items:
            for item in ids[:max_items - len(items)]:
                if item not in items:
                    items.append(f"id {item}")
        return items[:max_items]

    if suffix in {".sh", ".yaml", ".yml", ".json", ".ini", ".cfg", ".conf", ".sql"}:
        lines = [line.strip() for line in text.splitlines() if line.strip()][:max_items]
        return lines

    return []


@lru_cache(maxsize=1)
def build_repo_manifest(max_files: int = 40) -> dict:
    files: list[dict] = []
    ordered_paths: list[Path] = []
    seen: set[str] = set()

    def add_relpath(rel: str) -> None:
        path = ROOT / rel
        if not path.exists() or not path.is_file():
            return
        rel_norm = str(path.relative_to(ROOT))
        if rel_norm in seen:
            return
        seen.add(rel_norm)
        ordered_paths.append(path)

    for rel in CORE_CONTEXT_FILES:
        add_relpath(rel)
    for rel in DOC_ORDER:
        add_relpath(rel)
    for path in _repo_searchable_files():
        rel = str(path.relative_to(ROOT))
        if rel in seen:
            continue
        ordered_paths.append(path)

    for path in ordered_paths:
        rel = str(path.relative_to(ROOT))
        items = _file_summary_items(path)
        if not items:
            continue
        files.append({
            "path": rel,
            "items": items,
        })
        if len(files) >= max_files:
            break

    return {
        "files": files,
        "paths": [str(item["path"]) for item in files],
    }


def format_repo_manifest(manifest: dict) -> str:
    files = manifest.get("files") or []
    if not files:
        return ""
    lines: list[str] = []
    lines.append("Mapa do repositorio:")
    for item in files:
        path = str(item.get("path") or "").strip()
        entries = item.get("items") or []
        if not path or not entries:
            continue
        lines.append(f"- {path}")
        for entry in entries[:6]:
            lines.append(f"  - {entry}")
    return "\n".join(lines).strip()


def _read_simple_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return values
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _mask_env_value(key: str, value: str) -> str:
    upper = str(key or "").upper()
    text = str(value or "").strip()
    if not text:
        return ""
    if any(token in upper for token in ("PASS", "SECRET", "TOKEN", "KEY")):
        return "<masked>"
    if len(text) > 120:
        return text[:117] + "..."
    return text


def _compose_service_inventory() -> list[dict]:
    path = ROOT / "docker-compose.yml"
    if not path.exists():
        return []
    try:
        if yaml is not None:
            data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {}
            services = data.get("services") or {}
            items: list[dict] = []
            for name, cfg in services.items():
                cfg = cfg or {}
                entry = {
                    "name": str(name),
                    "image": str(cfg.get("image") or "").strip(),
                    "build": "",
                    "ports": [str(v).strip() for v in (cfg.get("ports") or []) if str(v).strip()],
                    "volumes": [str(v).strip() for v in (cfg.get("volumes") or []) if str(v).strip()],
                }
                build = cfg.get("build")
                if isinstance(build, dict):
                    parts = []
                    ctx = str(build.get("context") or "").strip()
                    df = str(build.get("dockerfile") or "").strip()
                    if ctx:
                        parts.append(f"context={ctx}")
                    if df:
                        parts.append(f"dockerfile={df}")
                    entry["build"] = ", ".join(parts)
                elif isinstance(build, str):
                    entry["build"] = build
                items.append(entry)
            return items
    except Exception:
        pass

    # Fallback heuristico se PyYAML nao estiver disponivel por algum motivo.
    items: list[dict] = []
    current = None
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if re.match(r"^  [A-Za-z0-9_-]+:\s*$", raw_line):
            name = raw_line.strip().rstrip(":")
            if name in {"services", "volumes", "networks", "configs", "secrets"}:
                current = None
                continue
            current = {"name": name, "image": "", "build": "", "ports": [], "volumes": []}
            items.append(current)
            continue
        if not current:
            continue
        m = re.match(r"^\s+image:\s*(.+)$", raw_line)
        if m:
            current["image"] = m.group(1).strip()
            continue
        m = re.match(r"^\s+dockerfile:\s*(.+)$", raw_line)
        if m:
            current["build"] = f"{current['build']}, dockerfile={m.group(1).strip()}".strip(", ")
            continue
        m = re.match(r"^\s+context:\s*(.+)$", raw_line)
        if m:
            current["build"] = f"{current['build']}, context={m.group(1).strip()}".strip(", ")
            continue
        m = re.match(r"^\s+-\s+(.+)$", raw_line)
        if m and current is not None:
            value = m.group(1).strip()
            if ":" in value and "ports" in raw_line:
                current["ports"].append(value)
            elif "/" in value or ":" in value:
                current["volumes"].append(value)
    return items


def _dir_inventory(path: Path, max_samples: int = 6) -> dict | None:
    if not path.exists() or not path.is_dir():
        return None
    files = 0
    dirs = 0
    samples: list[str] = []
    try:
        children = sorted(path.iterdir(), key=lambda p: (not p.is_file(), p.name.lower()))
    except Exception:
        children = []
    for child in children:
        if child.name.startswith("."):
            continue
        if child.is_file():
            files += 1
            if len(samples) < max_samples:
                samples.append(child.name)
        elif child.is_dir():
            dirs += 1
            if len(samples) < max_samples:
                samples.append(f"{child.name}/")
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "files": files,
        "dirs": dirs,
        "samples": samples,
    }


def build_environment_inventory() -> dict:
    env_files = [ROOT / ".env", ROOT / ".env.example"]
    merged_env: dict[str, str] = {}
    for env_path in env_files:
        merged_env.update(_read_simple_env(env_path))

    selected_keys = [
        "RB_DB_NAME",
        "RB_DB_USER",
        "RB_DB_BIND",
        "RB_DB_BACKUP_PATH",
        "RB_SERVER_NAME",
        "RB_PUBLIC_BASE_URL",
        "RB_PROJECT_NAME",
        "RB_COMPANY_NAME",
        "RB_COMPANY_CNPJ",
        "RB_INTERNAL_IP",
        "RB_ENABLE_HTTPS",
        "RB_HTTP_PORT",
        "RB_HTTPS_PORT",
        "RB_DATA_DIR",
        "RB_AGENT_LLM_PROVIDER",
        "RB_AGENT_OLLAMA_URL",
        "RB_AGENT_OLLAMA_MODEL",
        "RB_FREEPBX_HOST",
        "RB_FREEPBX_PJSIP_TRANSPORT",
        "RB_SIP_FREEPBX_WS_URL",
        "RB_SIP_FREEPBX_DOMINIO",
        "ESXI_HOST",
        "ESXI_USER",
        "RB_VSPHERE_CLIENT_PATH",
    ]

    selected_env = {
        key: _mask_env_value(key, merged_env.get(key) or os.environ.get(key, ""))
        for key in selected_keys
        if _mask_env_value(key, merged_env.get(key) or os.environ.get(key, ""))
    }

    runtime = {
        "hostname": socket.gethostname(),
        "user": getpass.getuser(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cwd": str(ROOT),
    }
    os_release = {}
    os_release_path = Path("/etc/os-release")
    if os_release_path.exists():
        for raw_line in os_release_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" not in raw_line:
                continue
            key, value = raw_line.split("=", 1)
            value = value.strip().strip('"')
            if key in {"PRETTY_NAME", "NAME", "VERSION_ID", "VERSION_CODENAME"}:
                os_release[key] = value
    if os_release:
        runtime["os_release"] = os_release

    compose_services = _compose_service_inventory()

    data_dirs = []
    for rel in (
        "backupsSql",
        "backups sql",
        "sync-backups",
        "sync-import",
        "Relatorios",
        "RequisicoesAbastecimento",
        "cameras",
        "certs",
        "sql",
        "deploy",
        "docs",
        "esxi",
    ):
        inv = _dir_inventory(ROOT / rel)
        if inv:
            data_dirs.append(inv)

    return {
        "runtime": runtime,
        "environment": selected_env,
        "compose": compose_services,
        "data_dirs": data_dirs,
    }


def format_environment_inventory(inventory: dict) -> str:
    lines: list[str] = []
    runtime = inventory.get("runtime") or {}
    environment = inventory.get("environment") or {}
    compose = inventory.get("compose") or []
    data_dirs = inventory.get("data_dirs") or []

    if runtime:
        lines.append("Ambiente de runtime:")
        for key in ("hostname", "user", "system", "release", "machine", "python", "cwd"):
            value = runtime.get(key)
            if value:
                lines.append(f"- {key}: {value}")
        os_release = runtime.get("os_release") or {}
        if os_release:
            os_desc = ", ".join(f"{k}={v}" for k, v in os_release.items() if v)
            if os_desc:
                lines.append(f"- os_release: {os_desc}")

    if environment:
        lines.append("")
        lines.append("Variaveis de ambiente relevantes:")
        for key in sorted(environment):
            lines.append(f"- {key}={environment[key]}")

    if compose:
        lines.append("")
        lines.append("Servicos do docker-compose:")
        for service in compose:
            name = service.get("name") or ""
            image = service.get("image") or ""
            build = service.get("build") or ""
            ports = service.get("ports") or []
            volumes = service.get("volumes") or []
            parts = []
            if image:
                parts.append(f"image={image}")
            if build:
                parts.append(f"build={build}")
            if ports:
                parts.append(f"ports={', '.join(ports[:4])}")
            if volumes:
                parts.append(f"volumes={', '.join(volumes[:4])}")
            if name and parts:
                lines.append(f"- {name}: " + " | ".join(parts))

    if data_dirs:
        lines.append("")
        lines.append("Diretorios operacionais presentes:")
        for item in data_dirs:
            path = item.get("path") or ""
            files = item.get("files") or 0
            dirs = item.get("dirs") or 0
            samples = item.get("samples") or []
            sample_text = f" | amostras: {', '.join(samples[:5])}" if samples else ""
            lines.append(f"- {path}: {files} arquivos, {dirs} subdiretorios{sample_text}")

    return "\n".join(lines).strip()


def build_system_overview() -> dict:
    files: list[dict] = []
    seen: set[str] = set()
    for module in SYSTEM_OVERVIEW_MODULES:
        module_files = []
        for path in module.get("files") or []:
            if path in seen:
                continue
            seen.add(path)
            module_files.append(path)
        files.append(
            {
                "name": module.get("name") or "",
                "summary": module.get("summary") or "",
                "files": module_files,
            }
        )
    return {
        "title": "Visao geral do sistema",
        "modules": files,
        "sources": sorted({path for module in files for path in module.get("files") or []}),
    }


def format_system_overview(overview: dict) -> str:
    modules = overview.get("modules") or []
    if not modules:
        return ""

    lines: list[str] = []
    lines.append("Visao geral do sistema:")
    for module in modules:
        name = str(module.get("name") or "").strip()
        summary = str(module.get("summary") or "").strip()
        files = module.get("files") or []
        if not name or not summary:
            continue
        lines.append(f"- {name}: {summary}")
        if files:
            lines.append(f"  arquivos: {', '.join(str(path) for path in files)}")
    return "\n".join(lines).strip()


def system_overview_actions() -> list[dict]:
    return [
        {"name": "module_base", "label": "Base da aplicacao", "kind": "secondary"},
        {"name": "module_ops", "label": "Operacao e deploy", "kind": "secondary"},
        {"name": "module_fretes", "label": "Fretes e kanban", "kind": "secondary"},
        {"name": "module_devolucoes", "label": "Devolucoes e anexos", "kind": "secondary"},
        {"name": "module_nfe", "label": "Estoque e NF-e", "kind": "secondary"},
        {"name": "module_vendas", "label": "Vendas e relatorios", "kind": "secondary"},
        {"name": "module_chat", "label": "Chat e I.A-Rio", "kind": "secondary"},
        {"name": "module_sip", "label": "SIP e cameras", "kind": "secondary"},
    ]


def suggest_files(message: str) -> list[str]:
    text = normalize(message)
    score: dict[str, int] = {}

    for path in DOC_ORDER:
        score[path] = score.get(path, 0) + 1

    for _, patterns, paths in TOPIC_HINTS:
        hit_count = sum(1 for pattern in patterns if re.search(pattern, text))
        if not hit_count:
            continue
        for path in paths:
            score[path] = score.get(path, 0) + (hit_count * 5)

    changed = repo_changed_files()

    ordered = sorted(score.items(), key=lambda item: (-item[1], item[0]))
    seen: set[str] = set()
    result: list[str] = []
    for path, _ in ordered:
        if path in seen:
            continue
        seen.add(path)
        result.append(path)

    for path in changed:
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
        if len(result) >= 8:
            break
    return result[:8]


def recommended_flow(intent: str) -> list[str]:
    flows = {
        "debug": [
            "Reproduzir o problema com contexto real",
            "Ler os arquivos mais provaveis",
            "Aplicar a menor correcao segura",
            "Validar com teste ou compilacao",
        ],
        "change": [
            "Confirmar o fluxo atual nos arquivos certos",
            "Fazer a menor mudanca que resolve o pedido",
            "Atualizar docs se o comportamento mudar",
            "Validar o resultado com teste ou smoke check",
        ],
        "refactor": [
            "Entender o fluxo atual e os riscos de regressao",
            "Mover ou simplificar com mudanca minima por etapa",
            "Manter contrato e comportamento existentes",
            "Validar o modulo afetado depois da alteracao",
        ],
        "docs": [
            "Ler a fonte real do comportamento",
            "Atualizar os docs que descrevem o fluxo",
            "Preservar comandos, nomes e contratos",
            "Revisar consistencia com os outros documentos",
        ],
        "ops": [
            "Checar status e risco operacional antes de agir",
            "Usar os scripts locais existentes quando possivel",
            "Evitar mudancas desnecessarias em runtime",
            "Validar o ambiente depois da operacao",
        ],
        "general": [
            "Identificar o dominio e os arquivos certos",
            "Pedir contexto adicional apenas se faltar algo critico",
            "Fazer a menor alteracao segura",
            "Validar antes de resumir",
        ],
    }
    return flows.get(intent, flows["general"])


def validation_steps(intent: str) -> list[str]:
    steps = [
        "python3 -m compileall server.py tools tests",
        "python3 -m unittest discover -s tests -v",
        "pip check",
    ]
    if intent in {"ops", "change", "refactor", "debug"}:
        steps.append("./up.sh ou ./update.sh apenas se a mudanca exigir deploy")
    return steps


def build_task_brief(message: str) -> dict:
    intent = classify_intent(message)
    return {
        "message": message.strip(),
        "intent": intent,
        "likely_files": suggest_files(message),
        "changed_files": repo_changed_files()[:10],
        "flow": recommended_flow(intent),
        "validation": validation_steps(intent),
        "doc_order": DOC_ORDER,
    }


def format_task_brief(brief: dict) -> str:
    lines: list[str] = []
    lines.append(f"Pedido classificado como: {brief.get('intent', 'general')}")
    lines.append("")
    lines.append("Arquivos mais provaveis:")
    files = brief.get("likely_files") or []
    if files:
        for path in files:
            lines.append(f"- {path}")
    else:
        lines.append("- nenhum arquivo sugerido")
    changed = brief.get("changed_files") or []
    if changed:
        lines.append("")
        lines.append("Alteracoes ja presentes no worktree:")
        for path in changed:
            lines.append(f"- {path}")
    lines.append("")
    lines.append("Fluxo recomendado:")
    for index, step in enumerate(brief.get("flow") or [], start=1):
        lines.append(f"{index}. {step}")
    lines.append("")
    lines.append("Validacao sugerida:")
    for index, step in enumerate(brief.get("validation") or [], start=1):
        lines.append(f"{index}. {step}")
    lines.append("")
    lines.append("Ordem de leitura:")
    for index, path in enumerate(brief.get("doc_order") or [], start=1):
        lines.append(f"{index}. {path}")
    return "\n".join(lines).strip()
