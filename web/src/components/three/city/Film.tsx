import { useEffect } from "react";
import * as THREE from "three";
import { Canvas, useThree } from "@react-three/fiber";
import { palette, story, useCityData, type CityData } from "./core";
import { Scene } from "./Scene";

const STEP_AT = [0, 1, 2, 3, 4];        // story positions where each beat begins

/** Exposes window.__film(i, n): sets the story to frame i of n exactly, renders, and returns the frame as WebP. */
function Recorder() {
  const { gl, invalidate } = useThree();
  useEffect(() => {
    story.film = true; story.reduced = false;
    (window as any).__film = async (i: number, n: number, fps = 24, quality = 0.84) => {
      const p = (i / (n - 1)) * 4;
      story.p = p; story.pSmooth = p; story.t = i / fps;
      story.active = Math.min(4, Math.round(p));
      // when each beat began, on the same clock, so its own animations (pulses, flares) play in film time
      STEP_AT.forEach((at, k) => { story.enteredStep[k] = ((at / 4) * (n - 1)) / fps; });
      story.lastInput = performance.now() / 1000;
      for (let r = 0; r < 3; r++) { invalidate(); await new Promise((res) => requestAnimationFrame(() => res(null))); }
      return gl.domElement.toDataURL("image/webp", quality);
    };
    (window as any).__filmReady = true;
    return () => { story.film = false; delete (window as any).__film; };
  }, [gl, invalidate]);
  return null;
}

/** #/lab/film?w=1920&h=1080&dark=0 : the city scene as a film set, one exact frame at a time, no page chrome. */
export function FilmStage({ w = 1920, h = 1080, dark = false }: { w?: number; h?: number; dark?: boolean }) {
  const data = useCityData();
  const pal = palette(dark);
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: pal.sky, width: w, height: h }}>
      {data && (
        <Canvas frameloop="demand" dpr={1} style={{ width: w, height: h }}
                camera={{ fov: 38, near: 0.1, far: 5000, position: [30, 17, 52] }}
                gl={{ antialias: true, preserveDrawingBuffer: true, powerPreference: "high-performance", toneMapping: THREE.NoToneMapping }}>
          <Recorder />
          <Scene data={data as CityData} pal={pal} dark={dark} copy={{ closedTag: "", lastTag: "", arcTag: "", street: "", lift: () => "" }} />
        </Canvas>
      )}
    </div>
  );
}
