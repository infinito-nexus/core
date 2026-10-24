from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils import PROJECT_ROOT

# nocheck: lookup-cache-import (this lookup IS the agent-config SPOT accessor)
from utils.cache.yaml import load_yaml

ROLES_DIR = PROJECT_ROOT / "agents" / "roles"


def _merge(base: Any, override: Any) -> Any:
    """Return ``override`` folded onto ``base``: dicts merge key by key, every
    other value (scalar or list) is replaced.

    Args:
        base: the value from the role's files.
        override: the value from the inventory.
    """
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _merge(merged.get(key), value) if key in merged else value
        return merged
    return override


def _config_of(role: str, roles_dir: Path, override: dict) -> dict:
    """Return the role's merged configuration: ``agent.yml`` fields plus a
    ``cron`` key holding the ``cron.yml`` list, with the inventory override
    folded on top.

    Args:
        role: the role directory name.
        roles_dir: the directory the role lives in.
        override: the inventory's ``agents.<role>`` mapping.
    """
    role_dir = roles_dir / role
    agent_file = role_dir / "agent.yml"
    if not agent_file.is_file():
        raise AnsibleError(
            f"lookup('agent_config', ...): no role '{role}' in {roles_dir}"
        )
    config = dict(load_yaml(agent_file) or {})
    cron_file = role_dir / "cron.yml"
    config["cron"] = load_yaml(cron_file) or [] if cron_file.is_file() else []
    return _merge(config, override or {})


class LookupModule(LookupBase):
    """
    lookup('agent_config', role, path[, default])

    - reads agents/roles/<role>/agent.yml and cron.yml
    - folds the inventory's agents.<role> mapping on top
    - resolves a dotted path into the merged configuration
    - strict (missing path raises) unless a third term gives a default
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) not in (2, 3):
            raise AnsibleError(
                "lookup('agent_config', role, path[, default]) expects 2 or 3 terms."
            )
        role, path = terms[0], terms[1]
        default_provided = len(terms) == 3
        variables = variables or {}
        roles_dir = Path(kwargs["roles_dir"]) if kwargs.get("roles_dir") else ROLES_DIR
        override = ((variables.get("agents") or {}).get(role)) or {}

        config = _config_of(role, roles_dir, override)

        value: Any = config
        for part in str(path).split("."):
            if not isinstance(value, dict) or part not in value:
                if default_provided:
                    return [terms[2]]
                raise AnsibleError(
                    f"lookup('agent_config', '{role}', '{path}'): missing key '{part}'."
                )
            value = value[part]
        return [value]
