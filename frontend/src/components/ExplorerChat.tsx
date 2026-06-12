"use client";
import "@openuidev/react-ui/components.css";
import "@openuidev/react-ui/styles/index.css";

import {
  openAIMessageFormat,
  openAIReadableStreamAdapter,
} from "@openuidev/react-headless";
import { Copilot } from "@openuidev/react-ui";
import { openuiLibrary, openuiPromptOptions } from "@openuidev/react-ui/genui-lib";
import { getJobId, readCachedReport } from "@/lib/api";

// The genui system prompt teaches the model OpenUI Lang + the component library.
const basePrompt = openuiLibrary.prompt(openuiPromptOptions);

const ROLE = `# Your role
You are the **Bless Spend Explorer**, an assistant embedded inside a SaaS spend-audit dashboard.
Help the user understand and navigate the savings report currently on screen: explain where
numbers come from, surface the biggest wins, compare vendors and categories, and recommend
what to act on first.

Guidelines:
- Ground every answer in the "Current dashboard data" below. If something is not in the data, say so plainly.
- Prefer rich GenUI components (cards, tables, charts, ranked lists) over long paragraphs when presenting numbers.
- All amounts are USD. "monthly_savings" is the recurring monthly waste Bless can recover for that vendor.
- "annual_savings" = "potential_monthly_savings" x 12. The dashboard groups issues into kill / rightsize / easy buckets.
- Be concise and specific. Always reference vendors and categories by name.`;

// Re-read on every message so the assistant always reflects the current report.
function reportContext(): string {
  const jobId = getJobId();
  if (!jobId) {
    return "No audit has been run yet. The user has not uploaded a CSV or connected a billing account.";
  }
  const cached = readCachedReport(jobId);
  if (!cached) return "A job exists but its report has not finished loading yet.";

  const r = cached.report;
  const compact = {
    total_monthly_spend: r.total_monthly_spend,
    potential_monthly_savings: r.potential_monthly_savings,
    annual_savings: r.annual_savings,
    vendor_count: r.vendor_count,
    issues_found: r.issues_found,
    categories: r.categories,
    action_groups: r.action_groups.map((g) => ({
      key: g.key,
      label: g.label,
      total_savings: g.total_savings,
      items: g.items.map((it) => ({
        vendor: it.vendor_name,
        category: it.category,
        monthly_amount: it.monthly_amount,
        monthly_savings: it.monthly_savings,
        flag: it.flag_type,
        priority: it.priority,
        action: it.action_label,
        source: it.source,
        why: it.reasoning,
      })),
    })),
  };
  return "```json\n" + JSON.stringify(compact) + "\n```";
}

export function ExplorerChat({ onClose }: { onClose?: () => void }) {
  return (
    <Copilot
      agentName="Spend Explorer"
      componentLibrary={openuiLibrary}
      streamProtocol={openAIReadableStreamAdapter()}
      welcomeMessage={{
        title: "Spend Explorer",
        description:
          "Ask me anything about your savings report — where a number comes from, your biggest wins, or what to cut first.",
      }}
      conversationStarters={{
        variant: "long",
        options: [
          {
            displayText: "What's my biggest source of waste?",
            prompt: "What is my biggest source of waste, and how much can I save?",
          },
          {
            displayText: "Break down savings by category",
            prompt: "Show me a chart of potential savings broken down by category.",
          },
          {
            displayText: "What should I cancel first?",
            prompt:
              "Which subscriptions should I cancel first for the fastest savings? Show them as a ranked list with the monthly savings for each.",
          },
          {
            displayText: "How is annual savings calculated?",
            prompt: "How is the annual savings number on the dashboard calculated?",
          },
        ],
      }}
      headerActions={
        onClose ? (
          <button
            onClick={onClose}
            aria-label="Close explorer"
            className="grid h-7 w-7 place-items-center rounded-lg text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 6L6 18" /><path d="M6 6l12 12" />
            </svg>
          </button>
        ) : undefined
      }
      processMessage={async ({ messages, abortController }) => {
        const systemPrompt = `${basePrompt}\n\n${ROLE}\n\n# Current dashboard data\n${reportContext()}`;
        return fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            systemPrompt,
            messages: openAIMessageFormat.toApi(messages),
          }),
          signal: abortController.signal,
        });
      }}
    />
  );
}
