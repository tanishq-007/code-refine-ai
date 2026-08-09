# Architecture — An Explainable Multi-Agent System for Automated Code Refactoring, Documentation, and Quality Enhancement

This document describes the multi-agent architecture of the Code Debt
Collector: the agents, how a finding flows through them, how routing decisions
are made, and how every decision is made *explainable* in the final roadmap.

For the detection rule behind each finding type, see `DETECTION_RULES.md`. For
setup and the course-component mapping, see `README.md`. For the honest
"what's actually verified" state, see `ONBOARDING.md`.

---

## 1. The idea in one paragraph

A deterministic scan (Phase 1) produces technical-debt *findings*. Each finding
is scored for impact/effort (Phase 2) and ranked. The top findings are then
handed to a **team of specialist LLM agents**: a **coordinator** routes each
finding to the specialist that owns its kind of debt, that specialist proposes
and self-verifies a fix, and an **independent reviewer** agent judges the
result. Every step records *what it did and why*, and the final Markdown
roadmap renders that trace — so the system explains not just *what* to change
but *who* decided it, *why they were chosen*, and *whether the change was
judged good*.

The multi-agent layer is a **routing + role-specialization layer on top of the
already-verified single-agent tool loop** — not a rewrite. `--strategy single`
falls back to the original one-generalist-agent behaviour and produces a
byte-for-byte-unchanged roadmap.

---

## 2. The agents

| Agent | Role | Owns | Code |
|-------|------|------|------|
| **Coordinator** | Routes each finding to a specialist; records the routing reason; runs the reviewer; assembles results | — | `agent/orchestrator.py` (`_resolve_multi_agent`, `_run_mcp_session`) |
| **RefactoringAgent** | Behaviour-preserving structural fixes | `long_function`, `high_complexity`, `duplication`, `long_parameter_list`, `dead_code`, `magic_number`, `unused_import`, `unused_variable` | `agent/specialists.py` |
| **DocumentationAgent** | Adds docstrings; never changes executable code | `missing_docstring` | `agent/specialists.py` |
| **TestGenerationAgent** | Adds a focused regression test demonstrating the target function's behaviour | `missing_tests` | `agent/specialists.py` |
| **ReviewerAgent** | Independent quality gate: approve / revise / reject + rationale. A `reject` or `revise` earns the fix exactly ONE retry — the same specialist re-attempts with the rationale fed back as extra context, and the retry replaces the original only if its tests actually pass; a still-`reject`ed fix withholds the diff and drops out of the verified count | *(reviews behaviour-changing fixes; docstring fixes are skipped — no behaviour to assess)* | `agent/reviewer.py`, retry loop in `agent/orchestrator.py` (`MAX_REVIEW_RETRIES`) |
| **Verifier** (tool, not an LLM) | Applies the fix to a throwaway repo copy and runs the tests | — | `agent/fixgen.py` (`apply_and_verify`), exposed as the `run_tests` MCP tool |

The three specialist agents share the **same tool-use engine**
(`resolve_finding` / `_resolve_finding_mcp`) and the same 6 MCP tools
(`read_finding`, `read_file_snippet`, `get_standards`, `search_codebase`,
`propose_fix`, `run_tests`). They differ only in their **system prompt** and
the **finding types they own** — so specialization is real (distinct role,
distinct judgement) without duplicating the loop. Any finding type with no
dedicated specialist falls to `DEFAULT_SPECIALIST` (RefactoringAgent) rather
than going unhandled — see §4.

---

## 3. How a finding flows

```
                    ┌─────────────────────────────────────────────┐
 scan (Phase 1)     │  analyzers/  →  Finding[]                    │
                    └───────────────────┬─────────────────────────┘
                                        ▼
 score (Phase 2)     agent/scoring.py  →  ScoredFinding[]  (impact/effort, ranked)
                     rag/  grounds severity + fan-in            │  (+ explainable justification)
                                        ▼
                    ┌───────────────────────────────────────────── COORDINATOR ─┐
                    │  for each top-N finding:                                   │
                    │                                                            │
                    │     route(finding.type)  ─────────────►  (Specialist, why) │
                    │            │                                               │
                    │   ┌────────┬──────────┴─────────┐                          │
                    │   ▼        ▼                     ▼                          │
                    │  RefactoringAgent  DocumentationAgent  TestGenerationAgent  │
                    │   │  propose_fix  →  run_tests (self-verify)  │            │
                    │   └──────────┬───────────────────────────────┘            │
                    │              ▼  (diff, applied?, tests_passed?)            │
                    │        ReviewerAgent  ──►  {verdict, rationale}            │
                    │              │  (independent — did NOT write the fix)      │
                    │              ▼                                             │
                    │     reject/revise?  ──► ONE retry (same specialist,        │
                    │              │            rationale fed back) ──► kept     │
                    │              │            only if its tests pass          │
                    │              ▼  (not re-reviewed either way)               │
                    │   result{agent, routing_reason, diff, tests_passed,       │
                    │          review, retry}                                   │
                    └───────────────────────────┬───────────────────────────────┘
                                                 ▼
 roadmap             agent/roadmap.py  →  roadmap.md  (Agents table + per-finding trace)
```

Both **transports** honour this flow identically:
- `--transport in-process` (default) — tools dispatch as direct function calls.
- `--transport mcp` — tools cross a real MCP stdio subprocess boundary
  (`mcp_server/server.py`), with a session-level fallback to in-process.

Routing and reviewing are transport-agnostic (they're client-side prompt
selection + one LLM call), so `--strategy multi` works over both.

---

## 4. Routing

`agent/specialists.route(finding_type)` returns `(specialist, reason)`:

- If a specialist declares the type in its `handles` set, it wins. Today all
  10 finding types have a dedicated owner (8 to RefactoringAgent, 1 each to
  DocumentationAgent and TestGenerationAgent), so this is the path every
  finding actually takes.
- Otherwise the finding falls to `DEFAULT_SPECIALIST` (RefactoringAgent) with
  a reason that says so explicitly. This only fires today if a new analyzer
  is added without also giving its finding type a specialist — routing
  degrades to "try the generalist fixer" rather than silently dropping the
  finding, and it may honestly report `UNRESOLVED` if that's not the right
  fit, which is visible in the roadmap either way.

The human-readable `reason` is carried all the way into the roadmap, so the
routing decision itself is auditable.

---

## 5. Explainability — the decision trace

Every finding in the roadmap carries a full trace, assembled from what each
stage recorded:

| Layer | Question answered | Source |
|-------|-------------------|--------|
| `why` | Why was this flagged? | analyzer `description` |
| `scorer notes` | Why this priority? | `agent/scoring.py` justification (LLM or the rule-fired heuristic trace) |
| `handled by` + reason | Who fixed it, and why them? | `agent/specialists.route` |
| `proposed fix` status | Did it apply? Did tests pass? | `run_tests` / `apply_and_verify` |
| `reviewer verdict` | Was the change actually good? A `reject` withholds the diff and excludes the fix from the verified count | `agent/reviewer.py` |
| `retry` (if present) | Did a `reject`/`revise` verdict earn this finding its one retry, and what happened? | `agent/orchestrator.py` (`_merge_retry`) |

The roadmap also opens with an **Agents** summary table (findings handled and
verified per specialist) and a one-line ReviewerAgent tally (`N approve, M
reject, …`) — the system explaining itself at a glance.

Under `--strategy single`, none of the `agent`/`review` tags are produced, so
the Agents section is omitted and the roadmap is identical to the original
single-agent output — a clean before/after baseline for the writeup.

---

## 6. Title → implementation mapping

| Title phrase | Realized by |
|--------------|-------------|
| **Multi-Agent System** | Coordinator + RefactoringAgent + DocumentationAgent + TestGenerationAgent + ReviewerAgent (`agent/specialists.py`, `agent/reviewer.py`, `agent/orchestrator.py`) |
| **Automated Code Refactoring** | RefactoringAgent over 8 structural finding types, structured `{old_str,new_str}` edits → deterministic diff → sandboxed verify |
| **Documentation** | DocumentationAgent — a dedicated specialist that resolves `missing_docstring` by writing docstrings, without touching code |
| **Testing** | TestGenerationAgent — a dedicated specialist that resolves `missing_tests` by adding a focused regression test, verified the same way as any other fix |
| **Quality Enhancement** | ReviewerAgent quality gate + impact/effort prioritization + `run_tests` verification |
| **Explainable** | Per-finding decision trace + Agents summary in `agent/roadmap.py`, grounded in each stage's recorded rationale |

---

## 7. Running it

```bash
# Multi-agent (default): findings routed to specialists, reviewed, explained
python main.py run --repo addition -o roadmap.md --strategy multi

# Single-agent baseline (original generalist loop; unchanged output)
python main.py run --repo addition -o roadmap_single.md --strategy single

# Multi-agent over a real MCP stdio subprocess
python main.py run --repo addition --strategy multi --transport mcp
```

**Model configuration** (default to Mistral's `mistral-small-latest` for
`LLM_ORCH_MODEL` (specialists) and `LLM_REVIEW_MODEL` (ReviewerAgent), and
`codestral-latest` for `LLM_FIX_MODEL` (`propose_fix`)). Pointing `LLM_REVIEW_MODEL` at a **stronger
model** makes the reviewer a sharper critic than the author — recommended, since
an independent, more capable reviewer best catches the small-model failure mode
(introducing a name it never defines).

---

## 8. Cost & rate-limit note

The multi-agent path spends more LLM calls than the single-agent one: each
finding costs a specialist tool loop **plus, for behaviour-changing fixes, one
reviewer call**. Docstring fixes skip the reviewer (nothing behavioural to
judge), so they don't pay that call. A `reject`/`revise` verdict adds **at most
one more** specialist tool loop (the capped retry, `MAX_REVIEW_RETRIES = 1` in
`agent/orchestrator.py`) — never a second review call, and never more than one
retry regardless of the retry's own outcome. On a free-tier provider plan this
hits the per-minute/day limit sooner, so:

- `top_n` throttles how many findings are resolved per run.
- Client-side pacing (`LLM_MIN_INTERVAL_SECONDS`) spaces requests.
- A `429` is surfaced as a typed `RateLimitExhausted` that **hard-stops** the
  run cleanly (including mid-review and mid-retry) instead of retrying into an
  exhausted quota — threaded through every agent and both transports.
