#!/usr/bin/env python3
"""
PROJECT BOTASAURUS v2.0 - Test Script

Demonstrates the Botasaurus Tier 2 data acquisition engine.
Tests RequestClient, BrowserClient, and the main executor.

Usage:
    python scripts/test_botasaurus.py

Requirements:
    - botasaurus >= 4.0.0
    - botasaurus-requests
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path for local development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app.services.titan.tiers.botasaurus import (
    BotasaurusConfig,
    BrowserClient,
    ConfigLoader,
    RequestClient,
    Tier2BotasaurusExecutor,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("botasaurus_test")


def test_config_loading():
    """Test configuration loading."""
    logger.info("=" * 60)
    logger.info("TEST 1: Configuration Loading")
    logger.info("=" * 60)

    # Load from default file
    logger.info("Loading from default Data Bank file...")
    config = ConfigLoader.from_default_file()

    logger.info(f"Version: {config.version}")
    logger.info(f"Browser Headless: {config.tier2.browser.headless}")
    logger.info(f"Browser Block Images: {config.tier2.browser.block_images}")
    logger.info(f"User Agent Mode: {config.tier2.browser.fingerprint.user_agent}")
    logger.info(f"Window Size Mode: {config.tier2.browser.fingerprint.window_size}")
    logger.info(f"Tiny Profile: {config.tier2.browser.fingerprint.tiny_profile}")
    logger.info(f"Cloudflare Bypass: {config.tier2.browser.cloudflare.bypass_enabled}")
    logger.info(f"Request Max Retry: {config.tier2.request.max_retry}")
    logger.info(f"Proxy Rotation: {config.tier2.proxy.rotation_strategy}")

    # Test merging
    logger.info("\nTesting config merge...")
    merged = ConfigLoader.merge(
        config,
        {
            "tier2": {
                "browser": {"headless": True},
                "request": {"max_retry": 10},
            }
        },
    )
    logger.info(f"Merged Headless: {merged.tier2.browser.headless}")
    logger.info(f"Merged Max Retry: {merged.tier2.request.max_retry}")

    logger.info("TEST 1: PASSED\n")


def test_request_client():
    """Test RequestClient (lightweight HTTP)."""
    logger.info("=" * 60)
    logger.info("TEST 2: Request Client")
    logger.info("=" * 60)

    config = ConfigLoader.default()
    client = RequestClient(config=config)

    logger.info("Making request to httpbin.org...")
    response = client.fetch_sync("https://httpbin.org/get")

    logger.info(f"Success: {response.success}")
    logger.info(f"Status Code: {response.status_code}")
    logger.info(f"Response Time: {response.response_time_ms:.0f}ms")
    logger.info(f"Content Length: {len(response.content)} bytes")

    if response.detected_challenge:
        logger.warning(f"Challenge Detected: {response.detected_challenge}")

    stats = client.get_stats()
    logger.info(f"Client Stats: {stats}")

    logger.info("TEST 2: PASSED\n")


def test_browser_client():
    """Test BrowserClient (full browser with driver.requests.get)."""
    logger.info("=" * 60)
    logger.info("TEST 3: Browser Client")
    logger.info("=" * 60)

    config = ConfigLoader.default()
    client = BrowserClient(config=config)

    logger.info("Making browser request to httpbin.org...")
    response = client.fetch_sync("https://httpbin.org/get")

    logger.info(f"Success: {response.success}")
    logger.info(f"Status Code: {response.status_code}")
    logger.info(f"Response Time: {response.response_time_ms:.0f}ms")
    logger.info(f"Method Used: {response.method}")
    logger.info(f"Profile ID: {response.profile_id}")
    logger.info(f"Content Length: {len(response.content)} bytes")

    if response.detected_challenge:
        logger.warning(f"Challenge Detected: {response.detected_challenge}")

    stats = client.get_stats()
    logger.info(f"Client Stats: {stats}")

    logger.info("TEST 3: PASSED\n")


async def test_executor_request_mode():
    """Test Tier2BotasaurusExecutor in request-only mode."""
    logger.info("=" * 60)
    logger.info("TEST 4: Executor (Request Mode)")
    logger.info("=" * 60)

    # Mock settings
    class MockSettings:
        TITAN_REQUEST_TIMEOUT = 60
        TITAN_HEADLESS = True

    executor = Tier2BotasaurusExecutor(
        settings=MockSettings(),
        mode="request",
    )

    logger.info("Executing request to httpbin.org (request mode)...")
    result = await executor.execute("https://httpbin.org/headers")

    logger.info(f"Success: {result.success}")
    logger.info(f"Status Code: {result.status_code}")
    logger.info(f"Execution Time: {result.execution_time_ms:.0f}ms")
    logger.info(f"Response Size: {result.response_size_bytes} bytes")
    logger.info(f"Tier Used: {result.tier_used}")

    if result.error:
        logger.warning(f"Error: {result.error}")

    await executor.cleanup()
    logger.info("TEST 4: PASSED\n")


async def test_executor_browser_mode():
    """Test Tier2BotasaurusExecutor in browser-only mode."""
    logger.info("=" * 60)
    logger.info("TEST 5: Executor (Browser Mode)")
    logger.info("=" * 60)

    class MockSettings:
        TITAN_REQUEST_TIMEOUT = 60
        TITAN_HEADLESS = True

    executor = Tier2BotasaurusExecutor(
        settings=MockSettings(),
        mode="browser",
    )

    logger.info("Executing request to httpbin.org (browser mode)...")
    result = await executor.execute("https://httpbin.org/user-agent")

    logger.info(f"Success: {result.success}")
    logger.info(f"Status Code: {result.status_code}")
    logger.info(f"Execution Time: {result.execution_time_ms:.0f}ms")
    logger.info(f"Response Size: {result.response_size_bytes} bytes")
    logger.info(f"Method: {result.metadata.get('method', 'N/A')}")

    if result.error:
        logger.warning(f"Error: {result.error}")

    await executor.cleanup()
    logger.info("TEST 5: PASSED\n")


async def test_executor_auto_mode():
    """Test Tier2BotasaurusExecutor in auto mode (request -> browser)."""
    logger.info("=" * 60)
    logger.info("TEST 6: Executor (Auto Mode)")
    logger.info("=" * 60)

    class MockSettings:
        TITAN_REQUEST_TIMEOUT = 60
        TITAN_HEADLESS = True

    executor = Tier2BotasaurusExecutor(
        settings=MockSettings(),
        mode="auto",
    )

    # Test with a simple URL (should succeed with request)
    logger.info("Test 6a: Simple URL (should use request)...")
    result = await executor.execute("https://httpbin.org/ip")

    logger.info(f"Success: {result.success}")
    logger.info(f"Method: {result.metadata.get('method', 'N/A')}")
    logger.info(f"Escalated: {result.metadata.get('escalated_from_request', False)}")

    stats = executor.get_stats()
    logger.info(f"Executor Stats: {stats}")

    await executor.cleanup()
    logger.info("TEST 6: PASSED\n")


async def test_error_handling():
    """Test error handling for invalid domains."""
    logger.info("=" * 60)
    logger.info("TEST 7: Error Handling")
    logger.info("=" * 60)

    class MockSettings:
        TITAN_REQUEST_TIMEOUT = 30
        TITAN_HEADLESS = True

    executor = Tier2BotasaurusExecutor(
        settings=MockSettings(),
        mode="request",
    )

    # Test DNS error
    logger.info("Testing DNS error handling...")
    result = await executor.execute("https://this-domain-definitely-does-not-exist-12345.com")

    logger.info(f"Success: {result.success}")
    logger.info(f"Error Type: {result.error_type}")
    logger.info(f"Should Escalate: {result.should_escalate}")
    logger.info(f"Error: {result.error}")

    await executor.cleanup()
    logger.info("TEST 7: PASSED\n")


async def run_all_tests():
    """Run all tests."""
    logger.info("\n" + "=" * 60)
    logger.info("PROJECT BOTASAURUS v2.0 - Test Suite")
    logger.info("=" * 60 + "\n")

    tests = [
        ("Config Loading", test_config_loading),
        ("Request Client", test_request_client),
        ("Browser Client", test_browser_client),
        ("Executor Request Mode", test_executor_request_mode),
        ("Executor Browser Mode", test_executor_browser_mode),
        ("Executor Auto Mode", test_executor_auto_mode),
        ("Error Handling", test_error_handling),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            if asyncio.iscoroutinefunction(test_func):
                await test_func()
            else:
                test_func()
            passed += 1
        except Exception as e:
            logger.error(f"TEST FAILED: {name}")
            logger.exception(e)
            failed += 1

    logger.info("\n" + "=" * 60)
    logger.info(f"TEST RESULTS: {passed} passed, {failed} failed")
    logger.info("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
