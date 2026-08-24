#
# `on_off` filter — render a boolean as the literal string "on" or
# "off". Replaces the verbose Jinja idiom
#
#     {{ x | bool | ternary('on', 'off') }}
#
# that nginx, msmtp, unbound, etc. need for their config syntax.
#
from __future__ import annotations


def on_off(value):
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (int, float)):
        return "on" if value else "off"
    if value is None:
        return "off"
    s = str(value).strip().lower()
    if s in ("true", "yes", "on", "1", "y", "t"):
        return "on"
    if s in ("false", "no", "off", "0", "n", "f", ""):
        return "off"
    raise ValueError(
        f"on_off: cannot coerce {value!r} to on/off; expected a bool-like value."
    )


class FilterModule:
    def filters(self):
        return {
            "on_off": on_off,
        }
