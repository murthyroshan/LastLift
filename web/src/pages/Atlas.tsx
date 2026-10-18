import { useEffect, useState } from "react";
import { getAtlas, getClaims } from "../api";
import { S } from "../strings.en";

type Agency = { id: string; provider: string; country: string; license: string; platforms: number; single_lift: number;
  two_plus: number; at_grade: number; lift_dependent: number; single_lift_share: number | null; lift_units: number;
  readiness: "A" | "B" | "C"; falkordb: { checked?: number; equal?: number } };
type Atlas = { aggregate: { feeds: number; assessable: number; named: number; platforms: number; lift_dependent: number;
  single_lift: number; falkordb_checked: number; falkordb_equal: number; grades: Record<string, number>; shares: number[] };
  agencies: Agency[] };

const pct = (x: number) => `${Math.round(100 * x)}%`;

/** MS5: the same generic rules run on every agency that publishes GTFS-Pathways. Agencies are named only after the
 *  author has checked their licence; the others count in the aggregates without a name. */
export function AtlasPage() {
  const [a, setA] = useState<Atlas | null>(null);
  const [claims, setClaims] = useState<Record<string, any> | null>(null);
  useEffect(() => {
    getAtlas().then(setA).catch(() => {});
    getClaims().then(setClaims).catch(() => {});
  }, []);
  if (!a || !claims) return <p aria-busy="true">…</p>;
  const g = a.aggregate;
  const mbta = a.agencies.find((x) => x.id === "mdb-437");
  return (
    <>
      <p className="eyebrow">{S.atlas.eyebrow}</p>
      <h1>{S.atlas.title}</h1>
      <p className="lead">{S.atlas.lead}</p>
      <div className="tiles">
        <div className="tile"><span className="n">{g.feeds}</span><span className="l">{S.atlas.tileFeeds}</span></div>
        <div className="tile" data-k="2"><span className="n">{g.assessable}</span><span className="l">{S.atlas.tileAssessable}</span></div>
        <div className="tile" data-k="1"><span className="n">{pct(g.single_lift / Math.max(1, g.lift_dependent))}</span>
          <span className="l">{S.atlas.tileShare(g.single_lift, g.lift_dependent)}</span></div>
        <div className="tile" data-k="2"><span className="n">{g.falkordb_equal}/{g.falkordb_checked}</span>
          <span className="l">{S.atlas.tileChecks}</span></div>
      </div>

      <section className="card block" aria-labelledby="sh-h">
        <h2 id="sh-h">{S.atlas.sharesTitle}</h2>
        <p className="muted">{S.atlas.sharesHelp}</p>
        <div className="share-strip" aria-hidden="true">
          <div className="share-axis"><span>{pct(0)}</span><span>{pct(0.5)}</span><span>{pct(1)}</span></div>
          <div className="share-track">
            {g.shares.map((s, i) => (
              <i key={i} className={`share-dot ${mbta && Math.abs((mbta.single_lift_share ?? -1) - s) < 1e-9 ? "mbta" : ""}`}
                 style={{ left: `${100 * s}%`, top: `${12 + (i % 3) * 14}px` }} />
            ))}
          </div>
        </div>
        <p className="small">{S.atlas.sharesText(g.shares.map(pct).join(", "), mbta ? pct(mbta.single_lift_share ?? 0) : "")}</p>
      </section>

      {mbta && <section className="card block" aria-labelledby="or-h">
        <h2 id="or-h">{S.atlas.oracleTitle}</h2>
        <p>{S.atlas.oracle(mbta.single_lift, claims.platforms_single_lift)}</p>
      </section>}

      <section className="block" aria-labelledby="ag-h">
        <h2 id="ag-h">{S.atlas.tableTitle}</h2>
        <div className="table-wrap" tabIndex={0}>
          <table>
            <thead><tr><th scope="col">{S.atlas.colAgency}</th><th scope="col" className="num">{S.atlas.colPlatforms}</th>
              <th scope="col" className="num">{S.atlas.colSingle}</th><th scope="col" className="num">{S.atlas.colTwo}</th>
              <th scope="col" className="num">{S.atlas.colLifts}</th><th scope="col">{S.atlas.colGrade}</th>
              <th scope="col">{S.atlas.colChecked}</th></tr></thead>
            <tbody>
              {a.agencies.map((x) => (
                <tr key={x.id}>
                  <th scope="row">{x.provider} <span className="muted">({x.country})</span>
                    {x.license && <> · <a className="small" href={x.license} target="_blank" rel="noopener noreferrer"
                      aria-label={S.atlas.licenceOf(x.provider)}>{S.atlas.licence}</a></>}</th>
                  <td className="num">{x.platforms}</td><td className="num">{x.single_lift}</td><td className="num">{x.two_plus}</td>
                  <td className="num">{x.lift_units}</td><td>{S.atlas.grade[x.readiness]}</td>
                  <td>{S.atlas.checked(x.falkordb.equal ?? 0, x.falkordb.checked ?? 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small">{S.atlas.unnamed(g.feeds - g.named)}</p>
      </section>

      <section className="card block" aria-labelledby="gr-h">
        <h2 id="gr-h">{S.atlas.gradesTitle}</h2>
        <ul className="link-list">
          {(["A", "B", "C"] as const).map((k) => <li key={k}><strong>{S.atlas.grade[k]}</strong>: {S.atlas.gradeText[k]} ({g.grades[k] ?? 0})</li>)}
        </ul>
        <p className="muted small">{S.atlas.rules}</p>
      </section>
    </>
  );
}
