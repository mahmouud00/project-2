# Changelog

All notable changes are listed here. Versions follow Semantic Versioning (MAJOR.MINOR.PATCH).

## [Unreleased]
### Added
- Half-circle arch (أرج) above a unit: when the total height is above the opening height, the arch is a separate fixed unit with its own frame, calculated with its library model (per unit or the company's `default_arch_model_id`) at width × (total − height). Its cost is part of the unit, it is a linked quotation line (`parent_line_id`, price inside the unit) and a work order item of its own (migration 0007).
- Formula language: geometry functions in exact decimals (`pi`, `sqrt`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `rad`, `deg`, `arc_length`, `segment_area`, `arc_radius`, `arc_angle`); glass panes can give their real area (`area_expr`) for shaped glass. Demo library: example arch model `AR1`.
- Survey sheet like the factory's paper form (migration 0005): survey `kind` (windows/doors or shutters), floor, technician; per unit: total height, sliding/hinged, colour as written, single/double glass and its colour, insect screen type, application; shutters: installation method and motor type. Edited as a table in the desktop app and printed in the same layout (`GET /surveys/{id}/print`, landscape).
- Suggested price per m² of a survey (`GET /surveys/{id}/pricing`): average of the survey from the real cost of each unit at its sizes and the price list; shown next to every survey on the customer page.
- Price per m² typed per quotation line (`price_per_m2`) or for all lines (`POST /quotations/{id}/price-per-m2`); each unit bills at least `min_billed_area_m2` (company setting, default 1 m²); the area is width × total height when the survey gives a total height (migration 0006 carries it to quotation lines), else width × height. Quotation screen and print columns: model number, width, height, qty, opening area, total area, model type and drawing, price per m², cost.
- Licence activation from the login screen (offline): public `GET/POST /system/activation` shows why the licence is not usable and the server fingerprint, and installs a signed licence while none is active (an active one is only replaced after login).
- Desktop program (`desktop/`, Tauri + React + TypeScript): Arabic RTL, light / dark / follow Windows, the company's logo and name on every page, LAN server discovery or manual address, every screen of the system (sales, production, inventory, purchasing, treasury, invoices with printing, library editor with element width/height pieces, reference tests and publishing, users and roles per branch, company branding, licence, backups, devices, audit and PII logs, price lists). Sizes in cm, width first, exact decimal conversion.
- Windows release build (`.github/workflows/windows-release.yml`): desktop installer (NSIS, offline WebView2), server installer (server compiled to native code with Nuitka, bundled PostgreSQL 16 as a local-only service, WinSW service, firewall rules, generated secrets, smoke-tested on the build machine), and the MYTech Licence Tool (compiled GUI: issue/verify licences, sign library packages and server updates, key management). Published as a GitHub pre-release.
- Server CLI: `version`, `fingerprint`, `backup`, `restore`, `update`; `init-db` and `create-company` read secrets from the environment (never the command line).
- `GET /purchase-orders/{id}`.
- Company branding: display name, phones, e-mail, website, address, tax number, commercial register, invoice footer, accent colour and logo (`POST/GET /company/logo`); public `GET /system/branding` for the login screen.
- Customer invoices (`/invoices`): created from a work order, a quotation or manual lines; model, image, drawing, sizes, colour, glass, price and discounts per line; invoice discount and tax; gap-free number on issue; cancel with a reason; cash receipts linked to invoices (migration 0004).
- Printable A4 documents (self-contained HTML, company logo and details on every page, sizes in cm, width first): invoice, quotation, cut list.
- Model pieces carry `element` (e.g. حلق، ضلفة، باكتة) and `side` (`width`/`height`) so each element's width and height deductions are shown together; passed through calculation results and cut lists.
- Company setting `length_unit` (default `cm`): the desktop app shows and accepts lengths in cm (the API stays in mm).
- UI mockups updated with the MYTech logo and colours, cm everywhere, width always before height.
- Trial environment: `docker compose up --build` (PostgreSQL + API + demo data: MYTech and DEMO accounts, an example library system clearly marked as not real, price lists, stock, customer, survey and quotation); `python -m app.cli demo` / `serve`; guide `docs/TRY.md`.
- "Authorize" button on `/api/docs` (OAuth2 password form, `POST /auth/token`, client_id = company code).

### Changed
- `GET /surveys` returns each survey's openings (the list showed 0 units).
- Server installer: stops the MYTech and PostgreSQL services before replacing files (upgrade over a running install failed with "Access is denied").
- Licence files saved with a UTF-8 BOM (e.g. by Notepad) are accepted.
- Windows: the server exe is a console program (setup scripts wait for it); stopping the service also stops the server process (job object); the server installer turns off Inno RedirectionGuard (error 448).
- The vendor public key is a compiled-in constant (`app/licensing/vendor_key.py`) instead of a `.pem` file next to the program; a real key pair replaced the development key; private keys are stored encrypted.
- Windows machine fingerprint uses registry values only (no subprocess), so it is identical for the installer and the service and never depends on a timeout. Licences for the old formula must be reissued (none were issued).
- Customer statement bills issued invoices (with their services and discounts) instead of the work order amount.
- Survey opening sizes use `Decimal` instead of `float`.
- CORS allows the desktop program's origins by default.
- Compiled server layout: `app\<version>\mytech-server.exe`; the service launcher and the updater run the version in `current.json`.

## [0.1.0] - 2026-10-24
### Added
- Backend skeleton: FastAPI app, settings (`.env`), uniform error format, PII-redacting logging.
- PostgreSQL with three roles (app / system / owner), Alembic migrations, Row-Level Security on every tenant table.
- Companies, branches, roles (per-branch), users, devices, audit log, PII access log.
- JWT login with rotating refresh tokens (reuse detection), account lockout, change password.
- Optimistic locking (`version`) with `409 VERSION_CONFLICT`.
- Client/server version headers; `426 CLIENT_UPDATE_REQUIRED` for outdated devices.
- Licensing interface with offline signed-file (Ed25519, machine-bound, grace then read-only) and online subscription providers; device/user/branch limits; module gates; licence upload endpoint.
- Formula engine: own tokenizer/parser (no eval), Decimal arithmetic, whitelisted functions (min/max/round/ceil/floor/round_to/lookup/if...), dependency ordering with cycle detection, unit (mm/cm) handling, opening vs manufacturing size, calibration and overrides, generic sanity checks, drawing data.
- Golden test harness (`tests/golden`), any difference > 0.1 mm fails.
- Catalogue library authored inside the system: profile systems (UPVC / shutter / aluminium, mm or cm formulas, rounding, approved/trial), named constants, materials with colour variants (SKU per colour), product models with image and a full definition (parameters, formulas, cut pieces per material with their deduction formula, quantity and angles, glass, accessories, validations, drawing), vendor reference test cases.
- Publishing creates an immutable, hashed version of a system; publishing is refused if a definition is invalid or a reference test drifts > 0.1 mm. Calculations (`POST /engine/calculate`) use the published version and return the version id.
- Company calibration deltas and constant overrides, company material settings (price, internal code, hidden) kept outside library rows.
- Companies can create their own private systems; library rows are read-only for customers; library visibility follows licensed material types.
- Library update packages: vendor export (`POST /library/packages/export`), offline signing (`vendor_admin sign-package`), customer preview with a full change list (`/library/packages/preview`) and apply (`/library/packages/{id}/apply`); signature and file-hash verification, same ids at every customer, published versions never rewritten, removed items deactivated (never deleted), company calibration untouched. Online: only MYTech updates the shared library.
- Image upload (PNG/JPEG/WEBP, content-sniffed, 5 MB) and authenticated download.
- Company settings (tax, deposit %, quote validity/waste, saw kerf, bar trims, reusable offcut).
- Customers (PII-tagged, access logged), site surveys with measured openings (site size kept apart from manufacturing size).
- Price lists (end customer / dealer / contractor) with margin, labour per m², minimum price and per-model/system overrides (margin or price per m²); material cost resolution (company price → colour price → library reference).
- Quotations generated from a survey or lines: every line calculated with the published formulas (version stored), cost breakdown, totals, discount, tax, status workflow, explicit recalculation.
- Work orders from accepted quotations with frozen items, stage workflow (survey → quotation → approved/deposit → manufacturing → assembly → quality → delivered, or cancelled) and stage log; deposit check.
- Manufacturing outputs: cut list per SKU (length, count, angles, item references), bar optimisation (best-fit decreasing + improvement, kerf, trims, reusable offcuts, waste %), glass list, accessories, actual material cost, drawing data per item with model image; frozen once manufacturing starts.
- Inventory: warehouses per branch, immutable movement ledger with locked balances and average cost, adjustments, transfers, automatic issue of a work order's materials (all-or-nothing, no negative stock).
- Purchasing: suppliers, purchase orders, partial receiving into stock, last purchase price becomes the company cost.
- Treasury: cashboxes per branch, receipts/payments linked to work orders and purchase orders, reversals instead of edits, customer and supplier statements.
- Personal data (Law 151/2020): export of everything held about a customer/user/supplier, erasure by anonymisation (financial records kept), access-log query; log redaction fix for bearer tokens.
- Daily automatic backup (pg_dump, checksum sidecar, retention, single-runner lock), manual backup endpoint, verified restore that rebuilds the schema and re-grants roles.
- Live change events over WebSocket (`/api/v1/system/events`) fed by PostgreSQL NOTIFY from every audited change; no personal data in events.
- LAN discovery: UDP broadcast responder + mDNS service `_mytech._tcp`; client `discover()` helper.
- Safe updates: signed update files (`*.mtu`) with per-version install folders, mandatory pre-update backup, migrations with the new code, health check, automatic rollback (database restore + previous version) on any failure; `tools/release/build_update.py`.
- Windows deployment: launcher, WinSW service definition (auto start, restart on failure), install and update PowerShell scripts, firewall rules.
- Migration safety test (seed at old revisions, upgrade, compare data); CI workflow and pre-commit hook running the full test suite.
- Documentation: API.md, LIBRARY.md (authoring guide), INSTALL.md, UPDATE.md, ONLINE.md.
- `tools/vendor_admin`: key generation, licence issuing/inspection, company and subscription management.
