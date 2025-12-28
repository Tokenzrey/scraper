"""Titan Metrics and Structured Logging Module.

Provides:
- Structured JSON logging for scraper operations
- Metrics collection for monitoring (Prometheus-compatible)
- Operation timing and tracking
- Error categorization and tracking

Usage:
    from .metrics import TitanMetrics, log_scrape_operation

    # Log a scrape operation
    log_scrape_operation(
        url="https://example.com",
        tier_used=1,
        success=True,
        execution_time_ms=150.0,
        error_type=None,
    )

    # Get metrics summary
    metrics = TitanMetrics.get_summary()
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from threading import Lock
from typing import Any

logger = logging.getLogger("titan.metrics")


class MetricType(str, Enum):
    """Types of metrics we track."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMING = "timing"


@dataclass
class OperationLog:
    """Structured log entry for a scrape operation."""

    timestamp: str
    operation_id: str
    url: str
    domain: str
    tier_used: int
    tier_name: str
    success: bool
    status: str  # success, blocked, failed, timeout, captcha_required
    execution_time_ms: float
    response_size_bytes: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    challenge_detected: str | None = None
    escalation_path: list[str] | None = None
    fallback_used: bool = False
    cached_session_used: bool = False

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.__dict__, default=str)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return self.__dict__.copy()


class TitanMetrics:
    """Thread-safe metrics collector for Titan scraper.

    Tracks:
    - Requests per tier
    - Success/failure rates
    - Execution times (histogram)
    - Error types distribution
    - Escalation frequency
    - CAPTCHA encounters
    """

    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Initialize metrics storage."""
        self._lock = Lock()
        self._start_time = datetime.now(UTC)

        # Counters
        self.requests_total = 0
        self.requests_by_tier = defaultdict(int)  # tier_level -> count
        self.success_total = 0
        self.failure_total = 0
        self.errors_by_type = defaultdict(int)  # error_type -> count
        self.challenges_by_type = defaultdict(int)  # challenge_type -> count
        self.escalations_total = 0
        self.captcha_required_total = 0
        self.cached_sessions_used = 0

        # Timing (for percentiles)
        self.execution_times: list[float] = []
        self.execution_times_by_tier: dict[int, list[float]] = defaultdict(list)

        # Domain tracking
        self.requests_by_domain = defaultdict(int)
        self.failures_by_domain = defaultdict(int)

    def record_operation(self, log: OperationLog) -> None:
        """Record a completed scrape operation."""
        with self._lock:
            self.requests_total += 1
            self.requests_by_tier[log.tier_used] += 1
            self.requests_by_domain[log.domain] += 1

            if log.success:
                self.success_total += 1
            else:
                self.failure_total += 1
                self.failures_by_domain[log.domain] += 1

                if log.error_type:
                    self.errors_by_type[log.error_type] += 1

            if log.challenge_detected:
                self.challenges_by_type[log.challenge_detected] += 1

            if log.status == "captcha_required":
                self.captcha_required_total += 1

            if log.escalation_path and len(log.escalation_path) > 1:
                self.escalations_total += 1

            if log.cached_session_used:
                self.cached_sessions_used += 1

            # Record timing
            self.execution_times.append(log.execution_time_ms)
            self.execution_times_by_tier[log.tier_used].append(log.execution_time_ms)

            # Keep only last 10000 timing samples to prevent memory growth
            if len(self.execution_times) > 10000:
                self.execution_times = self.execution_times[-10000:]
            for tier in self.execution_times_by_tier:
                if len(self.execution_times_by_tier[tier]) > 5000:
                    self.execution_times_by_tier[tier] = self.execution_times_by_tier[tier][-5000:]

    def get_summary(self) -> dict[str, Any]:
        """Get metrics summary."""
        with self._lock:
            success_rate = (self.success_total / self.requests_total * 100) if self.requests_total > 0 else 0

            return {
                "uptime_seconds": (datetime.now(UTC) - self._start_time).total_seconds(),
                "requests": {
                    "total": self.requests_total,
                    "success": self.success_total,
                    "failure": self.failure_total,
                    "success_rate_pct": round(success_rate, 2),
                    "by_tier": dict(self.requests_by_tier),
                },
                "errors": {
                    "by_type": dict(self.errors_by_type),
                    "escalations": self.escalations_total,
                    "captcha_required": self.captcha_required_total,
                },
                "challenges": dict(self.challenges_by_type),
                "timing": self._calculate_timing_stats(),
                "cache": {
                    "sessions_used": self.cached_sessions_used,
                },
                "top_failure_domains": self._get_top_failures(10),
            }

    def _calculate_timing_stats(self) -> dict[str, Any]:
        """Calculate timing statistics."""
        if not self.execution_times:
            return {"samples": 0}

        sorted_times = sorted(self.execution_times)
        count = len(sorted_times)

        return {
            "samples": count,
            "min_ms": round(sorted_times[0], 2),
            "max_ms": round(sorted_times[-1], 2),
            "mean_ms": round(sum(sorted_times) / count, 2),
            "p50_ms": round(sorted_times[count // 2], 2),
            "p90_ms": round(sorted_times[int(count * 0.9)], 2),
            "p99_ms": (round(sorted_times[int(count * 0.99)], 2) if count >= 100 else None),
        }

    def _get_top_failures(self, n: int) -> list[dict[str, Any]]:
        """Get top N domains with most failures."""
        sorted_domains = sorted(self.failures_by_domain.items(), key=lambda x: x[1], reverse=True)[:n]

        return [{"domain": domain, "failures": count} for domain, count in sorted_domains]

    def to_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []

        # Counters
        lines.append(f"titan_requests_total {self.requests_total}")
        lines.append(f"titan_success_total {self.success_total}")
        lines.append(f"titan_failure_total {self.failure_total}")
        lines.append(f"titan_escalations_total {self.escalations_total}")
        lines.append(f"titan_captcha_required_total {self.captcha_required_total}")

        # Per-tier counters
        for tier, count in self.requests_by_tier.items():
            lines.append(f'titan_requests_by_tier{{tier="{tier}"}} {count}')

        # Error types
        for error_type, count in self.errors_by_type.items():
            lines.append(f'titan_errors_by_type{{type="{error_type}"}} {count}')

        # Challenge types
        for challenge_type, count in self.challenges_by_type.items():
            lines.append(f'titan_challenges_by_type{{type="{challenge_type}"}} {count}')

        return "\n".join(lines)

    @classmethod
    def reset(cls) -> None:
        """Reset all metrics (for testing)."""
        if cls._instance:
            cls._instance._initialize()


# Global metrics instance
_metrics = TitanMetrics()


def log_scrape_operation(
    operation_id: str,
    url: str,
    tier_used: int,
    tier_name: str,
    success: bool,
    status: str,
    execution_time_ms: float,
    response_size_bytes: int | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    challenge_detected: str | None = None,
    escalation_path: list[str] | None = None,
    fallback_used: bool = False,
    cached_session_used: bool = False,
) -> OperationLog:
    """Log a scrape operation with structured data.

    Args:
        operation_id: Unique ID for this operation
        url: Target URL
        tier_used: Tier level used (1, 2, or 3)
        tier_name: Human-readable tier name
        success: Whether operation succeeded
        status: Final status (success, blocked, failed, timeout, captcha_required)
        execution_time_ms: Total execution time in milliseconds
        response_size_bytes: Response size in bytes (for success)
        error_type: Type of error (for failures)
        error_message: Error message (for failures)
        challenge_detected: Type of challenge detected
        escalation_path: List of tiers tried
        fallback_used: Whether fallback was used
        cached_session_used: Whether a cached session was used

    Returns:
        The OperationLog that was recorded
    """
    from urllib.parse import urlparse

    # Extract domain
    parsed = urlparse(url)
    domain = parsed.netloc or ""

    log = OperationLog(
        timestamp=datetime.now(UTC).isoformat(),
        operation_id=operation_id,
        url=url,
        domain=domain,
        tier_used=tier_used,
        tier_name=tier_name,
        success=success,
        status=status,
        execution_time_ms=execution_time_ms,
        response_size_bytes=response_size_bytes,
        error_type=error_type,
        error_message=error_message,
        challenge_detected=challenge_detected,
        escalation_path=escalation_path,
        fallback_used=fallback_used,
        cached_session_used=cached_session_used,
    )

    # Record in metrics
    _metrics.record_operation(log)

    # Log structured JSON
    if success:
        logger.info(log.to_json())
    else:
        logger.warning(log.to_json())

    return log


def get_metrics_summary() -> dict[str, Any]:
    """Get current metrics summary."""
    return _metrics.get_summary()


def get_prometheus_metrics() -> str:
    """Get metrics in Prometheus format."""
    return _metrics.to_prometheus()
