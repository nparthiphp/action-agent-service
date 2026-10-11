import { useState } from "react";
import { TierChip } from "../components/Bits";
import { label } from "../format";
import type { ActionContract } from "../types";

const RB = { revert: "can undo", compensate: "compensate", none: "nothing to undo" } as const;

export function Catalog({ catalog }: { catalog: ActionContract[] }) {
  const [domain, setDomain] = useState("all");
  const domains = ["all", ...Array.from(new Set(catalog.map((c) => c.domain)))];
  const list = catalog.filter((c) => domain === "all" || c.domain === domain);
  return (
    <>
      <div className="chips" role="group" aria-label="Filter by domain">
        {domains.map((d) => (
          <button key={d} className="chip" aria-pressed={domain === d} onClick={() => setDomain(d)}>
            {d === "all" ? `All (${catalog.length})` : label(d)}
          </button>
        ))}
      </div>
      <div className="acts">
        {list.map((c) => (
          <article className="card act" key={c.action_id}>
            <div className="hd"><TierChip tier={c.tier} /><b>{label(c.action_id)}</b><span className={`rb-chip ${c.rollback.kind}`}>{RB[c.rollback.kind]}</span></div>
            <p>{c.summary}</p>
            <details>
              <summary>Contract</summary>
              <dl>
                <dt>Domain</dt><dd>{label(c.domain)}</dd>
                <dt>Inputs</dt><dd>{c.inputs.length ? c.inputs.join(", ") : "none"}</dd>
                <dt>Blast radius</dt><dd>{c.blast_radius}</dd>
                {c.production_floor && <><dt>In production</dt><dd>at least {c.production_floor}</dd></>}
                {c.blast_param && <><dt>Escalates when</dt><dd>{c.blast_param} is above {c.blast_limit}</dd></>}
                {c.preconditions.length > 0 && <><dt>Before running</dt><dd>{c.preconditions.join("; ")}</dd></>}
                <dt>Verified by</dt><dd>{c.verify.description}</dd>
                <dt>Rollback</dt><dd>{c.rollback.description}</dd>
              </dl>
            </details>
          </article>
        ))}
      </div>
    </>
  );
}
