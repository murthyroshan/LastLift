/** True when WebGL2 runs on a real GPU. Software renderers (SwiftShader, llvmpipe, Microsoft Basic Render) make the
 *  3D scenes far too slow, so callers fall back to their static or 2D versions there. Checked once per page load. */
let cached: boolean | null = null;

export function realGpu(): boolean {
  if (cached !== null) return cached;
  try {
    const gl = document.createElement("canvas").getContext("webgl2");
    if (!gl) return (cached = false);
    const info = gl.getExtension("WEBGL_debug_renderer_info");
    const r = String(info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    return (cached = !/swiftshader|llvmpipe|software|basic render/i.test(r));
  } catch {
    return (cached = false);
  }
}
