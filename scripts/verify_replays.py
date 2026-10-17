"""Re-execute every recorded replay's tool calls through the MCP server and fail on any drift.

    python scripts/verify_replays.py
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift.agent import replay  # noqa: E402
from lastlift.mcp_server import mcp  # noqa: E402


async def main():
    index = json.loads((replay.REPLAY_DIR / "index.json").read_text(encoding="utf-8"))
    drifts = []
    for item in index:
        rec = replay.load(item["id"])
        d = await replay.verify(rec, mcp)
        drifts += d
        print(f"{item['id']}: {'OK' if not d else 'DRIFT'}")
    for d in drifts:
        print("DRIFT:", d, file=sys.stderr)
    print(f"{len(index)} replays, {len(drifts)} drift(s)")
    return 1 if drifts else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
