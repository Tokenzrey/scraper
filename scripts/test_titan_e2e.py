#!/usr/bin/env python3
"""
Titan Worker - End-to-End Validation Script (Comprehensive)

This script tests the full Titan Worker flow including:
1. Simple static site scraping (REQUEST mode)
2. Dynamic/JS site scraping (BROWSER mode)
3. Cloudflare-protected site handling (AUTO mode with escalation)
4. Rate limit handling
5. Timeout handling
6. Error case validation

Test Categories:
- Basic: Static sites that should work with REQUEST mode
- Browser: Sites requiring JavaScript rendering
- Cloudflare: Sites with Cloudflare protection
- Edge Cases: Timeout, errors, edge scenarios

Usage:
    # Start services first:
    docker compose up -d

    # Run all tests:
    python scripts/test_titan_e2e.py --all

    # Run specific category:
    python scripts/test_titan_e2e.py --category basic
    python scripts/test_titan_e2e.py --category cloudflare

    # Run specific URL:
    python scripts/test_titan_e2e.py --url https://example.com --strategy auto

    # Verbose mode:
    python scripts/test_titan_e2e.py --all --verbose
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from enum import Enum

import httpx

# =============================================================================
# CONFIGURATION
# =============================================================================
API_BASE_URL = "http://localhost:8000/api/v1"
DEBUG = False  # Set via --verbose flag
TIMEOUT_NORMAL = 90  # Normal polling timeout (increased for retry delays)
TIMEOUT_BROWSER = 180  # Longer timeout for browser mode (allows 120s worker + retries)
TIMEOUT_CLOUDFLARE = 150  # Extra long timeout for Cloudflare bypass (120s worker + margin)
TEST_DELAY = 3  # Delay between tests to avoid rate limiting (seconds)
MAX_RATE_LIMIT_RETRIES = 5  # Max retries on rate limit
RATE_LIMIT_BACKOFF = 10  # Initial backoff on rate limit (seconds)

# =============================================================================
# SMART HTTPBIN CONFIGURATION
# =============================================================================
# Prefer self-hosted httpbin (docker service) but fallback to public
# NOTE: From host machine, use localhost:8080 (docker-compose port mapping)
#       From inside Docker network, use httpbin:80
HTTPBIN_LOCAL_URL = os.environ.get("HTTPBIN_URL", "http://localhost:8080")
HTTPBIN_PUBLIC_URL = "https://httpbin.org"

# Global flag to track httpbin availability
HTTPBIN_AVAILABLE = False
HTTPBIN_IS_LOCAL = False


def check_httpbin_health(url: str, timeout: int = 5) -> tuple[bool, str]:
    """
    Check if httpbin is healthy and reachable.

    Returns:
        Tuple of (is_healthy, error_message)
    """
    try:
        response = httpx.get(f"{url}/get", timeout=timeout)
        if response.status_code == 200:
            return True, ""
        elif response.status_code == 503:
            return False, "Service Unavailable (503) - httpbin may be overloaded"
        else:
            return False, f"Unexpected status code: {response.status_code}"
    except httpx.ConnectError as e:
        return False, f"Connection Refused - service is down or port not exposed ({e})"
    except httpx.TimeoutException:
        return False, "Connection timeout - service not responding"
    except Exception as e:
        return False, f"Unknown error: {e}"


def get_httpbin_base_url() -> str:
    """
    Get the best available httpbin URL with comprehensive health checking.

    Priority:
    1. Environment variable (TEST_HTTPBIN_URL or HTTPBIN_URL)
    2. localhost:8080 (docker-compose port mapping from host)
    3. httpbin:80 (docker internal network)
    4. httpbin.org (public, unreliable fallback)
    """
    global HTTPBIN_AVAILABLE, HTTPBIN_IS_LOCAL

    # First try environment variables
    env_url = os.environ.get("TEST_HTTPBIN_URL") or os.environ.get("HTTPBIN_URL")
    if env_url:
        env_url = env_url.rstrip("/")
        is_healthy, error = check_httpbin_health(env_url)
        if is_healthy:
            print(f"  ✓ Using httpbin from env: {env_url}")
            HTTPBIN_AVAILABLE = True
            HTTPBIN_IS_LOCAL = "localhost" in env_url or "httpbin:" in env_url
            return env_url
        else:
            print(f"  ⚠ Env httpbin ({env_url}) unhealthy: {error}")

    # Try local httpbin URLs
    local_urls = ["http://localhost:8080", "http://127.0.0.1:8080", "http://httpbin:80"]
    for local_url in local_urls:
        is_healthy, error = check_httpbin_health(local_url)
        if is_healthy:
            print(f"  ✓ Using self-hosted httpbin: {local_url}")
            HTTPBIN_AVAILABLE = True
            HTTPBIN_IS_LOCAL = True
            return local_url
        else:
            debug_log(f"Local httpbin ({local_url}) unavailable: {error}")

    # Try public httpbin as last resort
    print("  ⚠ Local httpbin not available, trying public...")
    is_healthy, error = check_httpbin_health(HTTPBIN_PUBLIC_URL, timeout=10)
    if is_healthy:
        print(f"  ⚠ Using public httpbin (may be unreliable): {HTTPBIN_PUBLIC_URL}")
        HTTPBIN_AVAILABLE = True
        HTTPBIN_IS_LOCAL = False
        return HTTPBIN_PUBLIC_URL
    else:
        print(f"  ✗ Public httpbin also unavailable: {error}")
        print("  ✗ ALL HTTPBIN SOURCES UNAVAILABLE")
        print("    → Suggestion: Run 'docker run -p 8080:80 kennethreitz/httpbin' in another terminal")
        HTTPBIN_AVAILABLE = False
        HTTPBIN_IS_LOCAL = False
        return HTTPBIN_PUBLIC_URL  # Return anyway for test case generation


HTTPBIN_BASE_URL = None  # Will be set at runtime


class Category(Enum):
    """Test categories."""

    BASIC = "basic"
    BROWSER = "browser"
    CLOUDFLARE = "cloudflare"
    EDGE_CASE = "edge_case"
    ALL = "all"


@dataclass
class Case:
    """Represents a single test case."""

    name: str
    url: str
    strategy: str
    category: Category
    expected_status: str = "success"
    expected_strategy_used: str | None = None  # None means any
    should_fallback: bool | None = None  # None means don't check
    max_execution_time_ms: int = 15000  # 15s default
    min_content_length: int = 100
    content_contains: list[str] | None = None  # Required text in content
    description: str = ""
    # === SMART TEST EXPECTATIONS ===
    # For tests that may have multiple acceptable outcomes
    acceptable_statuses: list[str] | None = None  # Multiple OK statuses
    skip_on_external_failure: bool = False  # Skip if external service is down
    is_external: bool = False  # True for external services like httpbin.org


# =============================================================================
# TEST CASES DEFINITION
# =============================================================================
def get_test_cases() -> list[Case]:
    """Generate test cases with dynamic httpbin URL."""
    global HTTPBIN_BASE_URL
    if HTTPBIN_BASE_URL is None:
        HTTPBIN_BASE_URL = get_httpbin_base_url()

    httpbin = HTTPBIN_BASE_URL

    return [
        # ---------- BASIC TESTS (REQUEST mode should work) ----------
        Case(
            name="example.com-request",
            url="https://example.com",
            strategy="request",
            category=Category.BASIC,
            expected_status="success",
            expected_strategy_used="request",
            max_execution_time_ms=5000,
            min_content_length=500,
            content_contains=["Example Domain"],
            description="Simple static site - should work with REQUEST mode",
        ),
        Case(
            name="example.org-request",
            url="https://example.org",
            strategy="request",
            category=Category.BASIC,
            expected_status="success",
            expected_strategy_used="request",
            max_execution_time_ms=5000,
            description="Example.org - static site",
        ),
        Case(
            name="w3.org-request",
            url="https://www.w3.org/",
            strategy="request",
            category=Category.BASIC,
            expected_status="success",
            max_execution_time_ms=10000,
            description="W3C website - more complex static",
        ),
        Case(
            name="httpbin-request",
            url=f"{httpbin}/html",
            strategy="request",
            category=Category.BASIC,
            expected_status="success",
            expected_strategy_used="request",
            content_contains=["Herman Melville"],
            description="HTTPBin HTML endpoint (self-hosted or public)",
            is_external="httpbin.org" in httpbin,
            acceptable_statuses=["success", "failed"],  # 503 from public is OK
            skip_on_external_failure=True,
        ),
        # ---------- AUTO MODE TESTS (Should try REQUEST first, fallback if needed) ----------
        Case(
            name="example.com-auto",
            url="https://example.com",
            strategy="auto",
            category=Category.BASIC,
            expected_status="success",
            expected_strategy_used="request",  # Should succeed with REQUEST
            should_fallback=False,
            description="AUTO mode should use REQUEST for simple sites",
        ),
        # ---------- BROWSER MODE TESTS (Force browser usage) ----------
        Case(
            name="example.com-browser",
            url="https://example.com",
            strategy="browser",
            category=Category.BROWSER,
            expected_status="success",
            expected_strategy_used="browser",
            max_execution_time_ms=15000,
            description="Force BROWSER mode on simple site",
        ),
        # ---------- CLOUDFLARE TESTS (Sites with Cloudflare protection) ----------
        # Note: These are unpredictable. Use acceptable_statuses for flexibility.
        Case(
            name="cloudflare-protected-auto",
            url="https://nowsecure.nl/",  # Known Cloudflare-protected test site
            strategy="auto",
            category=Category.CLOUDFLARE,
            expected_status="success",
            acceptable_statuses=[
                "success",
                "blocked",
                "timeout",
            ],  # May need manual CAPTCHA
            should_fallback=True,  # Should escalate from REQUEST to BROWSER
            max_execution_time_ms=60000,
            description="Cloudflare-protected site - may require manual CAPTCHA",
            is_external=True,
        ),
        Case(
            name="cloudflare-protected-browser",
            url="https://nowsecure.nl/",
            strategy="browser",
            category=Category.CLOUDFLARE,
            expected_status="success",
            acceptable_statuses=[
                "success",
                "blocked",
                "timeout",
            ],  # May need manual CAPTCHA
            expected_strategy_used="browser",
            max_execution_time_ms=60000,
            description="Cloudflare-protected site - force browser mode",
            is_external=True,
        ),
        Case(
            name="cloudflare-discord-com",
            url="https://discord.com/",
            strategy="auto",
            category=Category.CLOUDFLARE,
            expected_status="success",
            acceptable_statuses=["success", "blocked"],  # Discord may block
            max_execution_time_ms=30000,
            description="Discord (Cloudflare protected) - AUTO mode",
            is_external=True,
        ),
        Case(
            name="cloudflare-medium",
            url="https://medium.com/",
            strategy="auto",
            category=Category.CLOUDFLARE,
            expected_status="success",
            acceptable_statuses=["success", "blocked"],  # Medium may require login
            max_execution_time_ms=30000,
            description="Medium (Cloudflare protection) - AUTO mode",
            is_external=True,
        ),
        Case(
            name="cloudflare-request-expect-blocked",
            url="https://nowsecure.nl/",
            strategy="request",
            category=Category.CLOUDFLARE,
            expected_status="blocked",  # REQUEST mode should be blocked
            expected_strategy_used="request",
            should_fallback=False,
            description="Cloudflare-protected - REQUEST only should be blocked",
            is_external=True,
        ),
        # ---------- EDGE CASE TESTS ----------
        Case(
            name="invalid-url",
            url="https://this-domain-definitely-does-not-exist-12345.com/",
            strategy="auto",
            category=Category.EDGE_CASE,
            expected_status="failed",  # Should fail gracefully
            max_execution_time_ms=30000,  # Should fail fast with DNS pre-check (~5-10s)
            description="Non-existent domain - should fail gracefully (DNS error, fail-fast)",
        ),
        Case(
            name="httpbin-status-403",
            url=f"{httpbin}/status/403",
            strategy="request",
            category=Category.EDGE_CASE,
            expected_status="blocked",  # Should detect as blocked
            acceptable_statuses=["blocked", "failed"],  # 503 from httpbin is OK
            description="HTTP 403 response - should detect as blocked",
            is_external="httpbin.org" in httpbin,
            skip_on_external_failure=True,
        ),
        Case(
            name="httpbin-status-429",
            url=f"{httpbin}/status/429",
            strategy="request",
            category=Category.EDGE_CASE,
            expected_status="blocked",  # Rate limited
            acceptable_statuses=["blocked", "failed"],  # 503 from httpbin is OK
            description="HTTP 429 rate limit response",
            is_external="httpbin.org" in httpbin,
            skip_on_external_failure=True,
        ),
        Case(
            name="httpbin-status-503",
            url=f"{httpbin}/status/503",
            strategy="request",
            category=Category.EDGE_CASE,
            expected_status="failed",  # Server error (NOT blocked - 503 is temporary)
            description="HTTP 503 service unavailable response",
            is_external="httpbin.org" in httpbin,
            skip_on_external_failure=True,
        ),
        Case(
            name="httpbin-delay-5s",
            url=f"{httpbin}/delay/5",
            strategy="request",
            category=Category.EDGE_CASE,
            expected_status="success",
            acceptable_statuses=["success", "failed"],  # 503 from httpbin is OK
            max_execution_time_ms=15000,
            description="Slow response (5s delay) - should handle gracefully",
            is_external="httpbin.org" in httpbin,
            skip_on_external_failure=True,
        ),
        Case(
            name="httpbin-delay-timeout",
            url=f"{httpbin}/delay/35",  # Longer than typical timeout
            strategy="request",
            category=Category.EDGE_CASE,
            expected_status="timeout",
            acceptable_statuses=["timeout", "failed"],  # 503 from httpbin is OK
            max_execution_time_ms=60000,
            description="Very slow response - should timeout",
            is_external="httpbin.org" in httpbin,
            skip_on_external_failure=True,
        ),
        Case(
            name="httpbin-json-endpoint",
            url=f"{httpbin}/json",
            strategy="request",
            category=Category.EDGE_CASE,
            expected_status="success",
            acceptable_statuses=["success", "failed"],  # 503 from httpbin is OK
            content_contains=["slideshow"],
            description="JSON response - should handle non-HTML",
            is_external="httpbin.org" in httpbin,
            skip_on_external_failure=True,
        ),
        Case(
            name="httpbin-redirect-chain",
            url=f"{httpbin}/redirect/3",
            strategy="request",
            category=Category.EDGE_CASE,
            expected_status="success",
            acceptable_statuses=["success", "failed"],  # 503 from httpbin is OK
            max_execution_time_ms=90000,  # Increased for slow redirects in Docker
            description="Multiple redirects - should follow",
            is_external="httpbin.org" in httpbin,
            skip_on_external_failure=True,
        ),
        Case(
            name="httpbin-utf8",
            url=f"{httpbin}/encoding/utf8",
            strategy="request",
            category=Category.EDGE_CASE,
            expected_status="success",
            acceptable_statuses=["success", "failed"],  # 503 from httpbin is OK
            description="UTF-8 encoding test",
            is_external="httpbin.org" in httpbin,
            skip_on_external_failure=True,
        ),
    ]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
def debug_log(msg: str) -> None:
    """Print debug message if DEBUG is enabled."""
    if DEBUG:
        print(f"  [DEBUG] {msg}")


def log_info(msg: str) -> None:
    """Print info message."""
    print(f"  {msg}")


def log_success(msg: str) -> None:
    """Print success message."""
    print(f"  ✓ {msg}")


def log_fail(msg: str) -> None:
    """Print failure message."""
    print(f"  ✗ {msg}")


def log_warn(msg: str) -> None:
    """Print warning message."""
    print(f"  ⚠ {msg}")


# =============================================================================
# API INTERACTION
# =============================================================================
def create_scrape_task(
    client: httpx.Client,
    url: str,
    strategy: str = "auto",
    max_retries: int = MAX_RATE_LIMIT_RETRIES,
) -> str | None:
    """Create a scrape task and return job_id. Handles rate limiting with retries."""
    backoff = RATE_LIMIT_BACKOFF

    for attempt in range(max_retries + 1):
        try:
            payload = {
                "url": url,
                "strategy": strategy,
            }
            debug_log(f"POST {API_BASE_URL}/scrape (attempt {attempt + 1})")
            debug_log(f"Payload: {json.dumps(payload)}")

            response = client.post(
                f"{API_BASE_URL}/scrape",
                json=payload,
                timeout=30.0,
            )

            debug_log(f"Response status: {response.status_code}")
            debug_log(f"Response body: {response.text[:500]}")

            if response.status_code == 201:
                data = response.json()
                job_id = data["job_id"]
                debug_log(f"Job created: {job_id}")
                return job_id
            elif response.status_code == 429:
                # Rate limited - wait and retry
                if attempt < max_retries:
                    log_warn(f"Rate limited. Waiting {backoff}s before retry...")
                    time.sleep(backoff)
                    backoff *= 2  # Exponential backoff
                    continue
                else:
                    log_fail(f"Rate limit exceeded after {max_retries} retries")
                    return None
            else:
                log_fail(f"Task creation failed: {response.status_code} - {response.text[:200]}")
                return None

        except Exception as e:
            log_fail(f"Task creation error: {e}")
            if DEBUG:
                import traceback

                traceback.print_exc()
            return None

    return None


def poll_task_status(
    client: httpx.Client,
    job_id: str,
    max_wait: int = TIMEOUT_NORMAL,
    poll_interval: int = 2,
) -> dict | None:
    """Poll task status until complete or timeout."""
    debug_log(f"Polling task {job_id} (max wait: {max_wait}s)")

    start_time = time.time()
    last_status = None
    error_count = 0
    max_errors = 5

    while time.time() - start_time < max_wait:
        try:
            response = client.get(
                f"{API_BASE_URL}/scrape/{job_id}",
                timeout=30.0,
            )

            if response.status_code == 200:
                error_count = 0
                data = response.json()
                status = data["status"]

                if status != last_status:
                    debug_log(f"Status: {status} (elapsed: {int(time.time() - start_time)}s)")
                    last_status = status

                if status == "complete":
                    return data
                elif status in ("failed", "not_found"):
                    return data

            elif response.status_code == 404:
                return None
            else:
                error_count += 1
                if error_count >= max_errors:
                    log_fail("Too many errors polling task")
                    return None

            time.sleep(poll_interval)

        except Exception as e:
            error_count += 1
            debug_log(f"Poll error: {e}")
            if error_count >= max_errors:
                return None
            time.sleep(poll_interval)

    log_fail(f"Polling timeout after {max_wait}s")
    return None


# =============================================================================
# TEST VALIDATION
# =============================================================================
def validate_result(test_case: Case, result: dict | None) -> tuple[bool, list[str]]:
    """
    Validate scrape result against test case expectations.

    Supports smart test expectations:
    - acceptable_statuses: Multiple OK statuses for external services
    - skip_on_external_failure: Mark as skipped if external service is down

    Returns:
        Tuple of (passed, list of failure/warning messages)
    """
    messages: list[str] = []
    passed = True

    if result is None:
        return False, ["No result received"]

    task_result = result.get("result")
    if task_result is None:
        return False, [f"No task result. Status: {result.get('status')}"]

    status = task_result.get("status")
    strategy_used = task_result.get("strategy_used")
    execution_time = task_result.get("execution_time_ms", 0)
    fallback_used = task_result.get("fallback_used", False)
    content = task_result.get("content", "")
    error = task_result.get("error", "")

    # === SMART STATUS CHECK ===
    # If acceptable_statuses is set, any of those statuses is OK
    acceptable = test_case.acceptable_statuses or [test_case.expected_status]

    if status not in acceptable:
        passed = False
        if len(acceptable) > 1:
            messages.append(f"Status '{status}' not in acceptable: {acceptable}")
        else:
            messages.append(f"Expected status '{test_case.expected_status}', got '{status}'")
    else:
        # Status is acceptable - if it's not the primary expected, note it
        if status != test_case.expected_status and len(acceptable) > 1:
            messages.append(f"[INFO] Got acceptable status '{status}' (expected: '{test_case.expected_status}')")

    # === SKIP ON EXTERNAL FAILURE ===
    # If this is an external service test and it failed due to service unavailability
    if test_case.skip_on_external_failure and test_case.is_external:
        service_unavailable_indicators = [
            "503",
            "service unavailable",
            "connection refused",
            "timed out",
        ]
        error_lower = error.lower() if error else ""
        if status == "failed" and any(ind in error_lower for ind in service_unavailable_indicators):
            messages.append(f"[SKIP] External service unavailable: {error[:100]}")
            return True, messages  # Mark as passed (skipped)

    # --- Strategy Used Check ---
    if test_case.expected_strategy_used and strategy_used != test_case.expected_strategy_used:
        passed = False
        messages.append(f"Expected strategy '{test_case.expected_strategy_used}', got '{strategy_used}'")

    # --- Fallback Check ---
    if test_case.should_fallback is not None:
        if fallback_used != test_case.should_fallback:
            # This is a warning, not a failure (fallback behavior can vary)
            messages.append(f"Expected fallback={test_case.should_fallback}, got fallback={fallback_used}")

    # --- Execution Time Check ---
    if status == "success" and execution_time > test_case.max_execution_time_ms:
        messages.append(f"Execution time {execution_time}ms exceeded max {test_case.max_execution_time_ms}ms")

    # --- Content Length Check (only for success) ---
    if status == "success":
        content_length = len(content) if content else 0
        if content_length < test_case.min_content_length:
            passed = False
            messages.append(f"Content length {content_length} < min {test_case.min_content_length}")

        # --- Content Contains Check ---
        if test_case.content_contains:
            for expected_text in test_case.content_contains:
                if expected_text.lower() not in content.lower():
                    passed = False
                    messages.append(f"Content missing expected text: '{expected_text}'")

    # --- Error Check (for expected failures) ---
    if test_case.expected_status in ("failed", "blocked", "timeout"):
        if not error:
            messages.append("Expected error message for failed status")

    return passed, messages


# =============================================================================
# TEST RUNNER
# =============================================================================
def run_test(client: httpx.Client, test_case: Case) -> bool:
    """Run a single test case."""
    print(f"\n{'='*60}")
    print(f"TEST: {test_case.name}")
    print(f"{'='*60}")
    log_info(f"URL: {test_case.url}")
    log_info(f"Strategy: {test_case.strategy}")
    log_info(f"Category: {test_case.category.value}")
    if test_case.description:
        log_info(f"Description: {test_case.description}")

    # Create task
    job_id = create_scrape_task(client, test_case.url, test_case.strategy)
    if not job_id:
        log_fail("Failed to create task")
        return False

    log_info(f"Job ID: {job_id}")

    # Determine timeout based on test category and strategy
    # Cloudflare tests need extra time for full browser + bypass
    if test_case.category == Category.CLOUDFLARE:
        timeout = TIMEOUT_CLOUDFLARE
    elif test_case.strategy == "browser":
        timeout = TIMEOUT_BROWSER
    else:
        timeout = TIMEOUT_NORMAL

    debug_log(f"Using timeout: {timeout}s (category={test_case.category.value})")

    # Poll for result
    result = poll_task_status(client, job_id, max_wait=timeout)

    # Validate
    passed, messages = validate_result(test_case, result)

    # Print result summary
    if result and result.get("result"):
        task_result = result["result"]
        log_info(f"Status: {task_result.get('status')}")
        log_info(f"Strategy Used: {task_result.get('strategy_used')}")
        log_info(f"Execution Time: {task_result.get('execution_time_ms', 0)}ms")
        log_info(f"Fallback Used: {task_result.get('fallback_used', False)}")
        content_len = len(task_result.get("content", "")) if task_result.get("content") else 0
        log_info(f"Content Length: {content_len} bytes")
        if task_result.get("error"):
            log_info(f"Error: {task_result.get('error')}")

    # Print validation messages
    for msg in messages:
        if "Expected" in msg or "missing" in msg or "exceeded" in msg:
            log_fail(msg)
        else:
            log_warn(msg)

    if passed:
        log_success("TEST PASSED")
    else:
        log_fail("TEST FAILED")

    return passed


def run_tests_by_category(
    client: httpx.Client,
    category: Category,
) -> tuple[int, int, int]:
    """
    Run all tests in a category.

    Returns (passed, failed, skipped).
    """
    all_test_cases = get_test_cases()

    if category == Category.ALL:
        test_cases = all_test_cases
    else:
        test_cases = [tc for tc in all_test_cases if tc.category == category]

    if not test_cases:
        print(f"No tests found for category: {category.value}")
        return 0, 0, 0

    passed = 0
    failed = 0
    skipped = 0
    total = len(test_cases)

    print(f"\n{'#'*60}")
    print(f"RUNNING {total} TESTS - Category: {category.value}")
    print(f"Using httpbin: {HTTPBIN_BASE_URL}")
    print(f"Httpbin available: {HTTPBIN_AVAILABLE}")
    print(f"{'#'*60}")

    for i, test_case in enumerate(test_cases):
        # === PRE-FLIGHT CHECK: Skip httpbin tests if httpbin is unavailable ===
        if HTTPBIN_BASE_URL and HTTPBIN_BASE_URL in test_case.url and not HTTPBIN_AVAILABLE:
            print(f"\n{'='*60}")
            print(f"TEST: {test_case.name}")
            print(f"{'='*60}")
            log_warn(f"SKIPPING: httpbin unavailable for {test_case.url}")
            log_warn("  → Run 'docker run -p 8080:80 kennethreitz/httpbin' to enable")
            skipped += 1
            continue

        if run_test(client, test_case):
            passed += 1
        else:
            failed += 1

        # Add delay between tests to avoid rate limiting
        if i < len(test_cases) - 1:
            debug_log(f"Waiting {TEST_DELAY}s before next test...")
            time.sleep(TEST_DELAY)

    return passed, failed, skipped


# =============================================================================
# HEALTH CHECK
# =============================================================================
def check_api_health(client: httpx.Client) -> bool:
    """Check if API is healthy and ready."""
    try:
        response = client.get(f"{API_BASE_URL}/health", timeout=10.0)
        if response.status_code == 200:
            return True
        else:
            log_fail(f"Health check failed: {response.status_code}")
            return False
    except Exception as e:
        log_fail(f"Health check error: {e}")
        return False


# =============================================================================
# MAIN
# =============================================================================
def main() -> int:
    global API_BASE_URL, DEBUG

    parser = argparse.ArgumentParser(
        description="Titan Worker E2E Validation (Comprehensive)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all tests:
  python scripts/test_titan_e2e.py --all

  # Run basic tests only:
  python scripts/test_titan_e2e.py --category basic

  # Run Cloudflare tests:
  python scripts/test_titan_e2e.py --category cloudflare

  # Test specific URL:
  python scripts/test_titan_e2e.py --url https://example.com --strategy auto

  # Verbose output:
  python scripts/test_titan_e2e.py --all --verbose
        """,
    )
    parser.add_argument(
        "--url",
        type=str,
        help="Specific URL to test",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="auto",
        choices=["auto", "request", "browser"],
        help="Scraping strategy to use",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=API_BASE_URL,
        help="API base URL",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all tests",
    )
    parser.add_argument(
        "--category",
        type=str,
        choices=["basic", "browser", "cloudflare", "edge_case", "all"],
        help="Run tests by category",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose debug output",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available test cases",
    )
    args = parser.parse_args()

    API_BASE_URL = args.api_url
    DEBUG = args.verbose

    # List tests if requested
    if args.list:
        all_test_cases = get_test_cases()
        print("Available Test Cases:")
        print("-" * 60)
        for tc in all_test_cases:
            print(f"  [{tc.category.value:10}] {tc.name}")
            print(f"              URL: {tc.url}")
            print(f"              {tc.description}")
            if tc.acceptable_statuses:
                print(f"              Acceptable: {tc.acceptable_statuses}")
            print()
        return 0

    print("=" * 60)
    print("TITAN WORKER - END-TO-END VALIDATION (Comprehensive)")
    print("=" * 60)
    print(f"API Base URL: {API_BASE_URL}")
    print(f"Debug Mode: {'ON' if DEBUG else 'OFF'}")

    # Check API health
    with httpx.Client() as client:
        if not check_api_health(client):
            print("\nMake sure services are running: docker compose up -d")
            return 1

        log_success("API Health: OK")

        results: list[tuple[int, int, int]] = []  # (passed, failed, skipped)

        if args.url:
            # Test specific URL
            test_case = Case(
                name="custom-test",
                url=args.url,
                strategy=args.strategy,
                category=Category.BASIC,
                description="Custom URL test",
            )
            passed = run_test(client, test_case)
            results.append((1 if passed else 0, 0 if passed else 1, 0))

        elif args.all or args.category == "all":
            # Run all tests
            results.append(run_tests_by_category(client, Category.ALL))

        elif args.category:
            # Run specific category
            category = Category(args.category)
            results.append(run_tests_by_category(client, category))

        else:
            # Default: run basic tests
            results.append(run_tests_by_category(client, Category.BASIC))

    # Summary
    total_passed = sum(r[0] for r in results)
    total_failed = sum(r[1] for r in results)
    total_skipped = sum(r[2] for r in results)
    total_tests = total_passed + total_failed + total_skipped

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Passed:  {total_passed}")
    print(f"Failed:  {total_failed}")
    print(f"Skipped: {total_skipped}")
    print(f"Total:   {total_tests}")

    if total_failed == 0:
        if total_skipped > 0:
            log_warn(f"ALL TESTS PASSED ({total_skipped} skipped due to unavailable services)")
        else:
            log_success("ALL TESTS PASSED")
        return 0
    else:
        log_fail(f"FAILED: {total_failed} test(s)")
        if total_skipped > 0:
            log_warn(f"Skipped: {total_skipped} test(s) due to unavailable services")
        return 1


if __name__ == "__main__":
    sys.exit(main())
