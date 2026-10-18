import { S } from "../strings.en";

const frac = (v: unknown): [number, number] | null => {
  const m = typeof v === "string" ? v.match(/^(\d+)\/(\d+)$/) : null;
  return m ? [Number(m[1]), Number(m[2])] : null;
};

/** "Why a graph?": the evaluation's own numbers, side by side (all from claims.json, nothing typed in):
 *  the same language model with and without LastLift's graph, the count-lifts rule against max-flow, and the
 *  certification of every FalkorDB result. */
export function WhyGraph({ claims }: { claims: Record<string, any> | null }) {
  const withG = frac(claims?.eval_full_gemini_ids), without = frac(claims?.eval_llm_only_gemini_ids);
  const wrong = claims?.eval_bcount_wrong, single = claims?.eval_bcount_platforms;
  const ok = claims?.falkordb_certified, calls = claims?.maxflow_calls;
  if (!withG || !without) return null;
  const bar = (n: number, of: number, k: "good" | "bad", label: string) => (
    <div className="wg-row">
      <span className="wg-label">{label}</span>
      <span className="wg-track" aria-hidden="true"><i className={`wg-fill ${k}`} style={{ width: `${(100 * n) / of}%` }} /></span>
      <span className="wg-n">{n}<em>/{of}</em></span>
    </div>
  );
  return (
    <section className="wg" aria-labelledby="wg-h">
      <h2 id="wg-h" className="lp-title wg-title">{S.why.title}</h2>
      <p className="wg-lead">{S.why.lead}</p>
      <div className="wg-grid">
        <article className="wg-card wg-main">
          <p className="wg-kicker">{S.why.k1}</p>
          <p className="wg-q">{S.why.q1}</p>
          {bar(without[0], without[1], "bad", S.why.without)}
          {bar(withG[0], withG[1], "good", S.why.with)}
          <p className="wg-note">{S.why.n1}</p>
        </article>
        {wrong != null && single != null && <article className="wg-card">
          <p className="wg-kicker">{S.why.k2}</p>
          <p className="wg-big">{wrong}<em>/{single}</em></p>
          <p className="wg-note">{S.why.n2}</p>
        </article>}
        {ok != null && calls != null && <article className="wg-card">
          <p className="wg-kicker">{S.why.k3}</p>
          <p className="wg-big good">{ok}<em>/{calls}</em></p>
          <p className="wg-note">{S.why.n3}</p>
        </article>}
      </div>
    </section>
  );
}
