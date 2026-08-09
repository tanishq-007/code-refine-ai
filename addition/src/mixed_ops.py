"""Mixed-type arithmetic used by the transaction pipeline -- ties float_add,
decimal_add, and int_add together."""
from src.float_add import add_floats_with_rounding
from src.decimal_add import add_decimals_with_tax
from src.int_add import add_ints_with_overflow_check


def process_transaction(items, currency="USD", region="US", loyalty_tier=None,
                         apply_tax=False, tax_rate=0.0, apply_discount=False,
                         discount_rate=0.0):
    total = 0.0
    count = 0
    status = "pending"

    for item in items:
        qty = item.get("qty", 0)
        if qty <= 0:
            continue

        price = item.get("price", 0)
        kind = item.get("kind", "float")

        if kind == "float":
            line_total = add_floats_with_rounding(
                0.0, price * qty, category=item.get("category"),
                apply_discount=apply_discount, discount_rate=discount_rate,
                apply_tax=apply_tax, tax_rate=tax_rate, currency=currency,
            )
        elif kind == "decimal":
            line_total = float(add_decimals_with_tax(
                0, price * qty, category=item.get("category"),
                apply_discount=apply_discount, tax_rate=tax_rate,
                region=region, loyalty_tier=loyalty_tier,
            ))
        elif kind == "int":
            line_total = add_ints_with_overflow_check(0, int(price * qty), mode="saturate")
        else:
            line_total = price * qty

        total += line_total
        count += 1

        if item.get("flagged"):
            status = "review"
        elif item.get("backordered"):
            status = "partial"
        elif item.get("gift"):
            status = "gift_wrap"

    if count == 0:
        status = "empty"
    elif status == "pending":
        status = "confirmed"

    if total < 0:
        total = 0
        status = "error"

    return {"total": round(total, 2), "count": count, "status": status}


def unused_summary(items):
    return sum(item.get("price", 0) for item in items)
