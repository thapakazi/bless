from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .agent.orchestrator import run_job
from .agent.parser import parse_csv
from .agent.reporter import build_report
from .db.clickhouse import (
    fetch_transactions,
    get_job_status,
    init_schema,
    insert_transactions,
    set_job_status,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("bless")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_schema()
        log.info("ClickHouse schema initialized")
    except Exception as e:
        log.exception("Failed to initialize ClickHouse schema: %s", e)
    yield


app = FastAPI(title="Bless — SaaS Spend Auditor", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/upload")
async def upload(background: BackgroundTasks, file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Expected a .csv file upload")
    content = await file.read()
    try:
        rows = parse_csv(content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not rows:
        raise HTTPException(400, "No usable rows parsed from CSV")

    job_id = uuid.uuid4().hex
    inserted = insert_transactions(job_id, rows)
    set_job_status(job_id, "ingested")
    log.info("Upload job_id=%s vendors=%d", job_id, inserted)

    # Kick off the agent loop in the background.
    background.add_task(run_job, job_id)

    return {
        "job_id": job_id,
        "vendor_count": inserted,
        "status": "ingested",
    }


@app.get("/api/report/{job_id}")
def report(job_id: str):
    rows = fetch_transactions(job_id)
    if not rows:
        raise HTTPException(404, f"No data for job_id={job_id}")

    job = get_job_status(job_id) or {"status": "unknown"}
    if job["status"] in {"ingested", "enriching", "detecting", "reporting"}:
        # in-flight: return interim shape
        total_monthly = round(sum(r["monthly_amount"] for r in rows), 2)
        return {
            "job_id": job_id,
            "status": job["status"],
            "total_monthly_spend": total_monthly,
            "vendor_count": len(rows),
            "vendors": rows,
        }
    if job["status"] == "failed":
        raise HTTPException(500, job.get("error") or "job failed")

    # complete (or unknown but data exists — render anyway)
    full = build_report(job_id)
    full["vendors"] = rows
    return full
