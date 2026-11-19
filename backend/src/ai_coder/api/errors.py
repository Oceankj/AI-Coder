"""Uniform error responses for the HTTP API.

docs/interfaces.md requires every error body to look like:

    {"error": {"code": "NOT_FOUND", "message": "Workspace, run or file not found."}}

FastAPI's own errors use a different shape ({"detail": ...}) and return 422
for validation failures, so this module replaces those handlers. Route code
raises `ApiError` (or one of the helpers below) and never builds error bodies
by hand.

Error codes in use (they match the frontend's MSW handlers):

    INVALID_INPUT       400  malformed or invalid request body / parameters
    INVALID_CURSOR      400  events `after` is not a nonnegative integer
    INVALID_PATH        400  file path is not a valid project-relative path
    NOT_FOUND           404  workspace, run, file, or route does not exist
    METHOD_NOT_ALLOWED  405  route exists but not for this HTTP method
    NOT_READY           409  download requested before the run completed
    FILE_TOO_LARGE      413  file preview larger than 2 MiB
    UNSUPPORTED_FILE    415  file is not UTF-8 text
    INTERNAL_ERROR      500  unexpected server error (details are logged only)
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

NOT_FOUND_MESSAGE = "Workspace, run, or file not found."


class ApiError(Exception):
    """An error that maps directly to an HTTP status and error code."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def not_found() -> ApiError:
    # One message for every missing resource, so callers cannot probe which
    # workspace or run IDs exist in other scopes.
    return ApiError(404, "NOT_FOUND", NOT_FOUND_MESSAGE)


def invalid_input(message: str) -> ApiError:
    return ApiError(400, "INVALID_INPUT", message)


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message}}
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers so every error leaves the API in the documented shape."""

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI would answer 422; the contract says invalid input is 400.
        return error_response(400, "INVALID_INPUT", _describe_validation(exc))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Raised by the router for unknown paths (404) and wrong methods (405).
        if exc.status_code == 404:
            return error_response(404, "NOT_FOUND", NOT_FOUND_MESSAGE)
        if exc.status_code == 405:
            return error_response(405, "METHOD_NOT_ALLOWED", "Method not allowed.")
        return error_response(exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Log the real cause for developers; never send it to the browser.
        logger.exception("Unhandled error", exc_info=exc)
        return error_response(500, "INTERNAL_ERROR", "Internal server error.")


def _describe_validation(exc: RequestValidationError) -> str:
    first = exc.errors()[0] if exc.errors() else None
    if not first:
        return "Invalid request."
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    return f"Invalid {location}: {first.get('msg', 'invalid value')}."
