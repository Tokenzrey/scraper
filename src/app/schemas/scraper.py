from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ScrapeStrategy(str, Enum):
    """Scraping strategy to use for fetching content."""

    AUTO = "auto"  # Try REQUEST first, fallback to BROWSER on block
    REQUEST = "request"  # curl_cffi only (fast, lightweight)
    BROWSER = "browser"  # Botasaurus/Selenium (heavy, JS rendering)


class ScrapeResultStatus(str, Enum):
    """Status of a completed scrape operation."""

    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"


class ScrapeOptions(BaseModel):
    """Optional configuration for a scrape task."""

    model_config = ConfigDict(extra="forbid")

    proxy_url: Annotated[
        str | None,
        Field(
            default=None,
            description="Proxy URL (http://user:pass@host:port)",
            examples=["http://user:pass@proxy.example.com:8080"],
        ),
    ]
    cookies: Annotated[
        dict[str, str] | None,
        Field(
            default=None,
            description="Cookies to include in request",
            examples=[{"session_id": "abc123", "auth_token": "xyz789"}],
        ),
    ]
    headers: Annotated[
        dict[str, str] | None,
        Field(
            default=None,
            description="Additional headers to include",
            examples=[{"X-Custom-Header": "value", "Accept-Language": "en-US"}],
        ),
    ]
    block_images: Annotated[
        bool,
        Field(
            default=True,
            description="Block image loading in BROWSER mode for faster execution",
        ),
    ]
    wait_selector: Annotated[
        str | None,
        Field(
            default=None,
            description="CSS selector to wait for in BROWSER mode before capturing content",
            examples=["#main-content", ".product-list", "[data-loaded='true']"],
        ),
    ]
    wait_timeout: Annotated[
        int,
        Field(
            default=10,
            ge=1,
            le=60,
            description="Maximum seconds to wait for selector in BROWSER mode",
        ),
    ]
    javascript_enabled: Annotated[
        bool,
        Field(
            default=True,
            description="Enable JavaScript execution in BROWSER mode",
        ),
    ]
    # New 3-tier system options
    profile_id: Annotated[
        str | None,
        Field(
            default=None,
            description="TinyProfile ID for session persistence across requests (Tier 2/3)",
            examples=["user_session_123", "site_profile_abc"],
        ),
    ]
    use_google_get: Annotated[
        bool,
        Field(
            default=True,
            description="Use google_get() in Tier 3 for maximum Cloudflare bypass",
        ),
    ]


class ScrapeTaskCreate(BaseModel):
    """Request body for creating a new scrape task."""

    model_config = ConfigDict(extra="forbid")

    url: Annotated[
        HttpUrl,
        Field(
            description="Target URL to scrape",
            examples=["https://example.com/page", "https://api.example.com/data.json"],
        ),
    ]
    strategy: Annotated[
        ScrapeStrategy,
        Field(
            default=ScrapeStrategy.AUTO,
            description=(
                "Scraping strategy: AUTO (try request, fallback to browser), " "REQUEST (fast), BROWSER (JS rendering)"
            ),
        ),
    ]
    options: Annotated[
        ScrapeOptions | None,
        Field(
            default=None,
            description="Optional scrape configuration (proxy, cookies, headers, etc.)",
        ),
    ]


class ScrapeTaskResponse(BaseModel):
    """Response when a scrape task is successfully queued."""

    job_id: Annotated[
        str,
        Field(description="Unique identifier for the queued task"),
    ]
    status: Annotated[
        str,
        Field(default="queued", description="Current status of the task"),
    ]


class ScrapeResult(BaseModel):
    """Result of a completed scrape task."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    status: Annotated[
        ScrapeResultStatus,
        Field(description="Outcome status of the scrape operation"),
    ]
    content: Annotated[
        str | None,
        Field(
            default=None,
            description="Raw HTML or JSON content fetched from the target URL",
        ),
    ]
    content_type: Annotated[
        str | None,
        Field(
            default=None,
            description="Content-Type header from the response",
            examples=["text/html; charset=utf-8", "application/json"],
        ),
    ]
    strategy_used: Annotated[
        ScrapeStrategy,
        Field(description="The actual strategy that was used to fetch the content"),
    ]
    execution_time_ms: Annotated[
        int,
        Field(description="Total execution time in milliseconds"),
    ]
    http_status_code: Annotated[
        int | None,
        Field(
            default=None,
            description="HTTP status code from the target server",
        ),
    ]
    error: Annotated[
        str | None,
        Field(
            default=None,
            description="Error message if the scrape failed",
        ),
    ]
    fallback_used: Annotated[
        bool,
        Field(
            default=False,
            description="True if REQUEST mode failed and BROWSER mode was used as fallback",
        ),
    ]
    url: Annotated[
        str,
        Field(description="The URL that was scraped"),
    ]
    # New 3-tier system info
    tier_used: Annotated[
        int | None,
        Field(
            default=None,
            description="Which tier succeeded (1=curl_cffi, 2=browser+request, 3=full_browser)",
        ),
    ]
    response_size_bytes: Annotated[
        int | None,
        Field(
            default=None,
            description="Size of the response content in bytes",
        ),
    ]


class ScrapeTaskInfo(BaseModel):
    """Information about a scrape task's current state."""

    model_config = ConfigDict(use_enum_values=True)

    job_id: Annotated[
        str,
        Field(description="Unique identifier for the task"),
    ]
    status: Annotated[
        str,
        Field(description="Current job status (queued, in_progress, complete, failed)"),
    ]
    result: Annotated[
        ScrapeResult | None,
        Field(
            default=None,
            description="Scrape result if the task is complete",
        ),
    ]
    enqueue_time: Annotated[
        str | None,
        Field(
            default=None,
            description="ISO timestamp when the task was enqueued",
        ),
    ]
    start_time: Annotated[
        str | None,
        Field(
            default=None,
            description="ISO timestamp when the task started processing",
        ),
    ]
    finish_time: Annotated[
        str | None,
        Field(
            default=None,
            description="ISO timestamp when the task finished",
        ),
    ]
