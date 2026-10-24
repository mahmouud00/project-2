# Changelog

All notable changes are listed here. Versions follow Semantic Versioning (MAJOR.MINOR.PATCH).

## [Unreleased]
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
- Image upload (PNG/JPEG/WEBP, content-sniffed, 5 MB) and authenticated download.
- `tools/vendor_admin`: key generation, licence issuing/inspection, company and subscription management.
