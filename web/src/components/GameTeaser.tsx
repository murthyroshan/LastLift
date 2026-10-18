import { useEffect, useState } from "react";
import { S } from "../strings.en";

const BASE = import.meta.env.BASE_URL;

type Facts = { fid: string; hang: number; journeys: number };

/** The landing's way into the game: a still from the station as its lift fails, the two numbers behind it (from the
 *  mirror: the lift Alewife's platforms hang on, and the journeys its loss cuts), and Play / Watch it play. */
export function GameTeaser() {
  const [f, setF] = useState<Facts | null>(null);
  useEffect(() => {
    Promise.all([
      fetch(`${BASE}m/station/place-alfcl.json`).then((r) => r.json()),
      fetch(`${BASE}m/contingency.json`).then((r) => r.json()),
    ]).then(([st, ct]) => {
      const lift = (st?.graph?.exit?.nodes ?? []).find((n: any) => n.kind === "lift" && n.last_lift?.length);
      if (!lift) return;
      const link = (ct?.now?.data?.last_link ?? []).find((x: any) => x.facility_id === lift.facility_id);
      setF({ fid: lift.facility_id, hang: lift.last_lift.length, journeys: link?.journeys ?? 0 });
    }).catch(() => {});
  }, []);

  const game = `${BASE}concepts/alewife.html`;
  return (
    <div className="gt">
      <h2 className="lp-title gt-title">{S.teaser.title}</h2>
      <article className="gt-card">
        <img className="gt-img" src={`${BASE}game/poster-813.webp`} alt={f ? S.teaser.alt(f.fid) : ""} width={1342} height={565} loading="lazy" />
        <div className="gt-body">
          <p className="gt-kicker">{S.teaser.kicker}</p>
          {f && <p className="gt-head">{S.teaser.failed(f.fid)}</p>}
          <p className="gt-lead">{S.teaser.lead}</p>
          {f && <ul className="gt-facts">
            <li><b>{f.hang}</b> {S.teaser.hang}</li>
            {f.journeys > 0 && <li><b>{f.journeys}</b> {S.teaser.cut}</li>}
          </ul>}
          <div className="gt-ctas">
            <a className="lh-btn lh-btn-ink gt-play" href={game}><span aria-hidden="true">▶</span> {S.teaser.play}</a>
            <a className="lh-btn gt-watch" href={`${game}?autoplay`}>{S.teaser.watch}</a>
          </div>
        </div>
      </article>
    </div>
  );
}
