"""lookup('role_version', 'web-app-cst-<name>')

Args:
    application_id: a custom role the pull placed under ``roles/``.

Returns:
    The version the pull read from ``Cargo.toml``, ``pyproject.toml`` or
    ``package.json`` at the source's pinned commit, or in its local checkout,
    as recorded in the role's pull marker, e.g. ``0.4.3``.
"""

# nocheck: lookup-external-consumer -- called by pulled web-app-cst-* roles

from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.roles.custom import VERSION_MANIFESTS, is_custom, marker_fields


class LookupModule(LookupBase):
    def run(
        self, terms: list[Any], variables: dict[str, Any] | None = None, **kwargs: Any
    ) -> list[str]:
        if len(terms) != 1:
            raise AnsibleError(
                "lookup('role_version', application_id) takes exactly one term"
            )
        application_id = str(terms[0])
        if not is_custom(application_id):
            raise AnsibleError(
                f"lookup('role_version'): {application_id!r} is no custom role; "
                "only a role the pull places records a source version"
            )
        base = (variables or {}).get("playbook_dir")
        if not base:
            raise AnsibleError("lookup('role_version'): 'playbook_dir' is unavailable.")
        fields = marker_fields(Path(str(base)) / "roles" / application_id)
        if fields.get("directory") != application_id:
            raise AnsibleError(
                f"lookup('role_version'): roles/{application_id} was not placed by a pull"
            )
        version = fields.get("version", "")
        if not version:
            raise AnsibleError(
                f"lookup('role_version'): the source of {application_id} declares no "
                f"semver in {', '.join(VERSION_MANIFESTS)} at its repository root"
            )
        return [version]
