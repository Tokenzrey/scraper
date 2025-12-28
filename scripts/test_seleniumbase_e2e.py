"""
End-to-end test script for Tier 5 SeleniumBase Executor.

Tests:
1. Basic fetch with UC Mode + CDP Mode
2. CAPTCHA solving capability
3. Cloudflare bypass
4. Error handling and classification

Usage:
    python scripts/test_seleniumbase_e2e.py
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def test_tier5_seleniumbase():
    """Test Tier 5 SeleniumBase executor."""
    from app.core.config import Settings
    from app.services.titan.tiers import Tier5SeleniumBaseExecutor, TierLevel

    print("=" * 60)
    print("TIER 5 SELENIUMBASE E2E TEST")
    print("=" * 60)

    # Create settings
    settings = Settings()

    # Create executor
    executor = Tier5SeleniumBaseExecutor(settings)
    print(f"\n✅ Executor created: {executor.TIER_NAME}")
    print(f"   Tier Level: {executor.TIER_LEVEL}")
    print(f"   Typical Overhead: {executor.TYPICAL_OVERHEAD_KB} KB")
    print(f"   Typical Time: {executor.TYPICAL_TIME_MS} ms")
    print(f"   Mode: {executor.config.mode}")
    print(f"   UC Mode: {executor.config.uc_mode.enabled}")
    print(f"   CDP Mode: {executor.config.cdp_mode.enabled}")
    print(f"   CAPTCHA Auto-Solve: {executor.config.captcha.auto_solve}")

    try:
        # Test 1: Simple fetch with CDP Mode
        print("\n" + "-" * 40)
        print("TEST 1: Simple fetch with CDP Mode (httpbin.org)")
        print("-" * 40)

        result = await executor.execute("https://httpbin.org/html")

        print(f"Success: {result.success}")
        print(f"Status Code: {result.status_code}")
        print(f"Content Length: {len(result.content or '')} chars")
        print(f"Execution Time: {result.execution_time_ms:.2f} ms")
        print(f"Tier Used: {result.tier_used}")
        print(f"Challenge Detected: {result.detected_challenge}")
        print(f"CDP Mode Used: {result.metadata.get('cdp_mode')}")
        print(f"CAPTCHA Solved: {result.metadata.get('captcha_solved')}")

        if result.content:
            print(f"Content Preview: {result.content[:200]}...")

        # Test 2: Cloudflare protected site with CAPTCHA solving
        print("\n" + "-" * 40)
        print("TEST 2: Cloudflare + CAPTCHA site (nowsecure.nl)")
        print("-" * 40)

        cf_result = await executor.execute("https://nowsecure.nl/")

        print(f"Success: {cf_result.success}")
        print(f"Status Code: {cf_result.status_code}")
        print(f"Content Length: {len(cf_result.content or '')} chars")
        print(f"Execution Time: {cf_result.execution_time_ms:.2f} ms")
        print(f"Challenge Detected: {cf_result.detected_challenge}")
        print(f"CAPTCHA Solved: {cf_result.metadata.get('captcha_solved')}")
        print(f"Final URL: {cf_result.metadata.get('final_url')}")

        # Test 3: GitLab (known Cloudflare protected)
        print("\n" + "-" * 40)
        print("TEST 3: GitLab sign-in page (Cloudflare Turnstile)")
        print("-" * 40)

        gitlab_result = await executor.execute("https://gitlab.com/users/sign_in")

        print(f"Success: {gitlab_result.success}")
        print(f"Status Code: {gitlab_result.status_code}")
        print(f"Content Length: {len(gitlab_result.content or '')} chars")
        print(f"Execution Time: {gitlab_result.execution_time_ms:.2f} ms")
        print(f"CAPTCHA Solved: {gitlab_result.metadata.get('captcha_solved')}")
        print(f"Page Title: {gitlab_result.metadata.get('page_title')}")

        # Test 4: Error handling (invalid domain)
        print("\n" + "-" * 40)
        print("TEST 4: Error handling (invalid domain)")
        print("-" * 40)

        error_result = await executor.execute(
            "https://this-domain-does-not-exist-12345.com/"
        )

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


async def test_cdp_client_directly():
    """Test CDPClient directly."""
    from app.services.titan.tiers.seleniumbase import CDPClient

    print("\n" + "=" * 60)
    print("CDP CLIENT DIRECT TEST")
    print("=" * 60)

    async with CDPClient() as client:
        print("\n✅ CDPClient initialized")

        # Fetch a page
        result = await client.fetch("https://httpbin.org/user-agent")

        print(f"URL: {result.url}")
        print(f"Title: {result.title}")
        print(f"CDP Mode Used: {result.cdp_mode_used}")
        print(f"Content Preview: {result.html[:500]}")

        # Test with CAPTCHA solving
        print("\nTesting CAPTCHA solve capability...")
        captcha_result = await client.fetch_with_captcha_solve(
            "https://httpbin.org/html"
        )
        print(f"CAPTCHA Solved: {captcha_result.captcha_solved}")


async def test_pure_cdp_mode():
    """Test Pure CDP Mode (no WebDriver)."""
    print("\n" + "=" * 60)
    print("PURE CDP MODE TEST")
    print("=" * 60)

    try:
        from seleniumbase import sb_cdp

        print("Testing Pure CDP Mode...")
        url = "https://httpbin.org/html"
        sb = sb_cdp.Chrome(url, incognito=True)
        print(f"Page loaded: {url}")
        print(f"Title: {sb.get_title()}")
        sb.driver.stop()
        print("✅ Pure CDP Mode works!")
    except ImportError:
        print("⚠️ Pure CDP Mode requires seleniumbase>=4.x")
    except Exception as e:
        print(f"❌ Pure CDP Mode error: {e}")


if __name__ == "__main__":
    print("Starting Tier 5 SeleniumBase tests...\n")

    try:
        asyncio.run(test_tier5_seleniumbase())
    except ImportError as e:
        print(f"\n⚠️  Import error: {e}")
        print("Make sure seleniumbase is installed: pip install seleniumbase")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
