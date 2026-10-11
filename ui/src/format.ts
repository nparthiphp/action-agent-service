import type { RunStatus } from "./types";

export const label = (id: string) => id.replace(/_/g, " ");

export function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export function timeLeft(iso: string): string {
  const s = Math.floor((new Date(iso).getTime() - Date.now()) / 1000);
  if (s <= 0) return "expired";
  const m = Math.floor(s / 60);
  return m >= 1 ? `${m} min` : `${s} s`;
}

type Tone = "" | "ok" | "warn" | "bad";
export const STATUS: Record<RunStatus, [string, Tone]> = {
  received: ["Received", ""], invalid: ["Invalid plan", "bad"], rejected_by_policy: ["Blocked by policy", "bad"],
  shadowed: ["Shadow only", ""], awaiting_human: ["A person acts", "warn"], human_required: ["A person must act", "warn"],
  awaiting_approval: ["Waiting for approval", "warn"], denied: ["Denied", ""], expired: ["Approval expired", ""],
  executing: ["Running", ""], verifying: ["Verifying", ""], succeeded: ["Done", "ok"], rolling_back: ["Rolling back", "warn"],
  rolled_back: ["Rolled back", "warn"], rollback_failed: ["Rollback failed", "bad"], failed: ["Failed, nothing changed", "bad"],
  killed: ["Stopped by kill switch", "bad"],
};

export function messageTone(s: RunStatus): Tone {
  if (["failed", "rollback_failed", "killed", "rejected_by_policy", "invalid"].includes(s)) return "bad";
  if (s === "succeeded") return "ok";
  if (["rolled_back", "human_required", "awaiting_human"].includes(s)) return "warn";
  return "";
}

export function getApprover(): string {
  try { return localStorage.getItem("aa_approver") ?? ""; } catch { return ""; }
}
export function setApprover(v: string) {
  try { localStorage.setItem("aa_approver", v); } catch { /* storage unavailable */ }
}
