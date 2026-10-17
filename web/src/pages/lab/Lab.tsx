import { lazy, Suspense } from "react";
import type { Route } from "../../router";

const Station3DLab = lazy(() => import("./Station3DLab").then((m) => ({ default: m.Station3DLab })));
const IntroLab = lazy(() => import("../../components/three/CityIntro").then((m) => ({ default: m.CityIntro })));

/** Development views for the 3D pieces: #/lab/station3d and #/lab/intro. */
export function Lab({ route }: { route: Route }) {
  const which = route.parts[1];
  return (
    <Suspense fallback={<p aria-busy="true">…</p>}>
      {which === "intro" ? <IntroLab /> : <Station3DLab route={route} />}
    </Suspense>
  );
}
