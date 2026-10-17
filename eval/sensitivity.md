# Sensitivity table (pre-registered specification)

Every headline number that depends on a modelling choice is re-computed with the choice flipped, and the table is
published whatever it shows. Each row names the switch, the headline numbers it can move, and how it is applied.

| Switch | Values | Numbers it can move | How |
|---|---|---|---|
| Fare gates passable | assumed passable / treated as blocking | single-lift and lost platforms | rebuild the snapshot with gate edges excluded from the step-free subgraph |
| Overrides (`data/overrides.csv`) | applied / not applied | single-lift count, false-accessible count | rebuild without the five overrides |
| Platform halves (Sullivan, Wellington) | split / joined | single-lift count | rebuild without OV1 and OV2 |
| Lift units | one per facility per connected component / one per facility | spof lifts | rebuild with the unit split disabled |
| Closure history (when built) | imputed end dates in / out; episode gap 0 / 30 / 120 min; calendar / service hours | lost-hours, single-lift share of lost hours | re-run the replay with each setting |

Rules: the switches are applied one at a time from the committed defaults; no setting is chosen because of its
result; the defaults stay as committed.
