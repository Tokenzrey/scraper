import os
from enum import Enum

from pydantic import SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    APP_NAME: str = "FastAPI app"
    APP_DESCRIPTION: str | None = None
    APP_VERSION: str | None = None
    LICENSE_NAME: str | None = None
    CONTACT_NAME: str | None = None
    CONTACT_EMAIL: str | None = None


class CryptSettings(BaseSettings):
    SECRET_KEY: SecretStr = SecretStr("secret-key")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7


class DatabaseSettings(BaseSettings):
    pass


class SQLiteSettings(DatabaseSettings):
    SQLITE_URI: str = "./sql_app.db"
    SQLITE_SYNC_PREFIX: str = "sqlite:///"
    SQLITE_ASYNC_PREFIX: str = "sqlite+aiosqlite:///"


class MySQLSettings(DatabaseSettings):
    MYSQL_USER: str = "username"
    MYSQL_PASSWORD: str = "password"
    MYSQL_SERVER: str = "localhost"
    MYSQL_PORT: int = 5432
    MYSQL_DB: str = "dbname"
    MYSQL_SYNC_PREFIX: str = "mysql://"
    MYSQL_ASYNC_PREFIX: str = "mysql+aiomysql://"
    MYSQL_URL: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def MYSQL_URI(self) -> str:
        credentials = f"{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
        location = f"{self.MYSQL_SERVER}:{self.MYSQL_PORT}/{self.MYSQL_DB}"
        return f"{credentials}@{location}"


class PostgresSettings(DatabaseSettings):
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "postgres"
    POSTGRES_SYNC_PREFIX: str = "postgresql://"
    POSTGRES_ASYNC_PREFIX: str = "postgresql+asyncpg://"
    POSTGRES_URL: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def POSTGRES_URI(self) -> str:
        credentials = f"{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
        location = f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        return f"{credentials}@{location}"


class FirstUserSettings(BaseSettings):
    ADMIN_NAME: str = "admin"
    ADMIN_EMAIL: str = "admin@admin.com"
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "!Ch4ng3Th1sP4ssW0rd!"


class TestSettings(BaseSettings):
    ...


class RedisCacheSettings(BaseSettings):
    REDIS_CACHE_HOST: str = "localhost"
    REDIS_CACHE_PORT: int = 6379

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_CACHE_URL(self) -> str:
        return f"redis://{self.REDIS_CACHE_HOST}:{self.REDIS_CACHE_PORT}"


class ClientSideCacheSettings(BaseSettings):
    CLIENT_CACHE_MAX_AGE: int = 60


class RedisQueueSettings(BaseSettings):
    REDIS_QUEUE_HOST: str = "localhost"
    REDIS_QUEUE_PORT: int = 6379


class RedisRateLimiterSettings(BaseSettings):
    REDIS_RATE_LIMIT_HOST: str = "localhost"
    REDIS_RATE_LIMIT_PORT: int = 6379

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_RATE_LIMIT_URL(self) -> str:
        return f"redis://{self.REDIS_RATE_LIMIT_HOST}:{self.REDIS_RATE_LIMIT_PORT}"


class DefaultRateLimitSettings(BaseSettings):
    DEFAULT_RATE_LIMIT_LIMIT: int = 10
    DEFAULT_RATE_LIMIT_PERIOD: int = 3600


class CRUDAdminSettings(BaseSettings):
    CRUD_ADMIN_ENABLED: bool = True
    CRUD_ADMIN_MOUNT_PATH: str = "/admin"

    CRUD_ADMIN_ALLOWED_IPS_LIST: list[str] | None = None
    CRUD_ADMIN_ALLOWED_NETWORKS_LIST: list[str] | None = None
    CRUD_ADMIN_MAX_SESSIONS: int = 10
    CRUD_ADMIN_SESSION_TIMEOUT: int = 1440
    SESSION_SECURE_COOKIES: bool = True

    CRUD_ADMIN_TRACK_EVENTS: bool = True
    CRUD_ADMIN_TRACK_SESSIONS: bool = True

    CRUD_ADMIN_REDIS_ENABLED: bool = False
    CRUD_ADMIN_REDIS_HOST: str = "localhost"
    CRUD_ADMIN_REDIS_PORT: int = 6379
    CRUD_ADMIN_REDIS_DB: int = 0
    CRUD_ADMIN_REDIS_PASSWORD: str | None = "None"
    CRUD_ADMIN_REDIS_SSL: bool = False


class EnvironmentOption(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class EnvironmentSettings(BaseSettings):
    ENVIRONMENT: EnvironmentOption = EnvironmentOption.LOCAL


class CORSSettings(BaseSettings):
    CORS_ORIGINS: list[str] = ["*"]
    CORS_METHODS: list[str] = ["*"]
    CORS_HEADERS: list[str] = ["*"]


class CaptchaSettings(BaseSettings):
    """Configuration for Manual CAPTCHA Resolver System.

    Redis Keys:
    - captcha:session:{domain} => Cached solver sessions (cookies, UA, proxy)
    - captcha:task:{id}:lock => Task lock for operator assignment
    - captcha:queue:pending => List of pending task IDs

    Pub/Sub:
    - captcha:events => Channel for real-time notifications
    """

    # ============================================
    # Session Cache Settings
    # ============================================
    # Default TTL for cached sessions (cf_clearance typically valid ~30 minutes)
    CAPTCHA_SESSION_TTL: int = 900  # 15 minutes (conservative)

    # Maximum TTL allowed for sessions (even if explicitly requested longer)
    CAPTCHA_SESSION_MAX_TTL: int = 3600  # 1 hour

    # ============================================
    # Task Settings
    # ============================================
    # Default time for operator to solve (after which task expires)
    CAPTCHA_TASK_TIMEOUT: int = 600  # 10 minutes

    # Lock timeout for operator assignment (auto-release if operator disconnects)
    CAPTCHA_TASK_LOCK_TTL: int = 1800  # 30 minutes

    # Default priority for new tasks (1-10, higher = more urgent)
    CAPTCHA_DEFAULT_PRIORITY: int = 5

    # ============================================
    # Redis Key Prefixes (configurable for namespacing)
    # ============================================
    CAPTCHA_REDIS_PREFIX: str = "captcha"
    CAPTCHA_SESSION_KEY_PREFIX: str = "captcha:session"
    CAPTCHA_TASK_LOCK_KEY_PREFIX: str = "captcha:task"
    CAPTCHA_QUEUE_KEY: str = "captcha:queue:pending"

    # ============================================
    # Pub/Sub Channel
    # ============================================
    CAPTCHA_EVENTS_CHANNEL: str = "captcha:events"

    # ============================================
    # Proxy Engine Settings
    # ============================================
    # Browser impersonation profile for curl_cffi
    CAPTCHA_PROXY_IMPERSONATE: str = "chrome124"

    # Timeout for proxy requests to target site
    CAPTCHA_PROXY_TIMEOUT: int = 30

    # ============================================
    # Preview/Thumbnail Settings
    # ============================================
    CAPTCHA_PREVIEW_DIR: str = "/app/captcha-previews"
    CAPTCHA_PREVIEW_ENABLED: bool = True

    # ============================================
    # Worker Integration
    # ============================================
    # How long worker waits for captcha solution before timeout
    CAPTCHA_WORKER_WAIT_TIMEOUT: int = 900  # 15 minutes


class TitanStrategyOption(str, Enum):
    """Default scraping strategy for Titan Worker."""

    AUTO = "auto"
    REQUEST = "request"
    BROWSER = "browser"


class TitanTierOption(str, Enum):
    """Starting tier for escalation."""

    TIER_1 = "tier1"  # curl_cffi
    TIER_2 = "tier2"  # Browser + driver.requests.get()
    TIER_3 = "tier3"  # Full browser


class TitanSettings(BaseSettings):
    """Configuration for Titan 3-Tier Scraping Engine.

    Tier System:
    - Tier 1: curl_cffi with TLS fingerprinting (fast, ~50KB)
    - Tier 2: Browser session + driver.requests.get() (stealth, ~50KB)
    - Tier 3: Full browser with google_get() (maximum stealth, ~2MB)
    """

    # ============================================
    # Timeout Settings (seconds)
    # ============================================
    TITAN_REQUEST_TIMEOUT: int = 90  # Tier 1 timeout (increased for slow sites/redirects)
    TITAN_BROWSER_TIMEOUT: int = 120  # Tier 2 & 3 timeout (for Cloudflare bypass)
    TITAN_MAX_RETRIES: int = 3  # Not currently used (escalation replaces retry)

    # ============================================
    # Tier Escalation Settings
    # ============================================
    # Default strategy determines behavior
    TITAN_DEFAULT_STRATEGY: TitanStrategyOption = TitanStrategyOption.AUTO

    # Starting tier (for AUTO strategy)
    TITAN_START_TIER: TitanTierOption = TitanTierOption.TIER_1

    # Maximum tier to escalate to (for AUTO strategy)
    TITAN_MAX_TIER: TitanTierOption = TitanTierOption.TIER_3

    # ============================================
    # Proxy Configuration
    # ============================================
    TITAN_PROXY_URL: str | None = None  # Format: http://user:pass@host:port

    # ============================================
    # Browser Settings (Tier 2 & 3)
    # ============================================
    # Headless=False is MORE stealthy (requires XVFB in Docker)
    TITAN_HEADLESS: bool = False

    # Block images to reduce bandwidth/time (Tier 2 always blocks)
    TITAN_BLOCK_IMAGES: bool = True

    # Use google_get() in Tier 3 for maximum Cloudflare bypass
    TITAN_USE_GOOGLE_GET: bool = True

    # Enable human mode in Tier 3 (realistic mouse/keyboard behavior)
    TITAN_HUMAN_MODE: bool = True

    # ============================================
    # Chrome Paths (set via environment in Docker)
    # ============================================
    TITAN_CHROME_BIN: str | None = None
    TITAN_CHROMEDRIVER_PATH: str | None = None

    # ============================================
    # TinyProfile Settings (Session Persistence)
    # ============================================
    # Directory for storing TinyProfiles (<1KB each)
    TITAN_PROFILE_DIR: str = "/app/titan-profiles"

    # Enable profile persistence across requests
    TITAN_ENABLE_PROFILES: bool = True

    # ============================================
    # User-Agent Configuration
    # ============================================
    # Custom User-Agent (None = let Botasaurus use UserAgent.HASHED)
    TITAN_USER_AGENT: str | None = None

    # Fallback User-Agent pool for Tier 1 (curl_cffi)
    TITAN_USER_AGENTS: list[str] = [
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.2 Safari/605.1.15"
        ),
        ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 " "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    ]

    # ============================================
    # Challenge Detection
    # ============================================
    # HTTP status codes that trigger escalation
    TITAN_BLOCKED_STATUS_CODES: list[int] = [403, 429, 503, 520, 521, 522, 523, 524]


class Settings(
    AppSettings,
    SQLiteSettings,
    PostgresSettings,
    CryptSettings,
    FirstUserSettings,
    TestSettings,
    RedisCacheSettings,
    ClientSideCacheSettings,
    RedisQueueSettings,
    RedisRateLimiterSettings,
    DefaultRateLimitSettings,
    CRUDAdminSettings,
    EnvironmentSettings,
    CORSSettings,
    TitanSettings,
    CaptchaSettings,
):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
