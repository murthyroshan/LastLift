# The network view, the Atlas, and what FalkorDB does

Every number here comes from `claims.json` (checked by `scripts/readme_sync.py --check`). Back to the [README](../README.md).

## One closed lift, seen across the whole network

A lift can cut a platform off, yet riders may still ride a train to another station and back. So LastLift also asks the network question: which journeys between stations does a closure break?

- **<!--claim:net_platform_spof_lifts-->69<!--/claim--> lifts can each cut a platform off on their own; only <!--claim:net_spof_lifts-->15<!--/claim--> can cut a whole station off from the step-free network** (<!--claim:net_cut_off_stations-->13<!--/claim--> stations; each such closure breaks <!--claim:net_spof_journeys_each-->176<!--/claim--> of the <!--claim:net_od_pairs-->7,832<!--/claim--> journeys between the <!--claim:net_origins-->89<!--/claim--> stations with an accessible entrance). For the other <!--claim:net_rescued_lifts-->54<!--/claim--> the network re-routes riders: median worst detour <!--claim:net_detour_median_min-->11<!--/claim--> min, longest <!--claim:net_detour_max_min-->20.2<!--/claim--> min.
- **How:** dominator trees. Every lift is node-split, so closing it deletes one node; the journeys it breaks from an origin are exactly the stations in that node's dominator subtree. One tree per origin (Cooper-Harvey-Kennedy, on the network contracted to its lift-free strongly connected parts) gives the whole N-1 table in a fraction of a second. A plain search with each lift removed agrees for <!--claim:net_dominator_eq_witness-->198<!--/claim--> of <!--claim:net_dominator_lifts-->198<!--/claim--> lifts, and the tests apply closures in FalkorDB with Cypher and re-read the graph to confirm it.
- **Conditional last lifts:** with one lift closed, its partner can become the only link between a station and the network. There are <!--claim:net_conditional_pairs-->42<!--/claim--> such pairs, and <!--claim:net_conditional_cross_station-->0<!--/claim--> of them span two stations: in the open data the turnaround stations always have a spare. In the demo state, lift 885 is closed, so 884 alone now links Revere Beach to every other station.
- **Critical pairs (N-2):** <!--claim:n2_critical_pairs-->42<!--/claim--> lift pairs are each harmless alone but cut platforms off together; the worst is <!--claim:n2_top_pair-->821+973<!--/claim--> (<!--claim:n2_top_pair_dirs-->18<!--/claim--> platform-directions). Each pair is re-checked in FalkorDB: max-flow 0 with both closed, above 0 with either alone.
- **Every minimum cut, not just one:** for each of the <!--claim:mincut_dirs-->333<!--/claim--> lift-dependent platform-directions, all minimum cuts come from the certified flow's residual graph (Picard-Queyranne); <!--claim:mincut_pq_eq_brute-->333<!--/claim--> equal a brute-force search over every set of lifts, and <!--claim:mincut_multi-->71<!--/claim--> have more than one.
- **Exact reliability:** no platform depends on more than twelve lifts, so the chance of losing access when each lift is out with probability q is computed exactly by enumeration (the station page has a slider). With every lift out <!--claim:rel_q_assumed-->2%<!--/claim--> of the time, about <!--claim:net_mc_reachable_q02-->99%<!--/claim--> of journeys between stations stay step-free (Monte-Carlo, seeded).
- **Repair order:** for the lifts closed now, the order that gives back the most soonest is computed exactly (dynamic programming over subsets) and compared with greedy.
- **Query plans:** `GET /v1/queries/{id}/plan?mode=explain|profile` returns FalkorDB's own plan (profiles run on a private copy; write queries are refused); examples are in [`docs/profiles/`](profiles/).

The Silver Line (SL1-SL5) counts as a ride in this analysis (model rules version 2): Courthouse and World Trade Center are reachable step-free only by it.

## Turn FalkorDB off, and here is exactly what stops working

Everything LastLift computes is computed in FalkorDB: redundancy (`algo.maxFlow` on the step-free subgraph), closures (relationship-type swaps `SF` → `SF_CLOSED`), what-ifs (`GRAPH.COPY` of the live graph, closures applied to the copy), incident memory (`Incident` nodes linked to lifts), the repair ranking (`DEPENDS_ON` / `DEPENDS_NOW` relationships), the station drawings and the route certificates. Stop the database and:

- `/healthz` returns 503 and every tool and the agent answer 503 `graph_unavailable`, never a guess (tested in `tests/test_memory.py`);
- no what-if, reroute, ranking or answer can be produced;
- the website falls back to a frozen copy of the demo state that FalkorDB computed earlier, and says so.

## Does it travel? The Step-Free Atlas

The same rules, with no agency-specific handling, run on every transit agency that publishes GTFS-Pathways with open access in the Mobility Database catalogue: 14 feeds, of which 10 model their lifts well enough to assess. Only the needed files are fetched, by HTTP range reads on each zip ([`ingest/atlas_fetch.py`](../ingest/atlas_fetch.py)). Every lift-dependent platform-direction is solved exactly in Python and again with FalkorDB's `algo.maxFlow` in a temporary graph that is deleted afterwards: 2884 of 2884 agree ([`scripts/atlas_sweep.py`](../scripts/atlas_sweep.py)). Run on the MBTA's feed, the generic rules give the same 89 single-lift platforms as LastLift's own model. Each agency gets a data-readiness grade; agencies are named on the site only after their data licence has been checked: four are, the other ten are counted without their names ([licence table](atlas_licences.md)).
