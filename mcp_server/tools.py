"""
mcp_server/tools.py

Logic for the 6 MCP tools the agent uses, kept as plain testable Python
functions with no dependency on the `mcp` package itself (server.py is the
thin binding that exposes these over stdio). All file access is confined
to the repo root via `_safe_path` -- a path-traversal guard so a tool
can't be coaxed into reading/writing outside the target repo.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import List, Dict

from analyzers.base import Finding, IGNORE_DIRS, read_findings
from rag import retrieval


class PathTraversalError(Exception):
    pass


class NoDiffCachedError(Exception):
    """run_tests was called for a finding_id with no cached diff -- propose_fix
    must be called first for that id. Retryable: the model should call
    propose_fix, then retry run_tests with the same finding_id."""


# finding_id -> diff text, populated by propose_fix() and consumed by
# run_tests(). Deliberately module-level, not passed around: this file is
# imported exactly once per session on both transports -- the same Python
# process for in-process dispatch, and the same long-lived spawned
# subprocess for the whole MCP session (one spawn serves every finding in
# a `run`) -- so a plain dict here is visible to both tools on both paths
# without any extra plumbing. See run_tests()'s docstring for why this
# cache exists at all (it isn't just an optimization).
_DIFF_CACHE: Dict[str, str] = {}


def _safe_path(repo_root: str, rel_path: str) -> str:
    repo_root = os.path.abspath(repo_root)
    full = os.path.abspath(os.path.join(repo_root, rel_path))
    if not (full == repo_root or full.startswith(repo_root + os.sep)):
        raise PathTraversalError(f"'{rel_path}' escapes repo root")
    return full


def _sandbox_root(repo_root: str) -> str:
    """Returns a fresh, pristine copy of repo_root every time it's called.

    Deliberately re-copies rather than reusing a cached sandbox: propose_fix
    and run_tests each call this once per finding (and again on every retry
    of the same finding), and a stale sandbox would carry over whatever a
    previous finding's or attempt's applied diff left behind -- so a later
    finding's fix would be proposed/tested against already-mutated source
    instead of the real repo state."""
    repo_root = os.path.abspath(repo_root)
    sandbox = os.path.join(repo_root, ".code_debt", "sandbox")
    if os.path.exists(sandbox):
        shutil.rmtree(sandbox)
    # Skip the same dirs the analyzers do (IGNORE_DIRS) plus anything
    # dot-prefixed -- without the ".*" catch-all this drags in .claude/
    # worktrees, .venv/, and .env itself (copying live API keys into a
    # sandbox meant to be throwaway). See agent/fixgen.py's _SANDBOX_IGNORE
    # (kept as a separate copy, not a shared import -- see this function's
    # docstring note on the mcp_server/agent layering).
    shutil.copytree(repo_root, sandbox, ignore=shutil.ignore_patterns(*IGNORE_DIRS, ".*"))
    return sandbox


# ---------------------------------------------------------------------
# Tool 1: read_finding
# ---------------------------------------------------------------------
def read_finding(findings_path: str, finding_id: str) -> Dict:
    findings = read_findings(findings_path)
    for f in findings:
        if f.id == finding_id:
            return f.to_dict()
    raise KeyError(f"No finding with id {finding_id}")


# ---------------------------------------------------------------------
# Tool 2: read_file_snippet
# ---------------------------------------------------------------------
def read_file_snippet(repo_root: str, rel_path: str, line_start: int, line_end: int,
                       context: int = 3, numbered: bool = True) -> str:
    """numbered=True (the tool's default, used for the model's own
    read_file_snippet calls) prefixes each line with its line number for
    human/agent-reading display. propose_fix() below deliberately passes
    numbered=False -- the diff-generation prompt must show clean source,
    or the model echoes the "NNN| " prefixes into its diff output, which
    git apply then rejects."""
    full = _safe_path(repo_root, rel_path)
    with open(full, encoding="utf-8") as f:
        lines = f.readlines()
    start = max(0, line_start - 1 - context)
    end = min(len(lines), line_end + context)
    if not numbered:
        return "".join(lines[start:end])
    prefixed = [f"{i + 1:>5}| {lines[i]}" for i in range(start, end)]
    return "".join(prefixed)


# ---------------------------------------------------------------------
# Tool 3: get_standards
# ---------------------------------------------------------------------
def get_standards(finding_type: str) -> str:
    return retrieval.get_standards(finding_type)


# ---------------------------------------------------------------------
# Tool 4: search_codebase
# ---------------------------------------------------------------------
def search_codebase(repo_root: str, pattern: str, max_results: int = 50) -> List[Dict]:
    regex = re.compile(pattern)
    results = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith((".py", ".js", ".jsx", ".ts", ".tsx")):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, repo_root)
            try:
                with open(full, encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, start=1):
                        if regex.search(line):
                            results.append({"file": rel, "line": i, "text": line.rstrip()})
                            if len(results) >= max_results:
                                return results
            except OSError:
                continue
    return results


# ---------------------------------------------------------------------
# Tool 5: propose_fix
# ---------------------------------------------------------------------
def propose_fix(repo_root: str, findings_path: str, finding_id: str) -> Dict:
    """Thin wrapper around agent.fixgen -- kept here so the MCP tool surface
    is the single place the agent dispatches through. Caches the diff under
    finding_id (see _DIFF_CACHE) so run_tests() can apply it without the
    model ever having to carry the diff text itself."""
    from agent import fixgen  # local import: avoids mcp_server <-> agent import cycle at module load
    finding_dict = read_finding(findings_path, finding_id)
    finding = Finding.from_dict(finding_dict)
    working_root = _sandbox_root(repo_root)
    snippet = read_file_snippet(working_root, finding.file, finding.line_start, finding.line_end,
                                 numbered=False)
    result = fixgen.propose_fix(finding, snippet, working_root)
    _DIFF_CACHE[finding_id] = result.get("diff", "")
    return result


# ---------------------------------------------------------------------
# Tool 6: run_tests
# ---------------------------------------------------------------------
def run_tests(repo_root: str, finding_id: str) -> Dict:
    """Applies the diff most recently proposed for finding_id (via
    propose_fix, server-side cached in _DIFF_CACHE) to a throwaway copy of
    repo_root and runs its test suite. Never touches the caller's actual
    tree.

    Deliberately takes finding_id, not diff text: the model used to have to
    copy propose_fix's (possibly large, multi-line) diff text verbatim into
    this tool's own arguments, and a real failure mode was observed where it
    double-escaped that text in the process (literal "\\n" instead of actual
    newlines), corrupting the diff -- git reported "corrupt patch" even
    though the diff propose_fix generated was valid. Passing back an id the
    model already has instead of a multi-line string it has to retype
    eliminates that whole failure mode structurally."""
    from agent import fixgen
    if finding_id not in _DIFF_CACHE:
        raise NoDiffCachedError(
            f"No diff cached for finding_id {finding_id!r} -- call propose_fix first."
        )
    diff_text = _DIFF_CACHE[finding_id]
    return fixgen.apply_and_verify(repo_root, diff_text, sandbox_root=_sandbox_root(repo_root))


TOOL_SCHEMAS = [
    {
        "name": "read_finding",
        "description": "Look up the full record for a single finding by id.",
        "input_schema": {
            "type": "object",
            "properties": {"finding_id": {"type": "string"}},
            "required": ["finding_id"],
        },
    },
    {
        "name": "read_file_snippet",
        "description": "Read a line range (with surrounding context) from a file in the repo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rel_path": {"type": "string"},
                "line_start": {"type": "integer"},
                "line_end": {"type": "integer"},
            },
            "required": ["rel_path", "line_start", "line_end"],
        },
    },
    {
        "name": "get_standards",
        "description": "Retrieve coding-standards guidance relevant to a finding type.",
        "input_schema": {
            "type": "object",
            "properties": {"finding_type": {"type": "string"}},
            "required": ["finding_type"],
        },
    },
    {
        "name": "search_codebase",
        "description": "Regex-search the codebase for a pattern; returns matching file/line/text.",
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "required": ["pattern"],
        },
    },
    {
        "name": "propose_fix",
        "description": "Generate a unified-diff fix proposal for a given finding id.",
        "input_schema": {
            "type": "object",
            "properties": {"finding_id": {"type": "string"}},
            "required": ["finding_id"],
        },
    },
    {
        "name": "run_tests",
        "description": "Apply the most recently proposed fix for a finding id to a throwaway copy "
                       "of the repo and run its tests. Requires propose_fix to have been called "
                       "for this finding_id first.",
        "input_schema": {
            "type": "object",
            "properties": {"finding_id": {"type": "string"}},
            "required": ["finding_id"],
        },
    },
]
