"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ActionList } from "@/components/ActionList";
import { AppShell } from "@/components/AppShell";
import { SourceFilter } from "@/components/SourceFilter";
import { SpendDonut } from "@/components/SpendDonut";
import {
  cacheReport,
  getJobId,
  getReport,
  getStatus,
  money,
  readCachedReport,
  Report,
} from "@/lib/api";

// Sources present across all action items, in a stable order.
function reportSources(report: Report): string[] {
  const seen = new Set<string>();
  for (const g of report.action_groups) {
    for (const it of g.items) seen.add(it.source);
  }
  return [...seen].sort();
}

const PRIORITY_BUCKET: Record<string, "critical" | "medium" | "easy"> = {
  HIGH: "critical",
  MEDIUM: "medium",
  LOW: "easy",
};

// Drop excluded sources and recompute the figures derived from action items so
// the savings/issue numbers stay consistent with what's shown.
function applySourceFilter(report: Report, excluded: string[]): Report {
  if (excluded.length === 0) return report;
  const drop = new Set(excluded);

  const action_groups = report.action_groups.map((g) => {
    const items = g.items.filter((it) => !drop.has(it.source));
    return {
      ...g,
      items,
      total_savings: items.reduce((s, it) => s + it.monthly_savings, 0),
    };
  });

  const items = action_groups.flatMap((g) => g.items);
  const potential = items.reduce((s, it) => s + it.monthly_savings, 0);
  const issues = { total: items.length, critical: 0, medium: 0, easy: 0 };
  for (const it of items) issues[PRIORITY_BUCKET[it.priority]] += 1;

  return {
    ...report,
    action_groups,
    potential_monthly_savings: potential,
    annual_savings: potential * 12,
    issues_found: issues,
  };
}

const POLL_INTERVAL_MS = 3000;

export default function DashboardPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [stale, setStale] = useState(false);
  const [pendingStatus, setPendingStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [excludedSources, setExcludedSources] = useState<string[]>([]);

  useEffect(() => {
    const id = getJobId();
    setJobId(id);
    if (!id) {
      setError("no-job");
      return;
    }

    // Optimistic render: paint cached report immediately if available.
    const cached = readCachedReport(id);
    if (cached) {
      setReport(cached.report);
      setStale(!cached.fresh);
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = () => {
      getStatus(id)
        .then((s) => {
          if (cancelled) return;
          if (s.status === "failed") {
            setError(s.error ?? "Job failed");
            return;
          }
          if (s.status === "complete") {
            return getReport(id).then((r) => {
              if (cancelled) return;
              cacheReport(id, r);
              setReport(r);
              setStale(false);
              setPendingStatus(null);
              setError(null);
            });
          }
          setPendingStatus(s.status);
          timer = setTimeout(tick, POLL_INTERVAL_MS);
        })
        .catch((e) => {
          if (cancelled) return;
          setError(e instanceof Error ? e.message : "Failed to load status");
        });
    };
    tick();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const sources = useMemo(() => (report ? reportSources(report) : []), [report]);
  const filtered = useMemo(
    () => (report ? applySourceFilter(report, excludedSources) : null),
    [report, excludedSources],
  );

  if (error === "no-job") {
    return (
      <AppShell>
        <Empty />
      </AppShell>
    );
  }

  if (!report || !filtered) {
    return (
      <AppShell>
        <div className="grid min-h-full place-items-center text-neutral-400">
          {error ?? (pendingStatus ? `Analyzing your spend… (${pendingStatus})` : "Loading report…")}
        </div>
      </AppShell>
    );
  }

  const issues = filtered.issues_found;

  const toggleSource = (s: string) =>
    setExcludedSources((prev) =>
      prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s],
    );

  const refreshing = pendingStatus !== null && !error;

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-8 py-8">
        {(stale || refreshing) && (
          <div className="mb-4 flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-700">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
            {stale && !refreshing && "Showing previous audit. Upload a new CSV to refresh."}
            {refreshing && stale && `Showing previous audit while we re-analyze… (${pendingStatus})`}
            {refreshing && !stale && `Refreshing in background… (${pendingStatus})`}
          </div>
        )}
        {/* header */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold">Savings Report</h1>
            <p className="text-sm text-neutral-400">Based on your upload · {report.generated_at}</p>
          </div>
          <div className="flex items-center gap-3">
            <SourceFilter sources={sources} excluded={excludedSources} onToggle={toggleSource} />
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[#fef2f2] px-3 py-1 text-sm font-medium text-[#ef4444]">
              ⚠ {issues.total} issue{issues.total === 1 ? "" : "s"} found
            </span>
          </div>
        </div>

        {/* summary cards */}
        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Monthly Spend" value={`$${money(report.total_monthly_spend)}`} sub={`across ${report.vendor_count} vendors`} icon="$" />
          <Stat label="Potential Savings" value={`$${money(filtered.potential_monthly_savings)}/mo`} sub={`$${money(filtered.annual_savings)}/year`} icon="↘" accent />
          <Stat label="Annual Savings" value={`$${money(filtered.annual_savings)}`} sub="ROI in first month" icon="📅" green />
          <Stat
            label="Issues Found"
            value={`${issues.total}`}
            sub={`${issues.critical} critical · ${issues.medium} medium · ${issues.easy} easy`}
            icon="⚠"
            amber
          />
        </div>

        {/* highlight banner */}
        <div className="mt-5 flex flex-col gap-2 rounded-2xl bg-neutral-900 px-7 py-6 text-white sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-xs uppercase tracking-wide text-neutral-400">Savings highlighted</div>
            <div className="mt-1 text-3xl font-bold text-[#ff5a4d]">
              ${money(filtered.potential_monthly_savings)}
              <span className="text-base font-normal text-neutral-400">/month</span>
            </div>
            <div className="mt-1 text-sm text-neutral-400">
              is being wasted right now. Act on the 🔴 items today.
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm text-neutral-400">= ${money(filtered.annual_savings)}/year</div>
            <div className="font-semibold">a full engineer&apos;s tools budget</div>
          </div>
        </div>

        {/* main grid */}
        <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
          <div className="rounded-2xl border border-neutral-200 bg-white p-6 lg:self-start">
            <h2 className="text-lg font-semibold">Spend by Category</h2>
            <p className="mb-5 text-sm text-neutral-400">
              Flagged categories in <span className="text-[#ef4444]">red</span>
            </p>
            <SpendDonut categories={report.categories} />
          </div>
          <ActionList groups={filtered.action_groups} jobId={jobId!} />
        </div>
      </div>
    </AppShell>
  );
}

function Stat({
  label,
  value,
  sub,
  icon,
  accent,
  green,
  amber,
}: {
  label: string;
  value: string;
  sub: string;
  icon: string;
  accent?: boolean;
  green?: boolean;
  amber?: boolean;
}) {
  const valueColor = accent ? "text-[#ef4444]" : green ? "text-emerald-600" : amber ? "text-amber-500" : "text-neutral-900";
  const iconBg = accent ? "bg-[#fef2f2]" : green ? "bg-emerald-50" : amber ? "bg-amber-50" : "bg-neutral-100";
  return (
    <div className="rounded-2xl border border-neutral-200 bg-white p-5">
      <div className="flex items-center gap-2">
        <span className={`grid h-7 w-7 place-items-center rounded-lg text-sm ${iconBg}`}>{icon}</span>
        <span className="text-xs font-medium uppercase tracking-wide text-neutral-400">{label}</span>
      </div>
      <div className={`mt-3 text-2xl font-bold ${valueColor}`}>{value}</div>
      <div className="mt-1 text-xs text-neutral-400">{sub}</div>
    </div>
  );
}

function Empty() {
  return (
    <div className="grid min-h-full place-items-center px-6 text-center">
      <div>
        <h1 className="text-2xl font-bold">No report yet</h1>
        <p className="mt-2 text-neutral-500">Upload a CSV or connect a billing account to get started.</p>
        <div className="mt-6 flex justify-center gap-3">
          <Link href="/" className="rounded-lg bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700">
            New Upload
          </Link>
          <Link href="/connections" className="rounded-lg border border-neutral-300 px-4 py-2 text-sm font-medium hover:bg-neutral-50">
            Connect billing
          </Link>
        </div>
      </div>
    </div>
  );
}
