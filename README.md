# Bless

SaaS spend auditor. Drop a CSV of company transactions; an agent loop enriches each vendor, flags waste, and renders a prioritized savings dashboard.

## Stack

- **Backend** — Python 3.11 + FastAPI, ClickHouse Cloud, Anthropic Claude (Sonnet 4.6 enricher, Opus 4.7 reporter & chat).
- **Frontend** — Next.js 16 (App Router) + Tailwind 4, served by `bun`.
- **Tooling** — `uv` for Python, `bun` for JS. Both wired into `justfile`.

## Quickstart

```bash
cp .env.example .env             # fill in CLICKHOUSE_* and ANTHROPIC_API_KEY
just install                     # uv venv + backend deps
just up                          # docker compose (optional, for local ClickHouse)
just dev                         # FastAPI on :8000
just fe-install && just fe-dev   # Next.js on :3000
```

Then visit `http://localhost:3000`, drop `sample_data/demo.csv` on the upload zone, and watch the pipeline run.

## Docs

- [docs/arch.md](docs/arch.md) — architecture, data flow, ClickHouse schema, API surface.
- [docs/prompt.md](docs/prompt.md) — original spec the project was scaffolded from. Historical; the current code has diverged.
- [CLAUDE.md](CLAUDE.md) — guide for Claude Code (and humans) navigating this repo.
