# The agents: tools, memory, operations and MCP

Back to the [README](../README.md).

## The agent acts through the same tools as everyone

- Thirteen tools ([`lastlift/tools.py`](../lastlift/tools.py)): `resolve_place`, `current_closures`, `platform_redundancy`, `what_if_close`, `step_free_route`, `repair_priority`, `lift_history`, `draft_action`, `network_impact`, `repair_order`, `recall_lift_history`, `lift_dossier`, `stress_test`. The LLM never writes Cypher; every tool runs fixed, parameterised queries and reports their ids.
- The agent reaches the tools **only through MCP** (an in-memory MCP client; a test breaks every direct path and the agent still answers).
- Every answer is grounded: an id or number that is not in a tool result, or wording our copy rules forbid, sends the answer back to a deterministic template built from the tool results.
- Repair priority ranks lifts to repair now (closed, platforms cut off), to protect (working, but newly the last lift) and structural single points of failure; `draft_action` drafts a ticket and never files it.
- Providers fail over in a fixed chain: Groq `openai/gpt-oss-120b`, then `qwen/qwen3.8-27b` (the order set in `render.yaml`), then Gemini `gemini-3.1-flash-lite`, then the template. Each switch appears in the run's trace, the answer names the model that wrote it, and a daily token budget (counted from the providers' usage figures) stops LLM calls before the free quotas run out. A fault-injection test (`tests/test_chain.py`) fails each tier in turn.
- Every run has a W3C trace id (send a `traceparent` header to join your own trace); each tool call has its own span id, and LLM calls are logged with OpenTelemetry GenAI attribute names (`gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`).
- Seven recorded runs in `web/public/replay/` re-execute against the graph in CI (`scripts/verify_replays.py`): a recorded fact that no longer matches the graph fails the build.

## Operations agents: no language model in the critical path

<p align="center"><img src="img/timeline.webp" alt="The Operations page following one closure end to end: Monitor reads the alert for lift 869, the Analyst finds 891 is now the last step-free link, the Dispatcher proposes a protect ticket after its state check, a person approves, and issue number one is filed in lastlift-ops" width="100%"></p>

Three roles in one process act on every lift closure ([`lastlift/agents/`](../lastlift/agents/)), handing off by writing nodes so every decision can be read back in Cypher:

- **Monitor** reads MBTA's alerts. **Analyst** chooses a playbook from graph facts (lift not modelled: *abstain*; a platform-direction's k went to 0: *access lost*; another lift became the last one: *preventive*; otherwise *no loss*; a lift in the top quarter of closures in the archive's last year adds *chronic*, so memory changes the action), calls the tools through MCP and writes `(:Assessment)-[:ABOUT]->(:Lift)`. **Dispatcher** proposes actions from a fixed policy table, and only if a Cypher guard confirms the assessment was made at the graph's current `state_version`: a stale belief cannot act.
- Policy: repair and protect tickets need a person's approval (website inbox, `POST /v1/approvals/{id}` with an `Idempotency-Key`, or MCP elicitation on `/mcp-ops`); approved tickets become GitHub issues on the ops repository only when filing is switched on, as a lift dossier with a Mermaid drawing of the station, deduplicated per lift. Rider notices ("follow a station" in the free ntfy app; no subscriber data stored) go out automatically only when notifications are switched on, once per change of state.
- No language model is given a write tool, so text in an alert (a prompt injection included) cannot cause an action; a test checks it.
- Memory and provenance: every chat run is recorded as `(:Run)-[:CALLED]->(:ToolCall)-[:READ]->(:Lift|:Platform|:Station)` with its `(:Answer)`; when a lift changes state, the answers that read it are marked stale in the same step. `recall_lift_history` and `lift_dossier` read it back. Memory means observed history and provenance; nothing is learned.
- Recorded runs are hash-chained: the website's "Verify this replay" button recomputes the chain in the browser, and one edited byte fails.

## Answers that know when they are out of date

<p align="center"><img src="img/stale-answer.webp" alt="An agent answer in the chat marked out of date: lift 813 changed state after this answer, with an Ask again button" width="420"></p>

An agent's answer is only as good as the context it was built from, and lift status changes by the hour. LastLift keeps that context honest in the graph itself:

- Every chat run is written as `(:Run)-[:CALLED]->(:ToolCall)-[:READ]->(:Lift)` with its `(:Answer)`, tagged with the run's trace id.
- When a lift changes state (`state.sync`), the same step marks every answer that read it `stale`, with the reason. An unrelated answer is untouched.
- `GET /v1/answers/{trace_id}` reports whether an answer is still true. The chat polls it while it is open: "✓ Still true" until a lift it read changes, then "⚠ Out of date: lift 813 changed state after this answer", with **Ask again**.
- To see it happen: ask about Alewife in the chat, then run `python scripts/demo_stale.py close 813` against your own graph; the answer flips within seconds. `python scripts/demo_stale.py restore` puts the closures back exactly as they were.

## Use it from your own agent

Point any MCP client that supports streamable HTTP at the endpoint:

```json
{ "mcpServers": { "lastlift": { "url": "https://lastlift-api.onrender.com/mcp/" } } }
```

All thirteen tools are read-only (`readOnlyHint`), with an output schema; `what_if_close` works on a throwaway copy. The server also offers resources (`lastlift://model`, `lastlift://stations/{id}` and its Mermaid drawing `graph.mmd`, `lastlift://lifts/{id}/dossier.md`, `lastlift://incidents/open`, `lastlift://runs/{id}`, `lastlift://eval/latest`) and prompts (`triage_closure`, `station_briefing`, `plan_step_free_trip`, `explain_certificate`). The free host sleeps when idle, so the first call may take a minute.

The same block works in Cursor (`.cursor/mcp.json`), VS Code and desktop agents that speak MCP; they then see LastLift's tools, resources and prompts alongside their own.

Or straight over HTTP:

```sh
# Which Alewife platforms hang on one lift, and why
curl -s -X POST https://lastlift-api.onrender.com/v1/tools/platform_redundancy \
  -H 'Content-Type: application/json' -d '{"station_id": "place-alfcl"}'

# Close a working lift on a throwaway copy of the graph
curl -s -X POST https://lastlift-api.onrender.com/v1/tools/what_if_close \
  -H 'Content-Type: application/json' -d '{"facility_ids": ["813"]}'

# Ask the agent; the reply carries every tool call it made and a trace id
curl -s -X POST https://lastlift-api.onrender.com/api/ask \
  -H 'Content-Type: application/json' -d '{"question": "What happens if lift 813 fails too?"}'
```
