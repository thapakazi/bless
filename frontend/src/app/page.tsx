"use client";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { DEMO_CSV, setJobId, uploadCsv } from "@/lib/api";

const STEPS = [
  "Ingesting data…",
  "Enriching vendors…",
  "Detecting waste…",
  "Building your report…",
];

export default function UploadPage() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [step, setStep] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function ingest(file: File | Blob) {
    setError(null);
    setStep(0);
    const timers = STEPS.map((_, i) =>
      setTimeout(() => setStep(i), i * 550),
    );
    try {
      const { job_id } = await uploadCsv(file);
      timers.forEach(clearTimeout);
      setStep(STEPS.length - 1);
      setJobId(job_id);
      router.push("/dashboard");
    } catch (e) {
      timers.forEach(clearTimeout);
      setStep(null);
      setError(e instanceof Error ? e.message : "Upload failed");
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) ingest(file);
  }

  return (
    <AppShell>
      <div className="grid min-h-full place-items-center px-6 py-16">
        <div className="w-full max-w-2xl text-center">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-[#fef2f2] px-3 py-1 text-sm font-medium text-[#ef4444]">
            ⚡ AI-powered waste detection
          </span>
          <h1 className="mt-6 text-4xl font-bold tracking-tight">Upload your SaaS spend</h1>
          <p className="mt-3 text-lg text-neutral-500">
            We&apos;ll find every dollar you shouldn&apos;t be paying.
          </p>

          {step === null ? (
            <div
              onClick={() => inputRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={`mt-10 cursor-pointer rounded-2xl border-2 border-dashed bg-white px-8 py-16 transition-colors ${
                dragging ? "border-[#ef4444] bg-[#fef2f2]/30" : "border-neutral-300 hover:border-neutral-400"
              }`}
            >
              <input
                ref={inputRef}
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) ingest(f);
                }}
              />
              <div className="mx-auto grid h-14 w-14 place-items-center rounded-xl bg-neutral-100 text-neutral-500">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 16V4" /><path d="M7 9l5-5 5 5" /><path d="M4 20h16" />
                </svg>
              </div>
              <div className="mt-5 text-lg font-semibold">Drop your CSV here</div>
              <div className="text-neutral-400">or click to browse</div>
              <div className="mx-auto mt-6 inline-block rounded-lg bg-neutral-50 px-4 py-2 font-mono text-sm text-neutral-400">
                Ramp · Brex · Mercury · any bank CSV
              </div>
            </div>
          ) : (
            <div className="mt-10 rounded-2xl border border-neutral-200 bg-white px-8 py-16">
              <div className="mx-auto max-w-xs space-y-3 text-left">
                {STEPS.map((label, i) => (
                  <div key={label} className="flex items-center gap-3">
                    <span
                      className={`grid h-6 w-6 place-items-center rounded-full text-xs ${
                        i < step!
                          ? "bg-emerald-500 text-white"
                          : i === step
                            ? "bg-[#ef4444] text-white"
                            : "bg-neutral-100 text-neutral-400"
                      }`}
                    >
                      {i < step! ? "✓" : i + 1}
                    </span>
                    <span className={i <= step! ? "text-neutral-900" : "text-neutral-400"}>{label}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {error && <p className="mt-4 text-sm text-[#ef4444]">{error}</p>}

          <p className="mt-6 text-sm text-neutral-500">
            Demo mode — drop any CSV or{" "}
            <button
              onClick={() => ingest(new Blob([DEMO_CSV], { type: "text/csv" }))}
              disabled={step !== null}
              className="font-semibold text-[#ef4444] hover:underline disabled:opacity-50"
            >
              load the demo dataset
            </button>
          </p>
        </div>
      </div>
    </AppShell>
  );
}
