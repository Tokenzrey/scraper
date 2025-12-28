# Captcha Resolver — Backend Design & Spec

Dokumen ini menjelaskan desain backend lengkap untuk Manual Captcha Resolver, termasuk API contracts, data model, caching, pub/sub, worker integration, dan security. Fokus: memungkinkan worker menangguhkan percobaan scraping sampai solusi CAPTCHA diterima dari operator, serta memastikan solusi dapat dipakai untuk bypass Cloudflare secara andal.

**Versi:** 2.0
**Penulis:** Tim Engineering
**Tanggal:** 2025-12-15
**Status:** ✅ IMPLEMENTED

---

## Ringkasan Arsitektur

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Titan Worker  │────▶│   FastAPI API   │◀────│  Operator UI    │
│                 │     │                 │     │  (Frontend)     │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         │              ┌────────┴────────┐              │
         │              │                 │              │
         ▼              ▼                 ▼              │
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│     Redis       │  │   PostgreSQL    │  │   WebSocket     │
│  Cache/PubSub   │  │   captcha_task  │  │   /ws/captcha   │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

- Komponen utama:
  - **API endpoints** (FastAPI) - `src/app/api/v1/captcha.py`
  - **Database model** `CaptchaTask` (Postgres) - `src/app/models/captcha.py`
  - **Redis cache & pub/sub** untuk notifikasi real-time - `src/app/services/captcha/`
  - **WebSocket** untuk update frontend - `src/app/api/v1/ws.py`
  - **Worker integration**: helper functions untuk Titan Worker - `src/app/services/captcha/worker_integration.py`

---

## Data Model

### Table: `captcha_task`

```python
# src/app/models/captcha.py

class CaptchaStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SOLVING = "solving"
    SOLVED = "solved"
    EXPIRED = "expired"
    FAILED = "failed"
    UNSOLVABLE = "unsolvable"

class CaptchaSolutionType(str, Enum):
    COOKIE = "cookie"
    TOKEN = "token"
    SESSION = "session"

class CaptchaTask(Base):
    __tablename__ = "captcha_task"

    # Primary fields
    id: Mapped[int]                           # Auto-increment ID
    uuid: Mapped[uuid.UUID]                   # Public UUID
    url: Mapped[str]                          # Target URL
    domain: Mapped[str]                       # Extracted domain
    status: Mapped[CaptchaStatus]             # Task status
    challenge_type: Mapped[str | None]        # cloudflare, turnstile, recaptcha
    error_message: Mapped[str | None]         # Error from scraper

    # Priority & Assignment
    priority: Mapped[int]                     # 1-10, higher = urgent
    assigned_to: Mapped[str | None]           # Operator ID
    attempts: Mapped[int]                     # Retry count

    # Solution data
    cf_clearance: Mapped[str | None]          # Cloudflare cookie
    solver_result: Mapped[dict | None]        # JSONB - full solution
    solver_expires_at: Mapped[datetime | None]
    solver_notes: Mapped[str | None]

    # Metadata
    preview_path: Mapped[str | None]          # Screenshot path
    proxy_url: Mapped[str | None]             # Proxy used
    user_agent: Mapped[str | None]            # UA used
    request_id: Mapped[str | None]            # Original request ID
    last_error: Mapped[str | None]            # Last error message
    metadata: Mapped[dict]                    # JSONB - additional data

    # Timestamps
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
```

### Migration

Migration file: `src/migrations/versions/a1b2c3d4e5f6_update_captcha_task_for_resolver.py`

- Menggunakan pattern idempotent (`IF NOT EXISTS`)
- Menambahkan enum values baru dengan safe check
- Index pada `priority`, `assigned_to`, dan composite `status_priority`

---

## API Endpoints

### Public Routes (`/api/v1/captcha/`)

| Method | Endpoint | Description | Request Body | Response |
|--------|----------|-------------|--------------|----------|
| POST | `/tasks` | Create CAPTCHA task | `CaptchaTaskCreate` | `CaptchaTaskResponse` |
| GET | `/tasks` | List tasks (paginated) | Query params | `CaptchaTaskListResponse` |
| GET | `/tasks/pending` | List pending tasks | Query params | `CaptchaTaskListResponse` |
| GET | `/tasks/{uuid}` | Get single task | - | `CaptchaTaskResponse` |
| POST | `/tasks/{uuid}/assign` | Assign to operator | `CaptchaTaskAssign` | `AssignResponse` |
| POST | `/tasks/{uuid}/solve` | Submit solution | `CaptchaSolutionSubmit` | `SolveResponse` |
| POST | `/tasks/{uuid}/mark-unsolvable` | Mark unsolvable | `CaptchaMarkUnsolvable` | `MarkUnsolvableResponse` |
| PATCH | `/tasks/{uuid}/status` | Update status | `{"status": "..."}` | `CaptchaTaskResponse` |
| GET | `/sessions/{domain}` | Get cached session | - | `SessionResponse` |
| GET | `/proxy/render/{uuid}` | Proxy render page | - | HTML |
| DELETE | `/expired` | Cleanup expired tasks | - | `CleanupResponse` |

### Internal Routes (`/internal/`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/solver-frame/{uuid}` | Proxied iframe for operator |

### WebSocket Routes

| Endpoint | Description |
|----------|-------------|
| `/ws/captcha` | All CAPTCHA events |
| `/ws/captcha/{domain}` | Domain-specific events |

### Request/Response Schemas

```python
# src/app/schemas/captcha.py

class CaptchaTaskCreate(BaseModel):
    url: str
    challenge_type: str | None = None
    error_message: str | None = None
    request_id: str | None = None
    priority: int = Field(default=5, ge=1, le=10)
    proxy_url: str | None = None
    user_agent: str | None = None
    metadata: dict = Field(default_factory=dict)

class CaptchaSolutionSubmit(BaseModel):
    type: CaptchaSolutionType
    payload: list[CookieItem] | dict | str
    user_agent: str | None = None
    expires_at: datetime | None = None
    notes: str | None = None

class CaptchaTaskAssign(BaseModel):
    operator_id: str
    lock_duration_seconds: int = Field(default=1800, ge=60, le=7200)
```

---

## Redis / Cache & Pub/Sub

### Configuration

```python
# src/app/core/config.py - CaptchaSettings

CAPTCHA_SESSION_TTL = 900              # 15 minutes
CAPTCHA_SESSION_MAX_TTL = 3600         # 1 hour max
CAPTCHA_TASK_TIMEOUT = 600             # 10 minutes
CAPTCHA_TASK_LOCK_TTL = 1800           # 30 minutes
CAPTCHA_DEFAULT_PRIORITY = 5
CAPTCHA_REDIS_PREFIX = "captcha"
CAPTCHA_SESSION_KEY_PREFIX = "captcha:session"
CAPTCHA_TASK_LOCK_KEY_PREFIX = "captcha:task"
CAPTCHA_QUEUE_KEY = "captcha:queue:pending"
CAPTCHA_EVENTS_CHANNEL = "captcha:events"
CAPTCHA_PROXY_IMPERSONATE = "chrome124"
CAPTCHA_PROXY_TIMEOUT = 30
CAPTCHA_WORKER_WAIT_TIMEOUT = 900      # 15 minutes
```

### Redis Keys

| Key Pattern | TTL | Description |
|-------------|-----|-------------|
| `captcha:session:{domain}` | 15m | Cached session (cookies, UA) |
| `captcha:task:{id}:lock` | 30m | Operator lock |
| `captcha:queue:pending` | - | Pending task queue |

### Pub/Sub Events

Channel: `captcha:events`

```python
class CaptchaEventType(str, Enum):
    TASK_CREATED = "task_created"
    TASK_ASSIGNED = "task_assigned"
    TASK_SOLVING = "task_solving"
    TASK_SOLVED = "task_solved"
    TASK_FAILED = "task_failed"
    TASK_UNSOLVABLE = "task_unsolvable"
    SESSION_CACHED = "session_cached"
    SESSION_EXPIRED = "session_expired"

# Event payload structure
{
    "type": "task_solved",
    "timestamp": "2025-12-15T10:30:00Z",
    "payload": {
        "task_id": "123",
        "uuid": "abc-123-def",
        "domain": "example.com",
        "has_session": true,
        "session_ttl": 900
    }
}
```

---

## Services

### CaptchaSessionService

```python
# src/app/services/captcha/session_service.py

class CaptchaSessionService:
    """Session caching with Redis + memory fallback."""

    async def get_session(domain: str) -> CaptchaSession | None
    async def store_session(domain, cookies, user_agent, ttl) -> CaptchaSession
    async def invalidate_session(domain: str) -> bool

class CaptchaSession:
    domain: str
    cookies: dict[str, str]
    user_agent: str | None
    proxy_url: str | None
    created_at: datetime
    expires_at: datetime

    def is_valid() -> bool
    def get_cf_clearance() -> str | None
    def to_dict() -> dict
    @classmethod
    def from_dict(data: dict) -> CaptchaSession
```

### CaptchaPubSubService

```python
# src/app/services/captcha/pubsub.py

class CaptchaPubSubService:
    """Redis pub/sub for real-time events."""

    async def publish_task_created(task_id, uuid, url, domain, priority)
    async def publish_assigned(task_id, uuid, domain, operator_id)
    async def publish_solved(task_id, uuid, domain, has_session, session_ttl)
    async def publish_unsolvable(task_id, uuid, domain, reason)
    async def subscribe(callback) -> None
    async def wait_for_solution(domain, timeout) -> bool
```

### CaptchaProxyService

```python
# src/app/services/captcha/proxy_engine.py

class CaptchaProxyService:
    """Proxied iframe rendering with curl_cffi."""

    async def stream_and_capture(url, proxy_url, user_agent) -> StreamResponse
    async def render_solver_frame(task: CaptchaTask) -> str
```

Features:
- TLS fingerprint impersonation (`chrome124`)
- Header stripping (`X-Frame-Options`, `Content-Security-Policy`)
- `Set-Cookie` interception untuk auto-capture

---

## Worker Integration

### Helper Functions

```python
# src/app/services/captcha/worker_integration.py

# Check for cached session before scraping
async def check_cached_session(url_or_domain, redis_client) -> CaptchaSession | None

# Create CAPTCHA task when blocked
async def create_captcha_task(url, challenge_type, error_message, ...) -> dict | None

# Wait for solution via pub/sub
async def wait_for_solution(domain, redis_client, timeout) -> CaptchaSession | None

# Combined: create task + wait
async def create_task_and_wait(url, redis_client, ...) -> CaptchaSession | None

# Inject session cookies into headers
def inject_session_cookies(headers, session) -> dict[str, str]

# Polling alternative (no pub/sub)
async def poll_for_session(domain, timeout, poll_interval) -> CaptchaSession | None
```

### Usage Example

```python
from src.app.services.captcha import (
    check_cached_session,
    create_task_and_wait,
    inject_session_cookies,
    execute_with_captcha_handling,
)

# Option 1: Manual integration
async def scrape_with_captcha(url: str, redis_client):
    domain = urlparse(url).netloc
    headers = {}

    # 1. Check cache first
    session = await check_cached_session(domain, redis_client)
    if session and session.is_valid():
        headers = inject_session_cookies(headers, session)

    # 2. Execute scraping
    result = await orchestrator.execute(url, headers=headers)

    # 3. Handle CAPTCHA if required
    if result.error_type == "captcha_required":
        session = await create_task_and_wait(
            url=url,
            redis_client=redis_client,
            challenge_type="cloudflare",
            error_message=result.error,
            priority=7,
            timeout=900,
        )

        if session:
            headers = inject_session_cookies(headers, session)
            result = await orchestrator.execute(url, headers=headers)

    return result

# Option 2: Automatic handling
async def scrape_auto(url: str, redis_client):
    result = await execute_with_captcha_handling(
        orchestrator=orchestrator,
        url=url,
        redis_client=redis_client,
        max_retries=2,
    )
    return result
```

---

## WebSocket Events

### Connection

```javascript
// Frontend connection
const ws = new WebSocket('ws://localhost:8000/ws/captcha');

// Or domain-specific
const ws = new WebSocket('ws://localhost:8000/ws/captcha/example.com');

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('Event:', data.type, data.payload);
};
```

### Event Types

| Event | Payload | Description |
|-------|---------|-------------|
| `task_created` | task_id, uuid, url, domain, priority | New task created |
| `task_assigned` | task_id, uuid, domain, operator_id | Task assigned |
| `task_solved` | task_id, uuid, domain, has_session, session_ttl | Solution submitted |
| `task_unsolvable` | task_id, uuid, domain, reason | Marked unsolvable |
| `session_cached` | domain, ttl | Session cached |

---

## Security Considerations

- ✅ Task assignment locking (HTTP 409 on conflict)
- ✅ Session TTL enforcement
- ✅ Domain extraction validation
- ⚠️ TODO: Role-based access control for operators
- ⚠️ TODO: Encrypted storage for `solver_result`
- ⚠️ TODO: Rate limiting per operator/domain
- ⚠️ TODO: Audit trail logging

---

## Testing

### Unit Tests

```bash
# Run all captcha tests
pytest tests/api/test_captcha.py -v
pytest tests/services/test_captcha_services.py -v
```

Test coverage:
- ✅ Task CRUD operations
- ✅ Task assignment & conflict handling
- ✅ Solution submission
- ✅ Session caching
- ✅ Pub/sub events
- ✅ Worker integration helpers

---

## File Structure

```
src/app/
├── api/v1/
│   ├── captcha.py              # API endpoints
│   └── ws.py                   # WebSocket endpoints
├── models/
│   └── captcha.py              # Database model
├── schemas/
│   └── captcha.py              # Pydantic schemas
├── services/
│   └── captcha/
│       ├── __init__.py         # Exports
│       ├── proxy_engine.py     # curl_cffi proxy
│       ├── pubsub.py           # Redis pub/sub
│       ├── session_service.py  # Session caching
│       └── worker_integration.py # Worker helpers
└── core/
    └── config.py               # CaptchaSettings

tests/
├── api/
│   └── test_captcha.py         # API tests
└── services/
    └── test_captcha_services.py # Service tests
```

---

## Environment Variables

```bash
# Required
CAPTCHA_SESSION_TTL=900
CAPTCHA_SESSION_MAX_TTL=3600
CAPTCHA_TASK_TIMEOUT=600
CAPTCHA_TASK_LOCK_TTL=1800
CAPTCHA_DEFAULT_PRIORITY=5
CAPTCHA_WORKER_WAIT_TIMEOUT=900

# Optional
CAPTCHA_PROXY_IMPERSONATE=chrome124
CAPTCHA_PROXY_TIMEOUT=30
CAPTCHA_PREVIEW_DIR=/app/captcha-previews
CAPTCHA_PREVIEW_ENABLED=true
```

---

## Deployment Checklist

- [ ] Run Alembic migration: `alembic upgrade head`
- [ ] Ensure Redis `notify-keyspace-events` enabled
- [ ] Configure CAPTCHA_* environment variables
- [ ] Verify curl_cffi installed (`pip install curl_cffi`)
- [ ] Set up preview directory with write permissions
- [ ] Configure CORS for WebSocket connections
- [ ] Set up monitoring for captcha:events channel

---

**Status:** Backend implementation complete. Ready for frontend integration.
