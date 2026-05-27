from __future__ import annotations

import textwrap
from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from plugins.filter.docker_service_enabled import (
    FilterModule as _DockerServiceEnabledFilter,
)
from utils.cache.applications import get_merged_applications
from utils.cache.yaml import dump_yaml_str
from utils.roles.applications.config import get
from utils.roles.applications.services.database import (
    get_database_service_config,
    resolve_database_service_key,
)


def _resolve_local_database_host(
    applications: dict[str, Any], application_id: str
) -> str | None:
    try:
        dbtype = resolve_database_service_key(applications, application_id)
    except ValueError as exc:
        raise AnsibleError(f"container_depends_on: {exc}") from exc
    if not dbtype:
        return None
    cfg = get_database_service_config(applications, application_id)
    if not bool(cfg.get("enabled", False)):
        return None
    if bool(cfg.get("shared", False)):
        return None
    return "database"


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "container_depends_on: expected exactly 1 positional term "
                "(application_id)"
            )
        application_id = str(terms[0]).strip()
        if not application_id:
            raise AnsibleError(
                "container_depends_on: 'application_id' must be a non-empty string"
            )

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        applications = get_merged_applications(
            variables=vars_,
            roles_dir=kwargs.get("roles_dir"),
            templar=getattr(self, "_templar", None),
        )

        if application_id not in applications:
            raise AnsibleError(
                f"container_depends_on: unknown application_id '{application_id}'"
            )

        entries: dict[str, dict[str, str]] = {}

        db_host = _resolve_local_database_host(applications, application_id)
        if db_host:
            entries[db_host] = {"condition": "service_healthy"}

        redis_enabled = _DockerServiceEnabledFilter.is_docker_service_enabled(
            applications, application_id, "redis"
        ) or bool(
            get(
                applications=applications,
                application_id=application_id,
                config_path="services.oauth2.enabled",
                strict=False,
                default=False,
                skip_missing_app=True,
            )
        )
        if redis_enabled:
            entries["redis"] = {"condition": "service_healthy"}

        extra = kwargs.get("extra")
        if extra:
            if not isinstance(extra, Mapping):
                raise AnsibleError("container_depends_on: 'extra' must be a mapping")
            for name, body in extra.items():
                if isinstance(body, Mapping):
                    entries[str(name)] = {str(k): str(v) for k, v in body.items()}

        if not entries:
            return [""]

        indent = int(kwargs.get("indent", 4))
        body = dump_yaml_str({"depends_on": entries}).rstrip()
        if indent <= 0:
            return [body]
        return [textwrap.indent(body, " " * indent)]
