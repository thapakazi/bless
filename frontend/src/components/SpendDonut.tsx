"use client";
import { Category, money } from "@/lib/api";

const COLORS: Record<string, string> = {
  Engineering: "#3b82f6",
  Communication: "#ef4444",
  Design: "#f59e0b",
  Marketing: "#8b5cf6",
  "HR & People": "#10b981",
  "Finance / Other": "#9ca3af",
};
const FALLBACK = ["#3b82f6", "#ef4444", "#f59e0b", "#8b5cf6", "#10b981", "#9ca3af", "#06b6d4"];

function colorFor(cat: string, i: number) {
  return COLORS[cat] ?? FALLBACK[i % FALLBACK.length];
}

export function SpendDonut({ categories }: { categories: Category[] }) {
  const total = categories.reduce((s, c) => s + c.amount, 0) || 1;
  const r = 70;
  const sw = 26;
  const c = 2 * Math.PI * r;
  let offset = 0;

  return (
    <div className="flex flex-col items-center gap-6 sm:flex-row sm:items-center">
      <svg width="180" height="180" viewBox="0 0 180 180" className="shrink-0">
        <g transform="rotate(-90 90 90)">
          <circle cx="90" cy="90" r={r} fill="none" stroke="#f1f1f3" strokeWidth={sw} />
          {categories.map((cat, i) => {
            const frac = cat.amount / total;
            const len = frac * c;
            const dash = `${len} ${c - len}`;
            const el = (
              <circle
                key={cat.category}
                cx="90"
                cy="90"
                r={r}
                fill="none"
                stroke={colorFor(cat.category, i)}
                strokeWidth={sw}
                strokeDasharray={dash}
                strokeDashoffset={-offset}
              />
            );
            offset += len;
            return el;
          })}
        </g>
      </svg>

      <ul className="w-full space-y-2 text-sm">
        {categories.map((cat, i) => (
          <li key={cat.category} className="flex items-center gap-2">
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ background: colorFor(cat.category, i) }}
            />
            <span className="flex-1 truncate text-neutral-600">
              {cat.category}
              {cat.flagged && <span className="ml-1 text-[#ef4444]">🚩</span>}
            </span>
            <span className="font-semibold tabular-nums">${money(cat.amount)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
