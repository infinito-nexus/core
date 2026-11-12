"""Lookup `playwright_order`: run each role's Playwright pass after the roles
its ``meta/tests.yml`` names under ``playwright.run_after``.

    lookup('playwright_order', roles)

Term: the round's Playwright roles in their discovery order. Each role's
``playwright.run_after`` is read through the ``role_tests`` lookup, so a Jinja
value renders with ``application_id`` bound to that role. A named role outside
the round constrains nothing, and a role no constraint moves keeps its place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.order import stable_order_after

RUN_AFTER = "playwright.run_after"


def _role_names(role: str, value: Any, known: set[str]) -> list[str]:
    """Return *value* as the role names *role* runs after.

    Args:
        role: the role whose ``meta/tests.yml`` declared *value*.
        value: the rendered ``playwright.run_after``.
        known: every role directory under ``roles/``.

    Raises:
        AnsibleError: *value* is not a list of role names, or names a role
            that does not exist.
    """
    if not isinstance(value, list) or not all(
        isinstance(name, str) and name.strip() for name in value
    ):
        raise AnsibleError(
            f"{role}: {RUN_AFTER} in meta/tests.yml must render to a list of "
            f"role names, got {value!r}."
        )
    unknown = sorted(set(value) - known)
    if unknown:
        raise AnsibleError(f"{role}: {RUN_AFTER} names unknown roles {unknown}.")
    return value


class LookupModule(LookupBase):
    def run(
        self, terms, variables: dict[str, Any] | None = None, **kwargs
    ) -> list[list[str]]:
        if len(terms) != 1 or not isinstance(terms[0], list):
            raise AnsibleError(
                "lookup('playwright_order', roles) expects exactly one list of "
                "role names."
            )
        roles = [str(role) for role in terms[0]]
        base = (variables or {}).get("playbook_dir")
        if not base:
            raise AnsibleError(
                "lookup('playwright_order'): 'playbook_dir' is unavailable."
            )
        roles_dir = Path(str(base)) / "roles"
        known = {path.name for path in roles_dir.iterdir() if path.is_dir()}

        role_tests = lookup_loader.get(
            "role_tests", loader=self._loader, templar=self._templar
        )
        after = {
            role: _role_names(
                role,
                role_tests.run([role, RUN_AFTER], variables=variables, default=[])[0],
                known,
            )
            for role in roles
        }
        try:
            return [stable_order_after(roles, after)]
        except RuntimeError as exc:
            raise AnsibleError(f"lookup('playwright_order'): {exc}") from exc
