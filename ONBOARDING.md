# Onboarding — Code Debt Collector

This is a handoff doc for anyone picking up this project. It covers what's
implemented, what's actually verified working, what's still rough, and how
to try the tool yourself in five minutes.

For the exact detection rule behind every finding type, see `DETECTION_RULES.md`.
For the general project pitch and course-component mapping, see `README.md`.
This doc is the "what's the real state of things" layer between the two.

## Quick start (5 minutes)

```bash
pip install -e .
cp .env.example .env        # add MISTRAL_API_KEY -- free at console.mistral.ai
```

Then, from `gen-ai-project/`:

```bash
python main.py scan --repo addition          # deterministic findings, no key needed
python main.py eval                          # precision/recall vs. planted debt, no key needed
python main.py score --repo addition         # LLM impact/effort scoring (needs the key)
python main.py run --repo addition -o roadmap.md --transport mcp   # full agentic pass
```

`--transport mcp` vs `--transport in-process` (default) only changes *how* the
agent's tool calls are executed (real MCP stdio subprocess vs. direct in-process
function calls) — not what it does. See `DETECTION_RULES.md`'s "Tool-execution
transport" section for the full explanation.

## What the `addition/` folder is for

It's a **hand-built demo target codebase** — not part of the tool itself, not a
test fixture for `main.py eval` (that's `eval/sample_repo`, which is graded
against `eval/ground_truth.json`). `addition/` exists purely so you have
something richer than the tiny `eval/sample_repo` to point the scanner at and
see real, varied output without needing your own project.

```
addition/
  src/
    float_add.py     add_floats (clean) + add_floats_with_rounding (long, complex,
                     many params) + legacy_float_sum (dead code)
    decimal_add.py   same shape, decimal arithmetic
    int_add.py       same shape, integer overflow handling
    mixed_ops.py      ties the three above together; process_transaction is
                     itself long/complex and (harmlessly) flagged dead_code
                     since nothing outside the repo calls it -- a good example
                     of dead_code's known false-positive limitation
  tests/
    test_float_add.py   covers add_floats only, deliberately leaving the rest
                        of the codebase under-tested
```

It currently trips **7 of the 10 finding types** (`dead_code`, `high_complexity`,
`long_function`, `long_parameter_list`, `magic_number`, `missing_docstring`,
`missing_tests` — last verified: 74 findings). It doesn't trigger
`unused_import`/`unused_variable` (no planted example). It also doesn't
trigger `duplication` even though `float_add.py`/`decimal_add.py`/`int_add.py`
are narratively "the same shape" — without `jscpd`, `analyzers/duplication.py`'s
AST-clone fallback (see `DETECTION_RULES.md`) only catches functions that are
*structurally* identical, and these three differ enough (float vs. `Decimal`
vs. `int` arithmetic) that their signatures don't collide. Installing `jscpd`
(`npm i -g jscpd`) would catch the token-level similarity the fallback misses.

**How to run it**: exactly like any other target repo —
`python main.py scan --repo addition`, `... score --repo addition`,
`... run --repo addition -o addition_roadmap.md`. Nothing addition-specific
about the commands; it's just a `--repo` argument.

## The web UI

Everything above is the CLI. There's also a full local web app over the same
pipeline — `server/app.py` (FastAPI) + `frontend/` (React + Vite). It doesn't
replace the CLI, it wraps it: every job the UI runs is just `main.py
scan`/`score`/`run`/`eval` as a subprocess, with its live stdout streamed
back over SSE.

```bash
pip install -e ".[web]"
uvicorn server.app:app --port 8000        # terminal 1 — backend

cd frontend && npm install && npm run dev  # terminal 2 — http://localhost:5173
```

Seven pages, all driven by one repo-scoped data layer (`frontend/src/lib/store.tsx`):

- **Landing** — pitch + pipeline explainer.
- **Overview** — dashboard: findings-by-type donut/bar, hotspot files, an
  impact/effort scatter colored by roadmap tier.
- **Findings** — filterable/sortable table of every raw finding, expandable
  to the actual code snippet.
- **Roadmap** — the Do now / Plan / Backlog board (or the raw `roadmap.md`).
- **Fixes** — review each specialist-proposed fix (routing reason, reviewer
  verdict, retry note), view the diff in a Monaco split editor, and apply a
  verified fix straight to the real repo (two-step confirm; `git apply`
  validates the whole patch before touching any file).
- **Editor** — for findings below the pipeline's `--top-n` cutoff that never
  got an LLM fix: pick one, hand-edit the file, save — it's diffed against
  disk and gets the exact same sandboxed apply-and-test verification as a
  model-proposed fix.
- **Run** — pick `scan`/`score`/`run`/`eval`, set flags (top-N, strategy,
  transport, skip-fixes, skip-fan-in), and watch the job's output stream live.

The repo picker (top of every page) isn't limited to this project — its "Add
repo" option can `git clone` any URL or accept a drag-and-dropped/uploaded
folder from the browser; both land in `.code_debt_workspace/` (gitignored)
and show up in the picker immediately. Every UI-triggered pipeline run writes
its artifacts to `<repo>/.code_debt/` (`findings.json`, `scored.json`,
`fixes.json`, `roadmap.md`), which is also where every page reads from.

## What's implemented, this round and before

- **Provider migration**: Anthropic/Claude → any OpenAI-compatible endpoint
  (`agent/llm_client.py`), defaulting to Mistral's hosted models (previously
  Groq's free-tier Llama models). Batched scoring, client-side rate-limit
  pacing, typed `RateLimitExhausted` handling that stops cleanly instead of
  retrying into an exhausted quota.
- **5 new analyzers** (`long_parameter_list`, `missing_docstring`,
  `unused_import`, `unused_variable`, `magic_number`) — all deterministic, all
  with planted eval fixtures and ground truth entries.
- **Roadmap tier-gating fix**: "Do now" now requires `impact >= 3 AND ratio >=
  2.0`, not ratio alone — mechanical low-impact findings no longer
  automatically crowd out real structural debt.
- **Explainable offline heuristic scorer**: justification is now a formatted
  trace of which rules fired, not two bare numbers.
- **MCP stdio transport** (`--transport mcp`): the agent's 6 tools can now
  genuinely cross a subprocess/MCP-protocol boundary (spawns
  `mcp_server/server.py`), with a verified session-level fallback to
  in-process if the transport can't spawn/initialize, and per-tool-call
  latency instrumentation.
- **Fix-generation redesign** (the part that took the most iteration): the
  model no longer hand-authors unified diffs. It returns a structured
  `{"edits": [{"old_str", "new_str"}]}` (str_replace semantics); the diff is
  built deterministically with `difflib.unified_diff()`. `run_tests` no
  longer receives diff text as an argument either — it takes a `finding_id`
  and looks the diff up from a server-side cache populated by `propose_fix`
  — this eliminated a real failure mode where the model corrupted the diff's
  JSON escaping when copying it into a second tool call.
- **Multi-agent routing** (`--strategy multi`, the default): a coordinator
  routes every finding to one of 3 specialists — RefactoringAgent
  (structural debt), DocumentationAgent (`missing_docstring`), or
  TestGenerationAgent (`missing_tests`) — each with its own role prompt over
  the same shared tool-use engine. An independent ReviewerAgent judges every
  behaviour-changing fix (docstring/test-only fixes skip review — no
  behaviour to assess) and a `reject`/`revise` verdict earns exactly one
  capped retry, fed the reviewer's rationale. See `ARCHITECTURE.md`.
- **The web UI** (`server/app.py` + `frontend/`): a FastAPI backend wraps the
  CLI as background jobs with SSE log streaming, and a React app gives you a
  dashboard, a findings explorer, a roadmap board, a fix-review split-diff
  editor with apply-to-repo, and a manual fix editor for findings outside the
  `--top-n` cutoff. See "The web UI" above.
- **RAG rewrite: Voyage/Chroma → local TF-IDF** (`rag/index.py`): the
  embedding-API-based retrieval was replaced with a pure-Python TF-IDF
  vectorizer + cosine similarity over the same standards corpus
  (`rag/standards.py`, now covering all 10 finding types instead of 5). No
  external API, no key, no rate limit — `get_standards(finding_type)`
  dropped the now-meaningless `repo_root`/`py_files` params it used to need
  for index-building.
- **Fixed a real crash bug**: `agent/fixgen.py::propose_fix`'s retry path
  referenced an undefined `raw` variable — the very first malformed model
  response would `NameError` instead of retrying. `llm_client.request_json_response`
  gained an optional `raw_out` hook so the caller can recover the model's
  actual text even when JSON parsing itself fails.
- **Fixed a sandbox-bloat/secret-copying bug**: `agent/fixgen.py` and
  `mcp_server/tools.py`'s fix-verification sandbox copier only excluded
  `.git` (and sometimes `.code_debt`), so every real fix run copied
  `.claude/` (162MB in one observed case), `node_modules/`, and — worse —
  `.env` itself (live API keys) into `<repo>/.code_debt/sandbox`. Now uses
  the shared `IGNORE_DIRS` plus a dot-prefix catch-all, same pattern as the
  analyzers. Measured: 444MB → 799KB for one real sandbox.

## What's actually working (verified, not assumed)

- `main.py scan` / `main.py eval` — 100% deterministic, fully verified,
  reproducible. This is the most solid part of the project.
- `main.py score` — both LLM (Mistral, batched) and offline heuristic paths
  verified live.
- `main.py run` — **the full pipeline mechanics are solid**: diffs are always
  syntactically valid, always apply cleanly when the model's content is
  correct, tests are correctly detected and run (including from a `tests/`
  subdirectory), Windows line-ending handling is correct. Confirmed via a
  live smoke-test batch: 9/9 completed runs across both transports had zero
  infrastructure failures (no corrupt patches, no invalid paths, no
  undetected test suites) — every non-pass was a genuine, inspectable model
  content mistake (e.g. renaming to an undefined name).
- **Live-verified against Mistral specifically** (not just Groq): a full
  `main.py scan` → `score` → `run` (multi-agent, in-process transport) pass
  against this project's own ~55-file Python codebase resolved 10 findings with
  zero infrastructure failures; the same pass against `addition/` resolved
  14. Both produced a valid `roadmap.md` with real reviewer verdicts.
  `--transport mcp` has not been separately re-verified against Mistral this
  round (it was verified against Groq previously — the transport layer
  itself doesn't depend on the provider, but it hasn't been re-run).
- **The web UI is live and in active use**, not just reviewed: the FastAPI
  job runner (`server/app.py`) has been observed running real `scan`/`run`
  jobs against multiple repos through its API during this project's actual
  use, confirming the background-job + SSE-streaming mechanism works against
  a live server, not just in theory.

## Verification notes (latest run)

- **Regression tests**: `pytest -q tests/test_structured_llm.py` → 2 passed.
- **Eval benchmark**: `python main.py eval` → overall P/R/F1 `0.77/0.91/0.83`.
- **Call-budget / coordination changes**: structured JSON helpers are now used by scoring, reviewing, fix generation, and the new verification/planning helpers; reviewer self-consistency and planner/retry hooks are wired into the orchestrator, and reviewer logs are written to `.code_debt/review_log.jsonl`.

## What still needs work

- **Fix-resolution success rate was low on Groq's `llama-3.1-8b-instant`**
  (~1 in 9 in live testing at the time) — a content-quality ceiling (it
  didn't reliably define a name it introduced), not an infrastructure bug.
  Every mechanical failure mode found during development (line-number leaks,
  wrong hunk headers, hallucinated context, JSON escaping corruption,
  Windows CRLF corruption, missing test detection) has been individually
  root-caused and fixed. **This has not been rigorously re-benchmarked on
  Mistral's models** — the live smoke tests this round showed zero
  infrastructure failures, but nobody has yet counted a large clean-tests-pass
  rate specifically for `mistral-small-latest`/`codestral-latest`. Worth
  doing before citing a number for the current default provider.
- **`duplication` works without `jscpd`, but with lower recall** — a
  dependency-free AST structural-clone fallback (`analyzers/duplication.py`)
  catches whole-function clones; installing `jscpd` (`npm i -g jscpd`) adds
  jscpd's token-window analysis on top, which also catches *partial*
  duplication inside a larger function that the fallback can't see.
- **No automated tests for the fix pipeline itself** — `apply_and_verify`,
  `propose_fix`, and the orchestrator loop were all verified via live manual
  smoke tests, not a checked-in pytest suite. Worth adding if this keeps
  evolving.
- **No automated tests for `rag/index.py`'s TF-IDF retrieval** either — it
  was verified manually (every finding type correctly self-retrieves; a
  few free-text queries correctly retrieve the right document by content,
  not just an exact type-name match) but there's no `tests/test_rag.py`
  locking that behavior in.
- **No clean transport-latency benchmark**: every live comparison run so far
  got confounded by real rate-limit retries (originally against Groq's free
  tier). The per-tool-call numbers logged (`[transport] ... called Nx, mean
  X.XXXs`) are directionally useful but not a clean apples-to-apples overhead
  measurement.

## Where to look for more detail

- `DETECTION_RULES.md` — the exact rule/threshold behind every finding type,
  the scoring formulas (LLM and heuristic), and the transport/fix-generation
  architecture with the specific bugs found and fixed.
- `README.md` — project pitch, course-component mapping, setup instructions.
