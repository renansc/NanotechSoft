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
- Manual freight-card union in the main RioB Kanban depends only on both active
  cards having the same assigned truck. Dates, statuses, routes, cities, loads,
  drivers, and helpers may differ; the destination status wins. Transfer all
  operational links transactionally and retain the archived source history.
  Each union must persist its before snapshots and exact transferred record IDs;
  undo unions in reverse order, restoring both cards and their operational links
  transactionally while retaining union and undo audit entries.
- Daily-sales evidence can arrive as TXT, load PDF, and outgoing NF-e XML. TXT
  keeps its seller from the source; PDF must not be imported without an operator
  selecting the responsible seller. A deterministic TXT/PDF pair may be joined
  automatically only when the active SELLOUT confirms the same date, seller,
  city, one final map, and the PDF/final map suffix; write an audit entry and
  preserve both originals. Ambiguous unions, separation, and movement between
  cards require explicit confirmation. Never merge cards assigned to different
  trucks or dates. The outgoing-XML/freight link remains the definitive RioB
  Kanban link after the sales card reaches Loading.
- Daily-sales validation has three evidence stages: TXT received, load PDF
  formed, and final SELLOUT confirmed. Import SELLOUT as CSV/XLSX and preserve
  its customer, route, map, address, city, driver, and helper fields. Match by
  map first; before a PDF exists, use order date plus seller. SELLOUT is the
  final operational confirmation, but differences in gross value or customer
  count must stay visible instead of rewriting the prior TXT/PDF evidence.
- The recurring three-file routine is exposed under `Import -> Importar
  SELLOUT`. Resolved city, route, and map values must appear on the final card.
  Suggest a registered truck from the map prefix, but never fabricate a driver
  or helper when the SELLOUT field is blank/`000-`.
- The Daily Sales workflow weekly-load report uses the HTML ISO-week label but
  its operational interval runs from Sunday through Saturday (for example,
  `2026-W33` is 2026-08-09 through 2026-08-15). It lists one row per PDF load,
  including cards already sent to freight. Prefer current
  card/freight assignments and fill missing truck, crew, city, and route from
  the active SELLOUT; never invent missing crew names.
- The customer CSV/XLSX and route-table PDF are reference imports for this
  reconciliation. They enrich missing address/city/route descriptions and do
  not replace the original uploaded documents.
- PDF signature deduplication must not silently swallow a reimport. If the prior
  PDF card is logically deleted and has no freight, reimport reactivates that
  same card, updates its synthetic order and card to the operator-selected
  seller in one transaction, and records the previous/new seller in history.
  An active duplicate returns a visible conflict identifying its card/seller;
  a PDF already linked to freight can never be reassigned by reimport.
- Sending a Daily Sales card to freight follows the same crew rule as the main
  RioB freight form: when no separate delivery person/support is selected, a
  driver marked both `is_motorista` and `is_entregador` is assigned to both
  roles and may go alone. Validation errors must name only the fields actually
  missing instead of presenting a generic city/truck/crew warning.
- A Daily Sales card creates its RioB freight in `liberado`, as a future-load
  plan, never directly in `carregando`. Do not block this transition because
  the selected truck or crew is still assigned to an active trip: their
  availability must be enforced only when the planned freight advances to the
  effective loading stage.
- In freight `Ver dados/Carga`, a linked Daily Sales PDF remains the primary
  operational source even after outgoing XMLs are attached. Preserve PDF map,
  route, cities, seller, weight, deliveries, volumes, total, bonus, and product
  quantities. XML may fill only missing fields/items. De-duplicate products by
  normalized product code (or normalized name when code is absent), never add
  PDF and XML quantities for the same product, and label each displayed item's
  source. Stock movement still requires its separate confirmation workflow.
- In the daily TXT dashboard, `TOTAL DO PEDIDO` is the gross value. Items whose
  sales table is `91 - BONIFICACAO` compose the monetary bonus as
  `quantidade * valor_unitario`; daily and seller net value is always gross
  minus that bonus. Keep gross, bonus, and net visible together and calculate
  the bonus in a per-order aggregate so joining multiple items never repeats
  the order gross value.
- Daily-sales dashboards are live projections of active card sources. A logical
  card deletion must exclude its import/seller source (and every attached source
  of a composed card) from daily summaries and detail immediately, while keeping
  the original document and audit history. Any future financial edit must update
  the canonical order/item rows and the audit log in the same transaction; never
  maintain a separate cached total that can diverge from card state.
- TXT Daily Sales persistence contains only effective sales: `status=positiva`
  and `valor_total > 0`. Parse the full source file for structural validation,
  but never insert negative/zero visits in `vendas_diario_pedidos`, never retain
  their items, and never create their Kanban cards. The daily dashboard is a
  sales dashboard, not a visit/negativation archive.
- Keep every operational screen task-focused and clean. The main menu defines
  domains and its submenus define tasks; render only the selected task. Never
  leave configuration, reports, registrations, imports, and manual operations
  stacked together merely because they share a backend module. Configuration
  belongs under Config, reports under Relatorios, registrations under Cadastros,
  purchase-document intake under Compras, and stock position/movement/product
  maintenance/traceability under Estoque.
- Stock remains canonical in individual units, but production dashboards display
  `pallets + packages/boxes + remaining units`. Capacities are: water 150x12,
  PET 600 ml 132x12, GFA 600 ml 35x24, PET 2 L 80x6, PET 200 ml 304x12,
  GFA 200 ml CX48 48x48, and GFA 200 ml CX24 60x24. Never guess the GFA
  200 ml box variant when the product registration/name does not distinguish
  CX24 from CX48; in that case retain the canonical unit display.
- The stock dashboard has exactly two production blocks: `Retornavel` (`GFA`)
  and `PET + Agua` (`PET`, `AGUA`). Each active product appears once with
  current-week sales, current stock, weekly consumption forecast, and weekly
  production suggestion. The forecast converts the greater historical monthly
  reference (same month last year versus the average of up to three complete
  prior months) to seven days; the production suggestion deducts consumption
  already observed in the week and available stock. If no historical reference
  exists, the current-week pace is the documented fallback.
- Pending-load stock commitments are not a dashboard panel. They belong to
  `Relatorios > Estoque comprometido`, with inclusive load-date, stock-group,
  and product filters. The JSON and PDF must apply the same filters; the PDF is
  opened in the browser so it can be printed.
- A composed daily-sales card must never add TXT, PDF, and XML quantities as if
  they were independent stock issues. They are alternate evidence for the same
  load. For stock-decrement suggestion prefer official outgoing XML when linked,
  otherwise detailed TXT, and use PDF only as contingency. Keep quantities by
  source visible for reconciliation; actual stock movement still requires the
  existing confirmation workflow.
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
- A change is not complete merely because it works in the local Docker
  environment. For every RioB change that can reach production, explicitly
  validate both environments: confirm the intended commit is on `origin/main`,
  confirm the Render deployment is running that revision, exercise the affected
  route through the public Render URL, and verify that the Render service is
  connected to the intended persistent database. The `/healthz` result alone is
  insufficient because it only proves that the portal process is alive.
- Code deployment and data deployment are separate operations. Never assume
  that a Git push or Render auto-deploy copies the local MySQL data: the Render
  service must point RioB to the `riobranco` schema on the single MySQL server
  configured by `NS_DB_*`. Before attributing empty screens to cache or frontend
  code, compare a read-only business-data endpoint in local Docker and Render.
  Never restore, synchronize, replace, or seed production data as part of a
  normal code deploy; require an explicit, backed-up, separately approved data
  operation.
- The integrated portal and RioB must use the same MySQL server and credentials,
  configured by `NS_DB_HOST`, `NS_DB_PORT`, `NS_DB_USER`, and
  `NS_DB_PASSWORD`. `NS_DB_NAME` selects the portal schema (`notechsoft`) and
  `RIOB_DB_NAME` selects the RioB schema (`riobranco`) on that same server.
  Never introduce a second MySQL connection or let the Render Blueprint
  overwrite the operator-provided `NS_DB_*` values with an empty private
  service.
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
- Finished production products in the `PET` and `AGUA` groups map source-specific
  codes to one stock product through `estoque_produto_codigos`. Keep NF-e input,
  SELLOUT/sales, outgoing NF-e, and manual codes as typed aliases; never assume
  that equal numeric codes from different sources mean the same product. Use
  beverage taxonomy only as the fallback, and never merge still and sparkling
  water.
- A physical opening inventory is an absolute balance, not an additive input.
  Submit it as `quantidade_atual` to the product adjustment endpoint, which
  records the auditable delta against the canonical consolidated balance.
- `Estoque > Cadastrar produtos` opens as a searchable product list. Keep its
  registration form collapsed until the operator selects `Novo Produto` or
  `Editar`; both actions expand the same form, while cancel/save returns to the
  list. Product search must cover name, canonical base, primary/source codes,
  packaging, and stock group, with an additional group filter. Do not split the
  existing combined product-registration and optional stock-adjustment flow.
- The stock dashboard has one primary row per canonical active product. It shows
  current-month sales, the same month in the previous year, the average of up to
  three prior complete months, physical stock, committed stock, available stock,
  remaining monthly demand, and production suggestion. For finished GFA, PET,
  and water products, monthly reference demand is the larger available value
  between the prior-year month and recent-month average; subtract current-month
  sales and then available stock. Select exactly one sales import per reference
  month so overlapping caches never duplicate volume. A separate printable
  committed-stock report lists only products reserved by pending loads.
- Stock has two top-level operational areas: `PRODUCAO` and
  `ALMOXARIFADO_GERAL`. Production is split into `PRODUTOS` and
  `MATERIA_PRIMA`. Formula inputs (for example sugar, concentrate, flavoring,
  acidulant, preservative, coloring and carbon dioxide) belong to raw material;
  other non-commercial supplies belong to general warehouse. Dashboard groups
  are active records in `estoque_grupos`; the defaults displayed are returnable
  drinks, PET, water, caps, and preforms, while `OUTROS` starts hidden. Only
  active, registered products from groups marked `exibir_dashboard` may appear.
  Product deletion is logical: hide the registration and its aliases immediately
  but preserve every stock movement for audit. The stock dashboard refreshes its
  uncached stock projection every five seconds; historical monthly sales may be
  held in a short in-memory cache because imported sales sources are immutable
  and a newly activated import changes the cache key.
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
