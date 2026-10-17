import { simpleOn } from "../lib/display";
import { S } from "../strings.en";

/** Redundancy shown as glyph + number + word: ✕ lost, ◐ single lift, ● lift routes, ▬ no lift needed. */
export function KState({ k }: { k: number | string | null | undefined }) {
  const W = simpleOn() ? S.simple.k : S.k;
  if (k === null || k === undefined) return <span className="state">– {W.none}</span>;
  if (k === "at grade" || k === "grade") return <span className="state" data-k="grade">▬ {W.grade}</span>;
  const n = Number(k);
  if (n === 0) return <span className="state" data-k="0">✕ {n} {W.lost}</span>;
  if (n === 1) return <span className="state" data-k="1">◐ {n} {W.one}</span>;
  return <span className="state" data-k={n >= 3 ? "3+" : "2"}>● {n} {W.many}</span>;
}
