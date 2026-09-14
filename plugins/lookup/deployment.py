from __future__ import annotations

from typing import Any

from ansible.plugins.lookup import LookupBase

from utils.roles.validation.invokable import list_invokable_app_ids

_STATUS_CACHE: dict[tuple, dict[str, list[str]]] = {}

_EPHEMERAL_RUNTIMES = frozenset({"act", "github"})

_IMPLICIT_GROUPS = frozenset({"all", "ungrouped"})


def _reset_cache_for_tests() -> None:
    _STATUS_CACHE.clear()


def _coerce_to_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [str(item) for item in raw]


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, list[str]]]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        whitelist = _coerce_to_list(vars_.get("APPLICATIONS_WHITELIST"))
        groups = _coerce_to_list(vars_.get("group_names"))
        inventory = sorted(
            name
            for name, hosts in (vars_.get("groups") or {}).items()
            if hosts and name not in _IMPLICIT_GROUPS
        )
        runtime = str(vars_.get("RUNTIME", "")).strip().lower()
        key = (tuple(whitelist), tuple(groups), tuple(inventory), runtime)

        cached = _STATUS_CACHE.get(key)
        if cached is not None:
            return [cached]

        running = whitelist or groups
        deployed = list(running) if runtime in _EPHEMERAL_RUNTIMES else list(groups)
        result = {
            "whitelist": whitelist,
            "running": list(running),
            "groups": groups,
            "inventory": inventory,
            "deployed": deployed,
            "runtime": runtime,
            "all": list(list_invokable_app_ids()),
        }
        _STATUS_CACHE[key] = result
        return [result]
