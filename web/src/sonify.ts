// "Hear the last lift": one tone per independent step-free route (the certified k). Closing a lift drops the tones of
// the routes that cross it; a single surviving route trembles (one failure from no route); no route at all is a
// falling two-note earcon. A pure mapping (chord) plus one Web Audio player. Nothing sounds before a user gesture,
// and every sound has a text twin announced at the same time (the callers do that).

export type Route = { label: string; lifts: string[] };
export type Voice = { label: string; freq: number; active: boolean };
export type Plan = { voices: Voice[]; tremolo: boolean; earcon: boolean; active: number };

const FREQS = [220, 330, 440, 554, 660];

/** The chord for a platform-direction: its routes, with the given lifts closed. */
export function chord(routes: Route[], closed: string[] = []): Plan {
  const shut = new Set(closed);
  const voices = routes.slice(0, FREQS.length).map((r, i) => ({
    label: r.label, freq: FREQS[i], active: !r.lifts.some((l) => shut.has(l)),
  }));
  const active = voices.filter((v) => v.active).length;
  return { voices, active, tremolo: active === 1, earcon: routes.length > 0 && active === 0 };
}

let ctx: AudioContext | null = null;

/** Play a plan. With `before`, the routes play first, then the dropped voices fade out (the audible "drop"). */
export async function play(plan: Plan, volume = 0.6, before?: Plan): Promise<void> {
  ctx = ctx ?? new AudioContext();
  if (ctx.state === "suspended") await ctx.resume();
  const now = ctx.currentTime;
  const master = ctx.createGain();
  master.gain.value = Math.max(0, Math.min(1, volume));
  master.connect(ctx.destination);
  const start = before ?? plan;
  const n = Math.max(1, start.voices.length);
  const dropAt = before ? 1.0 : Infinity;
  start.voices.forEach((v, i) => {
    const osc = ctx!.createOscillator(), tri = ctx!.createOscillator(), g = ctx!.createGain();
    osc.type = "sine"; tri.type = "triangle";
    osc.frequency.value = v.freq; tri.frequency.value = v.freq;
    g.gain.setValueAtTime(0, now);
    g.gain.linearRampToValueAtTime(0.12 / n, now + 0.08);
    const stillActive = plan.voices[i]?.active ?? false;
    if (before && v.active && !stillActive) g.gain.linearRampToValueAtTime(0, now + dropAt + 0.4);
    const survivorAlone = plan.tremolo && stillActive;
    if (survivorAlone) {                           // 5 Hz tremolo on the last route
      const lfo = ctx!.createOscillator(), depth = ctx!.createGain();
      lfo.frequency.value = 5; depth.gain.value = 0.05 / n;
      lfo.connect(depth).connect(g.gain);
      lfo.start(now + (before ? dropAt : 0)); lfo.stop(now + 2.6);
    }
    g.gain.linearRampToValueAtTime(0, now + 2.6);
    osc.connect(g); tri.connect(g); g.connect(master);
    if (!(before ? v.active : true) && before) return;
    osc.start(now); tri.start(now); osc.stop(now + 2.7); tri.stop(now + 2.7);
  });
  if (plan.earcon) {                               // no route left: 196 -> 147 Hz, 2 x 250 ms
    [196, 147].forEach((f, i) => {
      const o = ctx!.createOscillator(), g = ctx!.createGain();
      const t = now + (before ? dropAt + 0.5 : 0) + i * 0.3;
      o.frequency.value = f; o.type = "sine";
      g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(0.25, t + 0.03);
      g.gain.linearRampToValueAtTime(0, t + 0.25);
      o.connect(g).connect(master); o.start(t); o.stop(t + 0.27);
    });
  }
}

export function stopAll(): void {
  ctx?.close();
  ctx = null;
}

/** Sound on or off, remembered per browser (never required; any storage failure means off). */
export function soundOn(): boolean {
  try { return window.localStorage.getItem("lastlift.sound") === "on"; } catch { return false; }
}
export function setSoundOn(on: boolean): void {
  try { window.localStorage.setItem("lastlift.sound", on ? "on" : "off"); } catch { /* storage unavailable */ }
}
