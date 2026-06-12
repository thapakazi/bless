"""Per-vendor usage investigator.

For the top-N vendors by spend, run a Claude tool-use loop that can:
- web_search:        Anthropic server-side search (current pricing, seat patterns)
- web_fetch:         Anthropic server-side fetch (pricing pages, docs)
- query_usage_data:  client-side ClickHouse lookup for any Airbyte-synced
                     tables that mention this vendor (Gmail billing emails,
                     GitHub activity, etc.)

The agent's job: estimate paid vs active seats, summarize usage at this spend
level, and produce one piece of waste evidence with a dollar figure. Output
is a JSON object merged on top of the seed-only enrichment.

For vendors below the top-N cutoff we skip the tool-use loop and rely on the
cheaper static enricher (saves tokens + wall-clock).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic
from anthropic.types import TextBlockParam

from ..config import get_settings
from ..db.clickhouse import get_client as get_ch
from ..llm import claude
from . import vendor_seed

log = logging.getLogger("bless.investigator")

# Number of top-spend vendors that get the full tool-use investigation.
TOP_N_INVESTIGATE = 5

# How many tool-iterations per vendor before we force a final answer.
MAX_TOOL_ROUNDS = 4


INVESTIGATOR_ROLE = """You are Bless, an investigative SaaS usage analyst auditing a
startup's spend. For one vendor at a time you must estimate:

1. How many seats / licenses the customer is paying for at the given spend.
2. How many of those seats are likely active vs. unused.
3. A one-sentence usage summary at this price tier.
4. ONE piece of evidence-based waste reasoning with a dollar figure.

You have three tools, used SPARINGLY (1-3 calls TOTAL per vendor, never more):
- web_search: search the public web for the vendor's current pricing page,
  typical seat counts at this monthly spend, or recent product news.
- web_fetch: fetch a specific URL (e.g. the vendor's pricing page).
- query_usage_data: check our internal database for any usage data we've
  already ingested via Airbyte for this vendor (Gmail billing emails, GitHub
  activity, Slack admin export, etc.). Try this BEFORE web_search if a
  vendor likely emits its own usage signal.

Be decisive. If a search returns enough signal, STOP — don't chain searches.

Return your FINAL answer as a single JSON object, no prose, no code fences:
{
  "category": "infra | devtools | productivity | comms | design | observability | marketing | support | analytics | data | security | finance | ai | other",
  "current_plan": "string (best guess plan name at this spend)",
  "lower_plan": "string or null",
  "lower_plan_cost": number,
  "annual_monthly_equivalent": number,
  "has_startup_credits": boolean,
  "startup_credits_url": "string or null",
  "cancel_url": "string or null",
  "downgrade_url": "string or null",
  "estimated_paid_seats": integer or null,
  "estimated_active_seats": integer or null,
  "utilization_pct": integer (0-100) or null,
  "usage_summary": "1-2 sentences",
  "waste_evidence": "1 sentence with a $ figure",
  "sources": ["url1", "url2"]
}

Rules:
- Use null when you genuinely don't know — never invent URLs or numbers.
- annual_monthly_equivalent = annual-billing price / 12 for the CURRENT plan.
- For utilization_pct, ground in your seat estimate: active / paid * 100.
"""


def _seed_blob() -> str:
    return json.dumps(vendor_seed.SEED, indent=2, sort_keys=True)


def _system_blocks() -> list[TextBlockParam]:
    """Same caching pattern as the static enricher — role + seed reference,
    cache_control on the last block."""
    return [
        {"type": "text", "text": INVESTIGATOR_ROLE},
        {
            "type": "text",
            "text": (
                "VENDOR REFERENCE (curated facts on well-known vendors; prefer "
                "these where available):\n" + _seed_blob()
            ),
            "cache_control": {"type": "ephemeral"},
        },
    ]


# --- client-side tool: query_usage_data -----------------------------------

QUERY_USAGE_TOOL = {
    "name": "query_usage_data",
    "description": (
        "Look up any Airbyte-synced usage data for this vendor. Returns up "
        "to 20 rows from any user table whose name contains the vendor "
        "slug. Use BEFORE web_search when a vendor likely emits its own "
        "usage signal (e.g. github commits, gmail billing receipts)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "vendor_slug": {
                "type": "string",
                "description": "lowercase vendor name, e.g. 'datadog'",
            },
            "limit": {
                "type": "integer",
                "description": "max rows to return (default 10, max 50)",
            },
        },
        "required": ["vendor_slug"],
    },
}


def _exec_query_usage_data(args: dict) -> str:
    slug = (args.get("vendor_slug") or "").lower()
    limit = min(int(args.get("limit") or 10), 50)
    if not slug:
        return json.dumps({"error": "vendor_slug required"})
    ch = get_ch()
    s = get_settings()
    db = s.clickhouse_db
    # List tables in our DB that look like Airbyte-landed vendor data.
    tables = ch.query(
        "SELECT name FROM system.tables WHERE database = {d:String} "
        "AND name NOT IN ('transactions','enriched_vendors','waste_flags','jobs')",
        parameters={"d": db},
    ).result_rows
    matches: dict[str, list] = {}
    for (tname,) in tables:
        if slug in tname.lower():
            try:
                rows = ch.query(
                    f"SELECT * FROM `{db}`.`{tname}` LIMIT {limit}"
                ).result_rows
                matches[tname] = [list(r) for r in rows]
            except Exception as e:
                matches[tname] = [{"error": str(e)}]
    if not matches:
        return json.dumps(
            {"hits": [], "note": f"no airbyte-synced tables found for '{slug}'"}
        )
    return json.dumps({"hits": matches}, default=str)[:8000]


# --- main loop ------------------------------------------------------------


def investigate_one(vendor_name: str, monthly_amount: float) -> dict:
    """Run the tool-use loop for one vendor. Returns merged enrichment dict.

    Falls back to seed-only on any failure (so a flaky search doesn't break
    the audit).
    """
    if not claude.is_available():
        return _seed_only(vendor_name)

    s = get_settings()
    client = anthropic.Anthropic(api_key=s.anthropic_api_key)
    model = s.claude_model_enricher

    tools = [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": 3},
        QUERY_USAGE_TOOL,
    ]

    user = (
        f"Vendor: {vendor_name}\n"
        f"Monthly spend: ${monthly_amount:.2f}\n\n"
        "Investigate. Use at most 1-3 tool calls. Return the JSON object."
    )
    messages: list[dict] = [{"role": "user", "content": user}]

    final_text = ""
    total_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }

    try:
        for round_idx in range(MAX_TOOL_ROUNDS):
            resp = claude.messages_create_traced(
                client=client,
                name=f"investigate:{vendor_name}:r{round_idx}",
                model=model,
                max_tokens=1500,
                system=_system_blocks(),
                tools=tools,
                messages=messages,
                metadata={
                    "role": "investigator",
                    "vendor_name": vendor_name,
                    "round": round_idx,
                    "monthly_amount": monthly_amount,
                },
            )
            _accum(total_usage, resp.usage)

            # Gather any client-side tool_use blocks we need to satisfy.
            tool_use_blocks = [
                b for b in resp.content if getattr(b, "type", "") == "tool_use"
            ]
            if not tool_use_blocks or resp.stop_reason == "end_turn":
                final_text = _first_text(resp.content)
                break

            # echo assistant turn
            messages.append({"role": "assistant", "content": resp.content})

            tool_results = []
            for tu in tool_use_blocks:
                # web_search is server-side and is handled by Anthropic — we
                # never see it here. Only our custom tool needs execution.
                if tu.name == "query_usage_data":
                    try:
                        out = _exec_query_usage_data(tu.input)
                    except Exception as e:
                        out = json.dumps({"error": str(e)})
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": out,
                        }
                    )
            if not tool_results:
                # only server-side tools fired this round; keep going.
                final_text = _first_text(resp.content)
                continue
            messages.append({"role": "user", "content": tool_results})
        else:
            # ran out of rounds
            log.warning("investigator hit MAX_TOOL_ROUNDS for %s", vendor_name)
    except Exception as e:
        log.warning("investigator failed for %s (%s); seed fallback", vendor_name, e)
        return _seed_only(vendor_name)

    parsed = _parse_json_loose(final_text)
    log.info(
        "investigate %s usage=%s tool_rounds<=%d sources=%d",
        vendor_name,
        {k: v for k, v in total_usage.items() if v},
        MAX_TOOL_ROUNDS,
        len(parsed.get("sources") or []),
    )
    return _merge_with_seed(vendor_name, parsed)


def _accum(acc: dict, u) -> None:
    acc["input_tokens"] += u.input_tokens or 0
    acc["output_tokens"] += u.output_tokens or 0
    acc["cache_creation_input_tokens"] += u.cache_creation_input_tokens or 0
    acc["cache_read_input_tokens"] += u.cache_read_input_tokens or 0


def _first_text(content) -> str:
    for b in content:
        if getattr(b, "type", "") == "text":
            return b.text
    return ""


def _parse_json_loose(raw: str) -> dict[str, Any]:
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b > a:
        try:
            return json.loads(s[a : b + 1])
        except json.JSONDecodeError:
            return {}
    return {}


def _seed_only(vendor_name: str) -> dict:
    seed = vendor_seed.lookup(vendor_name) or {}
    return _shape({**seed, "category": seed.get("category") or "other"})


def _merge_with_seed(vendor_name: str, llm: dict) -> dict:
    seed = vendor_seed.lookup(vendor_name) or {}
    # Seed wins on plan/category/url fields; LLM provides the usage signals.
    seed_authoritative = {
        k: v for k, v in seed.items()
        if v is not None and k in {
            "category", "current_plan", "lower_plan", "lower_plan_cost",
            "annual_monthly_equivalent", "has_startup_credits",
            "startup_credits_url", "cancel_url", "downgrade_url",
        }
    }
    merged = {**llm, **seed_authoritative}
    return _shape(merged, sources=llm.get("sources") or [])


def _shape(d: dict, sources: list | None = None) -> dict:
    util = d.get("utilization_pct")
    return {
        "category": (d.get("category") or "other"),
        "current_plan": (d.get("current_plan") or "Unknown"),
        "lower_plan": (d.get("lower_plan") or ""),
        "lower_plan_cost": float(d.get("lower_plan_cost") or 0.0),
        "annual_monthly_equivalent": float(d.get("annual_monthly_equivalent") or 0.0),
        "has_startup_credits": bool(d.get("has_startup_credits") or False),
        "startup_credits_url": (d.get("startup_credits_url") or ""),
        "cancel_url": (d.get("cancel_url") or ""),
        "downgrade_url": (d.get("downgrade_url") or ""),
        "estimated_paid_seats": int(d.get("estimated_paid_seats") or -1) if d.get("estimated_paid_seats") not in (None, "") else -1,
        "estimated_active_seats": int(d.get("estimated_active_seats") or -1) if d.get("estimated_active_seats") not in (None, "") else -1,
        "utilization_pct": int(util) if isinstance(util, (int, float)) else -1,
        "usage_summary": (d.get("usage_summary") or ""),
        "waste_evidence": (d.get("waste_evidence") or ""),
        "investigation_sources": ", ".join(sources or d.get("investigation_sources_list") or []),
    }


# --- batch ----------------------------------------------------------------


def investigate_job(job_id: str) -> int:
    """Run investigation on the top-N vendors by monthly spend, seed-only on
    the rest. Returns rows inserted into enriched_vendors.
    """
    ch = get_ch()
    rows = ch.query(
        """
        SELECT vendor_name, monthly_amount
        FROM transactions
        WHERE job_id = {j:String}
        ORDER BY monthly_amount DESC
        """,
        parameters={"j": job_id},
    ).result_rows
    if not rows:
        return 0

    enriched: list[list] = []
    for idx, (vendor_name, monthly_amount) in enumerate(rows):
        if idx < TOP_N_INVESTIGATE:
            e = investigate_one(vendor_name, float(monthly_amount))
        else:
            e = _seed_only(vendor_name)
        enriched.append(
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
                e["estimated_paid_seats"],
                e["estimated_active_seats"],
                e["utilization_pct"],
                e["usage_summary"],
                e["waste_evidence"],
                e["investigation_sources"],
            ]
        )

    ch.command(
        "DELETE FROM enriched_vendors WHERE job_id = {j:String}",
        parameters={"j": job_id},
    )
    ch.insert(
        "enriched_vendors",
        enriched,
        column_names=[
            "job_id", "vendor_name", "category", "current_plan", "lower_plan",
            "lower_plan_cost", "annual_monthly_equivalent",
            "has_startup_credits", "startup_credits_url", "cancel_url",
            "downgrade_url", "estimated_paid_seats", "estimated_active_seats",
            "utilization_pct", "usage_summary", "waste_evidence",
            "investigation_sources",
        ],
    )
    return len(enriched)
