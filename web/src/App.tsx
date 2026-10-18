import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { getDisclaimers, getLiveStatus, pingLive, type LiveStatus, type Scope } from "./api";
import { AgentDrawer } from "./components/AgentDrawer";
import { AnnouncerProvider } from "./components/Announcer";
import { isPresent, Present } from "./components/Present";
import { EyesFree, isEyesFree } from "./components/EyesFree";
import { Landing } from "./pages/Landing";
// every other page loads when it is first visited, so the landing ships only what it needs
const About = lazy(() => import("./pages/About").then((m) => ({ default: m.About })));
const Tour = lazy(() => import("./pages/Tour").then((m) => ({ default: m.Tour })));
const Network = lazy(() => import("./pages/Network").then((m) => ({ default: m.Network })));
const Approvals = lazy(() => import("./pages/Approvals").then((m) => ({ default: m.Approvals })));
const Repairs = lazy(() => import("./pages/Repairs").then((m) => ({ default: m.Repairs })));
const Station = lazy(() => import("./pages/Station").then((m) => ({ default: m.Station })));
const Lab = lazy(() => import("./pages/lab/Lab").then((m) => ({ default: m.Lab })));
const Console = lazy(() => import("./pages/Console").then((m) => ({ default: m.Console })));
const AtlasPage = lazy(() => import("./pages/Atlas").then((m) => ({ default: m.AtlasPage })));
const Sandbox = lazy(() => import("./pages/Sandbox").then((m) => ({ default: m.Sandbox })));
const TimeMachine = lazy(() => import("./pages/TimeMachine").then((m) => ({ default: m.TimeMachine })));
import { CommandPalette } from "./components/CommandPalette";
import { I } from "./components/icons";
import { DisplayPanel } from "./components/DisplayPanel";
import { applyDisplay, loadDisplay, type Display } from "./lib/display";
import { lessMotion, startCursor, startSmoothScroll } from "./lib/motion";
import { href, useRoute } from "./router";
import { S } from "./strings.en";

type Wake = "checking" | "waking" | "live" | "offline";

/** Polls the live API while it wakes (the free host sleeps); the mirror keeps every screen usable meanwhile. */
function useWake(): Wake {
  const [wake, setWake] = useState<Wake>("checking");
  useEffect(() => {
    let tries = 0, stop = false;
    if (isPresent()) { setWake("offline"); return; }       // present mode: no live polling, the mirror only
    const tick = async () => {
      if (stop) return;
      if (await pingLive()) { setWake("live"); return; }
      tries += 1;
      setWake(tries >= 12 ? "offline" : "waking");
      if (tries < 12) window.setTimeout(tick, 5000);
    };
    tick();
    return () => { stop = true; };
  }, []);
  return wake;
}

/** The live feed's status while the Live scope is on, refreshed every minute. */
function useLiveStatus(on: boolean): LiveStatus | null {
  const [status, setStatus] = useState<LiveStatus | null>(null);
  useEffect(() => {
    if (!on) { setStatus(null); return; }
    let stop = false;
    const tick = () => getLiveStatus().then((s) => !stop && setStatus(s)).catch(() => {});
    tick();
    const id = window.setInterval(tick, 60000);
    return () => { stop = true; clearInterval(id); };
  }, [on]);
  return status;
}

export default function App() {
  const route = useRoute();
  const wake = useWake();
  const [wantLive, setWantLive] = useState(false);
  const scope: Scope = wantLive && wake === "live" ? "live" : "demo";
  const status = useLiveStatus(scope === "live");
  const [drawer, setDrawer] = useState(false);
  useEffect(() => {                                   // "Ask your own question" on the landing opens the chat dock
    const open = () => setDrawer(true);
    window.addEventListener("lastlift:ask", open);
    return () => window.removeEventListener("lastlift:ask", open);
  }, []);
  const [eyes, setEyes] = useState(isEyesFree());
  const closeEyes = useCallback(() => setEyes(false), []);
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.altKey && (e.key === "e" || e.key === "E")) { e.preventDefault(); setEyes((v) => !v); } };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  const [footer, setFooter] = useState("");
  const close = useCallback(() => setDrawer(false), []);
  useEffect(() => { getDisclaimers().then((d) => setFooter(d.footer)).catch(() => {}); }, []);

  const page = route.parts[0] ?? "";
  const [palette, setPalette] = useState(false);
  const [display, setDisplay] = useState<Display>(loadDisplay);
  const [displayOpen, setDisplayOpen] = useState(false);
  const [displayVersion, setDisplayVersion] = useState(0);
  const changeDisplay = (d: Display) => { applyDisplay(d, true); setDisplay(d); setDisplayVersion((v) => v + 1); };
  const closeDisplay = useCallback(() => {
    setDisplayOpen(false);
    document.querySelector<HTMLElement>(".display-trigger")?.focus();
  }, []);
  // five sections; the pages inside a section are tabs under the bar
  const sections: { key: string; path: string; label: string; pages: string[]; tabs?: [string, string][] }[] = [
    { key: "home", path: "/", label: S.nav.home, pages: [""] },
    { key: "command", path: "/console", label: S.nav.console, pages: ["console", "approvals"],
      tabs: [["/console", S.tabs.live], ["/approvals", S.tabs.agents]] },
    { key: "network", path: "/network", label: S.nav.network, pages: ["network", "contingency", "history", "station"],
      tabs: [["/network", S.tabs.network], ["/history", S.tabs.history]] },
    { key: "plan", path: "/repairs", label: S.nav.plan, pages: ["repairs", "sandbox"],
      tabs: [["/repairs", S.tabs.priorities], ["/sandbox", S.tabs.whatif]] },
    { key: "about", path: "/about", label: S.nav.about, pages: ["about", "atlas", "tour"],
      tabs: [["/about", S.tabs.how], ["/atlas", S.tabs.cities], ["/tour", S.tabs.tour]] },
  ];
  const current = sections.find((s) => s.pages.includes(page));

  // the landing's motion language on every page: smooth scrolling and the cursor ring
  useEffect(() => {
    if (!lessMotion() && !navigator.webdriver) document.documentElement.classList.add("anim-on");
    const stops = [startSmoothScroll(), startCursor()];
    return () => stops.forEach((s) => s());
  }, []);
  // panels rise in as they scroll into view (not under reduced motion, and not for automated test browsers)
  useEffect(() => {
    if (lessMotion() || navigator.webdriver || page === "") return;
    document.documentElement.classList.add("reveal-on");
    const io = new IntersectionObserver((es) => es.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
    }), { threshold: 0.08 });
    const t = window.setTimeout(() => {
      document.querySelectorAll("#main .card, #main .tiles, #main section, #main .table-wrap").forEach((el) => {
        if (el.closest(".landing, .console") || el.classList.contains("rv")) return;
        el.classList.add("rv");
        const r = el.getBoundingClientRect();
        if (r.top < window.innerHeight) el.classList.add("in"); else io.observe(el);
      });
    }, 60);
    return () => { clearTimeout(t); io.disconnect(); };
  }, [route.path, page]);
  const actions = [
    { id: "ask", label: S.nav.ask, run: () => setDrawer(true) },
    { id: "eyes", label: S.eyes.toggle, run: () => setEyes((v) => !v) },
    { id: "display", label: S.display.button, run: () => setDisplayOpen(true) },
    ...(wake === "live" ? [{ id: "live", label: S.live.toggle, run: () => setWantLive((v) => !v) }] : []),
  ];
  const liveText = scope === "demo" ? S.live.demo
    : !status ? S.live.loading
    : status.source === "harvest" ? S.live.harvest
    : S.live.polled(Math.floor((status.age_s ?? 0) / 60), status.alerts ?? 0, status.closed.length, status.stale);
  return (
    <AnnouncerProvider>
      <a className="skip" href="#main">{S.skip}</a>
      {isPresent() && <Present />}
      <div className="shell shell-top">
        <header className="site">
          <div className="topbar">
            <a className="brand" href={href("/")}>
              <svg className="brand-mark" viewBox="0 0 28 28" aria-hidden="true" focusable="false">
                <rect className="cab" x="3" y="2" width="22" height="24" rx="5" />
                <path className="arrow" d="M14 6.5l4.5 5h-9z M14 21.5l-4.5-5h9z" />
              </svg>
              <span>{S.appName}</span>
            </a>
            <nav className="site" aria-label="Main">
              {sections.map((s) => (
                <a key={s.key} href={href(s.path)} aria-current={current?.key === s.key ? "page" : undefined}>{s.label}</a>
              ))}
            </nav>
            <div className="topbar-tools">
              <button className="search-trigger" onClick={() => setPalette(true)} aria-haspopup="dialog" aria-label={S.shell.searchLabel}>
                <I.search /> <span>{S.shell.search}</span> <kbd>Ctrl K</kbd>
              </button>
              <button className="link display-trigger" aria-expanded={displayOpen} onClick={() => setDisplayOpen(!displayOpen)}>
                <I.about /><span>{S.display.button}</span></button>
            </div>
          </div>
          <div className="status-strip">
            <div className="banner" data-state={wake} role="status">{S.wake[wake]}</div>
            <div className="banner" data-state={scope === "live" ? (status?.stale ? "waking" : "live") : "demo"} role="status">{liveText}</div>
            <button className="link live-toggle" aria-pressed={scope === "live"} disabled={wake !== "live"}
                    title={wake === "live" ? undefined : S.live.needsServer} onClick={() => setWantLive(!wantLive)}>
              <span className="live-dot" aria-hidden="true" />{S.live.toggle}
            </button>
          </div>
        </header>
        {current?.tabs && (
          <nav className="section-tabs" aria-label={S.tabs.label(current.label)}>
            {current.tabs.map(([p, label]) => (
              <a key={p} href={href(p)} aria-current={`/${page}` === p ? "page" : undefined}>{label}</a>
            ))}
          </nav>
        )}
        <div className="shell-main">
          <main id="main" tabIndex={-1} key={displayVersion} data-page={page || "home"} data-section={page && current ? current.label : undefined}>
            <Suspense fallback={<p className="page-loading" aria-busy="true">…</p>}>
            {page === "station" ? <Station key={scope} route={route} live={wake === "live"} scope={scope} />
              : page === "console" ? <Console key={scope} scope={scope} />
              : page === "repairs" ? <Repairs key={scope} scope={scope} live={wake === "live"} />
              : page === "network" || page === "contingency" ? <Network key={scope} scope={scope} />
              : page === "approvals" ? <Approvals key={scope} scope={scope} live={wake === "live"} />
              : page === "about" ? <About />
              : page === "tour" ? <Tour />
              : page === "atlas" ? <AtlasPage />
              : page === "history" ? <TimeMachine />
              : page === "sandbox" ? <Sandbox key={scope} route={route} live={wake === "live"} scope={scope} />
              : page === "lab" && import.meta.env.DEV ? <Lab route={route} />       // development views only, never shipped
              : <Landing key={scope} scope={scope} />}
            </Suspense>
          </main>
          <footer className="site"><p>{footer}</p></footer>
        </div>
      </div>
      {displayOpen && <DisplayPanel value={display} onChange={changeDisplay} onClose={closeDisplay}
                                    eyes={eyes} onEyes={(v) => setEyes(v)} />}
      <CommandPalette open={palette} setOpen={setPalette} actions={actions} />
      {drawer ? <AgentDrawer live={wake === "live"} scope={scope} onClose={close} />
        : <button className="chat-launch" aria-label={S.agent.launch} onClick={() => setDrawer(true)}><I.agent /></button>}
      {eyes && <EyesFree live={wake === "live"} onClose={closeEyes} />}
      <p className="visually-hidden">{S.eyes.hint}</p>
    </AnnouncerProvider>
  );
}
