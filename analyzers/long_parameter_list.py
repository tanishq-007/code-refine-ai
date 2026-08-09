"""
analyzers/long_parameter_list.py

Flags functions/methods with too many declared parameters. Pure ast, no
external dependency. The implicit first parameter of an instance/class
method (`self`/`cls`) is excluded from the count so methods aren't
penalised for it; *args/**kwargs are never counted either.
"""
from __future__ import annotations

import ast
from typing import List

from analyzers.base import Finding

DEFAULT_THRESHOLD = 5


def _param_count(node) -> int:
    positional = list(node.args.posonlyargs) + list(node.args.args)
    if positional and positional[0].arg in ("self", "cls"):
        positional = positional[1:]
    return len(positional) + len(node.args.kwonlyargs)


def analyze(file_path: str, source: str, threshold: int = DEFAULT_THRESHOLD) -> List[Finding]:
    findings: List[Finding] = []
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return findings

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            count = _param_count(node)
            if count > threshold:
                end = getattr(node, "end_lineno", node.lineno)
                findings.append(Finding(
                    type="long_parameter_list",
                    file=file_path,
                    line_start=node.lineno,
                    line_end=end,
                    symbol=node.name,
                    description=f"Function '{node.name}' has {count} parameters (max {threshold})",
                    metric={"param_count": count, "threshold": threshold},
                ))
    return findings
