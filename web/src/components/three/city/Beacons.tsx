import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import { clamp, smooth, story, type CityData, type Palette } from "./core";
import { glowTexture } from "./Network";

/** Step two: the station where one lift is closed and another just became the last one.
 *  Three red pulses for the closure (only after the reader scrolls there; never looping), and a gold flare and
 *  beam for the lift that now carries everyone alone. */
export function Beacons({ data, pal, labels }: { data: CityData; pal: Palette; labels: { closed: string; last: string } }) {
  const f = data.focus;
  const rings = useRef<THREE.Mesh[]>([]);
  const flare = useRef<THREE.Sprite>(null);
  const beam = useRef<THREE.Mesh>(null);
  const tag = useRef<HTMLDivElement>(null);
  const tag2 = useRef<HTMLDivElement>(null);
  const glow = useMemo(() => glowTexture(256), []);
  useEffect(() => () => glow.dispose(), [glow]);

  useFrame(() => {
    if (!f) return;
    const near = 1 - clamp(Math.abs(story.pSmooth - 1) / 0.75);          // 1 at step two, 0 a step away
    const shown = Math.max(near, smooth(3.3, 3.7, story.pSmooth));       // and again for the dive
    const since = story.t - story.enteredStep[1];
    rings.current.forEach((m, i) => {
      if (!m) return;
      const ph = since - i * 0.33;
      const live = !story.reduced && ph > 0 && ph < 3 && near > 0.2;
      const k = live ? (ph % 1) : 0;
      m.scale.setScalar(live ? 0.6 + k * 5.5 : 0.0001);
      (m.material as THREE.MeshBasicMaterial).opacity = (1 - k) * 0.9 * near;
    });
    const glowK = shown * (story.reduced ? 1 : 0.85 + 0.15 * Math.sin(story.t * 3));
    if (flare.current) { flare.current.material.opacity = glowK * 0.8; flare.current.scale.setScalar(1.6 + 1.8 * shown); }
    if (beam.current) {
      beam.current.scale.set(1, 0.01 + 14 * shown, 1);
      beam.current.position.y = (0.01 + 14 * shown) / 2;
      (beam.current.material as THREE.MeshBasicMaterial).opacity = shown * 0.55;
    }
    if (tag.current) tag.current.style.opacity = String(near);
    if (tag2.current) tag2.current.style.opacity = String(near);
  });

  if (!f) return null;
  const { x, z } = f.station;
  return (
    <group position={[x, 0, z]}>
      {[0, 1, 2].map((i) => (
        <mesh key={i} ref={(m) => { if (m) rings.current[i] = m; }} rotation-x={-Math.PI / 2} position-y={0.08} scale={0.0001}>
          <ringGeometry args={[0.92, 1, 64]} />
          <meshBasicMaterial color={new THREE.Color(...pal.lost)} transparent depthWrite={false} toneMapped={false} />
        </mesh>
      ))}
      <sprite ref={flare} position={[0, 0.4, 0]}>
        <spriteMaterial map={glow} color={new THREE.Color(...pal.gold)} transparent depthWrite={false}
                        blending={THREE.AdditiveBlending} toneMapped={false} opacity={0} />
      </sprite>
      <mesh ref={beam}>
        <cylinderGeometry args={[0.03, 0.12, 1, 16, 1, true]} />
        <meshBasicMaterial color={new THREE.Color(...pal.gold)} transparent blending={THREE.AdditiveBlending}
                           depthWrite={false} toneMapped={false} opacity={0} />
      </mesh>
      <Html position={[0, 2.6, 0]} center zIndexRange={[5, 0]} pointerEvents="none">
        <div ref={tag} className="ci-tag ci-tag-k0box" style={{ opacity: 0 }}>{labels.closed}</div>
      </Html>
      <Html position={[0, 1.5, 0]} center zIndexRange={[5, 0]} pointerEvents="none">
        <div ref={tag2} className="ci-tag ci-tag-goldbox" style={{ opacity: 0 }}>{labels.last}</div>
      </Html>
    </group>
  );
}

/** Step four: every station-to-station journey that one lift alone carries, drawn as arcs that grow out from its
 *  station as the reader scrolls (one draw call; the growth is tied to scroll, not to time). */
export function Arcs({ data, pal, label }: { data: CityData; pal: Palette; label: string }) {
  const a = data.arc;
  const SEG = 48;
  const { geom, heads } = useMemo(() => {
    const g = new THREE.BufferGeometry();
    if (!a) return { geom: g, heads: [] as THREE.Vector3[][] };
    const pos: number[] = [], prog: number[] = [], seed: number[] = [];
    const curves: THREE.Vector3[][] = [];
    a.targets.forEach((t, k) => {
      const from = new THREE.Vector3(a.station.x, 0.15, a.station.z), to = new THREE.Vector3(t.x, 0.15, t.z);
      const d = from.distanceTo(to);
      const mid = from.clone().lerp(to, 0.5).setY(1.5 + d * 0.45);
      const curve = new THREE.QuadraticBezierCurve3(from, mid, to);
      const pts = curve.getPoints(SEG);
      curves.push(pts);
      const r = (Math.sin(k * 12.9898) * 43758.5453) % 1;
      for (let i = 0; i < SEG; i++) {
        pos.push(pts[i].x, pts[i].y, pts[i].z, pts[i + 1].x, pts[i + 1].y, pts[i + 1].z);
        prog.push(i / SEG, (i + 1) / SEG);
        seed.push(Math.abs(r), Math.abs(r));
      }
    });
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute("aProg", new THREE.Float32BufferAttribute(prog, 1));
    g.setAttribute("aSeed", new THREE.Float32BufferAttribute(seed, 1));
    return { geom: g, heads: curves };
  }, [a]);
  const mat = useMemo(() => new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uGrow: { value: 0 }, uFade: { value: 0 }, uA: { value: new THREE.Color(...pal.lost) }, uB: { value: new THREE.Color(...pal.one) } },
    vertexShader: `attribute float aProg; attribute float aSeed; varying float vP; varying float vS;
      void main(){ vP = aProg; vS = aSeed; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.); }`,
    fragmentShader: `uniform float uGrow; uniform float uFade; uniform vec3 uA; uniform vec3 uB; varying float vP; varying float vS;
      void main(){
        float g = uGrow * (1.0 + vS * 0.35) - vS * 0.35;      // arcs start a little apart
        if (vP > g) discard;
        float head = smoothstep(g - .08, g, vP);
        vec3 c = mix(uA, uB, vP) * (0.42 + 0.9 * head);
        gl_FragColor = vec4(c * uFade, uFade * (0.5 + 0.5 * head));
      }`,
  }), [pal]);
  const tag = useRef<HTMLDivElement>(null);
  useEffect(() => () => { geom.dispose(); mat.dispose(); }, [geom, mat]);
  useFrame(() => {
    const p = story.pSmooth;
    const grow = story.reduced ? (story.active === 3 ? 1 : 0) : smooth(2.45, 3.0, p);
    const fadeK = story.reduced ? (story.active === 3 ? 1 : 0) : smooth(2.35, 2.6, p) * (1 - smooth(3.3, 3.6, p));
    mat.uniforms.uGrow.value = grow;
    mat.uniforms.uFade.value = fadeK;
    if (tag.current) tag.current.style.opacity = String(fadeK);
  });
  if (!a) return null;
  void heads;
  return (
    <group>
      <lineSegments geometry={geom} material={mat} renderOrder={6} />
      <Html position={[a.station.x, 2.4, a.station.z]} center zIndexRange={[5, 0]} pointerEvents="none">
        <div ref={tag} className="ci-tag" style={{ opacity: 0 }}><span className="ci-tag-k0">{label}</span></div>
      </Html>
    </group>
  );
}
