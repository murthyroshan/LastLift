import { readFileSync } from "node:fs";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

/** `vite preview` serves the same headers as Vercel (vercel.json), so the browser tests run under the real CSP. */
function vercelHeaders(): Plugin {
  const rules: { source: string; headers: { key: string; value: string }[] }[] =
    JSON.parse(readFileSync(new URL("./vercel.json", import.meta.url), "utf-8")).headers;
  const compiled = rules.map((r) => ({ re: new RegExp(`^${r.source}$`), headers: r.headers }));
  return {
    name: "vercel-headers",
    configurePreviewServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = (req.url ?? "/").split("?")[0];
        for (const r of compiled) if (r.re.test(path)) for (const h of r.headers) res.setHeader(h.key, h.value);
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), vercelHeaders()],
  server: { proxy: { "/v1": "http://127.0.0.1:8000", "/api": "http://127.0.0.1:8000", "/healthz": "http://127.0.0.1:8000" } },
});
