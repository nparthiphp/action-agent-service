import type { ActionContract, ActionRun, StepRecord } from "../types";
import { label } from "../format";
import { TierChip } from "./Bits";

const STAGES = ["Dry run", "Run", "Verify", "Roll back"];
type Cell = "" | "done" | "fail" | "rolled" | "skip";
const MARK: Record<string, string> = { done: "✓", fail: "!", rolled: "↺", skip: "–" };

function stages(step: StepRecord, run: ActionRun): Cell[] {
  const o: Cell[] = ["", "", "", ""];
  const dryFail = run.message.includes("nothing was executed");
  switch (step.status) {
    case "dry_run_ok": o[0] = "done"; break;
    case "executed": o[0] = o[1] = "done"; break;
    case "verified": o[0] = o[1] = o[2] = "done"; break;
    case "failed": if (dryFail) o[0] = "fail"; else { o[0] = "done"; o[1] = "fail"; } break;
    case "rolled_back": o[0] = o[1] = "done"; o[3] = "rolled"; break;
    case "rollback_skipped": o[0] = o[1] = "done"; o[3] = "skip"; break;
    case "rollback_failed": o[0] = o[1] = "done"; o[3] = "fail"; break;
  }
  return o;
}

const fmt = (v: unknown) => (typeof v === "object" ? JSON.stringify(v) : String(v));

export function Lane({ run, catalog }: { run: ActionRun; catalog: Record<string, ActionContract> }) {
  return (
    <>
      <div className="lane" role="table" aria-label="Steps">
        <div className="lane-head" role="row">
          <div>Step</div>
          {STAGES.map((s) => <div key={s} style={{ textAlign: "center" }}>{s}</div>)}
        </div>
        {run.steps.map((st) => {
          const params = Object.entries(st.params ?? {}).map(([k, v]) => `${k}=${fmt(v)}`).join(", ");
          const showNote = st.detail && !["pending", "dry_run_ok"].includes(st.status);
          const noteBad = ["failed", "rollback_failed", "rollback_skipped"].includes(st.status);
          return (
            <div key={st.index} style={{ display: "contents" }}>
              <div className="lane-row" role="row">
                <div>
                  <div className="step-name">
                    {st.index + 1}. {label(st.action_id)} <TierChip tier={catalog[st.action_id]?.tier} />
                    <small>{params || "no inputs"}</small>
                  </div>
                </div>
                {stages(st, run).map((c, i) => (
                  <div key={i} role="cell">
                    <div className={`stage ${c} ${i === 3 ? "rb" : ""}`} title={STAGES[i] + (c ? `: ${c}` : "")}>
                      <span className="node">{MARK[c] ?? ""}</span>
                    </div>
                  </div>
                ))}
              </div>
              {showNote && (
                <div className="lane-row">
                  <div className={`lane-note ${noteBad ? "bad" : ""}`}>{st.detail}{st.attempts > 1 ? ` (${st.attempts} attempts)` : ""}</div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="legend">
        <span><i style={{ background: "var(--ok)" }} />done</span>
        <span><i style={{ background: "var(--bad)" }} />failed</span>
        <span><i style={{ background: "var(--vm-accent)" }} />rolled back</span>
        <span><i style={{ border: "2px dashed var(--warn)", width: 6, height: 6 }} />cannot be undone</span>
      </div>
    </>
  );
}
