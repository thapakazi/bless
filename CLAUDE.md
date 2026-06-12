# Bless — repo guide

SaaS spend auditor. CSV in, prioritized cost-savings dashboard out, driven by a Claude agent loop and ClickHouse.

See [docs/arch.md](docs/arch.md) for the architecture and data flow. See [docs/prompt.md](docs/prompt.md) for the original spec (historical — the current code uses Claude directly instead of the Pioneer/TrueFoundry/Guild.ai stack described there).

## Where things live

| Area | Path | Notes |
|---|---|---|
| Backend | `backend/` | FastAPI app, agent pipeline, ClickHouse client. See `backend/CLAUDE.md`. |
| Frontend | `frontend/` | Next.js 16 App Router. See `frontend/CLAUDE.md`. |
| Task runner | `justfile` | `just dev`, `just fe-dev`, `just up`, `just smoke`, etc. |
| Sample data | `sample_data/demo.csv` | 15-vendor demo CSV. |
| Docs | `docs/` | `arch.md` + original `prompt.md`. |

## Tooling rules

- **Python** — always `uv` (`uv run`, `uv pip install`). Never `pip` or `venv` directly.
- **JS** — always `bun` (`bun install`, `bun run`, `bun add`). Never npm/yarn/pnpm. `package-lock.json` is gitignored.
- **Just** — every dev command goes through `justfile` so it's discoverable. Run `just` with no args to list recipes.

## End-to-end flow (one paragraph)

`POST /api/upload` parses the CSV, inserts rows into ClickHouse `transactions`, sets the job status to `ingested`, and kicks `run_job(job_id)` as a FastAPI `BackgroundTask`. The orchestrator (`backend/agent/orchestrator.py`) then advances the job through `investigating` → `detecting` → `reporting` → `complete`. The frontend polls `/api/status/{job_id}` (cheap) on the dashboard + sidebar + `/jobs` page; once status flips to `complete`, it fetches `/api/report/{job_id}` exactly once. The report is reshaped server-side by `build_frontend_report` in `backend/agent/reporter.py` so the UI stays declarative.

## Conventions

- Treat `/api/report` as the heavy endpoint — only call it on `status == complete`. Use `/api/status` for polling.
- The `BackgroundTask` runs in the uvicorn process. Editing backend files with `--reload` enabled mid-job kills the orchestrator and leaves a zombie row stuck at `investigating`. Use `just serve` (no reload) when running real jobs, or delete zombies via `/jobs`.
- ClickHouse syntax: `FROM jobs FINAL AS j` is rejected — wrap in a subquery first.
- Never commit `frontend/bun.lock` is fine (allowed); never commit `package-lock.json` or `*.tsbuildinfo` (gitignored).
- No emojis in code/docs unless the user explicitly asks.

## Common tasks

- **Wipe ClickHouse Cloud data**: `uv run python -c "from backend.db.clickhouse import get_client; c=get_client(); [c.command(f'TRUNCATE TABLE {t}') for t in ('transactions','enriched_vendors','jobs','waste_flags')]"`
- **Inspect a job**: `just flags <JOB_ID>` or query directly with `uv run python -c "from backend.db.clickhouse import get_client; ..."`.
- **Burry a zombie**: hit `DELETE /api/jobs/{job_id}` from `/jobs` UI, or wipe via the snippet above.
