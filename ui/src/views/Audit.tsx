import { useEffect, useState } from "react";
import { api } from "../api";
import { label } from "../format";
import type { AuditEntry } from "../types";

export function Audit() {
  const [events, setEvents] = useState<AuditEntry[]>([]);
  const [q, setQ] = useState("");
  useEffect(() => { api.audit().then(setEvents).catch(() => undefined); }, []);
  const needle = q.trim().toLowerCase();
  const rows = events.filter((e) => !needle || `${e.run_id} ${e.event} ${label(e.event)} ${JSON.stringify(e.data)}`.toLowerCase().includes(needle));
  return (
    <>
      <div className="tools">
        <input type="search" placeholder="Search run, event or detail" aria-label="Search audit trail" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="fine">{rows.length} of {events.length} recent events</span>
      </div>
      <div className="card">
        {rows.length === 0 ? <div className="empty" style={{ border: 0 }}>No matching events.</div> : rows.map((e) => (
          <div className="ev" key={e.seq}>
            <span className="t">{new Date(e.ts).toLocaleTimeString()}</span>
            <span>{label(e.event)}</span>
            <a href={"#/runs/" + e.run_id}>{e.run_id}</a>
            <code>{JSON.stringify(e.data)}</code>
          </div>
        ))}
      </div>
    </>
  );
}
