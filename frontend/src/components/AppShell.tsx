"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getJobId, getReport, money } from "@/lib/api";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: GridIcon, needsJob: true },
  { href: "/", label: "New Upload", icon: UploadIcon, needsJob: false },
  { href: "/connections", label: "Connections", icon: PlugIcon, needsJob: false },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [jobId, setJobIdState] = useState<string | null>(null);
  const [savings, setSavings] = useState<number | null>(null);

  useEffect(() => {
    const sync = () => setJobIdState(getJobId());
    sync();
    window.addEventListener("bless:job", sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("bless:job", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  useEffect(() => {
    if (!jobId) {
      setSavings(null);
      return;
    }
    let active = true;
    getReport(jobId)
      .then((r) => active && setSavings(r.potential_monthly_savings))
      .catch(() => active && setSavings(null));
    return () => {
      active = false;
    };
  }, [jobId, pathname]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#f6f6f7] text-neutral-900">
      <aside className="flex w-64 shrink-0 flex-col border-r border-neutral-200 bg-white">
        <div className="flex items-center gap-3 border-b border-neutral-200 px-5 py-4">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-[#ef4444] text-white">
            <TrendIcon />
          </div>
          <div className="leading-tight">
            <div className="font-semibold">Bless</div>
            <div className="text-xs text-neutral-400">Spend Auditor</div>
          </div>
        </div>

        <nav className="flex-1 space-y-1 p-3">
          {NAV.map(({ href, label, icon: Icon, needsJob }) => {
            const active = pathname === href;
            const disabled = needsJob && !jobId;
            const base =
              "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors";
            if (disabled) {
              return (
                <div key={href} className={`${base} cursor-not-allowed text-neutral-300`}>
                  <Icon /> {label}
                </div>
              );
            }
            return (
              <Link
                key={href}
                href={href}
                className={`${base} ${
                  active
                    ? "bg-neutral-100 text-neutral-900"
                    : "text-neutral-500 hover:bg-neutral-50 hover:text-neutral-900"
                }`}
              >
                <Icon /> {label}
              </Link>
            );
          })}
        </nav>

        <div className="space-y-3 border-t border-neutral-200 p-3">
          <Link
            href="/connections"
            className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-neutral-500 hover:bg-neutral-50 hover:text-neutral-900"
          >
            <GearIcon /> Settings
          </Link>
          <Link
            href={jobId ? "/dashboard" : "/"}
            className="block rounded-xl bg-[#fef2f2] px-4 py-3"
          >
            <div className="text-xs font-semibold text-[#ef4444]">Potential savings</div>
            <div className="text-lg font-bold text-[#ef4444]">
              {savings != null ? `$${money(savings)}/mo` : "—"}
            </div>
            {savings != null && (
              <div className="mt-0.5 text-xs text-[#ef4444]/70">View report ›</div>
            )}
          </Link>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto">{children}</main>

      <Link
        href="/chat"
        title="Ask the Bless assistant"
        className="fixed bottom-6 right-6 grid h-11 w-11 place-items-center rounded-full bg-neutral-900 text-white shadow-lg hover:bg-neutral-700"
      >
        ?
      </Link>
    </div>
  );
}

/* --- icons (inline, no dep) --- */
function TrendIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 17l6-6 4 4 7-7" />
      <path d="M14 7h6v6" />
    </svg>
  );
}
function GridIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}
function UploadIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 16V4" /><path d="M7 9l5-5 5 5" /><path d="M4 20h16" />
    </svg>
  );
}
function PlugIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 2v6" /><path d="M15 2v6" /><path d="M6 8h12v3a6 6 0 0 1-12 0z" /><path d="M12 17v5" />
    </svg>
  );
}
function GearIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}
