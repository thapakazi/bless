#!/usr/bin/env bash
# Drive an upload -> agent loop -> report end-to-end against a running backend.
# Tolerant of transient 4xx/5xx during the polling window.

set -euo pipefail

CSV="${1:-sample_data/demo.csv}"
BASE="${BLESS_API:-http://localhost:8000}"

echo ">>> GET $BASE/health"
curl -sf "$BASE/health" | python3 -m json.tool

echo ">>> POST $BASE/api/upload  ($CSV)"
JOB=$(curl -sf -F "file=@${CSV}" "$BASE/api/upload" \
        | python3 -c 'import json,sys;print(json.load(sys.stdin)["job_id"])')
echo "job_id=$JOB"

printf "waiting for agent loop"
TIMEOUT=180  # seconds
START=$SECONDS
while :; do
    body=$(curl -s "$BASE/api/report/$JOB" || true)
    status=$(printf '%s' "$body" | python3 -c \
        'import json,sys
try:
    print(json.loads(sys.stdin.read()).get("status",""))
except Exception:
    print("")' 2>/dev/null || true)
    case "$status" in
        complete) echo " ready"; break ;;
        failed)   echo; echo "JOB FAILED"; printf '%s' "$body"; exit 1 ;;
        *)        printf "." ;;
    esac
    if (( SECONDS - START > TIMEOUT )); then
        echo; echo "TIMEOUT after ${TIMEOUT}s (last status='$status')"
        exit 1
    fi
    sleep 1
done

echo ">>> GET $BASE/api/report/$JOB"
curl -sf "$BASE/api/report/$JOB" > /tmp/bless_report.json
python3 <<'PY'
import json
r = json.load(open("/tmp/bless_report.json"))
spend = r["total_monthly_spend"]
savings = r["total_savings_opportunity"]
pct = r["savings_percentage"]
print()
print(f"SPEND:   ${spend:,.0f}/mo")
print(f"SAVINGS: ${savings:,.0f}/mo ({pct}%) -> ${savings*12:,.0f}/yr")
print(f"FLAGS:   {len(r['flags'])}")
print()
print("NARRATIVE:", r["narrative_summary"])
print("TOP_ACTION:", r["top_action"])
print()
print("--- TOP 10 FLAGS ---")
for f in r["flags"][:10]:
    print(f"{f['priority']:<6} {f['flag_type']:<15} {f['vendor_name']:<14} "
          f"${f['monthly_savings']:>7.0f}/mo  {f['reasoning'][:80]}")
PY
