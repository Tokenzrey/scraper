def pytest_addoption(parser):
    """Register common CLI options so running `pytest <script> --all` won't fail.

    This makes pytest accept the script's command-line flags (best-effort).
    It does not execute the script's main automatically.
    """
    parser.addoption("--all", action="store_true", help="Run all tests / script flag")
    parser.addoption("--category", action="store", help="Test category (script flag)")
    parser.addoption("--url", action="store", help="Test url (script flag)")
    parser.addoption("--strategy", action="store", help="Strategy (script flag)")
    parser.addoption("--api-url", action="store", help="API base URL (script flag)")
    # Note: do NOT register `--verbose` here because pytest already defines it.
