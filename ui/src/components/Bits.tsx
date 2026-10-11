import type { ReactNode } from "react";
import type { RunStatus, Tier } from "../types";
import { STATUS } from "../format";

export function Logo({ size = 32, stroke = 3.2 }: { size?: number; stroke?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <path d="M5 7l11 19L27 7" fill="none" stroke="var(--vm-ink)" strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="5" cy="7" r="3" fill="var(--vm-ink)" />
      <circle cx="27" cy="7" r="3" fill="var(--vm-ink)" />
      <circle cx="16" cy="26" r="3.6" fill="var(--vm-accent)" />
    </svg>
  );
}

export function StatusPill({ status }: { status: RunStatus }) {
  const [text, tone] = STATUS[status] ?? [status, ""];
  return <span className={`pill ${tone}`}><span className="dot" />{text}</span>;
}

export const TierChip = ({ tier }: { tier: Tier | null | undefined }) => (tier ? <span className={`tier ${tier}`}>{tier}</span> : null);

export function Pill({ tone, children }: { tone: "ok" | "bad" | ""; children: ReactNode }) {
  return <span className={`pill ${tone}`}><span className="dot" />{children}</span>;
}

const ICONS = {
  runs: <path d="M3 5h14M3 10h14M3 15h9" />,
  catalog: <><rect x="3" y="3" width="6" height="6" rx="1" /><rect x="11" y="3" width="6" height="6" rx="1" /><rect x="3" y="11" width="6" height="6" rx="1" /><rect x="11" y="11" width="6" height="6" rx="1" /></>,
  audit: <><path d="M10 2l6 2.5v5c0 4-2.6 6.7-6 8-3.4-1.3-6-4-6-8v-5z" /><path d="M7.5 10l2 2 3.5-4" /></>,
};
export function NavIcon({ name }: { name: keyof typeof ICONS }) {
  return <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICONS[name]}</svg>;
}
