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

## Amendment 1 (17 Oct 2026, before run 2)

**What happened in run 1.** The harness paced at 2 questions a minute but did not pace by tokens. Groq limits each
chat model to 8,000 tokens a minute, and a full-agent question uses about 5,800, so the models were rate-limited and
the provider chain (added after pre-registration, M6) failed over: of the full agent's 30 answers, qwen wrote 9,
gpt-oss-120b 13 and the template 8; the fallback system's 12 answers were 6 gpt-oss and 6 template; the LLM-only
system stopped at its first question. Run 1 therefore does not measure the systems named above.

**Change.** The harness now also paces by tokens (each question waits at least 60 x tokens used / 8,000 seconds),
waits out a rate limit of up to 60 s instead of failing over, for all three LLM systems, and records the serving model
of every answer. Questions, gold, systems, metrics and scoring are unchanged.

**Reporting.** Run 1 is kept and published as is (`eval/results/full_run1_rate_limited.json`,
`fallback_run1_rate_limited.json`), next to run 2. Run 2 is the scored run; any answer in it not written by the
system's named model is counted and reported.

## Amendment 2 (17 Oct 2026, before run 3)

**What happened in run 2.** Groq's free tier also limits each model per day: qwen `qwen/qwen3.8-27b` reached its
200,000 tokens-per-day limit (rolling 24 h) during the morning's runs, and `openai/gpt-oss-120b` reached its own. In
run 2 the full agent's 30 answers were written by gpt-oss-120b (19) and the template (11), none by qwen; the
LLM-only system stopped at its first question; the fallback system's 12 were Gemini (7) and the template (5). On
this tier, qwen cannot serve both the full agent (about 6,000 tokens a question over 2-4 calls) and the LLM-only
ablation within one day.

**Change.** Run 3 puts both arms of the ablation on one model with room in its free tier,
`gemini-3.1-flash-lite` (Google): the full agent (the same MCP tools, grounding validator and template fallback, with
the provider chain pinned to this model) and the LLM-only system (the same model, alert headers and station list,
no tools). Questions, gold, scoring and metrics are unchanged; `eval/gold_errata.md` lists one gold correction (Q25),
reported both ways. Pacing uses Gemini's per-minute limit. A provider error now fails that question, not the run.

**Reporting.** Runs 1 and 2 are kept and published as they are, with the serving model of every answer. Run 3 is the
scored comparison of the graph against no graph; the router system (no LLM) is unchanged and reproducible.
