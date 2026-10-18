import { useState } from "react";
import { API_BASE } from "../api";
import { S } from "../strings.en";

const PUBLIC_API = "https://lastlift-api.onrender.com";

/** "Use LastLift from your own agent": the public MCP endpoint, a copy-paste client config, and the same tools over
 *  plain HTTP. The graph is reusable context, not only this website. */
export function UseFromAgent() {
  const base = API_BASE || PUBLIC_API;
  const config = JSON.stringify({ mcpServers: { lastlift: { url: `${base}/mcp/` } } }, null, 2);
  const curl = [
    `# certified redundancy for every platform at Alewife`,
    `curl -s -X POST ${base}/v1/tools/platform_redundancy \\`,
    `  -H 'Content-Type: application/json' -d '{"station_id": "place-alfcl"}'`,
    ``,
    `# ask the agent; the reply lists every tool call it made, and a trace id`,
    `curl -s -X POST ${base}/api/ask \\`,
    `  -H 'Content-Type: application/json' -d '{"question": "What happens if lift 813 fails too?"}'`,
  ].join("\n");
  const [copied, setCopied] = useState("");
  const copy = (what: string, text: string) =>
    navigator.clipboard?.writeText(text).then(() => { setCopied(what); setTimeout(() => setCopied(""), 1800); }).catch(() => {});

  return (
    <section className="card use-agent" aria-labelledby="ua-h">
      <h2 id="ua-h">{S.useAgent.title}</h2>
      <p>{S.useAgent.lead}</p>
      <ul className="ua-gets">
        <li><strong>{S.useAgent.toolsT}</strong> {S.useAgent.tools}</li>
        <li><strong>{S.useAgent.resourcesT}</strong> {S.useAgent.resources}</li>
        <li><strong>{S.useAgent.promptsT}</strong> {S.useAgent.prompts}</li>
      </ul>
      <div className="ua-block">
        <div className="ua-head"><span>{S.useAgent.configLabel}</span>
          <button className="link" onClick={() => copy("config", config)} aria-live="polite">{copied === "config" ? S.useAgent.copied : S.useAgent.copy}</button></div>
        <pre tabIndex={0} aria-label={S.useAgent.configLabel}><code>{config}</code></pre>
      </div>
      <div className="ua-block">
        <div className="ua-head"><span>{S.useAgent.httpLabel}</span>
          <button className="link" onClick={() => copy("curl", curl)} aria-live="polite">{copied === "curl" ? S.useAgent.copied : S.useAgent.copy}</button></div>
        <pre tabIndex={0} aria-label={S.useAgent.httpLabel}><code>{curl}</code></pre>
      </div>
      <p className="muted">{S.useAgent.note}</p>
    </section>
  );
}
