"""
analyzers/scan.py

Phase 1 entry point: walk a repo, run every analyzer that applies to each
file, and return the aggregated Finding list. Degrades gracefully -- any
analyzer that needs a missing external tool (jscpd, git) just contributes
nothing rather than raising.
"""
from __future__ import annotations

import os
from typing import List

from analyzers.base import Finding, write_findings, IGNORE_DIRS
from analyzers import complexity, long_function, dead_code, missing_tests, duplication, churn
from analyzers import long_parameter_list, missing_docstring, unused_code, magic_numbers, verify

PY_EXTS = (".py",)
JS_TS_EXTS = (".js", ".jsx", ".ts", ".tsx")

# IGNORE_DIRS lives in analyzers.base so the external-tool analyzers can share it;
# re-exported here since callers historically import it from analyzers.scan.


def _walk_files(repo_root: str, exts) -> List[str]:
    """Returns paths relative to repo_root."""
    out = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(exts):
                full = os.path.join(dirpath, fn)
                out.append(os.path.relpath(full, repo_root))
    return sorted(out)


def scan(repo_root: str) -> List[Finding]:
    findings: List[Finding] = []

    py_files = _walk_files(repo_root, PY_EXTS)

    for rel in py_files:
        full = os.path.join(repo_root, rel)
        with open(full, encoding="utf-8") as f:
            source = f.read()
        findings.extend(complexity.analyze(rel, source))
        findings.extend(long_function.analyze(rel, source))
        findings.extend(missing_tests.analyze(repo_root, rel, source))
        findings.extend(long_parameter_list.analyze(rel, source))
        findings.extend(missing_docstring.analyze(rel, source))
        findings.extend(magic_numbers.analyze(rel, source))

    # dead_code needs whole-repo context (cross-file reference search)
    findings.extend(dead_code.analyze_repo(repo_root, py_files))

    # duplication is polyglot -- jscpd walks JS/TS + Python itself when present;
    # py_files is passed so the AST-clone fallback (no jscpd on PATH) skips a
    # redundant repo walk.
    findings.extend(duplication.analyze_repo(repo_root, py_files))

    # unused_import/unused_variable: ruff walks the whole repo itself when
    # present; py_files is passed so the AST fallback (no ruff on PATH)
    # doesn't need to re-walk the tree we already walked above.
    findings.extend(unused_code.analyze_repo(repo_root, py_files))

    findings = verify.verify_findings(repo_root, findings)

    # churn is a signal, not findings; scoring.py pulls it in separately.
    return findings


def scan_to_file(repo_root: str, out_path: str) -> List[Finding]:
    findings = scan(repo_root)
    write_findings(findings, out_path)
    return findings
