"""
agent/specialists.py

The multi-agent layer. Instead of one generalist agent resolving every kind
of finding, each finding is ROUTED to a specialist agent whose role prompt is
tuned to its kind of debt:

  RefactoringAgent   -- structural debt (long functions, high complexity,
                        duplication, long parameter lists, dead code, magic
                        numbers, unused imports/variables). Behaviour-preserving
                        code changes.
  DocumentationAgent -- missing/inadequate documentation. Adds docstrings;
                        does NOT change executable code.

Specialists share the SAME tool-use engine (agent/orchestrator.resolve_finding
and its MCP twin); they differ only in their system prompt and the finding
types they own. This keeps the already-verified single-agent loop as the
substrate and makes "multi-agent" a routing + prompt-specialization layer on
top of it, not a parallel rewrite. The coordinator records which specialist
handled each finding and why it was chosen, so agent/roadmap.py can explain
not just *what* changed but *who* decided it and *why they were picked* -- the
"explainable" half of the system.

Adding a specialist is a two-line change: define its prompt + Specialist and
add it to SPECIALISTS. Routing falls back to DEFAULT_SPECIALIST for any finding
type without a dedicated owner, so a new analyzer never goes unhandled.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Set, Tuple

# Shared tool-protocol contract every specialist must obey. The individual
# role prompts below prepend their specialty framing to this so the tool loop
# (propose_fix -> run_tests -> RESOLVED/UNRESOLVED) behaves identically across
# agents -- only the *judgement* about what a good fix is differs.
_TOOL_PROTOCOL = """
The finding, its code snippet, and applicable coding standards are already inlined above -- you
don't need to fetch them yourself. You have tools to search the codebase for related usages,
propose a fix, and run the test suite against that fix in a sandbox.

Always call `propose_fix` before `run_tests`, and always call `run_tests` to self-verify before
concluding. run_tests takes the same finding_id you already have -- it automatically applies
whatever you most recently proposed for that finding; you never need to pass diff text yourself.
If tests fail, you may call `propose_fix` again with what you learned (mention the failure in your
next message) up to a couple of times.

When you're done, reply with a final plain-text summary (no more tool calls) starting with either
"RESOLVED:" or "UNRESOLVED:" followed by one sentence explaining the outcome.""".rstrip()

REFACTORING_PROMPT = (
    """You are the Refactoring Agent, a specialist that resolves STRUCTURAL technical debt --
long or deeply-nested functions, high cyclomatic complexity, duplicated code, long parameter
lists, dead code, magic numbers, and unused imports/variables.

Propose a minimal, BEHAVIOUR-PRESERVING change that removes the debt: extract a helper, introduce
a named constant, delete the genuinely-unused symbol, collapse duplication, etc. Never change what
the code does -- only how it's structured. Any name you introduce (a new helper, constant, or
import) must be defined or imported in the same edit; do not reference something you haven't created."""
    + _TOOL_PROTOCOL
)

DOCUMENTATION_PROMPT = (
    """You are the Documentation Agent, a specialist that resolves MISSING or INADEQUATE
documentation. Your job is to add a clear, accurate docstring to the function, method, class, or
module the finding points at.

Write a concise docstring: a one-line summary of what it does, then (when they apply) an Args
section describing each parameter, a Returns section, and a Raises section. Match the surrounding
code's existing docstring style if one is visible. Describe the code's ACTUAL behaviour -- read it
first; don't guess. Do NOT change any executable code, rename anything, or alter logic -- your edit
adds documentation only. Running the tests afterwards confirms your docstring didn't break an
import or introduce a syntax error."""
    + _TOOL_PROTOCOL
)

TEST_GENERATION_PROMPT = (
    """You are the TestGeneration Agent, a specialist that resolves MISSING_TESTS findings.
Your goal is to add a focused regression test that demonstrates the behaviour of the target function
or verifies the path it is supposed to support. Read the implementation and any existing tests first,
then add or extend a test file with a minimal case that would have failed before the change.
Be behaviour-focused, not implementation-focused, and avoid introducing unrelated changes.
Use the existing test infrastructure and run the relevant tests to verify the new test passes."""
    + _TOOL_PROTOCOL
)


@dataclass(frozen=True)
class Specialist:
    """One named agent: a display name, its role system prompt, and the set of
    finding types it owns. `handles` is what the router matches against.

    `reviews_fixes` gates whether the independent ReviewerAgent spends an LLM
    call judging this specialist's fixes. It is True for specialists that change
    executable code (where the reviewer catches real blind spots -- a fix that
    references a helper it never defined, etc.), and False where a fix cannot
    alter behaviour and the sandboxed tests already prove it didn't break an
    import -- reviewing those adds no signal and just burns a call against the
    rate limit."""
    name: str
    system_prompt: str
    handles: Set[str]
    reviews_fixes: bool = True


REFACTORING_AGENT = Specialist(
    name="RefactoringAgent",
    system_prompt=REFACTORING_PROMPT,
    handles={
        "long_function", "high_complexity", "duplication", "long_parameter_list",
        "dead_code", "magic_number", "unused_import", "unused_variable",
    },
)

DOCUMENTATION_AGENT = Specialist(
    name="DocumentationAgent",
    system_prompt=DOCUMENTATION_PROMPT,
    handles={"missing_docstring"},
    # A docstring edit changes no behaviour; run_tests already confirms it
    # didn't break an import or syntax. An extra LLM review adds no signal, so
    # skip it and save the call (see reviews_fixes on Specialist).
    reviews_fixes=False,
)

TEST_GENERATION_AGENT = Specialist(
    name="TestGenerationAgent",
    system_prompt=TEST_GENERATION_PROMPT,
    handles={"missing_tests"},
)

# Order matters only for display; types are disjoint across specialists so
# there's no ambiguity in routing.
SPECIALISTS = [DOCUMENTATION_AGENT, TEST_GENERATION_AGENT, REFACTORING_AGENT]

# Finding types with no dedicated specialist (e.g. missing_tests, which needs
# test *generation* rather than a structural edit) fall here. RefactoringAgent
# is the most general fixer; routing to it is honest -- it may report
# UNRESOLVED, which the roadmap shows plainly -- rather than silently dropping
# the finding.
DEFAULT_SPECIALIST = REFACTORING_AGENT


def route(finding_type: str) -> Tuple[Specialist, str]:
    """Pick the specialist for a finding type and return (specialist, reason).
    The human-readable reason is threaded into the roadmap so the routing
    decision itself is explainable, not just its outcome."""
    for spec in SPECIALISTS:
        if finding_type in spec.handles:
            return spec, f"finding type '{finding_type}' is owned by {spec.name}"
    return (
        DEFAULT_SPECIALIST,
        f"finding type '{finding_type}' has no dedicated specialist; "
        f"routed to {DEFAULT_SPECIALIST.name} (default fixer)",
    )
