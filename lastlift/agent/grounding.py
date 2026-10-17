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


# --- structured claims (each sentence of an LLM answer cites the tool steps it rests on) --------------------------
LOSS_WORDS = re.compile(r"\b(loses?|lost|losing) step-free access\b|\bno step-free route\b", re.I)
LOSS_EVIDENCE = re.compile(r'"k": 0\b|\blose[s]? step-free access\b|\bno step-free route\b|"lost"', re.I)


def check_claim(claim: dict, results: list[dict]) -> list[str]:
    """Rules for one claim {text, cites: [step numbers, 1-based]}:
      C1 it cites at least one step, and every cited step exists;
      C2 everything checkable in it comes from the cited steps (G2-G6 above, restricted to those steps);
      C3 loss wording ("loses step-free access", "no step-free route") needs a cited step that shows a loss."""
    text = (claim.get("text") or "").strip()
    cites = claim.get("cites") or []
    if not cites or not all(isinstance(c, int) and 1 <= c <= len(results) for c in cites):
        return ["C1 cites no existing step"]
    cited = [results[c - 1] for c in cites]
    problems = [p for p in check(text, cited) if not p.startswith("G6 answer too long")]
    if LOSS_WORDS.search(text) and not any(LOSS_EVIDENCE.search(json.dumps(r, ensure_ascii=False)) for r in cited):
        problems.append("C3 loss wording without a cited step showing a loss")
    return problems


def parse_claims(content: str) -> list[dict] | None:
    """The final LLM message as a list of claims, or None if it is not the requested JSON."""
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    claims = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(claims, list):
        return None
    out = []
    for c in claims:
        if isinstance(c, dict) and isinstance(c.get("text"), str):
            cites = [int(x) for x in (c.get("cites") or []) if str(x).isdigit()]
            out.append({"kind": str(c.get("kind") or "claim"), "text": c["text"].strip(), "cites": cites})
    return out or None


def assemble(claims: list[dict], results: list[dict]) -> tuple[str, list[dict]]:
    """Validate every claim; a failed claim is replaced by the summary of its first cited step (the template
    counterpart) or dropped if it cites nothing real. Returns (answer text, per-claim report)."""
    report, parts, used = [], [], set()
    for c in claims:
        problems = check_claim(c, results)
        if not problems:
            parts.append(c["text"])
            report.append({**c, "ok": True, "problems": []})
            continue
        valid = [n for n in c["cites"] if isinstance(n, int) and 1 <= n <= len(results)]
        replacement = None
        if valid and valid[0] not in used:
            s = (results[valid[0] - 1].get("summary") or "").strip()
            if s:
                replacement = s[0].upper() + s[1:] + ("" if s.endswith(".") else ".")
                used.add(valid[0])
                parts.append(replacement)
        report.append({**c, "ok": False, "problems": problems, "replaced_by": replacement})
    text = " ".join(parts).strip()
    if text and "mbta.com/alerts/access" not in text:
        text += " Check mbta.com/alerts/access."
    return text, report
