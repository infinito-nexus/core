from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.plugins.lookup import LookupBase

from plugins.lookup import PROJECT_ROOT
from utils.mail.provider import (
    configured_provider,
    deployed_roles,
    resolve_active_provider,
)


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None = None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """Resolve the role acting as mail provider for this deploy.

        Args:
            terms: unused.
            variables: Ansible variables of the current host.
            roles_dir: optional roles tree; the repository's when omitted.

        Returns:
            One-element list holding the provider role id.
        """
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        roles_dir = Path(kwargs.get("roles_dir") or PROJECT_ROOT / "roles")
        return [
            resolve_active_provider(
                configured_provider(vars_.get("applications"), roles_dir),
                deployed_roles(vars_.get("groups")),
                roles_dir,
            )
        ]
