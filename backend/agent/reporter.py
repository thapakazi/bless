"""Reporter — assembles the final Bless object and asks Claude to write the
narrative + top_action. Falls back to a templated narrative if no API key.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..db.clickhouse import get_client
from ..llm import claude

log = logging.getLogger("bless.reporter")


# Map internal HIGH/MEDIUM/LOW priorities → frontend action_group buckets.
_GROUP_META = {
    "HIGH": {"key": "kill", "label": "Critical — cut these now", "color": "red"},
    "MEDIUM": {"key": "rightsize", "label": "Rightsize", "color": "yellow"},
    "LOW": {"key": "easy", "label": "Easy wins", "color": "green"},
}


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


# Compound or non-obvious vendor → domain mappings. Frontend renders logos via
# google.com/s2/favicons, which needs the actual marketing domain.
_VENDOR_DOMAINS = {
    "apple developer": "developer.apple.com",
    "google workspace": "workspace.google.com",
    "google meet": "meet.google.com",
    "google cloud": "cloud.google.com",
    "aws": "aws.amazon.com",
    "amazon web services": "aws.amazon.com",
    "new relic": "newrelic.com",
    "new relic observability": "newrelic.com",
    "hubspot": "hubspot.com",
    "github": "github.com",
    "gitlab": "gitlab.com",
    "notion": "notion.so",
    "vercel": "vercel.com",
    "netlify": "netlify.com",
    "supabase": "supabase.com",
    "sentry": "sentry.io",
    "datadog": "datadoghq.com",
    "intercom": "intercom.com",
    "slack": "slack.com",
    "zoom": "zoom.us",
    "figma": "figma.com",
    "sketch": "sketch.com",
    "mailchimp": "mailchimp.com",
    "linear": "linear.app",
    "stripe": "stripe.com",
}


def _guess_domain(vendor: str) -> str:
    key = vendor.lower().strip()
    if key in _VENDOR_DOMAINS:
        return _VENDOR_DOMAINS[key]
    # Fallback: collapse whitespace, lowercase, append .com. Works for single-word
    # SaaS vendors; missing rows render initials in the frontend.
    return key.replace(" ", "") + ".com"


def _vendor_meta(job_id: str) -> dict[str, dict]:
    client = get_client()
    rows = client.query(
        """
        SELECT t.vendor_name, t.monthly_amount,
               if(e.category = '', 'other', e.category) AS category
        FROM transactions AS t
        LEFT JOIN enriched_vendors AS e
          ON t.job_id = e.job_id AND t.vendor_name = e.vendor_name
        WHERE t.job_id = {j:String}
        """,
        parameters={"j": job_id},
    ).result_rows
    return {
        r[0]: {"monthly_amount": float(r[1] or 0), "category": r[2] or "other"}
        for r in rows
    }


def build_frontend_report(job_id: str) -> dict:
    """Adapter: reshape build_report() output into the dashboard's expected shape.

    The frontend Report contract lives in frontend/src/lib/api.ts. Keeping the
    transform server-side lets the UI stay declarative.
    """
    base = build_report(job_id)
    flags = base["flags"]
    spend = base["total_monthly_spend"]
    savings = base["total_savings_opportunity"]
    vendor_meta = _vendor_meta(job_id)

    # issues_found counts by priority bucket
    pcount = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in flags:
        p = (f.get("priority") or "MEDIUM").upper()
        if p in pcount:
            pcount[p] += 1
    issues_found = {
        "total": len(flags),
        "critical": pcount["HIGH"],
        "medium": pcount["MEDIUM"],
        "easy": pcount["LOW"],
    }

    # categories rollup: sum monthly_amount per category; mark flagged if any
    # vendor in that category has at least one waste flag.
    flagged_vendors = {f["vendor_name"] for f in flags}
    cat_totals: dict[str, float] = {}
    cat_flagged: dict[str, bool] = {}
    for v, meta in vendor_meta.items():
        c = meta["category"]
        cat_totals[c] = cat_totals.get(c, 0.0) + meta["monthly_amount"]
        cat_flagged[c] = cat_flagged.get(c, False) or (v in flagged_vendors)
    categories = sorted(
        [
            {"category": c, "amount": round(t, 2), "flagged": cat_flagged[c]}
            for c, t in cat_totals.items()
        ],
        key=lambda x: x["amount"],
        reverse=True,
    )

    # action_groups: bucket flags into kill/rightsize/easy
    buckets: dict[str, list[dict]] = {"HIGH": [], "MEDIUM": [], "LOW": []}
    for f in flags:
        p = (f.get("priority") or "MEDIUM").upper()
        if p not in buckets:
            p = "MEDIUM"
        meta = vendor_meta.get(
            f["vendor_name"], {"monthly_amount": 0.0, "category": "other"}
        )
        buckets[p].append(
            {
                "vendor_name": f["vendor_name"],
                "domain": _guess_domain(f["vendor_name"]),
                "category": meta["category"],
                "monthly_amount": meta["monthly_amount"],
                "flag_type": f["flag_type"],
                "priority": p,
                "monthly_savings": f["monthly_savings"],
                "reasoning": f["reasoning"],
                "action_label": f["action_label"],
                "action_url": f["action_url"],
                "source": "csv",
            }
        )
    action_groups = []
    for p in ("HIGH", "MEDIUM", "LOW"):
        meta = _GROUP_META[p]
        items = sorted(buckets[p], key=lambda x: x["monthly_savings"], reverse=True)
        action_groups.append(
            {
                "key": meta["key"],
                "label": meta["label"],
                "priority": p,
                "color": meta["color"],
                "total_savings": round(sum(i["monthly_savings"] for i in items), 2),
                "items": items,
            }
        )

    return {
        "job_id": job_id,
        "status": "complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_monthly_spend": spend,
        "potential_monthly_savings": savings,
        "annual_savings": round(savings * 12, 2),
        "vendor_count": base["vendor_count"],
        "issues_found": issues_found,
        "categories": categories,
        "action_groups": action_groups,
        "narrative_summary": base.get("narrative_summary", ""),
        "top_action": base.get("top_action", ""),
    }
