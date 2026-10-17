import { lazy, Suspense } from "react";
import type { Route } from "../../router";

const Station3DLab = lazy(() => import("./Station3DLab").then((m) => ({ default: m.Station3DLab })));
const IntroLab = lazy(() => import("../../components/three/CityIntro").then((m) => ({ default: m.CityIntro })));
const FilmStage = lazy(() => import("../../components/three/city/Film").then((m) => ({ default: m.FilmStage })));

/** Development views for the 3D pieces: #/lab/station3d, #/lab/intro and #/lab/film (the offline film set). */
export function Lab({ route }: { route: Route }) {
  const which = route.parts[1];
  const q = route.query;
  return (
    <Suspense fallback={<p aria-busy="true">…</p>}>
      {which === "intro" ? <IntroLab />
        : which === "film" ? <FilmStage w={Number(q.get("w") ?? 1920)} h={Number(q.get("h") ?? 1080)} dark={q.get("dark") === "1"} />
        : <Station3DLab route={route} />}
    </Suspense>
  );
}
