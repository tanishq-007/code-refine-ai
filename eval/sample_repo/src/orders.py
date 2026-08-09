"""
eval/sample_repo/src/orders.py

Planted debt (see eval/ground_truth.json):
  - one function here is genuinely unused anywhere in the repo (dead code)
  - `process_order`: long function (>50 lines) AND high cyclomatic complexity
  - has a test file (test_orders.py) but it doesn't cover one of the
    helper functions -> planted missing_tests finding
"""


def legacy_discount_calc(price, tier):
    """Apply the old tiered discount schedule to a price."""
    if tier == "gold":
        return price * 0.8
    elif tier == "silver":
        return price * 0.9
    return price


def apply_shipping_rules(order):
    """Return the shipping method that applies to this order."""
    if order["weight"] > 50:
        return "freight"
    if order["destination"] == "international":
        return "international"
    return "standard"


def process_order(order):
    """Price, discount, and ship a single order, mutating it in place."""
    status = "pending"
    total = 0
    for item in order["items"]:
        if item["qty"] <= 0:
            continue
        line_total = item["price"] * item["qty"]
        if item.get("category") == "electronics":
            if item["price"] > 500:
                line_total *= 0.95
            elif item["price"] > 100:
                line_total *= 0.98
        elif item.get("category") == "clothing":
            if order.get("is_member"):
                line_total *= 0.9
        total += line_total

    if order.get("coupon"):
        if order["coupon"] == "SAVE10":
            total *= 0.9
        elif order["coupon"] == "SAVE20":
            total *= 0.8
        elif order["coupon"] == "FREESHIP":
            order["free_shipping"] = True
        else:
            status = "invalid_coupon"

    if order.get("is_member"):
        total *= 0.95

    shipping = apply_shipping_rules(order)
    if shipping == "freight":
        total += 25
    elif shipping == "international":
        total += 40
    else:
        if total < 50:
            total += 5

    if total < 0:
        total = 0
        status = "error"
    elif status != "invalid_coupon":
        status = "confirmed"

    order["total"] = round(total, 2)
    order["status"] = status
    order["shipping_method"] = shipping

    if status == "confirmed":
        for item in order["items"]:
            item["fulfilled"] = True

    return order
