"""
rag/standards.py

The coding-standards corpus: one guidance paragraph per finding type.
rag/index.py builds a local TF-IDF retrieval index over these (used by
rag/retrieval.py::get_standards); lookup() below is also used directly as
a last-resort fallback if a query somehow shares no vocabulary with any
document at all.
"""

STATIC_STANDARDS = {
    "high_complexity": (
        "Prefer early returns/guard clauses over nested conditionals. "
        "Extract branches with 3+ nesting levels into named helper functions. "
        "Cyclomatic complexity above 10 should be split by responsibility, "
        "not just by line count."
    ),
    "long_function": (
        "A function should do one thing. Split by extracting cohesive blocks "
        "(setup / core logic / teardown) into named helpers. Prefer "
        "composition over one long procedural script."
    ),
    "duplication": (
        "Duplicated logic should be extracted into a shared function/module. "
        "If the duplication is only superficially similar (different domain "
        "concepts that happen to look alike), leave it -- premature "
        "abstraction is worse than duplication."
    ),
    "missing_tests": (
        "Public functions and classes should have at least one test "
        "exercising their primary contract and one edge case. Prefer "
        "behavior-based test names (test_returns_empty_on_no_input) over "
        "implementation-based ones."
    ),
    "dead_code": (
        "Unreferenced code should be deleted, not commented out -- version "
        "control is the archive. If it's a planned extension point, add a "
        "TODO with a tracking issue instead of leaving inert code."
    ),
    "long_parameter_list": (
        "A function with 6+ parameters is usually doing too much or missing "
        "an abstraction. Group related parameters into a single object, "
        "dataclass, or config, or split the function by responsibility. "
        "Prefer keyword arguments with defaults over positional boolean "
        "flags that silently change behavior."
    ),
    "missing_docstring": (
        "Every public module, class, and function should have a docstring "
        "stating what it does, its parameters/returns when non-obvious, and "
        "any exceptions it raises. Don't restate the signature -- the "
        "docstring should explain intent and behavior a reader can't get "
        "from the name alone."
    ),
    "unused_import": (
        "An unused import is dead weight and can mask what a module "
        "actually depends on. Delete it rather than leaving it 'just in "
        "case' -- re-adding a single import line later costs nothing."
    ),
    "unused_variable": (
        "An assigned-but-never-read local variable usually means dead logic "
        "or a forgotten return/use. Delete it, or if it's intentionally "
        "unused (e.g. unpacking a tuple), prefix it with an underscore (_) "
        "to signal that explicitly."
    ),
    "magic_number": (
        "A bare numeric literal buried in logic hides its own meaning and "
        "invites inconsistent copies of the same value elsewhere. Extract it "
        "into a named constant (UPPER_SNAKE_CASE) declared once near the top "
        "of the module or class, so the intent is documented and the value "
        "has a single source of truth."
    ),
}


def lookup(query: str) -> str:
    q = query.lower()
    for key, guidance in STATIC_STANDARDS.items():
        if key.replace("_", " ") in q or key in q:
            return guidance
    return (
        "General guidance: prefer small, well-named, single-responsibility "
        "functions; keep test coverage close to the code it exercises; "
        "delete rather than comment out dead code."
    )
