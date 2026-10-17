import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Edges, Environment, Html, Lightformer, OrbitControls, RoundedBox } from "@react-three/drei";
import { Bloom, EffectComposer, SMAA, Vignette } from "@react-three/postprocessing";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { StationGraph } from "../../api";
import { shortName } from "../../lib/stationLayout";
import { S } from "../../strings.en";
import { buildScene, cssColor, routePath, SLAB_DEPTH, type Scene, type Shaft } from "./station/geometry";
import "./station3d.css";

export type Station3DProps = {
  graph: StationGraph;                   // the station graph for one direction (board or exit)
  stationName: string;
  selected: string | null;               // selected platform id (node id == stop id)
  onPick?: (platformId: string) => void; // mouse pick; the platform table is the keyboard path
  routeEdges: Map<string, string>;       // edge id -> route label (A, B, C) for the selected platform
  lastLifts: Set<string>;                // facility ids that are the last lift for some platform
  pulse: Set<string>;                    // facility ids that just became the last lift (simulation)
  simClosed: Set<string>;                // facility ids closed only in the simulation
  flowKey: number;                       // change to replay the particle flow
  height?: number;                       // css px; default fills its container
};

const FLOW_MS = 4500;                    // WCAG 2.2.2: moving content stops within 5 s
const DOTS = 6, SPEED = 5.2;             // particles per route, world units per second
const DOLLY_MS = 1600;

/** Glow in the dark (values above 1 feed the bloom); in light mode, keep colours saturated instead of washing out. */
const glow = (c: THREE.Color, k: number, dark: boolean) => (dark ? c.clone().multiplyScalar(k) : c.clone());

type Palette = {
  dark: boolean; bg: THREE.Color; fg: THREE.Color; muted: THREE.Color; panel: THREE.Color;
  k0: THREE.Color; gold: THREE.Color; open: THREE.Color; sim: THREE.Color; routes: Record<string, THREE.Color>;
};

function usePalette(): Palette {
  const read = (): Palette => {
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    return {
      dark, bg: cssColor("--bg", dark ? "#0a0d12" : "#f4f6f9"), fg: cssColor("--fg"), muted: cssColor("--muted"),
      panel: cssColor("--panel"), k0: cssColor("--k0", "#ff6b5e"), gold: dark ? cssColor("--lastlift", "#ffd33d") : cssColor("--k1-fill", "#f5b83d"),
      open: new THREE.Color(dark ? "#9fd2ff" : "#2a7fd4"), sim: cssColor("--sim", "#c9a7ff"),
      routes: { A: cssColor("--route-a"), B: cssColor("--route-b"), C: cssColor("--route-c") },
    };
  };
  const [p, setP] = useState(read);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => setP(read());
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return p;
}

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** An exploded glass model of one station: a frosted slab per level, lifts as light shafts between the levels they
 *  join, every step-free link as a faint curve, and the selected platform's independent routes as glowing tubes
 *  with light flowing from start to end. Decorative for assistive technology: the platform, lift and route lists
 *  next to it carry the same facts in words. */
export function Station3D(props: Station3DProps) {
  const pal = usePalette();
  const scene = useMemo(() => buildScene(props.graph), [props.graph]);
  return (
    <div className="s3d" style={props.height ? { height: props.height } : undefined} aria-hidden="true">
      <Canvas dpr={[1, 2]} frameloop="demand" shadows={false}
              gl={{ antialias: false, powerPreference: "high-performance", alpha: false }}
              camera={{ fov: 34, near: 0.1, far: 600, position: [0, 10, 60] }}
              onCreated={({ gl }) => { gl.toneMapping = THREE.ACESFilmicToneMapping; gl.toneMappingExposure = pal.dark ? 1.05 : 1.0; }}>
        <color attach="background" args={[pal.bg]} />
        <fog attach="fog" args={[pal.bg, scene.size.length() * (pal.dark ? 1.3 : 2.4), scene.size.length() * (pal.dark ? 3 : 6)]} />
        <Environment resolution={256} frames={1}>
          <Lightformer form="rect" intensity={pal.dark ? 2.2 : 3} position={[0, 12, 6]} scale={[30, 6, 1]} color={pal.dark ? "#9fc4ff" : "#ffffff"} />
          <Lightformer form="rect" intensity={pal.dark ? 1.4 : 2} position={[-18, 4, -6]} rotation-y={Math.PI / 2} scale={[20, 4, 1]} color={pal.dark ? "#ffb35c" : "#fff1dc"} />
          <Lightformer form="ring" intensity={pal.dark ? 1.2 : 1.5} position={[16, 2, 10]} scale={6} color={pal.dark ? "#7fd1ff" : "#dbe9ff"} />
        </Environment>
        <Suspense fallback={null}>
          <StationModel {...props} scene={scene} pal={pal} />
        </Suspense>
        <EffectComposer multisampling={0} enableNormalPass={false}>
          <Bloom mipmapBlur intensity={pal.dark ? 1.15 : 0.55} luminanceThreshold={pal.dark ? 0.62 : 0.85} luminanceSmoothing={0.25} radius={0.72} />
          <Vignette eskil={false} offset={0.28} darkness={pal.dark ? 0.62 : 0.28} />
          <SMAA />
        </EffectComposer>
      </Canvas>
    </div>
  );
}

function StationModel(props: Station3DProps & { scene: Scene; pal: Palette }) {
  const { graph, scene, pal, selected, routeEdges, lastLifts, pulse, simClosed, flowKey, onPick, stationName } = props;
  const focus = routeEdges.size > 0;
  const byId = useMemo(() => new Map(graph.edges.map((e) => [e.id, e])), [graph]);
  const onRoute = useMemo(() => {
    const s = new Set<string>();
    for (const id of routeEdges.keys()) { const e = byId.get(id); if (e) { s.add(e.source); s.add(e.target); } }
    if (selected) s.add(selected);
    return s;
  }, [routeEdges, byId, selected]);
  const routes = useMemo(() => {
    const out: { label: string; path: THREE.CurvePath<THREE.Vector3> }[] = [];
    for (const r of graph.routes) {
      if (r.platform_id !== selected) continue;
      const path = routePath(scene, r.edge_ids, byId);
      if (path) out.push({ label: r.label, path });
    }
    return out;
  }, [graph, scene, byId, selected]);
  const [hover, setHover] = useState<string | null>(null);

  return (
    <group>
      <Wake />
      <Lights pal={pal} scene={scene} />
      <Rig scene={scene} selected={selected} />
      <Floor scene={scene} pal={pal} />
      <Slabs scene={scene} pal={pal} />
      <BaseLines scene={scene} pal={pal} focus={focus} simClosed={simClosed} />
      <Beads scene={scene} pal={pal} focus={focus} onRoute={onRoute} />
      <Street scene={scene} pal={pal} />
      {[...scene.shafts.values()].map((s) => (
        <LiftShaft key={s.id} shaft={s} pal={pal} dim={focus && !onRoute.has(s.id)}
                   state={simClosed.has(s.fid) ? "sim" : s.node.status === "closed" ? "closed"
                     : lastLifts.has(s.fid) ? "last" : "open"} pulse={pulse.has(s.fid)} />
      ))}
      {[...scene.nodes.values()].filter((n) => n.node.kind === "platform").map((n) => (
        <Platform key={n.node.id} at={n.p} w={Math.min(3.6, Math.max(1.4, n.w - 0.4))} pal={pal}
                  label={shortName(n.node.label, stationName)} selected={n.node.id === selected}
                  dim={focus && !onRoute.has(n.node.id)} hover={hover === n.node.id}
                  onHover={(h) => setHover(h ? n.node.id : null)} onPick={onPick ? () => onPick(n.node.id) : undefined} />
      ))}
      {routes.map((r, i) => (
        <RouteFlow key={`${selected}-${r.label}`} path={r.path} color={pal.routes[r.label] ?? pal.routes.A}
                   flowKey={flowKey} delay={i * 0.18} dark={pal.dark} />
      ))}
    </group>
  );
}

/* ---------- lights and camera ---------- */

/** On-demand rendering draws nothing until asked; redraw whenever the page becomes visible again. */
function Wake() {
  const { invalidate } = useThree();
  useEffect(() => {
    const on = () => invalidate(2);
    document.addEventListener("visibilitychange", on);
    window.addEventListener("focus", on);
    window.addEventListener("pageshow", on);
    return () => { document.removeEventListener("visibilitychange", on); window.removeEventListener("focus", on); window.removeEventListener("pageshow", on); };
  }, [invalidate]);
  return null;
}

function Lights({ pal, scene }: { pal: Palette; scene: Scene }) {
  return (
    <>
      <ambientLight intensity={pal.dark ? 0.35 : 0.9} />
      <hemisphereLight args={[pal.dark ? "#7fa8ff" : "#ffffff", pal.dark ? "#120a04" : "#c8ced8", pal.dark ? 0.55 : 0.7]} />
      <directionalLight position={[scene.width * 0.4, 30, 24]} intensity={pal.dark ? 1.1 : 1.6} color={pal.dark ? "#cfe3ff" : "#ffffff"} />
      <pointLight position={[-scene.width * 0.5, 6, 10]} intensity={pal.dark ? 40 : 10} distance={80} color={pal.dark ? "#ffb347" : "#ffd9a0"} />
    </>
  );
}

function Rig({ scene, selected }: { scene: Scene; selected: string | null }) {
  const controls = useRef<OrbitControlsImpl>(null);
  const { camera, invalidate, size } = useThree();
  const start = useRef(performance.now());
  const dollyDone = useRef(false);
  const target = useRef(scene.center.clone());

  // frame the whole model: distance from the larger of width and height, at a three-quarter view from above
  const frame = useMemo(() => {
    const aspect = size.width / Math.max(1, size.height);
    const vfov = ((camera as THREE.PerspectiveCamera).fov * Math.PI) / 180;
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect);
    const r = Math.hypot(scene.size.x * 0.5, scene.size.y * 0.5 + 1.2, scene.size.z * 0.35);   // flattened sphere: depth matters less
    const dist = (r / Math.sin(Math.min(vfov, hfov) / 2)) * 0.9;
    const dir = new THREE.Vector3(0.38, 0.3, 1).normalize();
    return { end: scene.center.clone().add(dir.clone().multiplyScalar(dist)), begin: scene.center.clone().add(dir.multiplyScalar(dist * 1.9)).add(new THREE.Vector3(0, dist * 0.35, 0)) };
  }, [scene, size.width, size.height, camera]);

  useEffect(() => {
    start.current = performance.now();
    dollyDone.current = reducedMotion();
    camera.position.copy(reducedMotion() ? frame.end : frame.begin);
    target.current.copy(scene.center);
    controls.current?.target.copy(scene.center);
    controls.current?.update();
    invalidate();
  }, [frame, scene, camera, invalidate]);

  useEffect(() => {                                    // ease the target toward the selected platform
    const n = selected ? scene.nodes.get(selected) : null;
    target.current.copy(n ? scene.center.clone().lerp(n.p, 0.3) : scene.center);
    invalidate();
  }, [selected, scene, invalidate]);

  useFrame((_, dt) => {
    const c = controls.current;
    if (!c) return;
    let moving = false;
    if (!dollyDone.current) {                           // finishes even if frames were skipped while hidden
      const t = Math.min(1, (performance.now() - start.current) / DOLLY_MS);
      camera.position.lerpVectors(frame.begin, frame.end, 1 - Math.pow(1 - t, 4));
      if (t >= 1) dollyDone.current = true;
      moving = true;
    }
    if (c.target.distanceTo(target.current) > 0.01) {
      c.target.lerp(target.current, reducedMotion() ? 1 : Math.min(1, dt * 3.2));
      moving = true;
    }
    c.update();
    if (moving) invalidate();
  });

  return (
    <OrbitControls ref={controls} makeDefault enableDamping dampingFactor={0.08} rotateSpeed={0.6} zoomSpeed={0.7}
                   minPolarAngle={Math.PI * 0.12} maxPolarAngle={Math.PI * 0.62}
                   minDistance={6} maxDistance={scene.size.length() * 3} enablePan />
  );
}

/* ---------- architecture ---------- */

function Floor({ scene, pal }: { scene: Scene; pal: Palette }) {
  const y = -(scene.rows - 1) * scene.gap - 2.2;
  const size = Math.ceil(Math.max(scene.width, 30) * 2.4);
  const grid = useMemo(() => {
    const g = new THREE.GridHelper(size, Math.round(size / 1.5), pal.dark ? 0x2a3442 : 0xb9c2ce, pal.dark ? 0x161c25 : 0xdde2e8);
    (g.material as THREE.Material).transparent = true;
    (g.material as THREE.Material).opacity = pal.dark ? 0.55 : 0.7;
    return g;
  }, [size, pal.dark]);
  useEffect(() => () => { grid.geometry.dispose(); (grid.material as THREE.Material).dispose(); }, [grid]);
  return (
    <group position={[scene.center.x, y, 0]}>
      <primitive object={grid} />
      <mesh rotation-x={-Math.PI / 2} position-y={-0.01}>
        <circleGeometry args={[size * 0.5, 64]} />
        <meshBasicMaterial color={pal.dark ? "#06080c" : "#e9edf2"} transparent opacity={0.6} />
      </mesh>
    </group>
  );
}

function Slabs({ scene, pal }: { scene: Scene; pal: Palette }) {
  const w = scene.width + 4;
  return (
    <group>
      {scene.bandKind.map((kind, i) => {
        const y = -i * scene.gap - 0.42;
        const isPlatforms = kind === "platform";
        return (
          <group key={i} position={[0, y, 0]}>
            <mesh renderOrder={-1}>
              <boxGeometry args={[w, 0.12, SLAB_DEPTH]} />
              <meshPhysicalMaterial color={pal.dark ? (isPlatforms ? "#2a4766" : "#1d2c3f") : (isPlatforms ? "#eaf2ff" : "#ffffff")}
                                    roughness={0.42} metalness={0} clearcoat={1} clearcoatRoughness={0.25}
                                    envMapIntensity={pal.dark ? 0.9 : 0.7} sheen={0.4} sheenColor={pal.dark ? "#6fa3e8" : "#ffffff"}
                                    transparent opacity={pal.dark ? 0.42 : 0.62} depthWrite={false} />
              <Edges threshold={15} color={pal.dark ? (isPlatforms ? "#5b8fd6" : "#3c5272") : "#9aa7b8"} />
            </mesh>
            <Html position={[-w / 2 + 0.2, 0.35, SLAB_DEPTH / 2]} center={false} zIndexRange={[10, 0]} className="s3d-level"
                  style={{ pointerEvents: "none" }}>
              <span>{S.xray.band[kind]}</span>
            </Html>
          </group>
        );
      })}
    </group>
  );
}

function BaseLines({ scene, pal, focus, simClosed }: { scene: Scene; pal: Palette; focus: boolean; simClosed: Set<string> }) {
  const geom = useMemo(() => {
    const pos: number[] = [], col: number[] = [];
    const base = pal.dark ? new THREE.Color("#8fa6c4") : new THREE.Color("#5a6a80");
    for (const e of scene.baseEdges) {
      const c = scene.edgeCurve(e);
      if (!c) continue;
      const colour = e.kind === "lift" && e.facility_id && simClosed.has(e.facility_id) ? pal.sim
        : e.kind === "lift" && e.status === "closed" ? pal.k0 : e.kind === "step" ? pal.muted : base;
      const pts = c.getPoints(e.kind === "lift" ? 2 : 16);
      for (let i = 0; i < pts.length - 1; i++) {
        pos.push(pts[i].x, pts[i].y, pts[i].z, pts[i + 1].x, pts[i + 1].y, pts[i + 1].z);
        col.push(colour.r, colour.g, colour.b, colour.r, colour.g, colour.b);
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
    return g;
  }, [scene, pal, simClosed]);
  useEffect(() => () => geom.dispose(), [geom]);
  return (
    <lineSegments geometry={geom}>
      <lineBasicMaterial vertexColors transparent opacity={focus ? 0.1 : pal.dark ? 0.55 : 0.6} depthWrite={false} />
    </lineSegments>
  );
}

function Beads({ scene, pal, focus, onRoute }: { scene: Scene; pal: Palette; focus: boolean; onRoute: Set<string> }) {
  const beads = useMemo(() => [...scene.nodes.values()].filter((n) => n.node.kind === "area" || n.node.kind === "gate"), [scene]);
  const posts = useMemo(() => [...scene.nodes.values()].filter((n) => n.node.kind === "entrance"), [scene]);
  const beadRef = useRef<THREE.InstancedMesh>(null);
  const postRef = useRef<THREE.InstancedMesh>(null);
  const capRef = useRef<THREE.InstancedMesh>(null);
  useEffect(() => {
    const m = new THREE.Matrix4();
    beads.forEach((b, i) => { m.makeTranslation(b.p.x, b.p.y, b.p.z); beadRef.current?.setMatrixAt(i, m); });
    posts.forEach((b, i) => {
      m.makeTranslation(b.p.x, b.p.y + 0.35, b.p.z); postRef.current?.setMatrixAt(i, m);
      m.makeTranslation(b.p.x, b.p.y + 0.8, b.p.z); capRef.current?.setMatrixAt(i, m);
    });
    for (const r of [beadRef, postRef, capRef]) if (r.current) r.current.instanceMatrix.needsUpdate = true;
  }, [beads, posts]);
  const hot = [...beads, ...posts].filter((b) => focus && onRoute.has(b.node.id));
  return (
    <group>
      <instancedMesh ref={beadRef} args={[undefined, undefined, Math.max(1, beads.length)]} count={beads.length} frustumCulled={false}>
        <sphereGeometry args={[0.13, 12, 12]} />
        <meshStandardMaterial color={pal.dark ? "#9db4d3" : "#4e5d72"} emissive={pal.dark ? "#3a5a85" : "#000000"}
                              emissiveIntensity={0.6} transparent opacity={focus ? 0.15 : 0.9} />
      </instancedMesh>
      <instancedMesh ref={postRef} args={[undefined, undefined, Math.max(1, posts.length)]} count={posts.length} frustumCulled={false}>
        <boxGeometry args={[0.16, 0.7, 0.16]} />
        <meshStandardMaterial color={pal.dark ? "#c9d6e8" : "#3f4b5c"} metalness={0.4} roughness={0.35} transparent opacity={focus ? 0.2 : 1} />
      </instancedMesh>
      <instancedMesh ref={capRef} args={[undefined, undefined, Math.max(1, posts.length)]} count={posts.length} frustumCulled={false}>
        <sphereGeometry args={[0.16, 14, 14]} />
        <meshBasicMaterial color={pal.dark ? "#cfe6ff" : "#2a7fd4"} toneMapped={false} transparent opacity={focus ? 0.2 : 1} />
      </instancedMesh>
      {hot.map((b) => (
        <mesh key={b.node.id} position={b.p}>
          <sphereGeometry args={[0.2, 16, 16]} />
          <meshBasicMaterial color={pal.dark ? "#ffffff" : "#10151c"} toneMapped={false} />
        </mesh>
      ))}
    </group>
  );
}

function Street({ scene, pal }: { scene: Scene; pal: Palette }) {
  const s = [...scene.nodes.values()].find((n) => n.node.kind === "street");
  if (!s) return null;
  return (
    <group position={s.p}>
      <mesh rotation-x={-Math.PI / 2} position-y={-0.3}>
        <ringGeometry args={[0.9, 1.25, 64]} />
        <meshBasicMaterial color={pal.dark ? "#d8ecff" : "#1d4f8f"} toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
      <mesh rotation-x={-Math.PI / 2} position-y={-0.32}>
        <circleGeometry args={[0.9, 64]} />
        <meshBasicMaterial color={pal.dark ? "#3d6fae" : "#cfe0f5"} transparent opacity={0.5} toneMapped={false} />
      </mesh>
      <mesh position-y={0.9}>
        <cylinderGeometry args={[0.04, 0.04, 2.4, 8]} />
        <meshBasicMaterial color={pal.dark ? "#d8ecff" : "#1d4f8f"} toneMapped={false} transparent opacity={0.5} />
      </mesh>
      <Html position={[0, 1.6, 0]} center className="s3d-tag s3d-street" style={{ pointerEvents: "none" }} zIndexRange={[20, 10]}>
        <span>{S.xray.street}</span>
      </Html>
    </group>
  );
}

/* ---------- lifts ---------- */

type LiftState = "open" | "closed" | "sim" | "last";

function LiftShaft({ shaft, pal, state, pulse, dim }: { shaft: Shaft;
  pal: Palette; state: LiftState; pulse: boolean; dim: boolean }) {
  const h = shaft.top - shaft.bottom;
  const mid = (shaft.top + shaft.bottom) / 2;
  const colour = state === "closed" ? pal.k0 : state === "sim" ? pal.sim : state === "last" ? pal.gold : pal.open;
  const glass = useRef<THREE.MeshStandardMaterial>(null);
  const core = useRef<THREE.MeshBasicMaterial>(null);
  const { invalidate } = useThree();
  const born = useRef(performance.now());
  useEffect(() => { born.current = performance.now(); invalidate(); }, [state, invalidate]);
  useFrame(() => {                                       // a closed lift flickers off once, then stays dark
    if (state !== "closed" || reducedMotion() || !core.current) return;
    const t = (performance.now() - born.current) / 1000;
    if (t > 1.2) { core.current.opacity = dim ? 0.08 : 0.22; return; }
    core.current.opacity = (Math.sin(t * 40) > 0.2 ? 0.9 : 0.15) * (1 - t / 1.4);
    invalidate();
  });
  const coreOpacity = dim ? 0.12 : state === "closed" ? 0.22 : 0.95;
  const intensity = state === "last" ? 2.6 : state === "open" ? 1.6 : state === "sim" ? 2 : 0.6;
  return (
    <group position={[shaft.x, mid, shaft.z]}>
      <mesh>
        <boxGeometry args={[0.95, h, 0.95]} />
        <meshStandardMaterial ref={glass} color={colour} emissive={colour} emissiveIntensity={dim ? 0.05 : state === "closed" ? 0.15 : 0.35}
                              transparent opacity={dim ? 0.06 : state === "closed" ? 0.12 : pal.dark ? 0.2 : 0.38} roughness={0.15} metalness={0.2}
                              depthWrite={false} />
        <Edges color={colour} threshold={10} />
      </mesh>
      <mesh>
        <boxGeometry args={pal.dark ? [0.16, h - 0.2, 0.16] : [0.3, h - 0.2, 0.3]} />
        <meshBasicMaterial ref={core} color={glow(colour, intensity, pal.dark)} toneMapped={false} transparent opacity={coreOpacity} />
      </mesh>
      {state === "closed" && !dim && <ClosedBands h={h} colour={pal.k0} />}
      {pulse && <Shockwave colour={pal.gold} y={0} />}
      <Html position={[shaft.stagger === 2 ? 0.6 : shaft.stagger === 1 ? -0.6 : 0, h / 2 + 0.55 + shaft.stagger * 1.25, 0]} center className={`s3d-tag s3d-lift s3d-${state} ${dim ? "s3d-dim" : ""}`}
            style={{ pointerEvents: "none" }} zIndexRange={[20, 10]}>
        <span>{shaft.fid}</span>
      </Html>
    </group>
  );
}

function ClosedBands({ h, colour }: { h: number; colour: THREE.Color }) {
  const n = Math.max(2, Math.floor(h / 0.9));
  return (
    <group>
      {Array.from({ length: n }, (_, i) => (
        <mesh key={i} position-y={-h / 2 + (i + 0.5) * (h / n)} rotation-z={Math.PI / 4}>
          <boxGeometry args={[1.25, 0.06, 0.98]} />
          <meshBasicMaterial color={colour} toneMapped={false} transparent opacity={0.75} />
        </mesh>
      ))}
    </group>
  );
}

function Shockwave({ colour, y }: { colour: THREE.Color; y: number }) {
  const rings = useRef<THREE.Mesh[]>([]);
  const born = useRef(performance.now());
  const { invalidate } = useThree();
  useEffect(() => { born.current = performance.now(); invalidate(); }, [invalidate]);
  useFrame(() => {
    if (reducedMotion()) return;
    const t = (performance.now() - born.current) / 1000;
    rings.current.forEach((m, i) => {
      const k = t - i * 0.35;
      const cycle = k - Math.floor(k);
      const live = k >= 0 && k < 3;                       // three pulses each, then stop
      m.visible = live;
      if (!live) return;
      const s = 0.6 + cycle * 3.4;
      m.scale.set(s, s, s);
      (m.material as THREE.MeshBasicMaterial).opacity = (1 - cycle) * 0.9;
    });
    if (t < 3.8) invalidate();
  });
  return (
    <group position-y={y}>
      {[0, 1].map((i) => (
        <mesh key={i} ref={(m) => { if (m) rings.current[i] = m; }} rotation-x={-Math.PI / 2}>
          <torusGeometry args={[1, 0.05, 8, 64]} />
          <meshBasicMaterial color={glow(colour, 2.2, true)} toneMapped={false} transparent opacity={0.8} />
        </mesh>
      ))}
    </group>
  );
}

/* ---------- platforms ---------- */

function Platform({ at, w, pal, label, selected, dim, hover, onHover, onPick }: {
  at: THREE.Vector3; w: number; pal: Palette; label: string; selected: boolean; dim: boolean; hover: boolean;
  onHover: (h: boolean) => void; onPick?: () => void;
}) {
  const accent = pal.routes.A;
  const lit = selected || hover;
  return (
    <group position={at}>
      <RoundedBox args={[w, 0.5, 1.5]} radius={0.14} smoothness={4}
                  onClick={(e) => { e.stopPropagation(); onPick?.(); }}
                  onPointerOver={(e) => { e.stopPropagation(); onHover(true); document.body.style.cursor = onPick ? "pointer" : ""; }}
                  onPointerOut={() => { onHover(false); document.body.style.cursor = ""; }}>
        <meshPhysicalMaterial color={selected ? accent : pal.dark ? "#5d86b8" : "#dce6f3"} roughness={0.18} metalness={0.05}
                              clearcoat={1} clearcoatRoughness={0.1} envMapIntensity={1.2} transparent opacity={dim ? 0.16 : 0.9}
                              emissive={selected ? accent : pal.dark ? "#2b5a92" : "#000000"} emissiveIntensity={selected ? 1.1 : hover ? 0.75 : 0.32} />
        <Edges color={selected ? accent : pal.dark ? "#7aa6dd" : "#7f8da0"} threshold={20} />
      </RoundedBox>
      {selected && (
        <mesh position-y={-0.27} rotation-x={-Math.PI / 2}>
          <planeGeometry args={[w + 0.9, 2.3]} />
          <meshBasicMaterial color={glow(accent, 1.6, pal.dark)} toneMapped={false} transparent opacity={0.22} />
        </mesh>
      )}
      <Html position={[0, 0.65, 0.4]} center className={`s3d-tag s3d-platform ${lit ? "s3d-lit" : ""} ${dim ? "s3d-dim" : ""}`}
            style={{ pointerEvents: "none" }} zIndexRange={[30, 10]}>
        <span>{label}</span>
      </Html>
    </group>
  );
}

/* ---------- routes ---------- */

function RouteFlow({ path, color, flowKey, delay, dark }: { path: THREE.CurvePath<THREE.Vector3>; color: THREE.Color; flowKey: number; delay: number; dark: boolean }) {
  const segs = Math.max(48, path.curves.length * 24);
  const tube = useMemo(() => new THREE.TubeGeometry(path as unknown as THREE.Curve<THREE.Vector3>, segs, 0.11, 10, false), [path, segs]);
  const halo = useMemo(() => new THREE.TubeGeometry(path as unknown as THREE.Curve<THREE.Vector3>, segs, 0.32, 10, false), [path, segs]);
  useEffect(() => () => { tube.dispose(); halo.dispose(); }, [tube, halo]);
  const length = useMemo(() => path.getLength(), [path]);
  const dots = useRef<(THREE.Group | null)[]>([]);
  const start = useRef(performance.now());
  const grow = useRef<THREE.MeshBasicMaterial>(null);
  const { invalidate } = useThree();
  const reduced = reducedMotion();
  useEffect(() => { start.current = performance.now(); invalidate(); }, [flowKey, path, invalidate]);
  useFrame(() => {
    const t = (performance.now() - start.current) / 1000 - delay;
    const live = !reduced && t >= 0 && t * 1000 < FLOW_MS;
    const fade = Math.max(0, Math.min(1, (FLOW_MS / 1000 - t) / 0.6));
    dots.current.forEach((g, j) => {
      if (!g) return;
      g.visible = live;
      if (!live) return;
      g.position.copy(path.getPointAt((((t * SPEED) / length) + j / DOTS) % 1));
      const s = 0.55 + 0.45 * fade;
      g.scale.setScalar(s);
    });
    if (grow.current) grow.current.opacity = reduced ? 0.95 : Math.min(0.95, Math.max(0, t + delay) * 2.2);
    if (!reduced && t * 1000 < FLOW_MS + 200) invalidate();
  });
  const hot = dark ? color.clone().lerp(new THREE.Color("#ffffff"), 0.55).multiplyScalar(2.4) : color.clone().multiplyScalar(0.85);
  return (
    <group>
      <mesh geometry={halo}>
        <meshBasicMaterial color={color} toneMapped={false} transparent opacity={0.12} depthWrite={false} />
      </mesh>
      <mesh geometry={tube}>
        <meshBasicMaterial ref={grow} color={glow(color, 1.5, dark)} toneMapped={false} transparent opacity={reduced ? 0.95 : 0} />
      </mesh>
      {!reduced && Array.from({ length: DOTS }, (_, j) => (
        <group key={j} ref={(g) => { dots.current[j] = g; }} visible={false}>
          <mesh renderOrder={5}>
            <sphereGeometry args={[0.3, 16, 16]} />
            <meshBasicMaterial color={hot} toneMapped={false} depthTest={false} />
          </mesh>
          <mesh renderOrder={4}>
            <sphereGeometry args={[0.8, 16, 16]} />
            <meshBasicMaterial color={color} toneMapped={false} transparent opacity={0.25} depthWrite={false} depthTest={false} />
          </mesh>
        </group>
      ))}
      {reduced && <Arrowheads path={path} color={color} dark={dark} />}
    </group>
  );
}

function Arrowheads({ path, color, dark }: { path: THREE.CurvePath<THREE.Vector3>; color: THREE.Color; dark: boolean }) {
  const marks = useMemo(() => {
    const n = Math.max(3, Math.round(path.getLength() / 4));
    return Array.from({ length: n }, (_, i) => {
      const u = (i + 0.5) / n;
      const p = path.getPointAt(u), t = path.getTangentAt(u).normalize();
      const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), t);
      return { p, q };
    });
  }, [path]);
  return (
    <group>
      {marks.map((m, i) => (
        <mesh key={i} position={m.p} quaternion={m.q}>
          <coneGeometry args={[0.26, 0.6, 12]} />
          <meshBasicMaterial color={glow(color, 1.8, dark)} toneMapped={false} />
        </mesh>
      ))}
    </group>
  );
}

