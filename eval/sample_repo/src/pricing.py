"""
eval/sample_repo/src/pricing.py

Planted debt: `tier_discount` is a near-duplicate of the tiered discount
function in orders.py (duplication finding -- requires jscpd to detect,
per the project's documented "duplication needs jscpd" caveat).
"""


def tier_discount(price, tier):
    """Apply the tiered discount schedule to a price."""
    if tier == "gold":
        return price * 0.8
    elif tier == "silver":
        return price * 0.9
    return price


def format_price(cents):
    """Format an integer cent amount as a dollar string."""
    return f"${cents / 100:.2f}"
