import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

const Ctx = createContext<(msg: string) => void>(() => {});

/** One polite live region for the whole app: simulations and agent answers are announced once, not chattered. */
export function AnnouncerProvider({ children }: { children: ReactNode }) {
  const [msg, setMsg] = useState("");
  const announce = useCallback((m: string) => {
    setMsg("");
    window.setTimeout(() => setMsg(m), 50);       // re-announce identical messages
  }, []);
  return (
    <Ctx.Provider value={announce}>
      {children}
      <div className="visually-hidden" role="status" aria-live="polite">{msg}</div>
    </Ctx.Provider>
  );
}

export const useAnnounce = () => useContext(Ctx);
