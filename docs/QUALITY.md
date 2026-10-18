# Quality, security, accessibility and the walkthrough

Every number here comes from `claims.json` (checked by `scripts/readme_sync.py --check`). Back to the [README](../README.md).

## Security and safeguards

- **Agents cannot act on their own.** No language model is given a write tool. Repair and protect tickets need a person's approval with an `Idempotency-Key`; filing is off by default (`ACTIONS_MODE=draft`) and, when switched on, accepted only from the operator's own machine.
- **Stale beliefs cannot act.** A proposal goes through only if the graph's `state_version` has not changed since it was made.
- **Grounding gate.** An id or number in an answer that is not in a tool result sends the answer back to a template built from the tool results; questions about anything but step-free access get the scope answer.
- **Spend caps.** Daily LLM call and token budgets; past them the agent answers from templates.
- **Website headers** ([`web/vercel.json`](../web/vercel.json)): a content security policy that allows the app's own scripts only, HSTS, `nosniff`, a strict referrer policy and a permissions policy. The browser tests run under the same headers.
- **Secrets** live only in the environment; a pre-commit and pre-push scan ([`scripts/secret_scan.py`](../scripts/secret_scan.py)) blocks keys, wrong authors and banned wording.

## Tests and quality

| Check | What it proves |
|---|---|
| `pytest` | Tools, agents, approvals, MCP surface, memory, recorded runs, the evaluation reproducing byte for byte, README and claims |
| Playwright (`web/tests/`) | 34 browser tests: every page from FalkorDB's precomputed snapshot with the API blocked, axe in light and dark at 320 and 1280 pixels, keyboard-only use, eyes-free mode |
| `scripts/verify_claims.py` | Every headline number re-derived from the snapshot with NetworkX alone |
| `scripts/verify_replays.py` | Recorded agent runs re-executed against the graph; a stale fact fails the build |
| `scripts/readme_sync.py --check` | Every number in this README comes from `claims.json`, every table from the code |
| `scripts/copy_lint.py` | No user-facing text says what LastLift cannot know |
| `scripts/latency.py --prod` | End-to-end answer time of the deployed agent over ten questions. Last run, on the free tiers: median 7.9 s, 95th percentile 19.4 s; 7 of 10 answered by the language model, the rest by the grounded template. Most of the wait is free-tier rate limiting (19 model failovers in that run); answers that need no model return in about a second |

## Built for the people it is about

- Every state is shown as a glyph, a number and a word, never colour alone; "good" is blue, never green.
- The station drawing is decorative for assistive technology; the platform, lift and route tables say the same in words.
- Hear it: a station's routes play as a chord (one tone per independent route, a trembling tone when one lift is left), and "Hear a line" plays a whole line station by station; every sound has a text twin and nothing plays before you press play.
- Atkinson Hyperlegible type, a two-tone focus ring, 44-pixel targets, reflow at 320 pixels, reduced-motion and forced-colours support.
- CI runs axe on every core screen in light and dark themes with the API blocked, plus keyboard-only and 320-pixel checks (`web/tests/a11y.spec.ts`).
- Wording rules and exact disclaimers are enforced by a lint ([`lastlift/wording.py`](../lastlift/wording.py)); see [`docs/ETHICS.md`](ETHICS.md). Not yet reviewed by disabled riders; designed for that review.

## Walk through Alewife

[`/concepts/alewife.html`](https://lastlift.vercel.app/concepts/alewife.html) is a seated first-person walkthrough of a platform like Alewife's, built in three.js from photo-scanned CC0 materials and a real metro HDRI (credits in [`web/public/world/CREDITS.md`](../web/public/world/CREDITS.md)). The station is drawn for the game; the lifts, the closure and the numbers on its results screens come from LastLift's data.

- **Mission 1:** the train pulls out; lift 961 is taped off; find lift 813 and ride it up.
- **Mission 2:** lift 813 fails in front of you. With both lifts out there is no step-free way off the platform, and the only way out is the train back to Davis.
- W and S roll, A and D turn, the mouse looks, E uses; touch controls on phones. Add `?autoplay` to watch mission 2 play itself.

## We found defects in the published data

Five overrides correct the published layout, each with evidence ([`data/overrides.csv`](../data/overrides.csv)): centre platforms at Sullivan Square and Wellington that the data joined to the side platforms (which made them look reachable when they are not), two Quincy Adams pathways tagged with the wrong elevator, and a Copley entrance.

A self-audit of the feed (`scripts/gtfs_audit.py`) found <!--claim:audit_items-->8<!--/claim--> kinds of possible issue that matter for step-free routing, from swapped elevator ids at South Station to `excludes-stop` values that contradict the pathways; MobilityData's gtfs-validator (<!--claim:audit_validator_version-->8.0.1<!--/claim-->) was run first and flags none of them. The write-up, with evidence rows, is [`docs/mbta_data_report.md`](mbta_data_report.md). _Reported to MBTA's developer contact: to be added by the author._
