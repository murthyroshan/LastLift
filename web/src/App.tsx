import { useCallback, useEffect, useState } from "react";
import { getDisclaimers, getLiveStatus, pingLive, type LiveStatus, type Scope } from "./api";
import { AgentDrawer } from "./components/AgentDrawer";
import { AnnouncerProvider } from "./components/Announcer";
import { isPresent, Present } from "./components/Present";
import { EyesFree, isEyesFree } from "./components/EyesFree";
import { About } from "./pages/About";
import { Landing } from "./pages/Landing";
import { Network } from "./pages/Network";
import { Approvals } from "./pages/Approvals";
import { Repairs } from "./pages/Repairs";
import { Station } from "./pages/Station";
import { Lab } from "./pages/lab/Lab";
import { Console } from "./pages/Console";
import { CommandPalette } from "./components/CommandPalette";
import { I } from "./components/icons";
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
  const cinematic = page === "";
  const [palette, setPalette] = useState(false);
  const nav: [string, string, string, keyof typeof I][] = [
    ["/", S.nav.home, "", "story"], ["/console", S.nav.console, "console", "command"], ["/network", S.nav.network, "network", "network"],
    ["/repairs", S.nav.repairs, "repairs", "repairs"], ["/approvals", S.nav.ops, "approvals", "ops"], ["/about", S.nav.about, "about", "about"]];
  const actions = [
    { id: "ask", label: S.nav.ask, run: () => setDrawer(true) },
    { id: "eyes", label: S.eyes.toggle, run: () => setEyes((v) => !v) },
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
      <div className={`shell ${cinematic ? "shell-cinematic" : "shell-console"}`}>
        <header className="site">
          <a className="brand" href={href("/")}>
            <svg className="brand-mark" viewBox="0 0 28 28" aria-hidden="true" focusable="false">
              <rect className="cab" x="3" y="2" width="22" height="24" rx="5" />
              <path className="arrow" d="M14 6.5l4.5 5h-9z M14 21.5l-4.5-5h9z" />
            </svg>
            <span>{S.appName}</span>
          </a>
          <button className="search-trigger" onClick={() => setPalette(true)} aria-haspopup="dialog" aria-label={S.shell.searchLabel}>
            <I.search /> <span>{S.shell.search}</span> <kbd>Ctrl K</kbd>
          </button>
          <nav className="site" aria-label="Main">
            {nav.map(([p, label, key, icon]) => {
              const Icon = I[icon];
              return <a key={p} href={href(p)} aria-current={page === key ? "page" : undefined}><Icon /><span>{label}</span></a>;
            })}
          </nav>
          <div className="nav-tools">
            <button className="link" aria-expanded={drawer} onClick={() => setDrawer(true)}><I.agent /><span>{S.nav.ask}</span></button>
            <button className="link" aria-pressed={eyes} onClick={() => setEyes(!eyes)}><I.ear /><span>{S.eyes.toggle}</span></button>
            <button className="link" aria-pressed={scope === "live"} disabled={wake !== "live"}
                    title={wake === "live" ? undefined : S.live.needsServer} onClick={() => setWantLive(!wantLive)}>
              <span className="live-dot" aria-hidden="true" /><span>{S.live.toggle}</span>
            </button>
          </div>
          <div className="status-strip">
            <div className="banner" data-state={wake} role="status">{S.wake[wake]}</div>
            <div className="banner" data-state={scope === "live" ? (status?.stale ? "waking" : "live") : "demo"} role="status">{liveText}</div>
          </div>
        </header>
        <div className="shell-main">
          <main id="main" tabIndex={-1}>
            {page === "station" ? <Station key={scope} route={route} live={wake === "live"} scope={scope} />
              : page === "console" ? <Console key={scope} scope={scope} />
              : page === "repairs" ? <Repairs key={scope} scope={scope} live={wake === "live"} />
              : page === "network" || page === "contingency" ? <Network key={scope} scope={scope} />
              : page === "approvals" ? <Approvals key={scope} scope={scope} live={wake === "live"} />
              : page === "about" ? <About />
              : page === "lab" ? <Lab route={route} />
              : <Landing key={scope} scope={scope} />}
          </main>
          <footer className="site"><p>{footer}</p></footer>
        </div>
      </div>
      <CommandPalette open={palette} setOpen={setPalette} actions={actions} />
      {drawer && <AgentDrawer live={wake === "live"} scope={scope} onClose={close} />}
      {eyes && <EyesFree live={wake === "live"} onClose={closeEyes} />}
      <p className="visually-hidden">{S.eyes.hint}</p>
    </AnnouncerProvider>
  );
}
