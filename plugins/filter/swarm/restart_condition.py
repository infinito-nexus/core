"""Filter `swarm_restart_condition`: map a compose-style
``docker_restart_policy`` to swarm's ``deploy.restart_policy.condition``.

`docker stack deploy` does NOT understand compose's `restart:` keys
(`no`, `always`, `unless-stopped`, `on-failure[:N]`). It uses a
disjoint set of `condition:` values: `none`, `on-failure`, `any`.
Translating between the two used to be inline Jinja in
``roles/sys-svc-container/templates/deploy.yml.j2`` -- this filter
pulls it out so the call site reads as a single expression and is
unit-testable.

MAPPING
=======

    compose ``docker_restart_policy`` -> swarm ``condition``
    ----------------------------------------------------------
    ``'no'``                          -> ``'none'``
        One-shot containers (matomo bootstrap, erpnext configurator,
        shopware init). They exit 0 and must never be respawned.
    ``'on-failure'`` or ``'on-failure:N'`` -> ``'on-failure'``
        Respawn only on non-zero exit. Swarm has no separate
        max-restarts knob on the condition itself; the ``:N`` suffix
        is dropped because swarm carries the same idea via
        ``restart_policy.max_attempts``.
    ``'always'`` / ``'unless-stopped'`` -> ``'any'``
        Long-running services -- the historical default of this
        deploy template.
    anything else (None, empty, typo) -> ``'any'``
        Safe default: long-running services are the most common case
        and a typo in a role's `docker_restart_policy` would
        otherwise silently produce ``none``, which would skip
        respawning real services and look like a deploy success.
"""

from __future__ import annotations

from typing import Any

_VALID_SWARM_CONDITIONS = frozenset({"none", "on-failure", "any"})


def swarm_restart_condition(value: Any) -> str:
    """Translate *value* (a compose-style ``docker_restart_policy``)
    to its swarm ``deploy.restart_policy.condition`` equivalent."""
    raw = "" if value is None else str(value).strip()
    if raw == "no":
        return "none"
    if raw == "on-failure" or raw.startswith("on-failure:"):
        return "on-failure"
    return "any"


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {
            "swarm_restart_condition": swarm_restart_condition,
        }
