from __future__ import annotations

from collections.abc import Mapping

from ansible.errors import AnsibleFilterError

DEFAULT_KEY = "default"
SELECTORS = ("primary", "canonical", "served")
TRUE_STRINGS = frozenset({"true", "yes", "on", "1"})


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in TRUE_STRINGS
    return bool(value)


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Mapping):
        return [str(item) for item in value.values() if item]
    return [str(item) for item in value if item]


def _selected(selectors, primary, canonical, served) -> list[str]:
    domains: list[str] = []
    for selector in _as_list(selectors):
        if selector not in SELECTORS:
            raise AnsibleFilterError(
                f"stack_vhosts: unknown domains selector {selector!r}, "
                f"expected one of {', '.join(SELECTORS)}"
            )
        if selector == "primary":
            domains.append(primary)
        elif selector == "canonical":
            domains.extend(_as_list(canonical))
        else:
            domains.extend(_as_list(served))
    return domains


def _domains(key, entry, primary, canonical, served) -> list[str]:
    if "domain" in entry:
        return _as_list(entry["domain"])
    if "domains" in entry:
        return _selected(entry["domains"], primary, canonical, served)
    if key == DEFAULT_KEY:
        return [primary]
    if isinstance(canonical, Mapping) and key in canonical:
        return _as_list(canonical[key])
    raise AnsibleFilterError(
        f"stack_vhosts: vhost {key!r} names no canonical domain key, "
        "so it MUST declare 'domain' or 'domains'"
    )


def stack_vhosts(declared, primary, canonical=None, served=None) -> list[dict]:
    """
    Args:
        declared: the consumer's ``server.vhosts`` mapping of a
            ``domains.canonical`` key (or ``default``) to that vhost's
            parameters; empty when the consumer declares none.
        primary: the consumer's primary domain.
        canonical: the consumer's ``domains.canonical`` domains, a mapping
            of key to domain(s) or a list.
        served: the domains the play serves for the consumer beyond its
            canonical ones (``domains.served``).

    Returns:
        One entry per logical domain, in declaration order: the vhost's
        parameters plus ``key`` and ``domain``. A vhost whose ``enabled`` is
        false is left out, and a domain two vhosts name is served once. An
        empty declaration serves the primary domain alone.
    """
    if not declared:
        return [{"key": DEFAULT_KEY, "domain": primary}]
    if not isinstance(declared, Mapping):
        raise AnsibleFilterError(
            f"stack_vhosts: server.vhosts MUST be a mapping, got {type(declared).__name__}"
        )
    resolved: list[dict] = []
    seen: set[str] = set()
    for key, raw in declared.items():
        entry = dict(raw or {})
        if not _truthy(entry.pop("enabled", True)):
            continue
        for domain in _domains(str(key), entry, primary, canonical, served):
            if domain in seen:
                continue
            seen.add(domain)
            params = {
                name: value
                for name, value in entry.items()
                if name not in ("domain", "domains")
            }
            resolved.append({**params, "key": str(key), "domain": domain})
    return resolved


class FilterModule:
    def filters(self):
        return {"stack_vhosts": stack_vhosts}
