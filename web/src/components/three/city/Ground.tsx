import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import { MeshReflectorMaterial } from "@react-three/drei";
import { flags, rng, story, type CityData, type Palette } from "./core";

const SIZE = 260;          // the light map covers SIZE x SIZE scene units around CENTRE
const CENTRE = { x: -4, z: 18 };
const RES = 2048;

/** City lights seen from the air: warm specks scattered along every ride corridor, denser near downtown and around
 *  stations, plus a soft haze over the core. Generated once from our own station and link data (no map tiles). */
function lightMap(data: CityData, dark: boolean) {
  const c = document.createElement("canvas");
  c.width = c.height = RES;
  const g = c.getContext("2d")!;
  g.fillStyle = "#000"; g.fillRect(0, 0, RES, RES);
  const px = (x: number) => ((x - CENTRE.x) / SIZE + 0.5) * RES;
  const pz = (z: number) => ((z - CENTRE.z) / SIZE + 0.5) * RES;
  const unit = RES / SIZE;
  const rand = rng(7);
  const gauss = () => { let s = 0; for (let i = 0; i < 4; i++) s += rand(); return (s - 2) / 0.58; };

  // haze over the urban core
  const haze = g.createRadialGradient(px(0), pz(0), 0, px(0), pz(0), 30 * unit);
  haze.addColorStop(0, dark ? "rgba(255,160,80,0.10)" : "rgba(255,210,170,0.08)");
  haze.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = haze; g.fillRect(0, 0, RES, RES);

  g.globalCompositeOperation = "lighter";
  const speck = (x: number, z: number, r: number, a: number, warm: number) => {
    const col = warm > 0.82 ? `rgba(200,220,255,${a})` : warm > 0.5 ? `rgba(255,214,150,${a})` : `rgba(255,170,95,${a})`;
    g.fillStyle = col;
    g.beginPath(); g.arc(px(x), pz(z), r, 0, Math.PI * 2); g.fill();
  };
  // corridors: specks scattered either side of every link, more where it is closer to downtown
  for (const l of data.links) {
    const dx = l.b.x - l.a.x, dz = l.b.z - l.a.z, len = Math.hypot(dx, dz);
    const near = Math.exp(-Math.hypot((l.a.x + l.b.x) / 2, (l.a.z + l.b.z) / 2) / 28);
    const n = Math.round(len * (l.rail ? 14 : 5) * (0.35 + near));
    for (let i = 0; i < n; i++) {
      const t = rand(), off = gauss() * (1.1 + 2.4 * (1 - near));
      const x = l.a.x + dx * t - (dz / len) * off, z = l.a.z + dz * t + (dx / len) * off;
      speck(x, z, 0.5 + rand() * 1.1, 0.06 + rand() * 0.26, rand());
    }
  }
  // neighbourhoods around stations
  for (const s of data.stations) {
    const near = Math.exp(-Math.hypot(s.x, s.z) / 22);
    const n = Math.round((s.data ? 110 : 50) * (0.4 + near));
    for (let i = 0; i < n; i++) {
      const r = Math.abs(gauss()) * (1.4 + 2.2 * (1 - near));
      const a = rand() * Math.PI * 2;
      speck(s.x + Math.cos(a) * r, s.z + Math.sin(a) * r, 0.45 + rand() * 0.9, 0.05 + rand() * 0.22, rand());
    }
  }
  // the dense core
  for (let i = 0; i < 2600; i++) {
    const r = Math.abs(gauss()) * 6.5, a = rand() * Math.PI * 2;
    speck(Math.cos(a) * r - 1, Math.sin(a) * r * 0.9 - 0.5, 0.45 + rand() * 0.8, 0.04 + rand() * 0.18, rand());
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

/** A faint survey grid that fades with distance (one draw call, additive). */
const gridMaterial = (col: string) => new THREE.ShaderMaterial({
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  uniforms: { uColor: { value: new THREE.Color(col) }, uFade: { value: 1 } },
  vertexShader: `varying vec3 vW; void main(){ vec4 w = modelMatrix * vec4(position,1.); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`,
  fragmentShader: `uniform vec3 uColor; uniform float uFade; varying vec3 vW;
    float line(float v, float w){ float d = abs(fract(v - .5) - .5) / fwidth(v); return 1. - min(d / w, 1.); }
    void main(){
      float g = max(line(vW.x / 4., 1.), line(vW.z / 4., 1.)) * .35 + max(line(vW.x / 20., 1.2), line(vW.z / 20., 1.2)) * .5;
      float dist = length(vW.xz - cameraPosition.xz);
      float a = g * exp(-dist / 70.) * uFade * .32;
      gl_FragColor = vec4(uColor * a, a);
    }`,
});

export function Ground({ data, pal, dark }: { data: CityData; pal: Palette; dark: boolean }) {
  const tex = useMemo(() => lightMap(data, dark), [data, dark]);
  const grid = useMemo(() => gridMaterial(pal.grid), [pal.grid]);
  const lights = useRef<THREE.MeshBasicMaterial>(null);
  useEffect(() => () => { tex.dispose(); grid.dispose(); }, [tex, grid]);
  useFrame(({ camera }) => {
    // fade the surface as the camera dives below it
    const under = THREE.MathUtils.clamp(1 - (camera.position.y + 0.5) / 2.5, 0, 1);
    grid.uniforms.uFade.value = 1 - under;
    if (lights.current) lights.current.opacity = (dark ? 1 : 0.85) * (1 - under * 0.85) * (0.12 + 0.88 * THREE.MathUtils.smoothstep(camera.position.y, 5, 24));
    void story;
  });
  return (
    <group>
      <mesh rotation-x={-Math.PI / 2} position={[CENTRE.x, -0.02, CENTRE.z]}>
        <planeGeometry args={[4000, 4000]} />
        {flags.has("noreflect") ? <meshStandardMaterial color={pal.ground} roughness={0.9} /> : <MeshReflectorMaterial
          color={pal.ground} metalness={0.55} roughness={0.85} mirror={0.6}
          blur={[300, 90]} resolution={512} mixBlur={1.4} mixStrength={dark ? 2.6 : 1.8} mixContrast={1.1}
          depthScale={0.6} minDepthThreshold={0.2} maxDepthThreshold={1.2}
        />}
      </mesh>
      <mesh rotation-x={-Math.PI / 2} position={[CENTRE.x, 0.01, CENTRE.z]} renderOrder={1}>
        <planeGeometry args={[SIZE, SIZE]} />
        <meshBasicMaterial ref={lights} map={tex} transparent blending={THREE.AdditiveBlending} depthWrite={false}
                           toneMapped={false} color={new THREE.Color(1.35, 1.2, 1.05)} />
      </mesh>
      <mesh rotation-x={-Math.PI / 2} position={[CENTRE.x, 0.015, CENTRE.z]} renderOrder={2} material={grid}>
        <planeGeometry args={[SIZE * 1.6, SIZE * 1.6]} />
      </mesh>
    </group>
  );
}
