import { useEffect, useRef, useState } from "react";
import { getReplay } from "../api";
import { href } from "../router";
import { S } from "../strings.en";

const RUN = "whatif-813";
const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

type Step = { tool: string; args: string; summary: string; ms?: number; via?: string };

/** The landing's proof that the agent is real: one recorded run (a language model calling LastLift's tools over MCP,
 *  each answer claim checked against the tool results) played back step by step when it scrolls into view. */
export function AgentShowcase() {
  const [run, setRun] = useState<{ question: string; steps: Step[]; answer: string; grounded: boolean; ms: number } | null>(null);
  const [shown, setShown] = useState(0);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getReplay(RUN).then((r) => {
      const ev: any[] = r.events ?? [];
      const calls = ev.filter((c) => c.type === "tool_call");      // recorded runs pair calls and results by order
      const steps = ev.filter((e) => e.type === "tool_result").map((e, i) => {
        const call = calls.find((c) => c.span_id && c.span_id === e.span_id) ?? calls[i];
        const args = Object.entries(call?.args ?? {}).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : v}`).join(" · ");
        return { tool: e.tool, args, summary: e.summary ?? "", ms: e.ms, via: e.via };
      });
      const ans = ev.find((e) => e.type === "answer");
      const done = ev.find((e) => e.type === "done");
      setRun({ question: r.question, steps, answer: ans?.text ?? r.answer ?? "", grounded: !!ans?.grounded, ms: done?.ms ?? 0 });
    }).catch(() => {});
  }, []);

  // play once, when the card is on screen: the question, each tool call, then the checked answer
  useEffect(() => {
    if (!run) return;
    const total = run.steps.length + 2;
    if (reduced() || navigator.webdriver) { setShown(total); return; }   // no playback for reduced motion or automation
    let timer = 0;
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return;
      io.disconnect();
      let i = 0;
      const tick = () => { i += 1; setShown(i); if (i < total) timer = window.setTimeout(tick, i === 1 ? 900 : 1100); };
      tick();
    }, { threshold: 0.35 });
    if (box.current) io.observe(box.current);
    return () => { io.disconnect(); clearTimeout(timer); };
  }, [run]);

  if (!run) return null;
  const answerOn = shown >= run.steps.length + 2;
  return (
    <section className="as" aria-labelledby="as-h">
      <h2 id="as-h" className="lp-title as-title">{S.showcase.title}</h2>
      <p className="as-lead">{S.showcase.lead}</p>
      <div className="as-card" ref={box}>
        <p className="as-q"><span className="as-who">{S.showcase.you}</span>{run.question}</p>
        <ol className="as-steps" aria-label={S.showcase.steps}>
          {run.steps.map((s, i) => (
            <li key={i} className={shown >= i + 2 ? "on" : ""}>
              <span className="as-tool">{s.tool}</span>
              {s.args && <span className="as-args">{s.args}</span>}
              <span className="as-sum">{s.summary}</span>
              <span className="as-meta">{s.via === "mcp" ? S.showcase.viaMcp : ""}{s.ms != null ? ` · ${Math.round(s.ms)} ms` : ""}</span>
            </li>
          ))}
        </ol>
        <div className={`as-answer ${answerOn ? "on" : ""}`} aria-live="polite">
          {answerOn && <>
            <p className="as-check">{run.grounded ? S.showcase.grounded : S.showcase.ungrounded}</p>
            <p className="as-text">{run.answer}</p>
            <p className="as-foot">{S.showcase.foot(Math.round(run.ms))}</p>
          </>}
        </div>
        <div className="as-ctas">
          <button className="lh-btn lh-btn-ink" onClick={() => window.dispatchEvent(new CustomEvent("lastlift:ask"))}>{S.showcase.ask}</button>
          <a className="lh-btn" href={href("/approvals")}>{S.showcase.agents}</a>
          <a className="lh-btn lh-btn-ghost" href={href("/tour")}>{S.showcase.tour}</a>
        </div>
      </div>
    </section>
  );
}
