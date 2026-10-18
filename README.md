<div align="center">

<img src="docs/logo.svg" width="64" height="64" alt="">

# LastLift

### Find the last lift before it fails.

**An agent that finds the lift a platform depends on, before it fails, and files the ticket after a person approves.**

[![ci](https://github.com/murthyroshan/LastLift/actions/workflows/ci.yml/badge.svg)](https://github.com/murthyroshan/LastLift/actions/workflows/ci.yml)
[![live site](https://img.shields.io/badge/live-lastlift.vercel.app-16181d?logo=vercel&logoColor=white)](https://lastlift.vercel.app)
[![MCP](https://img.shields.io/badge/MCP-streamable%20HTTP-3b82f6)](#use-it-from-your-own-agent)
[![FalkorDB](https://img.shields.io/badge/FalkorDB-4.22-f5a524)](https://www.falkordb.com)
[![track](https://img.shields.io/badge/Graph%20Hacks-Track%201%3A%20Agents%20That%20Act-f5a524)](#track-entered)
[![licence](https://img.shields.io/badge/licence-MIT-lightgrey)](LICENSE)
[![demo video](https://img.shields.io/badge/demo%20video-2%3A32-ff0033?logo=youtube&logoColor=white)](https://youtu.be/XLDNu4cGaN8)

**[▶ Demo video (2:32)](https://youtu.be/XLDNu4cGaN8)** · **[Live site](https://lastlift.vercel.app)** · **[Judge's tour](https://lastlift.vercel.app/#/tour)** · **[Play the walkthrough](https://lastlift.vercel.app/concepts/alewife.html)** · **[Issues the agents filed](https://github.com/murthyroshan/lastlift-ops/issues)** · **[Blog post](https://dev.to/roshan_7c49d2a48522e3f8ff/the-last-lift-finding-the-elevator-a-wheelchair-user-cant-lose-before-it-fails-2c9n)**

<br>

<img src="docs/img/hero.gif" alt="LastLift in seven frames: the finding, the agent calling tools over MCP, every claim checked, an answer marked out of date when lift 813 changes state, the ticket the agents filed after a person approved, and the walkthrough" width="100%">

</div>

> Unofficial decision-support prototype. Not affiliated with or endorsed by the MBTA or MassDOT. Uses MBTA GTFS and V3 API data under the MassDOT Developers License Agreement. Data may be incomplete or out of date. Always check mbta.com/alerts/access before travelling. Elevator status line 617-222-2828; customer support 617-222-3200 (TTY 711).
>
> Results describe the open-data model and may differ from conditions on the ground.

## The finding

<table>
<tr>
<td align="center" width="25%"><h1><!--claim:platforms_single_lift-->89<!--/claim--></h1>of <!--claim:platforms_step_free-->366<!--/claim--> step-free platforms in Boston's MBTA station data hang on <b>a single lift</b></td>
<td align="center" width="25%"><h1><!--claim:n2_critical_pairs-->42<!--/claim--></h1>lift pairs are harmless alone but <b>cut platforms off together</b></td>
<td align="center" width="25%"><h1><!--claim:net_spof_lifts-->15<!--/claim--></h1>lifts can each cut <b>a whole station</b> off from the step-free network</td>
<td align="center" width="25%"><h1><!--claim:falkordb_certified-->734<!--/claim--></h1>of <!--claim:maxflow_calls-->734<!--/claim--> FalkorDB max-flow results <b>certified</b> and equal to NetworkX</td>
</tr>
</table>

LastLift turns the MBTA's published station layouts into a flow network in FalkorDB, so for every platform it knows how many lift failures it takes to cut riders who need step-free access off, which lift that is, and what to do when it happens. An agent answers questions about it through tools that any MCP client can call, and operations agents turn a closure into a ticket a person approves.

**Graph Hacks track:** Agents That Act on Connected Data.

### If you have 60 seconds

- Every step-free route through a station is a path through lifts, walkways and fare gates. Give each lift a capacity of one and **max-flow is the number of lifts that must fail before a platform is cut off**. One means a single point of failure.
- Today, with lift 961 closed at Alewife, **lift 813 is newly the only lift** for the Red Line, Track 1 and Track 2 platforms. No alert says that; the graph does.
- <!--claim:naive_two_lifts_but_k1-->74<!--/claim--> of the single-lift platforms are at stations with two or more lifts: counting lifts is not enough.
- Every number is a certified FalkorDB result, cross-checked against NetworkX, and every agent answer cites the exact Cypher it ran.

## See it

<table>
<tr>
<td width="50%"><img src="docs/img/command.webp" alt="The Command console: lift alerts beside a map of the network with a column per station"><br><b>Command.</b> Every open lift alert, what it means, and a map of the network coloured by MBTA line.</td>
<td width="50%"><img src="docs/img/station-xray.webp" alt="A station x-ray of Alewife: a 3D model of its levels with each platform's lift routes"><br><b>Station x-ray.</b> Alewife's levels in 3D, every platform's independent lift routes, and the table twin for screen readers.</td>
</tr>
<tr>
<td width="50%"><img src="docs/img/timeline.webp" alt="One closure end to end: Monitor, Analyst, Dispatcher, a person's approval, and the GitHub issue it filed"><br><b>One closure, end to end.</b> Lift 869 closes at Downtown Crossing; the agents find 891 is now the last lift; a person approves; the issue is filed.</td>
<td width="50%"><img src="docs/img/stale-answer.webp" alt="The chat marks an earlier answer out of date because lift 813 changed state after it was given"><br><b>Answers that expire.</b> A live answer flips to out of date the moment a lift it read changes.</td>
</tr>
<tr>
<td colspan="2"><img src="docs/img/game-813-fails.webp" alt="The 3D walkthrough: lift 813 on an underground platform, taped off and out of service" width="100%"><br><b>Walk through Alewife.</b> A seated first-person walkthrough built from LastLift's own data: lift 961 is closed, then lift 813 fails in front of you. <a href="https://lastlift.vercel.app/concepts/alewife.html">Play it</a>, or <a href="https://lastlift.vercel.app/concepts/alewife.html?autoplay">watch it play itself</a>.</td>
</tr>
</table>

## The agent, grounded in a graph

A recorded run from [`web/public/replay/whatif-813.json`](web/public/replay/whatif-813.json): a language model reaching LastLift's tools only through MCP, every claim in its answer checked against what the tools returned. The website replays it on the landing page and lets you verify its hash chain in the browser.

```text
Q  What happens if lift 813 fails too?

1  resolve_place      query: lift 813                                        via MCP ·   36 ms
   → lift 813 (Alewife Elevator 813 (Platform to main lobby))
2  what_if_close      facility_ids: [813]                                    via MCP · 1070 ms
   → simulated closing 813: 3 more platforms lose step-free access; 0 lifts become the last lift
     (simulation on a copy; live state unchanged)
3  step_free_route    from_station: place-alfcl · to_platform: Red Line
                      also_closed: [813]                                     via MCP ·   67 ms
   → no step-free route in the open-data model

✓  grounded: every claim checked against the tool results

A  If lift 813 fails, the Alewife Red Line platform loses step-free access in the open-data model.
   No step-free route exists in the open-data model to board that platform via other stations.
   Check mbta.com/alerts/access.
```

And the agents act. These two issues were filed by the Dispatcher, after a person approved each proposal, as lift dossiers with a drawing of the station's step-free graph:

| | Issue | Why the graph proposed it |
|---|---|---|
| **Protect** | [lastlift-ops#1: lift 891, Downtown Crossing](https://github.com/murthyroshan/lastlift-ops/issues/1) | Still working, but with 869 closed it is the last lift for the Oak Grove and Alewife platforms (minimum cut {869, 891}) |
| **Repair** | [lastlift-ops#2: lift 885, Revere Beach](https://github.com/murthyroshan/lastlift-ops/issues/2) | Closed, and the Wonderland platform has no other step-free route |

## Answers that know when they are out of date

The agents' memory lives in the graph: every chat run is written as `(:Run)-[:CALLED]->(:ToolCall)-[:READ]->(:Lift)` with its `(:Answer)`. When a lift changes state, the same step marks every answer that read it stale, and only those; the chat flips from "✓ Still true" to "⚠ Out of date", with **Ask again**. The memory, the operations agents and every tool: [docs/AGENTS.md](docs/AGENTS.md).

## Instead of "Elevator out of service", LastLift says what it means for you

| The alert | LastLift |
|---|---|
| "Revere Beach Elevator 885 is unavailable." | The Wonderland platform loses step-free access in the open-data model. To board step-free: lift 884, ride the Blue Line to Beachmont, change platforms there step-free, ride back (about 17 minutes). There is no backup avoiding lifts 884, 886 and 887. |
| "Alewife Elevator 961 is unavailable." | No platform loses access, but lift 813 is now the only lift for three platforms. Protect it. |
| "Elevator 782 at Worcester is unavailable." | Cannot assess: MBTA publishes no station layout for Worcester. |

## How it proves a last lift

<p align="center"><img src="docs/how-it-proves.svg" alt="Max-flow from the street to a platform equals its number of lift-disjoint step-free routes: at Alewife, k is 2 with both lifts, 1 with lift 961 closed, 0 if lift 813 fails too" width="100%"></p>

FalkorDB 4.22's `algo.maxFlow` can return a wrong value on some networks: on an 11-edge reproduction it returns 300 where the true max-flow is 453 (reported by the Chokepoint project; reproduced in [`docs/falkordb-maxflow-note.md`](docs/falkordb-maxflow-note.md)). So no FalkorDB flow is trusted on its own:

- each result is certified by checking that the returned flow is a feasible flow whose residual graph has no augmenting path, and repaired with an exact Dinic run if it is not;
- the minimum cut names the lifts; each lift on a single route is removed in turn to find every single point of failure;
- an independent checker validates the k lift-disjoint routes as a proof.

On LastLift's network: <!--claim:maxflow_calls-->734<!--/claim--> max-flow calls, <!--claim:falkordb_first_pass_exact-->734<!--/claim--> certified on the first pass, <!--claim:falkordb_repaired-->0<!--/claim--> repaired, <!--claim:falkordb_eq_networkx-->734<!--/claim--> equal to NetworkX, <!--claim:checker_accepted-->333<!--/claim--> route proofs accepted and <!--claim:checker_rejected-->0<!--/claim--> rejected. `scripts/verify_claims.py` re-derives every headline number from the committed snapshot with NetworkX alone.

## Architecture

<p align="center"><img src="docs/architecture.svg" alt="LastLift architecture: MBTA open data, an ingest and proof stage, FalkorDB, tools over MCP and REST, a grounded chat agent and human-approved operations agents, and the website, MCP clients, the walkthrough and the ops issue tracker" width="100%"></p>

| Layer | What it is | Where |
|---|---|---|
| Data | MBTA GTFS-Pathways, V3 alerts, MassDOT alert archives and LAMP | [`ingest/`](ingest/), [`data/`](data/) |
| Proof | A pinned snapshot, the flow certifier, an independent NetworkX re-derivation | [`lastlift/flow.py`](lastlift/flow.py), [`lastlift/checker.py`](lastlift/checker.py), [`scripts/verify_claims.py`](scripts/verify_claims.py) |
| Graph | FalkorDB 4.22: the step-free network, closures as relationship swaps, what-ifs on `GRAPH.COPY`, memory and provenance | [`lastlift/queries.py`](lastlift/queries.py), [`lastlift/memory.py`](lastlift/memory.py) |
| Tools | Thirteen read-only tools over fixed, parameterised Cypher | [`lastlift/tools.py`](lastlift/tools.py) |
| MCP and API | `/mcp` (public, read-only), `/mcp-ops` (approvals), REST `/v1`, SSE `/api/ask` | [`lastlift/mcp_server.py`](lastlift/mcp_server.py), [`lastlift/main.py`](lastlift/main.py) |
| Agents | A grounded chat agent with a provider chain; Monitor, Analyst and Dispatcher | [`lastlift/agent/`](lastlift/agent/), [`lastlift/agents/`](lastlift/agents/) |
| Surfaces | React and Vite on Vercel (pages open from a snapshot FalkorDB computed; live answers from the graph), the 3D walkthrough, `lastlift-ops` | [`web/`](web/), [`web/public/concepts/alewife.html`](web/public/concepts/alewife.html) |

## Results at a glance

| What | Result | Details |
|---|---|---|
| The agent with and without the graph (same model, same 30 pre-registered questions) | right lift and platform ids in <!--claim:eval_full_gemini_ids-->23/24<!--/claim--> answers with the graph, <!--claim:eval_llm_only_gemini_ids-->5/24<!--/claim--> without | [Evaluation](docs/EVALUATION.md) |
| Checked against MBTA's own alert text, labelled blind by the author | live alerts: <!--claim:live_agree-->6<!--/claim--> of <!--claim:live_scored-->8<!--/claim--> agree, <!--claim:live_disagree-->0<!--/claim--> disagree; archived closures: <!--claim:hist_gold_agree-->16<!--/claim--> of <!--claim:hist_gold_scored-->17<!--/claim--> agree | [Evaluation](docs/EVALUATION.md) |
| Every reported closure since 2024, replayed through the graph | <!--claim:hist_dirs_lost-->251<!--/claim--> platform-directions lost step-free access; <!--claim:hist_single_share-->95%<!--/claim--> of the lost hours trace to a single lift | [Evaluation](docs/EVALUATION.md) |
| The whole network | <!--claim:net_platform_spof_lifts-->69<!--/claim--> lifts can each cut a platform off; only <!--claim:net_spof_lifts-->15<!--/claim--> can cut a station off from the network | [Network](docs/NETWORK.md) |
| Does it travel? | the same rules on <!--claim:atlas_feeds-->14<!--/claim--> open feeds: <!--claim:atlas_falkordb_equal-->2,884<!--/claim--> of <!--claim:atlas_falkordb_checked-->2,884<!--/claim--> FalkorDB results equal an exact solver | [Network](docs/NETWORK.md) |
| Quality, security and accessibility | the tests, the safeguards, axe in light and dark, and the defects we found in the published data | [Quality](docs/QUALITY.md) |

## Use it from your own agent

Point any MCP client that supports streamable HTTP at the endpoint (Cursor, VS Code, desktop agents):

```json
{ "mcpServers": { "lastlift": { "url": "https://lastlift-api.onrender.com/mcp/" } } }
```

Thirteen read-only tools with output schemas, plus resources (station graphs as Mermaid, lift dossiers, open incidents) and prompts. The free host sleeps when idle, so the first call may take a minute. Every tool, resource and `curl` example: [docs/AGENTS.md](docs/AGENTS.md).

## Judge it in 90 seconds

**On the site:** [the Judge's tour](https://lastlift.vercel.app/#/tour) walks through everything in seven stops, each one the real thing. **From a terminal:**

1. `POST https://lastlift-api.onrender.com/v1/tools/platform_redundancy` with `{"station_id": "place-alfcl"}`: Alewife, with the lift that became the last lift and why.
2. `POST .../v1/tools/what_if_close` with `{"facility_ids": ["813"]}`: close a working lift on a copy of the graph; three platforms lose step-free access; the live state is untouched.
3. `POST .../api/ask` with `{"question": "Can I get step-free onto the Wonderland-bound platform at Revere Beach right now?"}`: the agent's answer and every tool call it made, via MCP.
4. `GET .../v1/queries`: every Cypher statement LastLift runs.
5. `python scripts/smoke.py --prod` checks all of the above from your machine.

## Every submission requirement, and exactly where it is

| Rule 10 requirement | Where |
|---|---|
| Public source-code repository | this repository |
| README with setup instructions and the graph data model | [Run it yourself](#run-it-yourself), [The graph data model](#the-graph-data-model) |
| The Cypher queries or graph algorithms the product depends on | [The Cypher and the algorithms](#the-cypher-and-the-algorithms) (generated from `lastlift/queries.py`) |
| A demo video | [youtu.be/XLDNu4cGaN8](https://youtu.be/XLDNu4cGaN8) (2:32, narrated by the author, English subtitles) |
| A live deployment, or complete local setup | [lastlift.vercel.app](https://lastlift.vercel.app), the API at [lastlift-api.onrender.com/v1/docs](https://lastlift-api.onrender.com/v1/docs), and [Run it yourself](#run-it-yourself) |
| The track | Track 1, Agents That Act on Connected Data ([how it fits](#track-entered)) |

### Track entered

**Track 1, Agents That Act on Connected Data.**

- **The agents act on the graph.** Operations agents work every closure: the Monitor reads live MBTA alerts, the Analyst picks a playbook from certified max-flow, the Dispatcher proposes only while the graph is unchanged, and a person's approval files a real ticket ([lastlift-ops](https://github.com/murthyroshan/lastlift-ops/issues)). The chat agent answers only through the tools, over MCP, with every claim checked.
- **They act on context that is still true.** The agents' memory lives in FalkorDB: every run, tool call and answer is a node with what it read; an answer is marked stale the moment a lift it read changes ([Answers that know when they are out of date](#answers-that-know-when-they-are-out-of-date), [docs/AGENTS.md](docs/AGENTS.md)); the agents coordinate by writing assessments and proposals into the graph, guarded by its state version, never by messaging each other.

Rule 3 (the graph does real work): see [Turn FalkorDB off](docs/NETWORK.md#turn-falkordb-off-and-here-is-exactly-what-stops-working). Rule 6 (data you may use): public MBTA open data only. Rule 11 (AI disclosure): [AI assistance](#ai-assistance).

## The graph data model

<p align="center"><img src="docs/data-model.svg" alt="LastLift graph data model: a station complex from street to entrance, walkways and gates, lift (an edge of capacity 1, retyped SF_CLOSED when out), the lift's far door and the platform; stairs and escalators are STEP edges never used; platforms depend on lifts and ride to other platforms; lifts link to incidents" width="100%"></p>

Every node in a station complex carries `cx`; step-free walkways, gates and lift-access edges have capacity 1,000,000 and lift edges capacity 1, so a platform's max-flow from its station's street node is its number of lift-disjoint step-free routes. A closed lift's edge is retyped `SF_CLOSED`, which takes it out of every algorithm at once. Model rules, including five evidence-backed overrides of the published data, are in [`docs/model_rules.md`](docs/model_rules.md).

<details>
<summary><b>Graph counts</b>: every node label and relationship in the snapshot</summary>

<!--generated:counts-->
| Node labels | Count |
|---|---|
| `Lift` | 42 |
| `Node:Entrance` | 330 |
| `Node:Generic` | 1,924 |
| `Node:Lift` | 202 |
| `Node:LiftOut` | 202 |
| `Node:Platform` | 388 |
| `Node:Street` | 89 |
| `Platform` | 312 |
| `Station` | 276 |

| Relationship | Count |
|---|---|
| `HAS_ENTRANCE` | 330 |
| `HAS_LIFT` | 244 |
| `HAS_PLATFORM` | 388 |
| `RIDE` | 650 |
| `SF` | 9,248 |
| `STEP` | 1,069 |

| Step-free (`SF`) edge kind | Count |
|---|---|
| `gate` | 274 |
| `lift` | 202 |
| `lift_access` | 856 |
| `street` | 424 |
| `walk` | 7,492 |

Snapshot `2026-10-15`, GTFS feed "Fall 2026, 2026-10-14T18:47:38+00:00, version D", seed sha256 `8277887f216a…`: 3,765 nodes, 11,929 relationships.
<!--/generated-->

</details>

<a id="the-cypher-and-the-algorithms"></a>

<details>
<summary><b>The Cypher and the algorithms</b>: every statement LastLift runs</summary>

FalkorDB algorithms used: `algo.maxFlow` (redundancy, certified), `algo.WCC` (load verification), full-text index (station search), `GRAPH.COPY` (what-ifs). Every statement LastLift runs, generated from [`lastlift/queries.py`](lastlift/queries.py):

<!--generated:cypher-->
| Query | Cypher |
|---|---|
| `Q_CLEAR_DEPENDS_NOW` | `MATCH (p:Node:Platform {cx:$cx})-[d:DEPENDS_NOW]->() DELETE d` |
| `Q_CLEAR_INCIDENTS` | `MATCH (i:Incident) DETACH DELETE i` |
| `Q_CLOSED_AT_COMPLEX` | `MATCH (l:Lift {cx:$cx})-[:SF_CLOSED]->() RETURN collect(DISTINCT l.facility_id)` |
| `Q_CLOSED_FACILITIES` | `MATCH (i:Lift)-[:SF_CLOSED]->() RETURN collect(DISTINCT i.facility_id)` |
| `Q_CLOSE_LIFTS` | `UNWIND $fids AS fid MATCH (i:Lift {facility_id:fid})-[r:SF {kind:'lift'}]->(o) CREATE (i)-[c:SF_CLOSED]->(o) SET c = properties(r), i.closed = true DELETE r RETURN count(c)` |
| `Q_COMPLEX_FLOW_EDGES` | `MATCH (a:Node {cx:$cx})-[e:SF]->(b:Node) RETURN e.eid, a.uid, b.uid, e.cap, e.kind, e.facility_id` |
| `Q_COMPLEX_PLATFORMS` | `MATCH (p:Node:Platform {cx:$cx}) RETURN p.stop_id, collect(p.uid), head(collect(p.name)), head(collect(p.wheelchair_boarding)), head(collect(p.platform_name))` |
| `Q_COMPLEX_STREETS` | `MATCH (s:Street {cx:$cx}) RETURN collect(s.uid)` |
| `Q_CONDITIONAL` | `MATCH (a:Node:Lift)-[c:CRITICAL_PAIR]->(b:Node:Lift) WHERE c.scope = 'network' RETURN a.facility_id, b.facility_id, b.station_id, c.journeys, c.same_station ORDER BY c.journeys DESC, a.facility_id, b.facility_id` |
| `Q_CREATE_DEPENDS` | `UNWIND $rows AS r MATCH (p:Node:Platform) WHERE p.stop_id = r.stop MATCH (l:Node:Lift {{facility_id:r.fid, cx:p.cx}}) MERGE (p)-[d:{rel} {{dir:r.dir}}]->(l)` |
| `Q_CRITICAL_PAIRS` | `MATCH (a:Node:Lift)-[c:CRITICAL_PAIR]->(b:Node:Lift) WHERE c.scope = 'platform' RETURN a.facility_id, b.facility_id, a.station_id, c.n, c.dirs ORDER BY c.n DESC, a.facility_id, b.facility_id` |
| `Q_DOMINATES_FOR` | `MATCH (l:Node:Lift {facility_id:$fid})-[:DOMINATES_FOR]->(s:Station) RETURN collect(DISTINCT s.uid)` |
| `Q_LIFT_BLAST` | `MATCH (l:Node:Lift) WHERE l.facility_id IN $fids WITH l.facility_id AS fid, head(collect(l)) AS l RETURN fid, l.name, l.station_id, l.od_cut_base, l.od_cut_off, l.od_slow_base, l.detour_max_s, l.detour_mean_s ORDER BY fid` |
| `Q_LIFT_COMPLEXES` | `MATCH (l:Node:Lift) WHERE l.facility_id IN $fids RETURN collect(DISTINCT l.cx)` |
| `Q_LIFT_HISTORY` | `MATCH (l:Lift {facility_id:$fid})-[:CLOSED_IN]->(i:Incident) RETURN DISTINCT i.alert_id, i.effect, i.header, i.started, i.first_seen, i.last_seen, i.ongoing, i.ended_by, i.versions ORDER BY i.first_seen` |
| `Q_LIFT_INCIDENT_COUNT` | `MATCH (l:Lift {facility_id:$fid}) OPTIONAL MATCH (l)-[:CLOSED_IN]->(i:Incident) RETURN count(DISTINCT i)` |
| `Q_LIFT_INFO` | `MATCH (l:Lift {facility_id:$fid}) RETURN l.facility_id, l.name, l.short_name, l.station_id, l.cx, l.modelled, coalesce(l.closed, false) LIMIT 1` |
| `Q_LIFT_RECORD` | `MATCH (l:Lift) WHERE l.facility_id = $fid WITH l ORDER BY l.uid LIMIT 1 OPTIONAL MATCH (o:Outage)-[:OF]->(l) RETURN l.avail_12m, l.closed_h_12m, l.outages_12m, l.mttr_h, l.single_svc_h, count(o), sum(o.hours), max(o.end), sum(CASE WHEN o.imputed THEN 1 ELSE 0 END)` |
| `Q_LOST_NOW` | `MATCH (p:Node:Platform) WHERE (p.k_board = 0 AND (p.k_board_base > 0 OR p.at_grade_board)) OR (p.k_exit = 0 AND (p.k_exit_base > 0 OR p.at_grade_exit)) RETURN p.stop_id, p.name, p.platform_name, p.station_id, p.k_board, p.k_exit, p.deps_day` |
| `Q_MAXFLOW` | `MATCH (s:Node) WHERE s.uid IN $src WITH collect(s) AS S MATCH (t:Node) WHERE t.uid IN $dst WITH S, collect(t) AS T CALL algo.maxFlow({sourceNodes:S, targetNodes:T, relationshipTypes:['SF'], capacityProperty:'cap'}) YIELD edges, edgeFlows, maxFlow RETURN [e IN edges \| e.eid], edgeFlows, maxFlow` |
| `Q_META` | `MATCH (m:Meta) RETURN m.snapshot_id, m.seed_sha256 LIMIT 1` |
| `Q_MODELLED_LIFTS` | `MATCH (l:Node:Lift) WHERE l.facility_id IN $fids RETURN collect(DISTINCT l.facility_id)` |
| `Q_NETWORK_SPOF` | `MATCH (l:Node:Lift) WHERE l.od_cut_base > 0 WITH l.facility_id AS fid, head(collect(l)) AS l RETURN fid, l.name, l.station_id, l.od_cut_base, l.od_cut_off ORDER BY l.od_cut_base DESC, fid` |
| `Q_NEWLY_LAST` | `MATCH (p:Node:Platform)-[n:DEPENDS_NOW]->(l:Lift) WHERE NOT (p)-[:DEPENDS_ON {dir:n.dir}]->(l) RETURN l.facility_id, l.name, l.station_id, collect(DISTINCT p.stop_id + ' ' + n.dir)` |
| `Q_PAIR_OVERLAP` | `MATCH (x:Outage)-[:OF]->(a:Lift {facility_id:$a}) MATCH (y:Outage)-[:OF]->(b:Lift {facility_id:$b}) WHERE x.start < y.end AND y.start < x.end RETURN count(*), collect([CASE WHEN x.start > y.start THEN x.start ELSE y.start END, CASE WHEN x.end < y.end THEN x.end ELSE y.end END])[0..20]` |
| `Q_PLATFORM_CUTS` | `MATCH (p:Node:Platform {cx:$cx}) RETURN p.stop_id AS stop, head(collect(p.mincuts_board)), head(collect(p.mincuts_exit)), head(collect(p.rel_counts_board)), head(collect(p.rel_counts_exit)), head(collect(p.rel_relevant_board)), head(collect(p.rel_relevant_exit)) ORDER BY stop` |
| `Q_PRIORITY` | `MATCH (p:Node:Platform)-[d:DEPENDS_NOW]->(l:Lift) OPTIONAL MATCH (p)-[o:DEPENDS_ON]->(l) WHERE o.dir = d.dir WITH l, p, d, count(o) AS before WITH l, count(DISTINCT p.stop_id + d.dir) AS deps, sum(p.deps_day) AS departures, toInteger(sum(CASE WHEN before = 0 THEN 1 ELSE 0 END)) AS newly OPTIONAL MATCH (l)-[:CLOSED_IN]->(i:Incident) WITH l, deps, departures, newly, count(DISTINCT i) AS incidents RETURN l.facility_id, l.name, l.station_id, coalesce(l.closed, false), deps, newly, departures, incidents` |
| `Q_REACHES_FROM` | `MATCH (a:Station {uid:$sid})-[r:REACHES]->(b:Station) RETURN b.uid, b.name, r.base_s ORDER BY r.base_s, b.uid` |
| `Q_REOPEN_LIFTS` | `MATCH (i:Lift)-[r:SF_CLOSED]->(o) WHERE NOT i.facility_id IN $fids CREATE (i)-[c:SF]->(o) SET c = properties(r), i.closed = false DELETE r RETURN count(c)` |
| `Q_ROUTE_CHECK_RIDE` | `UNWIND $pairs AS p MATCH (a:Platform {uid:p[0]})-[e:RIDE]->(b:Platform {uid:p[1]}) RETURN a.uid, b.uid, e.wt` |
| `Q_ROUTE_CHECK_SF` | `UNWIND $pairs AS p MATCH (a:Node {uid:p[0]})-[e:SF]->(b:Node {uid:p[1]}) RETURN a.uid, b.uid, e.wt` |
| `Q_ROUTE_EDGES` | `MATCH (a)-[e:SF\|RIDE]->(b) RETURN a.uid, b.uid, e.eid, type(e), e.kind, e.wt, e.facility_id, e.routes` |
| `Q_ROUTE_NODES` | `MATCH (n) WHERE n:Node OR n:Platform RETURN n.uid, labels(n), n.name, n.station_id, n.platform_name, n.short_name` |
| `Q_SET_PLATFORM_NOW` | `MATCH (p:Node:Platform) WHERE p.stop_id = $stop SET p.k_board = $kb, p.k_exit = $ke, p.at_grade_board_now = $ab, p.at_grade_exit_now = $ae, p.cut_board_now = $cb, p.cut_exit_now = $ce` |
| `Q_STATION` | `MATCH (s:Station {uid:$sid}) RETURN s.uid, s.name, s.cx, s.has_pathways, s.has_street` |
| `Q_STATION_EDGES` | `MATCH (a:Node {cx:$cx})-[e]->(b:Node) WHERE type(e) IN ['SF','SF_CLOSED','STEP'] RETURN e.eid, a.uid, b.uid, type(e), e.kind, e.facility_id, e.pathway_ids` |
| `Q_STATION_NODES` | `MATCH (n:Node {cx:$cx}) RETURN n.uid, labels(n), n.name, n.platform_name, n.facility_id, n.unit, coalesce(n.closed, false), n.stop_id, n.wheelchair_boarding` |
| `Q_STATION_PLATFORMS` | `MATCH (p:Node:Platform {cx:$cx}) RETURN p.stop_id AS stop, collect(p.uid), head(collect(p.name)), head(collect(p.platform_name)), min(p.k_board), min(p.k_exit), min(p.k_board_base), min(p.k_exit_base), head(collect(p.at_grade_board)), head(collect(p.at_grade_exit)), head(collect(p.at_grade_board_now)), head(collect(p.at_grade_exit_now)), head(collect(p.cut_board_now)), head(collect(p.cut_exit_now)), coalesce(head(collect(p.no_accessible_entrance)), false) ORDER BY stop` |
| `Q_STATION_SEARCH` | `CALL db.idx.fulltext.queryNodes('Station', $q) YIELD node, score RETURN node.uid, node.name, node.has_pathways, node.has_street, score ORDER BY score DESC, node.uid LIMIT 5` |
| `Q_STATION_UNMODELLED_LIFTS` | `MATCH (l:Lift) WHERE l.station_id = $sid AND NOT l:Node RETURN l.facility_id, l.name ORDER BY l.facility_id` |
| `Q_WRITE_INCIDENTS` | `UNWIND $rows AS r CREATE (i:Incident) SET i = r.p WITH i, r UNWIND r.fids AS fid MATCH (l:Lift {facility_id:fid}) MERGE (l)-[:CLOSED_IN]->(i)` |
<!--/generated-->

</details>

## Run it yourself

Requirements: Python 3.14 (3.12+ works), Node 24, a FalkorDB 4.22 instance (Docker `falkordb/falkordb-server:v4.22.0`, or FalkorDB Cloud).

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt     # Windows: .venv\Scripts\python
.venv/bin/python dev.py doctor                               # checks Python, FalkorDB and .env key names
.venv/bin/python -m lastlift.seed --verify                   # load the committed snapshot into FalkorDB
.venv/bin/python -m uvicorn lastlift.main:app --port 8000    # API, MCP at /mcp/, agent at /api/ask
cd web && npm ci && npm run dev                              # website (VITE_API_BASE=http://localhost:8000)
```

No API key is needed: without an LLM key the agent answers through its deterministic template. The website shows the frozen demo alerts by default; its **Live** toggle switches to the `live` scope, which follows the MBTA's current alerts when the server runs with `LIVE_FEED=on` (polled every `LIVE_POLL_S` seconds; `GET /v1/live` reports the last poll and marks it stale after five minutes) and otherwise uses the latest committed alert harvest. Configuration comes from environment variables or a `.env` file one level above the repository (names in `.env.example`); secrets are never committed.

**Reproduce every number:** `python scripts/analyze.py` (the max-flow sweep in FalkorDB), `python scripts/verify_claims.py` (an independent NetworkX re-derivation), `python scripts/eval.py` (the validation), `python scripts/readme_sync.py --check` (this README against `claims.json`).

## What we assume, and where the model can be wrong

- Fare gates are passable for riders who need step-free access; only reaching the platform is modelled, not boarding the train; widths and surfaces are not in the data.
- MBTA publishes no level data; the station drawings infer levels from lift and stair connections.
- Where MBTA publishes no station layout (many commuter-rail stations), LastLift says it cannot assess.
- Lift status comes from MBTA's alerts, which can differ from a lift's actual state. The judged demo uses alerts frozen on 15 Oct 2026.
- Five evidence-backed overrides correct the published layout, and a self-audit of the feed found more: [docs/QUALITY.md](docs/QUALITY.md#we-found-defects-in-the-published-data).

## Data, licence and attribution

Code: MIT. Data: MBTA GTFS (feed "<!--claim:feed_version-->Fall 2026, 2026-10-14T18:47:38+00:00, version D<!--/claim-->") and MBTA V3 API alerts, Massachusetts Department of Transportation open data, used under the MassDOT Developers License Agreement. LastLift is unofficial and not affiliated with or endorsed by the MBTA or MassDOT.

## AI assistance

This project was built with the help of an AI coding assistant. Design decisions and the final review are the author's own. In the demo video, the narration is the author's own voice and every number and screen comes from the project's data and renders; a few short background shots were generated with Kling. The validation keys (`validation/gold_live_author.csv` and `validation/gold_history_author.csv`) were labelled by the author, blind, from MBTA's alert text only; a second label set made by the AI assistant (`validation/gold_live.csv`) is kept only to report labeller agreement.

## Credits

The `algo.maxFlow` defect reproduction is credited to the Chokepoint project. Built on FalkorDB, FastAPI, FastMCP, NetworkX, React, Vite, deck.gl, MapLibre and three.js. The walkthrough's materials and lighting are CC0 scans from Poly Haven.

## Feedback

Found a problem with a route or a station? [Report an accessibility problem with LastLift](../../issues/new?template=accessibility-problem.yml) (every field is optional). Prefer not to post publicly? Email mrslvt.dev@gmail.com. How LastLift handles people's experiences is set out in [docs/ETHICS.md](docs/ETHICS.md).
