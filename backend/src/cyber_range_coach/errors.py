from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, error: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "code": error.code,
                "message": error.message,
                "details": error.details,
                "trace_id": uuid4().hex,
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, error: Exception) -> JSONResponse:
        trace_id = uuid4().hex
        logger.exception(
            "Unhandled request error trace_id=%s method=%s path=%s",
            trace_id,
            request.method,
            request.url.path,
            exc_info=error,
        )
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "Внутренняя ошибка. Подробности записаны в локальный журнал.",
                "details": {},
                "trace_id": trace_id,
            },
        )
