# Model rules (frozen, rules_version 2)

Every number LastLift publishes is computed under these rules. Changing a rule bumps `rules_version`
in `ingest/build_snapshot.py`, which changes the snapshot hash and regenerates every claim.

## Source data
- MBTA GTFS, feed version recorded in `data/snapshots/<date>/MANIFEST.json` with the zip's sha256.
- Service day for departures and train-ride edges: the snapshot date (Thursday 2026-10-15).

## What counts as step-free
| GTFS `pathway_mode` | Treated as | Notes |
|---|---|---|
| 1 walkway, 3 moving sidewalk | step-free `walk` | weight = wheelchair traversal time, else traversal time, else length (s) |
| 6 fare gate, 7 exit gate | step-free `gate` | **assumption:** an accessible gate exists in every gate line (stated on every route that uses one) |
| 5 elevator | step-free via a lift unit | see lift units below |
| 2 stairs, 4 escalator | `STEP`, never step-free | kept only to explain "stairs exist here" |

All pathways in the feed are one-directional, so boarding and exiting are separate questions.

## Lift units
- One lift unit per elevator facility **per connected component of that facility's own pathways**.
  Five facilities tag physically separate shafts; splitting them stops the model "teleporting"
  between shafts. Elevator pathways without a facility id get a synthetic `nofac-<stop>` unit.
- Each elevator pathway u→v of unit L becomes `u → lift:L` (access), `lift:L → lift:L:out` (the lift,
  capacity 1) and `lift:L:out → v` (access). Duplicate access edges are merged.

## Flow network
- All step-free movement is one relationship type, `SF`, because FalkorDB 4.22's `algo.maxFlow`
  accepts a single relationship type. Edge `kind` is walk / gate / street / lift_access / lift.
- Capacities: the lift edge is 1; every other `SF` edge is 1,000,000 (`BIG`). A max-flow therefore
  counts lift-disjoint routes; a value of `BIG` or more means "reachable without any lift" (at grade).
- A closed lift's edge is swapped to type `SF_CLOSED`, so every algorithm excludes it by type.
- No parallel `SF` edges exist (verified on every load), as `algo.maxFlow` rejects multi-edges.

## Sources, targets and directions
- One virtual `Street` node per station with at least one accessible entrance
  (`wheelchair_boarding = 1`, plus overrides), linked both ways to those entrances.
- **Board k** of a platform = max-flow from the Street nodes of its complex to the platform.
  **Exit k** = max-flow from the platform to those Street nodes.
- A "platform" is a GTFS stop_id (a direction of service). Platforms with `wheelchair_boarding = 2`
  are never called step-free, whatever k comes out as.
- Complexes: each parent station, except Park Street and Downtown Crossing, which form one complex
  because the Winter St Concourse links them step-free.
- Lift single points of failure are counted in **facilities**, over **both directions**.

## Overrides (`data/overrides.csv`, each with evidence)
1. **Sullivan Square (70031) and Wellington (70033) are split into their two physical halves.**
   Oak Grove trains open on both sides (centre platform and Oak Grove platform); Forest Hills riders
   can only reach the Oak Grove platform by crossing through a waiting train, which is not a
   step-free route. GTFS uses one stop_id for both sides; the split restores the real layout, so
   closing 840/865 cuts Forest Hills riders while Oak Grove riders keep 881/864.
2. **Quincy Adams** pathways `qamnl-060/061` belong to elevator 805 (they were tagged 736).
3. **Copley** entrance `door-coecl-bpl` leads directly to elevator 976 and is a step-free source.

The build fails if any override stops matching the feed.

## Train rides
- `RIDE` edges join consecutive stops of representative trips (route types 0, 1, 2, plus the Silver Line
  bus routes SL1–SL5; typicality 1–2),
  weight = scheduled seconds (min 30). Entering a rail platform costs a 300 s boarding penalty so a
  reroute never rides a train where a short walk exists. Used only for reroutes, never for k.

## Wording
Results describe the open-data model. LastLift says "loses step-free access in the open-data model",
never "stranded", "safe" or a bare "accessible", and says "cannot assess" where pathway data is missing. <!-- copy-lint: quoted -->

## Changes
- **rules_version 2 (M10):** Silver Line SL1–SL5 (GTFS route ids 741, 742, 743, 751, 749) added to `RIDE`.
  Courthouse, World Trade Center and the other Silver Line stations are reachable step-free only by the
  Silver Line, so without it the network analysis would count them as cut off. `is_rail` stays false for
  stops served only by these buses. Redundancy (k) never uses `RIDE`, so no k changes.
