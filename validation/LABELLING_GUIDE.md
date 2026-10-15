# Labelling guide (live gold set)

**Provenance of the current labels:** the 14 rows were labelled by an AI coding assistant working from
MBTA's alert text only, before any LastLift model output for them was produced, and are pending review
by the author (`labelled_by` column). Any row the author changes is noted in `labeller_notes`.

You label each row of `gold_live.csv` **from MBTA's alert text only** (`mbta_text`), before seeing any
LastLift output. The labels are committed first, so the git history proves they came before the model.

Fill these columns; leave every other column untouched.

| Column | What to write |
|---|---|
| `mbta_board_class` | How MBTA says a wheelchair user **boards** while this lift is out: `IN_STATION` (another lift / route in the same station), `RIDE_AND_RETURN` (ride to another station and come back), `CROSS_THROUGH_TRAIN`, `SHUTTLE_OR_BUS`, `OTHER_STATION` (use a different station instead), or `NOT_STATED` |
| `mbta_exit_class` | Same choices, for **exiting** |
| `mbta_named_elevators` | Elevator numbers MBTA names as the alternative, separated by `;` (e.g. `881;884`). Empty if none |
| `mbta_named_stations` | Stations MBTA tells riders to use instead, separated by `;`. Empty if none |
| `exp_verdict` | Your reading of MBTA's text: `LOSS` (some platform loses step-free access inside this station), `NO_LOSS` (an in-station alternative exists for everyone), `ENTRANCE_ONLY` (only an entrance is cut off, platforms still reachable), `CANNOT_ASSESS` (the text doesn't say enough), `OUT_OF_SCOPE` (not about getting to or from a platform, e.g. a parking-lot lift) |
| `labeller_notes` | Anything ambiguous, in your own words |

Tips: "ride to X and come back" or "use X station instead" means `LOSS`. "Use elevator N" in the same
station means `NO_LOSS` for that direction. When unsure, choose `CANNOT_ASSESS` and explain in the notes.
