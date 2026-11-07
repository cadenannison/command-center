"""Error bodies and the handlers that keep request content (credentials) out of them."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from command_center.services.errors import UnknownSourceError


class ErrorBody(BaseModel):
    """A plain error."""

    detail: str


class ValidationIssue(BaseModel):
    """One request field that failed validation; never echoes the submitted value."""

    loc: list[str | int]
    msg: str
    type: str


class ValidationErrorBody(BaseModel):
    """Body of a 422 for a malformed request."""

    detail: list[ValidationIssue]


NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorBody}}
INVALID_REQUEST: dict[int | str, dict[str, Any]] = {422: {"model": ValidationErrorBody}}


def install_error_handlers(app: FastAPI) -> None:
    """Register the handlers. FastAPI's default 422 echoes `input`, which can be a credential."""

    @app.exception_handler(UnknownSourceError)
    async def _unknown_source(_request: Request, exc: UnknownSourceError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return JSONResponse(status_code=404, content=ErrorBody(detail=str(exc)).model_dump())

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(_request: Request, exc: RequestValidationError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        issues = [
            ValidationIssue(loc=list(error["loc"]), msg=error["msg"], type=error["type"])
            for error in exc.errors()
        ]
        body = ValidationErrorBody(detail=issues)
        return JSONResponse(status_code=422, content=body.model_dump())
