"""Name the data volume of every database provider on this host nobody consumes.

A consumer is a deployed role whose merged config enables a shared database of
the provider's engine; a role with a dedicated database brings its own volume
and is no consumer of the provider. A provider without a consumer holds only
the databases its engine creates for itself, so no databases.csv row names it
and baudolo records its volume undumped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.applications.services.database import (
    RDBMS_SERVICE_KEYS,
    get_database_service_config,
    resolve_database_service_key,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

PROVIDER_VOLUME = "data"


def provider_of(engine: str) -> str:
    return f"svc-db-{engine}"


class LookupModule(LookupBase):
    def run(
        self,
        terms: Sequence[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if terms:
            raise AnsibleError("database_consumerless_volumes: expects no terms.")

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        group_names = [str(group) for group in vars_.get("group_names") or []]
        templar = getattr(self, "_templar", None)
        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=templar
        ).run([], variables=vars_)[0]
        volume = lookup_loader.get("volume", loader=self._loader, templar=templar)

        providers = {provider_of(engine) for engine in RDBMS_SERVICE_KEYS}
        consumed: set[str] = set()
        for role_id in group_names:
            if role_id in providers:
                continue
            try:
                engine = resolve_database_service_key(applications, role_id)
            except ValueError as error:
                raise AnsibleError(f"database_consumerless_volumes: {error}") from error
            if engine and get_database_service_config(applications, role_id).get(
                "shared"
            ):
                consumed.add(provider_of(engine))

        return [
            [
                volume.run([provider, PROVIDER_VOLUME], variables=vars_)[0]["name"]
                for provider in sorted(providers)
                if provider in group_names and provider not in consumed
            ]
        ]
