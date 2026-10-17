# Errata to eval/gold_questions.yaml (append-only)

The pre-registered gold set is never edited after a run. Corrections are listed here with their reason, and every
affected metric is reported both as scored and with the correction.

## E1 (17 Oct 2026, found in run 2): Q25's forbidden claims assume lift 999 does not exist

- **Question:** "Lift 999 at Alewife is broken. What should I do?" (adversarial: a lift id that is not at Alewife).
- **Gold as committed:** `forbidden_claims: ["lift 999 is", "Lift 999 is"]`, written on the assumption that no lift
  999 exists.
- **What is true:** elevator 999 exists, at Downtown Crossing (GTFS `facilities.txt`; in the step-free model). The
  correct answer is to say so, for example "Lift 999 is at Downtown Crossing, not Alewife", which the forbidden
  substring wrongly penalises.
- **Correction:** for Q25, the forbidden claim is a statement that places lift 999 at Alewife, or that invents its
  status there. Metrics are reported as scored and corrected.

## S1 (17 Oct 2026, found in run 3): the loss-wording rule missed "cannot access"

- **Rule as run:** a gold "lost" platform-direction counts as stated when the answer contains loss wording
  (lose/lost, no step-free, cannot reach/get, cut off, no route, unavailable).
- **Missed:** "you cannot access the Wonderland platform step-free" (run 3, LLM-only, Q01), which states the loss
  and was counted false-accessible.
- **Correction:** "cannot access" / "can't access" also count. Every run is re-scored from its stored answers with
  the corrected rule (`eval/run.py --rescore`); each result file keeps the first score as `summary_as_scored`.

## Data note (17 Oct 2026, run 3): provider errors re-asked once

In run 3's LLM-only system, 14 of 30 questions got no answer (Gemini timeouts at 30 s, HTTP 503). They were re-asked
once with a 60 s timeout (`eval/run.py --retry-errors`); 10 were answered and 4 still failed, and those 4 count as
unanswered. Each re-asked row keeps its first error (`first_attempt_error`).
