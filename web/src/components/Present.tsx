import { useEffect, useRef, useState } from "react";
import { S } from "../strings.en";

type Beat = { label: string; url: string; dwell: number; scroll?: string };

/** Present mode (?present=1): a deterministic stage for recording. Larger type, a keystroke chip,
 *  beat hotkeys (1-8, "." next, A autopilot), G for a caption frame, ? for help. Single-key shortcuts exist
 *  only in this mode (WCAG 2.1.4). */
export function Present() {
  const [beats, setBeats] = useState<Beat[]>([]);
  const [at, setAt] = useState(-1);
  const [auto, setAuto] = useState(false);
  const [frame, setFrame] = useState(false);
  const [help, setHelp] = useState(false);
  const [chip, setChip] = useState("");
  const chipTimer = useRef(0);

  useEffect(() => {
    document.documentElement.classList.add("present");
    fetch(`${import.meta.env.BASE_URL}present/beats.json`).then((r) => r.json()).then(setBeats).catch(() => {});
    return () => document.documentElement.classList.remove("present");
  }, []);

  function go(i: number) {
    const b = beats[i];
    if (!b) return;
    setAt(i);
    window.location.hash = b.url.replace(/^#/, "");
    if (b.scroll) window.setTimeout(() => document.getElementById(b.scroll!)?.scrollIntoView({ block: "start" }), 600);
    else window.scrollTo(0, 0);
  }

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
      const names: Record<string, string> = { Tab: "Tab", Enter: "Enter", " ": "Space", ArrowRight: "→",
        ArrowLeft: "←", ArrowUp: "↑", ArrowDown: "↓", Escape: "Esc" };
      if (names[e.key]) {
        setChip((e.shiftKey ? "Shift + " : "") + names[e.key]);
        window.clearTimeout(chipTimer.current);
        chipTimer.current = window.setTimeout(() => setChip(""), 1200);
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (/^[1-8]$/.test(e.key)) go(Number(e.key) - 1);
      else if (e.key === ".") go(Math.min(at + 1, beats.length - 1));
      else if (e.key === "a" || e.key === "A") setAuto((v) => !v);
      else if (e.key === "g" || e.key === "G") setFrame((v) => !v);
      else if (e.key === "?") setHelp((v) => !v);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  useEffect(() => {                                   // autopilot: every beat in order, with its dwell time
    if (!auto || !beats.length) return;
    const next = at + 1;
    if (next >= beats.length) { setAuto(false); return; }
    const timer = window.setTimeout(() => go(next), at < 0 ? 0 : beats[at].dwell);
    return () => window.clearTimeout(timer);
  }, [auto, at, beats]);

  return (
    <>
      {chip && <div className="present-chip" aria-hidden="true">{chip}</div>}
      {frame && <div className="present-frame" aria-hidden="true"><div className="present-captions" /></div>}
      {help && (
        <div role="dialog" aria-modal="false" aria-labelledby="ph-h" className="present-help">
          <h2 id="ph-h">{S.present.title}</h2>
          <ul>{S.present.keys.map((k) => <li key={k}>{k}</li>)}</ul>
          <ol>{beats.map((b) => <li key={b.label}>{b.label}</li>)}</ol>
          <button onClick={() => setHelp(false)}>{S.agent.close}</button>
        </div>
      )}
    </>
  );
}

export const isPresent = () => new URLSearchParams(window.location.search).get("present") === "1";
