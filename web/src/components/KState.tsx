import { S } from "../strings.en";

/** Redundancy shown as glyph + number + word: ✕ lost, ◐ single lift, ● lift routes, ▬ no lift needed. */
export function KState({ k }: { k: number | string | null | undefined }) {
  if (k === null || k === undefined) return <span className="state">– {S.k.none}</span>;
  if (k === "at grade" || k === "grade") return <span className="state" data-k="grade">▬ {S.k.grade}</span>;
  const n = Number(k);
  if (n === 0) return <span className="state" data-k="0">✕ {n} {S.k.lost}</span>;
  if (n === 1) return <span className="state" data-k="1">◐ {n} {S.k.one}</span>;
  return <span className="state" data-k={n >= 3 ? "3+" : "2"}>● {n} {S.k.many}</span>;
}
