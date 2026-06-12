// API client for the Bless FastAPI backend.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export interface ActionItem {
  vendor_name: string;
  domain: string;
  category: string;
  monthly_amount: number;
  flag_type: string;
  priority: "HIGH" | "MEDIUM" | "LOW";
  monthly_savings: number;
  reasoning: string;
  action_label: string;
  action_url: string;
  source: string;
}

export interface ActionGroup {
  key: "kill" | "rightsize" | "easy";
  label: string;
  priority: "HIGH" | "MEDIUM" | "LOW";
  color: "red" | "yellow" | "green";
  total_savings: number;
  items: ActionItem[];
}

export interface Category {
  category: string;
  amount: number;
  flagged: boolean;
}

export interface Report {
  job_id: string;
  status: string;
  generated_at: string;
  total_monthly_spend: number;
  potential_monthly_savings: number;
  annual_savings: number;
  vendor_count: number;
  issues_found: { total: number; critical: number; medium: number; easy: number };
  categories: Category[];
  action_groups: ActionGroup[];
}

export interface Provider {
  provider: string;
  label: string;
  credential_fields: string[];
  is_stub: boolean;
}

export interface Connection {
  provider: string;
  status: string;
  account: string;
  is_stub: boolean;
  error: string;
  vendor_count: number;
}

const JOB_KEY = "bless_job_id";

export function getJobId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(JOB_KEY);
}

export function setJobId(id: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(JOB_KEY, id);
  window.dispatchEvent(new Event("bless:job"));
}

export function clearJob() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(JOB_KEY);
  window.dispatchEvent(new Event("bless:job"));
}

async function asError(res: Response): Promise<never> {
  let detail = res.statusText;
  try {
    const body = await res.json();
    detail = body.detail ?? body.error ?? detail;
  } catch {
    /* ignore */
  }
  throw new Error(detail);
}

export async function uploadCsv(file: File | Blob): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append("file", file, "upload.csv");
  const res = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: form });
  if (!res.ok) return asError(res);
  return res.json();
}

export async function getReport(jobId: string): Promise<Report> {
  const res = await fetch(`${API_BASE}/api/report/${jobId}`);
  if (!res.ok) return asError(res);
  return res.json();
}

export async function getProviders(): Promise<Provider[]> {
  const res = await fetch(`${API_BASE}/api/providers`);
  if (!res.ok) return asError(res);
  return (await res.json()).providers;
}

export async function connectProvider(
  provider: string,
  credentials: Record<string, string>,
  jobId?: string | null,
): Promise<{ job_id: string; connection: Connection; vendor_count: number }> {
  const res = await fetch(`${API_BASE}/api/connect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, credentials, job_id: jobId ?? null }),
  });
  if (!res.ok) return asError(res);
  return res.json();
}

export async function getConnections(
  jobId: string,
): Promise<{ sources: string[]; connected_providers: string[] }> {
  const res = await fetch(`${API_BASE}/api/connections/${jobId}`);
  if (!res.ok) return asError(res);
  return res.json();
}

export async function runAction(
  jobId: string,
  actionType: string,
  vendor: string,
  url?: string,
): Promise<{ status: string; ticket_id?: string; url?: string; message?: string }> {
  const res = await fetch(`${API_BASE}/api/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_id: jobId, action_type: actionType, vendor, url }),
  });
  if (!res.ok) return asError(res);
  return res.json();
}

export function money(n: number): string {
  return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

// Bundled demo dataset so "load the demo dataset" works with no file picker.
export const DEMO_CSV = `date,description,amount,currency
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
2026-02-28,VERCEL,200.00,USD
`;
