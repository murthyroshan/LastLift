import { useEffect, useRef, useState } from "react";
import { askLive, getQueries, getReplay, getReplayIndex, type Scope } from "../api";
import { useAnnounce } from "./Announcer";
import { S } from "../strings.en";

type Ev = Record<string, any>;

/** The agent's run, step by step: every tool call went through MCP; each step's Cypher is one click away. */
export function AgentDrawer({ live, scope, onClose }: { live: boolean; scope: Scope; onClose: () => void }) {
  const [index, setIndex] = useState<{ id: string; question: string }[]>([]);
  const [events, setEvents] = useState<Ev[]>([]);
  const [question, setQuestion] = useState("");
  const [running, setRunning] = useState(false);
  const [queries, setQueries] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<number | null>(null);
  const announce = useAnnounce();
  const timers = useRef<number[]>([]);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    heading.current?.focus();
    getReplayIndex().then(setIndex).catch(() => {});
    getQueries().then(setQueries).catch(() => {});
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("keydown", esc); timers.current.forEach(clearTimeout); };
  }, [onClose]);

  function finish(evs: Ev[]) {
    const a = evs.find((e) => e.type === "answer");
    if (a) announce(a.text);
    setRunning(false);
  }

  async function playRecorded(id: string) {
    timers.current.forEach(clearTimeout);
    setOpen(null); setRunning(true);
    const rec = await getReplay(id);
    setQuestion(rec.question);
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) { setEvents(rec.events); finish(rec.events); return; }
    setEvents([]);
    rec.events.forEach((e: Ev, i: number) => {
      timers.current.push(window.setTimeout(() => {
        setEvents((prev) => [...prev, e]);
        if (i === rec.events.length - 1) finish(rec.events);
      }, i * 350));
    });
  }

  function ask() {
    if (!question.trim() || !live) return;
    setEvents([]); setOpen(null); setRunning(true);
    const seen: Ev[] = [];
    askLive(question.trim(), (e) => {
      seen.push(e);
      setEvents([...seen]);
      if (e.type === "done") finish(seen);
    }, scope);
  }

  const results = events.filter((e) => e.type === "tool_result");
  const failovers = events.filter((e) => e.type === "error" && e.stage === "llm_failover");
  const answer = events.find((e) => e.type === "answer");
  return (
    <aside className="drawer" aria-labelledby="agent-h">
      <h2 id="agent-h" tabIndex={-1} ref={heading}>{S.agent.title}</h2>
      <p>{S.agent.intro}</p>
      <button onClick={onClose}>{S.agent.close}</button>

      <h3>{S.agent.recorded}</h3>
      <ul>
        {index.map((r) => (
          <li key={r.id}><button className="link" onClick={() => playRecorded(r.id)}>{r.question}</button></li>
        ))}
      </ul>

      <form onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <label htmlFor="q">{S.agent.ask}</label><br />
        <input id="q" type="text" value={question} placeholder={S.agent.placeholder}
               onChange={(e) => setQuestion(e.target.value)} disabled={!live} />{" "}
        <button className="primary" disabled={!live || running}>{S.agent.ask}</button>
        {!live && <p className="muted">{S.agent.liveOnly}</p>}
      </form>

      {running && <p aria-busy="true">{S.agent.running}</p>}
      {results.length > 0 && <>
        <h3>{S.agent.steps}</h3>
        <ol className="trace">
          {results.map((e, i) => (
            <li key={i}>
              <span className="tool">{e.tool}</span> <span className="chip">{S.agent.viaMcp}</span>
              <div>{e.summary}</div>
              {(e.queries?.length ?? 0) > 0 && (
                <button className="link" aria-expanded={open === i} onClick={() => setOpen(open === i ? null : i)}>
                  {S.agent.cypher}
                </button>
              )}
              {open === i && e.queries.map((q: string) => (
                <div key={q}><strong>{q}</strong>{queries[q] && <pre className="cypher">{queries[q]}</pre>}</div>
              ))}
            </li>
          ))}
        </ol>
      </>}
      {answer && <>
        <h3>{S.agent.answer}</h3>
        <p>{answer.text}</p>
        <p className="muted">{answer.source === "llm" ? S.agent.sourceLlm : S.agent.sourceTemplate}
          {answer.source === "llm" && answer.model ? ` (${answer.model})` : ""}</p>
        {failovers.length > 0 && <ul className="muted">
          {failovers.map((f, i) => <li key={i}>{S.agent.failover(f.from_model, f.to_model)}</li>)}
        </ul>}
        {events[0]?.trace_id && <p className="muted">{S.agent.trace(events[0].trace_id)}</p>}
      </>}
    </aside>
  );
}
