"""CAPTCHA Resolver Services.

This module provides services for the Manual CAPTCHA Resolver system:
- CaptchaProxyService: Proxied iframe rendering with cookie capture
- CaptchaPubSubService: Redis pub/sub for real-time notifications
- CaptchaSessionService: Session caching and retrieval
- Worker Integration: Helper functions for Titan Worker
"""

from .proxy_engine import CaptchaProxyService
from .pubsub import CaptchaPubSubService, get_pubsub_service
from .session_service import CaptchaSession, CaptchaSessionService, get_session_service
from .worker_integration import (
    check_cached_session,
    create_captcha_task,
    create_task_and_wait,
    execute_with_captcha_handling,
    inject_session_cookies,
    poll_for_session,
    wait_for_solution,
)

__all__ = [
    # Services
    "CaptchaProxyService",
    "CaptchaPubSubService",
    "CaptchaSessionService",
    "CaptchaSession",
    # Service factories
    "get_pubsub_service",
    "get_session_service",
    # Worker integration
    "check_cached_session",
    "create_captcha_task",
    "create_task_and_wait",
    "execute_with_captcha_handling",
    "inject_session_cookies",
    "poll_for_session",
    "wait_for_solution",
]
