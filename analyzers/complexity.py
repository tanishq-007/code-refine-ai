"""
analyzers/complexity.py

Cyclomatic complexity for Python. Uses `radon` if it's installed (more
battle-tested), otherwise falls back to a small ast-based counter so the
tool still works with zero external dependencies. Degrades gracefully, per
the project's design goal of Phase 1 working with nothing installed.
"""
from __future__ import annotations

import ast
from typing import List

from analyzers.base import Finding

DEFAULT_THRESHOLD = 10


def _ast_complexity(func_node: ast.AST) -> int:
    """Cyclomatic complexity = 1 + number of decision points."""
    complexity = 1
    decision_nodes = (
        ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try,
        ast.ExceptHandler, ast.With, ast.AsyncWith,
        ast.comprehension, ast.BoolOp,
    )
    for node in ast.walk(func_node):
        if isinstance(node, decision_nodes):
            complexity += 1
        # each `and`/`or` operand beyond the first adds a branch
        if isinstance(node, ast.BoolOp):
            complexity += max(0, len(node.values) - 1)
    return complexity


def _radon_complexity(source: str):
    """Returns list of (name, lineno, endline, complexity) via radon, or None
    if radon isn't installed."""
    try:
        from radon.complexity import cc_visit
    except ImportError:
        return None
    results = []
    for block in cc_visit(source):
        results.append((block.name, block.lineno, block.endline, block.complexity))
    return results


def analyze(file_path: str, source: str, threshold: int = DEFAULT_THRESHOLD) -> List[Finding]:
    findings: List[Finding] = []

    radon_results = _radon_complexity(source)
    if radon_results is not None:
        for name, lineno, endline, cc in radon_results:
            if cc > threshold:
                findings.append(Finding(
                    type="high_complexity",
                    file=file_path,
                    line_start=lineno,
                    line_end=endline,
                    symbol=name,
                    description=f"'{name}' has cyclomatic complexity {cc} (threshold {threshold}) [radon]",
                    metric={"complexity": cc, "threshold": threshold, "source": "radon"},
                ))
        return findings

    # ast fallback
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return findings

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cc = _ast_complexity(node)
            if cc > threshold:
                end = getattr(node, "end_lineno", node.lineno)
                findings.append(Finding(
                    type="high_complexity",
                    file=file_path,
                    line_start=node.lineno,
                    line_end=end,
                    symbol=node.name,
                    description=f"'{node.name}' has cyclomatic complexity {cc} (threshold {threshold}) [ast]",
                    metric={"complexity": cc, "threshold": threshold, "source": "ast"},
                ))
    return findings
