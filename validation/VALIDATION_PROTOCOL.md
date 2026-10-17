# Validation study protocol (pre-registered)

Committed before the study's evaluation runs; the git history shows the order. Labels are never edited after a
run: corrections go to `validation/gold_errata.md` (append-only) with the reason. Any change to this protocol is a
new commit with its reason, made before the run it affects.

## Question

How often does LastLift's open-data model agree with what the MBTA itself tells riders to do when an elevator is
out, and when it disagrees, why?

## Unit of analysis

The (lift, platform, direction) triple, direction = board or exit. Each triple has a binary outcome (step-free
access lost / not lost) and a reroute class.

**Reroute classes** (the labelling vocabulary of `validation/LABELLING_GUIDE.md`): `IN_STATION`,
`RIDE_AND_RETURN`, `OTHER_STATION`, `SHUTTLE_OR_BUS`, `CROSS_THROUGH_TRAIN`, `NOT_STATED`, plus the model's
`NO_ROUTE`.

## Oracles (triangulation)

| Oracle | Source | Use |
|---|---|---|
| O1 alternative-service text | MBTA facility property `alternate-service-text` (V3 API), one text per elevator | primary gold, labelled by the author; licensed for internal use, so never displayed or committed (only its sha256) |
| O2 `excludes-stop` | MBTA facility property | secondary check; disagreements with O1 are adjudicated by O1 |
| O3 live alerts | the 14 frozen alerts of 15 Oct 2026 (already evaluated: `validation/EVALUATION.md`) plus later harvests | stability over time |

## Labelling

1. The author labels, from the text alone and without seeing the model's output:
   - **every** row where the regex pre-fill and the model disagree or the pre-fill is incomplete; and
   - a **stratified random 20% of the rows where they agree** (seed in `eval/sampling.json`), so that the
     precision of the unreviewed agreements can be estimated.
2. Single rater, stated as such. **Intra-rater reliability:** 30 random rows (seeded) are re-labelled blind at least
   12 hours after the first labelling; Cohen's kappa is reported.
3. Freezing: the GTFS sha256, a sha256 per O1 text, the snapshot id, and this protocol's commit.

## Outputs

- A 2x2 table at triple level (model: lost / not lost; MBTA text implies lost / not lost) with sensitivity,
  specificity, PPV and NPV, each with a Wilson 95% interval. Headline: the **false-accessible count** (MBTA implies
  lost, the model says reachable), every case listed.
- A reroute-class confusion matrix.
- Named-lift recall: the share of MBTA-named alternative elevators that appear on the model's alternative routes
  (loose: any route; strict: the top route).
- O2 agreement with O1, every exception listed.
- Any aggregate over platforms gets a station-cluster bootstrap interval (1,000 resamples, seed 20261019), never a
  naive independent-rows interval.

## Error taxonomy

Every disagreement gets exactly one code, and the counts are published:

| Code | Meaning |
|---|---|
| E1 | defect in the published data (for example a pathway tagged with the wrong elevator) |
| E2 | one stop id covers two physical platforms |
| E3 | the advice is about an entrance, not a platform |
| E4 | multimodal advice the model cannot produce (bus, shuttle) |
| E5 | equivalent-route tie: MBTA names a different but equally valid elevator |
| E6 | the oracles contradict each other |
| E7 | pre-fill classifier error |
| E8 | needs a train ride and return, and the model's route differs |
| E9 | a lift that serves no platform |

## Route tie-break, fixed before the study

Where several step-free routes are equally short, the model's route is chosen by: fewest lifts, then lowest summed
traversal time, then fewest level changes. This rule is fixed now. Top-route recall is reported with and without it,
and the rule is not tuned on the gold.
