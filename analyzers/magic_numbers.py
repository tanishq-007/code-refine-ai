"""
analyzers/magic_numbers.py

Flags inline numeric literals that aren't obviously self-explanatory.
Pure ast, no external dependency.

Two AST gotchas this analyzer specifically guards against:
  - `bool` is a subclass of `int` in Python (`isinstance(True, int)` is
    True), so booleans are explicitly excluded.
  - A negative literal like `-1` does not parse as `Constant(-1)` -- it's
    `UnaryOp(op=USub, operand=Constant(1))`. The effective (signed) value
    is normalised before checking it against the allowlist.

Known limitation: heuristic. Some inline numbers are genuinely fine;
precision depends entirely on the allowlist/skip rules below. The
impact/effort scorer is expected to demote low-value hits using broader
context this analyzer doesn't have.
"""
from __future__ import annotations

import ast
from typing import List, Tuple

from analyzers.base import Finding

ALLOWLIST = {-1, 0, 1, 2}


def _is_test_file(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/")
    basename = norm.rsplit("/", 1)[-1]
    return (
        basename.startswith("test_") or basename.endswith("_test.py")
        or norm.split("/")[0] == "tests" or "/tests/" in norm
    )


class _Visitor(ast.NodeVisitor):
    """Single top-down pass. Assignment-to-a-Name RHS values and function
    default-arg values are marked "skip" (by node id) *before* the normal
    traversal reaches them, so the generic Constant/UnaryOp handlers below
    never flag them -- everything else (including other literals nested
    deeper in the same statement) is still visited normally."""

    def __init__(self) -> None:
        self.findings: List[Tuple[ast.AST, float]] = []
        self._skip_ids = set()

    def _mark_skip(self, value_node) -> None:
        if value_node is None:
            return
        if isinstance(value_node, ast.Constant) or (
            isinstance(value_node, ast.UnaryOp) and isinstance(value_node.operand, ast.Constant)
        ):
            self._skip_ids.add(id(value_node))

    def visit_Assign(self, node: ast.Assign) -> None:
        # e.g. TIMEOUT = 30 -- the named constant IS the fix, not the smell
        if any(isinstance(t, ast.Name) for t in node.targets):
            self._mark_skip(node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            self._mark_skip(node.value)
        self.generic_visit(node)

    def _visit_function(self, node) -> None:
        for default in list(node.args.defaults) + list(node.args.kw_defaults):
            self._mark_skip(default)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        if isinstance(node.op, (ast.USub, ast.UAdd)) and isinstance(node.operand, ast.Constant):
            sign = -1 if isinstance(node.op, ast.USub) else 1
            self._maybe_flag(node, node.operand.value, sign)
            return  # don't also visit the wrapped Constant as an unsigned literal
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        self._maybe_flag(node, node.value, sign=1)

    def _maybe_flag(self, node, raw_value, sign: int) -> None:
        if isinstance(raw_value, bool):
            return  # bool is a subclass of int -- explicitly excluded
        if not isinstance(raw_value, (int, float)):
            return  # numbers only -- not strings, None, etc.
        if id(node) in self._skip_ids:
            return  # named-constant assignment or a default arg -- that's the fix, not the smell
        effective = sign * raw_value
        if effective in ALLOWLIST:
            return
        self.findings.append((node, effective))


def analyze(file_path: str, source: str) -> List[Finding]:
    if _is_test_file(file_path):
        return []

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []

    visitor = _Visitor()
    visitor.visit(tree)

    findings: List[Finding] = []
    for node, value in visitor.findings:
        findings.append(Finding(
            type="magic_number",
            file=file_path,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            symbol=None,
            description=f"Magic number {value!r} used inline; consider a named constant",
            metric={"value": value},
        ))
    return findings
