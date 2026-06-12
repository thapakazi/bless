from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import median


# Only strip these when they appear as a *processor* prefix, not as the vendor itself.
# We require a separator (space, *, :) so "AWS" alone stays "AWS" but "AMZN MKTP US" loses "AMZN MKTP".
PROCESSOR_PREFIXES = [
    "AMZN MKTP ", "AMZN ",
    "GOOGLE *", "GOOGLE* ",
    "STRIPE:", "STRIPE*", "STRIPE ",
    "SQ *", "SQ* ",
    "PAYPAL *", "PAYPAL* ",
    "TST*", "TST *",
    "POS ", "POS*",
    "DEBIT ", "ACH ", "AUTOPAY ",
    "RECURRING ", "MONTHLY ", "ANNUAL ",
]

NOISE_SUFFIXES = [
    ".COM", ".IO", ".SO", ".AI", ".CO", ".NET", ".ORG",
    " INC", " LLC", " LTD", " CORP", " HQ", " USA",
    " OBSERVABILITY", " SUBSCRIPTION", " SOFTWARE", " - SUBSCRIPTION",
]

# Some descriptions are a parent-product compound — keep the recognisable brand
# instead of letting suffix-stripping eat it down to the generic part.
COMPOUND_REWRITES = {
    "GOOGLE MEET - GSUITE": "Google Meet",
    "GOOGLE MEET GSUITE": "Google Meet",
    "GOOGLE WORKSPACE": "Google Workspace",
    "GSUITE": "Google Workspace",
}

# Display these as all-caps even after title-casing.
ACRONYMS = {"AWS", "GCP", "IBM", "SAP", "HP", "AI", "API"}


@dataclass
class VendorAggregate:
    vendor_name: str
    raw_description: str
    dates: list[date] = field(default_factory=list)
    amounts: list[float] = field(default_factory=list)

    def monthly_amount(self) -> float:
        """Return USD monthly equivalent based on inferred frequency."""
        if not self.amounts:
            return 0.0
        freq = self.frequency()
        per_charge = float(median(self.amounts))
        if freq == "annual":
            return round(per_charge / 12.0, 2)
        if freq == "one-time":
            # amortize across observed window (min 1 month)
            return round(per_charge, 2)
        return round(per_charge, 2)

    def frequency(self) -> str:
        if len(self.dates) <= 1:
            return "one-time"
        sorted_dates = sorted(self.dates)
        gaps = [
            (b - a).days
            for a, b in zip(sorted_dates, sorted_dates[1:])
        ]
        if not gaps:
            return "one-time"
        med = median(gaps)
        if 20 <= med <= 45:
            return "monthly"
        if 300 <= med <= 400:
            return "annual"
        if med < 20:
            # multiple charges within a month → still monthly
            return "monthly"
        return "monthly"

    def to_row(self) -> dict:
        return {
            "vendor_name": self.vendor_name,
            "monthly_amount": self.monthly_amount(),
            "frequency": self.frequency(),
            "first_seen": min(self.dates),
            "last_seen": max(self.dates),
            "raw_description": self.raw_description,
        }


def normalize_vendor(description: str) -> str:
    s = description.upper().strip()
    if s in COMPOUND_REWRITES:
        return COMPOUND_REWRITES[s]
    for p in PROCESSOR_PREFIXES:
        if s.startswith(p):
            s = s[len(p):].strip()
            break
    if s in COMPOUND_REWRITES:
        return COMPOUND_REWRITES[s]
    # strip trailing reference numbers / store ids
    s = re.sub(r"\s*#?\d{3,}\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    for sfx in NOISE_SUFFIXES:
        if s.endswith(sfx):
            s = s[: -len(sfx)].strip()
    if not s:
        return description.strip()
    return " ".join(w if w in ACRONYMS else w.title() for w in s.split())


def _parse_date(v: str) -> date:
    v = v.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {v}")


def parse_csv(content: bytes | str) -> list[dict]:
    """Parse a Ramp/Brex/Mercury-style CSV.

    Expects columns (case-insensitive): date, description, amount, currency.
    Returns list of normalized vendor rows ready for ClickHouse insert.
    """
    if isinstance(content, bytes):
        text = content.decode("utf-8-sig", errors="replace")
    else:
        text = content

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    field_map = {f.lower().strip(): f for f in reader.fieldnames}
    required = {"date", "description", "amount"}
    missing = required - set(field_map)
    if missing:
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")

    aggregates: dict[str, VendorAggregate] = {}
    for row in reader:
        try:
            d = _parse_date(row[field_map["date"]])
            desc = row[field_map["description"]].strip()
            amt = float(row[field_map["amount"]])
        except (KeyError, ValueError):
            continue
        if not desc or amt <= 0:
            continue
        vendor = normalize_vendor(desc)
        agg = aggregates.get(vendor)
        if agg is None:
            agg = VendorAggregate(vendor_name=vendor, raw_description=desc)
            aggregates[vendor] = agg
        agg.dates.append(d)
        agg.amounts.append(amt)

    return [a.to_row() for a in aggregates.values()]
