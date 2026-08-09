"""
eval/sample_repo/src/rate_limiter.py

Planted debt for magic_number (see eval/ground_truth.json). Covers the
three skip rules (assignment RHS, default arg, allowlist) plus one
genuine inline positive.
"""
import time

TIMEOUT = 3600  # named constant -- NOT the smell, this IS the fix; skipped


def wait_for_slot():
    """Block until the next rate-limit window opens."""
    time.sleep(3600)  # planted magic_number positive: inline, unnamed


def get_last_item(items, offset=10):
    """Return the most recently added item."""
    return items[-1]  # -1 is allow-listed; NOT flagged (10 default arg also skipped)
