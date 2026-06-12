"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { VendorLogo } from "@/components/VendorLogo";
import {
  Connection,
  connectProvider,
  getConnections,
  getJobId,
  getProviders,
  Provider,
  setJobId,
} from "@/lib/api";

const DOMAINS: Record<string, string> = {
  github: "github.com",
  aws: "aws.amazon.com",
  zoom: "zoom.us",
};

const FIELD_LABELS: Record<string, string> = {
  pat: "Personal Access Token (ghp_…)",
  access_key_id: "Access Key ID",
  secret_access_key: "Secret Access Key",
  region: "Region (e.g. us-east-1)",
  account_id: "Account ID",
  token: "API Token",
};

interface Instructions {
  title: string;
  steps: string[];
  link?: { label: string; href: string };
}

const INSTRUCTIONS: Record<string, Instructions> = {
  github: {
    title: "How to create a Personal Access Token",
    steps: [
      "Open GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic).",
      'Click "Generate new token (classic)" and give it a name + expiration.',
      "Select the read:org scope (unlocks GitHub Actions usage). Plan info needs no scope.",
      "Generate, then copy the token (starts with ghp_) and paste it above.",
    ],
    link: {
      label: "Create token on GitHub ›",
      href: "https://github.com/settings/tokens/new?scopes=read:org&description=Bless%20billing",
    },
  },
  aws: {
    title: "How to get your AWS access keys",
    steps: [
      "Sign in to the AWS Console → IAM → Users → your user → Security credentials.",
      'Under "Access keys", create a new key (use case: Third-party service).',
      "Copy the Access Key ID and Secret Access Key.",
      "Use the region where billing is enabled (e.g. us-east-1). Read-only ce:GetCostAndUsage is enough.",
    ],
    link: {
      label: "Open IAM security credentials ›",
      href: "https://console.aws.amazon.com/iam/home#/security_credentials",
    },
  },
};

export default function ConnectionsPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [connected, setConnected] = useState<string[]>([]);
  const [hasJob, setHasJob] = useState(false);

  useEffect(() => {
    getProviders().then(setProviders).catch(() => setProviders([]));
    const id = getJobId();
    setHasJob(!!id);
    if (id) getConnections(id).then((c) => setConnected(c.connected_providers)).catch(() => {});
  }, []);

  function onConnected(provider: string, jobId: string, conn: Connection) {
    setJobId(jobId);
    setHasJob(true);
    setConnected((prev) => (prev.includes(provider) ? prev : [...prev, provider]));
    void conn;
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-4xl px-8 py-8">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold">Connections</h1>
            <p className="text-sm text-neutral-400">
              Pull live billing from your providers into one report.
            </p>
          </div>
          {hasJob && (
            <Link
              href="/dashboard"
              className="rounded-lg bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700"
            >
              View unified report ›
            </Link>
          )}
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
          {providers.map((p) => (
            <ProviderCard
              key={p.provider}
              provider={p}
              connected={connected.includes(p.provider)}
              onConnected={onConnected}
            />
          ))}
        </div>
      </div>
    </AppShell>
  );
}

function ProviderCard({
  provider,
  connected,
  onConnected,
}: {
  provider: Provider;
  connected: boolean;
  onConnected: (provider: string, jobId: string, conn: Connection) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [account, setAccount] = useState<string | null>(null);

  async function connect() {
    setBusy(true);
    setError(null);
    try {
      const res = await connectProvider(provider.provider, values, getJobId());
      setAccount(res.connection.account || "connected");
      onConnected(provider.provider, res.job_id, res.connection);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connection failed");
    } finally {
      setBusy(false);
    }
  }

  const ready = provider.credential_fields.every((f) =>
    provider.is_stub ? true : (values[f]?.trim()?.length ?? 0) > 0,
  );

  return (
    <div className="rounded-2xl border border-neutral-200 bg-white p-5">
      <div className="flex items-center gap-3">
        <VendorLogo name={provider.label} domain={DOMAINS[provider.provider]} size={40} />
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="font-semibold">{provider.label}</span>
            {provider.is_stub && (
              <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium uppercase text-amber-600">
                demo
              </span>
            )}
          </div>
          <div className="text-xs text-neutral-400">
            {connected || account ? (
              <span className="text-emerald-600">● Connected {account ? `· ${account}` : ""}</span>
            ) : provider.is_stub ? (
              "Stub adapter — returns sample data"
            ) : (
              "Live API"
            )}
          </div>
        </div>
      </div>

      <div className="mt-4 space-y-2">
        {provider.credential_fields.map((f) => (
          <input
            key={f}
            type={f.includes("secret") || f === "pat" || f === "token" ? "password" : "text"}
            placeholder={FIELD_LABELS[f] ?? f}
            value={values[f] ?? ""}
            onChange={(e) => setValues((v) => ({ ...v, [f]: e.target.value }))}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-neutral-400"
          />
        ))}
        {provider.is_stub && provider.credential_fields.length > 0 && (
          <p className="text-[11px] text-neutral-400">
            Optional for the demo — leave blank to use sample billing.
          </p>
        )}
      </div>

      {INSTRUCTIONS[provider.provider] && (
        <details className="mt-3 rounded-lg bg-neutral-50 px-3 py-2">
          <summary className="cursor-pointer select-none text-xs font-medium text-neutral-600">
            {INSTRUCTIONS[provider.provider].title}
          </summary>
          <ol className="mt-2 list-decimal space-y-1 pl-4 text-[11px] leading-relaxed text-neutral-500">
            {INSTRUCTIONS[provider.provider].steps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
          {INSTRUCTIONS[provider.provider].link && (
            <a
              href={INSTRUCTIONS[provider.provider].link!.href}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-block text-[11px] font-medium text-blue-600 hover:underline"
            >
              {INSTRUCTIONS[provider.provider].link!.label}
            </a>
          )}
        </details>
      )}

      {error && <p className="mt-2 text-sm text-[#ef4444]">{error}</p>}

      <button
        onClick={connect}
        disabled={busy || !ready}
        className="mt-3 w-full rounded-lg bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-40"
      >
        {busy ? "Connecting…" : account ? "Re-sync" : "Connect"}
      </button>
    </div>
  );
}
