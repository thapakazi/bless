"use client";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { JobSummary, listJobs, setJobId } from "@/lib/api";
import { useRouter } from "next/navigation";

const IN_FLIGHT = new Set(["ingested", "investigating", "detecting", "reporting"]);
const POLL_INTERVAL_MS = 5000;

const STATUS_STYLE: Record<string, string> = {
  ingested: "bg-neutral-100 text-neutral-600",
  investigating: "bg-amber-50 text-amber-600",
  detecting: "bg-amber-50 text-amber-600",
  reporting: "bg-amber-50 text-amber-600",
  complete: "bg-emerald-50 text-emerald-600",
  failed: "bg-[#fef2f2] text-[#ef4444]",
};

export default function JobsPage() {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = () => {
      listJobs()
        .then((js) => {
          if (cancelled) return;
          setJobs(js);
          setError(null);
          const anyInFlight = js.some((j) => IN_FLIGHT.has(j.status));
          if (anyInFlight) timer = setTimeout(tick, POLL_INTERVAL_MS);
        })
        .catch((e) => {
          if (cancelled) return;
          setError(e instanceof Error ? e.message : "Failed to load jobs");
          timer = setTimeout(tick, POLL_INTERVAL_MS);
        });
    };
    tick();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-8 py-8">
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-bold">Jobs</h1>
            <p className="text-sm text-neutral-400">
              Recent audits and their pipeline status. In-flight jobs refresh every 5s.
            </p>
          </div>
        </div>

        {error && (
          <div className="mt-4 rounded-lg bg-[#fef2f2] px-4 py-3 text-sm text-[#ef4444]">
            {error}
          </div>
        )}

        <div className="mt-6 overflow-hidden rounded-2xl border border-neutral-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 text-left text-xs font-medium uppercase tracking-wide text-neutral-500">
              <tr>
                <th className="px-5 py-3">Job</th>
                <th className="px-5 py-3">Status</th>
                <th className="px-5 py-3">Vendors</th>
                <th className="px-5 py-3">Started</th>
                <th className="px-5 py-3">Updated</th>
                <th className="px-5 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100">
              {jobs == null ? (
                <tr>
                  <td colSpan={6} className="px-5 py-8 text-center text-neutral-400">
                    Loading jobs…
                  </td>
                </tr>
              ) : jobs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-5 py-8 text-center text-neutral-400">
                    No jobs yet. Upload a CSV to get started.
                  </td>
                </tr>
              ) : (
                jobs.map((j) => (
                  <tr key={j.job_id} className="hover:bg-neutral-50">
                    <td className="px-5 py-3 font-mono text-xs text-neutral-500" title={j.job_id}>
                      {j.job_id.slice(0, 12)}…
                    </td>
                    <td className="px-5 py-3">
                      <span
                        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
                          STATUS_STYLE[j.status] ?? "bg-neutral-100 text-neutral-600"
                        }`}
                      >
                        {IN_FLIGHT.has(j.status) && (
                          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
                        )}
                        {j.status}
                      </span>
                      {j.error && (
                        <div className="mt-1 text-xs text-[#ef4444]" title={j.error}>
                          {j.error.length > 80 ? j.error.slice(0, 80) + "…" : j.error}
                        </div>
                      )}
                    </td>
                    <td className="px-5 py-3 text-neutral-600">{j.vendor_count}</td>
                    <td className="px-5 py-3 text-xs text-neutral-500" title={j.started_at ?? ""}>
                      {fmt(j.started_at)}
                    </td>
                    <td className="px-5 py-3 text-xs text-neutral-500" title={j.updated_at ?? ""}>
                      {fmt(j.updated_at)}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <button
                        onClick={() => {
                          setJobId(j.job_id);
                          router.push("/dashboard");
                        }}
                        className="rounded-lg border border-neutral-200 px-3 py-1.5 text-xs font-medium hover:bg-neutral-50"
                      >
                        Open
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </AppShell>
  );
}

function fmt(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const now = new Date();
  const sec = Math.round((now.getTime() - d.getTime()) / 1000);
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`;
  return d.toLocaleString();
}
