# Backend

FastAPI app + Claude-driven agent pipeline + ClickHouse storage.

## Tooling

- Python 3.11, `uv` for everything. `uv run uvicorn backend.main:app --reload` (or `just dev`).
- Schema is auto-applied on startup via `lifespan()` in `backend/main.py:27`.

## Entry points

- `backend/main.py` — FastAPI app, endpoints, lifespan.
- `backend/agent/orchestrator.py` — `run_job(job_id)`: the sequential agent loop, run as a `BackgroundTask`.
- `backend/agent/parser.py` — CSV → normalized vendor rows.
- `backend/agent/investigator.py` — per-vendor Claude tool-use loop (Sonnet 4.6). Investigates top-5 vendors deeply, seeds the rest.
- `backend/agent/detector.py` — 5-rule waste detection over `enriched_vendors`.
- `backend/agent/reporter.py` — Claude Opus 4.7 narrative + `build_frontend_report()` adapter for the UI.
- `backend/db/clickhouse.py` — client, schema DDL, `fetch_transactions`, `set_job_status`, `get_job_status`.
- `backend/llm/claude.py` — Anthropic SDK wrapper with prompt caching (required).
- `backend/integrations/airbyte.py` — alternative ingestion path via Airbyte Cloud OAuth.
- `backend/integrations/langfuse.py` — no-op when keys absent.

## API surface

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Health probe. |
| POST | `/api/upload` | CSV upload. Returns `{job_id, vendor_count, status}`. Kicks `run_job`. |
| GET | `/api/jobs` | Recent jobs (last 20) with status + vendor count. Used by `/jobs` page. |
| DELETE | `/api/jobs/{job_id}` | Wipes the job from all four tables. Accepted on any status. |
| GET | `/api/status/{job_id}` | Cheap status probe — single ClickHouse row. Frontend polls this. |
| GET | `/api/report/{job_id}` | Heavy. In-flight branch returns a stub; complete branch returns `build_frontend_report()` output. |
| GET/POST | `/api/sources/*` | Airbyte ingestion endpoints. |

## Job state machine

`ingested` → `investigating` → `detecting` → `reporting` → `complete` (or `failed`). Status transitions live in `backend/agent/orchestrator.py:18`. `set_job_status` writes a new row to the `jobs` `ReplacingMergeTree(updated_at)` table — always read with `FROM jobs FINAL`.

## ClickHouse gotchas

- `FROM jobs FINAL AS j` is a syntax error. Wrap in a subquery: `FROM (SELECT ... FROM jobs FINAL) AS j`.
- All four tables key on `job_id`. Use `DELETE FROM <table> WHERE job_id = {j:String}` to wipe one job.
- Cloud connection auto-enables HTTPS when host matches `*.clickhouse.cloud` (see `backend/config.py:11`).

## Background-task hazard

`run_job` runs inside the uvicorn worker. Running `just dev` (uvicorn `--reload`) will kill the orchestrator mid-pipeline if any backend file changes. The killed task does NOT update `jobs.status`, leaving a row stuck at `investigating` forever. For real runs use `just serve`. To unstick a zombie: `DELETE /api/jobs/{job_id}` (or the `/jobs` Delete button).

## Claude usage

Required per project memory: prompt caching ON for all Claude calls. Models — Sonnet 4.6 for the enricher/investigator, Opus 4.7 for the reporter and chat. Token budget $35 for the project, so cache hit rate matters.

## Adding an endpoint

1. Add the route in `backend/main.py`. Keep heavy queries off the polling path.
2. If it touches a new table, update the schema in `backend/db/clickhouse.py:13` and rely on `init_schema()` to apply.
3. If it changes the report shape, update `build_frontend_report()` and the matching `Report` interface in `frontend/src/lib/api.ts:35`.
