"""Lookup `tor_extra_ports`: every port the node onion forwards.

Two of them are flags rather than derivations, because no inventory carries
them. ``lookup('tor_ports')`` walks ``group_names`` and collects what the roles
listed there declare under ``ports.onion``; SSH belongs to no role at all, and
HTTP belongs to ``svc-prx-openresty``, which a node acquires through
``sys-stk-front-proxy`` and which therefore appears in no dependency list an
inventory holds. A node provisioned with ``--include svc-net-tor`` alone
published an onion forwarding SSH and nothing else, leaving every app it serves
unreachable over that onion.

Forwarding HTTP is what this role exists for, so it is declared, and a node that
must not answer HTTP over its onion turns ``TOR_ONION_HTTP_ENABLED`` off.

The derived ports still come from ``tor_ports``; a port named twice collapses,
since ``torrc.j2`` writes one ``HiddenServicePort`` line per entry.

Usage:

    {{ lookup('tor_extra_ports') }}
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import trust_as_template

FLAGGED_PORTS: tuple[tuple[str, int], ...] = (
    ("TOR_ONION_SSH_ENABLED", 22),
    ("TOR_ONION_HTTP_ENABLED", 80),
)


def _flag(templar: Any, name: str, value: Any) -> bool:
    """A declared flag as a boolean, with its Jinja resolved first.

    Args:
        templar: the lookup's templar, or None when it has none.
        name: the variable the flag came from, for the error message.
        value: whatever the variable holds; group vars reach a lookup
            unrendered, so a reference arrives as its own template text.
    """
    if isinstance(value, str) and "{{" in value and templar is not None:
        value = templar.template(trust_as_template(value))
    try:
        return boolean(value)
    except TypeError as exc:
        raise AnsibleError(
            f"lookup('tor_extra_ports'): {name} is not a boolean: {value!r}"
        ) from exc


def _entry(port: int) -> dict[str, Any]:
    """One forward, in the shape ``torrc.j2`` consumes.

    Args:
        port: the port the onion answers on; the backend host is substituted by
            the template, so the target carries the port alone.
    """
    return {"onion_port": port, "target": f"127.0.0.1:{port}"}


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if terms:
            raise AnsibleError("lookup('tor_extra_ports') expects no terms.")

        variables = variables or getattr(self._templar, "available_variables", {}) or {}

        entries: list[dict[str, Any]] = []
        for name, port in FLAGGED_PORTS:
            if name not in variables:
                raise AnsibleError(f"lookup('tor_extra_ports'): {name} is not defined")
            if _flag(getattr(self, "_templar", None), name, variables[name]):
                entries.append(_entry(port))

        derived = lookup_loader.get(
            "tor_ports",
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        ).run([], variables=variables, **kwargs)[0]

        seen = {entry["onion_port"] for entry in entries}
        for entry in derived:
            if entry["onion_port"] in seen:
                continue
            seen.add(entry["onion_port"])
            entries.append(entry)

        return [entries]
