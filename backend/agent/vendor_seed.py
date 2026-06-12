"""Curated SaaS vendor facts.

Used as the enricher's fallback when Pioneer is unavailable, and as
"ground truth" merged on top of Pioneer's output so demo flags are stable.

Keys are uppercased vendor names; match is case-insensitive.
"""

from __future__ import annotations


SEED: dict[str, dict] = {
    "AWS": {
        "category": "infra",
        "current_plan": "Pay-as-you-go",
        "lower_plan": None,
        "lower_plan_cost": 0.0,
        "annual_monthly_equivalent": 0.0,
        "has_startup_credits": True,
        "startup_credits_url": "https://aws.amazon.com/activate/",
        "cancel_url": "https://console.aws.amazon.com/billing/",
        "downgrade_url": "https://console.aws.amazon.com/cost-management/",
    },
    "GOOGLE MEET": {
        "category": "comms",
        "current_plan": "Business Standard",
        "lower_plan": "Business Starter",
        "lower_plan_cost": 6.0,
        "annual_monthly_equivalent": 10.0,
        "has_startup_credits": False,
        "startup_credits_url": None,
        "cancel_url": "https://admin.google.com/ac/billing",
        "downgrade_url": "https://admin.google.com/ac/billing/subscriptions",
    },
    "ZOOM": {
        "category": "comms",
        "current_plan": "Business",
        "lower_plan": "Pro",
        "lower_plan_cost": 14.99,
        "annual_monthly_equivalent": 119.90,
        "has_startup_credits": False,
        "startup_credits_url": None,
        "cancel_url": "https://zoom.us/billing",
        "downgrade_url": "https://zoom.us/billing/plan",
    },
    "DATADOG": {
        "category": "observability",
        "current_plan": "Pro",
        "lower_plan": "Free",
        "lower_plan_cost": 0.0,
        "annual_monthly_equivalent": 319.20,
        "has_startup_credits": True,
        "startup_credits_url": "https://www.datadoghq.com/partner/datadog-for-startups/",
        "cancel_url": "https://app.datadoghq.com/account/billing",
        "downgrade_url": "https://app.datadoghq.com/account/plan_and_usage",
    },
    "NEW RELIC": {
        "category": "observability",
        "current_plan": "Standard",
        "lower_plan": "Free",
        "lower_plan_cost": 0.0,
        "annual_monthly_equivalent": 279.20,
        "has_startup_credits": True,
        "startup_credits_url": "https://newrelic.com/startups",
        "cancel_url": "https://one.newrelic.com/-/admin/billing",
        "downgrade_url": "https://one.newrelic.com/-/admin/billing",
    },
    "FIGMA": {
        "category": "design",
        "current_plan": "Professional",
        "lower_plan": "Starter",
        "lower_plan_cost": 0.0,
        "annual_monthly_equivalent": 60.0,
        "has_startup_credits": False,
        "startup_credits_url": None,
        "cancel_url": "https://www.figma.com/settings/billing",
        "downgrade_url": "https://www.figma.com/settings/billing/plan",
    },
    "SKETCH": {
        "category": "design",
        "current_plan": "Standard",
        "lower_plan": None,
        "lower_plan_cost": 0.0,
        "annual_monthly_equivalent": 9.0,
        "has_startup_credits": False,
        "startup_credits_url": None,
        "cancel_url": "https://www.sketch.com/workspace/billing",
        "downgrade_url": None,
    },
    "NOTION": {
        "category": "productivity",
        "current_plan": "Business",
        "lower_plan": "Plus",
        "lower_plan_cost": 10.0,
        "annual_monthly_equivalent": 80.0,
        "has_startup_credits": True,
        "startup_credits_url": "https://www.notion.so/startups",
        "cancel_url": "https://www.notion.so/settings/billing",
        "downgrade_url": "https://www.notion.so/settings/plans",
    },
    "GITHUB": {
        "category": "devtools",
        "current_plan": "Team",
        "lower_plan": "Free",
        "lower_plan_cost": 0.0,
        "annual_monthly_equivalent": 16.80,
        "has_startup_credits": False,
        "startup_credits_url": None,
        "cancel_url": "https://github.com/settings/billing",
        "downgrade_url": "https://github.com/settings/billing/plans",
    },
    "SLACK": {
        "category": "comms",
        "current_plan": "Business+",
        "lower_plan": "Pro",
        "lower_plan_cost": 7.25,
        "annual_monthly_equivalent": 70.0,
        "has_startup_credits": False,
        "startup_credits_url": None,
        "cancel_url": "https://slack.com/account/team#billing",
        "downgrade_url": "https://slack.com/account/team#plan",
    },
    "INTERCOM": {
        "category": "support",
        "current_plan": "Starter",
        "lower_plan": None,
        "lower_plan_cost": 0.0,
        "annual_monthly_equivalent": 119.0,
        "has_startup_credits": True,
        "startup_credits_url": "https://www.intercom.com/early-stage",
        "cancel_url": "https://app.intercom.com/a/apps/_/settings/subscription",
        "downgrade_url": "https://app.intercom.com/a/apps/_/settings/subscription",
    },
    "HUBSPOT": {
        "category": "marketing",
        "current_plan": "Professional",
        "lower_plan": "Starter",
        "lower_plan_cost": 20.0,
        "annual_monthly_equivalent": 720.0,
        "has_startup_credits": True,
        "startup_credits_url": "https://www.hubspot.com/startups",
        "cancel_url": "https://app.hubspot.com/billing-management",
        "downgrade_url": "https://app.hubspot.com/billing-management/products",
    },
    "MAILCHIMP": {
        "category": "marketing",
        "current_plan": "Standard",
        "lower_plan": "Essentials",
        "lower_plan_cost": 13.0,
        "annual_monthly_equivalent": 104.0,
        "has_startup_credits": False,
        "startup_credits_url": None,
        "cancel_url": "https://mailchimp.com/billing/",
        "downgrade_url": "https://mailchimp.com/billing/plans/",
    },
    "VERCEL": {
        "category": "infra",
        "current_plan": "Pro",
        "lower_plan": "Hobby",
        "lower_plan_cost": 0.0,
        "annual_monthly_equivalent": 160.0,
        "has_startup_credits": True,
        "startup_credits_url": "https://vercel.com/startups",
        "cancel_url": "https://vercel.com/account/billing",
        "downgrade_url": "https://vercel.com/account/billing/plan",
    },
    "NETLIFY": {
        "category": "infra",
        "current_plan": "Pro",
        "lower_plan": "Starter",
        "lower_plan_cost": 0.0,
        "annual_monthly_equivalent": 15.20,
        "has_startup_credits": False,
        "startup_credits_url": None,
        "cancel_url": "https://app.netlify.com/teams/_/billing",
        "downgrade_url": "https://app.netlify.com/teams/_/billing",
    },
}


def lookup(vendor_name: str) -> dict | None:
    key = vendor_name.upper().strip()
    if key in SEED:
        return SEED[key]
    # try substring match on first word
    first = key.split()[0] if key else ""
    for k, v in SEED.items():
        if k.split()[0] == first:
            return v
    return None
