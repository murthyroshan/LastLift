"""Record the curated agent runs (the film's story beats) to web/public/replay/<id>.json.

    python scripts/record_replays.py              # LLM_MODE from config (live needs GROQ_API_KEY)
    python scripts/record_replays.py --mode off   # router + template only

Each file holds every event of the run, the answer and its source (llm or template). The tool facts are
digested so scripts/verify_replays.py can re-execute them and prove they have not drifted.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift.agent import llm, loop, replay  # noqa: E402

llm.RETRY_WAIT_S = 60    # recording can wait out a per-minute token limit; live users never wait this long

CURATED = [
    ("revere-board", "Can I get step-free onto the Wonderland-bound platform at Revere Beach right now?"),
    ("chinatown", "Is Chinatown step-free right now?"),
    ("alewife-813", "What changed at Alewife now that lift 961 is closed?"),
    ("whatif-813", "What happens if lift 813 fails too?"),
    ("priority", "Which lifts should be repaired or protected first?"),
    ("worcester-782", "Elevator 782 at Worcester is out. Who is affected?"),
    ("route-sstat-alfcl", "I need to get from South Station to Alewife step-free today. Which lifts does that depend on?"),
]


async def main(mode, pause, only):
    replay.REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    index = []
    for rid, question in CURATED:
        if only and rid not in only:            # keep the existing recording
            old = replay.load(rid)
            index.append({"id": rid, "question": question, "source": old["source"]})
            continue
        r = await loop.ask(question, scope="demo", mode=mode)
        rec = {"id": rid, "question": question, "schema": "contracts/ask_events.schema.json",
               "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "answer": r["answer"], "source": r["source"], "events": r["events"]}
        replay.seal(rec)
        (replay.REPLAY_DIR / f"{rid}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                                                       encoding="utf-8", newline="\n")
        index.append({"id": rid, "question": question, "source": r["source"]})
        print(f"{rid}: {r['source']}, {len([e for e in r['events'] if e['type'] == 'tool_call'])} tool calls", flush=True)
        if pause:
            await asyncio.sleep(pause)      # stay under the LLM's per-minute token limit
    (replay.REPLAY_DIR / "index.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default=None, help="live | off (default: LLM_MODE)")
    ap.add_argument("--pause", type=int, default=0, help="seconds between runs (live: ~65 for the free tier)")
    ap.add_argument("--only", nargs="*", default=None, help="re-record only these ids")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.mode, a.pause, set(a.only or []))))
