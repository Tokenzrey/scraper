#!/usr/bin/env python3
"""
PROJECT CHIMERA v4.5 - Test Script

Demonstrates the Chimera Tier 1 data acquisition engine.
Tests the ChimeraClient, ProxyRotator, and swarm execution.

Usage:
    python scripts/test_chimera.py

Requirements:
    - curl-cffi >= 0.7.0
    - Redis (optional, for session persistence)
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path for local development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app.services.titan.tiers.chimera import (
    ChimeraClient,
    ConfigLoader,
    ProxyRotator,
    RedisStateStore,
    SwarmConfig,
    run_chimera_swarm,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("chimera_test")


async def test_single_request():
    """Test a single request with ChimeraClient."""
    logger.info("=" * 60)
    logger.info("TEST 1: Single Request")
    logger.info("=" * 60)

    config = ConfigLoader.default()

    async with ChimeraClient(config=config) as client:
        logger.info(f"Session ID: {client.session_id[:8]}...")
        logger.info("Making request to httpbin.org...")

        response = await client.get("https://httpbin.org/get")

        logger.info(f"Status Code: {response.status_code}")
        logger.info(f"Success: {response.success}")
        logger.info(f"Response Time: {response.response_time_ms:.0f}ms")
        logger.info(f"Content Type: {response.content_type}")
        logger.info(f"Impersonate Used: {response.impersonate_used}")
        logger.info(f"Content Length: {len(response.content)} bytes")

        # Parse and show some response data
        if response.is_json:
            data = response.json()
            logger.info(f"User-Agent: {data.get('headers', {}).get('User-Agent', 'N/A')[:80]}...")

        stats = client.get_stats()
        logger.info(f"Client Stats: {stats}")

    logger.info("TEST 1: PASSED\n")


async def test_fingerprint_rotation():
    """Test fingerprint rotation."""
    logger.info("=" * 60)
    logger.info("TEST 2: Fingerprint Rotation")
    logger.info("=" * 60)

    config = ConfigLoader.default()

    async with ChimeraClient(config=config) as client:
        # Make first request
        logger.info("First request with initial fingerprint...")
        response1 = await client.get("https://httpbin.org/headers")
        fp1 = response1.impersonate_used
        logger.info(f"Fingerprint 1: {fp1}")

        # Rotate fingerprint
        await client.rotate_fingerprint()

        # Make second request
        logger.info("Second request after rotation...")
        response2 = await client.get("https://httpbin.org/headers")
        fp2 = response2.impersonate_used
        logger.info(f"Fingerprint 2: {fp2}")

        logger.info(f"Fingerprint changed: {fp1 != fp2}")

    logger.info("TEST 2: PASSED\n")


async def test_proxy_rotator():
    """Test the ProxyRotator."""
    logger.info("=" * 60)
    logger.info("TEST 3: Proxy Rotator")
    logger.info("=" * 60)

    # Create rotator with mock proxies
    proxies = [
        "http://proxy1.example.com:8080",
        "http://proxy2.example.com:8080",
        "http://proxy3.example.com:8080",
    ]

    rotator = ProxyRotator(
        proxies=proxies,
        strategy="sticky_session",
        sticky_ttl_seconds=300,
    )

    logger.info(f"Proxy count: {rotator.proxy_count}")
    logger.info(f"Healthy count: {rotator.healthy_count}")

    # Test sticky session
    session_id = "test-user-123"

    proxy1 = rotator.get_proxy(session_id=session_id)
    proxy2 = rotator.get_proxy(session_id=session_id)

    logger.info(f"First call proxy: {proxy1}")
    logger.info(f"Second call proxy: {proxy2}")
    logger.info(f"Same proxy (sticky): {proxy1 == proxy2}")

    # Test failure handling
    rotator.mark_failed(proxy1, is_banned=True)
    logger.info(f"Marked {proxy1} as banned")

    proxy3 = rotator.get_proxy(session_id="different-session")
    logger.info(f"New session gets: {proxy3}")
    logger.info(f"Banned proxy avoided: {proxy3 != proxy1}")

    stats = rotator.get_stats()
    logger.info(f"Rotator stats: {stats}")

    logger.info("TEST 3: PASSED\n")


async def test_swarm_execution():
    """Test concurrent swarm execution."""
    logger.info("=" * 60)
    logger.info("TEST 4: Swarm Execution")
    logger.info("=" * 60)

    # Test URLs - using httpbin endpoints
    urls = [
        "https://httpbin.org/get",
        "https://httpbin.org/headers",
        "https://httpbin.org/user-agent",
        "https://httpbin.org/ip",
        "https://httpbin.org/uuid",
    ]

    config = ConfigLoader.default()
    swarm_config = SwarmConfig(
        max_concurrency=3,
        timeout_per_request=30.0,
    )

    def progress(completed: int, total: int):
        logger.info(f"Progress: {completed}/{total}")

    swarm_config.progress_callback = progress

    logger.info(f"Starting swarm with {len(urls)} URLs, max_concurrency=3")

    results = await run_chimera_swarm(
        urls=urls,
        config=config,
        swarm_config=swarm_config,
    )

    logger.info(f"Total URLs: {results.total_urls}")
    logger.info(f"Successful: {results.successful}")
    logger.info(f"Failed: {results.failed}")
    logger.info(f"Success Rate: {results.success_rate:.1%}")
    logger.info(f"Total Time: {results.total_time_ms:.0f}ms")
    logger.info(f"Avg Response Time: {results.avg_response_time_ms:.0f}ms")

    if results.errors:
        logger.warning(f"Errors: {results.errors}")

    if results.challenges_detected:
        logger.warning(f"Challenges: {results.challenges_detected}")

    logger.info("TEST 4: PASSED\n")


async def test_config_loading():
    """Test configuration loading."""
    logger.info("=" * 60)
    logger.info("TEST 5: Configuration Loading")
    logger.info("=" * 60)

    # Load from default file
    logger.info("Loading from default Data Bank file...")
    config = ConfigLoader.from_default_file()

    logger.info(f"Project ID: {config.project_id}")
    logger.info(f"Version: {config.version}")
    logger.info(f"Default Impersonate: {config.fingerprint_profile.impersonate}")
    logger.info(f"Impersonate Pool: {config.fingerprint_profile.impersonate_pool}")
    logger.info(f"Max Concurrency: {config.network_policy.max_concurrency}")
    logger.info(f"Timeout (total): {config.network_policy.request_timeout.total}s")
    logger.info(f"Retry Max: {config.network_policy.retry_strategy.max_retries}")
    logger.info(f"Session Backend: {config.session_management.storage_backend}")

    # Test merging
    logger.info("\nTesting config merge...")
    merged = ConfigLoader.merge(
        config,
        {
            "network_policy": {"max_concurrency": 100},
            "fingerprint_profile": {"impersonate": "edge101"},
        },
    )
    logger.info(f"Merged Max Concurrency: {merged.network_policy.max_concurrency}")
    logger.info(f"Merged Impersonate: {merged.fingerprint_profile.impersonate}")

    logger.info("TEST 5: PASSED\n")


async def test_error_handling():
    """Test error handling for invalid domains."""
    logger.info("=" * 60)
    logger.info("TEST 6: Error Handling")
    logger.info("=" * 60)

    config = ConfigLoader.default()

    async with ChimeraClient(config=config) as client:
        # Test DNS error
        logger.info("Testing DNS error handling...")
        try:
            await client.get("https://this-domain-definitely-does-not-exist-12345.com")
            logger.error("Should have raised an error!")
        except Exception as e:
            logger.info(f"Caught expected error: {type(e).__name__}: {e}")

        # Test timeout (using a very short timeout)
        logger.info("\nTesting timeout handling...")
        try:
            await client.get("https://httpbin.org/delay/10", timeout=1.0)
            logger.error("Should have timed out!")
        except Exception as e:
            logger.info(f"Caught expected error: {type(e).__name__}: {e}")

    logger.info("TEST 6: PASSED\n")


async def test_state_store():
    """Test the state store (in-memory mode)."""
    logger.info("=" * 60)
    logger.info("TEST 7: State Store (In-Memory)")
    logger.info("=" * 60)

    from app.services.titan.tiers.chimera import CookieData, SessionData

    store = RedisStateStore(redis_client=None)  # Use in-memory

    session_id = "test-session-001"

    # Test cookie storage
    cookies = [
        CookieData(name="session", value="abc123", domain="example.com"),
        CookieData(name="token", value="xyz789", domain="example.com"),
    ]

    logger.info("Saving cookies...")
    await store.save_cookies(session_id, cookies)

    logger.info("Loading cookies...")
    loaded = await store.load_cookies(session_id)
    logger.info(f"Loaded {len(loaded)} cookies")

    for cookie in loaded:
        logger.info(f"  {cookie.name}={cookie.value[:10]}...")

    # Test session storage
    session_data = SessionData(
        session_id=session_id,
        user_agent="Mozilla/5.0 Test Agent",
        impersonate_profile="chrome120",
        cookies=cookies,
        request_count=42,
    )

    logger.info("\nSaving session...")
    await store.save_session(session_id, session_data)

    logger.info("Loading session...")
    loaded_session = await store.load_session(session_id)

    if loaded_session:
        logger.info(f"Session ID: {loaded_session.session_id}")
        logger.info(f"Request Count: {loaded_session.request_count}")
        logger.info(f"Impersonate: {loaded_session.impersonate_profile}")

    # Cleanup
    await store.delete_session(session_id)
    logger.info("\nSession deleted")

    logger.info("TEST 7: PASSED\n")


async def run_all_tests():
    """Run all tests."""
    logger.info("\n" + "=" * 60)
    logger.info("PROJECT CHIMERA v4.5 - Test Suite")
    logger.info("=" * 60 + "\n")

    tests = [
        ("Single Request", test_single_request),
        ("Fingerprint Rotation", test_fingerprint_rotation),
        ("Proxy Rotator", test_proxy_rotator),
        ("Swarm Execution", test_swarm_execution),
        ("Config Loading", test_config_loading),
        ("Error Handling", test_error_handling),
        ("State Store", test_state_store),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            await test_func()
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
