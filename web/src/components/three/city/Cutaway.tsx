import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import { Edges, Html, Line } from "@react-three/drei";
import { layoutStation } from "../../../lib/stationLayout";
import { smooth, story, type CityData, type Palette } from "./core";

const W = 9, ROW = 1.55, DOTS = 14;
const ZK = { street: 0, entrance: -1.7, gate: -0.9, area: -0.2, lift: 0.9, platform: 1.9 } as const;

/** The dive's destination: the real station graph (same arrangement as the plan drawing) as an underground
 *  cutaway. Each level from the street down is a glass slab; lifts are light shafts (gold = now the last lift,
 *  red = closed); the last lift's route glows and carries light up to the street as the reader scrolls. */
export function Cutaway({ data, pal, labels }: { data: CityData; pal: Palette; labels: { street: string; lift: (f: string) => string } }) {
  const f = data.focus;
  const g = data.bundle?.graph.exit;
  const built = useMemo(() => {
    if (!g || !f) return null;
    const lay = layoutStation(g);
    const pos = new Map<string, THREE.Vector3>();
    lay.placed.forEach((p, id) => {
      const jitter = p.node.kind === "area" || p.node.kind === "gate" ? ((p.t * 97) % 1 - 0.5) * 0.9 : 0;
      pos.set(id, new THREE.Vector3((p.t - 0.5) * W, -p.row * ROW, ZK[p.node.kind] + jitter));
    });
    const rows = lay.rows.length;
    // a lift spans from its highest to its lowest neighbour
    const span = new Map<string, [number, number]>();
    for (const e of g.edges) {
      for (const [a, b] of [[e.source, e.target], [e.target, e.source]]) {
        const n = lay.placed.get(a)?.node;
        if (n?.kind !== "lift") continue;
        const y = pos.get(b)?.y;
        if (y === undefined) continue;
        const s = span.get(a) ?? [pos.get(a)!.y, pos.get(a)!.y];
        span.set(a, [Math.min(s[0], y), Math.max(s[1], y)]);
      }
    }
    const walk = g.edges.filter((e) => e.kind !== "lift" && pos.has(e.source) && pos.has(e.target))
      .flatMap((e) => [pos.get(e.source)!.toArray(), pos.get(e.target)!.toArray()]) as [number, number, number][];
    // the route through the lift that is now the last one
    const route = g.routes.find((r) => r.lifts.includes(f.fid)) ?? g.routes[0];
    const byId = new Map(g.edges.map((e) => [e.id, e]));
    const rpts: THREE.Vector3[] = [];
    for (const id of route?.edge_ids ?? []) {
      const e = byId.get(id);
      if (!e) continue;
      if (!rpts.length && pos.has(e.source)) rpts.push(pos.get(e.source)!.clone());
      if (pos.has(e.target)) rpts.push(pos.get(e.target)!.clone());
    }
    const curve = rpts.length > 1 ? new THREE.CatmullRomCurve3(rpts, false, "centripetal", 0.3) : null;
    return { lay, pos, rows, span, walk, curve };
  }, [g, f]);

  const group = useRef<THREE.Group>(null);
  const dots = useRef<THREE.InstancedMesh>(null);
  const tags = useRef(new Set<HTMLDivElement>());
  const tmp = useMemo(() => new THREE.Object3D(), []);
  useEffect(() => () => { /* geometries and materials are declarative and disposed by the renderer */ }, []);

  useFrame(({ camera }) => {
    if (!group.current || !built) return;
    const k = story.reduced ? (story.active === 4 ? 1 : 0) : smooth(3.4, 3.85, story.pSmooth);
    // kept in the scene (collapsed) so its shaders compile at load, not mid-scroll
    group.current.scale.setScalar(k > 0.01 ? 0.85 + 0.15 * k : 0.0001);
    const under = camera.position.y < 0.3 ? 1 : 0;
    tags.current.forEach((t) => t && (t.style.opacity = String(k * under)));
    if (dots.current && built.curve) {
      const runs = !story.reduced;
      for (let i = 0; i < DOTS; i++) {
        // light travels from the platform up to the street; position follows scroll and the motion clock
        const u = runs ? ((i / DOTS) + story.t * 0.12 + story.pSmooth * 0.35) % 1 : i / DOTS;
        tmp.position.copy(built.curve.getPointAt(u));
        tmp.scale.setScalar(0.09 + 0.05 * Math.sin(u * Math.PI));
        tmp.updateMatrix();
        dots.current.setMatrixAt(i, tmp.matrix);
      }
      dots.current.instanceMatrix.needsUpdate = true;
    }
  });

  if (!f || !g || !built) return null;
  const { lay, pos, rows, span, walk, curve } = built;
  const kColour = (k: number | null | undefined) =>
    k === 0 ? pal.lost : k === 1 ? pal.one : typeof k === "number" ? pal.many : pal.grade;
  return (
    <group ref={group} position={[f.station.x, -0.6, f.station.z]} scale={0.0001}>
      {Array.from({ length: rows - 1 }, (_, r) => r + 1).map((r) => (
        <mesh key={r} position={[0, -r * ROW - 0.08, 0.1]}>
          <boxGeometry args={[W + 1.6, 0.05, 5.2]} />
          <meshPhysicalMaterial color="#9db4ff" transparent opacity={0.07} roughness={0.15} metalness={0.1} depthWrite={false} />
          <Edges color={new THREE.Color(0.45, 0.62, 1.25)} />
        </mesh>
      ))}
      <Line points={walk} segments lineWidth={0.9} color={new THREE.Color(0.55, 0.7, 1.1)} transparent opacity={0.35} toneMapped={false} />
      {curve && <Line points={curve.getPoints(160)} lineWidth={3.2} color={new THREE.Color(...pal.gold)} toneMapped={false} />}
      {curve && (
        <instancedMesh ref={dots} args={[undefined, undefined, DOTS]}>
          <sphereGeometry args={[1, 12, 10]} />
          <meshBasicMaterial color={new THREE.Color(...pal.gold).multiplyScalar(1.4)} toneMapped={false} />
        </instancedMesh>
      )}
      {[...lay.placed.values()].map(({ node }, idx) => {
        const p = pos.get(node.id)!;
        if (node.kind === "lift") {
          const [y0, y1] = span.get(node.id) ?? [p.y - ROW / 2, p.y + ROW / 2];
          const last = node.facility_id === f.fid;
          const closed = node.status === "closed" || f.closed.includes(node.facility_id ?? "");
          const c = last ? pal.gold : closed ? pal.lost : [0.9, 1.1, 1.5];
          const h = Math.max(0.6, y1 - y0);
          return (
            <group key={node.id} position={[p.x, (y0 + y1) / 2, p.z]}>
              <mesh>
                <cylinderGeometry args={[last ? 0.2 : 0.14, last ? 0.2 : 0.14, h, 16]} />
                <meshBasicMaterial color={new THREE.Color(...c).multiplyScalar(closed ? 0.6 : 1)} toneMapped={false}
                                   transparent opacity={closed ? 0.55 : 1} />
              </mesh>
              <mesh>
                <boxGeometry args={[0.85, h + 0.2, 0.85]} />
                <meshBasicMaterial transparent opacity={0.05} color={new THREE.Color(...c)} depthWrite={false} />
                <Edges color={new THREE.Color(...c).multiplyScalar(0.7)} />
              </mesh>
              <Html position={[0, h / 2 + 0.45 + (idx % 2) * 0.55, 0]} center zIndexRange={[5, 0]} pointerEvents="none">
                <div ref={(el) => { if (el) tags.current.add(el); }} className={`ci-tag ${last ? "ci-tag-goldbox" : closed ? "ci-tag-k0box" : ""}`} style={{ opacity: 0 }}>
                  {labels.lift(node.facility_id ?? "")}
                </div>
              </Html>
            </group>
          );
        }
        if (node.kind === "platform") {
          const c = kColour(node.k_exit);
          return (
            <mesh key={node.id} position={p}>
              <boxGeometry args={[Math.min(1.5, (lay.placed.get(node.id)!.w * W) * 0.8), 0.1, 0.42]} />
              <meshBasicMaterial color={new THREE.Color(...c)} toneMapped={false} />
            </mesh>
          );
        }
        if (node.kind === "street") {
          return (
            <group key={node.id} position={p}>
              <mesh><sphereGeometry args={[0.22, 16, 12]} /><meshBasicMaterial color={new THREE.Color(1.6, 1.6, 1.7)} toneMapped={false} /></mesh>
              <Html position={[0, 0.6, 0]} center zIndexRange={[5, 0]} pointerEvents="none">
                <div ref={(el) => { if (el) tags.current.add(el); }} className="ci-tag" style={{ opacity: 0 }}>{labels.street}</div>
              </Html>
            </group>
          );
        }
        return (
          <mesh key={node.id} position={p}>
            {node.kind === "entrance" ? <boxGeometry args={[0.22, 0.22, 0.22]} /> : <sphereGeometry args={[0.06, 8, 6]} />}
            <meshBasicMaterial color={new THREE.Color(0.8, 0.95, 1.3)} toneMapped={false} />
          </mesh>
        );
      })}
    </group>
  );
}
