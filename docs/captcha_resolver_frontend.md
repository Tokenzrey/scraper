# Captcha Resolver — Frontend Design & Spec

Dokumen ini menjelaskan desain lengkap frontend untuk fitur Manual Captcha Resolver yang terintegrasi dengan Titan Worker. Tujuan: menyediakan UI/UX yang memungkinkan operator manusia menyelesaikan CAPTCHA/Cloudflare challenge, mengirim solusi kembali ke backend, dan melihat preview / history tugas.

**Versi:** 2.0
**Penulis:** Tim Engineering
**Tanggal:** 2025-12-15
**Backend Status:** ✅ IMPLEMENTED (see `captcha_resolver_backend.md`)

---

**Ringkasan Singkat**

- Halaman utama: `Captcha Queue` — grid dari semua permintaan yang membutuhkan intervensi manusia.
- Setiap item di-grid: `CaptchaCard` menampilkan ringkasan dan preview (thumbnail atau iframe snapshot).
- Klik kartu membuka `Solver Workspace` — area kerja penuh (iframe atau overlay) di mana operator melihat halaman target dan menyelesaikan challenge.
- Setelah solusi ditemukan (token, cookie, atau session), frontend mengirimkan payload ke API backend untuk disimpan dan dipakai worker untuk bypass.

---

## Backend API Reference (Implemented)

### REST Endpoints

| Method | Endpoint | Description | Request | Response |
|--------|----------|-------------|---------|----------|
| POST | `/api/v1/captcha/tasks` | Create task | `CaptchaTaskCreate` | `CaptchaTaskResponse` |
| GET | `/api/v1/captcha/tasks` | List tasks | Query params | `CaptchaTaskListResponse` |
| GET | `/api/v1/captcha/tasks/pending` | Pending tasks | Query params | `CaptchaTaskListResponse` |
| GET | `/api/v1/captcha/tasks/{uuid}` | Get task | - | `CaptchaTaskResponse` |
| POST | `/api/v1/captcha/tasks/{uuid}/assign` | Assign task | `CaptchaTaskAssign` | `AssignResponse` |
| POST | `/api/v1/captcha/tasks/{uuid}/solve` | Submit solution | `CaptchaSolutionSubmit` | `SolveResponse` |
| POST | `/api/v1/captcha/tasks/{uuid}/mark-unsolvable` | Mark unsolvable | `CaptchaMarkUnsolvable` | Response |
| GET | `/api/v1/captcha/sessions/{domain}` | Get cached session | - | `SessionResponse` |
| GET | `/api/v1/captcha/proxy/render/{uuid}` | Proxy render | - | HTML |
| DELETE | `/api/v1/captcha/expired` | Cleanup expired | - | `CleanupResponse` |

### WebSocket Endpoints

| Endpoint | Description |
|----------|-------------|
| `/ws/captcha` | All CAPTCHA events (real-time) |
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
```

---

**Arsitektur Halaman & Komponen**

1. Pages

- `CaptchaQueuePage`

  - URL: `/captchas`
  - Fungsi: menampilkan grid, filter (domain, age, priority), pencarian, dan statistik singkat (total pending, solved, avg time).
  - Layout: header (search + filter), main grid, sidebar (detail selected item / logs), footer (bulk actions).

- `CaptchaSolverPage` (modal/route: `/captchas/:id/solve`)
  - Fungsi: workspace penuh untuk menyelesaikan CAPTCHA.
  - Behavior: buka sebagai modal atau route penuh; menyediakan toolbar Solve/Skip/Mark-Fail, keyboard shortcuts.

2. Components

- `CaptchaGrid`

  - Props: `items: CaptchaTask[]`, `onSelect(id)`
  - Features: virtualized list (react-window), lazy thumbnails, infinite-scroll/pagination.

- `CaptchaCard`

  - Props: `task: CaptchaTask`, `onOpen`.
  - UI: domain, path, age, preview thumbnail, priority badge, retry count, small action buttons (open, skip, assign).
  - Preview: shows either thumbnail image or small iframe snapshot (sandboxed) with blurred overlay (safety).

- `CaptchaFilters`

  - Fields: domain select, priority, age range, assigned_to (operator), status (pending/solved/failed).
  - Emits: `onChange(filterState)`.

- `CaptchaPreviewModal`

  - Shows larger preview and quick actions (open solver, copy URL, view raw HTML).

- `SolverWorkspace`

  - Core component when solving: contains `SolverFrame`, `SolutionForm`, `SessionTools`.

- `SolverFrame`

  - Implementation: sandboxed `iframe` OR proxy iframe served by backend to avoid cross-origin restrictions. Should include a small helper overlay (inspect element id, refresh, take-screenshot).
  - Props: `srcUrl`, `taskId`.
  - Safety: `sandbox="allow-scripts allow-forms"` if using direct iframe; preferred: backend-proxied endpoint `/api/v1/captcha/proxy/render/{uuid}`.

- `SolutionForm`

  - Fields: `solution_token` (string), `expires_at` (optional), `notes`, `type` (cookie|token|session). Submit button.
  - On submit: call `POST /api/v1/captcha/tasks/{uuid}/solve`.

- `OperatorToolbar`

  - Buttons: Save, Mark Unsolvable, Requeue, Assign to, Take Screenshot, Copy Headers, Copy Cookies.
  - Shortcuts: `Ctrl+Enter` untuk submit, `Esc` untuk close.

- `AuditTrail` / `TaskLogs`
  - Show chronological events: created_at, assigned_to, opened_at, solved_at, solver_user, last_attempt.

3. Hooks (React) / Data Layer

```typescript
// hooks/useCaptchaTasks.ts
export function useCaptchaTasks(filters: CaptchaFilters) {
  return useQuery({
    queryKey: ['captcha-tasks', filters],
    queryFn: () => fetchCaptchaTasks(filters),
    refetchInterval: 10000, // Poll every 10s
  });
}

// hooks/useCaptchaTask.ts
export function useCaptchaTask(uuid: string) {
  return useQuery({
    queryKey: ['captcha-task', uuid],
    queryFn: () => fetchCaptchaTask(uuid),
  });
}

// hooks/useSolveCaptcha.ts
export function useSolveCaptcha() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ uuid, solution }: { uuid: string; solution: CaptchaSolution }) =>
      submitSolution(uuid, solution),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['captcha-tasks'] });
    },
  });
}

// hooks/useAssignTask.ts
export function useAssignTask() {
  return useMutation({
    mutationFn: ({ uuid, operatorId }: { uuid: string; operatorId: string }) =>
      assignTask(uuid, operatorId),
  });
}

// hooks/useCaptchaEvents.ts (WebSocket)
export function useCaptchaEvents(domain?: string) {
  const [events, setEvents] = useState<CaptchaEvent[]>([]);
  const queryClient = useQueryClient();

  useEffect(() => {
    const wsUrl = domain
      ? `ws://${window.location.host}/ws/captcha/${domain}`
      : `ws://${window.location.host}/ws/captcha`;

    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      const data: CaptchaEvent = JSON.parse(event.data);
      setEvents(prev => [...prev.slice(-99), data]);

      // Auto-refresh on important events
      if (['task_created', 'task_solved', 'task_unsolvable'].includes(data.type)) {
        queryClient.invalidateQueries({ queryKey: ['captcha-tasks'] });
      }
    };

    ws.onerror = (error) => console.error('WebSocket error:', error);

    return () => ws.close();
  }, [domain, queryClient]);

  return events;
}
```

4. Data Models (frontend view)

```typescript
// types/captcha.ts

interface CaptchaTask {
  id: number;
  uuid: string;
  url: string;
  domain: string;
  status: 'pending' | 'in_progress' | 'solving' | 'solved' | 'failed' | 'unsolvable';
  challenge_type: string | null;
  error_message: string | null;
  priority: number; // 1-10
  assigned_to: string | null;
  attempts: number;
  cf_clearance: string | null;
  solver_result: Record<string, any> | null;
  solver_expires_at: string | null;
  solver_notes: string | null;
  preview_path: string | null;
  proxy_url: string | null;
  user_agent: string | null;
  request_id: string | null;
  last_error: string | null;
  metadata: Record<string, any>;
  created_at: string;
  updated_at: string;
}

interface CaptchaTaskCreate {
  url: string;
  challenge_type?: string;
  error_message?: string;
  request_id?: string;
  priority?: number; // 1-10, default 5
  proxy_url?: string;
  user_agent?: string;
  metadata?: Record<string, any>;
}

interface CaptchaSolutionSubmit {
  type: 'cookie' | 'token' | 'session';
  payload: CookieItem[] | Record<string, any> | string;
  user_agent?: string;
  expires_at?: string;
  notes?: string;
}

interface CookieItem {
  name: string;
  value: string;
  domain?: string;
  path?: string;
  secure?: boolean;
  http_only?: boolean;
  expires_at?: string;
}

interface CaptchaTaskAssign {
  operator_id: string;
  lock_duration_seconds?: number; // 60-7200, default 1800
}

interface CaptchaEvent {
  type: CaptchaEventType;
  timestamp: string;
  payload: {
    task_id: string;
    uuid: string;
    domain: string;
    [key: string]: any;
  };
}

interface CaptchaTaskListResponse {
  tasks: CaptchaTask[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

interface SessionResponse {
  domain: string;
  has_session: boolean;
  session: {
    domain: string;
    cf_clearance: string;
    user_agent: string | null;
    created_at: string;
    expires_at: string;
    ttl_remaining: number;
  } | null;
}
```

5. UX / Flow

- Operator lands on `CaptchaQueuePage` → sees prioritized list.
- Click card → `CaptchaSolverPage` opens; system marks task `in_progress` and assigns to current operator (via API).
- Solver frame loads proxied URL (backend serves sanitized view or direct iframe if CORS allows).
- Operator interacts with page inside frame, completes challenge (may require clicking, solving puzzle, etc.).
- Operator extracts token/cookie (browser UI or helper capture) → enters into `SolutionForm` → submit.
- Frontend shows transient success and optimistic marks task `solved` in UI; backend persists solution and notifies worker.
- Worker picks up solution (via DB change / Redis pubsub) and continues the suspended scrape attempt.

6. Security & Auth

- Only authenticated operators (role: `captcha_solver`) can access pages.
- All actions require JWT/CSRF tokens.
- `SolverFrame` served via backend proxy endpoint that strips harmful scripts and sets `Content-Security-Policy` where applicable.
- Rate-limit UI actions (e.g., 10 solves/min per operator) and require audit logging.

7. Accessibility & Internationalization

- Keyboard-first interactions, ARIA labels for cards and toolbar.
- Localizable strings (i18n) for labels and notifications.

8. Edge Cases & Failure Modes

- If frame cannot load target due to X-Frame-Options, backend should attempt to fetch and render sanitized HTML preview with interactive elements replaced by screenshots plus form inputs for operator to replicate actions.
- If operator marks `unsolvable`, the system should provide reason codes and optionally requeue to fallback solver (paid service) or escalate.

---

## API Integration Examples

### Fetch Tasks

```typescript
// api/captcha.ts
const API_BASE = '/api/v1/captcha';

export async function fetchCaptchaTasks(filters: CaptchaFilters): Promise<CaptchaTaskListResponse> {
  const params = new URLSearchParams();
  if (filters.status) params.set('status', filters.status);
  if (filters.domain) params.set('domain', filters.domain);
  if (filters.page) params.set('page', String(filters.page));
  if (filters.limit) params.set('limit', String(filters.limit));

  const response = await fetch(`${API_BASE}/tasks?${params}`);
  if (!response.ok) throw new Error('Failed to fetch tasks');
  return response.json();
}

export async function fetchPendingTasks(limit = 50): Promise<CaptchaTaskListResponse> {
  const response = await fetch(`${API_BASE}/tasks/pending?limit=${limit}`);
  if (!response.ok) throw new Error('Failed to fetch pending tasks');
  return response.json();
}
```

### Assign Task

```typescript
export async function assignTask(uuid: string, operatorId: string): Promise<AssignResponse> {
  const response = await fetch(`${API_BASE}/tasks/${uuid}/assign`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      operator_id: operatorId,
      lock_duration_seconds: 1800, // 30 minutes
    }),
  });

  if (response.status === 409) {
    throw new Error('Task already assigned to another operator');
  }
  if (!response.ok) throw new Error('Failed to assign task');
  return response.json();
}
```

### Submit Solution

```typescript
export async function submitSolution(uuid: string, solution: CaptchaSolutionSubmit): Promise<SolveResponse> {
  const response = await fetch(`${API_BASE}/tasks/${uuid}/solve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(solution),
  });

  if (!response.ok) throw new Error('Failed to submit solution');
  return response.json();
}

// Example: Submit cookie solution
await submitSolution('task-uuid-123', {
  type: 'cookie',
  payload: [
    {
      name: 'cf_clearance',
      value: 'abc123xyz789',
      domain: '.example.com',
      path: '/',
      secure: true,
      http_only: true,
    },
  ],
  user_agent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0',
  notes: 'Solved via manual interaction',
});
```

### Mark Unsolvable

```typescript
export async function markUnsolvable(uuid: string, reason: string): Promise<void> {
  const response = await fetch(`${API_BASE}/tasks/${uuid}/mark-unsolvable`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  });

  if (!response.ok) throw new Error('Failed to mark task as unsolvable');
}
```

### Get Cached Session

```typescript
export async function getCachedSession(domain: string): Promise<SessionResponse> {
  const response = await fetch(`${API_BASE}/sessions/${encodeURIComponent(domain)}`);
  if (!response.ok) throw new Error('Failed to get session');
  return response.json();
}
```

---

## Implementation Notes & Recommendations

- Use React + TypeScript, React Query (data fetching), React Router, Chakra/UI or Tailwind for rapid UI production.
- For previews: backend provides proxied frame via `/api/v1/captcha/proxy/render/{uuid}`.
- Use WebSocket `/ws/captcha` for real-time updates instead of polling.
- Keep the solver UI minimal and focused — operator efficiency is key.

---

**Appendix — Wireframe (textual)**

## Captcha Queue Page

```
┌──────────────────────────────────────────────────────────────────┐
│ [Search...] [Status: All ▼] [Domain: All ▼] [Priority: All ▼]   │
├──────────────────────────────────────────────────────────────────┤
│ Pending: 12  │  In Progress: 3  │  Solved Today: 47  │  Avg: 2m │
├──────────────────────────────────────────────────────────────────┤
│ ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐              │
│ │ [thumb] │  │ [thumb] │  │ [thumb] │  │ [thumb] │              │
│ │example  │  │site.com │  │test.org │  │demo.net │              │
│ │●High P:8│  │○Med P:5 │  │●High P:9│  │○Low P:2 │              │
│ │ 2m ago  │  │ 5m ago  │  │ 1m ago  │  │ 15m ago │              │
│ └─────────┘  └─────────┘  └─────────┘  └─────────┘              │
│                                                                  │
│ ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐              │
│ │ [thumb] │  │ [thumb] │  │ [thumb] │  │ [thumb] │              │
│ │...      │  │...      │  │...      │  │...      │              │
│ └─────────┘  └─────────┘  └─────────┘  └─────────┘              │
└──────────────────────────────────────────────────────────────────┘
```

## Solver Workspace

```
┌──────────────────────────────────────────────────────────────────┐
│ [← Back] [Save Solution] [Mark Unsolvable] [Screenshot] [Assign] │
├────────────────────────────────────┬─────────────────────────────┤
│                                    │ Task Details                │
│                                    │ ─────────────               │
│                                    │ Domain: example.com         │
│      SolverFrame (iframe)          │ URL: /protected-page        │
│                                    │ Priority: 8 (High)          │
│      [Proxied page content]        │ Attempts: 2                 │
│                                    │ Created: 2m ago             │
│                                    │                             │
│                                    ├─────────────────────────────┤
│                                    │ Solution Form               │
│                                    │ ─────────────               │
│                                    │ Type: [Cookie ▼]            │
│                                    │                             │
│                                    │ cf_clearance:               │
│                                    │ [________________]          │
│                                    │                             │
│                                    │ Notes:                      │
│                                    │ [________________]          │
│                                    │                             │
│                                    │ [Submit Solution]           │
│                                    ├─────────────────────────────┤
│                                    │ Audit Trail                 │
│                                    │ ─────────────               │
│                                    │ • Created 2m ago            │
│                                    │ • Assigned to you 30s ago   │
└────────────────────────────────────┴─────────────────────────────┘
```

---

**Status:** Backend API fully implemented. Ready for frontend development.

See also:
- `captcha_resolver_backend.md` - Full backend implementation details
- `scraper_frontend_integration.md` - Scraper UI integration
