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
7. `docs/ROTAS_E_RECURSOS_COMPLEMENTARES.md`
8. `docs/PLANO_REFATORACAO_E_PENDENCIAS.md`

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
- `/srv/sensoresMonitor/monitoramento-industrial-v5.0`
  - external Flask app mounted read-only by Compose and exposed at `/monitor/automacao/`

## Useful commands

- `../../../up.sh`
  - rebuild and start the integrated portal and RioB stack without replacing data
- `../../../down.sh`
  - stop portal and RioB applications while preserving databases
- `../../../update.sh`
  - pull the current branch and redeploy applications without operating databases
- `../../../git-safe-push.sh -m "message"`
  - validate, commit, and push through the repository-safe workflow
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
- In fretes created or linked from an outgoing XML, keep the trip summary
  synchronized when the truck is attached later: inherit `veiculos.km_atual`
  when the frete has no KM, inherit `cargas.peso_total` and the load delivery
  count when the corresponding frete fields are empty, count each linked
  outgoing NF-e as at least one delivery, and propagate the truck/context to
  the XML links without overwriting larger totals entered manually.
- Outgoing NF-e cards in the Kanban must be consolidated instead of duplicated:
  reuse an active card for the same destination city; when an archived frete
  contains multiple cities, register or extend that group in `cargas_rotas`;
  later XMLs whose cities belong to that route must reuse one active route card
  even before a truck is linked. Never merge active cards assigned to different
  trucks.
- A persisted outgoing NF-e/frete link is the source of truth for Kanban
  visibility: linked notes must remain searchable and visible after reopening
  the card, including notes also marked for maintenance and legacy records whose
  `nota_key` differs from the normalized access key. Filters must resolve the
  link by `nota_key`, access key, or note number. A linked note may be moved only
  to another active, non-archived frete, keeping a single definitive link and
  recording the transfer in both fretes' history.
- The pending-XML Kanban list must stay fast as history grows. Its default
  priority is: links in the current card, then unlinked notes, then links in
  other active fretes. Do not reopen/parse every XML file while listing.
  Links belonging to archived fretes are hidden by default and loaded only by
  explicit search or the interface option that includes archived history.
- When local runtime evidence is required, the project operator has authorized
  SSH access to localhost for read-only log and service inspection. Never store
  passwords or other credentials in this repository or in documentation.
- Removing an outgoing NF-e from a frete means "leave it available without a
  link", not cancel, discard, hide, or automatically recreate its card. Persist
  this as the manual `desvinculado` state, show it in the `sem_vinculo` filter
  immediately (including legacy `cancelado` rows whose origin is
  `desvinculado_kanban`), and only link it again after an explicit user action.
- Stock status uses a canonical beverage taxonomy and must merge duplicate
  product registrations by normalized flavor, volume, and presentation. Known
  flavors/families are grape, cola, orange, lemon/soda, raspberry, pineapple,
  Astuba, Laranjinha, citrus, tubaina, guarana, recyclable, 200 ml, 600 ml,
  2 L, returnable 600 ml and 200 ml, plus still and sparkling water. Default
  packs contain 12 units; PET 2 L packs contain 6; returnable 600 ml crates
  contain 24; returnable 200 ml crates contain 48; water packs contain 12.
  Explicit product codes or spelling variations must not create duplicate rows
  in the stock-status display when this canonical identity is the same.
- When changing behavior, inspect tests and add or adjust them when practical.
- During dead-code sweeps, a missing direct reference is not enough to remove
  Flask routes, HTML callbacks, protocol handlers, library overrides or public
  integration entry points. Record newly discovered active resources in
  `docs/ROTAS_E_RECURSOS_COMPLEMENTARES.md`.
- If you need to plan a change, generate a brief first instead of guessing the files.
- Prefer `./riob-agent brief "..."` when you need a concise, file-aware analysis before editing.
- If a flow touches deploy, backup, or integrations, mention the operational impact explicitly.
- Treat `docs/AI_RESEARCH_MANUAL.md` at the repository root as the permanent
  operational source of truth.
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
