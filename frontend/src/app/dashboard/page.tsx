"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ActionList } from "@/components/ActionList";
import { AppShell } from "@/components/AppShell";
import { SpendDonut } from "@/components/SpendDonut";
import { getJobId, getReport, money, Report } from "@/lib/api";

const IN_FLIGHT_STATUSES = new Set([
  "ingested",
  "enriching",
  "investigating",
  "detecting",
  "reporting",
]);

const POLL_INTERVAL_MS = 3000;

function isReportReady(r: Report): boolean {
  return !IN_FLIGHT_STATUSES.has(r.status) && r.issues_found != null;
}

export default function DashboardPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  useEffect(() => {
    const id = getJobId();
    setJobId(id);
    if (!id) {
      setError("no-job");
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = () => {
      getReport(id)
        .then((r) => {
          if (cancelled) return;
          setReport(r);
          setError(null);
          if (!isReportReady(r)) {
            timer = setTimeout(tick, POLL_INTERVAL_MS);
          }
        })
        .catch((e) => {
          if (cancelled) return;
          setError(e instanceof Error ? e.message : "Failed to load report");
        });
    };
    tick();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  if (error === "no-job") {
    return (
      <AppShell>
        <Empty />
      </AppShell>
    );
  }

  if (!report || !isReportReady(report)) {
    return (
      <AppShell>
        <div className="grid min-h-full place-items-center text-neutral-400">
          {error ?? (report ? `Analyzing your spend… (${report.status})` : "Loading report…")}
        </div>
      </AppShell>
    );
  }

  const issues = report.issues_found;

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-8 py-8">
        {/* header */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold">Savings Report</h1>
            <p className="text-sm text-neutral-400">Based on your upload · {report.generated_at}</p>
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-[#fef2f2] px-3 py-1 text-sm font-medium text-[#ef4444]">
            ⚠ {issues.total} issue{issues.total === 1 ? "" : "s"} found
          </span>
        </div>

        {/* summary cards */}
        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Monthly Spend" value={`$${money(report.total_monthly_spend)}`} sub={`across ${report.vendor_count} vendors`} icon="$" />
          <Stat label="Potential Savings" value={`$${money(report.potential_monthly_savings)}/mo`} sub={`$${money(report.annual_savings)}/year`} icon="↘" accent />
          <Stat label="Annual Savings" value={`$${money(report.annual_savings)}`} sub="ROI in first month" icon="📅" green />
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
              ${money(report.potential_monthly_savings)}
              <span className="text-base font-normal text-neutral-400">/month</span>
            </div>
            <div className="mt-1 text-sm text-neutral-400">
              is being wasted right now. Act on the 🔴 items today.
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm text-neutral-400">= ${money(report.annual_savings)}/year</div>
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
          <ActionList groups={report.action_groups} jobId={jobId!} />
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
