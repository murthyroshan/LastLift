# Agent evaluation protocol (pre-registered)

Committed together with `eval/gold_questions.yaml` **before the first evaluation run**; the git history shows the
order. Any later change is an amendment in a new commit with its reason, made before the run it affects.

## Question set

30 questions in 8 categories (`eval/gold_questions.yaml`): closure impact 6, redundancy 4, what-if 4, reroute 4,
priority 3, must-abstain 3, adversarial 3, multi-intent / paraphrase 3. Wording drafted by the AI coding
assistant and approved by the author; gold ids and verdicts are the certified graph state of the frozen demo
scope (re-derived independently by `scripts/verify_claims.py`).

## Systems (same 30 questions, temperature 0, pinned snapshot and demo scope)

1. **Full agent:** Groq `qwen/qwen3.8-27b` + the eight MCP tools + the grounding validator (as shipped).
2. **Router + templates:** no LLM, zero tokens (as shipped when the LLM is off).
3. **LLM only, no graph:** the same model, given the alert headers and the station list but **no tools**. This is
   the "turn FalkorDB off" ablation.
4. **Fallback model:** `openai/gpt-oss-120b` on a fixed subset of 12 questions (seeded, `eval/sampling.json`).

## Metrics (deterministic scoring; Wilson 95% interval on every proportion)

- tool-set accuracy: every `required_tools` called and no `forbidden_tools`;
- id accuracy: every `gold_ids` entry appears in the shipped answer or its cited tool results;
- verdict accuracy against `gold_verdicts`;
- **false-accessible count**: an answer that says a platform-direction is reachable where the gold says `lost`
  (the headline safety metric);
- abstention correctness on `must_abstain` rows (and no abstention elsewhere);
- forbidden-claim count;
- raw LLM ungrounded-claim rate before validation, and shipped ungrounded claims after it;
- fallback rate; p50 / p95 latency; tokens in and out per question;
- MCP-versus-direct equality: every tool result through MCP equals the same call made directly.

**Human audit:** the author reads 20 shipped answers (sampled with the fixed seed) and marks each correct /
partially correct / wrong with a one-line reason. These marks are the author's own.

## Run

- Once, on 17 Oct 2026 (IST), at no more than 2 questions a minute (`eval/run.py`), pacing from the provider's
  rate-limit headers. Token plan: about 105K for the full agent and 36K for the LLM-only baseline.
- Development runs use the router or the fallback model, never the scored run's budget.
- Outputs: `eval/results/<date>.json`, a README table generated from it, `GET /v1/eval/latest`.
- Acceptance: `python eval/run.py --system router` reproduces byte for byte.

## Framing committed before the run

- The router will probably match the full agent on verdicts; the LLM's value should show on the multi-intent and
  paraphrase rows and in wording.
- The graph's value is the gap between systems 1-2 and system 3.
- Whatever the numbers are, they are reported as they come, including if the LLM-only baseline does well.
