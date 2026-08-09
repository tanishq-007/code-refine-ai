"""
analyzers/validate.py

Structural sanity checks on a Finding list -- independent of any ground
truth, so this runs against ANY repo, not just eval/sample_repo. It answers
"did the scanner behave" (real file, in-range lines, unique ids), not "were
the findings correct" -- that second question still requires ground truth
and only exists for eval/sample_repo.
"""
from __future__ import annotations

import os
from typing import List

from analyzers.base import Finding, FINDING_TYPES


def validate_findings(repo_root: str, findings: List[Finding]) -> List[str]:
    """Returns a list of violation descriptions; empty means everything checked out."""
    violations: List[str] = []

    seen_ids = {}
    for f in findings:
        if f.id in seen_ids:
            violations.append(f"duplicate id {f.id!r} shared by {seen_ids[f.id]} and {f.file}:{f.line_start}")
        else:
            seen_ids[f.id] = f"{f.file}:{f.line_start}"

        if f.type not in FINDING_TYPES:
            violations.append(f"{f.id}: unknown type {f.type!r}")

        full = os.path.join(repo_root, f.file)
        if not os.path.isfile(full):
            violations.append(f"{f.id}: file {f.file!r} does not exist under {repo_root!r}")
            continue

        if f.line_start < 1:
            violations.append(f"{f.id}: line_start {f.line_start} is less than 1")
        if f.line_end and f.line_end < f.line_start:
            violations.append(f"{f.id}: line_end {f.line_end} is before line_start {f.line_start}")

        with open(full, encoding="utf-8", errors="ignore") as handle:
            line_count = sum(1 for _ in handle)
        last_line = max(f.line_start, f.line_end)
        if last_line > line_count:
            violations.append(
                f"{f.id}: line {last_line} is beyond {f.file}'s {line_count} lines"
            )

    return violations
