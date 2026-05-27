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
    # Mirror Ansible's `bool` filter coercion exactly so this is a
    # drop-in for the existing `| bool | ternary('on', 'off')`
    # idiom: every Ansible-truthy value renders "on", everything
    # else "off".
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
    # Unknown string: be strict. Templates should not pass arbitrary
    # strings through this filter.
    raise ValueError(
        f"on_off: cannot coerce {value!r} to on/off; expected a bool-like value."
    )


class FilterModule:
    def filters(self):
        return {
            "on_off": on_off,
        }
