"""Chat routes - split into focused modules for maintainability."""

from fastapi import APIRouter
from .conversations import router as conversations_router
from .runs import router as runs_router
from .titles import router as titles_router
from .ws import router as ws_router

router = APIRouter(prefix="/conversations", tags=["chat"])
# websocket and transport-specific routes must come before dynamic conversation routes
router.include_router(ws_router)
router.include_router(runs_router)
router.include_router(conversations_router)
router.include_router(titles_router)

__all__ = ["router"]
