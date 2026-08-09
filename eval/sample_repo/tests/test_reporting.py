"""
eval/sample_repo/tests/test_reporting.py

Exercises every public symbol in src/reporting.py so it isn't also
flagged dead_code/missing_tests -- this fixture's planted debt is
long_parameter_list and missing_docstring only.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from reporting import build_report, ReportBuilder, parse_config, Formatter


def test_build_report():
    """build_report bundles its seven fields into a dict."""
    result = build_report(1, 2, 3, 4, 5, 6, 7)
    assert result["g"] == 7


def test_report_builder():
    """ReportBuilder.build returns its five fields as a tuple."""
    assert ReportBuilder().build(1, 2, 3, 4, 5) == (1, 2, 3, 4, 5)


def test_parse_config():
    """parse_config wraps a path in a dict."""
    assert parse_config("a.yaml") == {"path": "a.yaml"}


def test_formatter():
    """Formatter renders a row via its private _render helper."""
    assert Formatter()._render([1, 2]) == "[1, 2]"
