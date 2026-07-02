"""Lookup ``engine``: resolve a central/embedded engine connection for a consumer.

    {{ lookup('engine', 'redis', application_id) }}            # full dict
    {{ lookup('engine', 'redis', application_id, 'url') }}     # one field

Mirrors the ``database`` lookup but for the non-RDBMS engines registered in
:data:`utils.roles.applications.services.engines.ENGINES` (redis, memcached,
rabbitmq, elasticsearch, typesense, qdrant, unbound). When the consumer declares
``services.<engine>.shared: true`` the connection points at the central
``svc-db-*`` / ``svc-dns-*`` stack with the consumer's own provisioned credentials;
otherwise it points at the embedded sidecar inside the consumer's own stack.

See ``docs/architecture/central-engines.md``.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.applications.config import get
from utils.roles.applications.services.engines import (
    ENGINES,
    engine_service,
    is_engine_enabled,
    is_engine_shared,
)
from utils.roles.entity_name import get_entity_name

# Fields returned by the lookup (``want`` selects one, default ``all``).
_FIELDS = (
    "engine",
    "enabled",
    "shared",
    "local",
    "host",
    "port",
    "username",
    "password",
    "instance",
    "prefix",
    "url",
)


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = terms or []
        if len(terms) not in (2, 3):
            raise AnsibleError(
                "engine: requires engine_type, consumer_id [, want_path]"
            )
        engine = str(terms[0]).strip()
        consumer_id = str(terms[1]).strip()
        want = str(terms[2]).strip() if len(terms) == 3 else "all"
        if engine not in ENGINES:
            raise AnsibleError(
                f"engine: unknown engine '{engine}'; known: {', '.join(ENGINES)}"
            )
        if not consumer_id:
            raise AnsibleError("engine: consumer_id must not be empty")

        vars_ = variables or self._templar.available_variables
        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=vars_)[0]

        descriptor = ENGINES[engine]
        svc_id = descriptor["svc"]
        port = int(descriptor["port"])
        entity = get_entity_name(consumer_id)

        enabled = is_engine_enabled(applications, consumer_id, engine)
        shared = is_engine_shared(applications, consumer_id, engine)
        svc_cfg = engine_service(applications, consumer_id, engine)

        # Central name = the central engine's service name; embedded host = the
        # engine's bare service key inside the consumer stack (e.g. "redis").
        central_name = str(
            get(
                applications,
                svc_id,
                f"services.{engine}.name",
                strict=False,
                default=engine,
                skip_missing_app=True,
            )
            or engine
        ).strip()

        username = entity
        prefix = entity
        password = str(
            svc_cfg.get("password")
            or get(
                applications,
                consumer_id,
                f"credentials.{engine}_password",
                strict=False,
                default="",
            )
            or ""
        ).strip()
        host = central_name if shared else engine
        instance = central_name if shared else entity

        # Redis ACL users live only in memory and are lost whenever the central
        # redis container is recreated (a deploy can recreate it after the
        # consumer was provisioned), so per-consumer ACL users are not durable.
        # Shared consumers therefore authenticate as the central `default` user
        # with the engine-wide password (security-equivalent: the per-consumer
        # ACL was already +@all ~* allkeys).
        if engine == "redis" and shared:
            username = "default"
            password = str(
                get(
                    applications,
                    svc_id,
                    "credentials.REDIS_PASSWORD",
                    strict=False,
                    default="",
                    skip_missing_app=True,
                )
                or ""
            ).strip()

        if engine == "rabbitmq":
            url = (
                f"amqp://{username}:{password}@{host}:{port}/{entity}"
                if shared
                else f"amqp://{host}:{port}/"
            )
        elif engine in ("redis", "memcached"):
            scheme = "redis" if engine == "redis" else "memcached"
            auth = f"{username}:{password}@" if (shared and password) else ""
            url = f"{scheme}://{auth}{host}:{port}"
        elif engine in ("elasticsearch", "typesense", "qdrant"):
            url = f"http://{host}:{port}"
        else:  # unbound
            url = host

        resolved = {
            "engine": engine,
            "enabled": enabled,
            "shared": shared,
            "local": bool(enabled and not shared),
            "host": host,
            "port": port,
            "username": username if shared else "",
            "password": password if shared else "",
            "instance": instance,
            "prefix": prefix,
            "url": url,
        }
        if want == "all":
            return [resolved]
        if want not in _FIELDS:
            raise AnsibleError(
                f"engine: unknown want '{want}'; known: {', '.join(_FIELDS)}"
            )
        return [resolved.get(want, "")]
