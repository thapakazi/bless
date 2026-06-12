# Bless — task runner. Run `just` to see available recipes.

set dotenv-load := true
set shell := ["bash", "-cu"]

# default: print recipes
default:
    @just --list

# --- bootstrap ---

# Create .venv and install backend deps
install:
    uv venv
    uv pip install -r backend/requirements.txt

# Copy .env.example -> .env if missing
env:
    @[ -f .env ] || cp .env.example .env
    @echo ".env ready"

# --- infra ---

# Start ClickHouse (detached)
up:
    docker compose up -d
    @just wait-clickhouse

# Stop ClickHouse
down:
    docker compose down

# Wipe ClickHouse volume (DESTRUCTIVE)
nuke:
    docker compose down -v
    rm -rf .clickhouse-data

# Wait until ClickHouse answers /ping
wait-clickhouse:
    @until curl -sf http://localhost:8123/ping >/dev/null; do sleep 1; done
    @echo "clickhouse: ready"

# Open a ClickHouse SQL shell inside the container
sh:
    docker exec -it bless-clickhouse clickhouse-client -u bless --password bless --database bless

# --- backend ---

# Run FastAPI in dev mode (autoreload)
dev:
    uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

# Run FastAPI in production-ish mode (no reload)
serve:
    uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000

# --- smoke test ---

# End-to-end smoke: upload demo.csv, wait for agent loop, print Bless report
smoke csv="sample_data/demo.csv":
    @scripts/smoke.sh {{csv}}

# Show row counts in ClickHouse (Cloud or local)
count:
    @uv run python -c "from backend.db.clickhouse import get_client; c=get_client(); [print(r) for r in c.query('SELECT job_id, count() AS vendors, max(monthly_amount) AS top_spend FROM transactions GROUP BY job_id ORDER BY job_id').result_rows]"

# Show every flag for a given job_id
flags JOB:
    @JOB={{JOB}} uv run python -c "import os;from backend.db.clickhouse import get_client; c=get_client(); [print(r) for r in c.query('SELECT priority, flag_type, vendor_name, monthly_savings FROM waste_flags WHERE job_id={j:String} ORDER BY monthly_savings DESC', parameters={'j': os.environ['JOB']}).result_rows]"

# Watch dev-server logs (live)
logs:
    tail -f /private/tmp/claude-502/-Users-thapakazi-repos-thapakazi-bless/d08b639c-7389-4bdb-b505-0ecc803d189d/tasks/bh4nyyjvp.output 2>/dev/null || echo "background server task no longer running — start one with: just dev"
