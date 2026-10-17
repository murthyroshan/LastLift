import { useEffect, useRef, useState } from "react";
import { lessMotion, scrollToY, scrollVelocity } from "../lib/motion";
import { S } from "../strings.en";

const BASE = import.meta.env.BASE_URL;
type Manifest = { n: number; fps: number; w: number; h: number; sizes: Record<string, number>; v?: string };
// where each caption is on screen, as scroll progress: the title over the amber shaft, the count while the camera
// arcs round, "one lift goes out" as the shaft turns red (about 60% in), the answer as it holds red
const BEATS = [[0, 0.18], [0.24, 0.46], [0.58, 0.78], [0.85, 1.01]];

/** Loads public/film/manifest.json; null while loading or when no film has been built. */
export function useFilm() {
  const [m, setM] = useState<Manifest | null | undefined>(undefined);
  useEffect(() => {
    fetch(`${BASE}film/manifest.json`, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).then((x) => setM(x?.n ? x : null)).catch(() => setM(null));
  }, []);
  return m;
}

/** The order frames load in: the first, then every 16th, 8th, 4th, 2nd, then the rest, so the whole film
 *  scrubs coarsely within a second and sharpens as the rest arrives. */
function loadOrder(n: number) {
  const seen = new Set<number>([0]), order = [0];
  for (const step of [16, 8, 4, 2, 1]) for (let i = 0; i < n; i += step) if (!seen.has(i)) { seen.add(i); order.push(i); }
  if (!seen.has(n - 1)) order.push(n - 1);
  return order;
}

/** A WebGL layer that shows the film and, while the page is moving fast, bends it in soft waves and splits its
 *  colour channels, settling back to a clean frame as the scroll slows. Null where WebGL is unavailable. */
function liquid(view: HTMLCanvasElement) {
  const gl = view.getContext("webgl", { antialias: false, premultipliedAlpha: false, preserveDrawingBuffer: false });
  if (!gl) return null;
  const sh = (type: number, src: string) => { const x = gl.createShader(type)!; gl.shaderSource(x, src); gl.compileShader(x); return x; };
  const prog = gl.createProgram()!;
  gl.attachShader(prog, sh(gl.VERTEX_SHADER, "attribute vec2 p; varying vec2 uv; void main(){ uv = vec2(p.x, -p.y) * 0.5 + 0.5; gl_Position = vec4(p, 0.0, 1.0); }"));
  gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, `precision mediump float; varying vec2 uv; uniform sampler2D t; uniform float v; uniform float time;
    void main(){
      float a = abs(v);
      vec2 q = uv;
      q.y += sin(q.x * 10.0 + time * 2.2) * 0.010 * a;
      q.x += sin(q.y * 7.0 + time * 1.7) * 0.007 * a;
      float k = 0.006 * v;
      gl_FragColor = vec4(texture2D(t, q + vec2(k, 0.0)).r, texture2D(t, q).g, texture2D(t, q - vec2(k, 0.0)).b, 1.0);
    }`));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return null;
  gl.useProgram(prog);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, "p");
  gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
  for (const [k, val] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]])
    gl.texParameteri(gl.TEXTURE_2D, k, val);
  const uv = gl.getUniformLocation(prog, "v"), ut = gl.getUniformLocation(prog, "time");
  return (src: HTMLCanvasElement, fresh: boolean, v: number, time: number) => {
    if (view.width !== src.width || view.height !== src.height) { view.width = src.width; view.height = src.height; fresh = true; }
    gl.viewport(0, 0, view.width, view.height);
    if (fresh) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
    gl.uniform1f(uv, v); gl.uniform1f(ut, time);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  };
}

/** Text that rises in letter by letter as its caption's --v goes from 0 to 1; read whole by assistive technology. */
function Chars({ text }: { text: string }) {
  let i = 0;
  return (
    <>
      <span className="visually-hidden">{text}</span>
      <span className="ch" aria-hidden="true">
        {text.split(" ").map((w, k) => (
          <span key={k}>{k > 0 && " "}<span className="ch-w">{[...w].map((c) => <span key={i} className="ch-c" style={{ ["--i" as any]: i++ }}>{c}</span>)}</span></span>
        ))}
      </span>
    </>
  );
}

/** The landing film: a sticky full-screen canvas scrubbed frame by frame by the scroll, four captions that rise in
 *  letter by letter, a slight tilt with the pointer, and a chapter bar. A loader counts the first frames in.
 *  Under reduced motion it is one still and the captions. */
export function FilmHero({ film, claims, onTry }: { film: Manifest; claims: Record<string, any> | null; onTry: () => void }) {
  const box = useRef<HTMLElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [p, setP] = useState(0);
  const [loaded, setLoaded] = useState(0);              // share of the first, coarse pass that has arrived
  const [still] = useState(lessMotion);

  useEffect(() => {
    // frames are composed on a 2D canvas; where WebGL is available it is shown through the liquid layer
    const view = canvas.current!;
    const show = still ? null : liquid(view);
    const cv = show ? document.createElement("canvas") : view, g = cv.getContext("2d")!;
    let fresh = false, vel = 0, shownV = 0;
    const size = window.innerWidth * Math.min(2, window.devicePixelRatio || 1) > 1100 ? "lg" : "sm";
    const imgs: (HTMLImageElement | null)[] = Array(film.n).fill(null);
    let cur = still ? film.n - 1 : 0, want = Math.round(cur), shown = -1, raf = 0, alive = true;

    const draw = (i: number) => {
      let k = -1;                                           // the nearest frame that has arrived
      for (let d = 0; d < film.n && k < 0; d++) k = imgs[i - d] ? i - d : imgs[i + d] ? i + d : -1;
      const img = k >= 0 ? imgs[k] : null; if (!img) return;
      const W = view.clientWidth, H = view.clientHeight, dpr = Math.min(1.25, window.devicePixelRatio || 1);   // the frames are 1280 wide: more pixels add nothing
      if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
      // fit the height, so the whole object shows
      const s = Math.max(cv.height / img.naturalHeight, Math.min(cv.width / img.naturalWidth, (cv.height / img.naturalHeight) * 1.04));
      const w = img.naturalWidth * s, h = img.naturalHeight * s, x = (cv.width - w) / 2, y = (cv.height - h) / 2;
      g.drawImage(img, x, y, w, h);
      if (x > 0) {      // wide screens: stretch the film's own outer pixels across the margins, so the backdrop runs on seamlessly
        const iw = img.naturalWidth, ih = img.naturalHeight, e = 6;
        g.drawImage(img, 0, 0, e, ih, 0, y, x + 1, h);
        g.drawImage(img, iw - e, 0, e, ih, x + w - 1, y, x + 1, h);
      }
      shown = k; fresh = true;
    };

    const order = still ? [film.n - 1] : loadOrder(film.n);
    const coarse = still ? 1 : Math.min(order.length, Math.ceil(film.n / 8) + 1);   // the loader waits for every 8th frame
    let next = 0, done = 0;
    const pump = () => {
      if (!alive || next >= order.length) return;
      const at = next, i = order[next++], img = new Image();
      img.decoding = "async";
      img.src = `${BASE}film/${size}/f${String(i).padStart(3, "0")}.webp${film.v ? `?v=${film.v}` : ""}`;   // a new film never reuses cached frames
      img.decode().then(() => { imgs[i] = img; if (shown < 0 || Math.abs(i - want) < Math.abs(shown - want)) draw(want); })
        .catch(() => {}).finally(() => { if (at < coarse) setLoaded(++done / coarse); pump(); });
    };
    for (let c = 0; c < 6; c++) pump();

    // the site's bar floats over the film (fixed) here; if it does not, the stage starts below it
    document.body.classList.add("has-film");
    const header = document.querySelector<HTMLElement>("header.site");
    const bar = () => (header && getComputedStyle(header).position !== "fixed" ? header.getBoundingClientRect().height : 0);
    box.current!.style.setProperty("--bar", `${bar()}px`);
    const progress = () => {
      const r = box.current!.getBoundingClientRect(), top = bar(), span = r.height - (window.innerHeight - top);
      return span > 0 ? Math.min(1, Math.max(0, (top - r.top) / span)) : 1;
    };
    let tx = 0, ty = 0, mx = 0, my = 0;
    const onPointer = (e: PointerEvent) => { tx = (e.clientX / window.innerWidth) * 2 - 1; ty = (e.clientY / window.innerHeight) * 2 - 1; };
    const tick = () => {                                     // ease toward the scroll position, so scrubbing glides
      const q = progress(), target = q * (film.n - 1);
      cur += (target - cur) * 0.2;
      if (Math.abs(target - cur) < 0.05) cur = target;
      const i = Math.round(cur);
      if (i !== want) { want = i; draw(i); }
      vel += (Math.max(-1, Math.min(1, scrollVelocity() / 45)) - vel) * 0.12;
      if (show && (fresh || Math.abs(vel) > 0.004 || Math.abs(shownV) > 0.004)) {
        show(cv, fresh, vel, performance.now() / 1000); fresh = false; shownV = vel;
      }
      mx += (tx - mx) * 0.05; my += (ty - my) * 0.05;
      stage.current?.style.setProperty("--mx", mx.toFixed(4));
      stage.current?.style.setProperty("--my", my.toFixed(4));
      header?.toggleAttribute("data-solid", q > 0.93 || box.current!.getBoundingClientRect().bottom < 80);   // solid once the film starts fading into the page
      setP((old) => (Math.abs(old - q) > 0.002 ? q : old));
      raf = requestAnimationFrame(tick);
    };
    if (!still) { raf = requestAnimationFrame(tick); window.addEventListener("pointermove", onPointer); }
    const onResize = () => { box.current?.style.setProperty("--bar", `${bar()}px`); draw(want); };
    window.addEventListener("resize", onResize);
    return () => {
      alive = false; cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize); window.removeEventListener("pointermove", onPointer);
      document.body.classList.remove("has-film"); header?.removeAttribute("data-solid");
    };
  }, [film, still]);

  const jump = (k: number) => {
    const el = box.current!, top = parseFloat(el.style.getPropertyValue("--bar")) || 0, span = el.offsetHeight - (window.innerHeight - top);
    const at = (BEATS[k][0] + BEATS[k][1]) / 2;
    scrollToY(el.getBoundingClientRect().top + window.scrollY - top + span * Math.min(0.995, k === 0 ? 0 : at));
  };
  const vis = (k: number) => {
    if (still) return 1;
    const [a, b] = BEATS[k], f = 0.05;
    return Math.max(0, Math.min(1, (p - a + f) / f, (b - p) / f));
  };
  const active = BEATS.findIndex(([a, b]) => p >= a - 0.03 && p <= b);
  const ready = still || loaded >= 1;

  return (
    <section ref={box} className={`fh ${still ? "fh-still" : ""} ${ready ? "fh-ready" : ""}`} aria-labelledby="hero-h" aria-busy={!ready}>
      {!still && (
        <div className="fh-loader" aria-hidden="true">
          <span className="fh-load-n">{Math.round(loaded * 100)}</span>
          <span className="fh-load-bar"><span style={{ transform: `scaleX(${loaded})` }} /></span>
          <span className="fh-load-l">{S.appName}</span>
        </div>
      )}
      <div className="fh-stage" ref={stage}>
        <canvas ref={canvas} className="fh-canvas" aria-hidden="true" />
        <div className="fh-veil" aria-hidden="true" />

        <div className="fh-beat" style={{ ["--v" as any]: ready ? vis(0) : 0 }}>
          <div className="fh-left">
            <p className="fh-kicker">{S.home.eyebrow}</p>
            <h1 id="hero-h" className="fh-title"><Chars text={S.landing.t1} /> <em><Chars text={S.landing.t2} /></em></h1>
          </div>
          <div className="fh-right">
            <p className="fh-p">{S.landing.t3}</p>
            <p className="fh-cue" aria-hidden="true"><span />{S.film.scroll}</p>
          </div>
        </div>

        <div className="fh-beat" style={{ ["--v" as any]: vis(1) }}>
          <div className="fh-left">
            {claims && <p className="fh-count">
              <span className="fh-big">{claims.platforms_single_lift}</span>
              <span className="fh-of">/{claims.platforms_step_free}</span>
            </p>}
          </div>
          <div className="fh-right"><p className="fh-p">{S.home.countText}</p></div>
        </div>

        <div className="fh-beat" style={{ ["--v" as any]: vis(2) }}>
          <div className="fh-left"><h2 className="fh-h"><Chars text={S.film.b1} /></h2></div>
          <div className="fh-right"><p className="fh-p">{S.film.b1p}</p></div>
        </div>

        <div className="fh-beat" style={{ ["--v" as any]: vis(3) }}>
          <div className="fh-left"><h2 className="fh-h"><Chars text={S.film.b3} /></h2></div>
          <div className="fh-right">
            <p className="fh-p">{S.film.b3p}</p>
            <div className="fh-ctas">
              <button className="lh-btn lh-btn-ink" onClick={onTry}>{S.film.try}<span aria-hidden="true">↓</span></button>
              <a className="lh-btn fh-btn-glass" href={`${BASE}concepts/world.html`}>{S.hero.walk}</a>
            </div>
          </div>
        </div>
        <div className="fh-out" aria-hidden="true" style={{ opacity: still ? 0 : Math.max(0, (p - 0.94) / 0.06) }} />

        {!still && (
          <nav className="fh-rail" aria-label={S.film.chapters} style={{ opacity: Math.max(0, Math.min(1, (0.98 - p) / 0.04)) }}>
            {S.film.chapter.map((c, k) => (
              <button key={c} onClick={() => jump(k)} aria-current={active === k ? "step" : undefined}>
                <span className="fh-tick" aria-hidden="true" /><span className="fh-chap">{c}</span>
              </button>
            ))}
            <span className="fh-fill" aria-hidden="true" style={{ transform: `scaleX(${p})` }} />
          </nav>
        )}
      </div>
    </section>
  );
}
