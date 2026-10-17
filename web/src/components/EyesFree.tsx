import { useEffect, useRef, useState } from "react";
import { API_BASE, askLive, getReplay, getReplayIndex } from "../api";
import { S } from "../strings.en";

type Ev = Record<string, any>;
type Said = { who: "you" | "lastlift"; text: string };

let actx: AudioContext | null = null;
function earcon(up: boolean) {                       // two short notes: rising = listening, falling = stopped
  try {
    actx = actx ?? new AudioContext();
    const now = actx.currentTime;
    (up ? [523, 659] : [659, 523]).forEach((f, i) => {
      const o = actx!.createOscillator(), g = actx!.createGain();
      o.frequency.value = f; g.gain.setValueAtTime(0.0001, now + i * 0.12);
      g.gain.linearRampToValueAtTime(0.15, now + i * 0.12 + 0.02); g.gain.linearRampToValueAtTime(0, now + i * 0.12 + 0.1);
      o.connect(g).connect(actx!.destination); o.start(now + i * 0.12); o.stop(now + i * 0.12 + 0.11);
    });
  } catch { /* no audio: the transcript still shows everything */ }
}

const words = (s: string) => new Set(s.toLowerCase().match(/[a-z0-9]+/g) ?? []);

/** Eyes-free mode: ask out loud (or type), hear a graph-checked answer, then walk its steps, ask why, repeat or stop.
 *  Speech recognition comes from the browser, with a server fallback; speech comes from the browser, or only from
 *  the screen reader (aria-live) in "screen reader voices it" mode, so nothing is spoken twice. Everything said is
 *  in the transcript. Without the server, answers come from the recorded runs. */
export function EyesFree({ live, onClose }: { live: boolean; onClose: () => void }) {
  const [said, setSaid] = useState<Said[]>([]);
  const [listening, setListening] = useState(false);
  const [srMode, setSrMode] = useState(false);
  const [rate, setRate] = useState(1);
  const [typed, setTyped] = useState("");
  const [liveText, setLiveText] = useState("");
  const steps = useRef<string[]>([]);
  const at = useRef(-1);
  const last = useRef("");
  const answerText = useRef("");
  const rec = useRef<any>(null);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => { heading.current?.focus(); say(S.eyes.welcome); return () => window.speechSynthesis?.cancel(); }, []);

  function say(text: string) {
    last.current = text;
    setSaid((s) => [...s, { who: "lastlift", text }]);
    if (srMode || !("speechSynthesis" in window)) { setLiveText(""); window.setTimeout(() => setLiveText(text), 30); return; }
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "en-US"; u.rate = rate;
    window.speechSynthesis.speak(u);
  }

  function stop() { window.speechSynthesis?.cancel(); rec.current?.stop?.(); setListening(false); }

  async function answer(question: string) {
    say(S.eyes.thinking);
    let events: Ev[] = [];
    if (live) {
      events = await new Promise<Ev[]>((resolve) => {
        const seen: Ev[] = [];
        askLive(question, (e) => { seen.push(e); if (e.type === "done") resolve(seen); });
      });
    } else {
      const index = await getReplayIndex().catch(() => []);
      const q = words(question);
      const best = index.map((r) => ({ r, n: [...words(r.question)].filter((w) => q.has(w) && w.length > 3).length }))
        .sort((a, b) => b.n - a.n)[0];
      if (!best || best.n < 2) { say(S.eyes.needsLive); return; }
      const recd = await getReplay(best.r.id);
      events = recd.events;
      say(S.eyes.recorded(recd.question));
    }
    steps.current = events.filter((e) => e.type === "tool_result").map((e) => e.summary);
    at.current = -1;
    const a = events.find((e) => e.type === "answer");
    answerText.current = a?.text ?? S.eyes.noAnswer;
    say(`${answerText.current} ${S.eyes.commands(steps.current.length)}`);
  }

  function handle(textRaw: string) {
    const text = textRaw.trim();
    if (!text) return;
    setSaid((s) => [...s, { who: "you", text }]);
    const t = text.toLowerCase();
    if (/^(stop|quiet|cancel)\b/.test(t)) { stop(); return; }
    if (/^repeat|say (that|it) again/.test(t)) { say(last.current); return; }
    if (/slower/.test(t)) { setRate((r) => Math.max(0.8, r - 0.2)); say(S.eyes.slower); return; }
    if (/faster/.test(t)) { setRate((r) => Math.min(1.4, r + 0.2)); say(S.eyes.faster); return; }
    if (/walk me through|step by step|^next/.test(t)) {
      if (!steps.current.length) { say(S.eyes.noSteps); return; }
      at.current = Math.min(at.current + 1, steps.current.length - 1);
      say(S.eyes.step(at.current + 1, steps.current.length, steps.current[at.current])); return;
    }
    if (/^(back|previous)/.test(t)) {
      if (!steps.current.length) { say(S.eyes.noSteps); return; }
      at.current = Math.max(at.current - 1, 0);
      say(S.eyes.step(at.current + 1, steps.current.length, steps.current[at.current])); return;
    }
    if (/^why\b/.test(t)) {
      const proof = steps.current.find((s) => /platforms?;|lift routes|single lift|loses step-free/.test(s)) ?? steps.current[0];
      say(proof ? S.eyes.why(proof) : S.eyes.noSteps); return;
    }
    void answer(text);
  }

  async function listen() {
    if (listening) { stop(); return; }
    const SR = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;
    earcon(true);
    setListening(true);
    if (SR) {
      const r = new SR();
      rec.current = r;
      r.lang = "en-US"; r.continuous = false; r.interimResults = false;
      r.onresult = (e: any) => handle(e.results[0][0].transcript);
      r.onend = () => { setListening(false); earcon(false); };
      r.onerror = () => { setListening(false); say(S.eyes.heardNothing); };
      r.start();
      return;
    }
    try {                                             // fallback: record up to 8 s and send it to the server
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      mr.ondataavailable = (e) => chunks.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((tr) => tr.stop());
        setListening(false); earcon(false);
        const blob = new Blob(chunks, { type: mr.mimeType || "audio/webm" });
        const r = await fetch(`${API_BASE}/v1/stt`, { method: "POST", body: blob,
          headers: { "Content-Type": blob.type } }).then((x) => x.json()).catch(() => null);
        if (r?.text) handle(r.text); else say(S.eyes.heardNothing);
      };
      rec.current = mr;
      mr.start();
      window.setTimeout(() => mr.state === "recording" && mr.stop(), 8000);
    } catch {
      setListening(false);
      say(S.eyes.noMic);
    }
  }

  useEffect(() => {                                   // hold Space to talk (not while typing)
    const down = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (e.code === "Space" && !e.repeat && !["INPUT", "TEXTAREA", "BUTTON", "SELECT"].includes(tag)) {
        e.preventDefault(); void listen();
      }
      if (e.key === "Escape") stop();
    };
    window.addEventListener("keydown", down);
    return () => window.removeEventListener("keydown", down);
  });

  return (
    <aside className="eyes" aria-labelledby="ef-h">
      <h2 id="ef-h" tabIndex={-1} ref={heading}>{S.eyes.title}</h2>
      <p>{S.eyes.intro}</p>
      <p>
        <button className="mic" aria-pressed={listening} onClick={() => void listen()}>
          <span aria-hidden="true">🎙</span> {listening ? S.eyes.listening : S.eyes.talk}
        </button>{" "}
        <button onClick={stop}>{S.eyes.stop}</button>{" "}
        <button onClick={onClose}>{S.agent.close}</button>
      </p>
      <form onSubmit={(e) => { e.preventDefault(); handle(typed); setTyped(""); }}>
        <label htmlFor="ef-q">{S.eyes.typeLabel}</label><br />
        <input id="ef-q" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={S.eyes.placeholder} />{" "}
        <button>{S.eyes.send}</button>
      </form>
      <p>
        <label><input type="checkbox" checked={srMode} onChange={(e) => setSrMode(e.target.checked)} /> {S.eyes.srMode}</label>
        {"  "}
        <label>{S.eyes.rate}{" "}
          <input type="range" min={0.8} max={1.4} step={0.1} value={rate} onChange={(e) => setRate(Number(e.target.value))} />
        </label>
      </p>
      <div aria-live="assertive" className="visually-hidden">{liveText}</div>
      <h3>{S.eyes.transcript}</h3>
      <ol className="transcript" tabIndex={0} aria-label={S.eyes.transcript}>
        {said.map((x, i) => <li key={i}><strong>{x.who === "you" ? S.eyes.you : S.eyes.us}:</strong> {x.text}</li>)}
      </ol>
    </aside>
  );
}

export const isEyesFree = () => new URLSearchParams(window.location.search).get("eyesfree") === "1";
