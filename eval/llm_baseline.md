# Graph versus no graph: baselines (pre-registered)

Committed before any baseline is run. Results are reported as they come; if a baseline does well, the README
says so.

## B-COUNT: count the lifts

Rule: a platform is a single point of failure if its station has exactly one lift. Scored against the certified
max-flow result for every assessed platform (the count of platforms the rule gets wrong, both ways). This is the
"naive" view the README contrasts with max-flow.

## B-BFS: reachability only

Analytic, not run: a reachability check answers "is there a step-free path now?". Finding every single point of
failure needs one re-run per lift per platform-direction, and finding pairs needs one per pair. The counts are
computed from the snapshot (`eval/baselines.py`) and reported next to the single max-flow call per
platform-direction that LastLift makes.

## B-LLM: a language model reads the station's pathways

- **Sample:** 30 platform-directions, stratified by station size (small and medium stations; stations with more than
  150 pathway rows are skipped to fit the context and the 8K tokens-per-minute limit), drawn with the seed in
  `eval/sampling.json`.
- **Model:** `gemini-3.1-flash-lite` (to keep the main model's daily budget for the agent evaluation), temperature 0.
- **Prompt (fixed):** the station's `pathways.txt` rows and stop names as CSV, then: "A rider who needs step-free
  access is on platform X. How many elevators must fail before they can no longer leave the platform step-free,
  and which elevators are those? Answer with a number and a list of elevator ids."
- **Scoring:** exact k (the number) and exact cut set (the elevator ids) against the certified result. Both rates
  with Wilson 95% intervals. Malformed answers count as wrong.
- **Artefacts:** every prompt and raw output is cached and committed (`eval/results/llm_baseline/`).
