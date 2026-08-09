"""
analyzers/unused_code.py

Prefers shelling out to `ruff` (pip install ruff) for unused-import (F401)
and unused-local-variable (F841) findings -- ruff's scope analysis handles
edge cases (closures, comprehensions, __all__ re-exports) more precisely
than a hand-rolled pass would.

If `ruff` isn't on PATH, this used to just return nothing -- recall was
flatly 0 until ruff was installed, silently, with no signal that anything
was degraded. That's now a real gap, not an acceptable one: unused_import
and unused_variable are pure single-file AST properties (unlike
duplication's jscpd, which genuinely needs cross-file token comparison
that isn't reasonably hand-rolled). So there IS a dependency-free fallback
below (_fallback_unused_imports/_fallback_unused_variables) that does real
per-function scope analysis -- not text/regex matching -- covering the
common cases (plain `import x`, `from x import y`, `__all__` re-exports,
simple local assignment-then-never-read). It intentionally does NOT try to
replicate ruff's handling of every closure/comprehension/walrus edge case;
when ruff is present, its output is used instead and the fallback doesn't
run at all.

No double-reporting with analyzers/dead_code.py: that analyzer covers
unused top-level functions/classes; this one covers imports and local
variables. They don't overlap by construction.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional, Set

from analyzers.base import Finding, IGNORE_DIRS

_CODE_TO_TYPE = {
    "F401": "unused_import",
    "F841": "unused_variable",
}

_SYMBOL_RE = re.compile(r"`([^`]+)`")

def ruff_available() -> bool:
    return shutil.which("ruff") is not None


def _symbol_from_message(message: str) -> Optional[str]:
    """ruff's F401/F841 messages always quote the identifier in backticks,
    e.g. "`os` imported but unused" -- pull it out for consistency with
    every other analyzer's `symbol` field (ruff's JSON doesn't give it to
    us structured)."""
    m = _SYMBOL_RE.search(message)
    return m.group(1) if m else None


def _run_ruff(repo_root: str) -> List[Finding]:
    # Ruff walks repo_root itself, so it must be told to skip vendored/build dirs
    # too -- otherwise it scans .venv and returns tens of thousands of findings from
    # third-party code. --force-exclude makes the excludes apply even though
    # repo_root is passed explicitly on the command line (without it, ruff ignores
    # its exclude list for directly-named paths). --extend-exclude (not --exclude)
    # so this adds to ruff's own defaults instead of replacing them; the ".*" glob
    # covers any dot-directory (.claude, .idea, ...), matching the blanket
    # `not d.startswith(".")` rule every Python-walk analyzer already applies.
    exclude = ",".join(sorted(IGNORE_DIRS) + [".*"])
    cmd = ["ruff", "check", "--select", "F401,F841", "--output-format", "json",
           "--extend-exclude", exclude, "--force-exclude", repo_root]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    except (subprocess.SubprocessError, OSError):
        return []

    try:
        items = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []

    findings: List[Finding] = []
    for item in items:
        ftype = _CODE_TO_TYPE.get(item.get("code"))
        if ftype is None:
            continue  # not one of the two rules we asked for

        rel = os.path.relpath(item["filename"], repo_root)
        line = item["location"]["row"]
        end_line = item.get("end_location", {}).get("row", line)
        message = item.get("message", "")

        findings.append(Finding(
            type=ftype,
            file=rel,
            line_start=line,
            line_end=end_line,
            symbol=_symbol_from_message(message),
            description=message,
            metric={"code": item.get("code")},
        ))
    return findings


# ---------------------------------------------------------------------
# Dependency-free AST fallback (used only when ruff is not on PATH)
# ---------------------------------------------------------------------

def _module_all_exports(tree: ast.Module) -> Set[str]:
    """Names listed in a module-level `__all__ = [...]`/`(...)` -- these are
    re-exports, not unused, even if nothing in-file references them."""
    exports: Set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                exports.update(
                    elt.value for elt in node.value.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                )
    return exports


def _fallback_unused_imports(rel_path: str, source: str) -> List[Finding]:
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return []

    exports = _module_all_exports(tree)

    imports: Dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                if bound != "_":
                    imports[bound] = node
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue  # star imports can't be attributed to a single name
                bound = alias.asname or alias.name
                if bound != "_":
                    imports[bound] = node

    if not imports:
        return []

    # A name counts as "used" if it appears as a Load anywhere outside the
    # import statements themselves -- Name loads, attribute bases (pkg.attr
    # still Loads `pkg`), and decorator references all walk through this.
    used: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)

    findings: List[Finding] = []
    for name, node in imports.items():
        if name in used or name in exports:
            continue
        end = getattr(node, "end_lineno", node.lineno)
        findings.append(Finding(
            type="unused_import",
            file=rel_path,
            line_start=node.lineno,
            line_end=end,
            symbol=name,
            description=f"`{name}` imported but unused",
            metric={"code": "AST-fallback"},
        ))
    return findings


class _FunctionScopeVisitor(ast.NodeVisitor):
    """Per-function local-variable liveness: a simple `name = value` (or
    annotated) assignment to a Name is flagged if that name is never read
    (Load) anywhere later in the SAME function body. Deliberately narrow --
    only plain Name targets, never augmented assignment (that's a read+write,
    already a use), never for-loop/with-as targets (idiomatically often
    unused, e.g. `for _ in range(n)`), never function parameters. This
    intentionally does not attempt ruff's full precision; it exists to give
    unused_variable non-zero recall when ruff is unavailable, not to replace
    ruff when it is."""

    def __init__(self) -> None:
        self.findings: List[Finding] = []

    def visit_FunctionDef(self, node):
        self._check_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._check_function(node)
        self.generic_visit(node)

    def _check_function(self, func) -> None:
        assigned: Dict[str, ast.AST] = {}
        for sub in ast.walk(func):
            if isinstance(sub, ast.Assign):
                for t in sub.targets:
                    if isinstance(t, ast.Name) and not t.id.startswith("_"):
                        assigned[t.id] = sub
            elif isinstance(sub, ast.AnnAssign) and sub.value is not None:
                if isinstance(sub.target, ast.Name) and not sub.target.id.startswith("_"):
                    assigned[sub.target.id] = sub

        if not assigned:
            return

        read: Set[str] = set()
        for sub in ast.walk(func):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                read.add(sub.id)

        for name, node in assigned.items():
            if name in read:
                continue
            end = getattr(node, "end_lineno", node.lineno)
            self.findings.append(Finding(
                type="unused_variable",
                file="",  # filled in by caller
                line_start=node.lineno,
                line_end=end,
                symbol=name,
                description=f"local variable `{name}` is assigned but never used",
                metric={"code": "AST-fallback"},
            ))


def _fallback_unused_variables(rel_path: str, source: str) -> List[Finding]:
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return []
    visitor = _FunctionScopeVisitor()
    visitor.visit(tree)
    for f in visitor.findings:
        f.file = rel_path
    return visitor.findings


def analyze_repo(repo_root: str, py_files: Optional[List[str]] = None) -> List[Finding]:
    if ruff_available():
        return _run_ruff(repo_root)

    # No ruff -- fall back to the AST-only pass above rather than silently
    # returning nothing. py_files is optional for backward compatibility
    # (callers that don't pass it get a self-walked file list, same pattern
    # as analyzers/dead_code.py's analyze_repo).
    if py_files is None:
        py_files = []
        for dirpath, dirnames, filenames in os.walk(repo_root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
            for fn in filenames:
                if fn.endswith(".py"):
                    py_files.append(os.path.relpath(os.path.join(dirpath, fn), repo_root))

    findings: List[Finding] = []
    for rel in sorted(py_files):
        basename = os.path.basename(rel)
        if basename.startswith("test_") or basename.endswith("_test.py"):
            continue  # test files commonly have intentionally-unused fixtures/imports
        full = os.path.join(repo_root, rel)
        try:
            with open(full, encoding="utf-8") as f:
                source = f.read()
        except OSError:
            continue
        findings.extend(_fallback_unused_imports(rel, source))
        findings.extend(_fallback_unused_variables(rel, source))
    return findings
