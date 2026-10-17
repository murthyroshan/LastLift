import { useMemo } from "react";
import type { StationGraph } from "../api";
import { nMinusOne } from "../lib/maxflow";
import { S } from "../strings.en";

/** UI7 N-1 stress matrix: rows are lift-dependent platform-directions, columns are the station's working lifts, each
 *  cell the lift-disjoint routes left if that one lift closes. The intact counts are checked against FalkorDB's
 *  certified values and the result is shown. A cell is a button that simulates that closure. */
export function StressMatrix({ board, exit, name, onSimulate }: { board: StationGraph; exit: StationGraph;
  name: (platform: string) => string; onSimulate?: (fid: string) => void }) {
  // the max-flows depend only on the graphs; names are applied at render time
  const solved = useMemo(() => nMinusOne(board, exit), [board, exit]);
  const { lifts, rows, checked, agree } = useMemo(() => {
    const { lifts, cells } = solved;
    const byRow = new Map<string, typeof cells>();
    for (const c of cells) {
      const k = `${c.platform}|${c.dir}`;
      if (!byRow.has(k)) byRow.set(k, []);
      byRow.get(k)!.push(c);
    }
    let checked = 0, agree = 0;
    const rows = [...byRow.entries()].flatMap(([k, cs]) => {
      const [platform, dir] = k.split("|") as [string, "board" | "exit"];
      const node = (dir === "board" ? board : exit).nodes.find((n) => n.id === platform);
      const certified = dir === "board" ? node?.k_board : node?.k_exit;
      if (typeof certified === "number") { checked += 1; if (certified === cs[0].base) agree += 1; }
      return cs[0].base === null || cs[0].base === 0 ? [] : [{ platform, dir, base: cs[0].base, cells: cs }];
    }).sort((a, b) => (a.base ?? 9) - (b.base ?? 9) || name(a.platform).localeCompare(name(b.platform)));
    return { lifts, rows, checked, agree };
  }, [solved, board, exit, name]);

  if (!rows.length || !lifts.length) return null;
  return (
    <section className="card block matrix" aria-labelledby="mx-h">
      <h2 id="mx-h">{S.matrix.title}</h2>
      <p className="muted">{S.matrix.help}</p>
      <p className="small"><span className="chip ok">✓ {S.matrix.matches(agree, checked)}</span></p>
      <div className="table-wrap" tabIndex={0}>
        <table className="heat">
          <caption className="visually-hidden">{S.matrix.caption}</caption>
          <thead><tr><th scope="col">{S.matrix.rowHead}</th><th scope="col" className="num">{S.matrix.now}</th>
            {lifts.map((f) => <th key={f} scope="col" className="num mono">{f}</th>)}</tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.platform}-${r.dir}`}>
                <th scope="row">{name(r.platform)} <span className="muted">{S.matrix.dir[r.dir]}</span></th>
                <td className="num"><strong>{r.base}</strong></td>
                {r.cells.map((c) => {
                  const k = c.after ?? 0, drop = (c.base ?? 0) - k;
                  return (
                    <td key={c.fid} className="num">
                      <button className="heat-cell" data-k={k >= 2 ? "2" : String(k)} data-drop={drop > 0 ? "yes" : undefined}
                              aria-label={S.matrix.cell(c.fid, name(r.platform), S.matrix.dir[r.dir], k, c.base ?? 0)}
                              onClick={() => onSimulate?.(c.fid)} disabled={!onSimulate}>
                        {k}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">{S.matrix.legend}</p>
    </section>
  );
}
