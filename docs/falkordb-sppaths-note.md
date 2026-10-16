# `algo.SPpaths` on FalkorDB 4.22.0: why LastLift routes with Dijkstra

**Observed (FalkorDB Cloud, 4.22.0, 2 graph threads, 16 Oct 2026):**

| Call | Graph | Result |
|---|---|---|
| `SPpaths` South Station street → Alewife street, `relTypes:['SF','RIDE']`, `weightProp:'wt'`, `pathCount:1`, `maxLen:60` | 3,720 nodes, 11,870 edges | still running after **~8 h** (2.86e7 ms in `GRAPH.INFO`) |
| `SPpaths` Revere Beach platform 70058 → street, same rel types, `pathCount:2`, `maxLen:250` | same | still running after ~8 h |
| `SPpaths` South Station street → platform 70080, `relTypes:['SF']` only, `costProp:'wt'`, `maxCost:626` (the true optimum), `maxLen:23`, `pathCount:1` | one station complex, 193 nodes | still running after > 3 min |

- Both server threads were held, so every later query queued (`Max pending queries exceeded`) until the instance was rebooted.
- The runaway calls were **not stopped by the query timeout**. The third call ran past `TIMEOUT_MAX 30000` and a 5,000 ms per-query timeout. So the timeout does not bound this procedure; one call can pin a small instance indefinitely.
- The likely cause is that `SPpaths` enumerates simple paths within its bounds rather than running a label-setting search. Station complexes are dense with short cycles (walkways in both directions, parallel corridors), so even a tight `maxCost` leaves a very large number of partial paths.

**What LastLift does instead (`lastlift/routing.py`):**
1. It reads the step-free (`SF`) and train (`RIDE`) edges from FalkorDB once per process. The closed set is read from the scope graph on every call.
2. It runs Dijkstra in Python: under 10 ms for South Station → Alewife. Tests check it against NetworkX.
3. **Certificate:** every edge of the returned route is re-read from the live scope graph with indexed `MATCH`es (`Q_ROUTE_CHECK_SF`, `Q_ROUTE_CHECK_RIDE`). The route is certified only if each edge exists, is open (`SF`, not `SF_CLOSED`) and has the weight used. A route through a closed lift is rejected (`tests/test_tools.py`).
4. No request path calls `SPpaths`.

**Deployment guard regardless:** `deploy/falkordb.args` sets `TIMEOUT_DEFAULT 15000 TIMEOUT_MAX 30000`. These do not stop `SPpaths` (above), so the code never calls it.

Upstream report: not filed yet. It will be filed only with the author's approval, alongside the maxFlow note (`docs/falkordb-maxflow-note.md`).
