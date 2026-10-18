import { useEffect, useRef, useState } from "react";
import { askLive, getAnswerStatus, getQueries, getReplay, getReplayIndex, type Scope } from "../api";
import { useAnnounce } from "./Announcer";
import { S } from "../strings.en";

type Ev = Record<string, any>;

/** Canonical JSON, identical to lastlift/agent/replay.py jscanon(): sorted keys, no spaces. */
const canon = (x: any): string => Array.isArray(x) ? `[${x.map(canon).join(",")}]`
  : x !== null && typeof x === "object"
    ? `{${Object.keys(x).sort().map((k) => `${JSON.stringify(k)}:${canon(x[k])}`).join(",")}}`
    : JSON.stringify(x);

async function verifyChain(rec: { events: Ev[]; chain?: string[]; head?: string }): Promise<number | true> {
  let h = "";
  for (let i = 0; i < rec.events.length; i++) {
    const bytes = new TextEncoder().encode(h + canon(rec.events[i]));
    const d = await crypto.subtle.digest("SHA-256", bytes);
    h = [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
    if (!rec.chain || rec.chain[i] !== h) return i + 1;
  }
  return h === rec.head ? true : rec.events.length;
}

/** The agent as a chat dock at the bottom right: one scrolling conversation, suggested (recorded) questions as chips,
 *  each answer carrying its steps (every tool call went through MCP, each step's Cypher one click away), the
 *  grounding check and the replay's hash-chain check. The message box stays pinned at the bottom. */
export function AgentDrawer({ live, scope, onClose }: { live: boolean; scope: Scope; onClose: () => void }) {
  const [index, setIndex] = useState<{ id: string; question: string }[]>([]);
  const [events, setEvents] = useState<Ev[]>([]);
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState("");
  const [running, setRunning] = useState(false);
  const [queries, setQueries] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<number | null>(null);
  const [rec, setRec] = useState<any>(null);
  const [verified, setVerified] = useState<string>("");
  const [status, setStatus] = useState<{ stale: boolean; reason: string; lifts: string[] } | null>(null);
  const announce = useAnnounce();
  const timers = useRef<number[]>([]);
  const heading = useRef<HTMLHeadingElement>(null);
  const body = useRef<HTMLDivElement>(null);

  useEffect(() => {
    heading.current?.focus();
    getReplayIndex().then(setIndex).catch(() => {});
    getQueries().then(setQueries).catch(() => {});
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("keydown", esc); timers.current.forEach(clearTimeout); };
  }, [onClose]);

  // keep the newest message in view as the run streams in
  useEffect(() => { const b = body.current; if (b && asked) b.scrollTop = b.scrollHeight; }, [events.length, running, asked]);

  function finish(evs: Ev[]) {
    const a = evs.find((e) => e.type === "answer");
    if (a) announce(a.text);
    setRunning(false);
  }

  async function playRecorded(id: string) {
    timers.current.forEach(clearTimeout);
    setOpen(null); setRunning(true);
    const rec = await getReplay(id);
    setRec(rec); setVerified("");
    setAsked(rec.question);
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

  function ask(text: string = question) {
    if (!text.trim() || !live) return;
    setEvents([]); setOpen(null); setRunning(true); setRec(null); setVerified("");
    setAsked(text.trim()); setQuestion("");
    const seen: Ev[] = [];
    askLive(text.trim(), (e) => {
      seen.push(e);
      setEvents([...seen]);
      if (e.type === "done") finish(seen);
    }, scope);
  }

  // a live answer is checked against the graph while the chat is open: it goes stale the moment a lift it read changes
  const liveTrace = !rec && !running && events.some((e) => e.type === "answer") ? events[0]?.trace_id : null;
  useEffect(() => {
    setStatus(null);
    if (!liveTrace) return;
    let alive = true;
    const check = () => getAnswerStatus(liveTrace, scope).then((s) => {
      if (alive && s.found) setStatus({ stale: !!s.stale, reason: s.stale_reason ?? "", lifts: s.lifts_read ?? [] });
    }).catch(() => {});
    check();
    const t = window.setInterval(check, 8000);
    return () => { alive = false; clearInterval(t); };
  }, [liveTrace, scope]);

  const results = events.filter((e) => e.type === "tool_result");
  const failovers = events.filter((e) => e.type === "error" && e.stage === "llm_failover");
  const claims: Ev[] = events.find((e) => e.type === "grounding")?.claims ?? [];
  const answer = events.find((e) => e.type === "answer");
  return (
    <aside className="chat" aria-labelledby="agent-h">
      <header className="chat-h">
        <span className="chat-dot" data-live={live} aria-hidden="true" />
        <h2 id="agent-h" tabIndex={-1} ref={heading}>{S.agent.title}</h2>
        <button className="chat-x" onClick={onClose} aria-label={S.agent.close}>✕</button>
      </header>

      <div className="chat-body" ref={body}>
        <p className="chat-intro">{S.agent.intro}</p>
        <p className="chat-label">{S.agent.recorded}</p>
        <ul className="chat-chips">
          {index.map((r) => (
            <li key={r.id}><button className="chat-chip" onClick={() => playRecorded(r.id)} disabled={running}>{r.question}</button></li>
          ))}
        </ul>

        {asked && <div className="msg me">{asked}</div>}

        {results.length > 0 && (
          <div className="msg steps">
            <p className="msg-label">{S.agent.steps}</p>
            <Waterfall events={events} />
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
          </div>
        )}

        {running && <p className="msg ai typing" aria-busy="true"><span className="visually-hidden">{S.agent.running}</span><i /><i /><i /></p>}

        {answer && (
          <div className="msg ai">
            <p className="msg-label">{S.agent.answer}</p>
            <p className="msg-text">{answer.text}</p>
            <p className="muted small">{answer.source === "llm" ? S.agent.sourceLlm : S.agent.sourceTemplate}
              {answer.source === "llm" && answer.model ? ` (${answer.model})` : ""}</p>
            {claims.length > 0 && <ul className="claims" aria-label={S.agent.claimsLabel}>
              {claims.map((c, i) => (
                <li key={i}>
                  {c.ok ? <span className="chip ok">✓ {S.agent.claimOk(c.cites.join(", "))}</span>
                    : <span className="chip">✕ {S.agent.claimReplaced}</span>}{" "}
                  {c.ok ? c.text : (c.replaced_by ?? "")}
                </li>
              ))}
            </ul>}
            {failovers.length > 0 && <ul className="muted small">
              {failovers.map((f, i) => <li key={i}>{S.agent.failover(f.from_model, f.to_model)}</li>)}
            </ul>}
            {status && <p className={`chat-fresh ${status.stale ? "stale" : ""}`} role="status">
              {status.stale ? S.agent.stale(status.reason) : S.agent.fresh(status.lifts.length > 1 ? S.agent.freshMany(status.lifts.length) : status.lifts.length ? S.agent.freshOne : S.agent.freshNone)}
              {status.stale && <> <button className="link" onClick={() => ask(asked)}>{S.agent.askAgain}</button></>}
            </p>}
            {events[0]?.trace_id && <p className="muted small">{S.agent.trace(events[0].trace_id)}</p>}
            {rec?.chain && !running && <p className="chat-verify">
              <button onClick={async () => {
                const r = await verifyChain(rec);
                const msg = r === true ? S.agent.chainOk(rec.events.length, rec.head.slice(0, 12)) : S.agent.chainBroken(r);
                setVerified(msg); announce(msg);
              }}>{S.agent.verify}</button>{" "}
              {verified && <span role="status">{verified}</span>}
            </p>}
          </div>
        )}
      </div>

      <form className="chat-compose" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        {!live && <p className="chat-hint">{S.agent.liveOnly}</p>}
        <label htmlFor="q" className="visually-hidden">{S.agent.ask}</label>
        <div className="chat-row">
          <input id="q" type="text" value={question} placeholder={S.agent.placeholder} autoComplete="off"
                 onChange={(e) => setQuestion(e.target.value)} disabled={!live} />
          <button className="primary chat-send" disabled={!live || running || !question.trim()}>{S.agent.ask}</button>
        </div>
      </form>
    </aside>
  );
}

/** The run as a timing waterfall: model thinking (grey) between tool calls (blue, one bar per MCP call, from its start
 *  to its result), then the grounding check and the answer. Decorative; the numbered steps below say the same. */
function Waterfall({ events }: { events: Ev[] }) {
  const end = Math.max(1, ...events.map((e) => Number(e.t_ms ?? 0)));
  const pct = (ms: number) => `${Math.max(0, Math.min(100, (100 * ms) / end))}%`;
  const rows = events.filter((e) => e.type === "tool_result").map((e) => {
    const stop = Number(e.t_ms ?? 0), dur = Number(e.ms ?? 0);
    return { tool: e.tool as string, start: stop - dur, dur, ok: e.ok !== false && e.ok !== "False" };
  });
  const ground = events.find((e) => e.type === "grounding");
  const answer = events.find((e) => e.type === "answer");
  return (
    <figure className="waterfall" aria-hidden="true">
      <div className="wf-axis"><span>{S.agent.wfStart}</span><span>{(end / 1000).toFixed(1)} s</span></div>
      <div className="wf-row wf-think"><span className="wf-l">{S.agent.wfModel}</span>
        <span className="wf-track"><i className="wf-bar think" style={{ left: 0, width: "100%" }} /></span></div>
      {rows.map((r, i) => (
        <div className="wf-row" key={i} style={{ animationDelay: `${i * 90}ms` }}>
          <span className="wf-l mono">{r.tool}</span>
          <span className="wf-track"><i className={`wf-bar ${r.ok ? "tool" : "fail"}`} style={{ left: pct(r.start), width: pct(Math.max(r.dur, end * 0.012)) }} />
            <span className="wf-ms" style={{ left: `calc(${pct(r.start + r.dur)} + 6px)` }}>{Math.round(r.dur)} ms</span></span>
        </div>
      ))}
      {ground && <div className="wf-row"><span className="wf-l">{S.agent.wfGround}</span>
        <span className="wf-track"><i className="wf-dot ground" style={{ left: pct(Number(ground.t_ms)) }} /></span></div>}
      {answer && <div className="wf-row"><span className="wf-l">{S.agent.wfAnswer}</span>
        <span className="wf-track"><i className="wf-dot answer" style={{ left: pct(Number(answer.t_ms ?? end)) }} /></span></div>}
    </figure>
  );
}
