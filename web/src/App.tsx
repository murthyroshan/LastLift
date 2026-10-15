import { useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

type Health = { status: string; falkordb: { reachable: boolean; module_version: string | null } };

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [state, setState] = useState<"checking" | "live" | "unavailable">("checking");

  useEffect(() => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 5000);
    fetch(`${API_BASE}/v1/health`, { signal: ctrl.signal })
      .then((r) => r.json())
      .then((h: Health) => {
        setHealth(h);
        setState(h.falkordb.reachable ? "live" : "unavailable");
      })
      .catch(() => setState("unavailable"))
      .finally(() => clearTimeout(timer));
    return () => ctrl.abort();
  }, []);

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header>
        <h1>LastLift</h1>
        <p className="tagline">Find the last lift before it fails.</p>
      </header>
      <main id="main">
        <p role="status" aria-live="polite">
          {state === "checking" && "Connecting to the graph server…"}
          {state === "live" && `Graph server live (FalkorDB ${health?.falkordb.module_version}).`}
          {state === "unavailable" && "Graph server unavailable. Recorded results will be shown here."}
        </p>
      </main>
      <footer>
        <p>
          Unofficial decision support based on open data. Not affiliated with any transit agency. Results describe
          the open-data model and may differ from conditions on the ground.
        </p>
      </footer>
    </>
  );
}
