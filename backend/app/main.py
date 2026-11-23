from __future__ import annotations

import uuid
import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse

from app.api.routes.auth import register_oauth, router as auth_router
from app.api.routes.local_auth import router as local_auth_router
from app.api.routes.admin import router as admin_router
from app.api.routes.archive import router as archive_router
from app.auth.database import migrate
from app.auth.oidc import OIDCFlowSessionMiddleware
from app.core.config import Settings
from app.core.engine_config import EngineSettings
from app.engine.supervisor import DigUpAdapter
from app.settings.routes import router as settings_router
from app.settings.service import SettingsService


class CallbackQueryRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            request_path = args[2]
            if isinstance(request_path, str) and request_path.startswith("/auth/microsoft/callback"):
                record.args = (*args[:2], "/auth/microsoft/callback", *args[3:])
        return True


def create_app(
    settings: Settings | None = None,
    db_path: str | None = None,
    *,
    engine_settings: EngineSettings | None = None,
    digup: DigUpAdapter | None = None,
    settings_path: str | None = None,
    settings_service: SettingsService | None = None,
) -> FastAPI:
    config = settings or Settings.from_env()
    base_engine = engine_settings or EngineSettings.from_env()
    configured_settings_path = settings_path or os.getenv("IIHS_SETTINGS_PATH")
    if configured_settings_path is None and db_path is not None:
        configured_settings_path = str(Path(db_path).with_name("settings.json"))
    archive_settings = settings_service or SettingsService(
        base_engine,
        path=Path(configured_settings_path) if configured_settings_path else None,
    )
    archive_engine = digup or DigUpAdapter(archive_settings.engine_settings())
    if digup is not None:
        archive_engine.settings = archive_settings.engine_settings()
        archive_engine.search_process.settings = archive_engine.settings
        archive_engine.index_job.settings = archive_engine.settings

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        migrate(db_path)
        try:
            yield
        finally:
            await archive_engine.close()

    application = FastAPI(title="IIHS Media Archive API", lifespan=lifespan)
    logging.getLogger("uvicorn.access").addFilter(CallbackQueryRedactionFilter())
    application.state.settings = config
    application.state.db_path = db_path
    application.state.oauth = None
    application.state.digup = archive_engine
    application.state.settings_service = archive_settings
    register_oauth(application, config)
    application.include_router(auth_router)
    application.include_router(local_auth_router)
    application.include_router(admin_router)
    application.include_router(archive_router)
    application.include_router(settings_router)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/auth/local/") or request.url.path.startswith("/api/admin/users"):
            return JSONResponse({"detail": "Invalid request"}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    @application.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        try:
            return await call_next(request)
        except Exception:
            return JSONResponse({"detail": "Internal server error"}, status_code=500)

    application.add_middleware(OIDCFlowSessionMiddleware, settings=config, db_path=db_path)
    return application


app = create_app()
