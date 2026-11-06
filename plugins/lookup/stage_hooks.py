from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase


def hook_roles(roles_dir: Path, point: str) -> list[str]:
    """Return the roles that ship a hook for one hook point.

    Args:
        roles_dir: the repository's ``roles`` directory.
        point: the hook point name, e.g. ``constructor``.

    Returns:
        Role names with ``tasks/hooks/<point>.yml``, sorted by name.
    """
    return sorted(
        hook.relative_to(roles_dir).parts[0]
        for hook in roles_dir.glob(f"*/tasks/hooks/{point}.yml")
    )


class LookupModule(LookupBase):
    """
    query('stage_hooks', 'constructor') -> roles that ship tasks/hooks/constructor.yml.
    """

    def run(
        self, terms, variables: dict[str, Any] | None = None, **kwargs
    ) -> list[str]:
        if len(terms) != 1:
            raise AnsibleError("lookup('stage_hooks') takes exactly one hook point.")
        base = (variables or {}).get("playbook_dir")
        if not base:
            raise AnsibleError("lookup('stage_hooks'): 'playbook_dir' is unavailable.")
        return hook_roles(Path(str(base)) / "roles", str(terms[0]).strip())
