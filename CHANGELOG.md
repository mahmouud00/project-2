# Changelog

All notable changes are listed here. Versions follow Semantic Versioning (MAJOR.MINOR.PATCH).

## [Unreleased]

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
