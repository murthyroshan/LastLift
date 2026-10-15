# algo.maxFlow on FalkorDB 4.22: what we observed and how LastLift guards against it

**Credit:** the defect was found and minimised by the Chokepoint project
(https://github.com/Hackmaass/Chokepoint), another Graph Hacks entry. We reproduced their case on our
own FalkorDB 4.22.0 instance and built LastLift so that a wrong max-flow can never reach a rider.

## Reproduction on our instance
Chokepoint's 11-edge node-split network (source `src:out`, sink `x1:in`, capacity property `cap`):
the true maximum flow is **453** (300 via `a20`, 153 via `a3 -> a12`; confirmed with NetworkX and
our own exact solver). `algo.maxFlow` on FalkorDB Cloud 4.22.0 returned **300**.

`tests/test_flow.py::test_falkordb_maxflow_on_known_repro` runs this case against a live FalkorDB and
is marked as an expected failure (strict). If a future FalkorDB release fixes the defect, that test
starts passing and CI flags it.

## Rate on networks shaped like LastLift's
In our hour-1 smoke tests (60 random node-split networks with capacity-1 lifts and 1,000,000-capacity
walkways), FalkorDB returned a wrong value once. On the real MBTA network, every one of the
734 platform-direction sweeps was certified exact on the first pass (see `claims.json`:
`falkordb_first_pass_exact`, `falkordb_repaired`).

## Single relationship type
On 4.22.0, `algo.maxFlow` accepts exactly one entry in `relationshipTypes` ("should contain a single
string"), and rejects parallel edges of that type. LastLift therefore puts every step-free move on one
relationship type (`SF`) and merges parallel edges at build time (verified on every load).

## How LastLift guards every number
1. **Certify** the returned flow (`lastlift/flow.py`): capacities respected, flow conserved at inner
   nodes, and no source-to-sink path left in the residual graph. A flow that passes is provably maximum.
2. **Repair** if certification fails: re-solve exactly (Dinic) on the same edges.
3. **Prove** each finite k (`lastlift/checker.py`): k lift-disjoint routes plus a k-lift cut that blocks
   every route. The checker never calls a max-flow; it only checks the proof.
4. **Cross-check** every value against NetworkX from the committed data files
   (`scripts/verify_claims.py`).
