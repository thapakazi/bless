# Deploying Bless to Render

Three services on Render: **frontend** (Next.js), **backend** (FastAPI), and a
**workflow** (the agent loop, on Render Workflows). ClickHouse stays on
ClickHouse Cloud.

`render.yaml` declares the two web services; the workflow is created in the
dashboard because Render Workflows isn't yet a blueprint type.

## 1. Claim hackathon credits

<https://credits-portal-mmdm.onrender.com/claim/harness-engineering-hack>

If you don't have an account yet: <https://render.com/register>

## 2. Push this branch to GitHub

The blueprint needs to read `render.yaml` from a Git remote.

```bash
git push -u origin <your-branch>
```

## 3. Create the Blueprint

Render Dashboard → **New** → **Blueprint** → pick this repo → submit.

Render creates `bless-backend` and `bless-frontend` but leaves required secrets
empty — both services will fail their first deploy until you fill them in.

## 4. Fill in backend secrets

`bless-backend` → **Environment** tab. Paste from your local `.env`:

| Key | Value |
|---|---|
| `CLICKHOUSE_HOST` | `<your-host>.clickhouse.cloud` |
| `CLICKHOUSE_DB` | (your db name) |
| `CLICKHOUSE_USER` | (your user) |
| `CLICKHOUSE_PASSWORD` | (your password) |
| `ANTHROPIC_API_KEY` | `sk-ant-...` |
| `LANGFUSE_PUBLIC_KEY` | (optional) |
| `LANGFUSE_SECRET_KEY` | (optional) |
| `AIRBYTE_*` | (optional) |

Leave `RENDER_API_KEY` and `WORKFLOW_SLUG` blank for now — set them in step 6.

The backend will deploy successfully on its own (the workflow dispatch is
guarded; missing keys just mean it falls back to running the orchestrator
in-process, which works but doesn't qualify for the Workflows prize).

## 5. Set frontend `NEXT_PUBLIC_API_BASE`

`bless-frontend` → **Environment** tab → set
`NEXT_PUBLIC_API_BASE = https://bless-backend.onrender.com` (or whatever
hostname Render gave the backend; check the backend service page).

This is baked into the client bundle at build time, so the frontend needs a
fresh deploy after you set it. Click **Manual Deploy → Deploy latest commit**.

## 6. Create the Workflow service

Render Dashboard → **New** → **Workflow** (Beta).

| Setting | Value |
|---|---|
| Name | `bless-workflow` |
| Repo | this one |
| Branch | same as the blueprint |
| Root Directory | *(leave blank — repo root)* |
| Language | Python |
| Build Command | `pip install uv && uv pip install --system -r backend/requirements.txt` |
| Start Command | `python -m workflow.main` |

Add the same ClickHouse + Anthropic + Langfuse env vars from step 4 — the
workflow runs the agent loop and needs the same access as the backend.

After it deploys, copy its **slug** (the dashboard shows it; format is the
service name) and create a **Render API key** under Account → API Keys.

Back on `bless-backend` set:

- `RENDER_API_KEY` = the key from above
- `WORKFLOW_SLUG` = `bless-workflow` (or whatever Render assigned)

Redeploy the backend.

## 7. Verify

Upload `sample_data/demo.csv` via the frontend. The backend log should show:

```
Dispatched workflow run job_id=<...> run_id=trn-...
```

…and the workflow's run page should show `run_job` advancing through
`investigating → detecting → reporting → complete`.

## Local dev unchanged

`just dev` still works as-is — when `RENDER_API_KEY`/`WORKFLOW_SLUG` are unset
the backend falls back to the in-process `BackgroundTask`.
