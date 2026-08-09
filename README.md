# Code Debt Collector

An agentic LLM system that scans a codebase, detects technical debt (long
functions, duplication, high complexity, missing tests, dead code, long
parameter lists, missing docstrings, unused imports/variables, magic
numbers), prioritizes findings by an impact / effort ratio using
multi-step LLM reasoning over deterministic signals, proposes refactoring
fixes as unified diffs, and emits a Markdown refactoring roadmap. See
`DETECTION_RULES.md` for the exact rule behind every finding type.

Polyglot: Python + JavaScript/TypeScript (analyzers walk both; duplication
detection via `jscpd` is polyglot by construction).

## How it maps to the course components

| Component        | Where |
|-------------------|-------|
| Prompt engineering | `agent/scoring.py` — structured-output prompts that score + justify |
| RAG               | `rag/` — local TF-IDF retrieval index (`rag/index.py`) over a coding-standards corpus (`rag/standards.py`); grounds severity judgment in scoring and gives specialists a "what does good look like" reference before proposing a fix. No external API/key. |
| MCP               | `mcp_server/server.py` — standalone MCP stdio server exposing all 6 analysis tools. `main.py run --transport mcp` spawns it and drives the agent loop's tool calls over a real MCP stdio session (verified: genuine subprocess boundary, real per-call latency); `--transport in-process` (the default) dispatches the same tools as plain in-process function calls instead, with a session-level fallback to it if the MCP transport can't spawn/initialize |
| Agentic LLM       | `agent/orchestrator.py` — an LLM drives the tool-use loop and self-verifies fixes |
| "and more"        | impact/effort scoring, fix verification via `run_tests`, and `eval/` precision/recall against planted debt |

Models: any OpenAI-compatible tool-calling endpoint via `agent/llm_client.py`
— defaults to Mistral's hosted `mistral-small-latest` (scoring, agent loop)
and `codestral-latest` (fix generation); override `LLM_BASE_URL`/`LLM_*_MODEL`
to point at a different OpenAI-compatible provider, or a different model
per call site, instead. Calls are client-side paced
(`LLM_MIN_INTERVAL_SECONDS`) and a 429 is surfaced as a typed
`RateLimitExhausted` so a hit quota stops the run cleanly instead of
retrying into a wall. Retrieval (`rag/get_standards`) needs no embedding
provider at all — it's a local TF-IDF index over a small fixed corpus, so
there's nothing to configure and no rate limit to hit.

## Layout

```
analyzers/   Phase 1  deterministic signals (complexity, long-function,
                       dead code, missing tests, duplication (jscpd, or an
                       AST-clone fallback for Python), git churn,
                       long parameter lists, missing docstrings, ruff
                       unused-import/-variable, magic numbers)
rag/         Phase 3  local TF-IDF retrieval over coding standards (no external API)
mcp_server/  Phase 4  local MCP tool server (6 tools)
agent/       Phase 5  orchestrator, scoring, fixgen, roadmap
eval/        planted-debt sample repo + ground truth + precision/recall
main.py      CLI: scan | score | run | eval
```

## Setup

```bash
pip install -e .
npm i -g jscpd              # optional: enables duplication detection (Python + JS/TS)
cp .env.example .env        # add MISTRAL_API_KEY
bash eval/seed_history.sh    # give the sample repo realistic git churn
```

Nothing above is strictly required to try the tool: `analyzers/complexity.py`
falls back to a small ast-based cyclomatic-complexity counter if `radon`
isn't installed, `analyzers/duplication.py` falls back to a dependency-free
AST structural-clone detector (Python-only, whole-function clones only) if
`jscpd` isn't on PATH — lower recall than `jscpd`, but not zero,
`analyzers/unused_code.py` (unused_import/
unused_variable) similarly contributes zero findings if `ruff` isn't on
PATH, `analyzers/churn.py` no-ops without a `.git` dir, `rag/get_standards`
needs no setup at all (local TF-IDF, no external API), and
`agent/scoring.py` falls back to a deterministic heuristic scorer without
an LLM key. Only `agent/fixgen.py` (fix generation, via `main.py run`)
hard-requires a live LLM (`MISTRAL_API_KEY` by default) — there's no
meaningful offline stand-in for generating a diff.

## Run

```bash
python main.py scan                 # Phase 1: raw findings as JSON
python main.py score                # add LLM (or offline heuristic) impact/effort scores
python main.py run -o roadmap.md    # full agentic pass -> roadmap
python main.py eval                 # precision/recall vs. planted debt (no API key needed)
```

## Web dashboard (localhost)

An interactive UI over the same pipeline: overview charts, a filterable
findings explorer with code snippets, the roadmap as a tiered board, a
split-diff editor for reviewing and applying proposed fixes, a manual
editor for hand-fixing findings outside the `--top-n` cutoff (still
sandbox-verified the same way), and a run panel that triggers
scan/score/run/eval with live-streamed logs.

```bash
pip install -e ".[web]"             # fastapi + uvicorn
uvicorn server.app:app --port 8000  # backend (terminal 1)

cd frontend
npm install
npm run dev                         # frontend (terminal 2) -> http://localhost:5173
```

The Vite dev server proxies `/api` to the backend on port 8000. Pipeline
runs started from the UI write their artifacts to `<repo>/.code_debt/`
(`findings.json`, `scored.json`, `fixes.json`, `roadmap.md`), which is
also where the dashboard reads from.

Besides pointing at any local path, the repo picker's *"Add repo"* option
can clone a repo from a Git URL or accept a dragged/uploaded folder from
the browser; both land in `.code_debt_workspace/` (gitignored) and show
up in the repo list ready to scan.

## Build order / status

- ✅ **Phase 1** `analyzers/` — `scan` produces real findings (complexity,
  long function, missing tests, dead code, long parameter lists, missing
  docstrings, magic numbers; duplication uses `jscpd` if present, else an
  AST-clone fallback for Python with lower recall; unused-import/-variable
  needs `ruff`, churn needs `git`). Degrades gracefully when external tools
  are absent.
- ✅ **Phase 2** `agent/scoring.py` — impact/effort scoring via structured
  outputs, reasoning over the deterministic signals. (`python main.py score`)
- ✅ **Phase 3** `rag/` — a local, dependency-free TF-IDF retrieval index
  (`rag/index.py`) over the coding-standards corpus (`rag/standards.py`);
  `get_standards` feeds both the scorer and the fix-generation specialists,
  `enrich_fan_in` adds a real (separate, plain-text) fan-in signal. No
  external API, no key, always on; `score --no-rag` only skips the fan-in
  pass, not standards retrieval.
- ✅ **Phase 4** `mcp_server/` — local MCP server exposing 6 tools. Logic
  lives in `mcp_server/tools.py` (no `mcp` dep, testable); `server.py` is
  the stdio binding, runnable standalone or spawned by `run --transport mcp`.
  File access is confined to the repo root (path-traversal guard).
- ✅ **Phase 5** — agentic loop + fixes + eval:
  - `agent/orchestrator.py` — an LLM (Mistral's hosted models by default, via
    `agent/llm_client.py`) drives the 6 tools via a tool-use loop, over
    either transport (`--transport in-process`, the default, or
    `--transport mcp` for a real MCP stdio session against `mcp_server/server.py`;
    session-level fallback to in-process if the MCP transport can't spawn/initialize),
    self-verifies fixes with `run_tests`, emits the roadmap.
  - `agent/fixgen.py` — proposes fixes as unified diffs; `apply_and_verify`
    applies them to a throwaway repo copy and runs tests (never touches
    your tree).
  - `eval/score_pipeline.py` — precision/recall/F1 vs. `ground_truth.json`
    (`python main.py eval`, no API key needed).

The `Finding` schema (`analyzers/base.py`) is the stable contract
everything depends on.

## Current eval (no jscpd/git installed; ruff installed; LLM scoring not required)

```
type                    P      R     F1   (tp/fp/fn)
long_function        1.00   1.00   1.00  (1/0/0)
high_complexity      1.00   1.00   1.00  (1/0/0)
duplication          1.00   1.00   1.00  (2/0/0)   <- AST-clone fallback, no jscpd needed
missing_tests        0.25   1.00   0.40  (1/3/0)   <- heuristic over-flags by design
dead_code            0.50   1.00   0.67  (1/1/0)
long_parameter_list  1.00   1.00   1.00  (1/0/0)
missing_docstring    1.00   1.00   1.00  (1/0/0)
unused_import        1.00   1.00   1.00  (1/0/0)
unused_variable      1.00   1.00   1.00  (1/0/0)
magic_number         0.33   1.00   0.50  (1/2/0)   <- see below
OVERALL              0.65   1.00   0.79  (11/6/0)
```

A git history (`bash eval/seed_history.sh`, for the churn signal used in
scoring) is the only thing missing above; installing `jscpd` would replace
`duplication`'s AST-clone fallback with jscpd's token-window analysis (more
sensitive to *partial*, not just whole-function, duplication) but isn't
needed for the perfect score already shown. The `dead_code`, `missing_tests`,
and `magic_number` precision dips are expected — `dead_code`'s one false
positive (`pricing.format_price`) is a real, if unplanted, unreferenced
function; `missing_tests`'s over-flagging is intentional (the heuristic
can't see indirect coverage); and `magic_number`'s two false positives are
genuine (if unplanted) inline literals in `orders.py`/`pricing.py`, which
predate that analyzer and were deliberately left as-is rather than
retrofitted — see `DETECTION_RULES.md` for why. Impact scoring demotes
these false positives later using fan-in/churn context the heuristic alone
doesn't have.

## Testing notes

This was built and verified in an offline sandbox (no network access):
`main.py scan`, `main.py score` (heuristic path), `main.py run --no-fixes`
(roadmap generation), `main.py eval`, and all 6 `mcp_server/tools.py`
functions (including the path-traversal guard) were exercised directly and
work with zero external dependencies installed.

`agent/fixgen.py` and `agent/orchestrator.py`'s live tool-use loop (default
`--transport in-process`) have since been **live-verified against Mistral**:
full `scan → score → run` (multi-agent) passes against both this project's
own codebase and `addition/` completed with zero infrastructure failures —
see `ONBOARDING.md`'s "What's actually working" for the specifics.
`mcp_server/server.py`'s stdio transport (`--transport mcp`) was previously
verified against Groq but hasn't been re-run against Mistral. `rag/get_standards`
(local TF-IDF retrieval, no external API) is exercised directly in every
`score`/`run` pass above and needs no separate live-verification step — see
`rag/index.py`'s module docstring for how retrieval is scored.
