from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, text

from .api.files import router as files_router
from .api.preferences import router as preferences_router
from .api.projects import router as projects_router
from .api.projects_core import router as projects_core_router
from .api.redaction_list import router as redaction_list_router
from .api.share import router as share_router
from .api.skills import router as skills_router
from .api.staged_files import router as staged_files_router
from .api.tasks import router as tasks_router
from .auth.routes import router as auth_router
from .chat import router as chat_router
from .config.database import AsyncSessionLocal
from .config.settings import settings
from .database.models import Skill
from .logging import configure_logging, log_event
from .middleware import RequestLoggingMiddleware, register_exception_handlers

configure_logging("api")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager.

    LAT-006: Startup no longer mutates schema or seeds data.  It only
    verifies database connectivity and that built-in skills have been
    seeded by a prior deployment step (recreate_db.py / seed_skills.py).
    This makes cold-start faster, prevents scale-out stampedes, and
    keeps app boot deterministic.
    """
    log_event(logger, "INFO", "app.startup.begin", "final", app="assistant-backend")

    try:
        # Verify database connectivity (read-only).
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        log_event(logger, "INFO", "app.startup.database_ready", "final")

        # Verify built-in skills are seeded (read-only).
        async with AsyncSessionLocal() as db:
            skill_count = await db.scalar(
                select(func.count()).select_from(Skill).where(Skill.owner_user_id.is_(None))
            )
            if skill_count and int(skill_count) > 0:
                log_event(
                    logger,
                    "INFO",
                    "app.startup.skills_verified",
                    "final",
                    builtin_skills=int(skill_count),
                )
            else:
                log_event(
                    logger,
                    "ERROR",
                    "app.startup.skills_missing",
                    "error",
                    message="No built-in skills found. Run: cd backend && PYTHONPATH=. python scripts/database/seed_skills.py",
                )
                raise RuntimeError(
                    "Built-in skills not seeded. Run seed_skills.py before starting the app."
                )

    except RuntimeError:
        raise
    except Exception:
        log_event(
            logger,
            "ERROR",
            "app.startup.database_failed",
            "error",
            exc_info=True,
        )
        raise

    try:
        from .services.redis_pubsub import get_async_redis

        redis_client = await get_async_redis()
        await redis_client.ping()
        log_event(logger, "INFO", "app.startup.redis_ready", "final")

        from .chat.services.run_supervisor import start_run_supervisor

        await start_run_supervisor()
        log_event(logger, "INFO", "app.startup.run_supervisor_ready", "final")
    except Exception:
        log_event(
            logger,
            "WARNING",
            "app.startup.redis_check_failed",
            "retry",
            message="Redis connectivity check failed; chat streaming may be degraded",
            exc_info=True,
        )

    log_event(logger, "INFO", "app.startup.completed", "final")
    yield

    from .services.chat_streams import get_all_local_streams, shutdown_user_listener
    from .chat.services.run_supervisor import stop_run_supervisor

    active_streams = get_all_local_streams()
    if active_streams:
        log_event(
            logger,
            "INFO",
            "app.shutdown.cancel_active_streams",
            "timing",
            stream_count=len(active_streams),
        )
        for stream in active_streams.values():
            stream.task.cancel()
        await asyncio.gather(*[stream.task for stream in active_streams.values()], return_exceptions=True)
        log_event(logger, "INFO", "app.shutdown.streams_cancelled", "timing")

    await stop_run_supervisor()
    await shutdown_user_listener()

    from .services.redis_pubsub import close_async_redis

    await close_async_redis()
    log_event(logger, "INFO", "app.shutdown.completed", "final")


app = FastAPI(title="assistant", version="2.0", lifespan=lifespan)

# Request logging middleware should run before router dispatch.
app.add_middleware(RequestLoggingMiddleware, slow_ms=settings.log_request_slow_ms)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=86400,
)

register_exception_handlers(app)


@app.get("/")
async def root():
    return {"message": "assistant", "version": "2.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


# Include routers
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(files_router)
app.include_router(staged_files_router)
app.include_router(preferences_router)
app.include_router(projects_core_router)
app.include_router(projects_router)
app.include_router(share_router)
app.include_router(tasks_router)
app.include_router(redaction_list_router)
app.include_router(skills_router)
