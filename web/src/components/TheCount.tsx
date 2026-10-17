import { useEffect, useMemo, useState } from "react";
import { getSystem } from "../api";
import { href } from "../router";
import { S } from "../strings.en";

type Bin = "grade" | "many" | "one" | "lost" | "none";
type P = { stop: string; station: string; name: string; board: { base: Bin; now: Bin }; exit: { base: Bin; now: Bin } };
const BINS: Bin[] = ["grade", "many", "one", "lost", "none"];
const COLS = 10, GAP = 13, BIN_W = 196, TOP = 92;

function Glyph({ bin }: { bin: Bin }) {
  if (bin === "grade") return <circle r={4.6} className="dot-grade" />;
  if (bin === "many") return <circle r={5} className="dot-many" />;
  if (bin === "one") return <rect x={-4.6} y={-4.6} width={9.2} height={9.2} transform="rotate(45)" className="dot-one" />;
  if (bin === "lost") return <path d="M-4.5,-4.5L4.5,4.5M4.5,-4.5L-4.5,4.5" className="dot-lost" />;
  return <circle r={2.6} className="dot-none" />;
}

/** One dot per modelled platform, in five bins; switching Baseline / Now moves the platforms that changed bins
 *  (a CSS transform transition, none under reduced motion). The figure caption and the bins' lists carry the same
 *  facts in words; the dots are decorative. */
export function TheCount() {
  const [platforms, setPlatforms] = useState<P[]>([]);
  const [when, setWhen] = useState<"base" | "now">("base");
  const [dir, setDir] = useState<"board" | "exit">("board");
  useEffect(() => { getSystem().then((s) => setPlatforms(s.platforms)).catch(() => {}); }, []);

  const { pos, counts, moved } = useMemo(() => {
    const groups: Record<Bin, P[]> = { "grade": [], "many": [], "one": [], "lost": [], "none": [] };
    for (const p of platforms) groups[p[dir][when]].push(p);
    const pos = new Map<string, { x: number; y: number; bin: Bin }>();
    BINS.forEach((b, i) => groups[b].forEach((p, j) =>
      pos.set(p.stop, { x: i * BIN_W + 14 + (j % COLS) * GAP, y: TOP + Math.floor(j / COLS) * GAP, bin: b })));
    const counts = Object.fromEntries(BINS.map((b) => [b, groups[b].length])) as Record<Bin, number>;
    const moved = new Set(platforms.filter((p) => p[dir].base !== p[dir].now).map((p) => p.stop));
    return { pos, counts, moved };
  }, [platforms, when, dir]);

  if (!platforms.length) return null;
  const rows = Math.max(...BINS.map((b) => Math.ceil(counts[b] / COLS)));
  const lostNow = platforms.filter((p) => p[dir].now === "lost" && p[dir].base !== "lost").length;
  const oneNow = platforms.filter((p) => p[dir].now === "one" && p[dir].base !== "one").length;
  return (
    <figure className="count-fig">
      <div className="count-controls">
        <div role="radiogroup" aria-label={S.count.whenLabel}>
          {(["base", "now"] as const).map((w) => (
            <button key={w} role="radio" aria-checked={when === w} onClick={() => setWhen(w)}>{S.count.when[w]}</button>
          ))}
        </div>
        <div role="radiogroup" aria-label={S.count.dirLabel}>
          {(["board", "exit"] as const).map((d) => (
            <button key={d} role="radio" aria-checked={dir === d} onClick={() => setDir(d)}>{S.count.dir[d]}</button>
          ))}
        </div>
      </div>
      <svg viewBox={`0 0 ${BIN_W * 5} ${TOP + rows * GAP + 10}`} className="count-svg" aria-hidden="true">
        {BINS.map((b, i) => (
          <g key={b} transform={`translate(${i * BIN_W + 10},0)`}>
            <text y={34} className={`count-num ${b === "one" ? "hero" : ""}`}>{counts[b]}</text>
            <text y={58} className="count-label">{S.count.bins[b]}</text>
          </g>
        ))}
        {platforms.map((p) => {
          const q = pos.get(p.stop)!;
          return (
            <g key={p.stop} className={`count-dot ${when === "now" && moved.has(p.stop) ? "moved" : ""}`}
               style={{ transform: `translate(${q.x}px, ${q.y}px)` }}>
              <Glyph bin={q.bin} />
            </g>
          );
        })}
      </svg>
      <figcaption>
        {S.count.caption(counts["one"], counts["many"], counts["grade"], counts["lost"], counts["none"], S.count.dir[dir])}
        {when === "now" && <> {S.count.delta(lostNow, oneNow)}</>}
      </figcaption>
      <div className="count-lists">
        {BINS.map((b) => (
          <details key={b}>
            <summary>{S.count.bins[b]}: {counts[b]}</summary>
            <ul>{platforms.filter((p) => pos.get(p.stop)?.bin === b).map((p) => (
              <li key={p.stop}><a href={href(`/station/${p.station}`)}>{p.name}</a></li>
            ))}</ul>
          </details>
        ))}
      </div>
    </figure>
  );
}
