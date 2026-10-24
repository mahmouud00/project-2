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
- Licensing interface with offline signed-file and online subscription providers.
