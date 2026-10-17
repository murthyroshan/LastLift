"""Seal the recorded replays with their hash chain (lastlift/agent/replay.py). Run once for replays recorded before
chaining existed; record_replays.py seals new ones itself. Events are not changed, only `chain` and `head` added.

    python scripts/seal_replays.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift.agent import replay  # noqa: E402


def main():
    for p in sorted(replay.REPLAY_DIR.glob("*.json")):
        if p.stem == "index":
            continue
        rec = json.loads(p.read_text(encoding="utf-8"))
        replay.seal(rec)
        p.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(p.stem, rec["head"][:16])
    return 0


if __name__ == "__main__":
    sys.exit(main())
