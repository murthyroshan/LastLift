import { useEffect, useState } from "react";
import { getClaims, getStations, type Scope } from "../api";
import { FilmHero, useFilm } from "../components/FilmHero";
import { LandingHero } from "../components/LandingHero";
import { LandingMore } from "../components/LandingMore";
import { scrollToY } from "../lib/motion";

/** The front door: the film, then the product (close a lift and watch what breaks), the numbers, how it works and
 *  where to go next. The station table and the count chart live on the Network page. */
export function Landing({ scope }: { scope: Scope }) {
  const [stations, setStations] = useState<Awaited<ReturnType<typeof getStations>>>([]);
  const [claims, setClaims] = useState<Record<string, any> | null>(null);
  const film = useFilm();

  useEffect(() => {
    getStations().then(setStations).catch(() => {});
    getClaims().then(setClaims).catch(() => {});
  }, [scope]);

  useEffect(() => {
    if ("scrollRestoration" in history) history.scrollRestoration = "manual";   // the film always starts at its first frame
    window.scrollTo(0, 0);
  }, []);

  const toProduct = () => {
    const el = document.getElementById("lh-product");
    if (el) scrollToY(el.getBoundingClientRect().top + window.scrollY - 40);
  };

  return (
    <div className="landing">
      {film && <FilmHero film={film} claims={claims} onTry={toProduct} />}
      {film !== undefined && <LandingHero claims={claims} stations={stations} film={!!film} />}
      {film !== undefined && <LandingMore />}
    </div>
  );
}
