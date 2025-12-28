# Scraper Frontend Integration — Full Feature Spec

Dokumen ini menjelaskan desain frontend yang memungkinkan operator atau integrator untuk menggunakan seluruh fitur Titan Scraper dari UI: membuat job scrape dengan konfigurasi penuh, memantau status, melihat dan men-download hasil, mengelola proxies, user agents, scheduling, dan bekerja bersama sistem manual captcha resolver.

**Versi:** 1.1
**Penulis:** Tim Engineering
**Tanggal:** 2025-12-15
**Backend Status:** ✅ CAPTCHA Resolver Backend Implemented

---

**Ringkasan**

- Tujuan: sediakan UI yang lengkap untuk membuat, memonitor, mengonfigurasi, dan mendapatkan hasil scraping menggunakan Titan Engine.
- Target users: integrator (developer), operator (support), manual solvers (captcha operators).
- Integrasi penuh dengan backend API (create job, watch job, fetch results), Redis pub/sub (live updates), dan Captcha Resolver UI/flow.

---

**1. Pages (High-level)**

- `ScraperDashboardPage` (route: `/scraper`)

  - Gambaran umum: tombol `New Scrape`, quick stats, recent jobs, filters.
  - Card grid list dengan `JobCard` (status badge, strategy used, runtime, size of output).

- `CreateScrapePage` (modal/route: `/scraper/new`)

  - Form lengkap untuk konfigurasi scrape (URL, strategy, headers, cookies, proxy, retries, timeouts, wait selectors, block_images, follow_redirects, render_js, save_profile, schedule cron).
  - Advanced tab: TLS fingerprint selection, browser window size, use_google_get, enable human-like delays, driver options.

- `JobDetailPage` (route: `/scraper/jobs/:id`)

  - Shows timeline: queued → started → tier results (tier1, tier2, tier3) → final result.
  - Sections: Request config (read-only), Execution metadata, Raw response preview (HTML/text), JSON parsed output (if any), Headers & Cookies inspector, Screenshot gallery, Logs, Actions (re-run, clone, abort, open captcha solver).

- `ResultsExplorerPage` (route: `/scraper/results`)

  - Searchable, filterable list of past results; supports export (CSV/JSON), schema mapping, and dataset preview.

- `ProxyManagerPage` (route: `/settings/proxies`)

  - CRUD for proxy entries, bulk import, health-check ping, priority groups.

- `UserAgentsPage` (route: `/settings/user-agents`)

  - Manage UA presets and TLS fingerprint mappings.

- `CaptchaResolverLink` / `SolverRedirect`
  - For jobs that require manual solve: `JobDetailPage` shows `Open Solver` button that opens `Captcha Resolver` page for that task (integration with `docs/captcha_resolver_frontend.md`).

---

**2. Components & Responsibilities**

- `ScrapeForm` (used in `CreateScrapePage`)

  - Fields:
    - `url` (required)
    - `strategy` (auto|request|browser|full_browser)
    - `timeout_ms`, `max_retries`, `retry_backoff_ms`
    - `headers[]`, `cookies[]`
    - `use_proxy` + `proxy_id` or `proxy_pool` selection
    - `block_images` (boolean)
    - `follow_redirects` (boolean)
    - `wait_for_selector` (CSS selector) and `wait_timeout_ms`
    - `render_delay_ms` for Tier3
    - `save_profile_on_success` (boolean) — if true, store session/profile
    - `schedule` (cron expression) optional
  - Validation: URL parser, numeric bounds, strategy-specific constraints (e.g., `render_delay_ms` only for browser strategies)
  - Output: normalized job payload to `POST /api/v1/scrape`

- `AdvancedConfigPanel`

  - TLS fingerprint chooser, spoofing presets, additional curl options (SNI, ciphers), custom CA bundle upload

- `JobCard` / `JobList` / `JobGrid`

  - Preview info: final status, strategy used, elapsed time, size, first 200 chars of result, small screenshot thumbnail
  - Quick actions: view, rerun, clone, cancel

- `TierResultView`

  - For each tier (1/2/3) show: timestamp, raw response code, error_type, curl/bot logs, secondary validations, duration

- `ResponseViewer`

  - Tabs: `Rendered HTML`, `Raw HTML`, `Text`, `JSON` (if content-type application/json), `Headers`, `Cookies`, `Screenshots`
  - For HTML: syntax highlighting, find (Ctrl+F), allow copy of selected HTML block

- `ResultDownloadActions`

  - Download JSON, CSV (flattened), raw HTML, HAR (optional)

- `LiveTimeline` / `JobLogs`

  - Live-updating event log showing escalation path and decisions (e.g., "Tier1 detected cloudflare -> Escalate to Tier3")

- `ConfigQuickActions`
  - Clone job, generate a shareable job config (export to JSON), apply template

---

**3. Data Models (frontend)**

- `ScrapeJobCreate` payload (example):

```json
{
	"url": "https://example.com/",
	"strategy": "auto",
	"timeout_ms": 90000,
	"max_retries": 2,
	"block_images": true,
	"follow_redirects": true,
	"headers": [{ "name": "Accept-Language", "value": "en-US" }],
	"cookies": [{ "name": "foo", "value": "bar", "domain": "example.com" }],
	"proxy_id": "proxy-1",
	"wait_for_selector": "#content",
	"render_delay_ms": 1000,
	"save_profile_on_success": true
}
```

- `ScrapeJobResult` (simplified):

```json
{
	"job_id": "uuid",
	"status": "success", // success | failed | blocked | captcha_required | timeout
	"strategy_used": "tier3_full_browser",
	"duration_ms": 4210,
	"result_size_bytes": 52345,
	"outputs": {
		"html": "<html>...</html>",
		"text": "...",
		"json": null
	},
	"screenshots": ["/internal/screenshots/uuid/1.png"],
	"tier_results": [
		/* tier-by-tier details */
	]
}
```

---

**4. Hooks & Data Layer (React / TS)**

- `useCreateScrapeJob()`

  - Mutation hook: posts payload to `POST /api/v1/scrape`, returns `job_id`
  - Accepts onSuccess callback to redirect to `job detail`

- `useJobStatus(jobId)`

  - Polls `/api/v1/scrape/{jobId}` or subscribes to `/ws/scrape/{jobId}` for live updates
  - Returns `{ job, isLoading, error, refetch }`

- `useJobResults(jobId)`

  - Fetches `outputs` once job completes; supports progressive streaming for large outputs

- `useLiveJobs({filters})`

  - For `ScraperDashboardPage`, use web socket or SSE to receive `job.created` / `job.updated` events

- `useProxyList()` and `useUserAgents()`
  - CRUD hooks for settings pages

---

**5. API Integration & Contracts**

- Create job:

  - `POST /api/v1/scrape` → returns `{ job_id, status: queued }` or validation error

- Inspect job:

  - `GET /api/v1/scrape/{job_id}` → returns full job object including `tier_results` and `outputs` if available

- Stream job updates:

  - WebSocket `ws://host/ws/scrape/{job_id}` or server-sent events `/sse/scrape/{job_id}`
  - Events: `job.updated`, `tier.updated`, `captcha.required`, `job.completed`

- Cancel job:

  - `POST /api/v1/scrape/{job_id}/cancel`

- Re-run job (clone):

  - `POST /api/v1/scrape/{job_id}/requeue` → creates a new job with same config

- Get job output (download):
  - `GET /api/v1/scrape/{job_id}/output?format=json|csv|html|har`

Notes: Use JWT auth, role-based permissions (create/run jobs for developers; view jobs for operator roles; admin pages restricted).

---

**6. Captcha Integration UX** ✅ Backend Ready

- If job status `captcha_required` is returned, `JobDetailPage` shows prominent CTA `Open Solver` that opens the Captcha Resolver UI for that task.
- Workflow:

  1. Worker creates `captcha_task` in backend and returns job status `captcha_required` with metadata `{ task_id }`.
  2. Frontend shows `Open Solver` linking to `/captchas/{task_id}/solve` or opens modal.
  3. Operator solves and submits solution; backend publishes `captcha:solved:{task_id}` and worker resumes.
  4. Frontend subscribes to `captcha:events` to update job automatically when solved.

- Additional helpers: `InjectSolution` action in `JobDetailPage` allowing advanced users to paste cookies/header tokens manually for ad-hoc testing.

### Backend API Endpoints (Implemented)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/captcha/tasks` | Create CAPTCHA task |
| GET | `/api/v1/captcha/tasks` | List tasks (paginated, filterable) |
| GET | `/api/v1/captcha/tasks/pending` | List pending tasks |
| GET | `/api/v1/captcha/tasks/{uuid}` | Get single task |
| POST | `/api/v1/captcha/tasks/{uuid}/assign` | Assign to operator |
| POST | `/api/v1/captcha/tasks/{uuid}/solve` | Submit solution |
| POST | `/api/v1/captcha/tasks/{uuid}/mark-unsolvable` | Mark unsolvable |
| GET | `/api/v1/captcha/sessions/{domain}` | Get cached session |
| GET | `/api/v1/captcha/proxy/render/{uuid}` | Proxy render page |

### WebSocket Endpoints (Implemented)

| Endpoint | Description |
|----------|-------------|
| `/ws/captcha` | All CAPTCHA events |
| `/ws/captcha/{domain}` | Domain-specific events |

### Event Types

```typescript
type CaptchaEventType =
  | "task_created"
  | "task_assigned"
  | "task_solving"
  | "task_solved"
  | "task_failed"
  | "task_unsolvable"
  | "session_cached"
  | "session_expired";

interface CaptchaEvent {
  type: CaptchaEventType;
  timestamp: string;
  payload: {
    task_id: string;
    uuid: string;
    domain: string;
    // Additional fields vary by event type
  };
}
```

### Frontend WebSocket Integration Example

```typescript
// hooks/useCaptchaEvents.ts
export function useCaptchaEvents(domain?: string) {
  const [events, setEvents] = useState<CaptchaEvent[]>([]);

  useEffect(() => {
    const wsUrl = domain
      ? `ws://localhost:8000/ws/captcha/${domain}`
      : `ws://localhost:8000/ws/captcha`;

    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setEvents(prev => [...prev, data]);

      // Handle specific events
      if (data.type === 'task_solved') {
        // Refresh task list or update UI
      }
    };

    return () => ws.close();
  }, [domain]);

  return events;
}
```

---

**7. Advanced Features & Customizations**

- Templates: save `ScrapeForm` configs as templates for repeatable jobs.
- Bulk scheduling: upload CSV of URLs with per-row overrides (strategy, proxy group, priority).
- Test-run mode: run quick probe with `dry_run: true` to get headers/status only.
- Schema extractor: allow user to define simple extraction rules (CSS selectors or JSONPath) and see extracted data in `ResultsExplorer`.
- Webhook integration: configure per-template webhook to post results to third-party services when job completes.

---

**8. Error Handling & Observability**

- Show clear error reason codes on `JobDetailPage`: `dns_error`, `connection_refused`, `timeout`, `blocked`, `captcha_required`, `server_error`.
- Provide actionable tips per error: e.g., for `dns_error` suggest verifying domain or toggling `use_proxy`.
- Integrate Prometheus metrics and UI counters: active_jobs, jobs_per_minute, avg_time_to_complete, captcha_tasks_pending.

---

**9. Security & Multi-tenant Considerations**

- Multi-tenant flagging: ensure job data isolation; namespace proxies and saved profiles per team.
- Sensitive data (cookies/tokens) must be encrypted at rest and access-controlled.
- Audit logs for job creation, reruns, and solver submissions.

---

**10. Example Flows**

- Quick scrape (developer):

  1. Open `ScraperDashboardPage` → New Scrape → paste URL → select `auto` strategy → Submit
  2. UI redirects to `JobDetailPage`; live timeline shows Tier1 attempt and final result appears
  3. Click `ResponseViewer` → export JSON

- Scheduled crawl (marketing):

  1. Create template with `proxy_pool=rotate-daytime` and cron `0 */4 * * *` → Save
  2. Upload CSV of product pages → map template → Schedule
  3. Monitor `ResultsExplorerPage` for exports

- Captcha solve flow (support):
  1. Support sees job status `captcha_required` → opens solver → operator solves
  2. Backend publishes solved event → Worker resumes and final result appears in detail page

---

**11. Implementation Recommendations**

- Tech stack: React + TypeScript, React Query (or SWR), Chakra UI or MUI/Tailwind, React Router, WebSocket/SSE for live updates.
- Use virtualization for job lists (react-window) to handle large result sets.
- For large outputs, store results in object storage (S3) and stream fetches; frontend shows first N KB and provides download link.
- Build component library for common elements: `PreviewThumbnail`, `ResponseViewer`, `JobTimeline`.

---

**12. Next Steps (Suggested)**

- Generate component skeletons for `ScrapeForm`, `JobCard`, `JobDetailPage`, and `ResponseViewer`.
- Build minimal FastAPI endpoints for creating & retrieving jobs to integrate with UI.
- Implement WebSocket server-side support for `/ws/scrape/{jobId}` or use Redis pub/sub bridge.

---

Dokumen ini dimaksudkan sebagai spesifikasi lengkap bagi tim frontend untuk mengimplementasikan UI yang mampu mengendalikan seluruh fitur Titan Scraper dan menerima hasil scraping. Jika Anda ingin, saya bisa langsung menghasilkan komponen React/TSX skeleton beserta example requests to the existing FastAPI endpoints.
