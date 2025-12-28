def pytest_addoption(parser):
    """Register common CLI options so running `pytest <script> --all` won't fail.

    This makes pytest accept the script's command-line flags (best-effort). It does not execute the script's main
    automatically.
    """

    # Helper to safely add options without causing conflicts if already registered
    def safe_addoption(*args, **kwargs):
        try:
            parser.addoption(*args, **kwargs)
        except ValueError:
            # Option already registered, skip
            pass

    safe_addoption("--all", action="store_true", help="Run all tests / script flag")
    safe_addoption("--category", action="store", help="Test category (script flag)")
    safe_addoption("--url", action="store", help="Test url (script flag)")
    safe_addoption("--strategy", action="store", help="Strategy (script flag)")
    safe_addoption("--api-url", action="store", help="API base URL (script flag)")
    # Note: do NOT register `--verbose` here because pytest already defines it.
