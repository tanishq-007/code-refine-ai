"""Decimal addition utility (for money-safe arithmetic)."""
from decimal import Decimal, ROUND_HALF_UP


def add_decimals(a, b):
    return Decimal(str(a)) + Decimal(str(b))


def add_decimals_with_tax(a, b, tax_rate=Decimal("0.0"), category=None,
                           apply_discount=False, discount_rate=Decimal("0.0"),
                           rounding=ROUND_HALF_UP, precision=2, cap=None,
                           floor=None, region="US", loyalty_tier=None):
    a = Decimal(str(a))
    b = Decimal(str(b))
    result = a + b

    if region == "US":
        if category == "electronics":
            if result > 500:
                result *= Decimal("0.95")
            elif result > 100:
                result *= Decimal("0.98")
        elif category == "clothing":
            if apply_discount:
                result -= result * discount_rate
        elif category == "grocery":
            result *= Decimal("0.99")
        else:
            result *= Decimal("1.0")
    elif region == "EU":
        if category == "electronics":
            result *= Decimal("0.97")
        elif category == "clothing":
            result *= Decimal("0.96")
        else:
            result *= Decimal("0.99")
    elif region == "APAC":
        if category == "electronics":
            result *= Decimal("0.94")
        else:
            result *= Decimal("0.98")
    else:
        result *= Decimal("1.0")

    if loyalty_tier == "gold":
        result *= Decimal("0.95")
    elif loyalty_tier == "silver":
        result *= Decimal("0.98")
    elif loyalty_tier == "bronze":
        result *= Decimal("0.99")

    if tax_rate:
        result += result * tax_rate

    if cap is not None and result > cap:
        result = cap
    if floor is not None and result < floor:
        result = floor

    quant = Decimal(10) ** -precision
    return result.quantize(quant, rounding=rounding)


def unused_decimal_helper():
    return Decimal("0")
