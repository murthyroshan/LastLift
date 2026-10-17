import { useEffect, useState } from "react";

export type Route = { path: string; parts: string[]; query: URLSearchParams };

function parse(): Route {
  const raw = window.location.hash.replace(/^#/, "") || "/";
  const [path, q = ""] = raw.split("?");
  return { path, parts: path.split("/").filter(Boolean), query: new URLSearchParams(q) };
}

/** Hash routing: works on any static host and keeps deep links shareable (#/station/place-alfcl?dir=exit). */
export function useRoute(): Route {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => {
      setRoute(parse());
      document.getElementById("main")?.focus();       // move focus to the new page for keyboard users
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export const href = (path: string, query?: Record<string, string>) =>
  `#${path}${query && Object.keys(query).length ? `?${new URLSearchParams(query)}` : ""}`;
