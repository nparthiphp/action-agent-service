import type { ActionContract, ActionRun, AuditEntry, ChainResult, Recommendation } from "./types";

// Empty by default: the dev server and the nginx image both proxy /v1 to the core.
// For a different origin set VITE_API_BASE and enable AA_CORS_ORIGINS on the core.
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, init);
  let body: unknown = null;
  try { body = await res.json(); } catch { /* no body */ }
  if (!res.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    throw new Error(detail ? (typeof detail === "string" ? detail : JSON.stringify(detail)) : `Request failed (${res.status})`);
  }
  return body as T;
}
const post = <T,>(path: string, data: unknown) =>
  call<T>(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(data) });

export const api = {
  runs: () => call<ActionRun[]>("/v1/runs?limit=100"),
  catalog: () => call<ActionContract[]>("/v1/catalog"),
  killSwitch: () => call<{ engaged: boolean }>("/v1/killswitch"),
  setKillSwitch: (engaged: boolean, by: string) => post<{ engaged: boolean }>("/v1/killswitch", { engaged, by }),
  submit: (rec: Recommendation) => post<ActionRun>("/v1/recommendations", rec),
  approve: (id: string, approver: string, comment: string) => post<ActionRun>(`/v1/runs/${id}/approve`, { approver, comment }),
  deny: (id: string, approver: string, comment: string) => post<ActionRun>(`/v1/runs/${id}/deny`, { approver, comment }),
  runAudit: (id: string) => call<AuditEntry[]>(`/v1/runs/${id}/audit`),
  audit: (limit = 300) => call<AuditEntry[]>(`/v1/audit?limit=${limit}`),
  verifyChain: () => call<ChainResult>("/v1/audit/verify"),
};
