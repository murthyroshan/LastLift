"""Grounding validator: an LLM answer is shown only if everything checkable in it comes from the tools.

Rules (an answer failing any rule is replaced by the deterministic template):
  G1 at least one tool result backs the answer;
  G2 every station id (place-...) is an entity of some tool result;
  G3 every lift / platform number (any 3-6 digit number) appears in the tool results;
  G4 every other number with two or more digits (minutes, counts) appears in the tool results;
  G5 no banned wording (lastlift.wording.NEVER_SAY);
  G6 the answer is not empty and not longer than 1,200 characters.
"""
import json
import re

from ..wording import violations

PLACE = re.compile(r"\bplace-[a-z0-9-]+\b")
NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w])")


def _numbers(text):
    return {m.group(1) for m in NUMBER.finditer(text)}


def check(answer: str, results: list[dict]) -> list[str]:
    """Return the list of violated rules (empty = grounded)."""
    problems = []
    if not results:
        problems.append("G1 no tool result")
    if not answer or not answer.strip():
        return problems + ["G6 empty answer"]
    if len(answer) > 1200:
        problems.append("G6 answer too long")
    corpus = json.dumps(results, ensure_ascii=False)
    entities = {e for r in results for e in r.get("entities", [])}
    for place in set(PLACE.findall(answer)):
        if place not in entities:
            problems.append(f"G2 unknown station id {place}")
    found = _numbers(corpus)
    known = found | {n.rstrip("0").rstrip(".") for n in found if "." in n}
    # "about 17 minutes" for 17.1: a rounded form of a number in the results is not a new number
    known |= {str(f(float(n))) for n in found if "." in n for f in (round, int)}
    for n in sorted(_numbers(answer)):
        if len(n.split(".")[0]) < 2 and "." not in n:
            continue                        # single digits ("2 routes") are not checked
        if n not in known and n.rstrip("0").rstrip(".") not in known:
            rule = "G3 lift/platform number" if n.isdigit() and 3 <= len(n) <= 6 else "G4 number"
            problems.append(f"{rule} {n} is not in any tool result")
    for phrase, why in violations(answer):
        problems.append(f"G5 wording '{phrase}' ({why})")
    return problems
