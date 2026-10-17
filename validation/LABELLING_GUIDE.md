# Labelling guide (live gold set)

**Provenance.** There are two label sets for the 14 live alerts, both made from MBTA's alert text only
and both committed before the evaluation (`scripts/eval.py`) was first run, as the git history shows:

- `gold_live_author.csv`: labelled blind by the author. **This is the evaluation key.**
- `gold_live.csv`: labelled by an AI coding assistant. Kept only to report labeller agreement (Cohen's kappa);
  never used to score the model.

Each labeller labels every row **from MBTA's alert text only** (`mbta_text`), without looking at LastLift's
output. Labels are committed before the evaluation runs, and are never edited afterwards (corrections go
in an errata file with reasons).

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

## Static sweep (`static_prefill.csv`, `gold_static.csv`)

MBTA publishes, for most elevators, a short text saying what riders should do while that elevator is out
(`alternate-service-text`). That text is licensed for internal use only: it is used here to validate,
never displayed and never committed.

1. `python scripts/static_sweep.py` writes your sheet to `validation/_private/static_review.csv`
   (gitignored). Each row has MBTA's text and a regex pre-fill. **The sheet never shows the model's verdict.**
2. For every row with `review_required = Y`, read the text and fill `author_board_class`,
   `author_exit_class`, `author_named_elevators` and `author_verdict` with the same vocabulary as above,
   correcting the pre-fill wherever it is wrong. Add `author_notes` for anything ambiguous.
3. `python scripts/static_sweep.py --make-gold` writes `gold_static.csv`: your labels for the flagged rows,
   the pre-fill for the rest (marked "regex prefill, not reviewed"), and a sha256 of each text, never the
   text itself. Commit it before running `python scripts/eval.py`.

Only your reviewed rows count towards the static agreement figure. Unreviewed rows were left unreviewed
because their pre-fill matched the model, so they are not evidence of agreement.
