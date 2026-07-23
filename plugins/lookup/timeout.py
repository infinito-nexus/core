"""Scale a base timeout (seconds) by the global ``TIMEOUT_FACTOR``.

Replaces a bare ``timeout: <seconds>`` task keyword or module argument so every
wait in the codebase scales from one knob: set ``TIMEOUT_FACTOR: 2`` in
group_vars on a slow uplink and every timeout doubles.

    timeout: "{{ lookup('timeout', 3600) | int }}"
    timeout: "{{ lookup('timeout', some_base_var) | int }}"

``TIMEOUT_FACTOR`` is read from the play variables and defaults to 1 (no
scaling) when unset, so the lookup is a value-identical drop-in for the
literal. An explicit ``factor=`` keyword overrides the global for one call.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

DEFAULT_TIMEOUT_FACTOR = 1


def scaled_timeout(base: Any, factor: Any = DEFAULT_TIMEOUT_FACTOR) -> int:
    """Return ``round(base * factor)`` as an int.

    Args:
        base: Base timeout in seconds (number or numeric string, >= 0).
        factor: Multiplier (number or numeric string, >= 0); TIMEOUT_FACTOR.

    Raises:
        AnsibleError: base or factor is non-numeric or negative.
    """
    try:
        base_val = float(base)
    except (TypeError, ValueError) as exc:
        raise AnsibleError(
            f"lookup('timeout', <base>): base {base!r} is not a number"
        ) from exc
    try:
        factor_val = float(factor)
    except (TypeError, ValueError) as exc:
        raise AnsibleError(
            f"lookup('timeout'): TIMEOUT_FACTOR {factor!r} is not a number"
        ) from exc
    if base_val < 0:
        raise AnsibleError(f"lookup('timeout', <base>): base {base!r} must be >= 0")
    if factor_val < 0:
        raise AnsibleError(f"lookup('timeout'): TIMEOUT_FACTOR {factor!r} must be >= 0")
    return round(base_val * factor_val)


class LookupModule(LookupBase):
    """lookup('timeout', base_seconds[, factor=TIMEOUT_FACTOR])"""

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        terms = terms or []
        if len(terms) != 1:
            raise AnsibleError(
                "lookup('timeout', base_seconds[, factor=]) expects exactly one "
                "positional term (the base timeout in seconds)."
            )
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        factor = kwargs.get("factor")
        if factor is None:
            factor = variables.get("TIMEOUT_FACTOR", DEFAULT_TIMEOUT_FACTOR)
        return [scaled_timeout(terms[0], factor)]
