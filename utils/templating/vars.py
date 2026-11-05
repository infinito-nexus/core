"""Resolve a play variable that may still be a template.

A value taken out of the play's variables is raw. A role whose
``application_id`` is itself a template, as ``sys-stk-full`` sets it from
``sys_stk_full_application_id``, therefore hands back the unrendered string,
while the same variable named inside an expression arrives resolved. Every
lookup that reads such a variable resolves it through here.
"""

from __future__ import annotations

import contextlib
from typing import Any


def resolve_var(templar: Any, value: Any) -> Any:
    """Template ``value`` when a templar is available, else pass it through.

    Args:
        templar: the plugin's templar, or None.
        value: the variable as the play holds it.
    """
    if templar is None or value is None:
        return value
    with contextlib.suppress(Exception):
        return templar.template(value)
    return value
