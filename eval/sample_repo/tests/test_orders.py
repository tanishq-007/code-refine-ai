"""
eval/sample_repo/tests/test_orders.py

Covers the main order-processing entrypoint only; two planted-debt
functions in this module are deliberately left without any test
reference here.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from orders import process_order


def test_process_order_basic():
    """process_order confirms a simple in-stock, domestic order."""
    order = {"items": [{"price": 10, "qty": 2, "category": "books"}],
              "weight": 1, "destination": "domestic"}
    result = process_order(order)
    assert result["status"] == "confirmed"
    assert result["total"] > 0
