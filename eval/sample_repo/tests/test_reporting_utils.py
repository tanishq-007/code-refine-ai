"""
eval/sample_repo/tests/test_reporting_utils.py

Exercises every public symbol in src/reporting_utils.py so it isn't also
flagged dead_code/missing_tests -- this fixture's planted debt is
unused_import and unused_variable only.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from reporting_utils import dump_debug_info, compute_summary, make_counter


def test_dump_debug_info():
    """dump_debug_info serializes a dict to a JSON string."""
    assert dump_debug_info({"a": 1}) == '{"a": 1}'


def test_compute_summary():
    """compute_summary returns the sum of its inputs."""
    assert compute_summary([1, 2, 3]) == 6


def test_make_counter():
    """make_counter's closure increments across calls."""
    increment = make_counter()
    assert increment() == 1
    assert increment() == 2
