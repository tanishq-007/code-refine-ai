"""
agent/fixgen.py

Proposes refactoring fixes and verifies them safely: apply_and_verify()
copies the repo to a throwaway tmp directory, applies the diff there, and
runs the test suite -- it never touches the caller's actual working tree.

propose_fix() does NOT ask the model to hand-author a unified diff. That
design was tried first and was unreliable in three distinct ways observed
in testing: the model would echo read_file_snippet's "NNN| " line-number
prefixes into the diff body (fixed separately by showing it unprefixed
source -- see mcp_server/tools.py's read_file_snippet(numbered=False));
even with clean source, it would still sometimes invent wrong @@ hunk
line numbers, or hallucinate a context line that isn't actually in the
file -- both silently break `git apply`'s exact-context-match requirement.

Instead, the model returns a STRUCTURED edit -- {"edits": [{"old_str":
"<exact existing text>", "new_str": "<replacement>"}]}, str_replace
semantics -- and the unified diff is built deterministically here with
difflib.unified_diff(), which computes correct hunk headers and context
by construction. The model only has to reproduce text it was already
shown verbatim, not author line numbers or diff syntax it's never fully
reliable at. propose_fix()'s return shape ({"finding_id", "diff"}) and
run_tests' input (diff text) are unchanged -- nothing downstream needs to
know this changed.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional

from analyzers.base import Finding, IGNORE_DIRS
from agent import llm_client
from rag import fix_examples

SYSTEM_PROMPT = """You are refactoring a specific piece of technical debt in a codebase.
You will be given a Finding (type, file, line range, description, metrics) and the current
source snippet with surrounding context. Propose a minimal, behavior-preserving fix.

Output ONLY strict JSON with this exact shape and nothing else:
{"edits": [{"old_str": "<exact existing code, copied verbatim>", "new_str": "<replacement code>"}]}

Rules:
- old_str must be an EXACT, verbatim substring of the source you were shown -- copy it
  character-for-character, including original whitespace/indentation. The source you were
  shown has no line numbers or annotations; don't invent any in old_str either.
- old_str must be specific enough to appear exactly once in the file -- include a line or two
  of surrounding context if the target line alone isn't unique.
- new_str is the replacement text for that exact span. Nothing else -- no line numbers, no
  diff syntax, no @@ hunks.
- You may include more than one edit if the fix genuinely requires it, but keep the change as
  small as possible while actually resolving the finding -- don't rewrite unrelated code."""

MAX_FIX_ATTEMPTS = 3  # retries let the model self-correct a bad/non-matching edit instead of giving up

# Sandbox/tempdir copies must skip the same dirs the analyzers do (IGNORE_DIRS)
# plus anything dot-prefixed -- without the ".*" catch-all, a copytree with
# only ".git" excluded drags in .claude/ (IDE state, worktrees -- observed at
# 162MB in one case), .venv/, and -- worse -- .env itself, copying live API
# keys into a sandbox that's supposed to be a throwaway.
_SANDBOX_IGNORE = shutil.ignore_patterns(*IGNORE_DIRS, ".*")


class EditNotFoundError(Exception):
    """A structured edit's old_str didn't match the file exactly once. Retryable --
    the caller feeds this back to the model rather than guessing what was meant."""


def _apply_edits(original_content: str, edits: List[Dict]) -> str:
    """Applies each {old_str, new_str} edit in order against the evolving
    content (so a later edit can target text a prior edit introduced).
    Raises EditNotFoundError -- never silently guesses -- if old_str isn't
    found exactly once at the point it's applied."""
    current = original_content
    for edit in edits:
        old_str = edit["old_str"]
        new_str = edit["new_str"]
        count = current.count(old_str)
        if count != 1:
            raise EditNotFoundError(
                f"old_str matched {count} time(s) in the file (need exactly 1): {old_str!r}"
            )
        current = current.replace(old_str, new_str, 1)
    return current


def build_unified_diff(original_content: str, modified_content: str, rel_path: str) -> str:
    """Deterministic unified diff between two full-file contents, with the
    same a/<path> b/<path> headers git apply/preview_fix expect. Shared by
    propose_fix (model-authored edits) and the web UI's manual-edit flow
    (update_fix_from_edit) so both produce diffs in exactly the same format."""
    # git's diff format is always forward-slash, even on Windows -- rel_path
    # may be a native os.path (backslash on Windows), so it must be normalised
    # here or `git apply` rejects the header outright ("invalid path 'src\\x.py'").
    posix_path = rel_path.replace("\\", "/")
    return "".join(difflib.unified_diff(
        original_content.splitlines(keepends=True),
        modified_content.splitlines(keepends=True),
        fromfile=f"a/{posix_path}", tofile=f"b/{posix_path}",
    ))


def propose_fix(finding: Finding, snippet: str, repo_root: str) -> Dict:
    """Returns {"finding_id": ..., "diff": ...} (empty diff if the model
    never produced a valid edit within MAX_FIX_ATTEMPTS). Requires an LLM
    key (LLM_API_KEY/MISTRAL_API_KEY); raises a clear error otherwise (there's
    no meaningful offline fallback for diff generation -- unlike scoring,
    this isn't something a cheap heuristic can approximate)."""
    if not llm_client.have_key():
        raise RuntimeError(
            "No LLM_API_KEY/MISTRAL_API_KEY set -- fix generation requires a live "
            "LLM. Scoring and eval work offline; this step doesn't."
        )

    full_path = os.path.join(repo_root, finding.file)
    with open(full_path, encoding="utf-8") as f:
        original_content = f.read()

    examples = fix_examples.get_examples(finding.type)
    example_text = ""
    if examples:
        example_text = "\n\n".join(
            f"Example:\nBefore:\n{ex['before']}\n\nAfter:\n{ex['after']}"
            for ex in examples
        )
    user_msg = (
        f"Finding: {finding.to_dict()}\n\n"
        f"Current source (file: {finding.file}):\n{snippet}\n\n"
        f"{example_text}\n\n"
        f"Produce the structured edit(s) fixing this finding."
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    diff_text = ""
    for _ in range(MAX_FIX_ATTEMPTS):
        # RateLimitExhausted intentionally isn't caught here: retrying it burns another
        # request against the same limit, so it propagates straight to the caller.
        raw_out: List[str] = []
        try:
            parsed = llm_client.request_json_response(
                model=llm_client.FIX_MODEL,
                max_tokens=1500,
                messages=messages,
                raw_out=raw_out,
            )
            edits = parsed["edits"]
            if not edits:
                raise ValueError("empty \"edits\" list")
            patched_content = _apply_edits(original_content, edits)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, EditNotFoundError) as e:
            # Retryable: ask the same model to correct itself rather than falling back
            # to anything non-LLM, or guessing what edit it meant. raw_out is populated
            # even when parsing itself failed (parse_json_response raises after
            # request_json_response already appended to it), so the model's actual
            # bad response is always available here, not just on a valid-JSON/bad-edit failure.
            raw = raw_out[0] if raw_out else ""
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content":
                f"That didn't work: {e}. Reply again with ONLY the JSON "
                '{"edits": [{"old_str": "...", "new_str": "..."}]} -- old_str must be '
                "copied EXACTLY from the source shown above, with no line numbers."})
            continue

        diff_text = build_unified_diff(original_content, patched_content, finding.file)
        break

    return {"finding_id": finding.id, "diff": diff_text}


_DIFF_PATH_RE = re.compile(r"^--- a/(.+)$", re.MULTILINE)


def preview_fix(repo_root: str, diff_text: str) -> Dict:
    """Reconstructs the full before/after file content a diff represents --
    for the web UI's split editor, which needs whole-file text rather than
    just the diff's own hunks. Applies diff_text to a throwaway copy of the
    single file it touches (same git-apply-with-patch-fallback approach as
    apply_and_verify); never touches repo_root. Returns
    {"path", "original", "modified"}."""
    match = _DIFF_PATH_RE.search(diff_text)
    if not match:
        raise ValueError("diff has no '--- a/<path>' header to preview")
    rel_path = match.group(1)

    full_path = os.path.realpath(os.path.join(repo_root, rel_path))
    if not full_path.startswith(os.path.realpath(repo_root) + os.sep):
        raise ValueError("diff path escapes repo root")
    with open(full_path, encoding="utf-8") as f:
        original = f.read()

    with tempfile.TemporaryDirectory() as tmp:
        dest = os.path.join(tmp, rel_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(full_path, dest)

        diff_path = os.path.join(tmp, "preview.diff")
        # newline="" -- see _apply_and_verify_impl below; text-mode writes would
        # turn "\n" into "\r\n" and corrupt the patch against LF-only source.
        with open(diff_path, "w", encoding="utf-8", newline="") as f:
            f.write(diff_text if diff_text.endswith("\n") else diff_text + "\n")

        apply_cmd = (["git", "apply", "--whitespace=fix", diff_path]
                     if shutil.which("git") else ["patch", "-p1", "-i", diff_path])
        proc = subprocess.run(apply_cmd, cwd=tmp, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)
        if proc.returncode != 0:
            raise RuntimeError(f"diff did not apply cleanly:\n{proc.stdout}\n{proc.stderr}")

        with open(dest, encoding="utf-8") as f:
            modified = f.read()

    return {"path": rel_path, "original": original, "modified": modified}


def _fresh_sandbox(repo_root: str) -> str:
    """A sandbox nested inside repo_root/.code_debt/sandbox rather than a
    tempdir outside the project tree. Mirrors mcp_server/tools.py's
    _sandbox_root exactly (kept as a separate copy, not a shared import, to
    avoid agent/ -- the higher-level, Phase 5 package -- depending back on
    mcp_server/ -- Phase 4). This matters for re-verification specifically:
    some repos' pytest config (e.g. this project's own pytest.ini) is only
    discovered via pytest walking up from cwd to an ancestor directory,
    which only works if the sandbox stays inside the repo tree -- a tempdir
    under the OS temp root never finds it, and a real fix would wrongly
    come back "tests failed" for a reason that has nothing to do with the
    fix's content. Always wiped and recopied so a stale sandbox never
    carries over a previous attempt's half-applied patch."""
    sandbox = os.path.join(repo_root, ".code_debt", "sandbox")
    if os.path.exists(sandbox):
        shutil.rmtree(sandbox)
    shutil.copytree(repo_root, sandbox, ignore=_SANDBOX_IGNORE)
    return sandbox


def update_fix_from_edit(repo_root: str, existing_diff: str, edited_content: str,
                         test_command: Optional[list] = None) -> Dict:
    """Rebuilds a fix's diff from a human edit made to the "modified" side of
    the web UI's split editor (the LLM's suggestion, tweaked by hand), then
    re-verifies it exactly like a model-proposed fix -- a manual edit earns
    the same sandboxed proof before its status badge can claim "tests pass",
    no exceptions. Returns {"path", "diff", "applied", "tests_passed", "log"}.
    `existing_diff` is only consulted for its `--- a/<path>` header, to find
    which file the edit belongs to -- the diff body itself is discarded and
    rebuilt from scratch against edited_content."""
    match = _DIFF_PATH_RE.search(existing_diff)
    if not match:
        raise ValueError("diff has no '--- a/<path>' header")
    return create_fix_from_edit(repo_root, match.group(1), edited_content,
                                test_command=test_command)


def create_fix_from_edit(repo_root: str, rel_path: str, edited_content: str,
                         test_command: Optional[list] = None) -> Dict:
    """Builds and verifies a fix directly from a human edit of a file -- no
    pre-existing LLM diff required, which is what the web UI's editor tab
    needs for findings below the pipeline's --top-n cutoff. The diff is
    computed against the file as it exists on disk right now, then earns the
    same sandboxed apply-and-test proof as a model-proposed fix.
    Returns {"path", "diff", "applied", "tests_passed", "log"}; an edit
    identical to the on-disk file comes back with an empty diff."""
    full_path = os.path.realpath(os.path.join(repo_root, rel_path))
    if not full_path.startswith(os.path.realpath(repo_root) + os.sep):
        raise ValueError("path escapes repo root")
    if not os.path.isfile(full_path):
        raise ValueError(f"no such file: {rel_path}")
    with open(full_path, encoding="utf-8") as f:
        original = f.read()

    new_diff = build_unified_diff(original, edited_content, rel_path)
    if not new_diff.strip():
        return {"path": rel_path, "diff": "", "applied": False, "tests_passed": None,
                "log": "Edited content is identical to the original file -- nothing to verify."}

    verified = apply_and_verify(repo_root, new_diff, test_command=test_command,
                                sandbox_root=_fresh_sandbox(repo_root))
    return {"path": rel_path, "diff": new_diff, **verified}


def apply_and_verify(repo_root: str, diff_text: str, test_command: Optional[list] = None,
                     sandbox_root: Optional[str] = None) -> Dict:
    """Copies repo_root to a tmp dir, applies diff_text there with `git apply`
    (falls back to `patch` if git isn't available), and runs tests.
    Returns {"applied": bool, "tests_passed": bool | None, "log": str}.
    Never mutates repo_root.

    Both subprocess calls below pin stdin=DEVNULL deliberately: when this
    runs as one of the MCP tools (mcp_server/server.py, stdio transport),
    this whole process's own stdin is a pipe carrying the JSON-RPC protocol
    from the orchestrator. Left unredirected, a nested subprocess inherits
    that same pipe and can block reading from it -- a real deadlock we hit
    (git/pytest waiting on stdin the orchestrator won't write to until it
    gets this tool's response, which won't come until the nested process
    stops waiting). DEVNULL avoids the whole class of failure, on both
    transports."""
    if sandbox_root is None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = os.path.join(tmp, "repo")
            shutil.copytree(repo_root, sandbox, ignore=_SANDBOX_IGNORE)
            return _apply_and_verify_impl(repo_root, diff_text, test_command, sandbox)
    sandbox = sandbox_root
    if not os.path.exists(sandbox):
        shutil.copytree(repo_root, sandbox, ignore=_SANDBOX_IGNORE)
    return _apply_and_verify_impl(repo_root, diff_text, test_command, sandbox)


def _apply_and_verify_impl(repo_root: str, diff_text: str, test_command: Optional[list], sandbox: str) -> Dict:
    result = {"applied": False, "tests_passed": None, "log": ""}

    diff_path = os.path.join(sandbox, "fix.diff")
    # newline="" is required on Windows: the default text-mode write translates
    # every "\n" in diff_text to "\r\n", corrupting the diff against LF-only
    # source files (git apply then rejects every context line -- confirmed via
    # a raw byte dump showing "\r\n" on disk despite diff_text containing only
    # "\n"). This bug predates and is independent of the diff-generation
    # changes elsewhere in this file.
    with open(diff_path, "w", encoding="utf-8", newline="") as f:
        f.write(diff_text if diff_text.endswith("\n") else diff_text + "\n")

    apply_cmd = ["git", "apply", "--reject", "--whitespace=fix", diff_path] \
        if shutil.which("git") else ["patch", "-p1", "-i", diff_path]

    proc = subprocess.run(apply_cmd, cwd=sandbox, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)
    result["log"] += f"$ {' '.join(apply_cmd)}\n{proc.stdout}\n{proc.stderr}\n"
    if proc.returncode != 0:
        result["applied"] = False
        return result
    result["applied"] = True

    python_files = [os.path.join(sandbox, f) for f in os.listdir(sandbox) if f.endswith(".py")]
    for root, _, files in os.walk(sandbox):
        for name in files:
            if name.endswith(".py"):
                python_files.append(os.path.join(root, name))

    for py_file in python_files:
        try:
            with open(py_file, "r", encoding="utf-8") as handle:
                compile(handle.read(), py_file, "exec")
        except SyntaxError as exc:
            result["tests_passed"] = False
            result["log"] += f"\nSyntax check failed for {os.path.relpath(py_file, sandbox)}: {exc}"
            return result

    cmd = test_command or _detect_test_command(sandbox)
    if cmd is None:
        result["tests_passed"] = None
        result["log"] += "\nNo test runner detected (no pytest/pyproject or package.json test script)."
        return result

    test_proc = subprocess.run(cmd, cwd=sandbox, capture_output=True, text=True, timeout=300,
                               stdin=subprocess.DEVNULL)
    result["log"] += f"\n$ {' '.join(cmd)}\n{test_proc.stdout}\n{test_proc.stderr}"
    result["tests_passed"] = test_proc.returncode == 0
    return result


def _detect_test_command(sandbox: str):
    tests_dir = os.path.join(sandbox, "tests")
    has_marker = (
        os.path.exists(os.path.join(sandbox, "pytest.ini"))
        or os.path.exists(os.path.join(sandbox, "pyproject.toml"))
        or any(f.startswith("test_") for f in os.listdir(sandbox) if f.endswith(".py"))
        # every fixture repo in this project (eval/sample_repo, addition/, ...) puts
        # tests in a tests/ subdirectory -- the checks above only look at the sandbox
        # root, so without this a real test suite goes undetected and tests_passed
        # silently stays None forever, regardless of whether the fix is actually right.
        or (os.path.isdir(tests_dir) and any(
            f.startswith("test_") and f.endswith(".py") for f in os.listdir(tests_dir)
        ))
    )
    if has_marker and shutil.which("pytest"):
        return ["pytest", "-q"]
    if os.path.exists(os.path.join(sandbox, "package.json")):
        if shutil.which("npm"):
            return ["npm", "test", "--silent"]
    return None
