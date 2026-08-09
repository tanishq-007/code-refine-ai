"""
agent/roadmap.py

Renders the final Markdown refactoring roadmap from scored findings
(and, if the agent loop got that far, verified fix diffs).
"""
from __future__ import annotations

from collections import Counter
from typing import List, Dict, Optional
from agent.scoring import ScoredFinding


def _rejected(fix: Dict) -> bool:
    """True if the independent ReviewerAgent rejected this fix. A rejected fix
    must not be presented as a usable result, no matter what the mechanical
    tests_passed/applied signals say -- that judgement is the whole point of the
    reviewer being a separate agent.

    Exception: if `retry_used` is set (agent/orchestrator.py's one capped
    review-triggered retry -- see MAX_REVIEW_RETRIES), the diff/status shown
    here is the RETRY's, not the rejected original's, so the suppression
    below no longer applies to it -- the retry was never itself reviewed, so
    there's no "reject" verdict about it to act on."""
    if fix.get("retry_used"):
        return False
    return (fix.get("review") or {}).get("verdict") == "reject"


def _tier(impact: int, ratio: float) -> str:
    # Gate "Do now" on impact as well as ratio: effort is forced to 1 for the
    # four mechanical finding types (missing_docstring/unused_import/
    # unused_variable/magic_number -- see agent/scoring.py), which floors
    # their ratio at 2.0 regardless of how low-value the finding actually is.
    # Without this gate they'd always outrank a real, high-effort structural
    # problem (e.g. impact 4 / effort 4 = ratio 1.0) purely for being cheap.
    if impact >= 3 and ratio >= 2.0:
        return "🔥 Do now (high impact / low effort)"
    if ratio >= 1.0:
        return "📋 Plan (balanced impact/effort)"
    return "🧹 Backlog (low ratio -- nice to have)"


def _agent_summary(fixes: Dict[str, Dict]) -> List[str]:
    """A short 'which specialist handled how many findings, and how they
    fared' table at the top of the roadmap. This is the multi-agent system
    explaining itself at a glance -- omitted entirely under strategy=single
    (where no fix carries an 'agent' tag), so the single-agent roadmap is
    byte-for-byte unchanged."""
    tagged = [fx for fx in fixes.values() if fx.get("agent")]
    if not tagged:
        return []

    stats: Dict[str, Dict[str, int]] = {}
    for fx in tagged:
        s = stats.setdefault(fx["agent"], {"handled": 0, "passed": 0})
        s["handled"] += 1
        # A reviewer-rejected fix does not count as verified even if its tests
        # passed -- tests passing on a change that doesn't truly fix the finding
        # is exactly the blind spot the reviewer exists to catch.
        if fx.get("tests_passed") and not _rejected(fx):
            s["passed"] += 1

    lines = ["## Agents\n", "Findings were routed to specialist agents:\n",
             "| Agent | Findings handled | Verified (tests pass, not rejected) |",
             "|-------|------------------|-------------------------------------|"]
    for name in sorted(stats):
        s = stats[name]
        lines.append(f"| {name} | {s['handled']} | {s['passed']} |")
    lines.append("")

    verdicts = Counter(fx["review"]["verdict"] for fx in tagged if fx.get("review"))
    if verdicts:
        breakdown = ", ".join(f"{n} {v}" for v, n in sorted(verdicts.items()))
        lines.append(f"**ReviewerAgent** independently reviewed "
                     f"{sum(verdicts.values())} proposed fix(es): {breakdown}.\n")
    return lines


def generate_markdown(scored: List[ScoredFinding], fixes: Optional[Dict[str, Dict]] = None,
                       repo_name: str = "repository") -> str:
    fixes = fixes or {}
    lines = [f"# Refactoring Roadmap -- {repo_name}", ""]
    lines.append(f"Generated from {len(scored)} findings, ranked by impact/effort ratio.\n")

    lines.extend(_agent_summary(fixes))

    tiers: Dict[str, List[ScoredFinding]] = {}
    for sf in scored:
        tiers.setdefault(_tier(sf.impact, sf.ratio), []).append(sf)

    tier_order = [
        "🔥 Do now (high impact / low effort)",
        "📋 Plan (balanced impact/effort)",
        "🧹 Backlog (low ratio -- nice to have)",
    ]

    for tier_name in tier_order:
        items = tiers.get(tier_name, [])
        if not items:
            continue
        lines.append(f"## {tier_name}\n")
        for sf in items:
            f = sf.finding
            lines.append(f"### `{f.file}:{f.line_start}-{f.line_end}` -- {f.symbol or f.type}")
            lines.append(f"- **type**: {f.type}")
            lines.append(f"- **impact/effort**: {sf.impact}/{sf.effort} (ratio {sf.ratio:.2f})")
            lines.append(f"- **why**: {f.description}")
            lines.append(f"- **scorer notes**: {sf.justification}")

            fix = fixes.get(f.id)
            if fix:
                if fix.get("agent"):
                    handled = f"- **handled by**: {fix['agent']}"
                    if fix.get("routing_reason"):
                        handled += f" ({fix['routing_reason']})"
                    lines.append(handled)
                if fix.get("error"):
                    status = f"⚠️ agent error: {fix['error']}"
                elif _rejected(fix):
                    # The reviewer's verdict overrides the mechanical signal:
                    # even a test-passing fix is withheld if the reviewer
                    # rejected it, so a bad change is never presented as usable.
                    status = "reviewer rejected -- do not apply"
                elif fix.get("tests_passed"):
                    status = "✅ tests pass"
                elif fix.get("applied"):
                    status = "⚠️ applied, tests failed"
                else:
                    status = "❌ fix did not apply"
                lines.append(f"- **proposed fix**: {status}")
                review = fix.get("review")
                if review:
                    lines.append(f"- **reviewer verdict**: {review.get('verdict')} "
                                 f"-- {review.get('rationale', '')}")
                if fix.get("planner_order") is not None:
                    lines.append(f"- **planner order**: {fix['planner_order']}")
                if fix.get("planner_group"):
                    lines.append(f"- **planner group**: {fix['planner_group']}")
                if fix.get("retry"):
                    # A reject/revise verdict earned this finding its one capped
                    # retry (agent/orchestrator.py's MAX_REVIEW_RETRIES) -- say
                    # what that retry did, independent of which attempt was kept.
                    lines.append(f"- **retry**: {fix['retry']}")
                if fix.get("diff"):
                    if _rejected(fix):
                        # Don't render a rejected diff as ready-to-apply code.
                        lines.append("\n_Diff withheld: the reviewer rejected this fix "
                                     "(see rationale above)._")
                    else:
                        lines.append("\n```diff")
                        lines.append(fix["diff"])
                        lines.append("```")
            lines.append("")

    return "\n".join(lines)
