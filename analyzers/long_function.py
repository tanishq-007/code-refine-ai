"""
analyzers/long_function.py

Flags functions whose body exceeds a line-count threshold. Pure ast, no
external deps.
"""
from __future__ import annotations

import ast
from typing import List

from analyzers.base import Finding

DEFAULT_THRESHOLD = 50


def analyze(file_path: str, source: str, threshold: int = DEFAULT_THRESHOLD) -> List[Finding]:
    findings: List[Finding] = []
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return findings

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            length = end - node.lineno + 1
            if length > threshold:
                findings.append(Finding(
                    type="long_function",
                    file=file_path,
                    line_start=node.lineno,
                    line_end=end,
                    symbol=node.name,
                    description=f"'{node.name}' is {length} lines long (threshold {threshold})",
                    metric={"lines": length, "threshold": threshold},
                ))
    return findings
