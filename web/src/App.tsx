import { useCallback, useEffect, useState } from "react";
import { getDisclaimers, pingLive } from "./api";
import { AgentDrawer } from "./components/AgentDrawer";
import { AnnouncerProvider } from "./components/Announcer";
import { About } from "./pages/About";
import { Landing } from "./pages/Landing";
import { Repairs } from "./pages/Repairs";
import { Station } from "./pages/Station";
import { href, useRoute } from "./router";
import { S } from "./strings.en";

type Wake = "checking" | "waking" | "live" | "offline";

/** Polls the live API while it wakes (the free host sleeps); the mirror keeps every screen usable meanwhile. */
function useWake(): Wake {
  const [wake, setWake] = useState<Wake>("checking");
  useEffect(() => {
    let tries = 0, stop = false;
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

export default function App() {
  const route = useRoute();
  const wake = useWake();
  const [drawer, setDrawer] = useState(false);
  const [footer, setFooter] = useState("");
  const close = useCallback(() => setDrawer(false), []);
  useEffect(() => { getDisclaimers().then((d) => setFooter(d.footer)).catch(() => {}); }, []);

  const page = route.parts[0] ?? "";
  const nav = [["/", S.nav.home, ""], ["/repairs", S.nav.repairs, "repairs"], ["/about", S.nav.about, "about"]];
  return (
    <AnnouncerProvider>
      <a className="skip" href="#main">{S.skip}</a>
      <header className="site">
        <a className="brand" href={href("/")}>{S.appName}</a>
        <span className="tag">{S.tagline}</span>
        <nav className="site" aria-label="Main">
          {nav.map(([p, label, key]) => (
            <a key={p} href={href(p)} aria-current={page === key ? "page" : undefined}>{label}</a>
          ))}
          <button className="link" aria-expanded={drawer} onClick={() => setDrawer(true)}>{S.nav.ask}</button>
        </nav>
      </header>
      <div className="banner" data-state={wake} role="status">{S.wake[wake]}</div>
      <main id="main" tabIndex={-1}>
        {page === "station" ? <Station route={route} live={wake === "live"} />
          : page === "repairs" ? <Repairs />
          : page === "about" ? <About />
          : <Landing />}
      </main>
      {drawer && <AgentDrawer live={wake === "live"} onClose={close} />}
      <footer className="site"><p>{footer}</p></footer>
    </AnnouncerProvider>
  );
}
