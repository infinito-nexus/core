from __future__ import annotations

import os
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

# nocheck: lookup-cache-import (this lookup IS the config SPOT accessor)
from utils.cache.applications import get_lazy_applications
from utils.cache.base import _fingerprint_scope, _render_with_templar

# nocheck: lookup-cache-import (config resolves user values via the users SPOT)
from utils.cache.users import get_merged_users
from utils.openbao_client import OpenBaoError, resolve, resolve_users
from utils.roles.applications.config import get


class LookupModule(LookupBase):
    """
    lookup('config', application_id, config_path[, default])

    - applications are resolved via lookup('applications')
    - default behavior is strict=True (missing keys raise)
    - if a 3rd argument (default) is provided, strict=False and that default is returned
    - parameters:
        1) application_id
        2) config_path
        3) optional default value
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) not in (2, 3):
            raise AnsibleError(
                "lookup('config', application_id, config_path[, default]) expects 2 or 3 terms."
            )

        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        with _fingerprint_scope():
            return self._resolve(terms, variables, kwargs.get("roles_dir"))

    def _resolve(
        self, terms: list[Any], variables: dict[str, Any], roles_dir: Any
    ) -> list[Any]:
        """
        Args:
            terms: the validated lookup terms.
            variables: the variables scope of the lookup.
            roles_dir: roles tree to build from, ``None`` for the project's own.

        Returns:
            The one-element lookup result.
        """
        application_id = terms[0]
        config_path = terms[1]

        default_provided = len(terms) == 3
        default_value = terms[2] if default_provided else None
        strict = not default_provided

        templar = getattr(self, "_templar", None)
        applications = get_lazy_applications(
            variables=variables,
            roles_dir=roles_dir,
            templar=templar,
        )

        if config_path.startswith("users."):
            user_path = config_path.split(".")
            if len(user_path) < 2:
                raise AnsibleError(
                    "lookup('config', ...): users path must include a canonical user key."
                )
            app_users = get(
                applications=applications,
                application_id=application_id,
                config_path="users",
                strict=False,
                default={},
                skip_missing_app=False,
            )
            canonical_user_key = user_path[1]
            if not isinstance(app_users, dict) or canonical_user_key not in app_users:
                if default_provided:
                    return [default_value]
                raise AnsibleError(
                    f"lookup('config', ...): application '{application_id}' does not define user "
                    f"'{canonical_user_key}'."
                )
            users = get_merged_users(
                variables=variables,
                roles_dir=roles_dir,
                templar=templar,
            )
            user_value = users.get(canonical_user_key)
            if user_value is None:
                if default_provided:
                    return [default_value]
                raise AnsibleError(
                    f"lookup('config', ...): canonical user '{canonical_user_key}' not found."
                )

            value: Any = user_value
            for part in user_path[2:]:
                if not isinstance(value, dict) or part not in value:
                    if default_provided:
                        return [default_value]
                    raise AnsibleError(
                        f"lookup('config', ...): missing user path '{config_path}'."
                    )
                value = value[part]
            value = _render_with_templar(
                value,
                templar=templar,
                variables=variables,
                raw_applications=applications,
                raw_users=users,
            )
            try:
                value = resolve_users(
                    value, (canonical_user_key, *user_path[2:]), os.environ
                )
            except OpenBaoError as exc:
                raise AnsibleError(f"lookup('config', ...): {exc}") from None
            return [value]

        value = get(
            applications=applications,
            application_id=application_id,
            config_path=config_path,
            strict=strict,
            default=default_value,
            skip_missing_app=not strict,
        )

        value = _render_with_templar(
            value,
            templar=templar,
            variables=variables,
            raw_applications=applications,
        )

        try:
            value = resolve(value, config_path, application_id, os.environ)
        except OpenBaoError as exc:
            raise AnsibleError(f"lookup('config', ...): {exc}") from None

        return [value]
