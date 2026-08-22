"""FastAPI 应用入口：生命周期、静态前端与路由注册。"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import get_settings
from app.db import Database
from app.observability.metrics import metrics

SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.asgi import SentryAsgiIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=os.getenv("SENTRY_ENV", "production"),
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        integrations=[SentryAsgiIntegration()],
    )

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-travel-agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Path(settings.db_dir).mkdir(parents=True, exist_ok=True)
    db = Database(settings.db_path)
    db.init_db()
    app.state.db = db
    app.state.metrics = metrics
    logger.info("星旅 Agent 启动完成: db=%s", settings.db_path)
    yield
    db.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="星旅 Agent · AI 旅行规划平台",
        version="1.0.0",
        lifespan=lifespan,
    )
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")

    frontend = Path(settings.frontend_dir)
    app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    uploads = Path(settings.db_dir) / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=uploads), name="uploads")

    @app.get("/")
    async def index():
        return FileResponse(frontend / "index.html")

    return app


app = create_app()

