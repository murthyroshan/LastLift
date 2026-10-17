import { useEffect, useRef } from "react";
import type { Display } from "../lib/display";
import { S } from "../strings.en";

/** The display and reading panel (UI11): a non-modal dialog; Escape closes it and returns focus to its button. */
export function DisplayPanel({ value, onChange, onClose, eyes, onEyes }: { value: Display; onChange: (d: Display) => void;
  onClose: () => void; eyes: boolean; onEyes: (on: boolean) => void }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    box.current?.querySelector<HTMLElement>("input, button")?.focus();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  const set = (p: Partial<Display>) => onChange({ ...value, ...p });
  return (
    <div className="display-panel" role="dialog" aria-modal="false" aria-labelledby="dp-h" ref={box}>
      <h2 id="dp-h">{S.display.title}</h2>
      <fieldset>
        <legend>{S.display.theme}</legend>
        {(["system", "light", "dark", "contrast"] as const).map((t) => (
          <label key={t} className="dp-opt"><input type="radio" name="dp-theme" checked={value.theme === t} onChange={() => set({ theme: t })} />
            {S.display.themes[t]}</label>
        ))}
      </fieldset>
      <label className="dp-row">{S.display.size(value.size)}
        <input type="range" min={100} max={200} step={10} value={value.size} onChange={(e) => set({ size: Number(e.target.value) })}
               aria-valuetext={S.display.size(value.size)} />
      </label>
      <label className="dp-check"><input type="checkbox" checked={value.motion === "reduce"}
        onChange={(e) => set({ motion: e.target.checked ? "reduce" : "system" })} /> {S.display.motion}</label>
      <label className="dp-check"><input type="checkbox" checked={value.simple} onChange={(e) => set({ simple: e.target.checked })} />
        {S.display.simple}</label>
      <label className="dp-check"><input type="checkbox" checked={!!value.readable} onChange={(e) => set({ readable: e.target.checked })} />
        {S.display.readable}</label>
      <label className="dp-check"><input type="checkbox" checked={eyes} onChange={(e) => onEyes(e.target.checked)} />
        {S.display.eyes}</label>
      <p className="muted small">{S.display.note}</p>
      <button onClick={onClose}>{S.agent.close}</button>
    </div>
  );
}
