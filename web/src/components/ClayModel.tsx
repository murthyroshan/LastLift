import { useEffect, useRef } from "react";
import { S } from "../strings.en";

/** The clay station model (public/concepts/clay), framed so its own three.js build stays isolated from the app's.
 *  The app drives it by message: the selected platform and the lifts closed in a simulation. Decorative for
 *  assistive technology and out of the tab order: the platform and lift tables carry the same facts. */
export function ClayModel({ stationId, dir, selected, closed, height = "clamp(26rem, 62vh, 44rem)" }: {
  stationId: string; dir: "board" | "exit"; selected?: string | null; closed?: string[]; height?: string }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const ready = useRef(false);
  const send = (msg: object) => frame.current?.contentWindow?.postMessage(msg, window.location.origin);

  useEffect(() => { ready.current = false; }, [stationId, dir]);
  useEffect(() => { if (ready.current) send({ select: selected ?? null }); }, [selected]);
  useEffect(() => { if (ready.current) send({ closed: closed ?? [] }); }, [closed?.join(",")]);   // eslint-disable-line react-hooks/exhaustive-deps

  const src = `${import.meta.env.BASE_URL}concepts/clay/demo.html?id=${encodeURIComponent(stationId)}&dir=${dir}&embed=1`
    + (closed?.length ? `&close=${closed.join(",")}` : "") + (selected ? `&pick=${encodeURIComponent(selected)}` : "");
  return (
    <iframe ref={frame} className="clay-frame" src={src} title={S.station.modelTitle} aria-hidden="true" tabIndex={-1}
            style={{ height }} onLoad={() => { ready.current = true; }} />
  );
}
