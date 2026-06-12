from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .agent.parser import parse_csv
from .db.clickhouse import fetch_transactions, init_schema, insert_transactions

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
async def upload(file: UploadFile = File(...)):
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
    log.info("Upload job_id=%s vendors=%d", job_id, inserted)
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
    total_monthly = round(sum(r["monthly_amount"] for r in rows), 2)
    return {
        "job_id": job_id,
        "status": "ingested",  # agent loop not wired yet
        "total_monthly_spend": total_monthly,
        "vendor_count": len(rows),
        "vendors": rows,
    }
