"use client";
import { useState } from "react";

const PALETTE = ["#eef2ff", "#fef2f2", "#fff7ed", "#f0fdf4", "#faf5ff", "#f8fafc"];

export function VendorLogo({ name, domain, size = 36 }: { name: string; domain?: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
  const bg = PALETTE[name.charCodeAt(0) % PALETTE.length];

  if (domain && !failed) {
    // Icon Horse auto-picks the highest-resolution icon a site exposes
    // (apple-touch-icon, large PNG, manifest icon) — much sharper than
    // Google S2, which upscales 16/32px favicons.
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={`https://icon.horse/icon/${domain}`}
        alt={name}
        width={size}
        height={size}
        onError={() => setFailed(true)}
        className="rounded-lg object-contain bg-white border border-neutral-100"
        style={{ width: size, height: size }}
      />
    );
  }
  return (
    <div
      className="rounded-lg grid place-items-center text-xs font-semibold text-neutral-600 border border-neutral-100"
      style={{ width: size, height: size, background: bg }}
    >
      {initials}
    </div>
  );
}
