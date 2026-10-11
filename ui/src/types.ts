export type Tier = "T0" | "T1" | "T2" | "T3";

export type RunStatus =
  | "received" | "invalid" | "rejected_by_policy" | "shadowed" | "awaiting_human" | "human_required"
  | "awaiting_approval" | "denied" | "expired" | "executing" | "verifying" | "succeeded"
  | "rolling_back" | "rolled_back" | "rollback_failed" | "failed" | "killed";

export type StepStatus =
  | "pending" | "dry_run_ok" | "executed" | "verified" | "failed"
  | "rolled_back" | "rollback_skipped" | "rollback_failed";

export interface StepSpec { action_id: string; params: Record<string, unknown> }

export interface Recommendation {
  recommendation_id: string;
  target: string;
  environment: "prod" | "nonprod";
  steps: StepSpec[];
  confidence: number;
  rationale?: string;
  source?: string;
  incident_ref?: string | null;
}

export interface StepRecord {
  index: number;
  action_id: string;
  params: Record<string, unknown>;
  status: StepStatus;
  detail: string;
  attempts: number;
}

export interface ApprovalRecord {
  requested_at: string;
  expires_at: string;
  status: "pending" | "approved" | "denied" | "expired";
  decided_by: string | null;
  comment: string;
}

export interface PolicyDecision { allowed: boolean; reason: string; requires_approval: boolean }

export interface HumanPlanItem { action_id?: string; summary?: string; verify?: string; rollback?: string }

export interface ActionRun {
  run_id: string;
  recommendation: Recommendation;
  status: RunStatus;
  tier: Tier | null;
  mode: string | null;
  risk_reasons: string[];
  policy: PolicyDecision | null;
  approval: ApprovalRecord | null;
  steps: StepRecord[];
  human_plan: HumanPlanItem[] | null;
  needs_escalation: boolean;
  message: string;
  created_at: string;
  updated_at: string;
}

export interface ActionContract {
  action_id: string;
  domain: string;
  summary: string;
  inputs: string[];
  preconditions: string[];
  blast_radius: string;
  tier: Tier;
  production_floor: Tier | null;
  blast_param: string | null;
  blast_limit: number | null;
  verify: { check: string; description: string };
  rollback: { kind: "revert" | "compensate" | "none"; description: string };
}

export interface AuditEntry { seq: number; ts: string; run_id: string; event: string; data: Record<string, unknown>; hash: string }
export interface ChainResult { ok: boolean; broken_at: number | null }
