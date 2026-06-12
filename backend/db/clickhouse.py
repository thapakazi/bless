from __future__ import annotations

from datetime import date
from typing import Iterable

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from ..config import get_settings


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS transactions (
        job_id           String,
        vendor_name      String,
        monthly_amount   Float64,
        frequency        String,
        first_seen       Date,
        last_seen        Date,
        raw_description  String,
        ingested_at      DateTime DEFAULT now()
    )
    ENGINE = MergeTree
    ORDER BY (job_id, vendor_name)
    """,
    """
    CREATE TABLE IF NOT EXISTS enriched_vendors (
        job_id                      String,
        vendor_name                 String,
        category                    String,
        current_plan                String,
        lower_plan                  String,
        lower_plan_cost             Float64,
        annual_monthly_equivalent   Float64,
        has_startup_credits         UInt8,
        startup_credits_url         String,
        cancel_url                  String,
        downgrade_url               String,
        enriched_at                 DateTime DEFAULT now()
    )
    ENGINE = MergeTree
    ORDER BY (job_id, vendor_name)
    """,
    """
    CREATE TABLE IF NOT EXISTS waste_flags (
        job_id           String,
        vendor_name      String,
        flag_type        String,
        priority         String,
        monthly_savings  Float64,
        reasoning        String,
        action_label     String,
        action_url       String,
        flagged_at       DateTime DEFAULT now()
    )
    ENGINE = MergeTree
    ORDER BY (job_id, priority, vendor_name)
    """,
]


_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        s = get_settings()
        _client = clickhouse_connect.get_client(
            host=s.clickhouse_host,
            port=s.clickhouse_port,
            username=s.clickhouse_user,
            password=s.clickhouse_password,
            database=s.clickhouse_db,
        )
    return _client


def init_schema() -> None:
    client = get_client()
    for stmt in SCHEMA:
        client.command(stmt)


def insert_transactions(
    job_id: str,
    rows: Iterable[dict],
) -> int:
    """Insert normalized vendor rows. Returns count inserted."""
    client = get_client()
    data = []
    for r in rows:
        data.append(
            [
                job_id,
                r["vendor_name"],
                float(r["monthly_amount"]),
                r["frequency"],
                _to_date(r["first_seen"]),
                _to_date(r["last_seen"]),
                r.get("raw_description", ""),
            ]
        )
    if not data:
        return 0
    client.insert(
        "transactions",
        data,
        column_names=[
            "job_id",
            "vendor_name",
            "monthly_amount",
            "frequency",
            "first_seen",
            "last_seen",
            "raw_description",
        ],
    )
    return len(data)


def fetch_transactions(job_id: str) -> list[dict]:
    client = get_client()
    result = client.query(
        """
        SELECT vendor_name, monthly_amount, frequency,
               first_seen, last_seen, raw_description
        FROM transactions
        WHERE job_id = {job_id:String}
        ORDER BY monthly_amount DESC
        """,
        parameters={"job_id": job_id},
    )
    return [
        {
            "vendor_name": r[0],
            "monthly_amount": r[1],
            "frequency": r[2],
            "first_seen": r[3].isoformat() if r[3] else None,
            "last_seen": r[4].isoformat() if r[4] else None,
            "raw_description": r[5],
        }
        for r in result.result_rows
    ]


def _to_date(v) -> date:
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))
