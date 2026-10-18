"""Operator demo of self-invalidating answers: change one lift's state in a scope, watch every earlier answer that
read it turn stale in the chat, then put the scope back exactly as it was.

    python scripts/demo_stale.py close 813            # closes lift 813 in the demo scope (remembers the old state)
    python scripts/demo_stale.py reopen 961           # or reopen a closed one
    python scripts/demo_stale.py restore              # back to the closed set saved by the first change
    python scripts/demo_stale.py status               # closed lifts now, and whether a restore is pending

Runs against the graph server in your .env (local or cloud), never the public deployment's own graph.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lastlift import state  # noqa: E402

SAVED = Path(tempfile.gettempdir()) / "lastlift_demo_stale.json"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["close", "reopen", "restore", "status"])
    ap.add_argument("facility_id", nargs="?")
    ap.add_argument("--scope", default="demo", choices=["demo", "live"])
    a = ap.parse_args()
    name = state.graph_name(a.scope)
    now = sorted(state.closed(name))
    saved = json.loads(SAVED.read_text()) if SAVED.exists() else None

    if a.action == "status":
        print(f"{name}: closed {now}; restore pending: {bool(saved and saved['graph'] == name)}")
        return
    if a.action == "restore":
        if not saved or saved["graph"] != name:
            sys.exit("nothing to restore for this scope")
        out = state.sync(name, saved["closed"])
        SAVED.unlink()
        print(f"restored {name} to {saved['closed']}; answers made stale: {out['answers_made_stale']}")
        return
    if not a.facility_id:
        sys.exit("give a lift number, e.g. close 813")
    if not saved:                                   # remember the state before the first change only
        SAVED.write_text(json.dumps({"graph": name, "closed": now}))
    want = set(now) | {a.facility_id} if a.action == "close" else set(now) - {a.facility_id}
    out = state.sync(name, sorted(want))
    print(f"{a.action} {a.facility_id} in {name}: changed {out['changed']}; "
          f"answers made stale: {out['answers_made_stale']}. Run 'restore' when done.")


if __name__ == "__main__":
    main()
