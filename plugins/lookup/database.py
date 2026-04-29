# lookup_plugins/database.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.applications.config import get
from utils.database_service import (
    get_database_service_config,
    resolve_database_service_key,
)
from utils.entity_name_utils import get_entity_name
from utils.cache.applications import get_merged_applications


class LookupModule(LookupBase):
    """
    Resolve database values for a given database_consumer_id.

    API (STRICT):
      - {{ lookup('database', database_consumer_id) }}
      - {{ lookup('database', database_consumer_id, 'url_full') }}

    Notes:
      - want-path is optional and MUST be the second positional argument if used
      - kwarg want= is NOT supported (use positional want-path)
    """

    def run(
        self,
        terms: List[Any],
        variables: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Any]:
        terms = terms or []
        if len(terms) not in (1, 2):
            raise AnsibleError("database: requires database_consumer_id [, want_path]")

        # STRICT: do not support legacy want= kwarg at all
        if "want" in kwargs and str(kwargs.get("want") or "").strip():
            raise AnsibleError(
                "database: kwarg 'want=' is not supported; use positional want_path "
                "like lookup('database', <id>, 'url_full')"
            )

        consumer_id = str(terms[0]).strip()
        if not consumer_id:
            raise AnsibleError("database: database_consumer_id must not be empty")

        # STRICT positional want-path (optional)
        want = str(terms[1]).strip() if len(terms) == 2 else ""
        if not want:
            want = "all"

        vars_ = variables or self._templar.available_variables
        applications = get_merged_applications(
            variables=vars_,
            roles_dir=kwargs.get("roles_dir"),
            templar=getattr(self, "_templar", None),
        )
        path_instances = self._require_var(vars_, "DIR_COMPOSITIONS")

        consumer_entity = get_entity_name(consumer_id)

        try:
            dbtype = resolve_database_service_key(applications, consumer_id)
        except ValueError as exc:
            raise AnsibleError(f"database: {exc}") from exc

        database_service = get_database_service_config(applications, consumer_id)
        enabled = bool(database_service.get("enabled", False))
        shared = bool(database_service.get("shared", False))

        # If no direct database service is configured: keep behavior similar to the
        # historical empty-value lookup payload.
        if not dbtype:
            resolved = {
                "id": "",
                "enabled": enabled,
                "shared": shared,
                "type": "",
                "name": consumer_entity,
                "instance": "",
                "host": "",
                "container": "",
                "username": consumer_entity,
                "password": "",
                "port": "",
                "env": "",
                "url_jdbc": "",
                "url_full": "",
                "volume": "",
                "image": "",
                "version": "",
                "reach_host": "127.0.0.1",
            }
            return [resolved if want == "all" else resolved.get(want, "")]

        # Central/shared DB if shared==True
        central_enabled = shared
        db_id = f"svc-db-{dbtype}"

        central_name = get(
            applications,
            db_id,
            f"services.{dbtype}.name",
            strict=False,
            default="",
            skip_missing_app=True,
        )
        central_name = (str(central_name) if central_name is not None else "").strip()

        name = consumer_entity
        instance = central_name if central_enabled else name
        host = central_name if central_enabled else "database"
        container = dbtype if central_enabled else f"{consumer_entity}-database"
        username = consumer_entity

        password = get(
            applications,
            consumer_id,
            "credentials.database_password",
            strict=False,
            default="",
        )

        # Per req-009 the database port lives on the database role itself at
        # `applications.svc-db-<type>.services.<type>.ports.local.database`.
        port = get(
            applications,
            db_id,
            f"services.{dbtype}.ports.local.database",
            strict=False,
            default="",
            skip_missing_app=True,
        )

        default_version = get(
            applications,
            db_id,
            f"services.{dbtype}.version",
            strict=False,
            default="",
            skip_missing_app=True,
        )

        version = get(
            applications,
            consumer_id,
            f"services.{dbtype}.version",
            strict=False,
            default=default_version,
        )

        # env path without compose dict
        env_dir = f"{path_instances}{get_entity_name(consumer_id)}/.env/"
        env = f"{env_dir}{dbtype}.env"

        jdbc_scheme = dbtype if dbtype == "mariadb" else "postgresql"
        url_jdbc = f"jdbc:{jdbc_scheme}://{host}:{port}/{name}"
        url_full = f"{dbtype}://{username}:{password}@{host}:{port}/{name}"

        volume_prefix = f"{consumer_entity}_" if not central_enabled else ""
        volume = f"{volume_prefix}{host}"

        resolved = {
            "id": db_id,
            "enabled": enabled,
            "shared": shared,
            "type": dbtype,
            "name": name,
            "instance": instance,
            "host": host,
            "container": container,
            "username": username,
            "password": password,
            "port": port,
            "env": env,
            "url_jdbc": url_jdbc,
            "url_full": url_full,
            "volume": volume,
            "image": dbtype,
            "version": version,
            "reach_host": "127.0.0.1",
        }

        return [resolved if want == "all" else resolved.get(want, "")]

    @staticmethod
    def _require_var(vars_: Dict[str, Any], key: str) -> Any:
        if key not in vars_:
            raise AnsibleError(f"database: required variable '{key}' is not set")
        return vars_[key]
