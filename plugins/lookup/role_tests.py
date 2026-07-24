"""Lookup `role_tests`: read a value from a role's ``meta/tests.yml``.

    lookup('role_tests', application_id, 'cli.timeout', default=3600)

Terms: application_id and a dotted key path. A missing file, missing key,
or non-mapping intermediate returns the ``default`` kwarg (``None`` when
not given). ``meta/tests.yml`` carries per-role test-harness settings
(e.g. the CLI e2e timeout for roles whose test legitimately outlasts the
uniform default).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_TESTS


class LookupModule(LookupBase):
    def run(
        self, terms, variables: dict[str, Any] | None = None, **kwargs
    ) -> list[Any]:
        if not terms or len(terms) != 2:
            raise AnsibleError(
                "lookup('role_tests', application_id, dotted_path) expects "
                "exactly two positional terms."
            )
        application_id = str(terms[0]).strip()
        dotted = str(terms[1]).strip()
        if not application_id or not dotted:
            raise AnsibleError(
                "role_tests: application_id and dotted_path must be non-empty."
            )
        default = kwargs.get("default")

        base = (variables or {}).get("playbook_dir")
        if not base:
            raise AnsibleError("lookup('role_tests'): 'playbook_dir' is unavailable.")

        path = Path(str(base)) / "roles" / application_id / ROLE_FILE_META_TESTS
        data = load_yaml_any(str(path), default_if_missing={})

        node: Any = data
        for key in dotted.split("."):
            if not isinstance(node, dict) or key not in node:
                return [default]
            node = node[key]
        return [node]
