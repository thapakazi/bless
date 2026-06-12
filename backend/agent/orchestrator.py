"""Agent loop — enrich → detect → report.

Runs as a FastAPI BackgroundTask. State is persisted in the `jobs` table so
/api/report can poll status while the loop is running.
"""

from __future__ import annotations

import logging

from ..db.clickhouse import get_client, set_job_status
from ..integrations.langfuse import (
    job_context,
    log_event,
    trace_span,
    update_current_trace,
)
from . import detector, investigator, reporter

log = logging.getLogger("bless.orchestrator")


def _job_input_summary(job_id: str) -> dict:
    """Pull a quick, cheap summary of the job's input for the trace."""
    try:
        client = get_client()
        rows = client.query(
            """
            SELECT count(), sum(monthly_amount), min(first_seen), max(last_seen)
            FROM transactions
            WHERE job_id = {j:String}
            """,
            parameters={"j": job_id},
        ).result_rows
        if not rows:
            return {"job_id": job_id}
        vendor_count, monthly_total, first_seen, last_seen = rows[0]
        return {
            "job_id": job_id,
            "vendor_count": int(vendor_count or 0),
            "monthly_spend": float(monthly_total or 0),
            "window": f"{first_seen}..{last_seen}",
        }
    except Exception as e:
        log.warning("trace input summary failed: %s", e)
        return {"job_id": job_id}


def _stage_tag(vendor_count: int) -> str:
    if vendor_count <= 25:
        return "stage:preseed"
    if vendor_count <= 50:
        return "stage:seed"
    return "stage:series-b+"


def run_job(job_id: str) -> None:
    """Top-level: runs the full Bless agent loop for one job."""
    job_input = _job_input_summary(job_id)
    with job_context(job_id, metadata=job_input):
        update_current_trace(
            input=job_input,
            tags=["bless", "csv-upload", _stage_tag(job_input.get("vendor_count", 0))],
        )
        try:
            set_job_status(job_id, "investigating")
            with trace_span(
                "investigate", trace_id=job_id, metadata=job_input
            ) as span:
                n = investigator.investigate_job(job_id)
                if span is not None:
                    try:
                        span.update(output={"vendors_enriched": n})
                    except Exception:
                        pass

            set_job_status(job_id, "detecting")
            with trace_span("detect_waste", trace_id=job_id) as span:
                f = detector.detect_job(job_id)
                if span is not None:
                    try:
                        span.update(output={"flags_found": f})
                    except Exception:
                        pass

            set_job_status(job_id, "reporting")
            with trace_span("generate_report", trace_id=job_id):
                # build_report is idempotent — main.py rebuilds on each GET
                # so the orchestrator only needs to mark the job complete.
                reporter.build_report(job_id)

            set_job_status(job_id, "complete")
            update_current_trace(
                output={
                    "vendors_enriched": n,
                    "flags_found": f,
                    "status": "complete",
                }
            )
        except Exception as e:
            log.exception("Job %s failed: %s", job_id, e)
            set_job_status(job_id, "failed", error=str(e))
            log_event(
                "step.failed",
                {"job_id": job_id, "error": str(e), "error_type": type(e).__name__},
            )
            update_current_trace(
                output={"status": "failed", "error": str(e)},
                tags=["bless", "csv-upload", "error"],
            )
            raise
