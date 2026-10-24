"""Uniform API errors: {"error": {"code", "message", "details"}}.

Codes are stable identifiers; the frontend translates them.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str = "", *, code: str | None = None, details: Any = None,
                 status_code: int | None = None):
        super().__init__(message or self.code)
        self.message = message or self.code
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"


class Unauthorized(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class Forbidden(AppError):
    status_code = 403
    code = "FORBIDDEN"


class Conflict(AppError):
    status_code = 409
    code = "CONFLICT"


class VersionConflict(Conflict):
    code = "VERSION_CONFLICT"


class LicenseError(AppError):
    status_code = 402
    code = "LICENSE_REQUIRED"


class ValidationFailed(AppError):
    status_code = 422
    code = "VALIDATION_FAILED"


def _body(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(StaleDataError)
    async def _stale(_: Request, exc: StaleDataError):
        return JSONResponse(_body("VERSION_CONFLICT", "Record was modified by someone else"), status_code=409)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(_body("VALIDATION_FAILED", "Invalid request", details), status_code=422)
