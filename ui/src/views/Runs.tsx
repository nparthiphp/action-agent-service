import { api } from "../api";
import { Logo, StatusPill, TierChip } from "../components/Bits";
import { ago, timeLeft } from "../format";
import { go } from "../hooks";
import { SCENARIOS } from "../scenarios";
import type { ActionContract, ActionRun } from "../types";
import { RunDetail } from "./RunDetail";

function RunCard({ run, selected }: { run: ActionRun; selected: boolean }) {
  const rec = run.recommendation;
  return (
    <button className="run" aria-current={selected} onClick={() => go("#/runs/" + run.run_id)}>
      <div className="row"><TierChip tier={run.tier} /><span className="name">{rec.target} · {rec.environment}</span></div>
      <div className="row"><StatusPill status={run.status} /></div>
      <div className="meta">
        <span>{rec.steps.length} {rec.steps.length === 1 ? "step" : "steps"}</span>
        <span>{run.status === "awaiting_approval" && run.approval ? `${timeLeft(run.approval.expires_at)} left` : ago(run.updated_at)}</span>
      </div>
    </button>
  );
}

export function Runs({ runs, selectedId, catalog, onRun, notify }: {
  runs: ActionRun[]; selectedId: string | null; catalog: Record<string, ActionContract>;
  onRun: (r: ActionRun) => void; notify: (m: string, bad?: boolean) => void;
}) {
  const pending = runs.filter((r) => r.status === "awaiting_approval");
  const selected = runs.find((r) => r.run_id === selectedId) ?? null;

  const start = async (i: number) => {
    try { const r = await api.submit(SCENARIOS[i].build()); onRun(r); go("#/runs/" + r.run_id); notify("Run started"); }
    catch (e) { notify((e as Error).message, true); }
  };

  return (
    <div className="split">
      <aside>
        <div className="group">
          <p className="col-title">Needs your decision</p>
          {pending.length ? pending.map((r) => <RunCard key={r.run_id} run={r} selected={r.run_id === selected?.run_id} />) : <div className="empty">Nothing is waiting for you.</div>}
        </div>
        <div className="group">
          <p className="col-title">All runs</p>
          {runs.length ? runs.map((r) => <RunCard key={r.run_id} run={r} selected={r.run_id === selected?.run_id} />) : <div className="empty">No runs yet. Start one below.</div>}
        </div>
        <div className="group">
          <p className="col-title">Start a sample run</p>
          {SCENARIOS.map((s, i) => <button key={s.name} className="scn" onClick={() => start(i)}><b>{s.name}</b><span>{s.note}</span></button>)}
        </div>
      </aside>
      <section className="card detail" aria-live="polite">
        {selected ? <RunDetail run={selected} catalog={catalog} onChange={onRun} notify={notify} /> : (
          <div className="hero">
            <Logo size={56} stroke={2.6} />
            <h2>Recommendations in. Safe changes out.</h2>
            <p>Every plan is checked, approved when it needs to be, verified after it runs, and rolled back if it fails. Pick a run, or start a sample.</p>
          </div>
        )}
      </section>
    </div>
  );
}
