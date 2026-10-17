import { useEffect, useMemo, useState } from "react";
import { getDays, getLifts, getStation, type StationBundle } from "../api";
import { lostWith } from "../lib/maxflow";
import { href } from "../router";
import { S } from "../strings.en";

type Ev = { fid: string; start: string; end: string; cause: string };
type Days = { from: string; to: string; days: { d: string; closed: string[]; svc_h: number }[]; events: Record<string, Ev[]>;
  collector: { source: string; polls: { t: string; closed: string[] }[] } };
type Lost = { station: string; stationId: string; platform: string; dir: "board" | "exit" };

const W = 1000, H = 120;
const fmtDay = (d: string) => new Date(`${d}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
const fmtTime = (t: string) => new Date(t).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "America/New_York" });

/** The sets of lifts closed together within one day: one set per stretch between closure starts and ends. */
function moments(day: string, evs: Ev[]): string[][] {
  const lo = Date.parse(`${day}T00:00:00-05:00`), hi = lo + 86_400_000;
  const cuts = [...new Set(evs.flatMap((e) => [Date.parse(e.start), Date.parse(e.end)]).filter((t) => t > lo && t < hi).concat([lo, hi]))].sort((a, b) => a - b);
  const sets: string[][] = [];
  for (let i = 0; i + 1 < cuts.length; i++) {
    const mid = (cuts[i] + cuts[i + 1]) / 2;
    const on = evs.filter((e) => Date.parse(e.start) <= mid && mid < Date.parse(e.end)).map((e) => e.fid);
    if (on.length) sets.push([...new Set(on)].sort());
  }
  return sets;
}

/** H4 history time machine: any day since 2024 (default the last 24 months) on today's layout, the worst moment of
 *  that day solved exactly in the browser, its closures listed; plus this week's 10-minute collector. */
export function TimeMachine() {
  const [data, setData] = useState<Days | null>(null);
  const [liftStation, setLiftStation] = useState<Record<string, { id: string; name: string }>>({});
  const [i, setI] = useState(-1);
  const [p, setP] = useState(0);
  const [bundles, setBundles] = useState<Record<string, StationBundle>>({});

  useEffect(() => {
    getDays().then((d) => { setData(d); setI(d.days.length - 1); setP(d.collector.polls.length - 1); }).catch(() => {});
    getLifts().then((d) => setLiftStation(Object.fromEntries(d.lifts.map((l: any) => [l.facility_id, { id: l.station_id, name: l.station }])))).catch(() => {});
  }, []);

  const day = data && i >= 0 ? data.days[i] : null;
  const evs = (day && data?.events[day.d]) || [];
  const poll = data?.collector.polls[p];
  const sets = useMemo(() => (day ? moments(day.d, evs) : []), [day, evs]);
  const needed = useMemo(() => [...new Set([...sets.flat(), ...(poll?.closed ?? [])].map((f) => liftStation[f]?.id).filter(Boolean) as string[])],
    [sets, poll, liftStation]);
  useEffect(() => {
    for (const s of needed) if (!bundles[s]) getStation(s).then((b) => setBundles((x) => ({ ...x, [s]: b }))).catch(() => {});
  }, [needed]);    // eslint-disable-line react-hooks/exhaustive-deps

  const solve = (closed: string[]): Lost[] => {
    const set = new Set(closed);
    return [...new Set(closed.map((f) => liftStation[f]?.id).filter(Boolean) as string[])].flatMap((s) => {
      const b = bundles[s];
      return b ? lostWith(b.graph.board, b.graph.exit, set).map((x) => ({ ...x, station: b.redundancy.data.name, stationId: s })) : [];
    });
  };
  const worst = useMemo(() => sets.map((c) => ({ closed: c, lost: solve(c) })).sort((a, b) => b.lost.length - a.lost.length)[0],
    [sets, bundles]);    // eslint-disable-line react-hooks/exhaustive-deps
  const pollLost = useMemo(() => (poll ? solve(poll.closed) : []), [poll, bundles]);    // eslint-disable-line react-hooks/exhaustive-deps

  const series = useMemo(() => {
    if (!data) return "";
    const max = Math.max(1, ...data.days.map((d) => d.svc_h));
    return data.days.map((d, k) => `${k ? "L" : "M"}${(k / (data.days.length - 1)) * W},${H - (d.svc_h / max) * (H - 8)}`).join(" ") + ` L${W},${H} L0,${H} Z`;
  }, [data]);

  if (!data || !day) return <p aria-busy="true">…</p>;
  const n = data.days.length, from24 = Math.max(0, n - 731);
  const worstDay = data.days.reduce((a, b) => (b.svc_h > a.svc_h ? b : a));
  const platformName = (l: Lost) => {
    const pl = (bundles[l.stationId]?.redundancy.data.platforms ?? []).find((x: any) => x.stop_id === l.platform);
    return pl ? [pl.platform_name, pl.name].filter(Boolean)[0] : l.platform;
  };
  return (
    <>
      <p className="eyebrow">{S.tm.eyebrow}</p>
      <h1>{S.tm.title}</h1>
      <p className="lead">{S.tm.lead}</p>
      <p className="tm-chips"><span className="chip">{S.tm.chipLayout}</span> <span className="chip">{S.tm.chipRecorded}</span>
        <span className="chip">{S.tm.chipBrowser}</span></p>

      <section className="card block" aria-labelledby="tm-h">
        <h2 id="tm-h">{fmtDay(day.d)}</h2>
        <svg viewBox={`0 0 ${W} ${H}`} className="tm-chart" aria-hidden="true" preserveAspectRatio="none"
             onClick={(e) => { const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect(); setI(Math.round(((e.clientX - r.left) / r.width) * (n - 1))); }}>
          <path d={series} className="tm-area" />
          <rect x={(from24 / (n - 1)) * W} y={0} width={W - (from24 / (n - 1)) * W} height={H} className="tm-window" />
          <line x1={(i / (n - 1)) * W} x2={(i / (n - 1)) * W} y1={0} y2={H} className="tm-cursor" />
        </svg>
        <label className="tm-slider">{S.tm.slider}
          <input type="range" min={0} max={n - 1} value={i} onChange={(e) => setI(Number(e.target.value))}
                 aria-valuetext={S.tm.valuetext(fmtDay(day.d), day.closed.length, day.svc_h)} />
        </label>
        <p className="tm-buttons">
          <button onClick={() => setI(Math.max(0, i - 1))}>{S.tm.prev}</button>
          <button onClick={() => setI(Math.min(n - 1, i + 1))}>{S.tm.next}</button>
          <button onClick={() => setI(from24)}>{S.tm.start24}</button>
          <button onClick={() => setI(data.days.indexOf(worstDay))}>{S.tm.worst(fmtDay(worstDay.d))}</button>
        </p>
        <div className="tiles compact">
          <div className="tile"><span className="n">{day.closed.length}</span><span className="l">{S.tm.tileClosed}</span></div>
          <div className="tile" data-k={worst?.lost.length ? "0" : undefined}><span className="n">{worst?.lost.length ?? 0}</span>
            <span className="l">{S.tm.tileLost}</span></div>
          <div className="tile" data-k={day.svc_h ? "1" : undefined}><span className="n">{day.svc_h}</span><span className="l">{S.tm.tileHours}</span></div>
        </div>
        {worst && worst.lost.length > 0 && <>
          <h3>{S.tm.worstMoment(worst.closed.length, worst.closed.length > 8 ? `${worst.closed.slice(0, 8).join(", ")}, …` : worst.closed.join(", "))}</h3>
          <ul className="link-list">{worst.lost.map((l) => (
            <li key={`${l.platform}-${l.dir}`}><a href={href(`/station/${l.stationId}`, { dir: l.dir })}>{l.station}</a>: {platformName(l)} {S.matrix.dir[l.dir]}</li>
          ))}</ul>
        </>}
        <h3>{S.tm.events(evs.length)}</h3>
        {evs.length === 0 ? <p className="muted">{S.tm.noEvents}</p> : (
          <div className="table-wrap tall" tabIndex={0}>
            <table><thead><tr><th scope="col">{S.tm.colLift}</th><th scope="col">{S.tm.colStation}</th><th scope="col">{S.tm.colFrom}</th>
              <th scope="col">{S.tm.colTo}</th><th scope="col">{S.tm.colCause}</th></tr></thead>
              <tbody>{evs.map((e, k) => (
                <tr key={k}><th scope="row" className="mono">{e.fid}</th><td>{liftStation[e.fid]?.name ?? "–"}</td>
                  <td>{fmtTime(e.start)}</td><td>{fmtTime(e.end)}</td><td>{e.cause.toLowerCase().replace(/_/g, " ")}</td></tr>
              ))}</tbody></table>
          </div>
        )}
      </section>

      {poll && <section className="card block" aria-labelledby="co-h">
        <h2 id="co-h">{S.tm.collectorTitle}</h2>
        <p className="muted">{S.tm.collectorHelp}</p>
        <label className="tm-slider">{S.tm.collectorSlider}
          <input type="range" min={0} max={data.collector.polls.length - 1} value={p} onChange={(e) => setP(Number(e.target.value))}
                 aria-valuetext={S.tm.pollText(fmtTime(poll.t), poll.closed.length, pollLost.length)} />
        </label>
        <p><strong>{fmtTime(poll.t)}</strong>: {S.tm.pollText(fmtTime(poll.t), poll.closed.length, pollLost.length)}</p>
        <p className="muted small">{poll.closed.join(", ")}</p>
      </section>}
    </>
  );
}
