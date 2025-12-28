from fastapi import APIRouter

from .v1 import captcha_internal_router, ws_router
from .v1 import router as v1_router

# Main API router with /api prefix
router = APIRouter(prefix="/api")
router.include_router(v1_router)

# Root-level routers (no /api prefix)
# These are exported separately to be mounted in main.py
# - ws_router: WebSocket endpoints (/ws/captcha)
# - captcha_internal_router: Internal endpoints (/internal/solver-frame/{id})
