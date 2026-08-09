"""
eval/sample_repo/tests/test_rate_limiter.py

Exercises both public symbols in src/rate_limiter.py so it isn't also
flagged dead_code/missing_tests -- this fixture's planted debt is
magic_number only. time.sleep is mocked so the test suite doesn't
actually block for an hour.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import rate_limiter


def test_wait_for_slot(monkeypatch):
    """wait_for_slot calls time.sleep with the configured timeout."""
    calls = []
    monkeypatch.setattr(rate_limiter.time, "sleep", lambda seconds: calls.append(seconds))
    rate_limiter.wait_for_slot()
    assert calls == [3600]


def test_get_last_item():
    """get_last_item returns the last element of the list."""
    assert rate_limiter.get_last_item([1, 2, 3]) == 3
