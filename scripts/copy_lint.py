"""Copy lint: no user-facing text uses a phrase from lastlift.wording.NEVER_SAY.

    python scripts/copy_lint.py          # exit 1 on any violation

Checked: every string literal in lastlift/*.py except docstrings (summaries, cards, tickets), the web
app's sources, README.md and the docs. Comments and docstrings are developer notes and are not checked.
docs/ETHICS.md quotes the banned phrases to explain them, so lines marked `copy-lint: quoted` are skipped.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift.wording import DISCLAIMERS, violations  # noqa: E402

SKIP_FILES = {ROOT / "lastlift" / "wording.py"}           # holds the banned list itself
TEXT_GLOBS = ["README.md", "docs/*.md", "web/src/**/*.ts", "web/src/**/*.tsx", "web/index.html",
              ".github/ISSUE_TEMPLATE/*"]


def python_strings(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.lineno, node.value


def text_lines(path: Path):
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "copy-lint: quoted" not in line:
            yield i, line


def scan():
    problems = []
    for path in sorted((ROOT / "lastlift").glob("*.py")):
        if path in SKIP_FILES:
            continue
        for line, s in python_strings(path):
            problems += [(path, line, hit, why) for hit, why in violations(s)]
    for pattern in TEXT_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file():
                for line, s in text_lines(path):
                    problems += [(path, line, hit, why) for hit, why in violations(s)]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if DISCLAIMERS["footer"] not in readme:
        problems.append((ROOT / "README.md", 0, "footer missing", "README must carry the exact footer"))
    return problems


def main():
    problems = scan()
    for path, line, hit, why in problems:
        print(f"{path.relative_to(ROOT)}:{line}: '{hit}' ({why})")
    print(f"copy lint: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
