"""Reporter — assembles the final Bless object and asks Claude to write the
narrative + top_action. Falls back to a templated narrative if no API key.
"""

from __future__ import annotations

import logging

from ..db.clickhouse import get_client
from ..llm import claude

log = logging.getLogger("bless.reporter")


REPORTER_SYSTEM = """You are a calm, witty CFO co-pilot named Bless. You write
the narrative summary for a SaaS spend audit report.

Style: 2-3 short sentences. Sharp, specific, no fluff. Lead with the dollar
figure. End with momentum, not a hedge.

You also produce one "top_action" — the single highest-leverage move the user
should make today, in one imperative sentence with the dollar amount.

Always return ONLY a JSON object with exactly these two fields:
{"narrative_summary": "...", "top_action": "..."}
"""


def _query_totals(job_id: str) -> dict:
    client = get_client()
    spend_row = client.query(
        """
        SELECT count() AS vendor_count, sum(monthly_amount) AS total
        FROM transactions WHERE job_id = {j:String}
        """,
        parameters={"j": job_id},
    ).result_rows
    vendor_count, total_spend = (int(spend_row[0][0]), float(spend_row[0][1] or 0))

    flag_rows = client.query(
        """
        SELECT vendor_name, flag_type, priority, monthly_savings, reasoning,
               action_label, action_url
        FROM waste_flags
        WHERE job_id = {j:String}
        ORDER BY monthly_savings DESC
        """,
        parameters={"j": job_id},
    ).result_rows
    flags = [
        {
            "vendor_name": r[0],
            "flag_type": r[1],
            "priority": r[2],
            "monthly_savings": float(r[3]),
            "reasoning": r[4],
            "action_label": r[5],
            "action_url": r[6],
        }
        for r in flag_rows
    ]
    # de-dupe savings by vendor: a vendor may carry multiple flags but we
    # don't want to double-count its monthly_savings. Take the max per vendor.
    by_vendor: dict[str, float] = {}
    for f in flags:
        by_vendor[f["vendor_name"]] = max(
            by_vendor.get(f["vendor_name"], 0.0), f["monthly_savings"]
        )
    total_savings = round(sum(by_vendor.values()), 2)
    return {
        "vendor_count": vendor_count,
        "total_monthly_spend": round(total_spend, 2),
        "total_savings_opportunity": total_savings,
        "flags": flags,
    }


def _templated_narrative(d: dict) -> tuple[str, str]:
    spend = d["total_monthly_spend"]
    savings = d["total_savings_opportunity"]
    pct = (savings / spend * 100) if spend else 0
    flag_count = len(d["flags"])
    top = d["flags"][0] if d["flags"] else None
    narrative = (
        f"You're spending ${spend:,.0f}/month across {d['vendor_count']} "
        f"vendors. I found {flag_count} ways to cut ${savings:,.0f}/month "
        f"(~{pct:.0f}%). That's ${savings*12:,.0f}/year back in the bank."
    )
    if top:
        top_action = (
            f"{top['action_label']} {top['vendor_name']} — "
            f"${top['monthly_savings']:.0f}/mo recovered today."
        )
    else:
        top_action = "Your stack is lean. Re-run after next month's invoices."
    return narrative, top_action


def build_report(job_id: str) -> dict:
    base = _query_totals(job_id)
    spend = base["total_monthly_spend"]
    savings = base["total_savings_opportunity"]
    base["savings_percentage"] = (
        round(savings / spend * 100, 1) if spend else 0.0
    )

    if claude.is_available() and base["flags"]:
        try:
            narrative, top_action = claude.generate_report_narrative(
                REPORTER_SYSTEM, base
            )
            if not narrative or not top_action:
                raise ValueError("empty narrative or top_action")
        except Exception as e:
            log.warning("Claude reporter failed (%s); using template", e)
            narrative, top_action = _templated_narrative(base)
    else:
        narrative, top_action = _templated_narrative(base)

    return {
        "job_id": job_id,
        "status": "complete",
        **base,
        "narrative_summary": narrative,
        "top_action": top_action,
    }
