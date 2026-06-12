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

# End-to-end smoke: upload demo.csv, fetch report
smoke:
    @echo ">>> /health"
    @curl -sf http://localhost:8000/health | python3 -m json.tool
    @echo ">>> POST /api/upload (sample_data/demo.csv)"
    @JOB=$(curl -sf -F "file=@sample_data/demo.csv" http://localhost:8000/api/upload | tee /tmp/bless_upload.json | python3 -c "import json,sys;print(json.load(sys.stdin)['job_id'])"); \
    echo "job_id=$JOB"; \
    echo ">>> GET /api/report/$JOB"; \
    curl -sf "http://localhost:8000/api/report/$JOB" | python3 -m json.tool

# Show row count in ClickHouse
count:
    docker exec bless-clickhouse clickhouse-client -u bless --password bless --database bless --query "SELECT job_id, count() AS vendors FROM transactions GROUP BY job_id ORDER BY job_id"
