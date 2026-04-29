# lookup_plugins/config.py
from __future__ import annotations

from typing import Any, Dict, Optional

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.applications.config import get
from utils.cache.applications import get_merged_applications
from utils.cache.base import _render_with_templar
from utils.cache.users import get_merged_users


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

    def run(self, terms, variables: Optional[Dict[str, Any]] = None, **kwargs):
        if not terms or len(terms) not in (2, 3):
            raise AnsibleError(
                "lookup('config', application_id, config_path[, default]) expects 2 or 3 terms."
            )

        application_id = terms[0]
        config_path = terms[1]

        default_provided = len(terms) == 3
        default_value = terms[2] if default_provided else None
        strict = not default_provided

        templar = getattr(self, "_templar", None)
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        applications = get_merged_applications(
            variables=variables,
            roles_dir=kwargs.get("roles_dir"),
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
                roles_dir=kwargs.get("roles_dir"),
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
            return [
                _render_with_templar(
                    value,
                    templar=templar,
                    variables=variables,
                    raw_applications=applications,
                    raw_users=users,
                )
            ]

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

        # lookup plugins must return a list
        return [value]
