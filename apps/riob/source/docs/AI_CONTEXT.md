# AI Context for RioBranco

This file is a compact context pack for agents and maintainers.

## What this repository is

RioBranco is a monolithic internal web app with:

- a single Flask backend in `server.py`
- a single-page frontend in `RioBranco.html`, `script.js`, and `style.css`
- MariaDB as the primary database
- Docker Compose and Nginx for runtime and proxying
- operational modules for fretes, estoque, NF-e, frota, vendas, chat, SIP, cameras, backups, ESXi monitoring, and industrial automation monitoring

## Read order

If you need context fast, read these files first:

1. `docs/README.md`
2. `docs/ARQUITETURA_SISTEMA.md`
3. `docs/DIAGRAMAS_E_PROCESSOS.md`
4. `docs/OPERACAO_E_DEPLOY.md`
5. `docs/NFE_RECEITA_E_INTEGRACAO.md`
6. `docs/API_E_DADOS.md`
7. `docs/PLANO_REFATORACAO_E_PENDENCIAS.md`

## Main files

- `server.py`
  - backend routes, schema bootstrap, business rules, PDF generation, integrations, and operational helpers
- `script.js`
  - frontend logic, menus, requests, modals, dashboards, and UI flows
- `style.css`
  - global styles for the app UI
- `RioBranco.html`
  - the main frontend shell
- `dashboards.html`
  - TV or kiosk view for operational dashboards
- `tools/riob_agent.py`
  - command-line operational helper for backup, deploy, status, and Git
- `tools/riob_agent_web.py`
  - browser-based wrapper for the operational helper
- `tools/riob_context.py`
  - repo-aware brief generator used to analyze a request before editing
- `apps/automacao/source`
  - bundled Flask app mounted read-only by Compose and exposed at `/monitor/automacao/`

## Useful commands

- `./up.sh`
  - rebuild and start `app` and `proxy`
- `./down.sh`
  - stop `app` and `proxy`
- `./update.sh`
  - pull latest code from the current branch and redeploy `app` and `proxy`
- `python3 -m unittest discover -s tests -v`
  - run the Python test suite
- `python3 -m compileall server.py tools tests`
  - quick syntax check for Python files
- `pip check`
  - verify installed Python dependencies
- `./riob-agent brief "corrigir o fluxo da NF-e"`
  - generate a compact brief with likely files, workflow, and validation steps
- `./riob-agent validate`
  - run the quick baseline checks: compileall, unittest, and pip check

## Assistant rules of thumb

- Do not guess APIs, routes, or table names when the repository can confirm them.
- Prefer the smallest useful patch over broad refactors.
- Preserve the current style in the large legacy files.
- When changing behavior, inspect tests and add or adjust them when practical.
- If you need to plan a change, generate a brief first instead of guessing the files.
- Prefer `./riob-agent brief "..."` when you need a concise, file-aware analysis before editing.
- If a flow touches deploy, backup, or integrations, mention the operational impact explicitly.
- If the context is incomplete, say what is missing instead of inventing details.

## High-signal areas

- NF-e and Receita logic is described in `docs/NFE_RECEITA_E_INTEGRACAO.md`
- API payloads and data rules are in `docs/API_E_DADOS.md`
- Deploy and recovery procedures are in `docs/OPERACAO_E_DEPLOY.md`
- Known technical debt and refactor priorities are in `docs/PLANO_REFATORACAO_E_PENDENCIAS.md`

## Local convention

- Keep filenames, routes, and status names consistent with the existing project vocabulary.
- Use ASCII-only edits unless the file already uses accented text.
- Favor explicit references to files and line-level behavior in explanations.
