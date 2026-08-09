# How Code Debt Collector decides what's "debt"

This documents exactly what each pipeline stage does and the precise rule
each finding type is based on -- so you can check the tool's output against
the actual logic rather than trusting it as a black box.

## Pipeline overview

This project numbers its build phases 1-5 (that's what `agent/orchestrator.py`'s
own module docstring means by "Phase 5", what `analyzers/scan.py`'s means by
"Phase 1", and what README.md's "Build order / status" section uses too) --
the table below uses that same numbering, not a separate CLI-command count.

| Phase | Name | Command | Deterministic or LLM? |
|---|---|---|---|
| 1 | Scan | `main.py scan` | **100% deterministic.** AST parsing, regex, and external CLI tools (`radon`, `jscpd`, `ruff`, `git`). No API calls, no model, fully reproducible. |
| 2 | Score | `main.py score` | **LLM if a key is set** (Mistral, batched — see `agent/scoring.py`), **deterministic heuristic otherwise** (exact rules below). |
| 3 | RAG support | *(no standalone command — used inside `score` and `run`; `--no-rag` on `score` skips only the fan-in pass, not standards retrieval)* | Infrastructure, not itself an LLM reasoning call. A local TF-IDF retrieval index over the coding-standards corpus, plus a separate plain-text fan-in grep — see `rag/`. No external API, no key. |
| 4 | MCP tool server | *(no standalone command in `main.py`; runnable directly via `python -m mcp_server.server --repo-root ...`, or spawned automatically by `run --transport mcp`)* | Infrastructure — exposes the 6 tools `run`'s agent loop can call. Makes no LLM calls itself. |
| 5 | Run (agentic) | `main.py run` | **Agentic** (`agent/orchestrator.py`) — the model is given 3 of the 6 tools (the other 3 are pre-fetched and inlined instead) and drives a multi-turn loop (up to `MAX_TOOL_TURNS`, 4 by default) to propose a fix and self-verify with tests. No offline mode; requires a key. Tool execution crosses a real MCP stdio transport with `--transport mcp`, or dispatches in-process (default) — see the "Run" section below. |
| — | Eval | `main.py eval` | Deterministic — compares `scan` output (Phase 1) to a planted ground truth, no LLM involved. |

Everything below the "Scan" row of the table is what produced the finding
table you've been looking at. The rest (Score/Run) is documented at the
bottom for completeness, since you'll hit it next.

## Scan: detection rules (all in `analyzers/`)

### `high_complexity` — `analyzers/complexity.py`
- Uses `radon`'s cyclomatic-complexity counter if installed; otherwise a
  built-in AST-based counter (same formula, no external dependency).
- **Rule**: complexity = `1 + number of decision points` in the function
  body. Decision points counted: `if`, `for`, `while`, `try`/`except`,
  `with`, comprehensions, and each extra operand in a boolean `and`/`or`
  chain.
- **Threshold**: flagged if `complexity > 10`.

### `long_function` — `analyzers/long_function.py`
- Pure AST, no external dependency.
- **Rule**: `length = end_lineno - lineno + 1` for every `def`/`async def`.
- **Threshold**: flagged if `length > 50` lines.

### `dead_code` — `analyzers/dead_code.py`
- Pure AST + regex text search, no external dependency.
- **Rule**: collects every module-level function/class name (skips names
  starting with `_`, `main`, and anything decorated with
  `@fixture`/`@app`/`@command`/`@route`/`@task`). For each name, regex
  word-boundary searches every other line in every other file in the repo
  (and the rest of its own file, outside its own definition).
- **Threshold**: flagged if the name is referenced **zero** times anywhere
  else in the repo.
- **Known limitation**: this is purely textual — it can't see that a
  function is an intended entry point called from outside the scanned
  repo (e.g. a CLI, another project, `__main__`), so those get flagged
  too. That's a deliberate simplicity trade-off, not a bug.

### `missing_tests` — `analyzers/missing_tests.py`
- Pure AST + naming convention, no external dependency.
- **Rule**: for each public top-level function/class in a module, looks
  for a conventionally named test file: `test_<module>.py` or
  `<module>_test.py` next to the source file, or `tests/test_<module>.py`
  at the repo root. If found, checks whether the symbol's name appears
  anywhere in that test file's text.
- **Threshold**: flagged if no test file exists at all ("No test file
  found"), or a test file exists but never mentions the symbol's name
  ("Test file exists but does not appear to reference").
- **Known limitation**: text-only — it can't see indirect coverage
  (e.g. tested only through another function that calls it), so this
  analyzer deliberately over-flags. Precision is expected to be low here;
  the impact/effort scorer is meant to demote false positives using
  broader context (fan-in, churn).

### `duplication` — `analyzers/duplication.py`
- Prefers shelling out to `jscpd` (`npm i -g jscpd`), polyglot (Python +
  JS/TS). **Rule** (jscpd path): token-based copy-paste detection,
  `--min-lines 5 --min-tokens 50`.
- If `jscpd` isn't on `PATH`, this does **not** just return zero findings —
  there's a dependency-free AST fallback for the Python-only case
  (`_fallback_python_duplication`): every function body (≥`MIN_LINES`, 5
  lines, same floor as jscpd's) gets hashed into a structural signature —
  statement/expression node types + literal values, with `Name`/`arg`
  identifiers mapped to positional placeholders (`V0`, `V1`, ...) so a
  simple rename doesn't defeat the match. Two functions whose signatures
  collide are reported as structurally identical (a type-2 clone), each
  pointing at one other member of its group. This deliberately does **not**
  do jscpd's token-window/percentage-overlap analysis (partial duplication
  inside a larger function) — only whole-function clones — so recall is
  lower without `jscpd`, but it is not 0 by design; e.g. `eval/sample_repo`
  currently trips 2 real duplication true positives via this fallback with
  no `jscpd` installed. JS/TS duplication still needs `jscpd` — the fallback
  is Python-only.

### `long_parameter_list` — `analyzers/long_parameter_list.py`
- Pure AST, no external dependency.
- **Rule**: for every `def`/`async def`, declared parameter count =
  `len(posonlyargs) + len(args) + len(kwonlyargs)`. The implicit first
  parameter is excluded from the count when it's named `self` or `cls`,
  so instance/class methods aren't penalised for it. `*args`/`**kwargs`
  are never counted.
- **Threshold**: flagged if the counted parameters `> 5` (i.e. 6+).

### `missing_docstring` — `analyzers/missing_docstring.py`
- Pure AST, no external dependency.
- **Rule**: `ast.get_docstring(node) is None or .strip()` is empty (a
  whitespace-only docstring counts as missing). Checked on the module
  itself, and on every `ClassDef`/`FunctionDef`/`AsyncFunctionDef`
  (including nested ones, e.g. methods and closures) whose name doesn't
  start with `_` — which also skips every dunder (`__init__`, `__str__`, …)
  automatically.
- **Threshold**: flagged if a public in-scope symbol has no non-empty
  docstring.
- **Known limitation**: presence-only, deliberately — it never judges
  docstring *quality*, only whether one exists.

### `unused_import` / `unused_variable` — `analyzers/unused_code.py`
- Shells out to `ruff check --select F401,F841 --output-format json`.
  Deliberately doesn't hand-roll AST scope analysis — local-variable
  liveness with closures, comprehensions, augmented assignment, and
  `__all__` re-exports is exactly the edge-case swamp `ruff` already
  handles correctly (same "don't reinvent grep" reasoning as `dead_code`'s
  plain-text approach).
- **Rule**: `F401` (import never used anywhere in its file) →
  `unused_import`; `F841` (local variable assigned but never read) →
  `unused_variable`. The `symbol` field is parsed out of ruff's own
  message text (the backtick-quoted identifier), since ruff's JSON
  doesn't expose it as a separate structured field.
- If `ruff` isn't on `PATH`, this analyzer returns zero findings rather than
  failing — recall for both types is genuinely 0 until it's installed.
  Unlike `duplication`, there's no dependency-free fallback here: ruff's
  scope analysis (closures, comprehensions, augmented assignment, `__all__`
  re-exports) is exactly the edge-case swamp not worth hand-rolling (see the
  "Deliberately doesn't hand-roll" note above).
- **No double-reporting**: `dead_code` covers unused top-level
  functions/classes; this analyzer covers imports and local variables —
  they don't overlap by construction.

### `magic_number` — `analyzers/magic_numbers.py`
- Pure AST, no external dependency.
- **Rule**: walks numeric literals (`int`/`float` `Constant` nodes; string
  literals are never flagged — that would catch every log message and
  dict key). Two AST gotchas handled explicitly: `bool` is a subclass of
  `int` in Python, so booleans are excluded; and a negative literal like
  `-1` parses as `UnaryOp(USub, Constant(1))`, not `Constant(-1)`, so the
  signed value is normalised before the allowlist check.
- **Allowlist** (never flagged): `{-1, 0, 1, 2}`.
- **Skipped contexts**: the literal is the direct right-hand side of an
  assignment to a `Name` target (e.g. `TIMEOUT = 30` — that assignment
  *is* the fix, not the smell); a default value in a function signature
  (`def f(x=30)`); or the file is a test file (`test_*.py`, `*_test.py`,
  or under a `tests/` directory).
- **Threshold**: flagged if a numeric literal survives every skip above.
- **Known limitation**: heuristic — precision depends entirely on the
  allowlist/skip rules. Measured eval precision for this type is lower
  than the other new analyzers (`0.33`, see `eval/ground_truth.json`) for
  an instructive reason: `eval/sample_repo/src/orders.py` and
  `pricing.py` predate this analyzer and are full of genuine (if
  unplanted) inline literals (`0.95`, `500`, `25`, …) — same documented
  pattern as `dead_code`'s `format_price` false positive. This wasn't
  retrofitted away; it's left as an honest demonstration of what
  "retrofitting a new lint rule onto an existing codebase" actually looks
  like. The impact/effort scorer is expected to demote low-value hits.

### Churn (not a finding type, a scoring signal) — `analyzers/churn.py`
- `git log --name-only` commit counts per file, via subprocess. Returns
  `{}` if there's no `.git` directory or `git` isn't on `PATH`. Feeds
  `agent/scoring.py`'s impact estimate (frequently-changed + already-flagged
  code is classic high-impact debt) — it doesn't produce findings itself.

## Score: how impact/effort is decided

### LLM mode (default, if `MISTRAL_API_KEY`/`LLM_API_KEY` is set)
`agent/scoring.py` batches up to 10 findings per call, sends each finding's
type/description/metric plus its fan-in, git-commit count, and a retrieved
coding-standard snippet, and asks the model for `impact` (1-5), `effort`
(1-5), and a one-sentence justification per finding, as strict JSON.

**Reproducibility caveat**: each batch is scored independently, and the
model conditions on all ≤10 findings in that same JSON payload -- so batch
*composition* is a hidden variable. Which findings land in the same batch
as a given finding depends on scan order and the total finding count, both
of which can shift between runs (a new finding anywhere earlier in the
list reshuffles every batch boundary after it). That means a finding's
LLM-mode score can change from one run to the next even at temperature 0,
without anything about that finding itself changing. This does **not**
affect detection reproducibility: `main.py eval` grades `scan` output only
(Phase 1, 100% deterministic, see above), never LLM-mode scores. The
**offline heuristic mode below is the reproducible baseline** for
scoring -- same inputs always produce the same impact/effort/justification,
by construction.

### Offline heuristic mode (no key set, or a call fails)
Fully deterministic, in `agent/scoring.py`'s `_heuristic_score()`. As of
this scorer, `justification` is a formatted trace of exactly which rules
below fired -- not just the two raw numbers -- so this path renders the
same as the LLM path in `agent/roadmap.py` (e.g. `"impact 3 (fan-in 4 ≥ 2;
5 commits ≥ 3); effort 1 (mechanical type)"`):

- **Impact** starts at `2`, then:
  - `+1` if fan-in (other files referencing this file) `>= 2`
  - `+1` if commit count `>= 3`
  - `+1` if type is `high_complexity` and `complexity > 20`
  - `-1` if type is `missing_tests` and fan-in `== 0` (demotes the analyzer's
    known over-flagging)
  - clamped to `[1, 5]`
- **Effort** starts at `2`, then:
  - `+1` if type is `high_complexity`
  - `+1` if type is `duplication`
  - `+1` if the finding's line count `> 100`
  - forced to `1` if type is `missing_docstring`, `unused_import`,
    `unused_variable`, or `magic_number` — these fixes are near-mechanical
    (delete the line, or generate/extract one), overriding the bumps above
  - clamped to `[1, 5]`
- Ranked by `impact / effort` ratio for the roadmap tiers (Do now / Plan /
  Backlog, at ratio thresholds 2.0 and 1.0 — see `agent/roadmap.py`).

## Run: how fixes are proposed (always LLM, no offline mode)
`agent/orchestrator.py` pre-fetches the finding, its code snippet, and its
coding standards (all deterministic lookups) and inlines them into the
model's first message, then offers it 3 live tools --  `search_codebase`,
`propose_fix`, `run_tests` -- in a loop, up to `MAX_TOOL_TURNS` turns
(4 by default, overridable via that env var), until it self-reports
resolved/unresolved. (The other 3 tools -- `read_finding`,
`read_file_snippet`, `get_standards` -- are still exposed by the MCP server
for protocol compatibility / external clients; the orchestrator's own loop
just doesn't spend a turn calling them itself, since it already inlined
their results.)

`agent/fixgen.py` generates the fix: the model does **not** hand-author diff
text. It returns a structured `{"edits": [{"old_str", "new_str"}]}` --
`old_str` must be an exact, verbatim substring of the source it was shown --
and the unified diff is built deterministically from that with
`difflib.unified_diff()`, which gets hunk headers and context right by
construction. Nothing here is rule-based in terms of *what* to change --
that's entirely the model's judgment -- but *how the diff text is produced*
is deterministic once the model picks its edit. The result is verified
afterward by actually running the test suite against the proposed patch in
a throwaway copy of the repo.

### Tool-execution transport: `--transport {in-process,mcp}`
The model side is identical either way (same 6 tools, same turn budget) --
only how a chosen tool call is *executed* changes:

- **`in-process`** (default): `agent/orchestrator.py::_execute_tool()` calls
  `mcp_server/tools.py`'s functions directly. No subprocess, no protocol.
- **`mcp`**: spawns `python -m mcp_server.server --repo-root <repo>` and
  calls the same 6 tools over a real MCP stdio session (official `mcp` SDK
  client). Verified live: server-side log lines per call, real per-tool
  latency (`agent/orchestrator.py::_print_latency_summary`), and identical
  resolution behavior to the in-process path on the same finding. Session
  setup (spawn + initialize + a tool-schema sanity check) is wrapped in a
  try/except; if that fails, the whole run falls back to in-process and
  prints which transport actually served it -- e.g.
  `[transport] MCP stdio session active (6 tools)` or
  `[transport] MCP unavailable (...), falling back to in-process dispatch`.

Two bugs surfaced and were fixed while wiring this up, both worth knowing
if you extend either transport further:
- `agent/fixgen.py::apply_and_verify()`'s nested subprocess calls (`git
  apply`, `pytest`) didn't redirect `stdin`. Under the `mcp` transport,
  that subprocess inherits the MCP server's own stdin -- the same pipe
  carrying the JSON-RPC protocol -- and could deadlock waiting on it.
  Fixed with `stdin=subprocess.DEVNULL` on both calls.
- `StdioServerParameters` (used to spawn the `mcp`-transport server)
  defaults to a minimal environment (PATH, TEMP, etc.), not the parent
  process's -- so the spawned server had no LLM API key and every
  server-side `propose_fix` call failed. Fixed by passing
  `env=dict(os.environ)` explicitly.

**Not yet true for either transport**: fix *resolution* quality (a clean
"✅ tests pass" outcome) is bounded by the underlying model's judgment, not
by which transport delivered the tool call -- confirmed by reproducing the
identical failure mode on both transports against the same finding.

This surfaced a real failure mode during development, since fixed at the
root rather than patched around: Groq's `llama-3.1-8b-instant` (the default
model at the time, when the model was asked to hand-author unified diff
text directly) had a tendency to echo `read_file_snippet`'s `NNN| `
line-number formatting into its diff output instead of proper unified-diff
syntax, which `git apply` then rejected. The fix was two-part: (1)
`read_file_snippet` now shows the fix-generation prompt unprefixed source
(`numbered=False` -- see `mcp_server/tools.py`), so there are no line
numbers to echo in the first place, and (2) the model no longer writes diff
syntax at all -- see `agent/fixgen.py`'s module docstring for the structured
`{"edits": [{"old_str", "new_str"}]}` approach, where the diff is built
deterministically by `difflib.unified_diff()` instead. Whether this fully
closes the failure mode on Mistral's models specifically hasn't been
rigorously re-benchmarked (see `ONBOARDING.md`'s "what still needs work").
