import { useEffect, useState } from "react";
import { getClaims, getFiled, type Filed } from "../api";
import { href } from "../router";
import { S } from "../strings.en";

const BASE = import.meta.env.BASE_URL;

/** For judges: the whole project in a few minutes, as numbered stops, each one a link to the real thing. */
export function Tour() {
  const [claims, setClaims] = useState<Record<string, any> | null>(null);
  const [filed, setFiled] = useState<Filed | null>(null);
  useEffect(() => {
    getClaims().then(setClaims).catch(() => {});
    getFiled().then(setFiled).catch(() => {});
  }, []);
  const ask = () => window.dispatchEvent(new CustomEvent("lastlift:ask"));
  const first = filed?.issues[0];
  const stops: { t: string; d: string; go: string; href?: string; onClick?: () => void; ext?: boolean }[] = [
    { t: S.tour.s1t, d: claims ? S.tour.s1(claims.platforms_single_lift, claims.platforms_step_free) : "", go: S.tour.s1go, href: href("/") },
    { t: S.tour.s2t, d: S.tour.s2, go: S.tour.s2go, onClick: ask },
    { t: S.tour.s3t, d: S.tour.s3, go: S.tour.s3go, href: href("/station/place-alfcl") },
    { t: S.tour.s4t, d: S.tour.s4, go: S.tour.s4go, href: href("/approvals") },
    { t: S.tour.s5t, d: first ? S.tour.s5(first.number) : S.tour.s5none, go: S.tour.s5go, href: first?.url ?? filed?.issues_url, ext: true },
    { t: S.tour.s6t, d: S.tour.s6, go: S.tour.s6go, href: href("/about") },
    { t: S.tour.s7t, d: S.tour.s7, go: S.tour.s7go, href: `${BASE}concepts/alewife.html?autoplay` },
  ];
  return (
    <article className="tour">
      <p className="eyebrow">{S.tour.eyebrow}</p>
      <h1>{S.tour.title}</h1>
      <p className="lead">{S.tour.lead}</p>
      <ol className="tour-stops">
        {stops.map((s, i) => (
          <li key={i} className="tour-stop">
            <div className="tour-body"><h2>{s.t}</h2><p>{s.d}</p></div>
            {s.onClick
              ? <button className="lh-btn lh-btn-ink tour-go" onClick={s.onClick}>{s.go}</button>
              : <a className="lh-btn lh-btn-ink tour-go" href={s.href} {...(s.ext ? { target: "_blank", rel: "noreferrer" } : {})}>{s.go}</a>}
          </li>
        ))}
      </ol>
      <p className="muted">{S.tour.foot}</p>
    </article>
  );
}
