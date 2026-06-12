# Frontend

Next.js 16 (App Router) + Tailwind 4 + OpenUI. Served by `bun`.

## Tooling

- Always `bun`. `bun install`, `bun add`, `bun run dev`. Recipes live in `justfile`: `just fe-install`, `just fe-dev`, `just fe-build`, `just fe-start`.
- Lockfile: `bun.lock` only. `package-lock.json` is gitignored.
- `*.tsbuildinfo` is gitignored — don't commit.

## App router layout

```
src/app/
  page.tsx              upload zone (/)
  dashboard/page.tsx    main report
  connections/page.tsx  GitHub/AWS/Zoom credential connectors
  jobs/page.tsx         job list with live status pills and delete
  chat/page.tsx         Q&A chat
  api/chat/route.ts     streamed chat proxy to Claude
  layout.tsx            root layout
src/components/
  AppShell.tsx          sidebar + nav, sidebar status poller
  ActionList.tsx        red/yellow/green action buckets
  SpendDonut.tsx        category donut chart
  VendorLogo.tsx        clearbit logo with initials fallback
src/lib/api.ts          all backend calls + types
```

## Polling pattern

The dashboard, sidebar, and `/jobs` page each run their own poller. Pattern:

1. On mount, call `getStatus(jobId)` (or `listJobs()`).
2. While `status` is in `{ingested, investigating, detecting, reporting}`, schedule another tick in 3–5s.
3. Once `status === "complete"`, fetch `/api/report/{job_id}` exactly once and stop polling.
4. On `failed`, surface the error and stop.

Never call `getReport` while in-flight — it returns a stub shape and burns ClickHouse cycles fetching every transaction row. See `dashboard/page.tsx:14` and `AppShell.tsx:32` for the canonical implementations.

## Report contract

`frontend/src/lib/api.ts:35` declares the `Report` interface. The backend reshapes its internal report into this shape via `build_frontend_report()` in `backend/agent/reporter.py`. If you change one side, change the other.

Key fields:
- `issues_found: {total, critical, medium, easy}` — priority bucket counts.
- `categories: [{category, amount, flagged}]` — donut data.
- `action_groups: [{key: 'kill'|'rightsize'|'easy', label, color, items}]` — three sections.

## Strict Mode in dev

Each `useEffect` runs twice on mount during `bun run dev` (React Strict Mode). The poller closures handle this via a `cancelled` flag, but the FIRST `getStatus` request is already in flight and will return after cleanup — it's discarded but still costs one round-trip per page mount. In production builds the doubled mount disappears.

## Job context (localStorage)

The "active" job is stored in `localStorage["bless_job_id"]`. `setJobId` and `clearJob` (in `lib/api.ts`) dispatch a `bless:job` window event so `AppShell` can re-sync. The dashboard reads this on mount and dies if absent (shows the Empty state). The `/jobs` page Open button writes here and routes to `/dashboard`.

## OpenUI

This project uses `@openuidev/react-*` packages — see `frontend/.agents/skills/openui/SKILL.md` for usage details.

## API base

`API_BASE` resolves to `process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000"`. Export `NEXT_PUBLIC_API_BASE` in deployed envs.
