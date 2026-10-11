import { useEffect, useState } from "react";
import { api } from "../api";
import { Lane } from "../components/Lane";
import { StatusPill, TierChip } from "../components/Bits";
import { getApprover, label, messageTone, setApprover, timeLeft } from "../format";
import type { ActionContract, ActionRun, AuditEntry } from "../types";

type Notify = (msg: string, bad?: boolean) => void;

function Decide({ run, onChange, notify }: { run: ActionRun; onChange: (r: ActionRun) => void; notify: Notify }) {
  const [name, setName] = useState(getApprover());
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const decide = async (kind: "approve" | "deny") => {
    const who = name.trim();
    if (!who) { notify("Enter your name first", true); return; }
    setApprover(who);
    setBusy(true);
    try {
      const r = await (kind === "approve" ? api.approve : api.deny)(run.run_id, who, comment.trim());
      notify(kind === "approve" ? "Approved" : "Denied");
      onChange(r);
    } catch (e) { notify((e as Error).message, true); onChange(run); }
    finally { setBusy(false); }
  };
  return (
    <div className="decide">
      <h3>This plan needs your approval</h3>
      <p>Approval expires in {timeLeft(run.approval!.expires_at)}. Policy is checked again when you approve.</p>
      <div className="row">
        <input type="text" placeholder="Your name" aria-label="Your name" value={name} onChange={(e) => setName(e.target.value)} />
        <input type="text" placeholder="Comment (optional)" aria-label="Comment" value={comment} onChange={(e) => setComment(e.target.value)} />
        <button className="btn primary" disabled={busy} onClick={() => decide("approve")}>Approve and run</button>
        <button className="btn danger" disabled={busy} onClick={() => decide("deny")}>Deny</button>
      </div>
      <div className="fine">The name is not verified in this prototype.</div>
    </div>
  );
}

function RunAudit({ run }: { run: ActionRun }) {
  const [events, setEvents] = useState<AuditEntry[] | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { api.runAudit(run.run_id).then(setEvents).catch(() => undefined); }, [run.run_id, run.updated_at]);
  return (
    <details className="audit sec" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>Audit trail for this run</summary>
      <div style={{ marginTop: 8 }}>
        {events === null ? "Loading…" : events.length === 0 ? <div className="empty">No events yet.</div> : events.map((e) => (
          <div className="ev small" key={e.seq}>
            <span className="t">{new Date(e.ts).toLocaleTimeString()}</span>
            <span>{label(e.event)}</span>
            <code>{JSON.stringify(e.data)}</code>
          </div>
        ))}
      </div>
    </details>
  );
}

export function RunDetail({ run, catalog, onChange, notify }: {
  run: ActionRun; catalog: Record<string, ActionContract>; onChange: (r: ActionRun) => void; notify: Notify;
}) {
  const rec = run.recommendation;
  return (
    <>
      <h2 className="title">{rec.target} · {rec.environment}</h2>
      <div className="sub">
        <StatusPill status={run.status} /><TierChip tier={run.tier} />
        <span>from {rec.source}</span>
        {rec.incident_ref && <span>incident {rec.incident_ref}</span>}
        <span className="mono">{run.run_id}</span>
      </div>

      {run.message && run.status !== "awaiting_approval" && <div className="sec"><div className={`msg ${messageTone(run.status)}`}>{run.message}</div></div>}
      {run.status === "awaiting_approval" && run.approval && <Decide run={run} onChange={onChange} notify={notify} />}

      <div className="sec"><h3>Steps</h3><Lane run={run} catalog={catalog} /></div>

      <div className="sec">
        <h3>Details</h3>
        <dl className="kv">
          <dt>Why {run.tier}</dt>
          <dd>{run.risk_reasons.length ? <ul className="reasons">{run.risk_reasons.map((x) => <li key={x}>{x}</li>)}</ul> : "No extra risk reasons."}</dd>
          {run.mode && <><dt>Autonomy mode</dt><dd>{label(run.mode)}</dd></>}
          {run.policy && <><dt>Policy</dt><dd>{run.policy.allowed ? "Allowed" : "Blocked"}{run.policy.reason ? `: ${run.policy.reason}` : ""}</dd></>}
          {run.approval?.decided_by && <><dt>Decision</dt><dd>{run.approval.status} by {run.approval.decided_by}{run.approval.comment ? `: ${run.approval.comment}` : ""}</dd></>}
          <dt>Confidence</dt><dd>{Math.round(rec.confidence * 100)}%</dd>
          {rec.rationale && <><dt>Rationale</dt><dd>{rec.rationale}</dd></>}
        </dl>
      </div>

      {run.human_plan && run.human_plan.length > 0 && (
        <div className="sec">
          <h3>Plan for a person to carry out</h3>
          <ol className="plan">
            {run.human_plan.map((p, i) => (
              <li key={i}>
                <b>{label(p.action_id ?? "step")}</b>{p.summary ? ` · ${p.summary}` : ""}
                {p.verify && <div className="fine">Check: {p.verify}</div>}
                {p.rollback && <div className="fine">Undo: {p.rollback}</div>}
              </li>
            ))}
          </ol>
        </div>
      )}
      <RunAudit run={run} />
    </>
  );
}
