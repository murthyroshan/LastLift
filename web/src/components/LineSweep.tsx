import { useEffect, useMemo, useRef, useState } from "react";
import { getLines, getMap, getSystem } from "../api";
import { playStep, type Bin } from "../sonify";
import { S } from "../strings.en";
import { useAnnounce } from "./Announcer";

const STEP_MS = 700;
const ORDER: Bin[] = ["lost", "one", "many", "grade", "none"];

/** MS2 city sweep: hear a line station by station, each station's worst step-free state now. Nothing sounds before
 *  Play; Stop ends it at once; every step is highlighted and announced as text. */
export function LineSweep() {
  const [lines, setLines] = useState<{ route_id: string; name: string; toward: string; stations: string[] }[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [worst, setWorst] = useState<Record<string, Bin>>({});
  const [pick, setPick] = useState(0);
  const [at, setAt] = useState(-1);
  const timers = useRef<number[]>([]);
  const announce = useAnnounce();

  useEffect(() => {
    getLines().then((d) => setLines(d.lines)).catch(() => {});
    getMap().then((m) => setNames(Object.fromEntries(m.stations.map((s: any) => [s.id, s.name])))).catch(() => {});
    getSystem().then((s) => {
      const w: Record<string, Bin> = {};
      for (const p of s.platforms) for (const b of [p.board.now, p.exit.now] as Bin[]) {
        const cur = w[p.station];
        if (!cur || ORDER.indexOf(b) < ORDER.indexOf(cur)) w[p.station] = b;
      }
      setWorst(w);
    }).catch(() => {});
    return () => timers.current.forEach(clearTimeout);
  }, []);

  const line = lines[pick];
  const steps = useMemo(() => (line?.stations ?? []).map((id) => ({ id, name: names[id] ?? id, bin: worst[id] ?? "none" as Bin })),
    [line, names, worst]);

  function stop() { timers.current.forEach(clearTimeout); timers.current = []; setAt(-1); }
  function play() {
    stop();
    announce(S.sweep.starting(line.name, line.toward, steps.length));
    steps.forEach((s, i) => {
      timers.current.push(window.setTimeout(() => {
        setAt(i);
        void playStep(s.bin).catch(() => {});
        announce(S.sweep.step(s.name, S.sweep.word[s.bin]));
        if (i === steps.length - 1) timers.current.push(window.setTimeout(() => setAt(-1), STEP_MS));
      }, 400 + i * STEP_MS));
    });
  }

  if (!lines.length) return null;
  const counts = ORDER.map((b) => [b, steps.filter((s) => s.bin === b).length] as const);
  return (
    <section className="card block sweep" aria-labelledby="sw-h">
      <h2 id="sw-h">{S.sweep.title}</h2>
      <p className="muted">{S.sweep.help}</p>
      <div role="radiogroup" aria-label={S.sweep.pick} className="lift-chips">
        {lines.map((l, i) => (
          <button key={`${l.route_id}-${l.toward}`} role="radio" aria-checked={pick === i}
                  onClick={() => { stop(); setPick(i); }}>
            {l.name} <span className="muted">→ {l.toward}</span>
          </button>
        ))}
      </div>
      <p className="sweep-controls">
        <button className="primary" onClick={play}>{S.sweep.play}</button>{" "}
        <button onClick={stop} disabled={at < 0}>{S.sweep.stop}</button>
        <span className="muted small"> {S.sweep.summary(counts.map(([b, n]) => `${n} ${S.sweep.word[b]}`).join(", "))}</span>
      </p>
      <ol className="sweep-line" tabIndex={0} aria-label={S.sweep.lineLabel(line.name, line.toward)}>
        {steps.map((s, i) => (
          <li key={`${s.id}-${i}`} data-bin={s.bin} aria-current={i === at ? "step" : undefined}>
            <span className="sw-dot" aria-hidden="true" />
            <span className="sw-name">{s.name}</span>
            <span className="visually-hidden">: {S.sweep.word[s.bin]}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
