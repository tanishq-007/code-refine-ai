"""
analyzers/missing_docstring.py

Flags public modules/classes/functions with no docstring. Pure ast, no
external dependency. Uses ast.get_docstring() (handles the "first
statement is a bare string" convention correctly); a whitespace-only
docstring counts as missing. Any name starting with `_` is skipped --
this automatically excludes all dunders (__init__, __str__, ...), which
keeps precision reasonable.

Known limitation: presence-only. This does not judge docstring quality,
only existence -- deliberate, to keep the rule simple and unambiguous.
"""
from __future__ import annotations

import ast
from typing import List

from analyzers.base import Finding


def _missing(node) -> bool:
    doc = ast.get_docstring(node)
    return doc is None or not doc.strip()


def analyze(file_path: str, source: str) -> List[Finding]:
    findings: List[Finding] = []
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return findings

    if tree.body and _missing(tree):
        findings.append(Finding(
            type="missing_docstring",
            file=file_path,
            line_start=1,
            line_end=1,
            symbol=None,
            description=f"Module '{file_path}' has no docstring",
            metric={"kind": "module"},
        ))

    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue  # private-by-convention (and all dunders) -- not required to document
            if _missing(node):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                end = getattr(node, "end_lineno", node.lineno)
                findings.append(Finding(
                    type="missing_docstring",
                    file=file_path,
                    line_start=node.lineno,
                    line_end=end,
                    symbol=node.name,
                    description=f"Public {kind} '{node.name}' has no docstring",
                    metric={"kind": kind},
                ))
    return findings
