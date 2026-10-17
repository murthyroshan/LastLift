import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import { clamp, smooth, story, type CityData, type CityStation, type Palette } from "./core";

const tmp = new THREE.Object3D();
const col = new THREE.Color();

/** Vertical fade for the light pillars: bright at the base, dissolving upward. */
function fadeTexture() {
  const c = document.createElement("canvas");
  c.width = 4; c.height = 128;
  const g = c.getContext("2d")!;
  const grd = g.createLinearGradient(0, 128, 0, 0);
  grd.addColorStop(0, "#fff"); grd.addColorStop(0.55, "#777"); grd.addColorStop(1, "#000");
  g.fillStyle = grd; g.fillRect(0, 0, 4, 128);
  const t = new THREE.CanvasTexture(c);
  return t;
}

/** A soft round glow sprite. */
export function glowTexture(size = 128) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  const grd = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  grd.addColorStop(0, "rgba(255,255,255,1)"); grd.addColorStop(0.2, "rgba(255,255,255,0.65)");
  grd.addColorStop(0.5, "rgba(255,255,255,0.14)"); grd.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grd; g.fillRect(0, 0, size, size);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

const stateColour = (s: CityStation, pal: Palette) =>
  !s.data ? pal.none : s.lost > 0 || s.now === "lost" ? pal.lost : s.single > 0 ? pal.one : s.now === "many" ? pal.many : pal.grade;

export function Network({ data, pal }: { data: CityData; pal: Palette }) {
  // ---------------------------------------------------------------- rails
  const rails = useMemo(() => data.links.filter((l) => l.rail).flatMap((l) =>
    [[l.a.x, 0.05, l.a.z], [l.b.x, 0.05, l.b.z]] as [number, number, number][]), [data]);
  const buses = useMemo(() => data.links.filter((l) => !l.rail).flatMap((l) =>
    [[l.a.x, 0.04, l.a.z], [l.b.x, 0.04, l.b.z]] as [number, number, number][]), [data]);
  const trains = useRef<any>(null);

  // ---------------------------------------------------------------- stations (instanced)
  const points = useRef<THREE.InstancedMesh>(null);
  const halos = useRef<THREE.InstancedMesh>(null);
  const glow = useMemo(() => glowTexture(), []);
  useLayoutEffect(() => {
    const m = points.current, h = halos.current;
    if (!m || !h) return;
    data.stations.forEach((s, i) => {
      const r = s.data ? 0.22 : 0.07;
      tmp.position.set(s.x, 0.12, s.z); tmp.scale.setScalar(r); tmp.rotation.set(0, 0, 0); tmp.updateMatrix();
      m.setMatrixAt(i, tmp.matrix);
      m.setColorAt(i, col.setRGB(...stateColour(s, pal)));
      tmp.position.set(s.x, 0.06, s.z); tmp.rotation.set(-Math.PI / 2, 0, 0); tmp.scale.setScalar(s.data ? 2.2 : 0.0001); tmp.updateMatrix();
      h.setMatrixAt(i, tmp.matrix);
      const [r0, g0, b0] = stateColour(s, pal);
      h.setColorAt(i, col.setRGB(r0 * 0.22, g0 * 0.22, b0 * 0.22));
    });
    m.instanceMatrix.needsUpdate = true; h.instanceMatrix.needsUpdate = true;
    if (m.instanceColor) m.instanceColor.needsUpdate = true;
    if (h.instanceColor) h.instanceColor.needsUpdate = true;
  }, [data, pal]);

  // ---------------------------------------------------------------- pillars: platforms hanging on one lift
  const pillarData = useMemo(() => {
    const ps = data.stations.filter((s) => s.data && (s.single > 0 || s.lost > 0));
    const maxD = Math.max(...ps.map((s) => Math.hypot(s.x, s.z)));
    return ps.map((s) => ({ s, h: 1.2 + (s.single + 2 * s.lost) * 1.15, delay: Math.hypot(s.x, s.z) / maxD }));
  }, [data]);
  const beams = useRef<THREE.InstancedMesh>(null);
  const cores = useRef<THREE.InstancedMesh>(null);
  const fade = useMemo(() => fadeTexture(), []);
  useLayoutEffect(() => {
    pillarData.forEach((p, i) => {
      const c = p.s.lost > 0 ? pal.lost : pal.one;
      beams.current?.setColorAt(i, col.setRGB(c[0] * 0.38, c[1] * 0.38, c[2] * 0.38));
      cores.current?.setColorAt(i, col.setRGB(c[0] * 0.75, c[1] * 0.75, c[2] * 0.75));
    });
    if (beams.current?.instanceColor) beams.current.instanceColor.needsUpdate = true;
    if (cores.current?.instanceColor) cores.current.instanceColor.needsUpdate = true;
  }, [pillarData, pal]);
  useEffect(() => () => { glow.dispose(); fade.dispose(); }, [glow, fade]);

  useFrame(() => {
    const p = story.pSmooth;
    // pillars stand low at first, rise across the city in step three (staggered outward), sink for the dive
    const baseRise = story.reduced ? (story.active >= 2 ? 1 : 0.32) : 0.32 + 0.68 * smooth(1.35, 2.05, p);
    const sink = 1 - smooth(3.35, 3.85, p) * 0.75;
    pillarData.forEach((d, i) => {
      const local = story.reduced ? baseRise : clamp(0.32 + 0.68 * smooth(1.35 + d.delay * 0.45, 1.75 + d.delay * 0.45, p));
      const h = Math.max(0.02, d.h * local * sink);
      tmp.rotation.set(0, 0, 0);
      tmp.position.set(d.s.x, h / 2, d.s.z); tmp.scale.set(1, h, 1); tmp.updateMatrix();
      beams.current?.setMatrixAt(i, tmp.matrix);
      tmp.scale.set(0.38, h, 0.38); tmp.updateMatrix();
      cores.current?.setMatrixAt(i, tmp.matrix);
    });
    if (beams.current) beams.current.instanceMatrix.needsUpdate = true;
    if (cores.current) cores.current.instanceMatrix.needsUpdate = true;
    // step two is about one station: everything else steps back
    const near1 = 1 - clamp(Math.abs(p - 1) / 0.7);
    const near3 = 1 - clamp(Math.abs(p - 3) / 0.7);
    const dimK = 1 - 0.82 * near1 - 0.5 * near3;
    for (const m of [beams.current, cores.current, halos.current]) {
      const mat = m?.material as THREE.MeshBasicMaterial | undefined;
      if (mat) mat.opacity = dimK;
    }
    const pm = points.current?.material as THREE.MeshBasicMaterial | undefined;
    if (pm) pm.opacity = 1 - 0.75 * near1;
    // train lights crawl along the rails while the motion clock runs
    if (trains.current?.material) trains.current.material.dashOffset = -story.t * 0.9;
  });

  return (
    <group>
      <Line points={buses} segments lineWidth={0.6} color={new THREE.Color(...pal.rail).multiplyScalar(0.25)}
            transparent opacity={0.45} toneMapped={false} />
      <Line points={rails} segments lineWidth={1.4} color={new THREE.Color(...pal.rail).multiplyScalar(0.6)}
            transparent opacity={0.85} toneMapped={false} />
      <Line ref={trains} points={rails} segments lineWidth={2.2} color={new THREE.Color(...pal.rail).multiplyScalar(1.6)}
            dashed dashSize={0.35} gapSize={3.2} transparent opacity={0.9} toneMapped={false} />

      <instancedMesh ref={halos} args={[undefined, undefined, data.stations.length]} renderOrder={3}>
        <planeGeometry args={[1, 1]} />
        <meshBasicMaterial map={glow} transparent blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </instancedMesh>
      <instancedMesh ref={points} args={[undefined, undefined, data.stations.length]}>
        <sphereGeometry args={[1, 16, 12]} />
        <meshBasicMaterial toneMapped={false} transparent depthWrite={false} />
      </instancedMesh>

      <instancedMesh ref={beams} args={[undefined, undefined, pillarData.length]} renderOrder={4}>
        <cylinderGeometry args={[0.42, 0.42, 1, 20, 1, true]} />
        <meshBasicMaterial alphaMap={fade} transparent blending={THREE.AdditiveBlending} depthWrite={false}
                           side={THREE.DoubleSide} toneMapped={false} />
      </instancedMesh>
      <instancedMesh ref={cores} args={[undefined, undefined, pillarData.length]} renderOrder={5}>
        <cylinderGeometry args={[0.42, 0.42, 1, 12, 1, true]} />
        <meshBasicMaterial alphaMap={fade} transparent blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </instancedMesh>
    </group>
  );
}
