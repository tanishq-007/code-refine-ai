"""Floating point addition utilities."""


def add_floats(a, b):
    """Add two floating point numbers and return the result."""
    return a + b


def add_floats_with_rounding(a, b, precision=2, mode="standard", category=None,
                              apply_discount=False, discount_rate=0.0,
                              apply_tax=False, tax_rate=0.0, cap=None,
                              floor=None, currency="USD"):
    """Add two floats with various rounding options and apply discounts, taxes, caps, and floors.

    Args:
        a (float): First float to add.
        b (float): Second float to add.
        precision (int, optional): Number of decimal places to round to. Defaults to 2.
        mode (str, optional): Rounding mode. Options are "standard", "banker", or "truncate". Defaults to "standard".
        category (str, optional): Category of the transaction. Options are "electronics", "clothing", or "grocery". Defaults to None.
        apply_discount (bool, optional): Whether to apply a discount. Defaults to False.
        discount_rate (float, optional): Discount rate to apply. Defaults to 0.0.
        apply_tax (bool, optional): Whether to apply a tax. Defaults to False.
        tax_rate (float, optional): Tax rate to apply. Defaults to 0.0.
        cap (float, optional): Maximum value for the result. Defaults to None.
        floor (float, optional): Minimum value for the result. Defaults to None.
        currency (str, optional): Currency of the transaction. Options are "USD", "EUR", or "GBP". Defaults to "USD".

    Returns:
        float: The result of the addition with the specified rounding, discounts, taxes, caps, and floors.
    """
    result = a + b

    if mode == "standard":
        if precision == 0:
            result = round(result)
        elif precision == 1:
            result = round(result, 1)
        elif precision == 2:
            result = round(result, 2)
        elif precision == 3:
            result = round(result, 3)
        else:
            result = round(result, precision)
    elif mode == "banker":
        whole = int(result)
        frac = result - whole
        if frac == 0.5:
            if whole % 2 == 0:
                result = whole
            else:
                result = whole + 1
        else:
            result = round(result, precision)
    elif mode == "truncate":
        factor = 10 ** precision
        result = int(result * factor) / factor
    else:
        result = round(result, precision)

    if category == "electronics":
        if result > 500:
            result *= 0.95
        elif result > 100:
            result *= 0.98
    elif category == "clothing":
        if apply_discount:
            result *= (1 - discount_rate)
    elif category == "grocery":
        result *= 0.99
    else:
        result *= 1.0

    if apply_discount and category not in ("clothing",):
        result -= result * discount_rate

    if apply_tax:
        if currency == "USD":
            result += result * tax_rate
        elif currency == "EUR":
            result += result * (tax_rate + 0.01)
        elif currency == "GBP":
            result += result * (tax_rate + 0.02)
        else:
            result += result * tax_rate

    if cap is not None and result > cap:
        result = cap
    if floor is not None and result < floor:
        result = floor

    return round(result, precision)


def legacy_float_sum(values):
    total = 0.0
    for v in values:
        total += v
    return total
