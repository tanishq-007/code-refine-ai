"""
agent/scoring.py

Phase 2: impact/effort scoring. Findings are sent to an LLM in batches (up
to BATCH_SIZE per call, structured JSON output) to rate impact (1-5) and
effort (1-5) and justify it, reasoning over the deterministic signals
(complexity/line-count/churn/fan-in) rather than the raw code alone.
Findings are then ranked by impact/effort ratio for the roadmap.

Works without an API key too (score(..., offline=True)) by using a cheap
deterministic heuristic, so `main.py eval` never needs an LLM key.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import List, Dict, Optional

from analyzers.base import Finding
from analyzers import churn as churn_mod
from agent import llm_client
from rag import retrieval

# findings per LLM call. Kept at 10 (not 20): the request charged against a
# provider's per-minute token budget is input + max_tokens, and max_tokens scales
# with the batch (see MAX_TOKENS_PER_FINDING). A batch of 20 pushed a single
# request past the provider's free-tier TPM limit (observed on Groq's 6k TPM
# limit) -> a 413 that forced the whole pass onto the heuristic. 10 keeps each
# request comfortably under that budget while still halving the call count vs
# one-at-a-time. Override with LLM_BATCH_SIZE.
BATCH_SIZE = int(os.environ.get("LLM_BATCH_SIZE", "10"))

# Output-token budget per finding in a scoring batch. Each finding yields one small
# JSON object (id, impact, effort, a 1-2 sentence justification), so ~150 tokens is
# ample. The old 300 doubled the request's token cost for no benefit -- and since
# max_tokens counts against the per-minute limit BEFORE any output is generated, an
# inflated value was the main reason a batch tripped the TPM cap. Override with
# LLM_MAX_TOKENS_PER_FINDING.
MAX_TOKENS_PER_FINDING = int(os.environ.get("LLM_MAX_TOKENS_PER_FINDING", "150"))

# Cap on how many findings get the (slow, paid) LLM scoring pass. Findings are
# cheaply heuristic-pre-ranked first and only the top SCORE_LIMIT are sent to the
# LLM for a precise score; the long tail keeps its heuristic score. Only the top
# findings ever reach the fix stage, so LLM-scoring all ~600+ of them was almost
# entirely wasted calls and latency. Set LLM_SCORE_LIMIT=0 to score every finding
# with the LLM (the old behaviour). Keep it comfortably above run's --top-n.
SCORE_LIMIT = int(os.environ.get("LLM_SCORE_LIMIT", "40"))

_warned: set = set()


def _warn_once(key: str, message: str) -> None:
    """Emit a stderr warning the first time a given failure class occurs in a
    run, so a degraded pass is visible without spamming one line per batch."""
    if key not in _warned:
        _warned.add(key)
        print(f"[scoring] WARNING: {message}", file=sys.stderr)

SYSTEM_PROMPT = """You are a senior engineer triaging technical-debt findings for a refactoring roadmap.
You will be given a JSON array of findings, each with supporting signals (deterministic metrics,
fan-in, churn, and retrieved coding standards). For EACH finding, output one object with this exact
shape: {"id": "<the finding's id, copied exactly>", "impact": <int 1-5>, "effort": <int 1-5>,
"justification": "<one or two sentences>"}
Output ONLY a JSON object of the form {"results": [<one of the above objects per input finding,
in the same order>]}, and nothing else.
impact: how much this debt hurts the codebase if left alone (bugs risk, blast radius, churn hot-spot).
effort: how much work fixing it will take (1 = trivial rename/extract, 5 = risky architectural change).
Be terse and concrete in each justification -- reference the actual metric numbers you were given."""


@dataclass
class ScoredFinding:
    finding: Finding
    impact: int
    effort: int
    justification: str

    @property
    def ratio(self) -> float:
        return self.impact / max(self.effort, 1)

    def to_dict(self) -> Dict:
        d = self.finding.to_dict()
        d.update({"impact": self.impact, "effort": self.effort,
                   "justification": self.justification, "ratio": round(self.ratio, 2)})
        return d


def _build_context(finding: Finding, fan_in: int, standard: str, churn: Dict[str, int]) -> Dict:
    commits = churn.get(finding.file, 0)
    return {
        "finding": finding.to_dict(),
        "fan_in": fan_in,
        "commit_count": commits,
        "relevant_standard": standard,
    }


def _heuristic_score(finding: Finding, fan_in: int, churn: Dict[str, int]) -> ScoredFinding:
    """Deterministic scorer. Used directly for the offline/no-key path AND as a
    cheap pre-ranking that lets the LLM pass skip the long tail of findings. Loosely
    mirrors what we'd expect an LLM to converge on given the same signals.

    `fan_in` is passed in (computed once per file by the caller) rather than
    recomputed here -- it's the same value for every finding in a file, and
    recomputing it per finding re-read the whole repo hundreds of times.

    `justification` is a formatted trace of exactly which rules fired below
    -- not just two bare numbers -- so the offline/no-key path is just as
    explainable as the LLM path (which always returns a justification) and
    both render uniformly in agent/roadmap.py."""
    commits = churn.get(finding.file, 0)

    impact = 2
    impact_reasons: List[str] = []
    if fan_in >= 2:
        impact += 1
        impact_reasons.append(f"fan-in {fan_in} ≥ 2")
    if commits >= 3:
        impact += 1
        impact_reasons.append(f"{commits} commits ≥ 3")
    if finding.type == "high_complexity" and finding.metric.get("complexity", 0) > 20:
        impact += 1
        impact_reasons.append(f"complexity {finding.metric.get('complexity')} > 20")
    if finding.type == "missing_tests" and fan_in == 0:
        impact -= 1  # over-flagged, low fan-in -> likely a false positive, demote
        impact_reasons.append("missing_tests with 0 fan-in, likely a false positive")
    impact = max(1, min(5, impact))

    effort = 2
    effort_reasons: List[str] = []
    if finding.type == "high_complexity":
        effort += 1
        effort_reasons.append("high_complexity type")
    if finding.type == "duplication":
        effort += 1
        effort_reasons.append("duplication type")
    if finding.metric.get("lines", 0) and finding.metric["lines"] > 100:
        effort += 1
        effort_reasons.append(f"{finding.metric['lines']} lines > 100")
    if finding.type in ("missing_docstring", "unused_import", "unused_variable", "magic_number"):
        effort = 1  # near-mechanical fix (delete, or generate/extract a constant) -- overrides the above
        effort_reasons = ["mechanical type"]
    effort = max(1, min(5, effort))

    impact_trace = "; ".join(impact_reasons) if impact_reasons else "baseline, no signals fired"
    effort_trace = "; ".join(effort_reasons) if effort_reasons else "baseline, no signals fired"
    justification = f"impact {impact} ({impact_trace}); effort {effort} ({effort_trace})"

    return ScoredFinding(finding=finding, impact=impact, effort=effort, justification=justification)


def _llm_score_batch(findings: List[Finding], contexts: List[Dict]) -> List[ScoredFinding]:
    """Scores a batch (<= BATCH_SIZE) of findings in a single LLM call."""
    parsed = llm_client.request_json_response(
        model=llm_client.SCORING_MODEL,
        max_tokens=MAX_TOKENS_PER_FINDING * len(findings),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(contexts)},
        ],
    )
    by_id = {p["id"]: p for p in parsed["results"]}

    results = []
    for finding in findings:
        p = by_id[finding.id]  # KeyError if the model dropped/renamed an id -> caller falls back
        results.append(ScoredFinding(
            finding=finding,
            impact=int(p["impact"]),
            effort=int(p["effort"]),
            justification=p["justification"],
        ))
    return results


def score_findings(findings: List[Finding], repo_root: str = "", py_files: Optional[List[str]] = None,
                    offline: Optional[bool] = None) -> List[ScoredFinding]:
    py_files = py_files or []
    if offline is None:
        offline = not llm_client.have_key()

    churn = churn_mod.compute_churn(repo_root) if repo_root else {}

    # fan-in depends only on the FILE and standards only on the finding TYPE, but
    # both were previously recomputed once per finding -- enrich_fan_in re-reads
    # every file in the repo, so scoring ~600 findings re-read the whole tree ~600
    # times. Memoize each so the expensive work runs once per unique file / type.
    _fan_in_cache: Dict[str, int] = {}
    _standard_cache: Dict[str, str] = {}

    def fan_in_of(file: str) -> int:
        if file not in _fan_in_cache:
            _fan_in_cache[file] = (
                retrieval.enrich_fan_in(repo_root, file, py_files) if repo_root else 0
            )
        return _fan_in_cache[file]

    def standard_of(ftype: str) -> str:
        if ftype not in _standard_cache:
            _standard_cache[ftype] = retrieval.get_standards(ftype)
        return _standard_cache[ftype]

    # Cheap heuristic score for EVERY finding first. Offline this is the final
    # answer; online it's a pre-ranking so the LLM pass can be limited to the top
    # candidates.
    heuristic = [_heuristic_score(f, fan_in_of(f.file), churn) for f in findings]
    heuristic.sort(key=lambda sf: sf.ratio, reverse=True)

    if offline:
        # Intentional no-key path: quiet by design. Say so once so an
        # unset key isn't mistaken for a broken API call below.
        print("[scoring] no LLM key set -> using offline heuristic scorer "
              "(set LLM_API_KEY/MISTRAL_API_KEY to enable LLM scoring).", file=sys.stderr)
        return heuristic

    # Online: LLM-rescore only the top SCORE_LIMIT pre-ranked findings (all of them
    # if SCORE_LIMIT <= 0). The tail keeps its heuristic score -- it can't reach the
    # fix stage, so a precise LLM score would be spent latency for no effect.
    if SCORE_LIMIT > 0 and len(heuristic) > SCORE_LIMIT:
        shortlist, tail = heuristic[:SCORE_LIMIT], heuristic[SCORE_LIMIT:]
        for sf in tail:
            sf.justification += (f" [heuristic score: outside the top {SCORE_LIMIT} "
                                 f"LLM-rescoring pool]")
        print(f"[scoring] LLM-scoring the top {len(shortlist)} of {len(heuristic)} findings "
              f"(pre-ranked by heuristic); the rest keep their heuristic score.", file=sys.stderr)
    else:
        shortlist, tail = heuristic, []

    heuristic_by_id = {sf.finding.id: sf for sf in shortlist}
    rescored: List[ScoredFinding] = []
    rate_limited = False
    degraded = 0  # findings that wanted LLM scoring but fell back to heuristic

    def _fallback(finding: Finding, note: str) -> ScoredFinding:
        sf = heuristic_by_id[finding.id]  # reuse the score we already computed
        sf.justification += note
        return sf

    shortlist_findings = [sf.finding for sf in shortlist]
    for i in range(0, len(shortlist_findings), BATCH_SIZE):
        batch = shortlist_findings[i:i + BATCH_SIZE]
        if rate_limited:
            # already hit a hard quota this run -- every remaining batch would
            # fail identically, so stop calling the LLM and just heuristic-score
            for finding in batch:
                rescored.append(_fallback(finding, " [LLM scoring skipped: rate limit exhausted earlier this run]"))
            degraded += len(batch)
            continue
        contexts = [_build_context(f, fan_in_of(f.file), standard_of(f.type), churn) for f in batch]
        try:
            rescored.extend(_llm_score_batch(batch, contexts))
        except llm_client.RateLimitExhausted as e:
            rate_limited = True
            _warn_once("rate_limit", f"LLM rate limit exhausted; scoring the rest offline: {e}")
            for finding in batch:
                rescored.append(_fallback(finding, f" [LLM scoring failed: rate limit exhausted: {e}]"))
            degraded += len(batch)
        except (ImportError, ModuleNotFoundError) as e:
            # A key IS set (offline is False), so the user wants LLM scoring --
            # but the client can't even be imported. That's a broken setup, not a
            # transient API hiccup: refuse to silently pass off heuristic output.
            raise RuntimeError(
                f"LLM scoring requested (API key present) but the LLM client "
                f"could not be imported: {e}. Install the project's dependencies "
                f"(e.g. `pip install -e .`) or run with `--no-rag`/no key for the "
                f"offline heuristic scorer."
            ) from e
        except Exception as e:  # noqa: BLE001 -- fall back rather than crash a whole scoring pass
            _warn_once("api_error", f"LLM call failed, falling back to heuristic scoring: {e}")
            for finding in batch:
                rescored.append(_fallback(finding, f" [LLM scoring failed: {e}]"))
            degraded += len(batch)

    if degraded:
        print(f"[scoring] WARNING: {degraded}/{len(shortlist_findings)} LLM-pool findings were scored "
              f"by the offline heuristic, not the LLM (see per-finding justifications for why).",
              file=sys.stderr)

    scored = rescored + tail
    scored.sort(key=lambda sf: sf.ratio, reverse=True)
    return scored
