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
