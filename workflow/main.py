"""Render Workflows entrypoint — wraps the agent loop as a task.

Run locally: `uv run python -m workflow.main` (after `RENDER_API_KEY` is set).
On Render: deployed as a Workflow service. Triggered from backend `/api/upload`.
"""

from __future__ import annotations

import logging

from render_sdk import Workflows

from backend.agent.orchestrator import run_job as _run_job

log = logging.getLogger("bless.workflow")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = Workflows()


@app.task
def run_job(job_id: str) -> dict:
    log.info("workflow run_job start job_id=%s", job_id)
    _run_job(job_id)
    log.info("workflow run_job done job_id=%s", job_id)
    return {"job_id": job_id, "status": "complete"}


if __name__ == "__main__":
    app.start()
