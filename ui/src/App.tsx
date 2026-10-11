import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { Logo, NavIcon, Pill } from "./components/Bits";
import { getApprover } from "./format";
import { go, useRoute, usePolling, type View } from "./hooks";
import type { ActionContract, ActionRun, ChainResult } from "./types";
import { Audit } from "./views/Audit";
import { Catalog } from "./views/Catalog";
import { Runs } from "./views/Runs";

const TITLES: Record<View, string> = { runs: "Runs", catalog: "Action catalog", audit: "Audit trail" };

export default function App() {
  const route = useRoute();
  const { data: polled, reload } = usePolling(async () => {
    const [runs, ks] = await Promise.all([api.runs(), api.killSwitch()]);
    return { runs, killed: ks.engaged };
  }, 4000);
  const [local, setLocal] = useState<ActionRun[] | null>(null);
  const [catalogList, setCatalogList] = useState<ActionContract[]>([]);
  const [chain, setChain] = useState<ChainResult | null>(null);
  const [toast, setToast] = useState<{ msg: string; bad: boolean } | null>(null);

  useEffect(() => { api.catalog().then(setCatalogList).catch(() => undefined); }, []);
  useEffect(() => { setLocal(null); }, [polled]); // a fresh poll replaces local edits

  const runs = local ?? polled?.runs ?? [];
  const killed = polled?.killed ?? false;
  const catalogById = useMemo(() => Object.fromEntries(catalogList.map((c) => [c.action_id, c])), [catalogList]);
  const pendingCount = runs.filter((r) => r.status === "awaiting_approval").length;

  const notify = useCallback((msg: string, bad = false) => {
    setToast({ msg, bad });
    setTimeout(() => setToast(null), 3500);
  }, []);
  const upsert = useCallback((r: ActionRun) => {
    setLocal((cur) => { const base = cur ?? polled?.runs ?? []; return base.some((x) => x.run_id === r.run_id) ? base.map((x) => (x.run_id === r.run_id ? r : x)) : [r, ...base]; });
  }, [polled]);

  const selectedId = route.runId ?? (route.view === "runs" ? (runs.find((r) => r.status === "awaiting_approval") ?? runs[0])?.run_id ?? null : null);

  const toggleKill = async () => {
    const engage = !killed;
    if (engage && !window.confirm("Stop all runs? New and waiting runs will not execute until you turn this off.")) return;
    try { await api.setKillSwitch(engage, getApprover() || "console"); notify(engage ? "Kill switch on" : "Kill switch off"); reload(); }
    catch (e) { notify((e as Error).message, true); }
  };
  const verify = async () => { try { setChain(await api.verifyChain()); } catch (e) { notify((e as Error).message, true); } };

  const nav = (view: View, text: string) => (
    <a href={"#/" + view} aria-current={route.view === view ? "page" : undefined} onClick={() => route.view === view && view === "runs" && go("#/runs")}>
      <NavIcon name={view} />{text}
      {view === "runs" && pendingCount > 0 && <span className="badge" title="Waiting for approval">{pendingCount}</span>}
    </a>
  );

  return (
    <div className="app">
      <aside className="side">
        <a className="logo" href="#/runs" aria-label="VertexMind Action Agent">
          <Logo /><span><b>VertexMind</b><small>Action Agent</small></span>
        </a>
        <nav className="nav" aria-label="Main">{nav("runs", "Runs")}{nav("catalog", "Action catalog")}{nav("audit", "Audit trail")}</nav>
        <div className="side-foot">Execution layer of ARIES.<br />Prototype build.</div>
      </aside>
      <div className="main">
        <header className="top">
          <h1>{TITLES[route.view]}</h1>
          <div className="check">
            {chain && <Pill tone={chain.ok ? "ok" : "bad"}>{chain.ok ? "Audit trail intact" : `Audit trail broken at entry ${chain.broken_at}`}</Pill>}
            <button className="btn" onClick={verify}>{chain ? "Check again" : "Check audit trail"}</button>
          </div>
          <div className="check">
            <span>Kill switch: <b>{killed ? "on" : "off"}</b></span>
            <button className={`btn ${killed ? "primary" : "danger"}`} onClick={toggleKill}>{killed ? "Turn off" : "Stop all runs"}</button>
          </div>
        </header>
        {killed && <div className="banner kill">Kill switch is on. Nothing will run until it is turned off. Steps that already ran are not rolled back.</div>}
        <div className="banner note">Prototype: there is no sign-in. The name you enter when approving is recorded but not verified.</div>
        <main className="view">
          {route.view === "runs" && <Runs runs={runs} selectedId={selectedId} catalog={catalogById} onRun={upsert} notify={notify} />}
          {route.view === "catalog" && <Catalog catalog={catalogList} />}
          {route.view === "audit" && <Audit />}
        </main>
      </div>
      {toast && <div className={`toast ${toast.bad ? "bad" : ""}`} role="status">{toast.msg}</div>}
    </div>
  );
}
