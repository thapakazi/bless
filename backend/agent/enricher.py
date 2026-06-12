"""Per-vendor enrichment.

For each vendor in the audit:
1. Call Claude with a *shared, cached* system prompt that contains the
   curated vendor reference. The first call pays the cache write; the
   remaining 14 read at ~10% of input cost.
2. Merge with our `vendor_seed.SEED` dict — seed wins on known fields so
   the demo stays deterministic even if Claude hallucinates a plan name.
3. Write to `enriched_vendors` in ClickHouse (idempotent on job_id+vendor).

If ANTHROPIC_API_KEY is unset, fall back to seed-only enrichment.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from anthropic.types import TextBlockParam

from ..db.clickhouse import get_client
from ..llm import claude
from . import vendor_seed

log = logging.getLogger("bless.enricher")


ENRICHER_ROLE = """You are a SaaS pricing analyst helping a startup CFO audit
their software spend. For each vendor you're given, return a JSON object
describing the most likely plan tier, a cheaper alternative, annual-billing
savings, and whether the vendor runs a startup-credits program.

Output schema (return EXACTLY these fields, nothing else):
{
  "category": "infra" | "devtools" | "productivity" | "comms" | "design" |
              "observability" | "marketing" | "support" | "analytics" |
              "data" | "security" | "finance" | "ai" | "other",
  "current_plan": string,
  "lower_plan": string | null,
  "lower_plan_cost": number,
  "annual_monthly_equivalent": number,
  "has_startup_credits": boolean,
  "startup_credits_url": string | null,
  "cancel_url": string | null,
  "downgrade_url": string | null
}

Rules:
- Use null for unknown URLs, never invent.
- annual_monthly_equivalent = annual-billing price / 12 for the *current* plan.
- lower_plan_cost is the per-month price of the next cheaper tier.
- Return ONLY the JSON object, no prose, no code fences.
"""


def _seed_reference_blob() -> str:
    """Compact JSON dump of the curated vendor seed.

    Included verbatim in the system prompt so (a) Claude has authoritative
    facts on the demo vendors and (b) the prompt exceeds the 2048-token cache
    minimum on Sonnet 4.6.
    """
    payload = {k: v for k, v in vendor_seed.SEED.items()}
    return json.dumps(payload, indent=2, sort_keys=True)


def _build_system_blocks() -> list[TextBlockParam]:
    """System content with prompt-cache marker on the LAST block.

    Render order = role → reference data. Cache breakpoint goes on the
    reference blob so role + reference are cached as one prefix.
    """
    return [
        {"type": "text", "text": ENRICHER_ROLE},
        {
            "type": "text",
            "text": (
                "Below is curated reference for well-known vendors. When the "
                "user asks about one of these, prefer these facts. When asked "
                "about a vendor NOT in this list, use your best judgement.\n\n"
                "VENDOR REFERENCE:\n" + _seed_reference_blob()
            ),
            "cache_control": {"type": "ephemeral"},
        },
    ]


def _merge_with_seed(vendor_name: str, llm_result: dict) -> dict:
    """Seed wins on known fields; LLM fills the rest."""
    seed = vendor_seed.lookup(vendor_name) or {}
    merged = {**llm_result, **{k: v for k, v in seed.items() if v is not None}}
    # canonicalise types / defaults
    return {
        "category": (merged.get("category") or "other"),
        "current_plan": (merged.get("current_plan") or "Unknown"),
        "lower_plan": (merged.get("lower_plan") or ""),
        "lower_plan_cost": float(merged.get("lower_plan_cost") or 0.0),
        "annual_monthly_equivalent": float(
            merged.get("annual_monthly_equivalent") or 0.0
        ),
        "has_startup_credits": bool(merged.get("has_startup_credits") or False),
        "startup_credits_url": (merged.get("startup_credits_url") or ""),
        "cancel_url": (merged.get("cancel_url") or ""),
        "downgrade_url": (merged.get("downgrade_url") or ""),
    }


def _fallback_only_seed(vendor_name: str) -> dict:
    seed = vendor_seed.lookup(vendor_name)
    if seed:
        return _merge_with_seed(vendor_name, {})
    return _merge_with_seed(vendor_name, {"category": "other"})


def enrich_one(vendor_name: str, monthly_amount: float, system_blocks) -> dict:
    """Enrich a single vendor. Returns merged row dict."""
    if not claude.is_available():
        return _fallback_only_seed(vendor_name)

    user = f"Vendor: {vendor_name}\nMonthly spend: ${monthly_amount:.2f}"
    try:
        raw, usage = claude.enrich_vendor(
            system_blocks, user, vendor_name=vendor_name
        )
        log.info(
            "enrich %s usage=%s",
            vendor_name,
            {k: v for k, v in usage.items() if v},
        )
    except Exception as e:
        log.exception("Claude enrich failed for %s: %s", vendor_name, e)
        return _fallback_only_seed(vendor_name)
    return _merge_with_seed(vendor_name, raw)


def enrich_job(job_id: str) -> int:
    """Enrich every vendor for this job. Returns count enriched."""
    client = get_client()
    vendors = client.query(
        """
        SELECT vendor_name, monthly_amount
        FROM transactions
        WHERE job_id = {job_id:String}
        """,
        parameters={"job_id": job_id},
    ).result_rows
    if not vendors:
        return 0

    system_blocks = _build_system_blocks()
    rows: list[list[Any]] = []
    for vendor_name, monthly_amount in vendors:
        e = enrich_one(vendor_name, float(monthly_amount), system_blocks)
        rows.append(
            [
                job_id,
                vendor_name,
                e["category"],
                e["current_plan"],
                e["lower_plan"],
                e["lower_plan_cost"],
                e["annual_monthly_equivalent"],
                1 if e["has_startup_credits"] else 0,
                e["startup_credits_url"],
                e["cancel_url"],
                e["downgrade_url"],
            ]
        )

    # idempotent: clear previous attempt for this job_id then insert
    client.command(
        "DELETE FROM enriched_vendors WHERE job_id = {j:String}",
        parameters={"j": job_id},
    )
    client.insert(
        "enriched_vendors",
        rows,
        column_names=[
            "job_id",
            "vendor_name",
            "category",
            "current_plan",
            "lower_plan",
            "lower_plan_cost",
            "annual_monthly_equivalent",
            "has_startup_credits",
            "startup_credits_url",
            "cancel_url",
            "downgrade_url",
        ],
    )
    return len(rows)
