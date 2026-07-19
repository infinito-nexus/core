"""Lookup `depends_on`: emit a mode-aware ``depends_on:`` block.

Compose accepts the long form ``<svc>: { condition: service_X }`` and
``docker stack deploy`` rejects it with *Additional property condition
is not allowed*. The two modes therefore need different YAML shapes:

* compose -> map form with explicit ``condition:`` per entry
* swarm   -> list form (just service names; swarm ignores depends_on
  ordering semantically but accepts the syntax)

Hand-writing the ``{% if DEPLOYMENT_MODE == 'swarm' %} … {% else %} …
{% endif %}`` per service is repetitive and easy to get wrong (forgot
gate, wrong condition default, inconsistent indent). This lookup
emits the whole block and switches on ``DEPLOYMENT_MODE`` itself.

USAGE

    # One dependency with an explicit condition.
    {{ lookup('depends_on', {ERPNEXT_CONFIGURATOR_CONTAINER:
        'service_completed_successfully'}) }}

    # Multiple dependencies, mixed conditions.
    {{ lookup('depends_on', {DB_CONTAINER: 'service_healthy',
                              INIT_CONTAINER: 'service_completed_successfully'}) }}

    # Multiple dependencies, all defaulting to ``service_started``
    # (the Docker Compose default when no condition is given).
    {{ lookup('depends_on', [SVC_A, SVC_B]) }}

    # Mix: dict value ``None`` means "use the default condition".
    {{ lookup('depends_on', {SVC_A: 'service_healthy', SVC_B: None}) }}

KWARGS

    indent (int, default 4)
        Number of spaces every line BUT the first one is prefixed with.
        The first line has NO leading whitespace - the caller places
        ``{{ lookup('depends_on', …) }}`` at the desired column in the
        template, and Jinja substitution turns that template-side
        leading whitespace into line 1's indent. Lines 2+ then carry
        ``indent`` extra spaces (on top of the YAML-relative indent)
        so they align under line 1.

        Concretely: writing ``    {{ lookup('depends_on', {…}) }}``
        (call placed at column 4 in the template) with the default
        ``indent=4`` renders as::

            <prev line>
                depends_on:
                  db:
                    condition: service_healthy
            <next line>

        ``indent=0`` collapses everything to the left edge - useful
        when the lookup is rendered into top-level YAML (no service
        wrapper).

    default_condition (str, default ``service_started``)
        Condition used for entries whose value is ``None`` (dict) or
        for plain-name entries in a list term.

    mode (str, optional)
        Override ``DEPLOYMENT_MODE`` (used by unit tests). When
        unset, the lookup reads ``DEPLOYMENT_MODE`` from the templar
        variables. An unknown value falls back to compose.

EMPTY INPUT

An empty mapping or list returns the empty string so the surrounding
template stays valid YAML (no orphan ``depends_on:`` keyword).
"""

from __future__ import annotations

import contextlib
import textwrap
from collections.abc import Mapping, Sequence
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache.yaml import dump_yaml_str

_DEFAULT_CONDITION = "service_started"
_VALID_CONDITIONS = frozenset(
    {"service_started", "service_healthy", "service_completed_successfully"}
)


def _normalise_entries(raw: Any, default_condition: str) -> dict[str, str]:
    """Turn the user-facing term into ``{service_name: condition}``.

    Accepts a ``Mapping`` (``None`` values mean "use default") or a
    non-string ``Sequence`` of plain service names.
    """
    if raw is None:
        return {}

    if isinstance(raw, Mapping):
        out: dict[str, str] = {}
        for name, condition in raw.items():
            key = str(name).strip()
            if not key:
                raise AnsibleError(
                    "depends_on: dependency name must be a non-empty string"
                )
            if condition is None or (
                isinstance(condition, str) and not condition.strip()
            ):
                out[key] = default_condition
            else:
                out[key] = str(condition).strip()
        return out

    if isinstance(raw, str):
        raise AnsibleError(
            "depends_on: expected a mapping or list of service names; "
            "got a single string. Wrap it in a list."
        )

    if isinstance(raw, Sequence):
        out = {}
        for name in raw:
            key = str(name).strip()
            if not key:
                raise AnsibleError(
                    "depends_on: dependency name must be a non-empty string"
                )
            out[key] = default_condition
        return out

    raise AnsibleError(
        "depends_on: first term must be a mapping {name: condition_or_None} "
        f"or a list of service names; got {type(raw).__name__}"
    )


def _validate_conditions(entries: dict[str, str]) -> None:
    bad = [
        (name, cond) for name, cond in entries.items() if cond not in _VALID_CONDITIONS
    ]
    if bad:
        bad_str = ", ".join(f"{name}={cond!r}" for name, cond in bad)
        raise AnsibleError(
            f"depends_on: invalid condition(s): {bad_str}. "
            f"Allowed: {sorted(_VALID_CONDITIONS)}."
        )


def _resolve_mode(variables: dict[str, Any], templar: Any, override: str | None) -> str:
    if override is not None:
        return str(override).strip()
    raw = variables.get("DEPLOYMENT_MODE", "compose")
    if templar is not None:
        with contextlib.suppress(Exception):
            raw = templar.template(raw)
    return str(raw).strip()


def _render(entries: dict[str, str], mode: str, indent: int) -> str:
    if not entries:
        return ""

    if mode == "swarm":
        payload: dict[str, object] = {"depends_on": list(entries.keys())}
    else:
        payload = {
            "depends_on": {name: {"condition": cond} for name, cond in entries.items()}
        }
    body = dump_yaml_str(payload).rstrip()
    lines = body.splitlines()
    if indent <= 0 or len(lines) <= 1:
        return body
    # Line 1 stays unindented so the caller can place
    # `{{ lookup('depends_on', …) }}` at their preferred template
    # column and the surrounding leading whitespace becomes the line-1
    # indent at render time. Jinja does not propagate that leading
    # whitespace to continuation lines, so we bake it into lines 2+
    # ourselves.
    return lines[0] + "\n" + textwrap.indent("\n".join(lines[1:]), " " * indent)


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "depends_on: expected exactly 1 positional term "
                "(mapping or list of service names)"
            )

        default_condition = str(
            kwargs.get("default_condition", _DEFAULT_CONDITION)
        ).strip()
        if default_condition not in _VALID_CONDITIONS:
            raise AnsibleError(
                f"depends_on: default_condition={default_condition!r} is not a "
                f"valid compose condition. Allowed: {sorted(_VALID_CONDITIONS)}."
            )

        try:
            indent = int(kwargs.get("indent", 4))
        except (TypeError, ValueError) as exc:
            raise AnsibleError(f"depends_on: indent must be an int: {exc}") from exc

        entries = _normalise_entries(terms[0], default_condition=default_condition)
        _validate_conditions(entries)

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)
        mode = _resolve_mode(vars_, templar, override=kwargs.get("mode"))

        return [_render(entries, mode, indent)]
