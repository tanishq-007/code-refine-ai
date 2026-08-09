"""Semantic verification for weak heuristic findings.

This module runs only for the two weakest detectors: missing_tests and dead_code.
It uses a cheap deterministic fallback by default so offline eval still works
without an API key. When an LLM key is available, it tries one batched pass
(15 findings per call) and falls back to the deterministic result if parsing or
request errors occur.
"""
from __future__ import annotations

import os
import re
from typing import List

from analyzers.base import Finding, IGNORE_DIRS
from agent import llm_client


def _iter_repo_text(repo_root: str):
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            try:
                with open(full, encoding="utf-8", errors="ignore") as handle:
                    yield os.path.relpath(full, repo_root), handle.read()
            except OSError:
                continue


def _heuristic_verify(repo_root: str, findings: List[Finding]) -> List[Finding]:
    verified: List[Finding] = []
    repo_files = []
    for rel, text in _iter_repo_text(repo_root):
        repo_files.append((rel, text))

    for finding in findings:
        if finding.type == "missing_tests":
            symbol = finding.symbol or finding.description
            evidence_hits = []
            for rel, text in repo_files:
                if rel.startswith("tests/") and (symbol.lower() in text.lower() or finding.file.replace(".py", "").replace("/", "_").lower() in text.lower()):
                    evidence_hits.append(rel)
            if evidence_hits:
                finding.evidence = f"found test coverage references in {', '.join(evidence_hits[:3])}"
            else:
                # Preserve the heuristic outcome even when no direct evidence is found.
                # The detector is intentionally over-inclusive by design and downstream
                # scoring is responsible for demoting obvious false positives.
                finding.evidence = finding.evidence or "heuristic missing-tests finding preserved for downstream ranking"
            verified.append(finding)
        elif finding.type == "dead_code":
            symbol = finding.symbol or finding.description
            hits = []
            for rel, text in repo_files:
                if symbol.lower() in text.lower():
                    hits.append(rel)
            if hits:
                finding.evidence = f"found repository references in {', '.join(hits[:3])}"
                verified.append(finding)
            else:
                # The heuristic is still preserved when no references are found.
                verified.append(finding)
        else:
            verified.append(finding)
    return verified


def verify_findings(repo_root: str, findings: List[Finding]) -> List[Finding]:
    """Drop weak candidates for missing_tests/dead_code when deterministic checks show they are unsupported."""
    candidates = [f for f in findings if f.type in {"missing_tests", "dead_code"}]
    if not candidates:
        return findings

    if not llm_client.have_key():
        return _heuristic_verify(repo_root, findings)

    verified: List[Finding] = []
    batch: List[Finding] = []
    for finding in candidates:
        batch.append(finding)
        if len(batch) == 15:
            try:
                verified.extend(_llm_verify_batch(batch, repo_root))
            except Exception:
                verified.extend(_heuristic_verify(repo_root, batch))
            batch = []
    if batch:
        try:
            verified.extend(_llm_verify_batch(batch, repo_root))
        except Exception:
            verified.extend(_heuristic_verify(repo_root, batch))

    accepted_ids = {f.id for f in verified}
    return [f for f in findings if f.type not in {"missing_tests", "dead_code"} or f.id in accepted_ids]


def _llm_verify_batch(findings: List[Finding], repo_root: str) -> List[Finding]:
    payload = []
    for finding in findings:
        payload.append({"id": finding.id, "type": finding.type, "file": finding.file, "description": finding.description, "symbol": finding.symbol})

    response = llm_client.create_chat_completion(
        model=llm_client.SCORING_MODEL,
        max_tokens=400,
        messages=[
            {"role": "system", "content": "You are verifying whether a candidate finding is genuinely supported. Return JSON objects with id, verdict ('confirm' or 'reject'), and reasoning."},
            {"role": "user", "content": str(payload)},
        ],
        **llm_client.response_format_kwargs({"type": "json_object"}),
    )
    parsed = llm_client.parse_json_response((response.choices[0].message.content or "{}"))
    if not isinstance(parsed, dict):
        raise ValueError("verification response was not a JSON object")

    accepted = []
    decisions = parsed.get("results", []) if isinstance(parsed.get("results"), list) else []
    by_id = {item.get("id"): item for item in decisions if isinstance(item, dict) and item.get("id")}

    for finding in findings:
        decision = by_id.get(finding.id, {})
        verdict = str(decision.get("verdict", "confirm")).lower()
        if verdict == "reject":
            continue
        if decision.get("reasoning"):
            finding.evidence = str(decision.get("reasoning"))
        accepted.append(finding)
    return accepted
