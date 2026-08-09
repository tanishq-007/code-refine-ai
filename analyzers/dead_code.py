"""
analyzers/dead_code.py

Heuristic dead-code detector for Python: flags module-level functions and
classes that are never referenced anywhere else in the repo (by name,
textually) outside of their own definition. This is intentionally simple
(no cross-module import resolution) but catches the common "I wrote this
and never wired it up" case cheaply and with zero dependencies.
"""
from __future__ import annotations

import ast
import os
import re
from typing import List, Dict

from analyzers.base import Finding


def _collect_defs(source: str, file_path: str):
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []
    defs = []
    for node in tree.body:  # module level only -> avoids flagging methods/helpers
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("_"):
                continue  # private-by-convention, likely intentional internal helper
            if node.name in ("main",):
                continue  # common entrypoint name
            # skip functions decorated as CLI commands / test fixtures / routes
            decorator_names = {
                d.id if isinstance(d, ast.Name) else getattr(d, "attr", "")
                for d in node.decorator_list
            }
            if decorator_names & {"fixture", "app", "command", "route", "task"}:
                continue
            end = getattr(node, "end_lineno", node.lineno)
            defs.append((node.name, node.lineno, end))
    return defs


def analyze_repo(repo_root: str, py_files: List[str]) -> List[Finding]:
    """py_files: list of file paths relative to repo_root."""
    sources: Dict[str, str] = {}
    for rel in py_files:
        with open(os.path.join(repo_root, rel), encoding="utf-8") as f:
            sources[rel] = f.read()

    all_defs: Dict[str, List] = {}
    for rel, src in sources.items():
        basename = os.path.basename(rel)
        if basename.startswith("test_") or basename.endswith("_test.py"):
            continue  # pytest discovers/calls these implicitly; not "dead" just because unreferenced
        all_defs[rel] = _collect_defs(src, rel)

    findings: List[Finding] = []
    for rel, defs in all_defs.items():
        for name, lineno, endline in defs:
            pattern = re.compile(rf"\b{re.escape(name)}\b")
            references = 0
            for other_rel, src in sources.items():
                for i, line in enumerate(src.splitlines(), start=1):
                    if other_rel == rel and lineno <= i <= endline:
                        continue  # skip the definition's own body
                    if pattern.search(line):
                        references += 1
            if references == 0:
                findings.append(Finding(
                    type="dead_code",
                    file=rel,
                    line_start=lineno,
                    line_end=endline,
                    symbol=name,
                    description=f"'{name}' is defined but never referenced elsewhere in the repo",
                    metric={"references": 0},
                ))
    return findings
