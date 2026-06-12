# Architecture

Bless is a CSV-in, dashboard-out spend auditor. The pipeline is split across a FastAPI backend, a Next.js frontend, and a ClickHouse Cloud store. Claude runs the per-vendor research loop and writes the final narrative.

## High level

```
+----------------------+          +-------------------+         +------------------+
|  Next.js (App Router)| <-HTTP-> |  FastAPI backend  | <-SQL-> | ClickHouse Cloud |
|  bun, Tailwind 4     |          |  uvicorn, uv      |         | 4 tables         |
+----------------------+          +---------+---------+         +------------------+
                                            |
                                            +---> Anthropic API (Sonnet 4.6, Opus 4.7)
                                            +---> Airbyte (optional ingestion source)
                                            +---> Langfuse (optional tracing)
```

The frontend is a thin presentation layer. Reshaping happens server-side in `build_frontend_report()`.

## Job lifecycle

```
POST /api/upload
  parse CSV
  INSERT transactions
  set_job_status(ingested)
  BackgroundTask -> run_job(job_id)

run_job(job_id):                                      jobs.status
  set_job_status(investigating)  ----------------->   investigating
  investigator.investigate_job(job_id)
    for each top-5 vendor:
      Claude Sonnet 4.6 tool-use loop (<=4 rounds)
      INSERT enriched_vendors
    seed-only rows for the rest

  set_job_status(detecting)      ----------------->   detecting
  detector.detect_job(job_id)
    apply 5 rules over enriched_vendors
    INSERT waste_flags

  set_job_status(reporting)      ----------------->   reporting
  reporter.build_report(job_id)
    Claude Opus 4.7 narrative + top_action

  set_job_status(complete)       ----------------->   complete
```

Failures at any stage set `failed` with `error` populated. The frontend's polling loop translates `failed` into a UI error.

## Storage — ClickHouse schema

Four MergeTree tables, all keyed on `job_id`:

| Table | Purpose | Engine |
|---|---|---|
| `transactions` | Per-vendor monthly-equivalent rollup from the CSV. | `MergeTree ORDER BY (job_id, vendor_name)` |
| `enriched_vendors` | Category, plan info, seat utilization, evidence. | `MergeTree ORDER BY (job_id, vendor_name)` |
| `waste_flags` | One row per detected flag with `priority` + `monthly_savings`. | `MergeTree ORDER BY (job_id, vendor_name)` |
| `jobs` | Status FSM. Last writer wins via `updated_at`. | `ReplacingMergeTree(updated_at) ORDER BY (job_id)` |

Full DDL in `backend/db/clickhouse.py:13`. Always read `jobs` with `FROM jobs FINAL`.

## API surface

| Method | Path | Used by | Notes |
|---|---|---|---|
| `GET` | `/health` | health probe | |
| `POST` | `/api/upload` | upload page | CSV → job_id |
| `GET` | `/api/jobs` | `/jobs` page | recent jobs + vendor_count |
| `DELETE` | `/api/jobs/{id}` | `/jobs` page | wipes all 4 tables for that job |
| `GET` | `/api/status/{id}` | dashboard + sidebar + `/jobs` | cheap polling endpoint |
| `GET` | `/api/report/{id}` | dashboard (on `complete` only) | reshaped via `build_frontend_report` |
| `GET/POST` | `/api/sources/*` | connections page | Airbyte ingestion path |

The dashboard polls `/api/status` every 3s; the sidebar and `/jobs` page poll every 5s. None hit `/api/report` until status is `complete`.

## Report shape

The internal `build_report()` output and the frontend `Report` contract differ — the adapter `build_frontend_report()` in `backend/agent/reporter.py:127` translates between them.

Adapter builds:
- `issues_found` — counts by priority bucket (HIGH→critical, MEDIUM→medium, LOW→easy).
- `categories[]` — sums monthly spend per category from `transactions ⨝ enriched_vendors`; `flagged: true` if any vendor in that category has at least one waste flag.
- `action_groups[]` — three buckets: `kill` (HIGH/red), `rightsize` (MEDIUM/yellow), `easy` (LOW/green). Each item is decorated with `monthly_amount`, `category`, and a `domain` heuristic for clearbit logos.
- `annual_savings = potential_monthly_savings * 12`.

Contract on the frontend: `frontend/src/lib/api.ts:35`.

## LLM usage

| Stage | Model | Why |
|---|---|---|
| Enrichment / investigation | `claude-sonnet-4-6` | Per-vendor tool-use loop. Cheaper + faster for high-volume calls. |
| Report narrative + `top_action` | `claude-opus-4-7` | One call per job; quality matters. |
| Chat | `claude-opus-4-7` | Streamed Q&A over the full report context. |

Prompt caching is required for cost reasons — the system prompt + report context is reused across vendor calls and chat turns. See project memory.

## Operational hazards

- **uvicorn `--reload` kills BackgroundTasks.** Editing any backend file mid-job aborts the orchestrator silently. The `jobs` row stays at `investigating` forever (zombie). Mitigations: use `just serve` (no reload) for real runs; surface and delete zombies via `/jobs`.
- **`/api/report` was heavy.** Earlier the FE polled `/api/report` directly; each in-flight call shipped every `transactions` row. Now `/api/status` is the polling target — `/api/report` is called exactly once when status flips to `complete`.
- **No per-vendor incremental writes during investigation.** `investigator.py` bulk-inserts at the end. While the loop runs, `enriched_vendors` for that job is empty — the UI shows `investigating` with no progress detail.

## Frontend polling cost

Three independent pollers run concurrently while a job is in-flight:

| Component | Endpoint | Cadence |
|---|---|---|
| `dashboard/page.tsx` | `/api/status` | 3s |
| `AppShell.tsx` (sidebar) | `/api/status` | 5s |
| `jobs/page.tsx` | `/api/jobs` | 5s |

React Strict Mode in `bun run dev` doubles the mount of each `useEffect`, costing one wasted request per page load. Production builds don't have this. A future cleanup could hoist the poller into a `JobStatusProvider` context shared by all three.

## Build / deploy

Local: docker-compose ClickHouse (`just up`) + uvicorn + bun. The `.clickhouse-data/` volume is gitignored. Cloud: `xestf9c4ag.us-west-2.aws.clickhouse.cloud` with HTTPS auto-enabled.

A `render.yaml` is planned per the original spec but not yet present.

## Historical spec

The repo was scaffolded from [docs/prompt.md](prompt.md), which specifies Pioneer + TrueFoundry + Guild.ai for LLM/orchestration. The current implementation uses Anthropic SDK directly with the orchestrator as a plain Python module. The original tool list (Composio, full Langfuse instrumentation, Pioneer streaming chat) is partially wired or stubbed.
