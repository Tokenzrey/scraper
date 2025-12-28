"""
End-to-end test script for Tier 4 Scrapling Executor.

Tests:
1. Basic fetch with StealthyFetcher
2. Cloudflare challenge handling
3. Error handling and classification

Usage:
    python scripts/test_scrapling_e2e.py
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def test_tier4_scrapling():
    """Test Tier 4 Scrapling executor."""
    from app.core.config import Settings
    from app.services.titan.tiers import Tier4ScraplingExecutor, TierLevel

    print("=" * 60)
    print("TIER 4 SCRAPLING E2E TEST")
    print("=" * 60)

    # Create settings
    settings = Settings()

    # Create executor
    executor = Tier4ScraplingExecutor(settings)
    print(f"\n✅ Executor created: {executor.TIER_NAME}")
    print(f"   Tier Level: {executor.TIER_LEVEL}")
    print(f"   Typical Overhead: {executor.TYPICAL_OVERHEAD_KB} KB")
    print(f"   Typical Time: {executor.TYPICAL_TIME_MS} ms")

    try:
        # Test 1: Simple fetch
        print("\n" + "-" * 40)
        print("TEST 1: Simple fetch (httpbin.org)")
        print("-" * 40)

        result = await executor.execute("https://httpbin.org/html")

        print(f"Success: {result.success}")
        print(f"Status Code: {result.status_code}")
        print(f"Content Length: {len(result.content or '')} chars")
        print(f"Execution Time: {result.execution_time_ms:.2f} ms")
        print(f"Tier Used: {result.tier_used}")
        print(f"Challenge Detected: {result.detected_challenge}")
        print(f"Should Escalate: {result.should_escalate}")

        if result.content:
            print(f"Content Preview: {result.content[:200]}...")

        # Test 2: Cloudflare protected site (optional)
        print("\n" + "-" * 40)
        print("TEST 2: Cloudflare protected site")
        print("-" * 40)

        # Using a known Cloudflare protected site
        cf_result = await executor.execute("https://nowsecure.nl/")

        print(f"Success: {cf_result.success}")
        print(f"Status Code: {cf_result.status_code}")
        print(f"Content Length: {len(cf_result.content or '')} chars")
        print(f"Execution Time: {cf_result.execution_time_ms:.2f} ms")
        print(f"Challenge Detected: {cf_result.detected_challenge}")
        print(f"Metadata: {cf_result.metadata}")

        # Test 3: Error handling (invalid domain)
        print("\n" + "-" * 40)
        print("TEST 3: Error handling (invalid domain)")
        print("-" * 40)

        error_result = await executor.execute("https://this-domain-does-not-exist-12345.com/")

        print(f"Success: {error_result.success}")
        print(f"Error Type: {error_result.error_type}")
        print(f"Error: {error_result.error}")
        print(f"Should Escalate: {error_result.should_escalate}")

    finally:
        # Cleanup
        await executor.cleanup()
        print("\n✅ Executor cleaned up")

    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED")
    print("=" * 60)


async def test_stealthy_client_directly():
    """Test StealthyClient directly."""
    from app.services.titan.tiers.scrapling import StealthyClient

    print("\n" + "=" * 60)
    print("STEALTHY CLIENT DIRECT TEST")
    print("=" * 60)

    async with StealthyClient() as client:
        print("\n✅ StealthyClient initialized")

        # Fetch a page
        result = await client.fetch("https://httpbin.org/user-agent")

        print(f"Status: {result.status_code}")
        print(f"URL: {result.url}")
        print(f"Content: {result.html[:500]}")


if __name__ == "__main__":
    print("Starting Tier 4 Scrapling tests...\n")

    try:
        asyncio.run(test_tier4_scrapling())
    except ImportError as e:
        print(f"\n⚠️  Import error: {e}")
        print("Make sure scrapling is installed: pip install scrapling[all]")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
