"""
eval/sample_repo/src/reporting_utils.py

Planted debt for unused_import and unused_variable (ruff F401/F841 --
see eval/ground_truth.json). Requires `pip install ruff`; recall is 0
without it, per analyzers/unused_code.py's documented degrade-gracefully
behavior.
"""
import os  # planted unused_import positive: never used in this file
import json  # negative: used only inside a function -- confirms ruff's scope analysis


def dump_debug_info(data):
    """Serialize data for a debug log line."""
    return json.dumps(data)


def compute_summary(values):
    """Return the sum of values."""
    total = sum(values)
    unused_local = total * 2  # planted unused_variable positive: never used again
    return total


def make_counter():
    """Return a closure-based counter's increment function.

    Planted unused_variable negative: `count` is read/written through the
    closure, not a naive unused local -- confirms we deferred to ruff's
    scope analysis rather than a naive text search.
    """
    count = 0

    def increment():
        """Advance and return the shared counter."""
        nonlocal count
        count += 1
        return count

    return increment
