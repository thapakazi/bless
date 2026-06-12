"use client";
import { useState } from "react";
import { ActionGroup, ActionItem, money, runAction } from "@/lib/api";
import { VendorLogo } from "./VendorLogo";

const DOT: Record<string, string> = { red: "bg-[#ef4444]", yellow: "bg-amber-400", green: "bg-emerald-500" };
const SAVE_TEXT: Record<string, string> = { red: "text-[#ef4444]", yellow: "text-amber-500", green: "text-emerald-600" };

export function ActionList({ groups, jobId }: { groups: ActionGroup[]; jobId: string }) {
  const total = groups.reduce((s, g) => s + g.items.length, 0);
  return (
    <div className="rounded-2xl border border-neutral-200 bg-white p-6">
      <h2 className="text-lg font-semibold">Action List</h2>
      <p className="mb-5 text-sm text-neutral-400">
        Prioritized by impact · {total} issue{total === 1 ? "" : "s"} found
      </p>

      <div className="space-y-7">
        {groups
          .filter((g) => g.items.length > 0)
          .map((g) => (
            <section key={g.key}>
              <div className="mb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={`h-2.5 w-2.5 rounded-full ${DOT[g.color]}`} />
                  <h3 className="font-semibold">{g.label}</h3>
                </div>
                <span className={`text-sm font-medium ${SAVE_TEXT[g.color]}`}>
                  Save ${money(g.total_savings)}/mo
                </span>
              </div>
              <div className="space-y-3">
                {g.items.map((item) => (
                  <ActionRow key={`${item.vendor_name}-${item.flag_type}`} item={item} jobId={jobId} />
                ))}
              </div>
            </section>
          ))}
      </div>
    </div>
  );
}

const ACTION_TYPE: Record<string, string> = {
  "Create Ticket": "create_ticket",
  "Open Billing": "open_billing",
  "Apply for Credits": "apply_credits",
};

function ActionRow({ item, jobId }: { item: ActionItem; jobId: string }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  async function onClick() {
    const type = ACTION_TYPE[item.action_label] ?? "open_billing";
    if (type !== "create_ticket" && item.action_url) {
      window.open(item.action_url, "_blank", "noopener");
    }
    setBusy(true);
    try {
      const res = await runAction(jobId, type, item.vendor_name, item.action_url);
      setDone(res.ticket_id ? `Ticket ${res.ticket_id}` : "Opened");
    } catch {
      setDone("Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-4 rounded-xl border border-neutral-200 px-4 py-3">
      <VendorLogo name={item.vendor_name} domain={item.domain} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-semibold">{item.vendor_name}</span>
          <span className="text-xs text-neutral-400">${money(item.monthly_amount)}/mo</span>
          {item.source !== "csv" && (
            <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] font-medium uppercase text-neutral-500">
              {item.source}
            </span>
          )}
        </div>
        <p className="truncate text-sm text-neutral-500">{item.reasoning}</p>
      </div>
      <span className="shrink-0 rounded-md bg-emerald-50 px-2.5 py-1 text-sm font-semibold text-emerald-600">
        −${money(item.monthly_savings)}/mo
      </span>
      <button
        onClick={onClick}
        disabled={busy}
        className="shrink-0 rounded-lg bg-neutral-900 px-3.5 py-2 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-50"
      >
        {done ?? (busy ? "…" : item.action_label)}
      </button>
    </div>
  );
}
