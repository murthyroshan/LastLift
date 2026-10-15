"""Developer commands for LastLift.

  python dev.py doctor     check git identity/hooks, Python, FalkorDB reachability, and .env key names
"""
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


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "doctor"
    sys.exit(doctor() if cmd == "doctor" else (print(__doc__) or 2))
