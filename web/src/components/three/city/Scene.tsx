import { useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { useFrame, useThree } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import { Bloom, DepthOfField, EffectComposer, Noise, ToneMapping, Vignette } from "@react-three/postprocessing";
import { BlendFunction, ToneMappingMode } from "postprocessing";
import { advanceClock, flags, smooth, story, type CityData, type Palette } from "./core";
import { Ground } from "./Ground";
import { Network } from "./Network";
import { Arcs, Beacons } from "./Beacons";
import { Cutaway } from "./Cutaway";

type Key = { p: number; pos: [number, number, number]; tgt: [number, number, number] };

/** Camera keyframes, one per beat of the story (p = story position). */
function keys(d: CityData): Key[] {
  const F = d.focus?.station ?? { x: -6, z: -4 };
  const D = d.arc?.station ?? { x: -4.5, z: -4.5 };
  return [
    { p: 0, pos: [30, 16.5, 52], tgt: [-6, 0, 5] },
    { p: 1, pos: [F.x + 9, 8.5, F.z + 15], tgt: [F.x, 0.8, F.z] },
    { p: 2, pos: [-40, 21, 40], tgt: [-1, 3, 4] },
    { p: 3, pos: [D.x + 9, 26, D.z + 27], tgt: [D.x + 4.5, 1.5, D.z + 9] },
    { p: 3.55, pos: [F.x + 3.5, 5.5, F.z + 7.5], tgt: [F.x, -0.5, F.z] },
    { p: 4, pos: [F.x + 6.5, -2.4, F.z + 19.5], tgt: [F.x - 0.6, -5.6, F.z + 0.4] },
  ];
}

/** Moves the camera along smooth splines through the keyframes, following (damped) scroll position. */
/** Where the text panel sits for each step: the subject is shifted into the free side of the frame. */
const SIDE = [-0.17, 0.19, -0.19, 0.19, -0.23];

function Rig({ data }: { data: CityData }) {
  const { size } = useThree();
  const ks = useMemo(() => keys(data), [data]);
  const curves = useMemo(() => ({
    pos: new THREE.CatmullRomCurve3(ks.map((k) => new THREE.Vector3(...k.pos)), false, "centripetal"),
    tgt: new THREE.CatmullRomCurve3(ks.map((k) => new THREE.Vector3(...k.tgt)), false, "centripetal"),
  }), [ks]);
  const look = useRef(new THREE.Vector3(...ks[0].tgt));
  const want = useMemo(() => new THREE.Vector3(), []);
  const wantT = useMemo(() => new THREE.Vector3(), []);
  useFrame(({ camera, clock }, dt) => {
    const now = clock.elapsedTime;
    if (!story.film) advanceClock(Math.min(dt, 0.05), performance.now() / 1000);
    void now;
    const target = story.reduced ? story.active : story.p;
    const k = story.reduced || story.film ? 1 : 1 - Math.exp(-Math.min(dt, 0.05) * 3.2);
    story.pSmooth += (target - story.pSmooth) * k;
    // story position -> spline parameter (piecewise linear between keyframes)
    const p = story.pSmooth;
    let i = 0;
    while (i < ks.length - 2 && p > ks[i + 1].p) i++;
    const f = THREE.MathUtils.clamp((p - ks[i].p) / (ks[i + 1].p - ks[i].p), 0, 1);
    const u = (i + f) / (ks.length - 1);
    curves.pos.getPointAt(Math.min(1, u), want);
    curves.tgt.getPointAt(Math.min(1, u), wantT);
    // a slow drift across the establishing shot, tied to scroll and the motion clock (never on its own for long)
    const drift = (1 - smooth(0.2, 0.9, p)) * (story.reduced ? 0 : 1);
    want.x += Math.sin(story.t * 0.12) * 2.5 * drift;
    camera.position.copy(want);
    look.current.lerp(wantT, story.reduced || story.film ? 1 : 0.25);
    camera.lookAt(look.current);
    // shift the frustum sideways so the subject sits beside the text, not under it (none on narrow screens)
    const j = Math.min(SIDE.length - 2, Math.floor(p)), fr = p - j;
    const side = size.width < 900 || story.film ? 0 : SIDE[j] + (SIDE[j + 1] - SIDE[j]) * (fr * fr * (3 - 2 * fr));
    const cam = camera as THREE.PerspectiveCamera;
    cam.setViewOffset(size.width, size.height, side * size.width, 0, size.width, size.height);
    cam.updateProjectionMatrix();
  });
  return null;
}

/** A gradient dome: a faint warm glow at the horizon fading to night (or dusk) overhead. */
function Sky({ pal }: { pal: Palette }) {
  const mat = useMemo(() => new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false,
    uniforms: { uTop: { value: new THREE.Color(pal.sky) }, uHorizon: { value: new THREE.Color(pal.fog) }, uGlow: { value: new THREE.Color("#ff9a50") } },
    vertexShader: `varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.); }`,
    fragmentShader: `uniform vec3 uTop; uniform vec3 uHorizon; uniform vec3 uGlow; varying vec3 vP;
      void main(){
        float h = smoothstep(0.0, 0.5, vP.y);
        vec3 c = mix(uHorizon, uTop, h);
        c += uGlow * 0.10 * exp(-abs(vP.y - 0.02) * 18.0);      // a thin band of city glow on the horizon
        gl_FragColor = vec4(c, 1.);
      }`,
  }), [pal]);
  return <mesh material={mat} scale={900}><sphereGeometry args={[1, 32, 16]} /></mesh>;
}

function Effects({ data }: { data: CityData }) {
  const dof = useRef<any>(null);
  const F = data.focus?.station;
  const focus = useMemo(() => new THREE.Vector3(F?.x ?? 0, -4.5, F?.z ?? 0), [F]);
  const { size } = useThree();
  // depth of field only exists during the dive (it is the most expensive pass on integrated GPUs)
  const [diving, setDiving] = useState(false);
  useFrame(() => {
    const d = smooth(3.55, 3.95, story.pSmooth);
    const want = !story.reduced && story.pSmooth > 3.3;
    if (want !== diving) setDiving(want);
    if (dof.current) dof.current.bokehScale = d * 3.2;
  });
  return (
    <EffectComposer multisampling={0}>
      <Bloom mipmapBlur intensity={0.75} luminanceThreshold={1.0} luminanceSmoothing={0.3} radius={0.72} />
      {flags.has("nodof") || !diving ? <></> : <DepthOfField ref={dof} target={focus} focalLength={0.02} bokehScale={0} height={Math.min(480, size.height)} />}
      <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
      <Vignette eskil={false} offset={0.22} darkness={0.72} />
      <Noise premultiply blendFunction={BlendFunction.OVERLAY} opacity={0.18} />
    </EffectComposer>
  );
}

export function Scene({ data, pal, dark, copy }: {
  data: CityData; pal: Palette; dark: boolean;
  copy: { closedTag: string; lastTag: string; arcTag: string; street: string; lift: (f: string) => string };
}) {
  return (
    <>
      <color attach="background" args={[pal.sky]} />
      <fog attach="fog" args={[pal.fog, 50, 230]} />
      <Sky pal={pal} />
      <Rig data={data} />
      <Ground data={data} pal={pal} dark={dark} />
      <Network data={data} pal={pal} />
      {/* Under React 19 StrictMode the first drei <Html> root mounted in a scene stays empty; this empty one takes
          that slot so the real labels below all render. */}
      <Html position={[0, -1000, 0]} pointerEvents="none"><span /></Html>
      <Beacons data={data} pal={pal} labels={{ closed: copy.closedTag, last: copy.lastTag }} />
      <Arcs data={data} pal={pal} label={copy.arcTag} />
      <Cutaway data={data} pal={pal} labels={{ street: copy.street, lift: copy.lift }} />
      {!flags.has("nofx") && <Effects data={data} />}
    </>
  );
}
