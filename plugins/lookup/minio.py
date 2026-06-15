from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache.applications import get_merged_applications
from utils.roles.applications.config import get
from utils.roles.entity_name import get_entity_name

MINIO_PROVIDER_ROLE = "web-app-minio"
MINIO_SERVICE_KEY = get_entity_name(MINIO_PROVIDER_ROLE)


class LookupModule(LookupBase):
    """
    Resolve MinIO object-store values for a given minio_consumer_id.

    Mirrors plugins/lookup/database.py: branches on the consumer's
    `services.minio.shared` flag to yield either central (shared) or
    embedded (local) connection details.

    API (STRICT):
      - {{ lookup('minio', minio_consumer_id) }}
      - {{ lookup('minio', minio_consumer_id, 'url') }}

    Notes:
      - want-path is optional and MUST be the second positional argument
      - kwarg want= is NOT supported (use positional want-path)
    """

    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = terms or []
        if len(terms) not in (1, 2):
            raise AnsibleError("minio: requires minio_consumer_id [, want_path]")

        if "want" in kwargs and str(kwargs.get("want") or "").strip():
            raise AnsibleError(
                "minio: kwarg 'want=' is not supported; use positional want_path "
                "like lookup('minio', <id>, 'url')"
            )

        consumer_id = str(terms[0]).strip()
        if not consumer_id:
            raise AnsibleError("minio: minio_consumer_id must not be empty")

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

        enabled = bool(
            get(
                applications,
                consumer_id,
                f"services.{MINIO_SERVICE_KEY}.enabled",
                strict=False,
                default=False,
            )
        )
        shared = bool(
            get(
                applications,
                consumer_id,
                f"services.{MINIO_SERVICE_KEY}.shared",
                strict=False,
                default=False,
            )
        )
        central_enabled = shared

        central_name = get(
            applications,
            MINIO_PROVIDER_ROLE,
            f"services.{MINIO_SERVICE_KEY}.name",
            strict=False,
            default=MINIO_SERVICE_KEY,
            skip_missing_app=True,
        )
        central_name = (
            str(central_name) if central_name is not None else ""
        ).strip() or MINIO_SERVICE_KEY

        host = central_name if central_enabled else MINIO_SERVICE_KEY
        network = (
            get_entity_name(MINIO_PROVIDER_ROLE) if central_enabled else consumer_entity
        )
        container = (
            central_name
            if central_enabled
            else f"{consumer_entity}-{MINIO_SERVICE_KEY}"
        )
        port = get(
            applications,
            MINIO_PROVIDER_ROLE,
            f"services.{MINIO_SERVICE_KEY}.api_port",
            strict=False,
            default=9000,
            skip_missing_app=True,
        )
        region = get(
            applications,
            MINIO_PROVIDER_ROLE,
            f"services.{MINIO_SERVICE_KEY}.region",
            strict=False,
            default="us-east-1",
            skip_missing_app=True,
        )
        client_image = get(
            applications,
            MINIO_PROVIDER_ROLE,
            "services.client.image",
            strict=False,
            default="quay.io/minio/mc",
            skip_missing_app=True,
        )
        client_version = get(
            applications,
            MINIO_PROVIDER_ROLE,
            "services.client.version",
            strict=False,
            default="",
            skip_missing_app=True,
        )
        mc_image = (
            f"{client_image}:{client_version}" if client_version else client_image
        )

        access_key = consumer_entity
        secret_key = get(
            applications,
            consumer_id,
            "credentials.objstore_secret_key",
            strict=False,
            default="",
        )
        bucket = consumer_entity

        public = bool(
            get(
                applications,
                consumer_id,
                f"services.{MINIO_SERVICE_KEY}.public",
                strict=False,
                default=False,
            )
        )

        image = get(
            applications,
            MINIO_PROVIDER_ROLE,
            f"services.{MINIO_SERVICE_KEY}.image",
            strict=False,
            default="quay.io/minio/minio",
            skip_missing_app=True,
        )
        default_version = get(
            applications,
            MINIO_PROVIDER_ROLE,
            f"services.{MINIO_SERVICE_KEY}.version",
            strict=False,
            default="latest",
            skip_missing_app=True,
        )
        version = get(
            applications,
            consumer_id,
            f"services.{MINIO_SERVICE_KEY}.version",
            strict=False,
            default=default_version,
        )

        env = f"{path_instances}{consumer_entity}/.env/objstore.env"

        volume_prefix = "" if central_enabled else f"{consumer_entity}_"
        volume = (
            f"{volume_prefix}{MINIO_SERVICE_KEY}"
            if bool(enabled and not shared)
            else ""
        )

        url = f"http://{host}:{port}"

        resolved = {
            "id": MINIO_PROVIDER_ROLE,
            "enabled": enabled,
            "shared": shared,
            "local": bool(enabled and not shared),
            "host": host,
            "port": port,
            "network": network,
            "container": container,
            "bucket": bucket,
            "public": public,
            "access_key": access_key,
            "secret_key": secret_key,
            "image": image,
            "version": version,
            "region": region,
            "mc_image": mc_image,
            "env": env,
            "volume": volume,
            "url": url,
            "reach_host": "127.0.0.1",
        }

        return [resolved if want == "all" else resolved.get(want, "")]

    @staticmethod
    def _require_var(vars_: dict[str, Any], key: str) -> Any:
        if key not in vars_:
            raise AnsibleError(f"minio: required variable '{key}' is not set")
        return vars_[key]
