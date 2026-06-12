Build a full-stack AI agent application called Bless — a SaaS spend 
auditor for startups. The app takes a CSV of company SaaS transactions, 
runs an autonomous multi-step agent loop to detect waste, and outputs a 
prioritized savings report via an interactive dashboard.

---

## TECH STACK

Backend: Python (FastAPI)
Frontend: React + Tailwind CSS (use OpenUI components where possible)
Database: ClickHouse (for transaction storage and analytical queries)
Agent orchestration: Guild.ai SDK
LLM inference: Pioneer API (OpenAI-compatible endpoint)
Model serving: TrueFoundry (for the enrichment model endpoint)
Data ingestion: Airbyte SDK (Python)
Action execution: Composio SDK (Python)
Observability: Langfuse (Python SDK)
Deployment: Render (provide render.yaml)

---

## PROJECT STRUCTURE

bless/
├── backend/
│   ├── main.py                  # FastAPI app entrypoint
│   ├── agent/
│   │   ├── orchestrator.py      # Guild.ai agent loop
│   │   ├── parser.py            # CSV ingestion + normalization
│   │   ├── enricher.py          # Per-vendor enrichment via TrueFoundry/Pioneer
│   │   ├── detector.py          # Waste pattern detection logic
│   │   └── reporter.py          # Final report generation via Pioneer LLM
│   ├── db/
│   │   ├── clickhouse.py        # ClickHouse client + schema setup
│   │   └── queries.py           # All analytical SQL queries
│   ├── integrations/
│   │   ├── airbyte.py           # Airbyte ingestion connector
│   │   ├── composio.py          # Composio action execution (Jira, Slack)
│   │   └── langfuse.py          # Langfuse tracing setup
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── UploadZone.jsx   # CSV drag-and-drop upload
│   │   │   ├── Bless.jsx      # Main report dashboard
│   │   │   ├── SpendChart.jsx   # Donut chart of spend by category
│   │   │   ├── ActionList.jsx   # Prioritized red/yellow/green action items
│   │   │   ├── SummaryBar.jsx   # Total spend + savings opportunity banner
│   │   │   └── ChatBox.jsx      # Follow-up Q&A chat with the agent
│   │   └── index.jsx
│   ├── package.json
│   └── tailwind.config.js
├── render.yaml                  # Render deployment config
├── .env.example                 # All required env vars listed
└── README.md

---

## BACKEND — DETAILED IMPLEMENTATION

### 1. FastAPI endpoints (main.py)

POST /api/upload
- Accepts a CSV file upload
- Passes it to parser.py for normalization
- Stores normalized records in ClickHouse
- Triggers the Guild.ai agent loop asynchronously
- Returns a job_id

GET /api/report/{job_id}
- Returns the current status of an analysis job
- Once complete, returns the full Bless report JSON

POST /api/chat
- Body: { job_id, message }
- Passes the message + full report context to Pioneer LLM
- Returns a streamed answer (Server-Sent Events)

POST /api/action
- Body: { job_id, action_type, vendor }
- Triggers a Composio action: "create_ticket" | "send_slack" | "open_billing"
- Returns action result

### 2. CSV Parser (parser.py)

Accept CSV with columns: date, description, amount, currency
Normalize vendor names using a lookup + LLM fallback:
- Strip payment processor prefixes (AMZN, GOOGLE *, STRIPE:, etc.)
- Deduplicate same-vendor multiple rows
- Infer billing frequency from date patterns (monthly/annual/one-time)
- Convert all amounts to USD monthly equivalent
- Output: list of { vendor_name, monthly_amount, frequency, raw_description, dates[] }

### 3. ClickHouse Schema (clickhouse.py)

Create these tables on startup if they don't exist:

transactions (
  job_id String,
  vendor_name String,
  monthly_amount Float64,
  frequency String,
  first_seen Date,
  last_seen Date,
  raw_description String
)

enriched_vendors (
  job_id String,
  vendor_name String,
  category String,
  current_plan String,
  lower_plan String,
  lower_plan_cost Float64,
  annual_monthly_equivalent Float64,
  has_startup_credits Bool,
  startup_credits_url String,
  cancel_url String,
  downgrade_url String
)

waste_flags (
  job_id String,
  vendor_name String,
  flag_type String,   -- GHOST | OVERPROVISION | DUPLICATE | ANNUAL_SAVINGS | STARTUP_CREDITS
  priority String,    -- HIGH | MEDIUM | LOW
  monthly_savings Float64,
  reasoning String,
  action_label String,
  action_url String
)

### 4. Guild.ai Agent Loop (orchestrator.py)

Define a Guild.ai agent with the following sequential steps:

STEP 1 — ENRICH (parallel across all vendors)
  For each vendor in transactions:
    Call enricher.py → get category, plan info, credits, URLs
    Write result to enriched_vendors in ClickHouse
    Trace with Langfuse: span name "enrich_{vendor_name}"

STEP 2 — DETECT WASTE
  Call detector.py with full enriched_vendors dataset
  Apply these rules:
    GHOST: vendor monthly_amount > 0, category is productivity/dev-tools,
           and no usage signal available → flag HIGH
    OVERPROVISION: current_plan_cost > lower_plan_cost * 1.5 → flag MEDIUM
    DUPLICATE: two vendors in same category → flag MEDIUM (keep cheaper one)
    ANNUAL_SAVINGS: frequency == 'monthly' AND annual discount > 20% → flag LOW
    STARTUP_CREDITS: has_startup_credits == true → flag LOW
  Write all flags to waste_flags in ClickHouse
  Trace with Langfuse: span name "detect_waste"

STEP 3 — GENERATE REPORT
  Query ClickHouse for all flags, sorted by monthly_savings DESC
  Call reporter.py → Pioneer LLM generates the summary narrative
  Return full report object:
  {
    job_id,
    total_monthly_spend,
    total_savings_opportunity,
    savings_percentage,
    vendor_count,
    flags: [ ...waste_flags ],
    narrative_summary: "...",
    top_action: "..."  // single best action for today
  }
  Trace entire run with Langfuse: root span "bless_run"

### 5. Enricher (enricher.py)

For each vendor, call TrueFoundry-hosted model with this prompt:

  "You are a SaaS pricing expert. Given a vendor name and monthly spend,
   return a JSON object with these fields:
   - category: string (e.g. 'devtools', 'productivity', 'infra', 'comms', 'analytics')
   - current_plan: string (best guess plan name)
   - lower_plan: string (next cheaper plan name, or null)
   - lower_plan_cost: number (monthly cost of lower plan, or null)
   - annual_monthly_equivalent: number (cost if billed annually / 12, or null)
   - has_startup_credits: boolean
   - startup_credits_url: string or null
   - cancel_url: string or null
   - downgrade_url: string or null

   Vendor: {vendor_name}
   Monthly spend: ${monthly_amount}

   Return ONLY valid JSON, no explanation."

Fall back to Pioneer API if TrueFoundry call fails.
Cache results in ClickHouse enriched_vendors to avoid duplicate calls.

### 6. Composio Actions (composio.py)

Implement three actions:

create_ticket(vendor, savings, reasoning):
  Use Composio Linear/Jira integration
  Title: "💸 Cancel {vendor} — save ${savings}/month"
  Description: reasoning
  Label: "cost-savings"

send_slack(report_summary):
  Use Composio Slack integration
  Channel: #finance or #general (configurable via env var SLACK_CHANNEL)
  Message: formatted Bless report with top 5 actions

open_billing(vendor, url):
  Log the action + return the URL for frontend to open in new tab

All actions logged to Langfuse as events on the active trace.

### 7. Langfuse Setup (langfuse.py)

Initialize Langfuse client from env vars.
Export a decorator @trace(name) that wraps any function as a Langfuse span.
Export a log_event(name, metadata) helper for point-in-time events.
Attach job_id as the trace ID so all spans for one run are grouped.

---

## FRONTEND — DETAILED IMPLEMENTATION

### UploadZone.jsx
Drag-and-drop CSV upload area.
Shows accepted file format hint: "Export from Ramp, Brex, Mercury, or any bank CSV"
On upload, POST to /api/upload, store returned job_id in state.
Show a progress indicator with animated steps:
  "📥 Ingesting data..." → "🔍 Enriching vendors..." → "🧠 Detecting waste..." → "📊 Building your Bless"

### SummaryBar.jsx
Top banner showing:
  Total Monthly Spend: $X,XXX
  Potential Savings: $X,XXX/mo  (in bold red)
  That's $XX,XXX/year you could keep
  Issues Found: N

### SpendChart.jsx
Donut chart (use Recharts) showing spend breakdown by category.
Color code: red for flagged vendors, gray for clean ones.

### ActionList.jsx
Three sections with colored left-border cards:
  🔴 Kill These First
  🟡 Right-Size These  
  🟢 Easy Wins
Each card shows:
  - Vendor name + logo (use Clearbit logo API: logo.clearbit.com/{domain})
  - Monthly cost
  - Savings amount
  - One-line reason
  - Action button: "Create Ticket" | "Open Billing" | "Apply for Credits"
    → calls POST /api/action on click

### ChatBox.jsx
Floating chat panel (bottom right).
Placeholder: "Ask me anything — 'What if we cut everything red?' or 'Find open-source alternatives'"
Streams responses from POST /api/chat using SSE.
Maintains conversation history in state.

---

## ENVIRONMENT VARIABLES (.env.example)

# ClickHouse
CLICKHOUSE_HOST=
CLICKHOUSE_PORT=8123
CLICKHOUSE_DB=bless
CLICKHOUSE_USER=
CLICKHOUSE_PASSWORD=

# Pioneer (LLM inference)
PIONEER_API_KEY=
PIONEER_BASE_URL=
PIONEER_MODEL=

# TrueFoundry (model serving)
TRUEFOUNDRY_ENDPOINT=
TRUEFOUNDRY_API_KEY=

# Guild.ai (agent orchestration)
GUILD_API_KEY=

# Airbyte (data ingestion)
AIRBYTE_API_KEY=
AIRBYTE_WORKSPACE_ID=

# Composio (action execution)
COMPOSIO_API_KEY=
SLACK_CHANNEL=#general

# Langfuse (observability)
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com

---

## SAMPLE CSV (for demo/testing)

Create a file sample_data/demo.csv with realistic startup spend data:

date,description,amount,currency
2026-01-05,NOTION.SO,96.00,USD
2026-01-07,GITHUB,21.00,USD
2026-01-10,AWS,1240.00,USD
2026-01-12,ZOOM,149.90,USD
2026-01-12,GOOGLE MEET - GSUITE,12.00,USD
2026-01-15,FIGMA,75.00,USD
2026-01-15,SKETCH,12.00,USD
2026-01-18,DATADOG,399.00,USD
2026-01-20,NEW RELIC OBSERVABILITY,349.00,USD
2026-01-22,SLACK,87.50,USD
2026-01-25,INTERCOM,149.00,USD
2026-01-28,HUBSPOT,890.00,USD
2026-01-28,MAILCHIMP,130.00,USD
2026-01-30,VERCEL,200.00,USD
2026-01-30,NETLIFY,19.00,USD
2026-02-05,NOTION.SO,96.00,USD
2026-02-07,GITHUB,21.00,USD
2026-02-10,AWS,1189.00,USD
2026-02-12,ZOOM,149.90,USD
2026-02-12,GOOGLE MEET - GSUITE,12.00,USD
2026-02-15,FIGMA,75.00,USD
2026-02-15,SKETCH,12.00,USD
2026-02-18,DATADOG,399.00,USD
2026-02-20,NEW RELIC OBSERVABILITY,349.00,USD
2026-02-22,SLACK,87.50,USD
2026-02-28,HUBSPOT,890.00,USD
2026-02-28,MAILCHIMP,130.00,USD
2026-02-30,VERCEL,200.00,USD

(Note: Intercom missing in Feb — ghost sub candidate. Sketch + Figma = duplicate. 
Datadog + New Relic = duplicate. Zoom + Google Meet = duplicate. 
Netlify missing in Feb = possible cancellation opportunity.)

---

## RENDER DEPLOYMENT (render.yaml)

Generate a render.yaml that defines:
- A web service for the FastAPI backend (Python, port 8000)
- A static site for the React frontend
- Environment variable groups pointing to the .env keys above
- Health check endpoint: GET /health on the backend

---

## README.md

Write a README that includes:
1. One-line description of Bless
2. The problem it solves (2-3 sentences)
3. Architecture diagram (ASCII)
4. Sponsor tools used and why (one line each)
5. Setup instructions (clone → install → set .env → run)
6. How to demo it (upload demo.csv → walk through report → use chat)
7. Hackathon prize categories targeted

---

## BUILD ORDER

Build in this sequence so the app is always in a runnable state:

1. Set up ClickHouse schema and client (db/)
2. Build CSV parser and store to ClickHouse (parser.py + basic FastAPI upload endpoint)
3. Build enricher with Pioneer fallback (no TrueFoundry dependency yet)
4. Build waste detector with all 5 flag types
5. Build reporter (report generation prompt + /api/report endpoint)
6. Wire Guild.ai orchestrator around steps 3-5
7. Add Langfuse tracing to all steps
8. Add Composio actions (/api/action endpoint)
9. Add Airbyte connector as alternative ingestion path
10. Build React frontend (UploadZone → SummaryBar → ActionList → SpendChart)
11. Add ChatBox with streaming
12. Add TrueFoundry as primary enrichment endpoint (Pioneer as fallback)
13. Write render.yaml and README
14. Test end-to-end with demo.csv

---

## DEMO SCRIPT (for the 3-minute hackathon demo)

Comment this into README.md:

0:00 — Show the upload screen. "A startup CFO exports their Ramp transactions. One CSV."
0:15 — Drop demo.csv. Show the animated progress steps.
0:40 — Report appears. Show the SummaryBar: "$3,891/month. $1,847 recoverable."
1:00 — Walk the 🔴 section: "Intercom — only one charge, likely forgotten. $149/month."
1:20 — Walk the 🟡 section: "Datadog AND New Relic. Pick one, save $349/month."
1:40 — Click "Create Ticket" on Datadog. Show Jira/Linear ticket created live.
2:00 — Open ChatBox. Type: "What's the cheapest way to run our monitoring stack?"
2:20 — Show streamed answer with specific alternatives.
2:40 — Show Langfuse trace in a split screen — "every decision is auditable."
3:00 — End: "Bless. Your CFO's 11pm shortcut."
