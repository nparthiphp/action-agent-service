import { useCallback, useEffect, useState } from "react";

export type View = "runs" | "catalog" | "audit";
export interface Route { view: View; runId: string | null }

function parse(): Route {
  const [v, id] = window.location.hash.replace(/^#\/?/, "").split("/");
  const view: View = v === "catalog" || v === "audit" ? v : "runs";
  return { view, runId: view === "runs" && id ? id : null };
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(parse);
  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
export const go = (hash: string) => { window.location.hash = hash; };

/** Calls load now and then every ms, keeping the latest result. Errors keep the last good value. */
export function usePolling<T>(load: () => Promise<T>, ms: number): { data: T | null; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    const run = () => load().then((d) => alive && setData(d)).catch(() => undefined);
    run();
    const t = setInterval(run, ms);
    return () => { alive = false; clearInterval(t); };
  }, [ms, tick]); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, reload: useCallback(() => setTick((n) => n + 1), []) };
}
