from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .agent.orchestrator import run_job
from .agent.parser import parse_csv
from .agent.reporter import build_frontend_report
from .db.clickhouse import (
    fetch_transactions,
    get_job_status,
    init_schema,
    insert_transactions,
    set_job_status,
)
from .integrations import airbyte as airbyte_mod

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


@app.get("/api/jobs")
def list_jobs(limit: int = 20):
    """Recent jobs with status + vendor count, newest first.

    Frontend's /jobs page polls this every few seconds while any job is in-flight.
    """
    from .db.clickhouse import get_client

    client = get_client()
    rows = client.query(
        """
        SELECT j.job_id, j.status, j.error, j.started_at, j.updated_at,
               coalesce(t.vendor_count, 0) AS vendor_count
        FROM (SELECT job_id, status, error, started_at, updated_at
              FROM jobs FINAL) AS j
        LEFT JOIN (
            SELECT job_id, count() AS vendor_count
            FROM transactions
            GROUP BY job_id
        ) AS t USING (job_id)
        ORDER BY j.updated_at DESC
        LIMIT {n:UInt32}
        """,
        parameters={"n": max(1, min(int(limit), 100))},
    ).result_rows
    return {
        "jobs": [
            {
                "job_id": r[0],
                "status": r[1],
                "error": r[2] or None,
                "started_at": r[3].isoformat() if r[3] else None,
                "updated_at": r[4].isoformat() if r[4] else None,
                "vendor_count": int(r[5]),
            }
            for r in rows
        ]
    }


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    """Wipe a job and all its data across transactions/enriched_vendors/waste_flags/jobs.

    Accepted on any status, including in-flight. The BackgroundTask (if any) keeps
    running until its next ClickHouse write, which becomes a no-op against the now-
    empty rows. No process-level kill is attempted.
    """
    from .db.clickhouse import get_client

    client = get_client()
    for table in ("transactions", "enriched_vendors", "waste_flags", "jobs"):
        client.command(
            f"DELETE FROM {table} WHERE job_id = {{j:String}}",
            parameters={"j": job_id},
        )
    log.info("Deleted job %s", job_id)
    return {"job_id": job_id, "deleted": True}


@app.get("/api/status/{job_id}")
def status(job_id: str):
    """Cheap status probe — single ClickHouse row, no transaction fetch.

    Frontend polls this while the agent loop runs, then switches to /api/report
    once status is `complete` (or surfaces the error on `failed`).
    """
    job = get_job_status(job_id)
    if not job:
        raise HTTPException(404, f"No job for job_id={job_id}")
    return {
        "job_id": job_id,
        "status": job["status"],
        "error": job.get("error") or None,
        "updated_at": job.get("updated_at"),
    }


@app.get("/api/report/{job_id}")
def report(job_id: str):
    rows = fetch_transactions(job_id)
    if not rows:
        raise HTTPException(404, f"No data for job_id={job_id}")

    job = get_job_status(job_id) or {"status": "unknown"}
    if job["status"] in {"ingested", "enriching", "investigating", "detecting", "reporting"}:
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
    full = build_frontend_report(job_id)
    full["vendors"] = rows
    return full


# --- Airbyte ingestion (alternative / augmenting source) ---


def _airbyte_guard() -> None:
    if not airbyte_mod.is_available():
        raise HTTPException(503, "airbyte: client credentials not configured")


def _airbyte_call(fn, *args, **kwargs):
    """Invoke an airbyte client fn, mapping AirbyteError -> HTTPException."""
    try:
        return fn(*args, **kwargs)
    except airbyte_mod.AirbyteError as e:
        # Surface upstream status when sensible; otherwise treat as bad gateway.
        status = e.status_code if 400 <= e.status_code < 600 else 502
        if status == 401 or status == 403:
            status = 502  # creds are server-side; client shouldn't see 401
        raise HTTPException(status, f"airbyte: {e.message}")


@app.get("/api/sources")
def list_sources(workspace_id: str | None = None):
    """List Airbyte connections across the workspace(s) we can see.

    Each entry has the connection plus its source summary and last sync time.
    If `workspace_id` is omitted, we scan every workspace the OAuth app sees.
    """
    _airbyte_guard()

    workspaces = _airbyte_call(airbyte_mod.list_workspaces)
    if workspace_id:
        workspaces = [w for w in workspaces if w.get("workspaceId") == workspace_id]

    sources_out: list[dict] = []
    for ws in workspaces:
        wid = ws.get("workspaceId")
        if not wid:
            continue
        connections = _airbyte_call(airbyte_mod.list_connections, workspace_id=wid)
        ws_sources = {s.get("sourceId"): s for s in _airbyte_call(airbyte_mod.list_sources, workspace_id=wid)}
        for c in connections:
            src = ws_sources.get(c.get("sourceId"), {})
            # Pull the most recent job for last-sync metadata.
            last_job: dict = {}
            try:
                jobs = airbyte_mod.list_jobs(connection_id=c.get("connectionId"), limit=1)
                if jobs:
                    last_job = jobs[0]
            except airbyte_mod.AirbyteError as e:
                log.warning("airbyte: could not fetch last job for %s: %s", c.get("connectionId"), e.message)
            sources_out.append({
                "workspace_id": wid,
                "workspace_name": ws.get("name"),
                "connection_id": c.get("connectionId"),
                "connection_name": c.get("name"),
                "status": c.get("status"),
                "source_id": c.get("sourceId"),
                "source_name": src.get("name"),
                "source_type": src.get("sourceType") or src.get("sourceDefinitionId"),
                "destination_id": c.get("destinationId"),
                "schedule": c.get("schedule"),
                "last_job_id": last_job.get("jobId"),
                "last_job_status": last_job.get("status"),
                "last_job_started_at": last_job.get("startTime"),
                "last_job_ended_at": last_job.get("lastUpdatedAt") or last_job.get("endTime"),
            })

    return {"workspace_count": len(workspaces), "connections": sources_out}


@app.post("/api/sources/{connection_id}/sync")
def trigger_source_sync(connection_id: str):
    """Trigger an Airbyte sync for the given connection. Returns the job."""
    _airbyte_guard()
    job = _airbyte_call(airbyte_mod.trigger_sync, connection_id)
    return {
        "connection_id": connection_id,
        "airbyte_job_id": job.get("jobId"),
        "status": job.get("status"),
        "job": job,
    }


@app.get("/api/sources/jobs/{airbyte_job_id}")
def get_source_job(airbyte_job_id: str):
    _airbyte_guard()
    job = _airbyte_call(airbyte_mod.get_job_status, airbyte_job_id)
    return job


@app.get("/api/sources/catalog")
def list_source_catalog(workspace_id: str | None = None):
    """List source connector definitions available to the workspace(s)."""
    _airbyte_guard()
    workspaces = _airbyte_call(airbyte_mod.list_workspaces)
    if workspace_id:
        workspaces = [w for w in workspaces if w.get("workspaceId") == workspace_id]

    out: list[dict] = []
    for ws in workspaces:
        wid = ws.get("workspaceId")
        if not wid:
            continue
        try:
            defs = airbyte_mod.list_source_definitions(workspace_id=wid)
        except airbyte_mod.AirbyteError as e:
            log.warning("airbyte: source_definitions not available for ws=%s: %s", wid, e.message)
            defs = []
        for d in defs:
            out.append({
                "workspace_id": wid,
                "source_definition_id": d.get("sourceDefinitionId") or d.get("id"),
                "name": d.get("name"),
                "docker_repository": d.get("dockerRepository"),
                "release_stage": d.get("releaseStage"),
            })
    return {"workspace_count": len(workspaces), "definitions": out}
