"""Resolve the role acting as mail provider for this deploy.

Usage:
  {{ lookup('mail_provider') }}

See :mod:`utils.mail.provider` for why this is not simply ``MAIL_PROVIDER``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.plugins.lookup import LookupBase

from utils.mail.provider import deployed_roles, resolve_active_provider

DEFAULT_MAIL_PROVIDER = "web-app-stalwart"


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None = None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        configured = (
            str(vars_.get("MAIL_PROVIDER") or "").strip() or DEFAULT_MAIL_PROVIDER
        )
        roles_dir = Path(kwargs.get("roles_dir") or Path.cwd() / "roles")
        return [
            resolve_active_provider(
                configured, deployed_roles(vars_.get("groups")), roles_dir
            )
        ]
