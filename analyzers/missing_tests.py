"""
analyzers/missing_tests.py

Heuristic: a source module "has tests" if a conventionally-named test file
exists (test_<module>.py, <module>_test.py, or tests/test_<module>.py) AND
that test file mentions at least one public symbol from the module.
Otherwise every public top-level function/class in the module is flagged.

This deliberately over-flags (a test file can exist and genuinely cover the
module via indirection we can't see textually) -- precision is expected to
be low here by design. The impact/effort scorer in agent/scoring.py is
responsible for demoting false positives using broader context (RAG
standards, fan-in) that this cheap heuristic doesn't have access to.
"""
from __future__ import annotations

import ast
import os
import re
from typing import List, Dict

from analyzers.base import Finding


def _public_symbols(source: str, file_path: str) -> List[tuple]:
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                end = getattr(node, "end_lineno", node.lineno)
                out.append((node.name, node.lineno, end))
    return out


def _find_test_file(repo_root: str, rel_path: str) -> str | None:
    base = os.path.splitext(os.path.basename(rel_path))[0]
    dirname = os.path.dirname(rel_path)
    candidates = [
        os.path.join(dirname, f"test_{base}.py"),
        os.path.join(dirname, f"{base}_test.py"),
        os.path.join("tests", f"test_{base}.py"),
    ]
    for c in candidates:
        full = c if os.path.isabs(c) else os.path.join(repo_root, c)
        if os.path.exists(full):
            return full
    return None


def _call_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _indirectly_covered(repo_root: str, rel_path: str, symbol: str, test_source: str, source: str) -> bool:
    """Return True when a public symbol is exercised indirectly through another tested function.

    This general rule mirrors the detector's intent: if the symbol is not referenced directly in the
    matching test file but another tested function in the module is called from the tests and that inner
    function calls the symbol, then the module is still covered by the tests and should not be flagged.
    """
    if not test_source:
        return False

    module_name = os.path.splitext(os.path.basename(rel_path))[0]
    try:
        test_tree = ast.parse(test_source, filename=rel_path)
        source_tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return False
    test_call_names = _call_names(test_tree)
    source_call_names = _call_names(source_tree)

    if symbol in test_call_names:
        return True

    for candidate in test_call_names:
        if candidate in source_call_names and candidate != symbol:
            # A helper/function under test calling the target symbol is a strong indirect signal.
            pattern = re.compile(rf"\b{re.escape(candidate)}\s*\(")
            if pattern.search(source):
                return True

    return False


def analyze(repo_root: str, rel_path: str, source: str) -> List[Finding]:
    basename = os.path.basename(rel_path)
    if basename.startswith("test_") or basename.endswith("_test.py") or \
       rel_path.replace(os.sep, "/").split("/")[0] == "tests" or "/tests/" in rel_path.replace(os.sep, "/"):
        return []  # don't flag the tests themselves

    symbols = _public_symbols(source, rel_path)
    if not symbols:
        return []

    test_file = _find_test_file(repo_root, rel_path)
    test_source = ""
    if test_file:
        with open(test_file, encoding="utf-8") as f:
            test_source = f.read()

    findings: List[Finding] = []
    for name, lineno, endline in symbols:
        directly_covered = test_file is not None and name in test_source
        indirectly_covered = False
        if not directly_covered and test_file is not None:
            indirectly_covered = _indirectly_covered(repo_root, rel_path, name, test_source, source)
        covered = directly_covered or indirectly_covered
        if not covered:
            finding = Finding(
                type="missing_tests",
                file=rel_path,
                line_start=lineno,
                line_end=endline,
                symbol=name,
                description=(
                    f"No test file found referencing '{name}'"
                    if not test_file else
                    f"Test file exists but does not appear to reference '{name}'"
                ),
                metric={"has_test_file": test_file is not None},
            )
            findings.append(finding)
    return findings
