"""Waste detector — five rules applied to (transactions JOIN enriched_vendors).

Rules (from prompt.md):
- GHOST: monthly_amount > 0, category in {productivity, devtools, comms},
  AND last_seen is more than 30 days before the latest charge in the dataset
  (proxy for "no usage signal — likely forgotten") → HIGH
- OVERPROVISION: current plan cost > lower_plan cost * 1.5 → MEDIUM
- DUPLICATE: two or more vendors in the same category → MEDIUM
  (savings = sum of cheaper ones; action keeps the largest)
- ANNUAL_SAVINGS: frequency == 'monthly' AND annual price gives >20% discount
  → LOW
- STARTUP_CREDITS: has_startup_credits == True → LOW (full monthly amount
  recoverable)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta

from ..db.clickhouse import get_client

log = logging.getLogger("bless.detector")

GHOST_CATEGORIES = {"productivity", "devtools", "comms", "marketing"}
GHOST_LOOKBACK_DAYS = 30


def _fetch_joined(job_id: str) -> list[dict]:
    """Return per-vendor rows joined with enrichment."""
    client = get_client()
    rows = client.query(
        """
        SELECT
            t.vendor_name        AS vendor_name,
            t.monthly_amount     AS monthly_amount,
            t.frequency          AS frequency,
            t.first_seen         AS first_seen,
            t.last_seen          AS last_seen,
            e.category           AS category,
            e.current_plan       AS current_plan,
            e.lower_plan         AS lower_plan,
            e.lower_plan_cost    AS lower_plan_cost,
            e.annual_monthly_equivalent AS annual_monthly_equivalent,
            e.has_startup_credits AS has_startup_credits,
            e.startup_credits_url AS startup_credits_url,
            e.cancel_url          AS cancel_url,
            e.downgrade_url       AS downgrade_url,
            e.estimated_paid_seats   AS estimated_paid_seats,
            e.estimated_active_seats AS estimated_active_seats,
            e.utilization_pct        AS utilization_pct,
            e.usage_summary          AS usage_summary,
            e.waste_evidence         AS waste_evidence
        FROM transactions AS t
        LEFT JOIN enriched_vendors AS e
            ON t.job_id = e.job_id AND t.vendor_name = e.vendor_name
        WHERE t.job_id = {job_id:String}
        ORDER BY t.monthly_amount DESC
        """,
        parameters={"job_id": job_id},
    )
    cols = result_cols = [c for c in rows.column_names]
    return [dict(zip(cols, r)) for r in rows.result_rows]


def _ghost(v: dict, dataset_latest) -> dict | None:
    """A ghost sub is paid-for but unused.

    Strongest signal: the investigator concluded utilization == 0.
    Weaker fallback: vendor in a usage-sensitive category AND last charge
    is more than GHOST_LOOKBACK_DAYS before the dataset's latest charge
    (i.e. they stopped showing up on the bank statement).
    """
    if v["monthly_amount"] <= 0:
        return None

    util = v.get("utilization_pct")
    active = v.get("estimated_active_seats")
    by_util = util is not None and util != -1 and util <= 5
    by_active = active is not None and active != -1 and active == 0

    if by_util or by_active:
        reasoning = (
            v.get("waste_evidence")
            or v.get("usage_summary")
            or f"{v['vendor_name']} appears unused. Full ${v['monthly_amount']:.0f}/mo recoverable."
        )
        return {
            "flag_type": "GHOST",
            "priority": "HIGH",
            "monthly_savings": float(v["monthly_amount"]),
            "reasoning": reasoning,
            "action_label": "Cancel",
            "action_url": v.get("cancel_url") or "",
        }

    cat = (v.get("category") or "").lower()
    if cat not in GHOST_CATEGORIES:
        return None
    if v["last_seen"] is None or dataset_latest is None:
        return None
    gap = (dataset_latest - v["last_seen"]).days
    if gap < GHOST_LOOKBACK_DAYS:
        return None
    return {
        "flag_type": "GHOST",
        "priority": "HIGH",
        "monthly_savings": float(v["monthly_amount"]),
        "reasoning": (
            f"{v['vendor_name']} last charged {v['last_seen']} ({gap} days ago) "
            f"— likely a forgotten subscription. Full ${v['monthly_amount']:.0f}/mo "
            f"recoverable."
        ),
        "action_label": "Cancel",
        "action_url": v.get("cancel_url") or "",
    }


def _unused_seats(v: dict) -> dict | None:
    """Investigator-driven: paid seats >> active seats, but not zero."""
    paid = v.get("estimated_paid_seats") or -1
    active = v.get("estimated_active_seats") or -1
    if paid <= 0 or active < 0:
        return None
    if active >= paid:
        return None
    unused = paid - active
    if unused < 2 or (unused / paid) < 0.25:
        return None
    per_seat = float(v["monthly_amount"]) / max(paid, 1)
    savings = round(per_seat * unused, 2)
    reasoning = (
        v.get("waste_evidence")
        or (
            f"{v['vendor_name']}: {active}/{paid} seats active ({100*active//paid}% utilization). "
            f"Deprovision {unused} unused seats at ~${per_seat:.0f}/seat → save ${savings:.0f}/mo."
        )
    )
    return {
        "flag_type": "UNUSED_SEATS",
        "priority": "HIGH" if unused / paid >= 0.5 else "MEDIUM",
        "monthly_savings": savings,
        "reasoning": reasoning,
        "action_label": "Deprovision seats",
        "action_url": v.get("downgrade_url") or v.get("cancel_url") or "",
    }


def _overprovision(v: dict) -> dict | None:
    current = float(v["monthly_amount"])
    lower = float(v.get("lower_plan_cost") or 0.0)
    if lower <= 0 or current <= lower * 1.5:
        return None
    savings = round(current - lower, 2)
    return {
        "flag_type": "OVERPROVISION",
        "priority": "MEDIUM",
        "monthly_savings": savings,
        "reasoning": (
            f"{v['vendor_name']} is on '{v.get('current_plan') or 'current plan'}' at "
            f"${current:.0f}/mo. '{v.get('lower_plan') or 'a cheaper tier'}' at "
            f"${lower:.0f}/mo likely covers the actual usage."
        ),
        "action_label": "Downgrade",
        "action_url": v.get("downgrade_url") or "",
    }


def _annual_savings(v: dict) -> dict | None:
    if v["frequency"] != "monthly":
        return None
    monthly = float(v["monthly_amount"])
    annual_eq = float(v.get("annual_monthly_equivalent") or 0.0)
    if annual_eq <= 0 or monthly <= 0:
        return None
    discount = (monthly - annual_eq) / monthly
    if discount < 0.20:
        return None
    savings = round(monthly - annual_eq, 2)
    return {
        "flag_type": "ANNUAL_SAVINGS",
        "priority": "LOW",
        "monthly_savings": savings,
        "reasoning": (
            f"{v['vendor_name']} bills monthly at ${monthly:.0f}. Annual billing "
            f"costs ${annual_eq:.0f}/mo equivalent — save {discount*100:.0f}% by "
            f"switching."
        ),
        "action_label": "Switch to annual",
        "action_url": v.get("downgrade_url") or v.get("cancel_url") or "",
    }


def _startup_credits(v: dict) -> dict | None:
    if not v.get("has_startup_credits"):
        return None
    return {
        "flag_type": "STARTUP_CREDITS",
        "priority": "LOW",
        "monthly_savings": float(v["monthly_amount"]),
        "reasoning": (
            f"{v['vendor_name']} runs a startup-credits program. If eligible, "
            f"you could recover the full ${v['monthly_amount']:.0f}/mo."
        ),
        "action_label": "Apply for credits",
        "action_url": v.get("startup_credits_url") or "",
    }


def _duplicates(vendors: list[dict]) -> list[dict]:
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for v in vendors:
        cat = (v.get("category") or "").lower()
        if not cat or cat == "other":
            continue
        by_cat[cat].append(v)

    flags = []
    for cat, group in by_cat.items():
        if len(group) < 2:
            continue
        group_sorted = sorted(
            group, key=lambda x: x["monthly_amount"], reverse=True
        )
        keep = group_sorted[0]
        drop = group_sorted[1:]
        savings = round(sum(v["monthly_amount"] for v in drop), 2)
        names = ", ".join(v["vendor_name"] for v in group_sorted)
        for v in drop:
            flags.append(
                {
                    "flag_type": "DUPLICATE",
                    "priority": "MEDIUM",
                    "vendor_name": v["vendor_name"],
                    "monthly_savings": float(v["monthly_amount"]),
                    "reasoning": (
                        f"Overlap in '{cat}': {names}. Consolidating on "
                        f"{keep['vendor_name']} drops {v['vendor_name']} "
                        f"(save ${v['monthly_amount']:.0f}/mo). Group total: "
                        f"${savings:.0f}/mo."
                    ),
                    "action_label": "Cancel",
                    "action_url": v.get("cancel_url") or "",
                }
            )
    return flags


def detect_job(job_id: str) -> int:
    """Run all five rules. Writes flags to ClickHouse, returns count."""
    vendors = _fetch_joined(job_id)
    if not vendors:
        return 0

    dataset_latest = max(
        (v["last_seen"] for v in vendors if v["last_seen"] is not None),
        default=None,
    )

    # collect flags. one vendor may produce multiple flags of different types.
    out = []
    for v in vendors:
        ghost = _ghost(v, dataset_latest)
        if ghost:
            ghost.setdefault("vendor_name", v["vendor_name"])
            out.append(ghost)
            # if it's a ghost, skip the other "you're paying too much" flags —
            # the answer is just to cancel.
            continue
        for rule in (_unused_seats, _overprovision, _annual_savings, _startup_credits):
            f = rule(v)
            if f:
                f.setdefault("vendor_name", v["vendor_name"])
                out.append(f)
    out.extend(_duplicates(vendors))

    if not out:
        log.info("detect job=%s no flags", job_id)
        _replace_flags(job_id, [])
        return 0

    rows = [
        [
            job_id,
            f["vendor_name"],
            f["flag_type"],
            f["priority"],
            float(f["monthly_savings"]),
            f["reasoning"],
            f["action_label"],
            f["action_url"],
        ]
        for f in out
    ]
    _replace_flags(job_id, rows)
    log.info("detect job=%s flags=%d", job_id, len(rows))
    return len(rows)


def _replace_flags(job_id: str, rows: list[list]) -> None:
    client = get_client()
    client.command(
        "DELETE FROM waste_flags WHERE job_id = {j:String}",
        parameters={"j": job_id},
    )
    if rows:
        client.insert(
            "waste_flags",
            rows,
            column_names=[
                "job_id",
                "vendor_name",
                "flag_type",
                "priority",
                "monthly_savings",
                "reasoning",
                "action_label",
                "action_url",
            ],
        )
