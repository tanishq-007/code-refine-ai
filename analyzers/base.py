"""
analyzers/base.py

The Finding schema — the stable contract everything else in this project
depends on (analyzers produce them, scoring.py scores them, fixgen.py fixes
them, roadmap.py renders them, eval/ grades them).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List


# Directories no analyzer should ever descend into -- vendored deps, VCS
# metadata, build artifacts, caches. Shared here (rather than in scan.py) so the
# analyzers that shell out to external tools walking the tree themselves (ruff in
# unused_code.py, jscpd in duplication.py) can exclude the SAME set the Python
# walker does. Without this, ruff happily scans .venv and returns tens of
# thousands of findings from third-party library code.
# ".code_debt" is this tool's OWN output directory (findings.json etc.) -- scanning
# it makes jscpd "find duplication" inside our own results. The Python walker skips
# it for free (it's dot-prefixed) but the external tools need it named explicitly.
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
               "build", ".mypy_cache", ".code_debt"}


FINDING_TYPES = (
    "long_function",
    "high_complexity",
    "duplication",
    "missing_tests",
    "dead_code",
    "long_parameter_list",
    "missing_docstring",
    "unused_import",
    "unused_variable",
    "magic_number",
)


def make_id(finding_type: str, file: str, line_start: int, line_end: int = 0,
            disambiguator: str = "") -> str:
    """Stable, content-derived id so re-scans don't churn ids.

    `disambiguator` (the finding's own description, in practice) keeps two
    distinct findings that share (type, file, line_start) from colliding on
    one id -- e.g. two magic-number literals on the same line (`max_val = 127
    if signed else 255`) previously hashed identically and silently shadowed
    each other in every id-keyed dict downstream (agent/scoring.py's
    by_id/heuristic_by_id). description already embeds the literal/symbol
    text that makes each finding unique, and is itself a deterministic
    function of the source, so ids stay stable across re-scans."""
    h = hashlib.sha1(
        f"{finding_type}:{file}:{line_start}:{line_end}:{disambiguator}".encode()
    ).hexdigest()[:10]
    return f"{finding_type}-{h}"


@dataclass
class Finding:
    type: str  # one of FINDING_TYPES
    file: str  # path relative to repo root
    line_start: int
    line_end: int
    description: str
    symbol: Optional[str] = None  # function/class name, if applicable
    metric: Dict[str, Any] = field(default_factory=dict)  # e.g. {"complexity": 14}
    evidence: Optional[str] = None  # short code excerpt
    severity: Optional[str] = None  # filled in later by heuristics; impact/effort by scoring.py
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = make_id(self.type, self.file, self.line_start, self.line_end, self.description)
        if self.type not in FINDING_TYPES:
            raise ValueError(f"Unknown finding type: {self.type!r}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Finding":
        return Finding(**d)


def write_findings(findings: List[Finding], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([fnd.to_dict() for fnd in findings], f, indent=2)


def read_findings(path: str) -> List[Finding]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return [Finding.from_dict(d) for d in raw]
