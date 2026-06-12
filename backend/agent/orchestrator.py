"""Agent loop — enrich → detect → report.

Runs as a FastAPI BackgroundTask. State is persisted in the `jobs` table so
/api/report can poll status while the loop is running.
"""

from __future__ import annotations

import logging

from ..db.clickhouse import set_job_status
from ..integrations.langfuse import log_event, trace_span
from . import detector, investigator, reporter

log = logging.getLogger("bless.orchestrator")


def run_job(job_id: str) -> None:
    """Top-level: runs the full Bless agent loop for one job."""
    with trace_span("bless_run", trace_id=job_id):
        try:
            set_job_status(job_id, "investigating")
            log_event("step.investigate.start", {"job_id": job_id})
            with trace_span("investigate", trace_id=job_id):
                n = investigator.investigate_job(job_id)
            log_event("step.investigate.done", {"job_id": job_id, "vendors": n})

            set_job_status(job_id, "detecting")
            log_event("step.detect.start", {"job_id": job_id})
            with trace_span("detect_waste", trace_id=job_id):
                f = detector.detect_job(job_id)
            log_event("step.detect.done", {"job_id": job_id, "flags": f})

            set_job_status(job_id, "reporting")
            log_event("step.report.start", {"job_id": job_id})
            with trace_span("generate_report", trace_id=job_id):
                # build_report is idempotent — main.py rebuilds on each GET
                # so the orchestrator only needs to mark the job complete.
                reporter.build_report(job_id)
            log_event("step.report.done", {"job_id": job_id})

            set_job_status(job_id, "complete")
        except Exception as e:
            log.exception("Job %s failed: %s", job_id, e)
            set_job_status(job_id, "failed", error=str(e))
            log_event("step.failed", {"job_id": job_id, "error": str(e)})
            raise
