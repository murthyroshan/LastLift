"""Developer commands for LastLift.

  python dev.py doctor     check git identity/hooks, Python, FalkorDB reachability, and .env key names
  python dev.py harvest    import accessibility alerts from the local collector archive into data/alerts/
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AUTHOR_NAME, AUTHOR_EMAIL = "murthyroshan", "mrslvt.dev@gmail.com"
REQUIRED_KEYS = ["FALKORDB_HOST", "FALKORDB_PORT", "FALKORDB_USERNAME", "FALKORDB_PASSWORD",
                 "GROQ_API_KEY", "GEMINI_API_KEY", "MBTA_API_KEY"]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def check(label, ok, detail=""):
    print(f"[{'ok' if ok else 'FIX'}] {label}" + (f": {detail}" if detail else ""))
    return ok


def doctor():
    results = [
        check("git user.name", git("config", "--local", "user.name") == AUTHOR_NAME),
        check("git user.email", git("config", "--local", "user.email") == AUTHOR_EMAIL),
        check("git user.useConfigOnly", git("config", "--local", "user.useConfigOnly") == "true"),
        check("git hooks path", git("config", "--local", "core.hooksPath") == ".githooks"),
        check("python >= 3.12", sys.version_info >= (3, 12), sys.version.split()[0]),
    ]
    env_file = ROOT.parent / ".env"
    if check(".env outside repo", env_file.is_file(), str(env_file)):
        keys = {line.split("=", 1)[0].strip() for line in env_file.read_text(encoding="utf-8-sig").splitlines()
                if "=" in line and not line.lstrip().startswith("#") and line.split("=", 1)[1].strip()}
        missing = [k for k in REQUIRED_KEYS if k not in keys]
        results.append(check("required .env keys present (names only)", not missing, ", ".join(missing) or "all set"))
    try:
        sys.path.insert(0, str(ROOT))
        from lastlift import db
        up = db.ping()
        results.append(check("FalkorDB reachable", up, db.module_version() or "unreachable"))
    except Exception as e:  # report the problem type only
        results.append(check("FalkorDB reachable", False, type(e).__name__))
    return 0 if all(results) else 1


ARCHIVE = ROOT.parent / "_alert_archive"
ALERTS_OUT = ROOT / "data" / "alerts"


def harvest():
    """Copy accessibility-alert versions from the collector archive (outside the repo) into
    data/alerts/accessibility_alert_versions.jsonl. Idempotent and deterministic: one row per
    (alert id, content hash), sorted by first capture time then id; re-running adds only new versions."""
    src = ARCHIVE / "alert_versions.jsonl"
    if not src.is_file():
        print(f"no collector archive at {src}")
        return 1
    rows = {}
    for line in src.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not rec.get("accessibility"):
            continue
        key = (rec["alert"]["id"], rec["sha256"])
        if key not in rows or rec["captured_at"] < rows[key]["captured_at"]:
            rows[key] = {"captured_at": rec["captured_at"], "sha256": rec["sha256"],
                         "facility_types": rec.get("facility_types", {}), "alert": rec["alert"]}
    ALERTS_OUT.mkdir(parents=True, exist_ok=True)
    out = ALERTS_OUT / "accessibility_alert_versions.jsonl"
    ordered = sorted(rows.values(), key=lambda r: (r["captured_at"], r["alert"]["id"], r["sha256"]))
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for r in ordered:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")
    polls = (ARCHIVE / "polls.jsonl").read_text(encoding="utf-8").splitlines() if (ARCHIVE / "polls.jsonl").is_file() else []
    polls = [p for p in (json.loads(x) for x in polls if x.strip())]
    first = polls[0]["at"] if polls else None
    last = polls[-1]["at"] if polls else None
    # When each accessibility alert was seen active (first/last poll, count): lets incident memory say
    # when a closure ended. An alert absent from the last poll has ended (or was withdrawn) since.
    activity = {}
    for p in polls:
        for aid in p.get("active_accessibility_alert_ids", []):
            a = activity.setdefault(aid, {"first_active": p["at"], "last_active": p["at"], "polls_active": 0})
            a["last_active"], a["polls_active"] = p["at"], a["polls_active"] + 1
    for a in activity.values():  # first poll that no longer listed it: the closure ended before then
        a["first_absent"] = next((p["at"] for p in polls if p["at"] > a["last_active"]), None)
    (ALERTS_OUT / "alert_activity.json").write_text(
        json.dumps({"first_poll": first, "last_poll": last, "polls": len(polls), "alerts": activity},
                   indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    summary = {"source": "MBTA V3 /alerts, polled every 10 minutes by the local collector",
               "polls": len(polls), "first_poll": first, "last_poll": last,
               "accessibility_alerts": len({r["alert"]["id"] for r in ordered}), "versions": len(ordered)}
    (ALERTS_OUT / "HARVEST.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8",
                                             newline="\n")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "doctor"
    commands = {"doctor": doctor, "harvest": harvest}
    sys.exit(commands[cmd]() if cmd in commands else (print(__doc__) or 2))
