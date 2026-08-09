"""
agent/orchestrator.py

Phase 5: the agentic loop. An LLM (see agent/llm_client.py; Mistral's hosted
models by default) is given 3 of the 6 MCP tools (schemas from
mcp_server/tools.py) -- search_codebase / propose_fix / run_tests -- and,
for each top-ranked finding, is free to call them in whatever order it
wants, self-verifying its own fix before moving on, until it either
confirms a passing fix or gives up and reports why.

The other 3 tools (read_finding, read_file_snippet, get_standards) are
deterministic given the finding -- there's no judgment call in fetching
them, so making the model spend a separate LLM turn on each was pure
round-trip overhead. _build_context_message() below fetches them once,
up front, and inlines them into the initial user message instead (still
exposed as real MCP tools on the server for protocol compatibility /
external clients, just not offered to this loop's model).

Two tool-execution transports, selected by `run(..., transport=...)`
(`python main.py run --transport {in-process,mcp}`):

  in-process (default) -- _execute_tool() dispatches directly into
    mcp_server/tools.py's plain functions. No subprocess, no protocol.
  mcp -- spawns `python -m mcp_server.server --repo-root <repo>` and
    drives the same 6 tools over a real MCP stdio session via the
    official `mcp` SDK client (_resolve_finding_mcp / _run_mcp_session).

The model side is identical either way: same TOOL_SCHEMAS, same
MAX_TOOL_TURNS budget, same system prompt. Only how a chosen tool call is
executed differs. MCP session setup (spawn + initialize + tool-schema
sanity check) is wrapped in a try/except; any failure there falls the
*whole run* back to in-process (session-level fallback, not per-call --
simpler and more honest than pretending per-call fallback is free) and
prints a one-line explanation of which transport actually served the run.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Dict, List, Optional

from analyzers.base import Finding, write_findings
from analyzers.scan import scan, _walk_files, PY_EXTS
from agent.scoring import score_findings, ScoredFinding
from agent import llm_client
from agent import roadmap as roadmap_mod
from agent import planner
from mcp_server import tools as mcp_tools

# was 8, then 5; now that the finding/snippet/standards are pre-loaded into the first message
# (see _build_context_message) instead of costing their own discovery turns, propose_fix -> run_tests
# -> summary rarely needs more than 3-4 turns even with one failed-test retry. Override per-run with
# the MAX_TOOL_TURNS env var.
MAX_TOOL_TURNS = int(os.environ.get("MAX_TOOL_TURNS", "4"))
MAX_TOOL_RETRIES = 3  # the model occasionally emits a malformed tool call; resample before giving up

# The only tools actually offered to the model in this loop -- read_finding, read_file_snippet, and
# get_standards are deliberately left out here since _build_context_message() already inlines their
# results into the first message (see module docstring).
AGENT_TOOL_NAMES = {"search_codebase", "propose_fix", "run_tests"}

AGENT_SYSTEM_PROMPT = """You are an autonomous refactoring agent. You've been given one technical-debt
finding to resolve, along with its code snippet and applicable coding standards already inlined below
-- you don't need to fetch them yourself. You have tools to search the codebase for related usages,
propose a fix, and run the test suite against that fix in a sandbox.

Always call `propose_fix` before `run_tests`, and always call `run_tests` to self-verify before
concluding. run_tests takes the same finding_id you already have -- it automatically applies
whatever you most recently proposed for that finding; you never need to pass diff text yourself.
If tests fail, you may call `propose_fix` again with what you learned (mention the failure in your
next message) up to a couple of times.
When you're done, reply with a final plain-text summary (no more tool calls) starting with either
"RESOLVED:" or "UNRESOLVED:" followed by one sentence explaining the outcome."""


def _build_context_message(repo_root: str, finding: Finding) -> str:
    """Pre-fetches what read_finding/read_file_snippet/get_standards would otherwise cost up to
    3 separate LLM turns to retrieve one at a time. All three are fully deterministic given the
    finding (the snippet's range and the standards lookup are keyed only on fields already on
    `finding`), so inlining them here skips no judgment call -- the model sees the exact same
    information, just without paying a round-trip for it."""
    try:
        snippet = mcp_tools.read_file_snippet(repo_root, finding.file, finding.line_start, finding.line_end)
    except Exception as e:  # noqa: BLE001 -- surface as text rather than aborting the finding
        snippet = f"(could not read snippet: {e})"
    try:
        standards = mcp_tools.get_standards(finding.type)
    except Exception as e:  # noqa: BLE001
        standards = f"(could not retrieve standards: {e})"
    return (
        f"Resolve this finding: {json.dumps(finding.to_dict())}\n\n"
        f"--- Code snippet ({finding.file}:{finding.line_start}-{finding.line_end}) ---\n"
        f"{snippet}\n\n"
        f"--- Coding standards for '{finding.type}' ---\n"
        f"{standards}"
    )


def _execute_tool(repo_root: str, findings_path: str, name: str, tool_input: Dict):
    if name == "read_finding":
        return mcp_tools.read_finding(findings_path, tool_input["finding_id"])
    if name == "read_file_snippet":
        return mcp_tools.read_file_snippet(
            repo_root, tool_input["rel_path"], tool_input["line_start"], tool_input["line_end"]
        )
    if name == "get_standards":
        return mcp_tools.get_standards(tool_input["finding_type"])
    if name == "search_codebase":
        return mcp_tools.search_codebase(repo_root, tool_input["pattern"])
    if name == "propose_fix":
        return mcp_tools.propose_fix(repo_root, findings_path, tool_input["finding_id"])
    if name == "run_tests":
        return mcp_tools.run_tests(repo_root, tool_input["finding_id"])
    raise ValueError(f"Unknown tool: {name}")


def _record_fix_result(last_fix_result: Dict, name: str, result) -> None:
    if name == "propose_fix":
        last_fix_result["diff"] = result.get("diff")
    if name == "run_tests":
        last_fix_result["applied"] = result.get("applied", False)
        last_fix_result["tests_passed"] = result.get("tests_passed")


def resolve_finding(repo_root: str, findings_path: str, sf: ScoredFinding,
                     latencies: Optional[Dict[str, List[float]]] = None,
                     system_prompt: str = AGENT_SYSTEM_PROMPT,
                     retry_note: Optional[str] = None,
                     model: Optional[str] = None) -> Dict:
    """Drives one finding through the agent loop (in-process transport).
    Returns a fix-result dict suitable for agent/roadmap.py, e.g.
    {"applied": True, "tests_passed": True, "diff": "..."}.
    Raises llm_client.RateLimitExhausted if the provider's rate limit is hit --
    callers should stop attempting further findings rather than catch-and-continue,
    since a hard quota won't clear itself between findings.

    `latencies`, if given, accumulates wall-clock seconds per tool name plus
    a "_resolve_finding_total" key -- passed in by run() so timings share
    one dict across every finding in a run (see Task 1e instrumentation).

    `system_prompt` selects the agent persona: the default generalist prompt
    (strategy="single") or a specialist's role prompt (strategy="multi", see
    agent/specialists.py). The tool loop itself is identical either way -- only
    the model's framing of what a good fix is changes.

    `retry_note`, if given, is appended as an extra user message before the
    tool loop starts -- this is how the ONE reviewer-triggered retry (see
    _resolve_multi_agent/_run_mcp_session's MAX_REVIEW_RETRIES handling) feeds
    the ReviewerAgent's rationale back to the SAME specialist, closing the
    proposer-critic loop without adding a second review call."""
    if latencies is None:
        latencies = {}
    tools = llm_client.to_openai_tools([t for t in mcp_tools.TOOL_SCHEMAS if t["name"] in AGENT_TOOL_NAMES])

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _build_context_message(repo_root, sf.finding)},
    ]
    if retry_note:
        messages.append({"role": "user", "content": retry_note})
    last_fix_result: Dict = {"applied": False, "tests_passed": None, "diff": None, "error": None}

    turn_start = time.monotonic()
    for _ in range(MAX_TOOL_TURNS):
        resp, last_err = None, None
        for _attempt in range(MAX_TOOL_RETRIES):
            try:
                resp = llm_client.create_chat_completion(
                    model=model or llm_client.ORCH_MODEL,
                    max_tokens=2000,
                    messages=messages,
                    tools=tools,
                )
                break
            except llm_client.RateLimitExhausted:
                raise  # retrying burns another request against the same limit; stop now
            except Exception as e:  # noqa: BLE001 -- resample rather than give up on the first
                last_err = e  # malformed generation; if it keeps failing, surface it and stop
        if resp is None:
            last_fix_result["error"] = str(last_err)
            break
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            break  # model produced its final RESOLVED/UNRESOLVED summary

        for call in msg.tool_calls:
            try:
                tool_input = json.loads(call.function.arguments or "{}")
                t0 = time.monotonic()
                result = _execute_tool(repo_root, findings_path, call.function.name, tool_input)
                latencies.setdefault(call.function.name, []).append(time.monotonic() - t0)
                _record_fix_result(last_fix_result, call.function.name, result)
                content = json.dumps(result) if not isinstance(result, str) else result
            except llm_client.RateLimitExhausted:
                raise  # propose_fix hit the limit internally -- stop, don't feed back to the model
            except Exception as e:  # noqa: BLE001 -- surface the error to the model, don't crash the loop
                content = json.dumps({"error": str(e)})
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": content,
            })

    latencies.setdefault("_resolve_finding_total", []).append(time.monotonic() - turn_start)
    return last_fix_result


def _resolve_in_process(repo_root: str, findings_path: str, scored: List[ScoredFinding],
                         top_n: int) -> "tuple[Dict[str, Dict], Dict[str, List[float]]]":
    """Resolve top_n findings via in-process dispatch, sharing one
    latencies dict across all of them (Task 1e instrumentation)."""
    fixes: Dict[str, Dict] = {}
    latencies: Dict[str, List[float]] = {}
    for sf in scored[:top_n]:
        try:
            fixes[sf.finding.id] = resolve_finding(repo_root, findings_path, sf, latencies)
        except llm_client.RateLimitExhausted as e:
            # every remaining finding would fail identically -- stop burning requests
            fixes[sf.finding.id] = {
                "applied": False, "tests_passed": None, "diff": None,
                "error": f"rate limit exhausted, stopping further fix attempts: {e}",
            }
            break
        except Exception as e:  # noqa: BLE001 -- one finding's agent loop failing
            # shouldn't lose the roadmap for every other finding
            fixes[sf.finding.id] = {
                "applied": False, "tests_passed": None, "diff": None, "error": str(e),
            }
    return fixes, latencies


# A "reject" or "revise" verdict gets exactly ONE re-attempt, never a loop --
# see _needs_retry/_merge_retry below. Bumping this constant would require
# also turning the single `if _needs_retry(...)` blocks in _resolve_multi_agent
# and _run_mcp_session into loops; it is not itself a loop bound today.
MAX_REVIEW_RETRIES = 1


def _needs_retry(verdict: Optional[Dict]) -> bool:
    """A reject or revise verdict earns the finding its one retry; approve
    (or no verdict at all -- no diff was produced) does not."""
    return bool(verdict) and verdict.get("verdict") in ("reject", "revise")


def _retry_prompt(verdict: Dict) -> str:
    """Turns the ReviewerAgent's verdict into feedback for the SAME specialist's
    one allowed retry -- this is what actually closes the proposer-critic loop.
    The retry is deliberately never re-reviewed (that would be a second LLM
    call per retry, doubling the cost this is supposed to stay cheap about)."""
    return (
        f"An independent reviewer looked at your proposed fix and returned verdict "
        f"'{verdict.get('verdict')}': {verdict.get('rationale', '')}\n"
        "Address that specific issue. Call propose_fix again with a corrected edit, "
        "then run_tests to verify, before giving your final RESOLVED/UNRESOLVED summary."
    )


def _use_retry(original: Dict, verdict_str: str, retry: Dict) -> bool:
    """True if the retry should replace the original.

    Only ever True when the retry's tests actually pass -- an unverified or
    still-failing retry never replaces anything, which is what guarantees the
    merge never ends up worse than the original alone would have been (an
    "applied but failing" retry does NOT get to outrank a "rejected" original
    just because reject sounds worse than a raw test failure).

    Given a passing retry, swapping is justified either because:
      - the original's tests didn't pass at all (a plain improvement), or
      - the reviewer said "reject" on the original even though ITS tests
        happened to pass -- reviewer.py's own documented blind spot (tests can
        pass on a change that doesn't truly fix the finding). There, the
        retry's passing tests are the only signal left to trust, since the
        retry is never independently re-reviewed."""
    if not retry.get("tests_passed"):
        return False
    return not original.get("tests_passed") or verdict_str == "reject"


def _retry_note(verdict: str, used_retry: bool, kept: Dict) -> str:
    """One-line note for agent/roadmap.py explaining what the retry did --
    e.g. 'reviewer requested revision; re-attempted 1x -- retry passed,
    using the retry'."""
    action = "requested revision" if verdict == "revise" else "rejected the fix"
    if used_retry:
        if kept.get("tests_passed"):
            outcome = "passed"
        elif kept.get("applied"):
            outcome = "applied, tests still failing"
        else:
            outcome = "did not apply"
        return f"reviewer {action}; re-attempted 1x -- retry {outcome}, using the retry"
    outcome = "still rejected" if verdict == "reject" else "no improvement over the original"
    return f"reviewer {action}; re-attempted 1x -- {outcome}, keeping the original"


def _merge_retry(original: Dict, verdict: Dict, retry: Dict) -> Dict:
    """Picks the better of `original` and its one retry (see _use_retry) and
    tags the result with the retry outcome for the roadmap. Never returns
    something worse than `original` alone would have been -- see _use_retry's
    docstring for why the swap is gated on the retry actually passing tests."""
    verdict_str = verdict.get("verdict")
    use_retry = _use_retry(original, verdict_str, retry)
    kept = retry if use_retry else original
    kept["review"] = verdict  # the record of WHY a retry happened stays the original verdict --
                              # the retry itself was never independently reviewed
    kept["retry_used"] = use_retry
    kept["retry"] = _retry_note(verdict_str, use_retry, kept)
    return kept


def _resolve_multi_agent(repo_root: str, findings_path: str, scored: List[ScoredFinding],
                          top_n: int) -> "tuple[Dict[str, Dict], Dict[str, List[float]]]":
    """Multi-agent coordinator (in-process transport). Routes each finding to
    the specialist that owns its type (agent/specialists.py) and drives it
    through the shared resolve_finding engine under that specialist's role
    prompt. Tags every result with which agent handled it and why it was
    routed there, so the roadmap can explain the decision -- the same shape as
    _resolve_in_process otherwise, including the shared latencies dict and the
    RateLimitExhausted hard-stop. After each specialist finishes, the
    independent ReviewerAgent (agent/reviewer.py) judges the proposed fix and
    its verdict is attached to the result -- but only for specialists whose
    fixes change behaviour (Specialist.reviews_fixes); a documentation fix is
    marked review-skipped without spending a call.

    A "reject" or "revise" verdict triggers exactly ONE retry (MAX_REVIEW_RETRIES),
    feeding the reviewer's rationale back to the same specialist (_retry_prompt);
    the retry replaces the original only if its tests actually pass
    (_merge_retry/_use_retry), and it is never itself reviewed again, so the
    whole retry costs at most one extra propose_fix/run_tests tool loop -- zero
    extra review calls, zero extra calls for an "approve" verdict."""
    from agent import specialists, reviewer

    fixes: Dict[str, Dict] = {}
    latencies: Dict[str, List[float]] = {}
    lessons_by_specialist: Dict[str, List[str]] = {}
    plan = planner.plan_findings([sf.finding for sf in scored[:top_n]])
    ordered_ids = plan.get("ordered_ids", [sf.finding.id for sf in scored[:top_n]])
    ordered = [sf for sf in scored[:top_n] if sf.finding.id in ordered_ids]
    ordered.sort(key=lambda sf: ordered_ids.index(sf.finding.id))
    for index, sf in enumerate(ordered):
        spec, reason = specialists.route(sf.finding.type)
        lesson_note = ""
        if spec.name in lessons_by_specialist and lessons_by_specialist[spec.name]:
            recent = lessons_by_specialist[spec.name][-3:]
            lesson_note = "Recent lessons for this specialist:\n- " + "\n- ".join(recent)
        system_prompt = spec.system_prompt
        if lesson_note:
            system_prompt = f"{lesson_note}\n\n{spec.system_prompt}"
        try:
            result = resolve_finding(repo_root, findings_path, sf, latencies,
                                     system_prompt=system_prompt)
        except llm_client.RateLimitExhausted as e:
            # every remaining finding would fail identically -- stop burning requests
            fixes[sf.finding.id] = {
                "applied": False, "tests_passed": None, "diff": None,
                "agent": spec.name, "routing_reason": reason,
                "error": f"rate limit exhausted, stopping further fix attempts: {e}",
            }
            break
        except Exception as e:  # noqa: BLE001 -- one finding's agent loop failing
            # shouldn't lose the roadmap for every other finding
            fixes[sf.finding.id] = {
                "applied": False, "tests_passed": None, "diff": None,
                "agent": spec.name, "routing_reason": reason, "error": str(e),
            }
            continue
        result["agent"] = spec.name
        result["routing_reason"] = reason
        result["planner_order"] = index + 1
        result["planner_group"] = None
        verdict = None
        if spec.reviews_fixes:
            try:
                verdict = reviewer.review(sf.finding, result)
                if verdict:
                    result["review"] = verdict
            except llm_client.RateLimitExhausted as e:
                result["review"] = {"verdict": "skipped",
                                    "rationale": f"rate limit exhausted before review: {e}"}
                fixes[sf.finding.id] = result
                break

            if _needs_retry(verdict):
                # Same rate-limit discipline as every other LLM call in this loop:
                # a 429 on the retry hard-stops the whole run rather than thrashing.
                retry_system_prompt = spec.system_prompt
                if verdict.get("verdict") == "reject" and spec.name != "RefactoringAgent":
                    retry_system_prompt = specialists.DEFAULT_SPECIALIST.system_prompt
                try:
                    retry_result = resolve_finding(repo_root, findings_path, sf, latencies,
                                                    system_prompt=retry_system_prompt,
                                                    retry_note=_retry_prompt(verdict),
                                                    model=llm_client.SCORING_MODEL)
                except llm_client.RateLimitExhausted as e:
                    result["retry"] = (f"reviewer verdict '{verdict.get('verdict')}'; "
                                       f"retry aborted -- rate limit exhausted: {e}")
                    fixes[sf.finding.id] = result
                    break
                retry_result["agent"] = spec.name
                retry_result["routing_reason"] = reason
                result = _merge_retry(result, verdict, retry_result)
        if verdict and verdict.get("verdict") == "reject":
            lessons_by_specialist.setdefault(spec.name, []).append(
                f"{spec.name} rejected fix for {sf.finding.type}: {verdict.get('rationale', '')}"
            )
        if not spec.reviews_fixes:
            result["review"] = {"verdict": "skipped",
                                "rationale": f"{spec.name} fix changes no behaviour; "
                                             "independent review skipped to save an LLM call"}
        fixes[sf.finding.id] = result
    return fixes, latencies


# ---------------------------------------------------------------------
# MCP stdio transport (Task 1: python main.py run --transport mcp)
# ---------------------------------------------------------------------

def _normalize_mcp_content(result) -> str:
    """Make an MCP CallToolResult read exactly like what the in-process
    path hands the model. _execute_tool's callers do
    `json.dumps(result) if not isinstance(result, str) else result` --
    match that shape here too so the model sees equivalent tool-result
    text regardless of transport (a fair comparison for Task 1e, and
    required for _record_fix_result to parse propose_fix/run_tests output).

    FastMCP quirk this specifically works around: a tool that returns a
    Python `list` (e.g. search_codebase) comes back as one TextContent
    block *per list item*, not one block containing a JSON array -- so
    multi-block responses are reassembled into a single list here."""
    if result.isError:
        message = " ".join(getattr(b, "text", "") for b in result.content)
        return json.dumps({"error": message})

    blocks = [getattr(b, "text", "") for b in result.content]
    if not blocks:
        return "[]"  # only search_codebase can plausibly return an empty collection
    if len(blocks) == 1:
        try:
            parsed = json.loads(blocks[0])
        except (json.JSONDecodeError, ValueError):
            return blocks[0]  # a bare string result (e.g. read_file_snippet, get_standards)
        return json.dumps(parsed)
    return json.dumps([json.loads(b) for b in blocks])  # reassembled list-of-dicts


TOOL_CALL_TIMEOUT_SECONDS = 320  # a bit above run_tests' own internal 300s pytest timeout


async def _call_tool_mcp(session, name: str, tool_input: Dict, latencies: Dict[str, List[float]]) -> str:
    """A hung tool call (e.g. the stdin-inheritance deadlock in nested
    subprocesses -- see agent/fixgen.py's apply_and_verify docstring) would
    otherwise freeze the whole run forever with no signal. Bound every call
    so a hang surfaces as a clear, catchable error instead."""
    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(session.call_tool(name, tool_input), timeout=TOOL_CALL_TIMEOUT_SECONDS)
    finally:
        latencies.setdefault(name, []).append(time.monotonic() - t0)
    return _normalize_mcp_content(result)


async def _resolve_finding_mcp(session, repo_root: str, sf: ScoredFinding, latencies: Dict[str, List[float]],
                                system_prompt: str = AGENT_SYSTEM_PROMPT,
                                retry_note: Optional[str] = None,
                                model: Optional[str] = None) -> Dict:
    """Same control loop as resolve_finding(), but every tool call crosses
    the MCP stdio boundary via `session` instead of an in-process dispatch.
    The LLM call is still a blocking HTTP request, so it's run in a thread
    (asyncio.to_thread) rather than stalling the event loop.

    `system_prompt` selects the generalist or a specialist persona, exactly as
    in the in-process resolve_finding() -- multi-agent routing works over the
    real MCP transport too.

    `retry_note`: same reviewer-feedback-as-extra-message mechanism as
    resolve_finding()'s -- the one capped retry works identically on both
    transports."""
    tools = llm_client.to_openai_tools([t for t in mcp_tools.TOOL_SCHEMAS if t["name"] in AGENT_TOOL_NAMES])

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _build_context_message(repo_root, sf.finding)},
    ]
    if retry_note:
        messages.append({"role": "user", "content": retry_note})
    last_fix_result: Dict = {"applied": False, "tests_passed": None, "diff": None, "error": None}

    turn_start = time.monotonic()
    for _ in range(MAX_TOOL_TURNS):
        resp, last_err = None, None
        for _attempt in range(MAX_TOOL_RETRIES):
            try:
                resp = await asyncio.to_thread(
                    llm_client.create_chat_completion,
                    model=model or llm_client.ORCH_MODEL,
                    max_tokens=2000,
                    messages=messages,
                    tools=tools,
                )
                break
            except llm_client.RateLimitExhausted:
                raise
            except Exception as e:  # noqa: BLE001 -- resample rather than give up on the first
                last_err = e
        if resp is None:
            last_fix_result["error"] = str(last_err)
            break
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            break  # model produced its final RESOLVED/UNRESOLVED summary

        for call in msg.tool_calls:
            try:
                tool_input = json.loads(call.function.arguments or "{}")
                content = await _call_tool_mcp(session, call.function.name, tool_input, latencies)
                try:
                    parsed = json.loads(content)
                except (json.JSONDecodeError, ValueError):
                    parsed = None
                _record_fix_result(last_fix_result, call.function.name,
                                    parsed if isinstance(parsed, dict) else {})
            except llm_client.RateLimitExhausted:
                raise  # propose_fix hit the limit server-side -- stop, don't feed back to the model
            except Exception as e:  # noqa: BLE001 -- surface the error to the model, don't crash the loop
                content = json.dumps({"error": str(e)})
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": content,
            })

    latencies.setdefault("_resolve_finding_total", []).append(time.monotonic() - turn_start)
    return last_fix_result


async def _run_mcp_session(repo_root: str, scored: List[ScoredFinding],
                            top_n: int, strategy: str = "multi",
                            ) -> "tuple[Dict[str, Dict], Dict[str, List[float]]]":
    """Spawns `python -m mcp_server.server --repo-root <repo>` and resolves
    top_n findings over a single MCP stdio session. Session setup (spawn,
    initialize, tool-schema sanity check) is *not* caught here -- a failure
    there is meant to propagate so the caller can fall the whole run back
    to in-process. Failures resolving an individual finding once the
    session is up ARE caught per-finding, same as _resolve_in_process.

    `strategy`: "multi" routes each finding to its specialist (agent/
    specialists.py) and tags the result with the handling agent; "single"
    uses the generalist prompt for every finding."""
    from mcp import ClientSession, StdioServerParameters
    from agent import specialists, reviewer
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server", "--repo-root", str(repo_root)],
        # StdioServerParameters defaults to a minimal environment (PATH, TEMP,
        # etc.) that deliberately excludes everything else -- without this,
        # the server's own propose_fix (it calls the LLM too, server-side)
        # fails every time with "no LLM_API_KEY/MISTRAL_API_KEY set", key present or not.
        env=dict(os.environ),
    )

    fixes: Dict[str, Dict] = {}
    latencies: Dict[str, List[float]] = {}
    plan = planner.plan_findings([sf.finding for sf in scored[:top_n]])
    ordered_ids = plan.get("ordered_ids", [sf.finding.id for sf in scored[:top_n]])
    ordered = [sf for sf in scored[:top_n] if sf.finding.id in ordered_ids]
    ordered.sort(key=lambda sf: ordered_ids.index(sf.finding.id))

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_tools()
            got = {t.name for t in listed.tools}
            expected = {t["name"] for t in mcp_tools.TOOL_SCHEMAS}
            if got != expected:
                raise RuntimeError(f"MCP server tool mismatch: expected {sorted(expected)}, got {sorted(got)}")

            for index, sf in enumerate(ordered):
                if strategy == "multi":
                    spec, reason = specialists.route(sf.finding.type)
                    prompt, agent_name = spec.system_prompt, spec.name
                    review_this, spec_name = spec.reviews_fixes, spec.name
                else:
                    prompt, agent_name, reason = AGENT_SYSTEM_PROMPT, None, None
                    review_this, spec_name = False, None
                try:
                    result = await _resolve_finding_mcp(session, repo_root, sf, latencies, system_prompt=prompt)
                except llm_client.RateLimitExhausted as e:
                    fixes[sf.finding.id] = {
                        "applied": False, "tests_passed": None, "diff": None,
                        "agent": agent_name, "routing_reason": reason,
                        "error": f"rate limit exhausted, stopping further fix attempts: {e}",
                    }
                    break
                except Exception as e:  # noqa: BLE001 -- one finding's agent loop failing
                    fixes[sf.finding.id] = {
                        "applied": False, "tests_passed": None, "diff": None,
                        "agent": agent_name, "routing_reason": reason, "error": str(e),
                    }
                    continue
                if agent_name:
                    result["agent"] = agent_name
                    result["routing_reason"] = reason
                    result["planner_order"] = index + 1
                    result["planner_group"] = None
                    if review_this:
                        try:
                            verdict = await asyncio.to_thread(reviewer.review, sf.finding, result)
                            if verdict:
                                result["review"] = verdict
                        except llm_client.RateLimitExhausted as e:
                            result["review"] = {"verdict": "skipped",
                                                "rationale": f"rate limit exhausted before review: {e}"}
                            fixes[sf.finding.id] = result
                            break

                        if _needs_retry(verdict):
                            # Same rate-limit discipline as the initial resolve above:
                            # a 429 on the retry hard-stops the run, it doesn't thrash.
                            try:
                                retry_result = await _resolve_finding_mcp(
                                    session, repo_root, sf, latencies, system_prompt=prompt,
                                    retry_note=_retry_prompt(verdict),
                                )
                            except llm_client.RateLimitExhausted as e:
                                result["retry"] = (f"reviewer verdict '{verdict.get('verdict')}'; "
                                                   f"retry aborted -- rate limit exhausted: {e}")
                                fixes[sf.finding.id] = result
                                break
                            retry_result["agent"] = agent_name
                            retry_result["routing_reason"] = reason
                            result = _merge_retry(result, verdict, retry_result)
                    else:
                        result["review"] = {"verdict": "skipped",
                                            "rationale": f"{spec_name} fix changes no behaviour; "
                                                         "independent review skipped to save an LLM call"}
                fixes[sf.finding.id] = result

    return fixes, latencies


def _print_latency_summary(transport: str, latencies: Dict[str, List[float]]) -> None:
    totals = latencies.get("_resolve_finding_total")
    if totals:
        mean = sum(totals) / len(totals)
        print(f"[transport] {transport}: {len(totals)} finding(s) resolved, "
              f"mean resolve_finding latency {mean:.2f}s")
    for name in sorted(k for k in latencies if k != "_resolve_finding_total"):
        times = latencies[name]
        print(f"[transport] {transport}: {name} called {len(times)}x, "
              f"mean {sum(times) / len(times):.3f}s")


def _resolve_top_findings(repo_root: str, findings_path: str, scored: List[ScoredFinding],
                           top_n: int, transport: str, strategy: str = "multi") -> Dict[str, Dict]:
    """Drives fix resolution for the top_n findings via the requested
    transport, with a session-level fallback to in-process if the MCP
    transport can't even get a session up (see _run_mcp_session's
    docstring for what "session-level" means here).

    `strategy`: "multi" (default) routes each finding to a specialist agent
    (agent/specialists.py); "single" uses the original generalist loop for
    every finding. Both transports honour it."""
    fixes: Dict[str, Dict] = {}
    latencies: Dict[str, List[float]] = {}
    active = "in-process"

    print(f"[strategy] {strategy}-agent fix resolution")

    if transport == "mcp":
        try:
            fixes, latencies = asyncio.run(_run_mcp_session(repo_root, scored, top_n, strategy))
            active = "mcp"
            print(f"[transport] MCP stdio session active ({len(mcp_tools.TOOL_SCHEMAS)} tools)")
        except Exception as e:  # noqa: BLE001 -- session-level fallback, not per-call
            print(f"[transport] MCP unavailable ({e}), falling back to in-process dispatch")

    if active == "in-process":
        if strategy == "multi":
            fixes, latencies = _resolve_multi_agent(repo_root, findings_path, scored, top_n)
        else:
            fixes, latencies = _resolve_in_process(repo_root, findings_path, scored, top_n)
        print("[transport] in-process dispatch active")

    _print_latency_summary(active, latencies)
    return fixes


def run(repo_root: str, out_path: str = "roadmap.md", top_n: int = 10,
        attempt_fixes: bool = True, transport: str = "in-process",
        strategy: str = "multi") -> str:
    """Full agentic pass: scan -> score -> (optionally) resolve top_n findings
    -> emit roadmap. Returns the roadmap markdown (also written to out_path).
    `transport`: "in-process" (default) or "mcp" -- see module docstring.
    `strategy`: "multi" (default) routes findings to specialist agents;
    "single" uses the original generalist agent loop."""
    repo_root = os.path.abspath(repo_root)
    findings = scan(repo_root)

    debt_dir = os.path.join(repo_root, ".code_debt")
    os.makedirs(debt_dir, exist_ok=True)
    findings_path = os.path.join(debt_dir, "findings.json")
    write_findings(findings, findings_path)

    py_files = _walk_files(repo_root, PY_EXTS)
    scored = score_findings(findings, repo_root=repo_root, py_files=py_files)

    fixes: Dict[str, Dict] = {}
    if attempt_fixes and llm_client.have_key():
        fixes = _resolve_top_findings(repo_root, findings_path, scored, top_n, transport, strategy)

    with open(os.path.join(debt_dir, "scored.json"), "w", encoding="utf-8") as f:
        json.dump([sf.to_dict() for sf in scored], f, indent=2)
    with open(os.path.join(debt_dir, "fixes.json"), "w", encoding="utf-8") as f:
        json.dump(fixes, f, indent=2)

    md = roadmap_mod.generate_markdown(scored, fixes, repo_name=os.path.basename(repo_root))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    return md
