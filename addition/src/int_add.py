"""Integer addition utilities with overflow handling."""

INT32_MAX = 2 ** 31 - 1
INT32_MIN = -(2 ** 31)


def add_ints(a, b):
    return a + b


def add_ints_with_overflow_check(a, b, mode="wrap", width=32, signed=True,
                                  on_overflow="raise", clamp_min=None,
                                  clamp_max=None, log_overflow=False):
    result = a + b

    if width == 8:
        max_val = 127 if signed else 255
        min_val = -128 if signed else 0
    elif width == 16:
        max_val = 32767 if signed else 65535
        min_val = -32768 if signed else 0
    elif width == 32:
        max_val = INT32_MAX if signed else 2 ** 32 - 1
        min_val = INT32_MIN if signed else 0
    elif width == 64:
        max_val = 2 ** 63 - 1 if signed else 2 ** 64 - 1
        min_val = -(2 ** 63) if signed else 0
    else:
        max_val = INT32_MAX
        min_val = INT32_MIN

    overflowed = result > max_val or result < min_val

    if overflowed:
        if log_overflow:
            print(f"overflow detected: {result}")

        if mode == "wrap":
            span = max_val - min_val + 1
            result = ((result - min_val) % span) + min_val
        elif mode == "saturate":
            if result > max_val:
                result = max_val
            else:
                result = min_val
        elif mode == "clamp":
            lo = clamp_min if clamp_min is not None else min_val
            hi = clamp_max if clamp_max is not None else max_val
            if result < lo:
                result = lo
            elif result > hi:
                result = hi
        elif on_overflow == "raise":
            kind = "signed" if signed else "unsigned"
            raise OverflowError(f"{result} out of range for {width}-bit {kind} int")
        else:
            if result > 0:
                result = max_val
            else:
                result = min_val

    return result


def dead_int_formatter(value):
    return f"[{value}]"
