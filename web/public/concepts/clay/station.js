// LastLift station model: a data-driven architectural model of any station's step-free graph.
//
//   import { mount } from "/concepts/clay/station.js";
//   const api = await mount(document.querySelector("#box"), "place-dwnxg", { dir: "exit" });
//   api.select("70078"); api.toggle("891"); api.explode(1); api.dispose();
//
// Floors come from how many lifts the shortest step-free path from the street must ride (floor 0 is street level).
// Every lift is a glass shaft between the floors it joins, with a cabin inside. Routes are an exact max-flow in the
// browser (each lift carries one route), so closing a lift re-routes honestly and "last lift" follows the graph.
//
// Needs an import map for "three", "three/addons/", "three/examples/jsm/", "postprocessing" and "n8ao".
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { RGBELoader } from "three/addons/loaders/RGBELoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { EffectComposer, RenderPass, EffectPass, SelectiveBloomEffect, DepthOfFieldEffect, ToneMappingEffect, ToneMappingMode, BlendFunction } from "postprocessing";
import { N8AOPostPass } from "n8ao";

export const TOKENS = {
  bg: "#F5F3EE", ground: "#EDEAE3", ink: "#16181D", muted: "#6B6F76",
  clay: "#FAF8F4", sand: "#E7E1D6", stone: "#CFC8BB",
  last: "#F5A524", closed: "#E5484D", route: "#3E7BFA", working: "#2FB5A0",
};
const ASSETS = "/concepts/assets";
const col = (h) => new THREE.Color(h);
const liftId = (n) => n.kind === "lift";

/* ================================================================= graph maths */
function floorsOf(graph) {
  const adj = new Map(graph.nodes.map((n) => [n.id, []]));
  for (const e of graph.edges) {
    if (!e.step_free) continue;
    const w = e.kind === "lift" ? 0.5 : 0;
    adj.get(e.source)?.push([e.target, w]); adj.get(e.target)?.push([e.source, w]);
  }
  const dist = new Map();
  for (const n of graph.nodes) if (n.kind === "street") dist.set(n.id, 0);
  const done = new Set();
  for (;;) {
    let u = null, du = Infinity;
    for (const [id, d] of dist) if (!done.has(id) && d < du) { u = id; du = d; }
    if (u === null) break;
    done.add(u);
    for (const [v, w] of adj.get(u) ?? []) if (!dist.has(v) || du + w < dist.get(v)) dist.set(v, du + w);
  }
  return dist;
}

/** Max-flow from sources to sinks, every open lift carrying one route: k and the routes (node ids). */
export function routes(graph, sources, sinks, closed = new Set(), cap = 4) {
  const lifts = new Set(graph.nodes.filter(liftId).map((n) => n.id));
  const shut = new Set(graph.nodes.filter((n) => liftId(n) && closed.has(n.facility_id)).map((n) => n.id));
  const IN = (id) => (lifts.has(id) ? `${id}#in` : id), OUT = (id) => (lifts.has(id) ? `${id}#out` : id);
  const g = new Map();
  const add = (u, v, c) => {
    if (!g.has(u)) g.set(u, new Map()); if (!g.has(v)) g.set(v, new Map());
    g.get(u).set(v, (g.get(u).get(v) ?? 0) + c); if (!g.get(v).has(u)) g.get(v).set(u, 0);
  };
  const BIG = 1e6;
  for (const id of lifts) if (!shut.has(id)) add(IN(id), OUT(id), 1);
  for (const e of graph.edges) {
    if (!e.step_free || shut.has(e.source) || shut.has(e.target)) continue;
    add(OUT(e.source), IN(e.target), BIG);
  }
  const S = "__S", T = "__T";
  for (const s of sources) add(S, IN(s), BIG);
  for (const t of sinks) add(OUT(t), T, BIG);
  const orig = new Map([...g.keys()].map((k) => [k, new Map(g.get(k))]));
  let flow = 0;
  while (flow < cap) {
    const prev = new Map([[S, null]]); const q = [S];
    while (q.length && !prev.has(T)) { const u = q.shift(); for (const [v, c] of g.get(u) ?? []) if (c > 0 && !prev.has(v)) { prev.set(v, u); q.push(v); } }
    if (!prev.has(T)) break;
    let f = Infinity; for (let v = T; prev.get(v) !== null; v = prev.get(v)) f = Math.min(f, g.get(prev.get(v)).get(v));
    for (let v = T; prev.get(v) !== null; v = prev.get(v)) { const u = prev.get(v); g.get(u).set(v, g.get(u).get(v) - f); g.get(v).set(u, g.get(v).get(u) + f); }
    flow += f;
    if (f >= BIG) break;
  }
  const atGrade = flow >= BIG;
  const used = new Map(); for (const [u, m] of orig) for (const [v, c] of m) { const r = c - (g.get(u).get(v) ?? 0); if (r > 0) used.set(`${u}>${v}`, r); }
  const out = [];
  for (let n = 0; n < Math.min(flow, cap); n++) {
    const path = []; let u = S; const seen = new Set();
    while (u !== T && !seen.has(u)) {
      seen.add(u);
      const nxt = [...(orig.get(u)?.keys() ?? [])].find((v) => (used.get(`${u}>${v}`) ?? 0) > 0);
      if (!nxt) break;
      used.set(`${u}>${nxt}`, used.get(`${u}>${nxt}`) - 1); u = nxt;
      const id = u.replace(/#(in|out)$/, "");
      if (u !== T && path[path.length - 1] !== id) path.push(id);
    }
    if (u === T && path.length) out.push(path);
  }
  return { k: atGrade ? Infinity : flow, atGrade, paths: out };
}

/* ================================================================= shared look */
let lookPromise = null;
/** HDRI environment and concrete maps, loaded once per page (CC0, Poly Haven; see /concepts/assets/CREDITS.md). */
export function loadLook(renderer) {
  if (lookPromise) return lookPromise;
  lookPromise = (async () => {
    const pm = new THREE.PMREMGenerator(renderer);
    let env;
    try {
      // a neutral white studio keeps the model's whites white; the warmer studio is the fallback
      const hdr = await new RGBELoader().loadAsync(`${ASSETS}/white_studio_03_1k.hdr`).catch(() => new RGBELoader().loadAsync(`${ASSETS}/studio_small_09_1k.hdr`));
      env = pm.fromEquirectangular(hdr).texture; hdr.dispose();
    } catch { env = pm.fromScene(new RoomEnvironment(), 0.04).texture; }
    const tl = new THREE.TextureLoader();
    const tex = async (f, srgb = false) => {
      try { const t = await tl.loadAsync(`${ASSETS}/${f}`); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace; t.anisotropy = 4; return t; }
      catch { return null; }
    };
    const [normal, arm] = await Promise.all([tex("concrete_floor_worn_001_nor_gl_1k.jpg"), tex("concrete_floor_worn_001_arm_1k.jpg")]);
    return { env, normal, arm };
  })();
  return lookPromise;
}

export function makeRenderer(canvas) {
  const r = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false, powerPreference: "high-performance", stencil: false });
  r.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  r.outputColorSpace = THREE.SRGBColorSpace;
  r.toneMapping = THREE.NoToneMapping;               // tone mapping happens in the effects chain
  r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFSoftShadowMap;
  return r;
}

export function makeScene(renderer, look, span = 9) {
  const scene = new THREE.Scene();
  scene.background = col(TOKENS.bg);
  scene.environment = look.env;
  scene.environmentIntensity = 0.7;
  scene.environmentRotation = new THREE.Euler(0, 1.1, 0);
  const key = new THREE.DirectionalLight(0xfff1e0, 2.2);      // soft key, upper left
  key.position.set(-8, 16, 10); key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  Object.assign(key.shadow.camera, { left: -span, right: span, top: span, bottom: -span, near: 2, far: 60 });
  key.shadow.radius = 7; key.shadow.blurSamples = 16; key.shadow.bias = -0.0003; key.shadow.normalBias = 0.025;
  const fill = new THREE.DirectionalLight(0xe4ecff, 0.45); fill.position.set(10, 5, -8);
  scene.add(key, fill, new THREE.HemisphereLight(0xffffff, col(TOKENS.ground), 0.25));
  // ground: a soft-edged disc that melts into the page colour and catches shadows
  const g = new THREE.Mesh(new THREE.CircleGeometry(60, 64), new THREE.ShadowMaterial({ color: 0x3b3326, opacity: 0.12 }));
  g.rotation.x = -Math.PI / 2; g.position.y = -0.16; g.receiveShadow = true; scene.add(g);
  return { scene, key };
}

/** AO (half resolution), selective bloom for status lights, depth of field while a lift is in focus, neutral tone map. */
export function makeEffects(renderer, scene, camera) {
  const composer = new EffectComposer(renderer, { frameBufferType: THREE.HalfFloatType, multisampling: Math.min(4, renderer.capabilities.maxSamples ?? 0) });
  composer.addPass(new RenderPass(scene, camera));
  const ao = new N8AOPostPass(scene, camera, 1, 1);
  ao.configuration.aoRadius = 0.55; ao.configuration.distanceFalloff = 0.6; ao.configuration.intensity = 2.4;
  ao.configuration.halfRes = true; ao.configuration.color = col("#2a2620"); ao.configuration.gammaCorrection = false;
  ao.setQualityMode?.("Performance");
  composer.addPass(ao);
  const dof = new DepthOfFieldEffect(camera, { focusDistance: 0.02, focalLength: 0.05, bokehScale: 0, height: 480 });
  dof.target = new THREE.Vector3();
  const dofPass = new EffectPass(camera, dof); dofPass.enabled = false;
  composer.addPass(dofPass);
  const bloom = new SelectiveBloomEffect(scene, camera, { intensity: 1.6, luminanceThreshold: 0.0, luminanceSmoothing: 0.2, mipmapBlur: true, radius: 0.6 });
  bloom.inverted = false; bloom.ignoreBackground = true;
  const mode = ToneMappingMode.NEUTRAL ?? ToneMappingMode.AGX ?? ToneMappingMode.ACES_FILMIC;
  composer.addPass(new EffectPass(camera, bloom, new ToneMappingEffect({ mode })));
  let bokeh = 0, bokehWant = 0;
  return {
    composer, ao, bloom, dof,
    select(objs) { bloom.selection.clear(); for (const o of objs) o && bloom.selection.add(o); },
    focus(point) { if (point) { dof.target.copy(point); bokehWant = 2.4; dofPass.enabled = true; } else bokehWant = 0; },
    setSize(w, h) { composer.setSize(w, h); },
    /** returns true while the focus blur is still easing */
    render(dt) {
      const d = bokehWant - bokeh;
      bokeh = Math.abs(d) < 0.02 ? bokehWant : bokeh + d * (1 - Math.exp(-dt * 6));
      dof.bokehScale = bokeh; dofPass.enabled = bokeh > 0.02;
      composer.render(dt);
      return Math.abs(bokehWant - bokeh) > 0.02;
    },
  };
}

export function radialTexture(stops) {
  const c = document.createElement("canvas"); c.width = c.height = 256;
  const x = c.getContext("2d"); const gr = x.createRadialGradient(128, 128, 0, 128, 128, 128);
  stops.forEach(([o, s]) => gr.addColorStop(o, s)); x.fillStyle = gr; x.fillRect(0, 0, 256, 256);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
function stripeTexture() {
  const c = document.createElement("canvas"); c.width = 256; c.height = 8;
  const x = c.getContext("2d"); const gr = x.createLinearGradient(0, 0, 256, 0);
  gr.addColorStop(0, "#20304f"); gr.addColorStop(0.42, "#3e7bfa"); gr.addColorStop(0.5, "#ffffff"); gr.addColorStop(0.58, "#3e7bfa"); gr.addColorStop(1, "#20304f");
  x.fillStyle = gr; x.fillRect(0, 0, 256, 8);
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; return t;
}

/* ================================================================= the model */
export function buildStation(graph, opts = {}) {
  const dir = opts.dir ?? "exit";
  const look = opts.look ?? {};
  const T = 0.28;
  const nodes = graph.nodes, byId = new Map(nodes.map((n) => [n.id, n]));
  const dist = floorsOf(graph);
  const reach = nodes.filter((n) => dist.has(n.id) && !liftId(n));
  const maxFloor = Math.max(0, ...reach.map((n) => dist.get(n.id)));
  const floorOf = (n) => (dist.has(n.id) ? (liftId(n) ? null : Math.round(dist.get(n.id))) : maxFloor + 1);
  const floors = [...new Set(nodes.filter((n) => !liftId(n)).map(floorOf))].sort((a, b) => a - b);
  const nF = floors.length;
  const GAP = THREE.MathUtils.clamp(5.6 / Math.max(1, nF - 1), 1.5, 2.2);
  const fIndex = (f) => floors.indexOf(f);
  const baseY = (fi) => (nF - 1 - fi) * GAP;
  let explode = 0;
  const yAt = (fi) => baseY(fi) * (1 + 0.85 * explode);

  // rows: back (street, entrances), middle (walkways, gates), front (platforms); lifts stand on the front edge
  const ROW = { street: -1.6, entrance: -1.6, area: -0.8, gate: -0.15, platform: 0.5 };
  const rowsKey = (n) => `${floorOf(n)}|${n.kind === "street" ? "entrance" : n.kind}`;
  const rows = new Map();
  for (const n of nodes) { if (liftId(n)) continue; const k = rowsKey(n); if (!rows.has(k)) rows.set(k, []); rows.get(k).push(n); }
  const maxRow = Math.max(1, ...[...rows.values()].map((r) => r.length));
  const W = THREE.MathUtils.clamp(maxRow * 0.78 + 2.2, 6.6, 12.5), D = 4.4;
  const x = new Map();
  for (const r of rows.values()) r.sort((a, b) => a.id.localeCompare(b.id)).forEach((n, i) => x.set(n.id, (i + 0.5) / r.length));
  const nbr = new Map(nodes.map((n) => [n.id, new Set()]));
  for (const e of graph.edges) if (e.step_free) { nbr.get(e.source)?.add(e.target); nbr.get(e.target)?.add(e.source); }
  const viaLift = (id) => [...(nbr.get(id) ?? [])].flatMap((m) => (liftId(byId.get(m)) ? [...nbr.get(m)].filter((q) => q !== id) : [m]));
  for (let it = 0; it < 6; it++) for (const r of rows.values()) {
    const bc = new Map(r.map((n) => { const ns = viaLift(n.id).filter((m) => x.has(m)); return [n.id, ns.length ? ns.reduce((s, m) => s + x.get(m), 0) / ns.length : x.get(n.id)]; }));
    r.sort((a, b) => bc.get(a.id) - bc.get(b.id) || a.id.localeCompare(b.id)).forEach((n, i) => x.set(n.id, (i + 0.5) / r.length));
  }
  const usable = W - 1.2;
  const local = new Map();   // node id -> { fi, p (position within its floor group) }
  for (const n of nodes) {
    if (liftId(n)) continue;
    local.set(n.id, { fi: fIndex(floorOf(n)), p: new THREE.Vector3((x.get(n.id) - 0.5) * usable, T / 2, ROW[n.kind] ?? 0) });
  }
  const worldPos = (id, out = new THREE.Vector3()) => { const l = local.get(id); return l ? out.copy(l.p).setY(l.p.y + yAt(l.fi)) : null; };

  /* materials */
  const concrete = (hex, rough = 0.85) => {
    const m = new THREE.MeshStandardMaterial({ color: col(hex), roughness: rough, metalness: 0 });
    if (look.normal) { m.normalMap = look.normal.clone(); m.normalMap.needsUpdate = true; m.normalScale.set(0.35, 0.35); }
    if (look.arm) { m.roughnessMap = look.arm.clone(); m.roughnessMap.needsUpdate = true; m.aoMap = m.roughnessMap; m.aoMapIntensity = 0.25; }
    return m;
  };
  const M = {
    slab: concrete("#FBFAF8", 0.88), edge: concrete("#E9E5DD", 0.9),
    stone: new THREE.MeshStandardMaterial({ color: col(TOKENS.stone), roughness: 0.7 }),
    mark: new THREE.MeshStandardMaterial({ color: col(TOKENS.sand), roughness: 0.9 }),
    tactile: new THREE.MeshStandardMaterial({ color: col("#E9B723"), roughness: 0.6 }),
    metal: new THREE.MeshPhysicalMaterial({ color: col("#cfd4da"), metalness: 1, roughness: 0.32, anisotropy: 0.7, anisotropyRotation: Math.PI / 2 }),
    dark: new THREE.MeshStandardMaterial({ color: col("#2c3036"), roughness: 0.55, metalness: 0.2 }),
    glass: new THREE.MeshPhysicalMaterial({ color: col("#f4f8ff"), metalness: 0, roughness: 0.06, transmission: 1, thickness: 0.22, ior: 1.45,
      attenuationColor: col("#d6e4ff"), attenuationDistance: 2.5, specularIntensity: 0.8, envMapIntensity: 1.2 }),
  };
  const setTexRepeat = (m, rx, ry) => { for (const t of [m.normalMap, m.roughnessMap]) t?.repeat.set(rx, ry); };
  setTexRepeat(M.slab, W / 3, D / 3);

  const rbox = (w, h, d, r = 0.06, seg = 4) => new RoundedBoxGeometry(w, h, d, seg, Math.min(r, w / 2 - 1e-3, h / 2 - 1e-3, d / 2 - 1e-3));
  const group = new THREE.Group();
  const floorGroups = floors.map((f, fi) => { const g = new THREE.Group(); g.position.y = baseY(fi); group.add(g); return g; });
  const add = (parent, geo, mat, p, shadow = true) => { const m = new THREE.Mesh(geo, mat); m.position.copy(p); m.castShadow = shadow; m.receiveShadow = true; parent.add(m); return m; };
  const bloomables = [];

  // floors: a concrete slab with a sand edge band
  for (let fi = 0; fi < nF; fi++) {
    const s = add(floorGroups[fi], rbox(W, T, D, 0.12, 6), M.slab, new THREE.Vector3(0, 0, 0), false);
    s.receiveShadow = true;
    add(floorGroups[fi], rbox(W + 0.02, 0.05, D + 0.02, 0.025, 3), M.edge, new THREE.Vector3(0, -T / 2 + 0.05, 0), false);
  }

  // things on the floors
  const platforms = new Map();
  const perRow = (n) => rows.get(rowsKey(n)).length;
  for (const n of nodes) {
    const l = local.get(n.id); if (!l) continue;
    const fg = floorGroups[l.fi], p = l.p;
    if (n.kind === "street") {
      add(fg, new THREE.CylinderGeometry(0.62, 0.62, 0.03, 64), new THREE.MeshStandardMaterial({ color: col("#fbfaf7"), roughness: 0.5 }), p.clone().add(new THREE.Vector3(0, 0.016, 0.25)));
      add(fg, new THREE.TorusGeometry(0.62, 0.018, 8, 64), M.metal, p.clone().add(new THREE.Vector3(0, 0.03, 0.25))).rotation.x = Math.PI / 2;
    } else if (n.kind === "entrance") {
      // a small portal: two posts and a lintel
      const q = p.clone();
      add(fg, rbox(0.06, 0.46, 0.06, 0.02), M.metal, q.clone().add(new THREE.Vector3(-0.16, 0.23, 0)));
      add(fg, rbox(0.06, 0.46, 0.06, 0.02), M.metal, q.clone().add(new THREE.Vector3(0.16, 0.23, 0)));
      add(fg, rbox(0.4, 0.06, 0.08, 0.02), M.metal, q.clone().add(new THREE.Vector3(0, 0.48, 0)));
    } else if (n.kind === "gate") {
      add(fg, rbox(0.08, 0.36, 0.44, 0.03), M.stone, p.clone().add(new THREE.Vector3(-0.07, 0.18, 0)));
      add(fg, rbox(0.12, 0.02, 0.36, 0.01), M.glass, p.clone().add(new THREE.Vector3(0.05, 0.3, 0)), false);
    } else if (n.kind === "area") {
      add(fg, new THREE.CylinderGeometry(0.07, 0.07, 0.015, 20), M.mark, p.clone().add(new THREE.Vector3(0, 0.008, 0)), false);
    } else if (n.kind === "platform") {
      const len = Math.min(1.5, (usable / perRow(n)) * 0.86);
      const mat = new THREE.MeshStandardMaterial({ color: col(TOKENS.sand), roughness: 0.75 });
      const m = add(fg, rbox(len, 0.14, 0.62, 0.05), mat, p.clone().add(new THREE.Vector3(0, 0.07, 0)));
      add(fg, new THREE.BoxGeometry(len * 0.94, 0.012, 0.07), M.tactile, p.clone().add(new THREE.Vector3(0, 0.146, 0.26)), false);  // tactile edge strip
      m.userData.platform = n.id;
      platforms.set(n.id, { id: n.id, name: n.label, mesh: m, mat, fi: l.fi, local: p.clone(), k: null, lost: false, shake: 0 });
    }
  }

  // stairs and escalators: the links the data marks not step-free, where they join two floors
  const stairGeo = (() => {
    const steps = []; const N = 7;
    for (let i = 0; i < N; i++) { const b = new THREE.BoxGeometry(0.42, (i + 1) / N, 1 / N); b.translate(0, (i + 1) / N / 2, -0.5 + (i + 0.5) / N); steps.push(b); }
    return mergeGeometries(steps);
  })();
  const stairs = [];
  const seenStep = new Set();
  for (const e of graph.edges) {
    if (e.step_free) continue;
    const a = local.get(e.source), b = local.get(e.target);
    if (!a || !b || a.fi === b.fi) continue;
    const key = [e.source, e.target].sort().join("|"); if (seenStep.has(key)) continue; seenStep.add(key);
    if (stairs.length >= 10) break;
    const [hiF, loF] = a.fi < b.fi ? [a, b] : [b, a];
    const m = new THREE.Mesh(stairGeo, M.stone); m.castShadow = true; m.receiveShadow = true;
    m.userData.stair = { hiFi: hiF.fi, loFi: loF.fi, x: (hiF.p.x + loF.p.x) / 2 + (stairs.length % 2) * 0.5, z: -1.15 };
    group.add(m); stairs.push(m);
  }

  // lifts: glass shaft, brushed metal frame, cabin with doors, a status light
  const lifts = new Map();
  const slots = [];
  const amberTex = radialTexture([[0, "rgba(255,190,80,0.85)"], [0.35, "rgba(255,170,40,0.3)"], [1, "rgba(255,170,40,0)"]]);
  const redTex = radialTexture([[0, "rgba(229,72,77,0.65)"], [0.4, "rgba(229,72,77,0.22)"], [1, "rgba(229,72,77,0)"]]);
  for (const n of nodes.filter(liftId)) {
    const ends = [...(nbr.get(n.id) ?? [])].map((m) => local.get(m)).filter(Boolean);
    if (!ends.length) continue;
    const fis = ends.map((e) => e.fi); const loFi = Math.max(...fis), hiFi = Math.min(...fis);   // lower floor has the larger index
    let lx = ends.reduce((s, e) => s + e.p.x, 0) / ends.length;
    const crowd = slots.filter((s) => Math.abs(s.x - lx) < 0.66 && !(s.hiFi > loFi || s.loFi < hiFi)).length;
    lx += 0.66 * crowd;
    slots.push({ x: lx, loFi, hiFi });
    const lz = 1.55;
    const g = new THREE.Group(); group.add(g);
    // geometry is built for a unit height and scaled, so explode can stretch the shaft
    const shaftGeo = rbox(0.56, 1, 0.56, 0.08, 4); shaftGeo.translate(0, 0.5, 0);
    const glass = new THREE.Mesh(shaftGeo, M.glass); glass.castShadow = false; glass.receiveShadow = false; g.add(glass);
    const frame = new THREE.Group(); g.add(frame);
    for (const [dx, dz] of [[-0.27, -0.27], [0.27, -0.27], [-0.27, 0.27], [0.27, 0.27]]) {
      const post = new THREE.Mesh(new THREE.BoxGeometry(0.04, 1, 0.04).translate(0, 0.5, 0), M.metal); post.position.set(dx, 0, dz); post.castShadow = true; frame.add(post);
    }
    const ring = (y) => { const r = new THREE.Mesh(rbox(0.62, 0.05, 0.62, 0.02, 2), M.metal); r.position.y = y; r.castShadow = true; g.add(r); return r; };
    const base = ring(0.025), crown = ring(1);
    const capMat = new THREE.MeshStandardMaterial({ color: col("#e9ecef"), metalness: 0.6, roughness: 0.35 });
    const cap = new THREE.Mesh(rbox(0.6, 0.08, 0.6, 0.03, 3), capMat); cap.castShadow = true; g.add(cap);
    const lampMat = new THREE.MeshStandardMaterial({ color: col("#ffffff"), emissive: col(TOKENS.working), emissiveIntensity: 2.2, roughness: 0.3 });
    const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.075, 20, 14), lampMat); g.add(lamp); bloomables.push(lamp);
    // the cabin, parked at the lower floor
    const cabin = new THREE.Group(); g.add(cabin);
    const cabMat = new THREE.MeshPhysicalMaterial({ color: col(TOKENS.working), roughness: 0.35, metalness: 0.15, clearcoat: 0.8, clearcoatRoughness: 0.25 });
    const cab = new THREE.Mesh(rbox(0.42, 0.5, 0.42, 0.05, 3), cabMat); cab.position.y = 0.3; cab.castShadow = true; cabin.add(cab);
    const inside = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.4, 0.02), new THREE.MeshStandardMaterial({ color: col("#fff4d6"), emissive: col("#ffe7b0"), emissiveIntensity: 0.8 }));
    inside.position.set(0, 0.29, 0.205); cabin.add(inside);
    const doorL = new THREE.Mesh(new THREE.BoxGeometry(0.17, 0.4, 0.015), M.metal), doorR = doorL.clone();
    doorL.position.set(-0.085, 0.29, 0.218); doorR.position.set(0.085, 0.29, 0.218); cabin.add(doorL, doorR);
    const stripMat = new THREE.MeshStandardMaterial({ color: col("#ffffff"), emissive: col(TOKENS.working), emissiveIntensity: 1.6 });
    const strip = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.02, 0.3), stripMat); strip.position.y = 0.56; cabin.add(strip); bloomables.push(strip);
    const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: amberTex, transparent: true, depthWrite: false, opacity: 0 }));
    glow.scale.set(2.2, 2.2, 1); g.add(glow);
    const pulse = new THREE.Mesh(new THREE.RingGeometry(0.34, 0.4, 48), new THREE.MeshBasicMaterial({ color: col(TOKENS.closed), transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide }));
    pulse.rotation.x = -Math.PI / 2; g.add(pulse); bloomables.push(pulse);
    const L = { id: n.id, fid: n.facility_id, label: n.label, g, glass, frame, base, crown, cap, lamp, lampMat, cabin, cab, cabMat, inside, doorL, doorR, strip, stripMat, glow, pulse,
      loFi, hiFi, x: lx, z: lz, closed: n.status === "closed", state: "open", hover: 0, hoverV: 0, hoverWant: 0, door: n.status === "closed" ? 0 : 1, pulseT: 9,
      color: col(TOKENS.working), lastFor: [] };
    for (const o of [glass, cab, cap, doorL, doorR, ...frame.children]) o.userData.lift = L;
    lifts.set(n.facility_id, L);
  }
  const liftList = [...lifts.values()];

  /* layout that depends on explode: floor heights, shaft lengths, stairs */
  function layout() {
    floorGroups.forEach((g, fi) => (g.position.y = yAt(fi)));
    for (const L of liftList) {
      const lo = yAt(L.loFi) + T / 2, hi = yAt(L.hiFi) + T / 2;
      const h = Math.max(hi - lo, GAP * 0.9) + 0.55;
      L.lo = lo; L.h = h;
      L.g.position.set(L.x, lo + L.hover * 0.09, L.z);
      L.glass.scale.y = h; L.frame.scale.y = h; L.crown.position.y = h; L.cap.position.y = h + 0.06; L.lamp.position.y = h + 0.14;
      L.glow.position.y = h * 0.5; L.glow.scale.setScalar(Math.min(3, 1.2 + h * 0.4));
    }
    for (const s of stairs) {
      const u = s.userData.stair, top = yAt(u.hiFi) - T / 2, bot = yAt(u.loFi) + T / 2;
      const rise = Math.max(0.1, top - bot);
      s.position.set(u.x, bot, u.z); s.scale.set(1, rise, Math.min(1.9, rise * 1.15));   // a run in proportion to the rise
      s.visible = explode < 0.12;                                                        // stairs belong to the assembled building
    }
  }
  layout();
  // things on a floor don't cast shadows through the slab onto the floor below; ambient occlusion grounds them
  for (const fg of floorGroups) fg.traverse((o) => { if (o.isMesh) o.castShadow = false; });

  /* routes: tubes with a flowing light texture, and a light pulse that travels each new route */
  const stripe = stripeTexture();
  let drawn = [];
  let currentPaths = [];
  function pathPoints(path) {
    const pts = [];
    for (let i = 0; i < path.length; i++) {
      const n = byId.get(path[i]);
      if (liftId(n)) {
        const L = lifts.get(n.facility_id); if (!L) continue;
        const prev = pts[pts.length - 1];
        const nxt = worldPos(path[i + 1]);
        const a = prev ? prev.y : L.lo + 0.3, b = nxt ? nxt.y + 0.22 : L.lo + L.h;
        const zf = L.z + 0.36;
        pts.push(new THREE.Vector3(L.x, a, zf), new THREE.Vector3(L.x, b, zf));
      } else {
        const p = worldPos(path[i]); if (p) pts.push(p.add(new THREE.Vector3(0, n.kind === "platform" ? 0.3 : 0.2, 0)));
      }
    }
    return pts.filter((p, i) => i === 0 || p.distanceTo(pts[i - 1]) > 0.05);
  }
  function buildRoutes(keepDraw = false) {
    const old = drawn;
    drawn = currentPaths.map((path, i) => {
      const pts = pathPoints(path); if (pts.length < 2) return null;
      const curve = new THREE.CatmullRomCurve3(pts, false, "centripetal", 0.35);
      const len = curve.getLength();
      const geo = new THREE.TubeGeometry(curve, Math.max(80, Math.round(len * 30)), 0.05, 12, false);
      const map = stripe.clone(); map.needsUpdate = true; map.repeat.set(Math.max(1, len / 0.9), 1);
      const mat = new THREE.MeshStandardMaterial({ color: col(TOKENS.route), emissive: col("#ffffff"), emissiveMap: map, emissiveIntensity: 0.9, roughness: 0.35 });
      const mesh = new THREE.Mesh(geo, mat); group.add(mesh);
      const head = new THREE.Mesh(new THREE.SphereGeometry(0.09, 20, 14), new THREE.MeshStandardMaterial({ color: col("#ffffff"), emissive: col("#cfe0ff"), emissiveIntensity: 3 }));
      head.visible = false; group.add(head);
      const prev = keepDraw ? old[i] : null;
      const R = { geo, mesh, head, curve, map, n: geo.index.count, draw: prev ? prev.draw : 0 };
      geo.setDrawRange(0, Math.floor(R.n * R.draw));
      return R;
    }).filter(Boolean);
    for (const d of old) { group.remove(d.mesh, d.head); d.geo.dispose(); d.mesh.material.dispose(); d.map.dispose(); }
    station.bloom = [...bloomables, ...drawn.map((d) => d.head)];
  }

  /* state */
  const streets = nodes.filter((n) => n.kind === "street").map((n) => n.id);
  let selected = null, flowT = 0, summary = { k: null, lastLifts: [], ways: 0 };
  const flowFor = (pid, closed) => (dir === "exit" ? routes(graph, [pid], streets, closed) : routes(graph, streets, [pid], closed));
  function soleLifts(pid, closed, res) {
    if (res.atGrade || res.k !== 1) return [];
    const onPath = res.paths[0].map((id) => byId.get(id)).filter((n) => n && liftId(n)).map((n) => n.facility_id);
    return onPath.filter((fid) => flowFor(pid, new Set([...closed, fid])).k === 0);
  }
  function recompute() {
    const closed = new Set(liftList.filter((L) => L.closed).map((L) => L.fid));
    const lastFor = new Map();
    for (const P of platforms.values()) {
      const r = flowFor(P.id, closed);
      P.k = r.k; P.lost = r.k === 0; P.res = r;
      for (const f of soleLifts(P.id, closed, r)) { if (!lastFor.has(f)) lastFor.set(f, []); lastFor.get(f).push(P.name); }
    }
    for (const L of liftList) {
      L.lastFor = lastFor.get(L.fid) ?? [];
      const last = L.lastFor.length > 0;
      L.state = L.closed ? "closed" : last ? "last" : "open";
      L.color = col(L.closed ? TOKENS.closed : last ? TOKENS.last : TOKENS.working);
      L.glow.material.map = L.closed ? redTex : amberTex; L.glow.material.needsUpdate = true;
      L.glowWant = L.closed ? 0.35 : last ? 0.6 : 0;
      L.doorWant = L.closed ? 0 : 1;
    }
    for (const P of platforms.values()) P.tint = col(P.id === selected ? "#dbe6ff" : P.lost ? "#f6d6d6" : TOKENS.sand);
    const S = selected ? platforms.get(selected) : null;
    if (S) {
      const r = S.res;
      currentPaths = r.paths.slice(0, 3);
      summary = { k: r.k, atGrade: r.atGrade, ways: r.paths.length, lastLifts: soleLifts(S.id, closed, r), platform: S.name, id: S.id };
      if (r.k === 0) S.shake = 1;
    } else { currentPaths = []; summary = { k: null, ways: 0, lastLifts: [...lastFor.keys()] }; }
    buildRoutes(false);
    flowT = 0;
    station.summary = summary;
  }

  /* per-frame animation; returns true while anything still moves */
  const tmp = new THREE.Color();
  function update(dt, reduced = false) {
    let busy = false;
    const k = reduced ? 1 : 1 - Math.exp(-dt * 7);
    const ease = (cur, want, rate = 7) => (reduced ? want : cur + (want - cur) * (1 - Math.exp(-dt * rate)));
    for (const L of liftList) {
      // colour and light
      for (const [m, prop] of [[L.cabMat, "color"], [L.lampMat, "emissive"], [L.stripMat, "emissive"]]) {
        const c = m[prop]; const d = Math.abs(c.r - L.color.r) + Math.abs(c.g - L.color.g) + Math.abs(c.b - L.color.b);
        if (d > 2e-3) { c.lerp(L.color, k); busy = true; } else c.copy(L.color);
      }
      const go = L.glowWant - L.glow.material.opacity;
      if (Math.abs(go) > 2e-3) { L.glow.material.opacity += go * k; busy = true; } else L.glow.material.opacity = L.glowWant;
      // doors slide; the cabin dims when closed
      const dd = L.doorWant - L.door;
      if (Math.abs(dd) > 1e-3) { L.door = ease(L.door, L.doorWant, 5); busy = true; } else L.door = L.doorWant;
      L.doorL.position.x = -0.085 - 0.13 * L.door; L.doorR.position.x = 0.085 + 0.13 * L.door;
      L.inside.material.emissiveIntensity = 0.15 + 0.75 * L.door;
      L.stripMat.emissiveIntensity = 0.4 + 1.4 * L.door;
      // a spring on hover
      if (!reduced) {
        const a = 190 * (L.hoverWant - L.hover) - 15 * L.hoverV;
        L.hoverV += a * dt; L.hover += L.hoverV * dt;
        if (Math.abs(L.hoverWant - L.hover) > 1e-3 || Math.abs(L.hoverV) > 1e-3) busy = true; else { L.hover = L.hoverWant; L.hoverV = 0; }
      } else L.hover = L.hoverWant;
      L.g.position.y = L.lo + L.hover * 0.09;
      // the red pulse after a closure
      if (L.pulseT < 1.4) {
        L.pulseT += dt; const t = L.pulseT / 1.4;
        L.pulse.scale.setScalar(1 + t * 3.2); L.pulse.material.opacity = (1 - t) * 0.9; L.pulse.position.y = 0.03; busy = true;
      } else L.pulse.material.opacity = 0;
    }
    for (const P of platforms.values()) {
      if (P.tint) { const c = P.mat.color; const d = Math.abs(c.r - P.tint.r) + Math.abs(c.g - P.tint.g) + Math.abs(c.b - P.tint.b); if (d > 2e-3) { c.lerp(P.tint, k); busy = true; } else c.copy(P.tint); }
      if (P.shake > 0) { P.shake = Math.max(0, P.shake - dt * 1.6); P.mesh.position.x = P.local.x + (reduced ? 0 : Math.sin(P.shake * 40) * 0.06 * P.shake); busy = true; }
    }
    // routes grow from the platform with a travelling light, then the light flows for a few seconds
    flowT += dt;
    for (const R of drawn) {
      const want = station.routeGate;
      const d = want - R.draw;
      if (Math.abs(d) > 1e-3) { R.draw += d * (reduced ? 1 : 1 - Math.exp(-dt * 2.2)); busy = true; } else R.draw = want;
      R.geo.setDrawRange(0, Math.floor(R.n * R.draw));
      R.head.visible = !reduced && R.draw > 0.01 && R.draw < 0.985;
      if (R.head.visible) R.head.position.copy(R.curve.getPointAt(Math.min(1, R.draw)));
      if (!reduced && flowT < 4.5) { R.map.offset.x -= dt * 0.9; busy = true; }
    }
    return busy;
  }

  let box = new THREE.Box3().setFromObject(group);
  const station = {
    group, lifts, platforms, floors: nF, width: W, depth: D, routeGate: 1, summary, bloom: [], get bounds() { return box; },
    get selected() { return selected; },
    get explode() { return explode; },
    setExplode(e) { explode = e; layout(); buildRoutes(true); },
    select(pid) { selected = pid && platforms.has(pid) ? pid : null; recompute(); },
    setClosed(fids) { const s = new Set(fids); for (const L of liftList) L.closed = s.has(L.fid); recompute(); },
    toggle(fid) {
      const L = lifts.get(fid); if (!L) return;
      L.closed = !L.closed;
      if (L.closed) L.pulseT = 0;
      recompute();
      return station.summary;
    },
    pickables: () => [...liftList.flatMap((L) => [L.glass, L.cab, L.cap]), ...[...platforms.values()].map((P) => P.mesh)],
    anchor(id) {
      const L = lifts.get(id); if (L) return new THREE.Vector3(L.x, L.lo + L.h + 0.2, L.z);
      const P = platforms.get(id); if (P) return worldPos(id).add(new THREE.Vector3(0, 0.3, 0));
      return box.getCenter(new THREE.Vector3());
    },
    centre(id) { const L = lifts.get(id); return L ? new THREE.Vector3(L.x, L.lo + L.h * 0.45, L.z) : station.anchor(id); },
    update, recompute,
  };
  recompute();
  box = new THREE.Box3().setFromObject(group);
  return station;
}

/* ================================================================= mount: an interactive viewer for any station */
const CSS = `
.llv{position:relative;width:100%;height:100%;font-family:Inter,system-ui,sans-serif;color:${TOKENS.ink}}
.llv canvas{display:block;width:100%;height:100%;touch-action:none;cursor:grab;border-radius:inherit}
.llv canvas.drag{cursor:grabbing}.llv canvas.hot{cursor:pointer}
.llv-card{position:absolute;z-index:3;min-width:236px;max-width:290px;padding:14px 16px 14px;border-radius:18px;
  background:rgba(255,255,255,.62);backdrop-filter:blur(18px) saturate(1.5);-webkit-backdrop-filter:blur(18px) saturate(1.5);
  box-shadow:0 18px 50px rgba(22,24,29,.14),0 0 0 1px rgba(255,255,255,.7) inset,0 0 0 1px rgba(62,123,250,.10);
  transform:translate(-50%,calc(-100% - 18px)) scale(.94);opacity:0;pointer-events:none;
  transition:opacity .28s cubic-bezier(.2,0,0,1),transform .5s cubic-bezier(.34,1.56,.64,1)}
.llv-card.show{opacity:1;transform:translate(-50%,calc(-100% - 18px)) scale(1)}
.llv-card.pinned{pointer-events:auto}
.llv-card.shake{animation:llvshake .5s}
@keyframes llvshake{20%{margin-left:-7px}40%{margin-left:6px}60%{margin-left:-4px}80%{margin-left:2px}}
.llv-card h3{margin:0 0 6px;font:700 19px/1.1 "Inter Tight",Inter,sans-serif;letter-spacing:-.02em;display:flex;align-items:center;gap:8px}
.llv-card .pill{font:600 11.5px/1 Inter,sans-serif;padding:5px 9px;border-radius:999px;color:#fff;background:${TOKENS.working}}
.llv-card .pill[data-s=last]{background:${TOKENS.last};color:#2a1a00}.llv-card .pill[data-s=closed]{background:${TOKENS.closed}}
.llv-card p{margin:4px 0;font-size:13px;line-height:1.35;color:${TOKENS.muted}}
.llv-card p b{color:${TOKENS.ink};font-weight:600}
.llv-card .row{display:flex;gap:8px;margin-top:10px}
.llv-btn{--mx:0px;--my:0px;--s:1;position:relative;overflow:hidden;isolation:isolate;display:inline-flex;align-items:center;justify-content:center;gap:6px;
  height:34px;padding:0 15px;border-radius:999px;border:0;font:600 13px Inter,sans-serif;cursor:pointer;color:#fff;background:${TOKENS.ink};
  transform:translate(var(--mx),var(--my)) scale(var(--s));transition:transform .5s cubic-bezier(.34,1.56,.64,1),background .3s,box-shadow .3s;
  box-shadow:0 6px 18px rgba(22,24,29,.16)}
.llv-btn::after{content:"";position:absolute;inset:-2px;z-index:-1;background:linear-gradient(105deg,transparent 32%,rgba(255,255,255,.35) 48%,transparent 64%);transform:translateX(-130%)}
.llv-btn:hover::after{transform:translateX(130%);transition:transform .9s cubic-bezier(.2,0,0,1)}
.llv-btn:active{--s:.95;transition-duration:.12s}
.llv-btn.line{color:${TOKENS.ink};background:rgba(255,255,255,.7);box-shadow:inset 0 0 0 1.5px ${TOKENS.ink}}
.llv-btn.danger{background:${TOKENS.closed}}
.llv-btn:focus-visible,.llv-keys button:focus-visible{outline:3px solid ${TOKENS.route};outline-offset:3px}
.llv-tools{position:absolute;right:14px;bottom:14px;z-index:3;display:flex;gap:6px;padding:5px;border-radius:999px;
  background:rgba(255,255,255,.5);backdrop-filter:blur(14px);box-shadow:inset 0 0 0 1px rgba(255,255,255,.6),0 6px 20px rgba(22,24,29,.06)}
.llv-tools .llv-btn{background:rgba(255,255,255,.85);color:${TOKENS.ink};box-shadow:none}
.llv-tools .llv-btn[aria-pressed=true]{background:${TOKENS.ink};color:#fff}
.llv-tools input{accent-color:${TOKENS.ink};width:90px;align-self:center}
.llv-keys{position:absolute;left:14px;bottom:14px;z-index:3;display:flex;flex-wrap:wrap;gap:4px;max-width:55%}
.llv-keys button{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0;padding:0}
.llv-keys button:focus{position:static;width:auto;height:30px;clip:auto;padding:0 12px;border-radius:999px;background:#fff;font:600 12.5px Inter,sans-serif;
  box-shadow:0 6px 20px rgba(22,24,29,.12)}
.llv-hint{position:absolute;left:50%;top:14px;transform:translateX(-50%);z-index:2;font:500 12px Inter,sans-serif;color:${TOKENS.muted};
  padding:6px 12px;border-radius:999px;background:rgba(255,255,255,.55);backdrop-filter:blur(10px);transition:opacity .6s}
@media (prefers-reduced-motion: reduce){.llv-card,.llv-btn{transition:none}.llv-btn::after{display:none}.llv-card.shake{animation:none}}
`;

export async function mount(container, stationId, opts = {}) {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!document.getElementById("llv-css")) { const s = document.createElement("style"); s.id = "llv-css"; s.textContent = CSS; document.head.appendChild(s); }
  const [data, state] = await Promise.all([
    opts.data ?? fetch(`/m/station/${encodeURIComponent(stationId)}.json`).then((r) => r.json()),
    opts.state ?? fetch("/m/state.json").then((r) => r.json()).catch(() => null),
  ]);
  const deps = new Map((state?.priority?.data?.ranked ?? []).map((r) => [String(r.facility_id), r.departures_day]));
  const graph = data.graph[opts.dir ?? "exit"];

  const root = document.createElement("div"); root.className = "llv"; container.appendChild(root);
  const canvas = document.createElement("canvas"); canvas.setAttribute("aria-hidden", "true"); root.appendChild(canvas);
  const card = document.createElement("div"); card.className = "llv-card"; card.setAttribute("role", "region"); card.setAttribute("aria-label", "Lift details"); card.setAttribute("aria-live", "polite"); root.appendChild(card);
  const hint = document.createElement("div"); hint.className = "llv-hint"; hint.setAttribute("aria-hidden", "true");
  hint.textContent = "Drag to turn · scroll to zoom · click a lift or a platform · double-click to reset"; root.appendChild(hint);
  const tools = document.createElement("div"); tools.className = "llv-tools"; root.appendChild(tools);
  const keys = document.createElement("div"); keys.className = "llv-keys"; keys.setAttribute("role", "group"); keys.setAttribute("aria-label", "Lifts in this station"); root.appendChild(keys);

  const renderer = makeRenderer(canvas);
  const look = await loadLook(renderer);
  const station = buildStation(graph, { ...opts, look });
  const { scene } = makeScene(renderer, look, Math.max(8, station.width * 0.75));
  const world = new THREE.Group(); world.add(station.group); scene.add(world);
  const c0 = station.bounds.getCenter(new THREE.Vector3()); station.group.position.x -= c0.x; station.group.position.z -= c0.z;
  const camera = new THREE.PerspectiveCamera(38, 1, 0.2, 400);
  const fx = makeEffects(renderer, scene, camera);
  const toWorld = (v) => station.group.localToWorld(v.clone());

  /* orbit camera with limits */
  const size = station.bounds.getSize(new THREE.Vector3());
  const radius = Math.max(size.x * 0.92, size.y * 1.3, size.z) * 0.6;
  const HOME = { yaw: 0.62, pitch: 0.36, dist: 1, target: new THREE.Vector3(0, size.y * 0.42, 0) };
  const cam = { yaw: HOME.yaw - (reduced ? 0 : 0.35), pitch: HOME.pitch, dist: 1, target: HOME.target.clone() };
  const want = { yaw: HOME.yaw, pitch: HOME.pitch, dist: 1, target: HOME.target.clone() };
  let baseDist = 10;
  const fitDist = () => radius / Math.tan(THREE.MathUtils.degToRad(19)) / Math.min(1, camera.aspect) * 1.02;
  function placeCamera() {
    const d = baseDist * cam.dist, cp = Math.cos(cam.pitch);
    camera.position.set(cam.target.x + d * Math.sin(cam.yaw) * cp, cam.target.y + d * Math.sin(cam.pitch), cam.target.z + d * Math.cos(cam.yaw) * cp);
    camera.lookAt(cam.target);
  }

  /* interaction state */
  let dragging = false, px = 0, py = 0, moved = 0, vYaw = 0, vPitch = 0, hover = null, focus = null, touched = false;
  let turntable = !reduced, idleT0 = performance.now();
  const stopIdle = () => { if (turntable) { turntable = false; } touched = true; hint.style.opacity = "0"; };
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  const pick = (e) => {
    const r = canvas.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObjects(station.pickables(), false)[0];
    return hit ? (hit.object.userData.lift ?? { platform: hit.object.userData.platform }) : null;
  };
  const word = (L) => (L.state === "closed" ? "Closed" : L.state === "last" ? "Last lift" : "Working");
  function cardFor(L, pinned) {
    const d = deps.get(String(L.fid));
    card.innerHTML = `<h3>Lift ${L.fid} <span class="pill" data-s="${L.state}">${word(L)}</span></h3>
      <p>${L.label.replace(/^.*?Elevator \d+\s*/, "").replace(/^\(|\)$/g, "") || L.label}</p>
      ${L.lastFor.length ? `<p>The only step-free link for <b>${L.lastFor.slice(0, 3).join(", ")}${L.lastFor.length > 3 ? ` and ${L.lastFor.length - 3} more` : ""}</b>.</p>` : ""}
      ${d ? `<p><b>${Number(d).toLocaleString("en-US")}</b> scheduled departures a day pass this lift's platforms.</p>` : ""}
      ${pinned ? `<div class="row"><button class="llv-btn ${L.closed ? "" : "danger"}" data-act="toggle">${L.closed ? "Reopen lift" : "Close lift"}</button>
        <button class="llv-btn line" data-act="done">Done</button></div>` : ""}`;
    card.classList.toggle("pinned", !!pinned);
    card.classList.add("show");
    card.dataset.fid = L.fid;
    placeCard();
    magnet(card);
  }
  function placeCard() {
    const fid = card.dataset.fid; const L = fid && station.lifts.get(fid);
    if (!L || !card.classList.contains("show")) return;
    const v = toWorld(station.anchor(fid)).project(camera);
    const r = root.getBoundingClientRect();
    card.style.left = `${THREE.MathUtils.clamp((v.x * 0.5 + 0.5) * r.width, 150, r.width - 150)}px`;
    card.style.top = `${Math.max(card.offsetHeight + 24, (-v.y * 0.5 + 0.5) * r.height)}px`;
  }
  function hideCard() { card.classList.remove("show", "pinned"); card.dataset.fid = ""; }
  card.addEventListener("click", (e) => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "toggle") toggle(card.dataset.fid);
    if (act === "done") unfocus();
  });

  function setHover(L) {
    for (const x of station.lifts.values()) x.hoverWant = x === L ? 1 : 0;
    hover = L; canvas.classList.toggle("hot", !!L);
    if (L && !focus) cardFor(L, false); else if (!focus) hideCard();
    kick();
  }
  function focusLift(L) {
    focus = L; stopIdle();
    want.target.copy(toWorld(station.centre(L.fid)));
    want.dist = 0.5;
    fx.focus(toWorld(station.centre(L.fid)));
    cardFor(L, true);
    setTimeout(() => card.querySelector("[data-act=toggle]")?.focus({ preventScroll: true }), 30);
    kick();
  }
  function unfocus() { focus = null; want.target.copy(HOME.target); want.dist = 1 + 0.55 * explodeWant; fx.focus(null); hideCard(); kick(); }
  function toggle(fid) {
    const s = station.toggle(fid);
    const L = station.lifts.get(fid);
    if (focus === L || card.dataset.fid === fid) cardFor(L, card.classList.contains("pinned"));
    if (s?.k === 0) { card.classList.remove("shake"); void card.offsetWidth; card.classList.add("shake"); }
    syncKeys(); opts.onChange?.(station.summary); fx.select(station.bloom); kick();
  }
  function select(pid) { station.select(pid); fx.select(station.bloom); opts.onChange?.(station.summary); kick(); return station.summary; }

  canvas.addEventListener("pointerdown", (e) => { dragging = true; px = e.clientX; py = e.clientY; moved = 0; canvas.setPointerCapture(e.pointerId); canvas.classList.add("drag"); stopIdle(); });
  canvas.addEventListener("pointermove", (e) => {
    if (dragging) {
      const dx = e.clientX - px, dy = e.clientY - py; px = e.clientX; py = e.clientY; moved += Math.abs(dx) + Math.abs(dy);
      vYaw = -dx * 0.006; vPitch = dy * 0.004;
      want.yaw += vYaw; want.pitch = THREE.MathUtils.clamp(want.pitch + vPitch, 0.08, 1.1); kick(); return;
    }
    const h = pick(e);
    const L = h?.fid ? h : null;
    if (L !== hover) setHover(L);
    canvas.classList.toggle("hot", !!h);
  });
  const up = (e) => {
    if (!dragging) return; dragging = false; canvas.classList.remove("drag");
    if (moved < 6) {
      const h = pick(e);
      if (h?.fid) focusLift(h);
      else if (h?.platform) select(station.selected === h.platform ? null : h.platform);
      else if (focus) unfocus();
    }
    kick();
  };
  canvas.addEventListener("pointerup", up); canvas.addEventListener("pointercancel", up);
  canvas.addEventListener("pointerleave", () => { if (hover) setHover(null); });
  canvas.addEventListener("wheel", (e) => { e.preventDefault(); stopIdle(); want.dist = THREE.MathUtils.clamp(want.dist * Math.exp(e.deltaY * 0.0012), 0.35, 1.8); kick(); }, { passive: false });
  canvas.addEventListener("dblclick", () => { unfocus(); want.yaw = HOME.yaw; want.pitch = HOME.pitch; want.dist = 1 + 0.55 * explodeWant; kick(); });

  /* toolbar: explode / assemble and reset */
  let explodeWant = 0, explodeCur = 0;
  function setExplodeWant(v) {
    stopIdle(); explodeWant = v; if (!focus) want.dist = 1 + 0.55 * v;
    slider.value = String(v); bExplode.textContent = v > 0.5 ? "Assemble" : "Explode"; bExplode.setAttribute("aria-pressed", String(v > 0.5)); kick();
  }
  const bExplode = document.createElement("button"); bExplode.className = "llv-btn"; bExplode.type = "button"; bExplode.textContent = "Explode"; bExplode.setAttribute("aria-pressed", "false");
  bExplode.addEventListener("click", () => setExplodeWant(explodeWant > 0.5 ? 0 : 1));
  const slider = document.createElement("input"); slider.type = "range"; slider.min = "0"; slider.max = "1"; slider.step = "0.01"; slider.value = "0"; slider.setAttribute("aria-label", "Separate the floors");
  slider.addEventListener("input", () => setExplodeWant(Number(slider.value)));
  const bReset = document.createElement("button"); bReset.className = "llv-btn"; bReset.type = "button"; bReset.textContent = "Reset view";
  bReset.addEventListener("click", () => { unfocus(); want.yaw = HOME.yaw; want.pitch = HOME.pitch; want.dist = 1 + 0.55 * explodeWant; kick(); });
  tools.append(bExplode, slider, bReset);

  /* keyboard: one focusable proxy per lift; focus shows its card, Enter toggles it */
  const keyBtns = new Map();
  for (const L of station.lifts.values()) {
    const b = document.createElement("button"); b.type = "button";
    b.addEventListener("focus", () => { stopIdle(); setHover(L); cardFor(L, false); });
    b.addEventListener("blur", () => { if (!focus) setHover(null); });
    b.addEventListener("click", () => toggle(L.fid));
    keys.appendChild(b); keyBtns.set(L.fid, b);
  }
  function syncKeys() { for (const L of station.lifts.values()) { const b = keyBtns.get(L.fid); b.textContent = `Lift ${L.fid}: ${word(L).toLowerCase()} — press Enter to ${L.closed ? "reopen" : "close"}`; b.setAttribute("aria-pressed", String(L.closed)); } }
  syncKeys();
  addEventListener("keydown", (e) => { if (e.key === "Escape" && focus) unfocus(); });

  function magnet(scope) {
    if (reduced) return;
    scope.querySelectorAll?.(".llv-btn").forEach((b) => {
      b.onpointermove = (e) => { const r = b.getBoundingClientRect(); b.style.setProperty("--mx", `${((e.clientX - r.left) / r.width - 0.5) * 10}px`); b.style.setProperty("--my", `${((e.clientY - r.top) / r.height - 0.5) * 6}px`); };
      b.onpointerleave = () => { b.style.setProperty("--mx", "0px"); b.style.setProperty("--my", "0px"); };
    });
  }
  magnet(tools);

  /* render on demand with an adaptive pixel ratio */
  let running = false, last = performance.now(), slow = 0, fast = 0, dpr = renderer.getPixelRatio();
  function resize() {
    const w = root.clientWidth, h = root.clientHeight;
    renderer.setSize(w, h, false); fx.setSize(w, h);
    camera.aspect = w / h; camera.updateProjectionMatrix(); baseDist = fitDist(); kick();
  }
  function frame(now) {
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    let busy = false;
    if (turntable) {
      if (now - idleT0 > 5000) turntable = false; else { want.yaw += dt * 0.12; busy = true; }
    }
    if (!dragging && (Math.abs(vYaw) > 1e-4 || Math.abs(vPitch) > 1e-4)) { want.yaw += vYaw; want.pitch = THREE.MathUtils.clamp(want.pitch + vPitch, 0.08, 1.1); vYaw *= 0.88; vPitch *= 0.85; busy = true; }
    const k = reduced ? 1 : 1 - Math.exp(-dt * 6);
    for (const p of ["yaw", "pitch", "dist"]) { const d = want[p] - cam[p]; if (Math.abs(d) > 1e-4) { cam[p] += d * k; busy = true; } else cam[p] = want[p]; }
    if (cam.target.distanceTo(want.target) > 1e-3) { cam.target.lerp(want.target, k); busy = true; } else cam.target.copy(want.target);
    // keep the whole stack in frame while the floors separate
    if (!focus) want.target.y = HOME.target.y * (1 + 0.85 * explodeWant);
    const de = explodeWant - explodeCur;
    if (Math.abs(de) > 1e-3) { explodeCur += de * (reduced ? 1 : 1 - Math.exp(-dt * 4)); station.setExplode(explodeCur); fx.select(station.bloom); busy = true; }
    else if (explodeCur !== explodeWant) { explodeCur = explodeWant; station.setExplode(explodeCur); fx.select(station.bloom); }
    placeCamera();
    if (station.update(dt, reduced)) busy = true;
    if (fx.render(dt)) busy = true;
    placeCard();
    // adaptive resolution: drop to 1x on a slow GPU, climb back when it is quick
    const ms = performance.now() - now;
    if (ms > 28) { slow++; fast = 0; } else if (ms < 10) { fast++; slow = 0; }
    if (slow > 8 && dpr > 1) { dpr = 1; renderer.setPixelRatio(dpr); resize(); slow = 0; }
    else if (fast > 90 && dpr < Math.min(devicePixelRatio, 1.75)) { dpr = Math.min(devicePixelRatio, 1.75); renderer.setPixelRatio(dpr); resize(); fast = 0; }
    if (busy || dragging) requestAnimationFrame(frame); else running = false;
  }
  function kick() { if (!running) { running = true; last = performance.now(); requestAnimationFrame(frame); } }
  const ro = new ResizeObserver(resize); ro.observe(root);
  resize();
  fx.select(station.bloom);
  if (opts.select !== undefined) station.select(opts.select);
  else { const first = [...station.platforms.values()].find((P) => P.k === 1); if (first) station.select(first.id); }
  fx.select(station.bloom);
  if (reduced) { turntable = false; hint.style.opacity = "1"; }
  kick();

  return {
    station, camera, renderer,
    select,
    toggle(fid) { toggle(fid); return station.summary; },
    setClosed(f) { station.setClosed(f); syncKeys(); fx.select(station.bloom); kick(); return station.summary; },
    explode(v) { setExplodeWant(v); },
    hover(fid) { setHover(fid ? station.lifts.get(fid) : null); },
    focus(fid) { const L = station.lifts.get(fid); if (L) focusLift(L); },
    stopIdle,
    dispose() { ro.disconnect(); fx.composer.dispose(); renderer.dispose(); root.remove(); },
  };
}
