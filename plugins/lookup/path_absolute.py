from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    """
    lookup('path_absolute', 'roles/sys-svc-compose/tasks/utils/swarm/x.yml')
    -> absolute path under the repository root (``playbook_dir``).

    Single point of truth for the repo-root anchor, replacing the repeated
    ``[playbook_dir, '<rel>'] | path_join`` boilerplate at cross-role
    include/template/script/src call sites. Joins every term, so a path may be
    passed whole ('roles/x/y.yml') or split across terms when a segment is a
    variable (``lookup('path_absolute', 'roles', system_service_role_name)``).
    """

    def run(
        self, terms, variables: dict[str, Any] | None = None, **kwargs
    ) -> list[str]:
        base = (variables or {}).get("playbook_dir")
        if not base:
            raise AnsibleError(
                "lookup('path_absolute'): 'playbook_dir' is unavailable."
            )
        parts: list[str] = []
        for term in terms:
            text = str(term).strip()
            if text:
                parts.extend(seg for seg in text.strip("/").split("/") if seg)
        return [str(Path(str(base), *parts))]
