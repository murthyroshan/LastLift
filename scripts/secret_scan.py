"""Repository guard run by the git hooks and CI.

Modes:
  --staged          check what is about to be committed (pre-commit)
  --msg FILE        check a commit message (commit-msg)
  --range A..B      re-check outgoing commits: author, messages, added lines (pre-push)
  --all             scan every tracked file (CI)

Blocks: secret files and secret-shaped strings, any value from the local .env (reported by
key name only, never the value), wrong author identity, attribution trailers, assistant-tool
config files or references, and commits after the submission freeze.
Stdlib only; never prints secret values.
"""
import codecs
import datetime as dt
import os
import re
import subprocess
import sys

AUTHOR = "murthyroshan <mrslvt.dev@gmail.com>"
FREEZE_AT = dt.datetime(2026, 10, 18, 23, 59, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))
# The assistant name is stored rot13-encoded so this file never contains it literally.
_TOOL_WORD = codecs.decode("pynhqr", "rot13")
TOOL_WORD_RE = re.compile(_TOOL_WORD, re.IGNORECASE)

BLOCKED_PATHS = [
    re.compile(r"(^|/)\.env(\.[^/]*)?$"),
    re.compile(r"\.(pem|key|rdb|aof|zip)$", re.IGNORECASE),
    re.compile(r"(^|/)id_rsa"),
    re.compile(r"(^|/)stop_times\.txt$"),
    re.compile(rf"(^|/)\.?{_TOOL_WORD}([./_-]|$)", re.IGNORECASE),
]
ALLOWED_PATHS = [re.compile(r"(^|/)\.env\.example$")]

SECRET_PATTERNS = [
    ("groq key", re.compile(r"gsk_[A-Za-z0-9]{20,}")),
    ("google key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("github token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36}|github_pat_\w{20,}")),
    ("openai-style key", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("credential url", re.compile(r"\b\w+://[^/\s:@'\"]+:[^/\s@'\"]+@")),
    ("assigned secret", re.compile(r"(?i)\b(password|secret|token|api[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}")),
]
PLACEHOLDER = re.compile(r"(?i)(example|placeholder|changeme|dummy|test|fake|xxxx|your_)")

TRAILER_RE = re.compile(r"(?im)^\s*(co-authored-by|signed-off-by)\s*:")
GENERATED_RE = re.compile(r"(?i)generated with|🤖")
WARN_BYTES, MAX_BYTES = 5 * 1024 * 1024, 20 * 1024 * 1024


def git(*args, check=True):
    out = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and out.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


SECRET_KEY_RE = re.compile(r"KEY|PASSWORD|TOKEN|SECRET|URL|HOST", re.IGNORECASE)


def env_values():
    """Values of secret-type keys in the local .env (outside the repo).

    Only key *names* ever leave this function's callers. Non-secret keys (usernames, ports,
    model names, modes) are skipped because their values are ordinary words found in code.
    """
    path = os.environ.get("ENV_FILE") or os.path.join(git("rev-parse", "--show-toplevel").strip(), "..", ".env")
    found = {}
    try:
        for line in open(path, encoding="utf-8-sig"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("'\"")
                if len(v) >= 8 and SECRET_KEY_RE.search(k):
                    found[k] = v
    except OSError:
        pass
    return found


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def err(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def finish(self, what):
        for w in self.warnings:
            print(f"warning: {w}", file=sys.stderr)
        if self.errors:
            print(f"BLOCKED ({what}):", file=sys.stderr)
            for e in self.errors:
                print(f"  - {e}", file=sys.stderr)
            return 1
        return 0


def check_path(path, rep, size=None):
    if any(p.search(path) for p in ALLOWED_PATHS):
        return
    for p in BLOCKED_PATHS:
        if p.search(path):
            rep.err(f"{path}: file type/name is not allowed in the repo")
            return
    if size is not None:
        if size > MAX_BYTES:
            rep.err(f"{path}: {size // 1024 // 1024} MB exceeds the 20 MB limit")
        elif size > WARN_BYTES:
            rep.warn(f"{path}: {size // 1024 // 1024} MB is large")


def check_lines(where, lines, rep, secrets):
    for lineno, line in lines:
        for name, pat in SECRET_PATTERNS:
            m = pat.search(line)
            if m and not PLACEHOLDER.search(m.group(0)) and not PLACEHOLDER.search(line):
                rep.err(f"{where}:{lineno}: looks like a {name}")
        for key, value in secrets.items():
            if value in line:
                rep.err(f"{where}:{lineno}: contains the value of .env key {key}")
        if TOOL_WORD_RE.search(line):
            rep.err(f"{where}:{lineno}: contains an assistant-tool reference (not allowed in this repo)")


def check_message(text, rep, where="commit message"):
    if TRAILER_RE.search(text):
        rep.err(f"{where}: co-author/sign-off trailers are not allowed")
    if GENERATED_RE.search(text):
        rep.err(f"{where}: generated-by attribution lines are not allowed")
    if TOOL_WORD_RE.search(text):
        rep.err(f"{where}: contains an assistant-tool reference")


def check_author(rep):
    ident = git("var", "GIT_AUTHOR_IDENT").rsplit(">", 1)[0] + ">"
    if ident != AUTHOR:
        rep.err(f"author identity must be '{AUTHOR}' (got '{ident}')")
    committer = git("var", "GIT_COMMITTER_IDENT").rsplit(">", 1)[0] + ">"
    if committer != AUTHOR:
        rep.err(f"committer identity must be '{AUTHOR}' (got '{committer}')")


def check_freeze(rep):
    if dt.datetime.now(dt.timezone.utc) > FREEZE_AT and os.environ.get("LASTLIFT_POST_FREEZE") != "1":
        rep.err("submission freeze is active (after 2026-10-18 23:59 IST)")


def added_lines(diff_text):
    """Yield (path, lineno, text) for added lines in a unified diff with -U0."""
    path, lineno = None, 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            lineno = int(m.group(1)) if m else 0
        elif raw.startswith("+") and not raw.startswith("+++") and path:
            yield path, lineno, raw[1:]
            lineno += 1


def staged(rep):
    secrets = env_values()
    check_author(rep)
    check_freeze(rep)
    for row in git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split("\0"):
        if row:
            size = None
            try:
                size = int(git("cat-file", "-s", f":{row}").strip())
            except SystemExit:
                pass
            check_path(row, rep, size)
    by_file = {}
    for path, lineno, text in added_lines(git("diff", "--cached", "-U0", "--no-color", "--text")):
        by_file.setdefault(path, []).append((lineno, text))
    for path, lines in by_file.items():
        check_lines(path, lines, rep, secrets)
    return rep.finish("pre-commit")


def message(path, rep):
    text = open(path, encoding="utf-8", errors="replace").read()
    text = "\n".join(l for l in text.splitlines() if not l.startswith("#"))
    check_message(text, rep)
    return rep.finish("commit-msg")


def commit_range(spec, rep):
    secrets = env_values()
    for sha in git("rev-list", spec).split():
        author = git("show", "-s", "--format=%an <%ae>", sha).strip()
        committer = git("show", "-s", "--format=%cn <%ce>", sha).strip()
        if author != AUTHOR or committer != AUTHOR:
            rep.err(f"{sha[:8]}: author/committer is '{author}' / '{committer}'")
        check_message(git("show", "-s", "--format=%B", sha), rep, f"{sha[:8]} message")
        for f in git("show", "--name-only", "--format=", sha).split("\n"):
            if f:
                check_path(f, rep)
        by_file = {}
        for p, lineno, text in added_lines(git("show", "-U0", "--no-color", "--text", "--format=", sha)):
            by_file.setdefault(p, []).append((lineno, text))
        for p, lines in by_file.items():
            check_lines(f"{sha[:8]}:{p}", lines, rep, secrets)
    return rep.finish("pre-push")


def all_files(rep):
    secrets = env_values()
    root = git("rev-parse", "--show-toplevel").strip()
    for path in git("ls-files", "-z").split("\0"):
        if not path:
            continue
        full = os.path.join(root, path)
        check_path(path, rep, os.path.getsize(full) if os.path.exists(full) else None)
        try:
            with open(full, encoding="utf-8") as fh:
                check_lines(path, enumerate(fh, 1), rep, secrets)
        except (UnicodeDecodeError, OSError):
            continue
    return rep.finish("scan --all")


def main(argv):
    rep = Report()
    if "--staged" in argv:
        return staged(rep)
    if "--msg" in argv:
        return message(argv[argv.index("--msg") + 1], rep)
    if "--range" in argv:
        return commit_range(argv[argv.index("--range") + 1], rep)
    if "--all" in argv:
        return all_files(rep)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
