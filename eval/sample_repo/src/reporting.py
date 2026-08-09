"""
eval/sample_repo/src/reporting.py

Planted debt for long_parameter_list and missing_docstring (see
eval/ground_truth.json). Kept deliberately short/simple so it doesn't
also trip long_function/high_complexity -- those are covered elsewhere.
"""


def build_report(a, b, c, d, e, f, g):
    """Build a report row from seven positional fields.

    Planted long_parameter_list positive: 7 declared parameters > 5.
    """
    return {"a": a, "b": b, "c": c, "d": d, "e": e, "f": f, "g": g}


class ReportBuilder:
    """Builds report rows incrementally."""

    def build(self, a, b, c, d, e):
        """5 declared params excluding `self` -- must NOT be flagged.

        Planted long_parameter_list negative: confirms `self` is excluded
        from the count (6 raw args would exceed the threshold; 5 doesn't).
        """
        return (a, b, c, d, e)


# Planted missing_docstring positive: public function, no docstring.
def parse_config(path):
    return {"path": path}


class Formatter:
    """Formats report rows for display."""

    # Planted missing_docstring negative: leading underscore -> skipped
    # even though it has no docstring either.
    def _render(self, row):
        return str(row)
