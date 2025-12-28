from fastapi import APIRouter

from .captcha import internal_router as captcha_internal_router
from .captcha import router as captcha_router
from .health import router as health_router
from .login import router as login_router
from .logout import router as logout_router
from .posts import router as posts_router
from .rate_limits import router as rate_limits_router
from .scraper import router as scraper_router
from .tasks import router as tasks_router
from .tiers import router as tiers_router
from .users import router as users_router
from .ws import router as ws_router

router = APIRouter(prefix="/v1")
router.include_router(health_router)
router.include_router(login_router)
router.include_router(logout_router)
router.include_router(users_router)
router.include_router(posts_router)
router.include_router(tasks_router)
router.include_router(tiers_router)
router.include_router(rate_limits_router)
router.include_router(scraper_router)
router.include_router(captcha_router)

# WebSocket routes (outside /v1 prefix for cleaner URLs)
# Internal routes (no /v1 prefix)
# These are exported separately to be mounted at root level
