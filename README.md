<h1 align="center">PROJECT CHIMERA - 7-Tier Intelligent Scraping Engine</h1>

<p align="center">
  <i><b>Enterprise-grade web scraping platform</b> with automatic escalation, CAPTCHA solving, and Human-in-the-Loop fallback.</i>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/Redis-DC382D?logo=redis&logoColor=fff&style=for-the-badge" alt="Redis">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
</p>

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [7-Tier Scraping System](#7-tier-scraping-system)
- [Requirements](#requirements)
- [Installation](#installation)
  - [Prerequisites (WSL Ubuntu)](#prerequisites-wsl-ubuntu)
  - [Setup dengan uv](#setup-dengan-uv)
  - [Instalasi Tier-Specific](#instalasi-tier-specific-opsional)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [API Reference](#api-reference)
- [Database Models](#database-models)
- [Background Jobs](#background-jobs)
- [CAPTCHA Resolver](#captcha-resolver)
- [Deployment](#deployment)
- [Testing](#testing)
- [Test Scripts](#test-scripts)
- [Troubleshooting](#troubleshooting)

---

## Overview

PROJECT CHIMERA adalah platform web scraping enterprise yang menggabungkan 7 tingkat (tier) teknologi scraping dengan eskalasi otomatis. Sistem ini dirancang untuk menangani berbagai level proteksi anti-bot, dari website sederhana hingga yang dilindungi Cloudflare, CAPTCHA, dan deteksi biometrik.

### Key Highlights

- **7-Tier Escalation**: Dari curl_cffi hingga Human-in-the-Loop
- **Automatic Challenge Detection**: Deteksi Cloudflare, CAPTCHA, rate limit
- **Golden Ticket System**: Harvesting credentials untuk reuse
- **Real-time Streaming**: WebSocket untuk HITL browser streaming
- **Session Persistence**: TinyProfile < 1KB per session
- **Enterprise Ready**: Rate limiting, authentication, admin panel

---

## Features

### Core Features

| Feature                | Description                                                          |
| ---------------------- | -------------------------------------------------------------------- |
| **7-Tier Scraper**     | Intelligent escalation dari request ringan hingga human intervention |
| **JWT Authentication** | Access + refresh token dengan cookie-based refresh                   |
| **Rate Limiting**      | Per-tier dan per-path rate limits                                    |
| **Background Jobs**    | ARQ worker untuk async scraping tasks                                |
| **Redis Caching**      | Server-side caching dengan TTL                                       |
| **Admin Panel**        | CRUDAdmin untuk manajemen data                                       |
| **WebSocket Events**   | Real-time notifications untuk CAPTCHA events                         |
| **Health Checks**      | `/health` dan `/ready` endpoints                                     |

### Scraping Capabilities

| Capability         | Technology                                |
| ------------------ | ----------------------------------------- |
| TLS Fingerprinting | curl_cffi dengan browser impersonation    |
| Browser Automation | Botasaurus, Nodriver, SeleniumBase        |
| Stealth Mode       | Camoufox (Firefox modified), DrissionPage |
| CAPTCHA Solving    | Auto-solve + manual HITL fallback         |
| Session Harvesting | Golden Ticket extraction dan reuse        |
| Cross-iframe       | DrissionPage native support               |
| Shadow DOM         | DrissionPage shadow-root handling         |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           PROJECT CHIMERA                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │   FastAPI    │    │    Redis     │    │  PostgreSQL  │              │
│  │   (Web)      │◄──►│   (Cache)    │◄──►│    (DB)      │              │
│  └──────┬───────┘    └──────┬───────┘    └──────────────┘              │
│         │                   │                                           │
│         │                   │                                           │
│         ▼                   ▼                                           │
│  ┌─────────────────────────────────────────────────────────────┐       │
│  │                    ARQ WORKER                                │       │
│  │  ┌─────────────────────────────────────────────────────┐    │       │
│  │  │              TITAN ORCHESTRATOR                      │    │       │
│  │  │                                                      │    │       │
│  │  │   Tier 1 ──► Tier 2 ──► Tier 3 ──► Tier 4 ──►       │    │       │
│  │  │   curl      browser    full       Camoufox          │    │       │
│  │  │                                                      │    │       │
│  │  │   ──► Tier 5 ──► Tier 6 ──► Tier 7                  │    │       │
│  │  │       UC+CDP    DrissionPage  HITL                   │    │       │
│  │  └─────────────────────────────────────────────────────┘    │       │
│  └─────────────────────────────────────────────────────────────┘       │
│                                                                         │
│  ┌──────────────┐    ┌──────────────┐                                  │
│  │  Admin Panel │    │  WebSocket   │                                  │
│  │  /admin      │    │  /ws/captcha │                                  │
│  └──────────────┘    └──────────────┘                                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
project-root/
├── docker/
│   └── worker/
│       ├── Dockerfile          # Worker dengan XVFB + Chromium
│       └── start.sh            # XVFB startup script
├── docker-compose.yml          # Main orchestration
├── Dockerfile                  # Web app container
├── pyproject.toml              # Dependencies (uv)
├── src/
│   ├── .env                    # Environment config
│   ├── app/
│   │   ├── main.py             # FastAPI entry point
│   │   ├── admin/              # CRUDAdmin setup
│   │   ├── api/
│   │   │   ├── dependencies.py # Auth, rate limit deps
│   │   │   └── v1/             # API v1 endpoints
│   │   │       ├── health.py
│   │   │       ├── login.py
│   │   │       ├── users.py
│   │   │       ├── scraper.py  # Titan scrape endpoints
│   │   │       ├── captcha.py  # CAPTCHA resolver
│   │   │       └── ws.py       # WebSocket
│   │   ├── core/
│   │   │   ├── config.py       # Pydantic settings
│   │   │   ├── security.py     # JWT & hashing
│   │   │   ├── db/             # SQLAlchemy setup
│   │   │   ├── utils/          # Cache, queue, rate limit
│   │   │   └── worker/         # ARQ settings
│   │   ├── crud/               # FastCRUD operations
│   │   ├── models/             # SQLAlchemy models
│   │   ├── schemas/            # Pydantic schemas
│   │   └── services/
│   │       ├── titan/          # 7-tier scraping engine
│   │       │   ├── orchestrator.py
│   │       │   └── tiers/
│   │       │       ├── base.py
│   │       │       ├── tier1_request.py
│   │       │       ├── tier2_browser_request.py
│   │       │       ├── tier3_full_browser.py
│   │       │       ├── chimera/
│   │       │       ├── botasaurus/
│   │       │       ├── nodriver/
│   │       │       ├── scrapling/
│   │       │       ├── seleniumbase/
│   │       │       ├── drissionpage/
│   │       │       └── hitl/
│   │       └── captcha/        # CAPTCHA service
│   └── migrations/             # Alembic migrations
├── scripts/                    # Utility scripts
└── tests/                      # Test suite
```

---

## 7-Tier Scraping System

### Tier Overview

| Tier  | Name            | Technology         | Time   | Stealth   | Memory | Use Case           |
| ----- | --------------- | ------------------ | ------ | --------- | ------ | ------------------ |
| 1     | Request         | curl_cffi + TLS    | ~50ms  | Medium    | 50KB   | APIs, simple sites |
| 1-alt | Chimera         | Advanced TLS       | ~100ms | High      | 100KB  | Bot detection      |
| 2     | Browser+Request | Botasaurus hybrid  | ~500ms | High      | 50KB   | Initial bypass     |
| 2-alt | Botasaurus      | Auto-escalation    | ~1s    | High      | 100KB  | Auto fallback      |
| 3     | Full Browser    | google_get() + JS  | ~2s    | Very High | 2MB    | JS rendering       |
| 3-alt | Nodriver        | Async CDP          | ~2s    | Very High | 500KB  | cf_verify()        |
| 4     | Scrapling       | Camoufox stealth   | ~3s    | Very High | 500KB  | OS fingerprint     |
| 5     | SeleniumBase    | UC + CDP + CAPTCHA | ~5s    | Maximum   | 800KB  | Auto CAPTCHA       |
| 6     | DrissionPage    | No webdriver       | ~2s    | Very High | 400KB  | iframe/shadow      |
| 7     | HITL            | Human-in-the-Loop  | Manual | Golden    | 500KB  | Final resort       |

### Escalation Flow

```
Request ──fail──► Browser+Request ──fail──► Full Browser ──fail──►
Scrapling ──fail──► SeleniumBase ──fail──► DrissionPage ──fail──►
HITL ──human solves──► Golden Ticket ──stored──► Tier 1 reuses ✓
```

### Golden Ticket System

Ketika human menyelesaikan challenge di Tier 7:

1. **Harvest**: Extract cookies (`cf_clearance`, session tokens)
2. **Store**: Simpan ke Redis dengan TTL (default: 1 jam)
3. **Reuse**: Tier 1 menggunakan credentials untuk ribuan request

```python
# Golden Ticket structure
{
    "domain": "example.com",
    "cookies": [{"name": "cf_clearance", "value": "..."}],
    "headers": {"user-agent": "..."},
    "user_agent": "Mozilla/5.0...",
    "ttl_seconds": 3600
}
```

---

## Requirements

### System Requirements

| Component | Minimum             | Recommended      |
| --------- | ------------------- | ---------------- |
| OS        | WSL2 Ubuntu / Linux | Ubuntu 22.04 LTS |
| Python    | 3.11+               | 3.11.9           |
| Memory    | 4GB                 | 8GB+             |
| Storage   | 10GB                | 20GB+            |
| Docker    | 24.0+               | Latest           |

### Software Dependencies

```bash
# Core
- Python 3.11+
- PostgreSQL 13+
- Redis 7+
- Docker & Docker Compose

# Browser (untuk Worker)
- Chromium/Chrome
- XVFB (X Virtual Framebuffer)
```

---

## Installation

### Prerequisites (WSL Ubuntu)

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install essential tools
sudo apt install -y curl git build-essential

# Install Python 3.11 (jika belum ada)
sudo apt install -y python3.11 python3.11-venv python3.11-dev

# Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

# Verify uv installation
uv --version
```

### Clone Repository

```bash
# Clone project
git clone https://github.com/your-username/project-chimera.git
cd project-chimera
```

### Setup dengan uv

```bash
# Create virtual environment dan install ALL dependencies (termasuk semua tier)
uv sync

# Activate virtual environment (opsional, uv run otomatis menggunakan venv)
source .venv/bin/activate

# Atau di Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

### Instalasi Tier-Specific (Opsional)

Jika Anda hanya membutuhkan tier tertentu, gunakan optional dependencies:

```bash
# Hanya Tier 1 (curl_cffi + botasaurus request)
uv pip install -e ".[tier1]"

# Tier 1 + Tier 3 (Nodriver)
uv pip install -e ".[tier1,tier3]"

# Tier 4 (Scrapling + Camoufox)
uv pip install -e ".[tier4]"

# Tier 5 (SeleniumBase UC Mode)
uv pip install -e ".[tier5]"

# Tier 6 + Tier 7 (DrissionPage + HITL)
uv pip install -e ".[tier6,tier7]"

# Semua tier sekaligus
uv pip install -e ".[all-tiers]"

# Development dependencies
uv pip install -e ".[dev]"

# Semua (development + all tiers)
uv pip install -e ".[dev,all-tiers]"
```

### Dependencies per Tier

| Tier | Package                              | Instalasi                      |
| ---- | ------------------------------------ | ------------------------------ |
| 1    | `curl-cffi`, `botasaurus`            | `uv pip install -e ".[tier1]"` |
| 2    | `botasaurus`, `botasaurus-driver`    | `uv pip install -e ".[tier2]"` |
| 3    | `nodriver`, `opencv-python`          | `uv pip install -e ".[tier3]"` |
| 4    | `scrapling[all]` (includes Camoufox) | `uv pip install -e ".[tier4]"` |
| 5    | `seleniumbase`                       | `uv pip install -e ".[tier5]"` |
| 6    | `DrissionPage`                       | `uv pip install -e ".[tier6]"` |
| 7    | `DrissionPage`, `websockets`         | `uv pip install -e ".[tier7]"` |

### Docker Installation (Jika belum ada)

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Install Docker Compose plugin
sudo apt install docker-compose-plugin

# Verify
docker --version
docker compose version
```

---

## Configuration

### Environment Variables

Buat file `src/.env` dari template:

```bash
cp src/.env.example src/.env
# atau buat manual
nano src/.env
```

### Complete .env Configuration

```ini
# ============================================
# APPLICATION SETTINGS
# ============================================
APP_NAME="PROJECT CHIMERA"
APP_DESCRIPTION="7-Tier Intelligent Scraping Engine"
APP_VERSION="1.0.0"
CONTACT_NAME="Your Name"
CONTACT_EMAIL="your.email@example.com"
LICENSE_NAME="MIT"

# Environment: local | staging | production
# - local: API docs enabled, debug mode
# - staging: API docs enabled, production-like
# - production: API docs disabled, optimized
ENVIRONMENT="local"

# ============================================
# DATABASE (PostgreSQL)
# ============================================
POSTGRES_USER="postgres"
POSTGRES_PASSWORD="your_secure_password_here"
POSTGRES_SERVER="db"           # 'db' untuk Docker, 'localhost' untuk local
POSTGRES_PORT=5432
POSTGRES_DB="chimera"

# ============================================
# SECURITY
# ============================================
# Generate dengan: openssl rand -hex 32
SECRET_KEY="your_64_character_hex_secret_key_here_generate_with_openssl"
ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

# ============================================
# ADMIN BOOTSTRAP
# ============================================
ADMIN_NAME="Admin"
ADMIN_EMAIL="admin@example.com"
ADMIN_USERNAME="admin"
ADMIN_PASSWORD="YourSecureAdminPassword123!"

# ============================================
# REDIS
# ============================================
REDIS_CACHE_HOST="redis"       # 'redis' untuk Docker, 'localhost' untuk local
REDIS_CACHE_PORT=6379
REDIS_QUEUE_HOST="redis"
REDIS_QUEUE_PORT=6379
REDIS_RATE_LIMIT_HOST="redis"
REDIS_RATE_LIMIT_PORT=6379

# ============================================
# RATE LIMITING
# ============================================
DEFAULT_RATE_LIMIT_LIMIT=1000  # requests per period
DEFAULT_RATE_LIMIT_PERIOD=3600 # seconds (1 hour)

# ============================================
# CORS
# ============================================
# Untuk development
CORS_ORIGINS='["*"]'
# Untuk production (ganti dengan domain Anda)
# CORS_ORIGINS='["https://yourdomain.com", "https://app.yourdomain.com"]'
CORS_METHODS='["*"]'
CORS_HEADERS='["*"]'

# ============================================
# CRUD ADMIN PANEL
# ============================================
CRUD_ADMIN_ENABLED=true
CRUD_ADMIN_MOUNT_PATH="/admin"
SESSION_SECURE_COOKIES=false   # true untuk production dengan HTTPS

# ============================================
# TITAN SCRAPER (7-TIER ENGINE)
# ============================================
# Timeouts
TITAN_REQUEST_TIMEOUT=90       # Tier 1 timeout (seconds)
TITAN_BROWSER_TIMEOUT=120      # Tier 2-7 timeout (seconds)
TITAN_MAX_RETRIES=3

# Strategy: auto | request | browser
TITAN_DEFAULT_STRATEGY="auto"

# Start/Max Tier: tier1 | tier2 | tier3
TITAN_START_TIER="tier1"
TITAN_MAX_TIER="tier3"

# Browser Settings
TITAN_HEADLESS=false           # false = MORE stealthy (requires XVFB)
TITAN_BLOCK_IMAGES=true        # Reduce bandwidth
TITAN_USE_GOOGLE_GET=true      # Tier 3 Cloudflare bypass
TITAN_HUMAN_MODE=true          # Realistic mouse/keyboard

# Proxy (opsional)
# TITAN_PROXY_URL="http://user:pass@proxy.example.com:8080"

# Profile Persistence
TITAN_PROFILE_DIR="/app/titan-profiles"
TITAN_ENABLE_PROFILES=true

# Chrome Paths (untuk Docker worker)
TITAN_CHROME_BIN="/usr/bin/chromium"
TITAN_CHROMEDRIVER_PATH="/usr/bin/chromedriver"

# ============================================
# CAPTCHA RESOLVER
# ============================================
CAPTCHA_SESSION_TTL=900        # 15 minutes
CAPTCHA_SESSION_MAX_TTL=3600   # 1 hour max
CAPTCHA_TASK_TIMEOUT=600       # 10 minutes untuk solve
CAPTCHA_TASK_LOCK_TTL=1800     # 30 minutes lock
CAPTCHA_DEFAULT_PRIORITY=5     # 1-10, higher = more urgent
CAPTCHA_PREVIEW_ENABLED=true
CAPTCHA_PREVIEW_DIR="/app/captcha-previews"
CAPTCHA_WORKER_WAIT_TIMEOUT=900

# ============================================
# FIRST TIER (Bootstrap)
# ============================================
TIER_NAME="free"
```

### Generate Secret Key

```bash
# Generate secure secret key
openssl rand -hex 32
```

---

## Running the Application

### Option 1: Docker Compose (Recommended)

```bash
# Build dan start semua services
docker compose up --build

# Atau run di background
docker compose up -d --build

# Lihat logs
docker compose logs -f

# Lihat logs specific service
docker compose logs -f web
docker compose logs -f worker
```

### Option 2: Local Development (tanpa Docker)

#### Start PostgreSQL & Redis

```bash
# Menggunakan Docker untuk database saja
docker compose up -d db redis

# Atau install native
sudo apt install postgresql redis-server
sudo systemctl start postgresql redis-server
```

#### Run FastAPI App

```bash
cd project-chimera

# Pastikan .env sudah dikonfigurasi untuk localhost
# POSTGRES_SERVER="localhost"
# REDIS_CACHE_HOST="localhost"

# Run migrations
cd src && uv run alembic upgrade head && cd ..

# Run FastAPI dengan hot reload
uv run uvicorn src.app.main:app --reload --host 0.0.0.0 --port 8000
```

#### Run ARQ Worker (Terminal terpisah)

```bash
# Terminal baru
cd project-chimera

# Untuk scraping dengan browser, perlu XVFB
sudo apt install xvfb chromium-browser chromium-chromedriver

# Start XVFB
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99

# Run worker
uv run arq src.app.core.worker.settings.WorkerSettings
```

### Bootstrap Data

```bash
# Create superuser (setelah app running)
docker compose run --rm create_superuser

# Atau manual
uv run python -m src.scripts.create_first_superuser
```

### Access Points

| Service      | URL                          | Description      |
| ------------ | ---------------------------- | ---------------- |
| API          | http://localhost:8000        | Main API         |
| API Docs     | http://localhost:8000/docs   | Swagger UI       |
| ReDoc        | http://localhost:8000/redoc  | Alternative docs |
| Admin Panel  | http://localhost:8000/admin  | CRUDAdmin        |
| Health Check | http://localhost:8000/health | Health status    |

---

## API Reference

### Authentication

#### Login

```bash
# Get access token
curl -X POST "http://localhost:8000/api/v1/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=YourSecureAdminPassword123!"
```

Response:

```json
{
	"access_token": "eyJhbGciOiJIUzI1NiIs...",
	"token_type": "bearer"
}
```

#### Using Token

```bash
# Authenticated request
curl -X GET "http://localhost:8000/api/v1/user/me/" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

### Scraper Endpoints

#### Create Scrape Task

```bash
curl -X POST "http://localhost:8000/api/v1/scrape" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "strategy": "auto",
    "options": {
      "block_images": true,
      "wait_selector": null,
      "javascript_enabled": true
    }
  }'
```

Response:

```json
{
	"job_id": "abc123",
	"status": "queued",
	"url": "https://example.com",
	"enqueue_time": "2024-01-15T10:30:00Z"
}
```

#### Get Scrape Result

```bash
curl -X GET "http://localhost:8000/api/v1/scrape/abc123"
```

Response:

```json
{
	"job_id": "abc123",
	"status": "complete",
	"result": {
		"status": "success",
		"content": "<!DOCTYPE html>...",
		"content_type": "text/html",
		"strategy_used": "request",
		"tier_used": 1,
		"execution_time_ms": 150,
		"http_status_code": 200,
		"fallback_used": false,
		"response_size_bytes": 45678
	}
}
```

### Users

#### Create User

```bash
curl -X POST "http://localhost:8000/api/v1/user" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "John Doe",
    "username": "johndoe",
    "email": "john@example.com",
    "password": "SecurePassword123!"
  }'
```

#### Get Current User

```bash
curl -X GET "http://localhost:8000/api/v1/user/me/" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Rate Limits

#### Get User's Rate Limits

```bash
curl -X GET "http://localhost:8000/api/v1/user/johndoe/rate_limits" \
  -H "Authorization: Bearer SUPERUSER_TOKEN"
```

### CAPTCHA Tasks

#### List Pending CAPTCHA Tasks

```bash
curl -X GET "http://localhost:8000/api/v1/captcha/tasks/pending"
```

#### Submit CAPTCHA Solution

```bash
curl -X POST "http://localhost:8000/api/v1/captcha/tasks/{task_uuid}/solve" \
  -H "Content-Type: application/json" \
  -d '{
    "solution_type": "cookies",
    "solution_payload": {
      "cf_clearance": "cookie_value_here",
      "user_agent": "Mozilla/5.0..."
    }
  }'
```

---

## Database Models

### User

```python
User:
  - id: int (PK)
  - name: str(30)
  - username: str(20) - unique
  - email: str(50) - unique
  - hashed_password: str
  - uuid: UUID - unique
  - tier_id: int (FK -> Tier)
  - is_superuser: bool
  - created_at: datetime
  - updated_at: datetime
  - deleted_at: datetime
  - is_deleted: bool
```

### Tier

```python
Tier:
  - id: int (PK)
  - name: str - unique
  - created_at: datetime
  - updated_at: datetime
```

### RateLimit

```python
RateLimit:
  - id: int (PK)
  - tier_id: int (FK -> Tier)
  - name: str - unique
  - path: str (e.g., "/api/v1/scrape")
  - limit: int (requests per period)
  - period: int (seconds)
```

### CaptchaTask

```python
CaptchaTask:
  - id: int (PK)
  - uuid: UUID - unique
  - url: str(2048)
  - domain: str(255)
  - status: enum (pending|in_progress|solving|solved|expired|failed|unsolvable)
  - priority: int (1-10)
  - assigned_to: str (operator ID)
  - challenge_type: str (turnstile|recaptcha|hcaptcha)
  - solver_result: JSONB
  - cookies_json: text
  - request_id: str (original scrape ID)
  - created_at: datetime
  - solved_at: datetime
  - expires_at: datetime
```

### Migrations

```bash
# Create new migration
cd src && uv run alembic revision --autogenerate -m "description"

# Apply migrations
uv run alembic upgrade head

# Rollback
uv run alembic downgrade -1
```

---

## Background Jobs

### ARQ Worker

Worker menjalankan task scraping secara async:

```python
# src/app/core/worker/functions.py
async def scrape_task(ctx, url: str, options: dict) -> dict:
    """Execute scrape with Titan orchestrator."""
    orchestrator = TitanOrchestrator(settings)
    result = await orchestrator.execute(url, options)
    return result.to_dict()
```

### Job Status

| Status        | Description        |
| ------------- | ------------------ |
| `queued`      | Task dalam antrian |
| `in_progress` | Sedang diproses    |
| `complete`    | Selesai sukses     |
| `failed`      | Gagal dengan error |

### Monitoring

```bash
# Lihat job queue di Redis
docker compose exec redis redis-cli

# Di Redis CLI
> KEYS arq:*
> LRANGE arq:queue 0 -1
```

---

## CAPTCHA Resolver

### Flow

```
1. Tier 3 detects challenge
   └─► Creates CaptchaTask (status: pending)

2. Admin Dashboard polls /captcha/tasks/pending
   └─► Shows list of tasks to solve

3. Admin opens solver iframe
   └─► GET /internal/solver-frame/{task_uuid}
   └─► Proxied page with challenge

4. Admin solves challenge manually
   └─► System captures cookies OR
   └─► Admin submits solution manually

5. POST /captcha/tasks/{uuid}/solve
   └─► Solution stored in DB
   └─► Cached in Redis (captcha:session:{domain})
   └─► Pub/sub notification to worker

6. Worker resumes with cached session
   └─► Completes original scrape request
```

### WebSocket Events

```javascript
// Connect to CAPTCHA events
const ws = new WebSocket("ws://localhost:8000/ws/captcha");

ws.onmessage = (event) => {
	const data = JSON.parse(event.data);
	switch (data.event) {
		case "task_created":
			// New CAPTCHA task available
			break;
		case "solved":
			// Task was solved
			break;
		case "expired":
			// Task expired
			break;
	}
};
```

---

## Deployment

### Production Checklist

- [ ] Generate new `SECRET_KEY`
- [ ] Change all default passwords
- [ ] Set `ENVIRONMENT=production`
- [ ] Configure CORS for specific domains
- [ ] Enable `SESSION_SECURE_COOKIES=true`
- [ ] Setup HTTPS (nginx/traefik)
- [ ] Configure proper logging
- [ ] Setup monitoring (Prometheus)
- [ ] Configure backup untuk PostgreSQL
- [ ] Setup Redis persistence

### Docker Production

```bash
# Build production images
docker compose -f docker-compose.prod.yml build

# Start dengan restart policy
docker compose -f docker-compose.prod.yml up -d

# Scale workers
docker compose -f docker-compose.prod.yml up -d --scale worker=3
```

### Production docker-compose.yml

```yaml
version: "3.8"

services:
  web:
    build: .
    restart: always
    environment:
      - ENVIRONMENT=production
    depends_on:
      - db
      - redis
    networks:
      - internal
      - web

  worker:
    build:
      context: .
      dockerfile: docker/worker/Dockerfile
    restart: always
    shm_size: "4gb"
    deploy:
      replicas: 3
    depends_on:
      - redis
    networks:
      - internal

  db:
    image: postgres:13-alpine
    restart: always
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - internal

  redis:
    image: redis:7-alpine
    restart: always
    volumes:
      - redis-data:/data
    networks:
      - internal

  nginx:
    image: nginx:alpine
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./certs:/etc/nginx/certs
    depends_on:
      - web
    networks:
      - web

networks:
  internal:
  web:

volumes:
  postgres-data:
  redis-data:
```

### Nginx Configuration

```nginx
# nginx.conf
upstream fastapi {
    server web:8000;
}

server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;

    location / {
        proxy_pass http://fastapi;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws {
        proxy_pass http://fastapi;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## Testing

### Run All Tests

```bash
# Dengan Docker
docker compose run --rm pytest

# Local
uv run pytest tests/ -v
```

### Run Specific Tests

```bash
# Test specific file
uv run pytest tests/test_user.py -v

# Test specific function
uv run pytest tests/test_user.py::test_create_user -v

# Test dengan coverage
uv run pytest tests/ --cov=src/app --cov-report=html
```

### Test Scraper Manually

```bash
# Test Tier 1 (curl_cffi)
uv run python -c "
import asyncio
from src.app.services.titan.tiers import Tier1RequestExecutor
from src.app.core.config import settings

async def test():
    executor = Tier1RequestExecutor(settings)
    result = await executor.execute('https://httpbin.org/get')
    print(f'Success: {result.success}')
    print(f'Status: {result.status_code}')
    await executor.cleanup()

asyncio.run(test())
"
```

---

## Test Scripts

Project ini menyediakan beberapa script untuk testing individual tier. Scripts berada di folder `scripts/`.

### Prerequisites untuk Test Scripts

```bash
# Pastikan dependencies sudah terinstall
uv sync

# Untuk browser-based tests (Tier 3-7), install browser dependencies
# Ubuntu/WSL:
sudo apt install -y chromium-browser chromium-chromedriver xvfb

# Start XVFB untuk headless browser (jika diperlukan)
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
```

### Daftar Test Scripts

| Script                     | Tier   | Deskripsi                                |
| -------------------------- | ------ | ---------------------------------------- |
| `test_chimera.py`          | Tier 1 | Test curl_cffi dengan TLS fingerprinting |
| `test_botasaurus.py`       | Tier 2 | Test Botasaurus @request + @browser      |
| `test_nodriver.py`         | Tier 3 | Test Nodriver async CDP browser          |
| `test_scrapling_e2e.py`    | Tier 4 | Test Scrapling + Camoufox stealth        |
| `test_seleniumbase_e2e.py` | Tier 5 | Test SeleniumBase UC Mode + CAPTCHA      |
| `test_titan_e2e.py`        | All    | Full orchestrator end-to-end test        |

### Menjalankan Test Scripts

#### Test Tier 1 - Chimera (curl_cffi)

```bash
# Langsung dengan uv run
uv run python scripts/test_chimera.py

# Atau dengan aktivasi venv terlebih dahulu
source .venv/bin/activate  # Linux/WSL
python scripts/test_chimera.py
```

**Output yang diharapkan:**

```
============================================================
TEST 1: Single Request
============================================================
Session ID: abc12345...
Making request to httpbin.org...
Status Code: 200
Success: True
Response Time: 150ms
```

#### Test Tier 2 - Botasaurus

```bash
uv run python scripts/test_botasaurus.py
```

**Output yang diharapkan:**

```
============================================================
TEST 1: Configuration Loading
============================================================
Version: 2.0.0
Browser Headless: True
Browser Block Images: True
Tiny Profile: True
```

#### Test Tier 3 - Nodriver

```bash
# Memerlukan XVFB untuk headless mode
export DISPLAY=:99
uv run python scripts/test_nodriver.py
```

**Output yang diharapkan:**

```
============================================================
TEST 1: Configuration Loading
============================================================
Version: 3.0.0
Browser Headless: False
CF Verify Enabled: True
```

#### Test Tier 4 - Scrapling (Camoufox)

```bash
# Scrapling menggunakan Camoufox (Firefox modified)
uv run python scripts/test_scrapling_e2e.py
```

**Output yang diharapkan:**

```
============================================================
TIER 4 SCRAPLING E2E TEST
============================================================
✅ Executor created: scrapling
   Tier Level: 4
   Typical Overhead: 500 KB
TEST 1: Simple fetch (httpbin.org)
Success: True
Status Code: 200
```

#### Test Tier 5 - SeleniumBase (UC Mode + CDP Mode)

```bash
# SeleniumBase memerlukan Chrome/Chromium
uv run python scripts/test_seleniumbase_e2e.py
```

**Output yang diharapkan:**

```
============================================================
TIER 5 SELENIUMBASE E2E TEST
============================================================
✅ Executor created: seleniumbase
   Tier Level: 5
   UC Mode: True
   CDP Mode: True
   CAPTCHA Auto-Solve: True
TEST 1: Simple fetch with CDP Mode (httpbin.org)
Success: True
CDP Mode Used: True
```

#### Test Full Orchestrator - Titan E2E

Script ini memerlukan API server berjalan:

```bash
# Terminal 1: Start services
docker compose up -d

# Terminal 2: Run E2E tests
uv run python scripts/test_titan_e2e.py --all

# Test kategori tertentu
uv run python scripts/test_titan_e2e.py --category basic
uv run python scripts/test_titan_e2e.py --category cloudflare

# Test URL spesifik
uv run python scripts/test_titan_e2e.py --url https://example.com --strategy auto

# Verbose mode
uv run python scripts/test_titan_e2e.py --all --verbose
```

### Troubleshooting Test Scripts

#### Error: ModuleNotFoundError

```bash
# Pastikan berada di root directory project
cd /path/to/project-chimera

# Reinstall dependencies
uv sync

# Atau install tier spesifik
uv pip install -e ".[tier5]"  # untuk SeleniumBase
```

#### Error: Display not found (Tier 3-5)

```bash
# Start XVFB
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99

# Atau gunakan headless mode dalam konfigurasi
```

#### Error: Chrome/Chromium not found

```bash
# Install Chromium
sudo apt install -y chromium-browser chromium-chromedriver

# Atau untuk SeleniumBase (auto-download driver)
uv run python -c "from seleniumbase import SB; SB(uc=True)"
```

#### Error: Camoufox not found (Tier 4)

```bash
# Scrapling menginstall Camoufox secara otomatis
# Jika gagal, coba manual:
uv pip install scrapling[all] --force-reinstall
```

---

## Development

### Pre-commit Hooks

Ensure pre-commit hooks are installed and running to maintain code quality.

#### Install Pre-commit

```bash
uv tool install pre-commit
# or
pip install pre-commit
```

#### Run Hooks Manually

Run these commands to check for violations without committing:

```bash
# Run all hooks
pre-commit run --all-files

# Basic Checks
pre-commit run end-of-file-fixer --all-files
pre-commit run trailing-whitespace --all-files
pre-commit run check-yaml --all-files
pre-commit run check-docstring-first --all-files
pre-commit run check-executables-have-shebangs --all-files
pre-commit run check-case-conflict --all-files
pre-commit run check-added-large-files --all-files
pre-commit run detect-private-key --all-files
pre-commit run check-merge-conflict --all-files

# PyUpgrade
pre-commit run pyupgrade --all-files

# Formatters & Linters (Ensure these are uncommented in .pre-commit-config.yaml)
pre-commit run docformatter --all-files
pre-commit run yesqa --all-files
pre-commit run ruff --all-files
pre-commit run ruff-format --all-files
pre-commit run blacken-docs --all-files
pre-commit run mdformat --all-files

# Tests
pre-commit run unit_test --hook-stage manual --all-files
```

---

## Troubleshooting

### Common Issues

#### 1. Database Connection Failed

```
Error: connection refused to database
```

Solution:

```bash
# Check if PostgreSQL is running
docker compose ps db

# Check logs
docker compose logs db

# Verify connection string in .env
POSTGRES_SERVER="db"  # untuk Docker
POSTGRES_SERVER="localhost"  # untuk local
```

#### 2. Redis Connection Failed

```
Error: Redis connection refused
```

Solution:

```bash
# Check Redis status
docker compose ps redis

# Test connection
docker compose exec redis redis-cli ping
# Should return: PONG
```

#### 3. Worker Browser Crash

```
Error: Chrome failed to start
```

Solution:

```bash
# Check XVFB is running
docker compose exec worker ps aux | grep Xvfb

# Check shared memory
docker compose exec worker df -h /dev/shm
# Should be at least 2GB

# Restart worker
docker compose restart worker
```

#### 4. Permission Denied

```
Error: Permission denied: '/app/titan-profiles'
```

Solution:

```bash
# Fix ownership
docker compose exec worker chown -R app:app /app/titan-profiles

# Atau rebuild
docker compose down -v
docker compose up --build
```

#### 5. Import Error for Tiers

```
Error: ModuleNotFoundError: No module named 'DrissionPage'
```

Solution:

```bash
# Install tier spesifik
uv pip install -e ".[tier6]"

# Atau install semua tier
uv pip install -e ".[all-tiers]"

# Atau rebuild Docker
docker compose build --no-cache worker
```

#### 6. Import Error for Specific Tier Packages

```
Error: ModuleNotFoundError: No module named 'nodriver'
Error: ModuleNotFoundError: No module named 'scrapling'
Error: ModuleNotFoundError: No module named 'seleniumbase'
```

Solution:

```bash
# Install tier yang diperlukan
uv pip install -e ".[tier3]"    # nodriver
uv pip install -e ".[tier4]"    # scrapling
uv pip install -e ".[tier5]"    # seleniumbase

# Atau install semua sekaligus
uv pip install -e ".[all-tiers]"
```

#### 7. Scrapling/Camoufox Installation Issues

```
Error: Failed to install camoufox
```

Solution:

```bash
# Install dengan semua extras
uv pip install "scrapling[all]>=0.2.9"

# Jika masih gagal, coba install dependencies secara terpisah
uv pip install playwright
playwright install firefox

# Lalu install scrapling
uv pip install scrapling
```

#### 8. SeleniumBase Driver Issues

```
Error: ChromeDriver executable needs to be in PATH
```

Solution:

```bash
# SeleniumBase biasanya auto-download driver
# Jika gagal, jalankan ini:
uv run python -c "from seleniumbase import SB; SB(uc=True)"

# Atau install chromedriver manual
sudo apt install chromium-chromedriver

# Untuk Windows, download dari:
# https://chromedriver.chromium.org/downloads
```

### Logs

```bash
# All logs
docker compose logs -f

# Specific service
docker compose logs -f web
docker compose logs -f worker

# Last 100 lines
docker compose logs --tail=100 worker
```

### Reset Everything

```bash
# Stop all containers
docker compose down

# Remove volumes (CAUTION: deletes data)
docker compose down -v

# Remove images
docker compose down --rmi all

# Fresh start
docker compose up --build
```

---

## License

MIT License - See [LICENSE](LICENSE.md)

---

## Contact

- **Author**: Your Name
- **Email**: your.email@example.com
- **Repository**: https://github.com/your-username/project-chimera

---

<p align="center">
  Built with FastAPI, PostgreSQL, Redis, and lots of caffeine.
</p>
