"""
analyzers/duplication.py

Prefers shelling out to `jscpd` (polyglot copy-paste detector, npm i -g
jscpd) for duplication findings across Python/JS/TS -- it's the right tool
for token-level clone detection across languages.

If jscpd isn't on PATH, this used to just return an empty list -- recall
was flatly 0 with no fallback at all. There IS a reasonable dependency-free
fallback for the Python-only case: normalize each function body to an AST
structural signature (statement shapes + literal values, with local
identifiers/parameter names mapped to positional placeholders so a simple
rename doesn't defeat the match -- i.e. it catches type-2 clones, not just
byte-identical type-1 clones) and hash it. Two functions whose signatures
collide are structurally identical regardless of naming. This intentionally
does NOT do jscpd's token-window/percentage-overlap analysis (partial
duplication within a larger function) -- it only catches whole-function
clones -- so when jscpd is present, its output is used instead and this
fallback doesn't run.
"""
from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
import tempfile
import os
from collections import defaultdict
from typing import Dict, List, Optional

from analyzers.base import Finding, IGNORE_DIRS

MIN_LINES = 5  # matches the jscpd path's --min-lines, so both report at the same granularity


def jscpd_available() -> bool:
    return shutil.which("jscpd") is not None


def _run_jscpd(repo_root: str) -> List[Finding]:
    with tempfile.TemporaryDirectory() as tmp:
        report_path = os.path.join(tmp, "jscpd-report.json")
        # jscpd walks repo_root itself, so exclude vendored/build dirs (the same
        # set the Python walker skips) or it reports duplication inside .venv and
        # node_modules. --ignore takes comma-separated globs.
        ignore = ",".join(f"**/{d}/**" for d in sorted(IGNORE_DIRS))
        cmd = [
            "jscpd", repo_root,
            "--reporters", "json",
            "--output", tmp,
            "--silent",
            "--ignore", ignore,
            # Restrict to the code languages this analyzer claims to cover. Without
            # this jscpd also flags prose duplication in README/ARCHITECTURE
            # markdown, which isn't the code-debt this tool reports on.
            "--format", "python,javascript,jsx,typescript,tsx",
            "--min-lines", "5",
            "--min-tokens", "50",
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=120, check=False)
        except (subprocess.SubprocessError, OSError):
            return []

        json_out = os.path.join(tmp, "jscpd-report.json")
        if not os.path.exists(json_out):
            return []
        with open(json_out) as f:
            report = json.load(f)

    findings: List[Finding] = []
    for dup in report.get("duplicates", []):
        first = dup["firstFile"]
        rel = os.path.relpath(first["name"], repo_root)
        findings.append(Finding(
            type="duplication",
            file=rel,
            line_start=first["start"],
            line_end=first["end"],
            description=(
                f"{dup.get('lines', '?')} duplicated lines shared with "
                f"{os.path.relpath(dup['secondFile']['name'], repo_root)}"
            ),
            metric={
                "lines": dup.get("lines"),
                "tokens": dup.get("tokens"),
                "duplicate_of": os.path.relpath(dup["secondFile"]["name"], repo_root),
            },
        ))
    return findings


# ---------------------------------------------------------------------
# Dependency-free AST structural-clone fallback (used only when jscpd is
# not on PATH). Python files only -- jscpd is still the only path that
# covers JS/TS.
# ---------------------------------------------------------------------

def _structural_signature(func: ast.AST) -> Optional[str]:
    """A hash of the function's shape: statement/expression node types and
    literal values, with Name/arg identifiers mapped to positional
    placeholders (V0, V1, ...) in first-seen order -- so `def f(a, b): return
    a+b` and `def g(x, y): return x+y` hash identically, but `return a+b`
    vs `return a-b` (different op) or `return a+1` (different literal) do
    not. Returns None if the body is only a docstring/pass (too trivial to
    call duplication)."""
    body = func.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]  # drop the docstring -- it's prose, not structure
    if not body or (len(body) == 1 and isinstance(body[0], ast.Pass)):
        return None

    name_map: Dict[str, str] = {}

    def placeholder(identifier: str) -> str:
        if identifier not in name_map:
            name_map[identifier] = f"V{len(name_map)}"
        return name_map[identifier]

    for arg in list(func.args.args) + list(func.args.kwonlyargs):
        placeholder(arg.arg)  # parameters get their placeholders assigned first, in declared order

    shape: List[str] = []
    wrapper = ast.Module(body=body, type_ignores=[])
    for node in ast.walk(wrapper):
        if isinstance(node, ast.Name):
            shape.append(f"Name:{placeholder(node.id)}")
        elif isinstance(node, ast.arg):
            shape.append(f"arg:{placeholder(node.arg)}")
        elif isinstance(node, ast.Constant):
            shape.append(f"Const:{node.value!r}")
        elif isinstance(node, ast.Attribute):
            shape.append(f"Attribute:{node.attr}")  # attribute names ARE structural (e.g. .append vs .pop)
        else:
            shape.append(type(node).__name__)

    return hashlib.sha1(json.dumps(shape).encode()).hexdigest()


def _iter_functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _fallback_python_duplication(repo_root: str, py_files: List[str]) -> List[Finding]:
    # signature -> list of (rel_path, node)
    groups: Dict[str, List] = defaultdict(list)
    function_count = 0

    for rel in sorted(py_files):
        full = os.path.join(repo_root, rel)
        try:
            with open(full, encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filename=rel)
        except (OSError, SyntaxError):
            continue
        for func in _iter_functions(tree):
            function_count += 1
            end = getattr(func, "end_lineno", func.lineno)
            if end - func.lineno + 1 < MIN_LINES:
                continue  # too short to be meaningful duplication, same floor as jscpd's --min-lines
            sig = _structural_signature(func)
            if sig:
                groups[sig].append((rel, func))

    group_count = sum(1 for members in groups.values() if len(members) >= 2)
    print(f"[duplication debug] fallback walked {function_count} Python functions; found {group_count} structural groups with 2+ members")

    findings: List[Finding] = []
    for sig, members in groups.items():
        if len(members) < 2:
            continue
        # Every function in the group is pairwise structurally identical --
        # report each one, pointing at one other member as its match (mirrors
        # jscpd's firstFile/secondFile pairing without needing every N-choose-2 pair).
        for i, (rel, func) in enumerate(members):
            other_rel, other_func = members[(i + 1) % len(members)]
            if other_rel == rel and other_func is func:
                continue
            end = getattr(func, "end_lineno", func.lineno)
            findings.append(Finding(
                type="duplication",
                file=rel,
                line_start=func.lineno,
                line_end=end,
                symbol=func.name,
                description=(
                    f"'{func.name}' is structurally identical to "
                    f"'{other_func.name}' in {other_rel} (AST clone detection)"
                ),
                metric={
                    "lines": end - func.lineno + 1,
                    "duplicate_of": other_rel,
                    "detector": "ast-fallback",
                },
            ))
    return findings


def analyze_repo(repo_root: str, py_files: Optional[List[str]] = None) -> List[Finding]:
    jscpd = jscpd_available()
    print(f"[duplication debug] jscpd_available={jscpd}")
    if jscpd:
        return _run_jscpd(repo_root)

    if py_files is None:
        py_files = []
        for dirpath, dirnames, filenames in os.walk(repo_root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
            for fn in filenames:
                if fn.endswith(".py"):
                    py_files.append(os.path.relpath(os.path.join(dirpath, fn), repo_root))

    return _fallback_python_duplication(repo_root, py_files)
