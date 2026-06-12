"use client";

const SOURCE_LABELS: Record<string, string> = {
  csv: "CSV upload",
  github: "GitHub",
  aws: "AWS",
  zoom: "Zoom",
};

function label(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

export function SourceFilter({
  sources,
  excluded,
  onToggle,
}: {
  sources: string[];
  excluded: string[];
  onToggle: (source: string) => void;
}) {
  if (sources.length < 2) return null;

  const activeCount = sources.length - excluded.length;

  return (
    <details className="group relative">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg border border-neutral-200 bg-white px-3 py-1.5 text-sm font-medium text-neutral-700 hover:border-neutral-300">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
        </svg>
        Sources
        <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[11px] text-neutral-500">
          {activeCount}/{sources.length}
        </span>
        <svg className="transition-transform group-open:rotate-180" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </summary>
      <div className="absolute right-0 z-10 mt-2 w-56 rounded-xl border border-neutral-200 bg-white p-2 shadow-lg">
        <p className="px-2 py-1 text-[11px] font-medium uppercase tracking-wide text-neutral-400">
          Include in report
        </p>
        {sources.map((s) => {
          const on = !excluded.includes(s);
          return (
            <label
              key={s}
              className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm hover:bg-neutral-50"
            >
              <input
                type="checkbox"
                checked={on}
                onChange={() => onToggle(s)}
                className="h-4 w-4 accent-neutral-900"
              />
              <span className={on ? "text-neutral-900" : "text-neutral-400"}>{label(s)}</span>
            </label>
          );
        })}
      </div>
    </details>
  );
}
