"""
agent/reviewer.py

The ReviewerAgent -- the quality gate of the multi-agent system. After a
specialist (RefactoringAgent / DocumentationAgent) proposes and self-verifies a
fix, the ReviewerAgent independently reviews the resulting diff and the test
outcome and issues an explainable verdict: approve / revise / reject, with a
one-sentence rationale.

It is a genuinely SEPARATE agent -- a distinct role prompt and its own LLM call,
not the same context that authored the fix -- so it can catch problems the
author is blind to. The recurring failure mode on small models here is exactly
that kind of blind spot: the fixer introduces a helper/constant/import it never
actually defines, then confidently self-verifies. An independent reviewer that
did not write the change is far more likely to notice.

It runs post-hoc and uses NO tools; it reasons over the finding, the unified
diff, and whether the sandboxed tests passed. Its verdict is recorded on the
fix result and rendered in the roadmap, adding a "was this change actually
good?" judgement on top of the mechanical "did it apply / did tests pass?"
signal -- the "Quality Enhancement" half of the system.

Point LLM_REVIEW_MODEL at a stronger model than the specialists use to make the
reviewer a sharper critic than the author (recommended when the free-tier 8B
model is doing the fixing).
"""
from __future__ import annotations

import json
import os
from collections import Counter
from typing import Dict, Optional

from analyzers.base import Finding
from agent import llm_client

REVIEW_MODEL = os.environ.get("LLM_REVIEW_MODEL", llm_client.ORCH_MODEL)

SYSTEM_PROMPT = """You are the Reviewer Agent, an independent code reviewer in a multi-agent
refactoring system. Another agent has proposed a fix for a technical-debt finding. Your job is to
judge that fix -- you did NOT write it and you are under no obligation to approve it.

You are given the finding, the proposed change as a unified diff, and whether the sandboxed test
suite passed. Check that the change actually resolves the finding, is behaviour-preserving, and
introduces no new problem -- in particular, that every name it uses (helpers, constants, imports) is
defined or imported within the change or already present, with no dangling references.

Output ONLY strict JSON, nothing else: {"verdict": "approve" | "revise" | "reject", "rationale": "<a concise explanation>"}
- approve: the fix correctly resolves the finding and is safe to apply.
- revise: partially right but has a specific, fixable issue -- name it in the rationale.
- reject: wrong, unsafe, or doesn't address the finding.
Weigh the test result but do not defer to it blindly: tests can pass on a change that doesn't truly
fix the finding, and can fail for reasons unrelated to the change's correctness."""

_TESTS_LABEL = {True: "passed", False: "failed", None: "not run / no test suite detected"}


def _append_review_log(entry: Dict) -> None:
    log_path = os.path.join(os.getcwd(), ".code_debt", "review_log.jsonl")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def _review_once(finding: Finding, fix_result: Dict, temperature: float = 0.2) -> Dict:
    diff = fix_result.get("diff")
    if not diff or not llm_client.have_key():
        return {}

    user_msg = (
        f"Finding: {json.dumps(finding.to_dict())}\n\n"
        f"Proposed change (unified diff):\n{diff}\n\n"
        f"Sandboxed tests: {_TESTS_LABEL.get(fix_result.get('tests_passed'), 'unknown')}\n\n"
        f"Review this fix and return only the JSON verdict."
    )
    parsed = llm_client.request_json_response(
        model=REVIEW_MODEL,
        max_tokens=400,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=temperature,
    )
    verdict = str(parsed.get("verdict", "revise")).lower().strip()
    if verdict not in ("approve", "revise", "reject"):
        verdict = "revise"
    return {
        "verdict": verdict,
        "rationale": str(parsed.get("rationale", "")).strip(),
    }


def review(finding: Finding, fix_result: Dict) -> Optional[Dict]:
    """Independently review one proposed fix.

    Returns {"verdict": "approve"|"revise"|"reject", "rationale": str}, or None
    if there is nothing to review (no diff was produced, or no LLM key -- the
    multi-agent path already requires a key for the specialists, so None here
    just means the specialist gave up before proposing anything).

    Propagates llm_client.RateLimitExhausted so the coordinator can hard-stop
    the run, the same discipline the rest of the pipeline follows -- retrying a
    429 only burns another request against the same limit."""
    diff = fix_result.get("diff")
    if not diff or not llm_client.have_key():
        return None

    # A fix whose sandboxed tests already FAILED is known-bad -- the roadmap
    # already renders it as "applied, tests failed". Spending a review LLM call
    # to re-confirm that adds no signal, so skip it. Note the asymmetry:
    # tests_passed is None means no suite was detected, which is exactly when an
    # independent review is most valuable -- so None still gets reviewed.
    if fix_result.get("tests_passed") is False:
        return {"verdict": "skipped",
                "rationale": "sandboxed tests failed; independent review skipped to save an LLM call"}

    verdicts = []
    first = _review_once(finding, fix_result, temperature=0.2)
    verdicts.append(first)
    if first.get("verdict") == "revise":
        for temperature in (0.7, 0.9):
            verdicts.append(_review_once(finding, fix_result, temperature=temperature))

    if len(verdicts) > 1:
        counter = Counter(item.get("verdict") for item in verdicts if item.get("verdict"))
        chosen_verdict = counter.most_common(1)[0][0] if counter else "revise"
        if counter and counter.most_common(1)[0][1] == 1 and "revise" in counter:
            chosen_verdict = "revise"
        chosen = next((item for item in verdicts if item.get("verdict") == chosen_verdict), first)
        entry = {
            "finding_id": finding.id,
            "verdict": chosen_verdict,
            "rationale": chosen.get("rationale", ""),
            "samples": verdicts,
        }
        _append_review_log(entry)
        return {"verdict": chosen_verdict, "rationale": chosen.get("rationale", "")}

    entry = {"finding_id": finding.id, "verdict": first.get("verdict", "revise"), "rationale": first.get("rationale", "")}
    _append_review_log(entry)
    return {"verdict": first.get("verdict", "revise"), "rationale": first.get("rationale", "")}
