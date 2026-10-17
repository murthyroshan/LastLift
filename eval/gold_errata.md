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
