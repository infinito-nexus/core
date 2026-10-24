from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.manager.credential_key import OVERRIDE_SECTION
from utils.roles.applications.config import get
from utils.roles.entity.name import entity_name
from utils.tls_common import (
    collect_domains_for_app,
    is_onion_domain,
    resolve_enabled,
)

OBJSTORE_ENGINES = ("seaweedfs", "minio")
OBJSTORE_PROVIDER_ROLE = {
    "seaweedfs": "web-svc-seaweedfs",
    "minio": "web-app-minio",
}
OBJSTORE_DEFAULT_PORT = {"seaweedfs": 8333, "minio": 9000}
OBJSTORE_DEFAULT_IMAGE = {
    "seaweedfs": "chrislusf/seaweedfs",
    "minio": "quay.io/minio/minio",
}
OBJSTORE_DEFAULT_REGION = "us-east-1"
OBJSTORE_PROXY_PREFIX = "/objstore"


def _is_enabled(applications: dict[str, Any], consumer_id: str, engine: str) -> bool:
    return bool(
        get(
            applications,
            consumer_id,
            f"services.{engine}.enabled",
            strict=False,
            default=False,
        )
    )


class LookupModule(LookupBase):
    """
    Resolve engine-agnostic S3 object-store values for a consumer.

    Mirrors plugins/lookup/database.py (postgres|mariadb): branches on which
    object-store engine (seaweedfs|minio) the consumer has enabled and yields a
    uniform S3 connection payload, so consumer templates stay engine-agnostic.

    API (STRICT):
      - {{ lookup('objstore', consumer_id) }}
      - {{ lookup('objstore', consumer_id, 'url') }}
    """

    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = terms or []
        if len(terms) not in (1, 2):
            raise AnsibleError("objstore: requires consumer_id [, want_path]")

        consumer_id = str(terms[0]).strip()
        if not consumer_id:
            raise AnsibleError("objstore: consumer_id must not be empty")

        want = str(terms[1]).strip() if len(terms) == 2 else ""
        if not want:
            want = "all"

        vars_ = variables or self._templar.available_variables
        applications = lookup_loader.get(
            "applications",
            loader=self._loader,
            templar=getattr(self, "_templar", None),
        ).run([], variables=vars_)[0]
        path_instances = self._require_var(vars_, "DIR_COMPOSITIONS")
        consumer_entity = entity_name(consumer_id)

        active = [
            e for e in OBJSTORE_ENGINES if _is_enabled(applications, consumer_id, e)
        ]
        if len(active) > 1:
            raise AnsibleError(
                f"objstore: multiple object-store engines enabled for "
                f"'{consumer_id}': {active}; enable only one."
            )
        engine = active[0] if active else ""

        if not engine:
            resolved = {
                "id": "",
                "engine": "",
                "enabled": False,
                "shared": False,
                "local": False,
                "host": "",
                "port": "",
                "network": "",
                "container": "",
                "bucket": consumer_entity,
                "public": False,
                "access_key": consumer_entity,
                "secret_key": "",
                "image": "",
                "version": "",
                "region": OBJSTORE_DEFAULT_REGION,
                "env": "",
                "volume": "",
                "endpoint": "",
                "url": "",
                "credentialed_url": "",
                "public_domain": "",
                "public_bucket": "",
                "public_endpoint": "",
                "public_url": "",
                "proxy_required": False,
                "proxy_prefix": "",
                "upstream_domain": "",
                "upstream_scheme": "",
                "reach_host": "127.0.0.1",
            }
            return [resolved if want == "all" else resolved.get(want, "")]

        provider_role = OBJSTORE_PROVIDER_ROLE[engine]
        shared = bool(
            get(
                applications,
                consumer_id,
                f"services.{engine}.shared",
                strict=False,
                default=False,
            )
        )
        central_enabled = shared

        central_name = get(
            applications,
            provider_role,
            f"services.{engine}.name",
            strict=False,
            default=engine,
            skip_missing_app=True,
        )
        central_name = (
            str(central_name) if central_name is not None else ""
        ).strip() or engine

        host = central_name if central_enabled else engine
        network = entity_name(provider_role) if central_enabled else consumer_entity
        container = central_name if central_enabled else f"{consumer_entity}-{engine}"
        port = get(
            applications,
            provider_role,
            f"services.{engine}.api_port",
            strict=False,
            default=OBJSTORE_DEFAULT_PORT[engine],
            skip_missing_app=True,
        )
        region = get(
            applications,
            provider_role,
            f"services.{engine}.region",
            strict=False,
            default=OBJSTORE_DEFAULT_REGION,
            skip_missing_app=True,
        )

        access_key = consumer_entity
        secret_key = get(
            applications,
            consumer_id,
            f"{OVERRIDE_SECTION}.objstore_secret_key",
            strict=False,
            default="",
        )
        bucket = consumer_entity
        public = bool(
            get(
                applications,
                consumer_id,
                f"services.{engine}.public",
                strict=False,
                default=False,
            )
        )

        image = get(
            applications,
            provider_role,
            f"services.{engine}.image",
            strict=False,
            default=OBJSTORE_DEFAULT_IMAGE[engine],
            skip_missing_app=True,
        )
        default_version = get(
            applications,
            provider_role,
            f"services.{engine}.version",
            strict=False,
            default="latest",
            skip_missing_app=True,
        )
        version = get(
            applications,
            consumer_id,
            f"services.{engine}.version",
            strict=False,
            default=default_version,
        )

        env = f"{path_instances}{consumer_entity}/.env/objstore.env"
        volume_prefix = "" if central_enabled else f"{consumer_entity}_"
        volume = (
            f"{volume_prefix}{engine}"
            if bool(_is_enabled(applications, consumer_id, engine) and not shared)
            else ""
        )
        endpoint = f"{host}:{port}"
        url = f"http://{endpoint}"
        userinfo = f"{quote(access_key, safe='')}:{quote(secret_key, safe='')}"
        credentialed_url = f"http://{userinfo}@{endpoint}"

        public_domain = get(
            applications,
            provider_role,
            "domains.canonical.api",
            strict=False,
            default="",
            skip_missing_app=True,
        )
        public_domain = (
            str(public_domain) if public_domain is not None else ""
        ).strip()
        provider_app = applications.get(provider_role) or {}
        if not isinstance(provider_app, dict):
            provider_app = {}
        scheme = (
            "https"
            if resolve_enabled(provider_app, bool(vars_.get("TLS_ENABLED", True)))
            else "http"
        )

        def _lookup(name: str, args: list[Any], **kwargs: Any) -> Any:
            return lookup_loader.get(
                name, loader=self._loader, templar=getattr(self, "_templar", None)
            ).run(args, variables=vars_, **kwargs)[0]

        def _consumer_is_onion_only() -> bool:
            domains_map = _lookup("domains", [])
            if consumer_id not in domains_map:
                return False
            served_on = collect_domains_for_app(
                domains_map, consumer_id, err_prefix="objstore"
            )
            return bool(served_on) and all(is_onion_domain(d) for d in served_on)

        proxy_required = bool(
            public_domain
            and not is_onion_domain(public_domain)
            and _consumer_is_onion_only()
        )
        browser_domain = public_domain
        browser_scheme = scheme
        if proxy_required:
            consumer_tls = _lookup("tls", [consumer_id], consumer=consumer_id)
            browser_domain = f"{consumer_tls['domain']}{OBJSTORE_PROXY_PREFIX}"
            browser_scheme = consumer_tls["protocols"]["web"]

        public_bucket = f"{browser_domain}/{bucket}" if browser_domain else ""
        public_endpoint = f"{scheme}://{public_domain}" if public_domain else ""
        public_url = f"{browser_scheme}://{public_bucket}" if public_bucket else ""

        resolved = {
            "id": provider_role,
            "engine": engine,
            "enabled": True,
            "shared": shared,
            "local": bool(not shared),
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
            "env": env,
            "volume": volume,
            "endpoint": endpoint,
            "url": url,
            "credentialed_url": credentialed_url,
            "public_domain": public_domain,
            "public_bucket": public_bucket,
            "public_endpoint": public_endpoint,
            "public_url": public_url,
            "proxy_required": proxy_required,
            "proxy_prefix": OBJSTORE_PROXY_PREFIX,
            "upstream_domain": public_domain,
            "upstream_scheme": scheme,
            "reach_host": "127.0.0.1",
        }
        return [resolved if want == "all" else resolved.get(want, "")]

    @staticmethod
    def _require_var(vars_: dict[str, Any], key: str) -> Any:
        if key not in vars_:
            raise AnsibleError(f"objstore: required variable '{key}' is not set")
        return vars_[key]
