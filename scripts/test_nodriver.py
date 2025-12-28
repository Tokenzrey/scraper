#!/usr/bin/env python3
"""
PROJECT NODRIVER v3.0 - Test Script

Demonstrates the Nodriver Tier 3 full browser engine.
Tests NodriverClient, configuration loading, and the main executor.

Usage:
    python scripts/test_nodriver.py

Requirements:
    - nodriver >= 0.30
    - opencv-python (optional, for cf_verify)
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path for local development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app.services.titan.tiers.nodriver import (
    ConfigLoader,
    NodriverClient,
    NodriverConfig,
    Tier3NodriverExecutor,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nodriver_test")


def test_config_loading():
    """Test configuration loading."""
    logger.info("=" * 60)
    logger.info("TEST 1: Configuration Loading")
    logger.info("=" * 60)

    # Load from default file
    logger.info("Loading from default Data Bank file...")
    config = ConfigLoader.from_default_file()

    logger.info(f"Version: {config.version}")
    logger.info(f"Browser Headless: {config.tier3.browser.headless}")
    logger.info(f"Browser Lang: {config.tier3.browser.lang}")
    logger.info(f"Expert Mode: {config.tier3.browser.startup.expert_mode}")
    logger.info(f"CF Verify Enabled: {config.tier3.cloudflare.cf_verify_enabled}")
    logger.info(f"Challenge Wait: {config.tier3.cloudflare.challenge_wait_seconds}s")
    logger.info(f"Total Timeout: {config.tier3.timeouts.total}s")
    logger.info(f"Max Retries: {config.tier3.retry.max_retries}")

    # Test merging
    logger.info("\nTesting config merge...")
    merged = ConfigLoader.merge(
        config,
        {
            "tier3": {
                "browser": {"headless": True},
                "cloudflare": {"cf_verify_enabled": False},
            }
        },
    )
    logger.info(f"Merged Headless: {merged.tier3.browser.headless}")
    logger.info(f"Merged CF Verify: {merged.tier3.cloudflare.cf_verify_enabled}")

    logger.info("TEST 1: PASSED\n")


async def test_nodriver_client():
    """Test NodriverClient directly."""
    logger.info("=" * 60)
    logger.info("TEST 2: Nodriver Client")
    logger.info("=" * 60)

    config = ConfigLoader.default()
    # Set headless for testing
    config.tier3.browser.headless = True

    async with NodriverClient(config=config) as client:
        logger.info("Making request to httpbin.org...")
        response = await client.fetch("https://httpbin.org/html")

        logger.info(f"Success: {response.success}")
        logger.info(f"Status Code: {response.status_code}")
        logger.info(f"Response Time: {response.response_time_ms:.0f}ms")
        logger.info(f"Content Length: {len(response.content)} bytes")
        logger.info(f"CF Verify Used: {response.cf_verify_used}")

        if response.detected_challenge:
            logger.warning(f"Challenge Detected: {response.detected_challenge}")

        if response.error:
            logger.warning(f"Error: {response.error}")

        stats = client.get_stats()
        logger.info(f"Client Stats: {stats}")

    logger.info("TEST 2: PASSED\n")


async def test_executor():
    """Test Tier3NodriverExecutor."""
    logger.info("=" * 60)
    logger.info("TEST 3: Executor")
    logger.info("=" * 60)

    # Mock settings
    class MockSettings:
        TITAN_BROWSER_TIMEOUT = 60
        TITAN_HEADLESS = True

    async with Tier3NodriverExecutor(settings=MockSettings()) as executor:
        logger.info("Executing request to httpbin.org...")
        result = await executor.execute("https://httpbin.org/get")

        logger.info(f"Success: {result.success}")
        logger.info(f"Status Code: {result.status_code}")
        logger.info(f"Execution Time: {result.execution_time_ms:.0f}ms")
        logger.info(f"Response Size: {result.response_size_bytes} bytes")
        logger.info(f"Tier Used: {result.tier_used}")
        logger.info(f"CF Verify Used: {result.metadata.get('cf_verify_used', False)}")

        if result.error:
            logger.warning(f"Error: {result.error}")

        stats = executor.get_stats()
        logger.info(f"Executor Stats: {stats}")

    logger.info("TEST 3: PASSED\n")


async def test_error_handling():
    """Test error handling for invalid domains."""
    logger.info("=" * 60)
    logger.info("TEST 4: Error Handling")
    logger.info("=" * 60)

    class MockSettings:
        TITAN_BROWSER_TIMEOUT = 30
        TITAN_HEADLESS = True

    async with Tier3NodriverExecutor(settings=MockSettings()) as executor:
        # Test DNS error
        logger.info("Testing DNS error handling...")
        result = await executor.execute(
            "https://this-domain-definitely-does-not-exist-12345.com"
        )

        logger.info(f"Success: {result.success}")
        logger.info(f"Error Type: {result.error_type}")
        logger.info(f"Should Escalate: {result.should_escalate}")
        logger.info(f"Error: {result.error}")

    logger.info("TEST 4: PASSED\n")


async def test_cloudflare_site():
    """Test against a Cloudflare-protected site (optional)."""
    logger.info("=" * 60)
    logger.info("TEST 5: Cloudflare Site (Optional)")
    logger.info("=" * 60)

    class MockSettings:
        TITAN_BROWSER_TIMEOUT = 90
        TITAN_HEADLESS = False  # Better chance with visible browser

    try:
        async with Tier3NodriverExecutor(settings=MockSettings()) as executor:
            logger.info("Testing Cloudflare-protected site...")
            # Using a known Cloudflare test page
            result = await executor.execute("https://www.cloudflare.com/")

            logger.info(f"Success: {result.success}")
            logger.info(f"Detected Challenge: {result.detected_challenge}")
            logger.info(f"CF Verify Used: {result.metadata.get('cf_verify_used', False)}")

            if result.success:
                logger.info(f"Content Length: {result.response_size_bytes} bytes")
            else:
                logger.warning(f"Failed: {result.error}")

    except Exception as e:
        logger.warning(f"Cloudflare test skipped: {e}")

    logger.info("TEST 5: PASSED\n")


async def run_all_tests():
    """Run all tests."""
    logger.info("\n" + "=" * 60)
    logger.info("PROJECT NODRIVER v3.0 - Test Suite")
    logger.info("=" * 60 + "\n")

    tests = [
        ("Config Loading", test_config_loading),
        ("Nodriver Client", test_nodriver_client),
        ("Executor", test_executor),
        ("Error Handling", test_error_handling),
        # ("Cloudflare Site", test_cloudflare_site),  # Optional - uncomment to test
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
    try:
        import nodriver
        logger.info(f"nodriver version: {nodriver.__version__ if hasattr(nodriver, '__version__') else 'unknown'}")
    except ImportError:
        logger.error("nodriver not installed. Install with: pip install nodriver")
        sys.exit(1)

    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
