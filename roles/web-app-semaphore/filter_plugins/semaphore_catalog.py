from __future__ import annotations

import json
from collections.abc import Mapping
from importlib.util import module_from_spec, spec_from_file_location
from typing import Any

from ansible.errors import AnsibleFilterError

from utils.cache import ROLES_DIR

FILES = ROLES_DIR / "web-app-semaphore" / "files"
CATALOG_PATH = ("services", "semaphore", "workspaces", "catalog")
PROVIDERS = tuple(
    sorted(path.name for path in (FILES / "opentofu" / "roots").iterdir())
)


def _schema():
    spec = spec_from_file_location(
        "semaphore_provision_schema", FILES / "python" / "provision" / "schema.py"
    )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    interface = json.loads(
        (FILES / "opentofu" / "interface.json").read_text(encoding="utf-8")
    )
    return module, module.definition(interface, "catalog")


def _override(applications: Any, application_id: str) -> Mapping:
    node = applications
    for key in (application_id, *CATALOG_PATH):
        if not isinstance(node, Mapping) or key not in node:
            return {}
        node = node[key]
    return node


def semaphore_catalogs(
    merged: Mapping, applications: Any, application_id: str
) -> dict[str, Any]:
    """Args:
        merged: ``services.semaphore.workspaces.catalog`` as the config lookup
            returns it, the inventory deep-merged into the role defaults.
        applications: the inventory's ``applications`` overrides.
        application_id: the Semaphore application.

    Returns:
        ``{provider: catalog}``: a provider the inventory names takes the
        inventory catalog as a whole, every other one the role default.

    Raises:
        AnsibleFilterError: a provider is unknown or missing, a catalog breaks
            ``$defs.catalog``, or two providers offer one region of a flavor.
    """
    override = _override(applications, application_id)
    unknown = sorted(set(merged) - set(PROVIDERS))
    missing = [provider for provider in PROVIDERS if provider not in merged]
    if unknown or missing:
        raise AnsibleFilterError(
            f"semaphore_catalogs: {'.'.join(CATALOG_PATH)} names the providers "
            f"{sorted(merged)}, expected {list(PROVIDERS)}"
        )
    schema, rule = _schema()
    catalogs = {}
    for provider in PROVIDERS:
        catalog = override[provider] if provider in override else merged[provider]
        try:
            schema.check(catalog, rule, provider)
        except schema.SchemaError as error:
            raise AnsibleFilterError(
                f"semaphore_catalogs: {'.'.join(CATALOG_PATH)}.{error}"
            ) from None
        catalogs[provider] = catalog
    offered: dict[tuple[str, str], list[str]] = {}
    for provider, catalog in catalogs.items():
        for flavor, entry in catalog.items():
            for region in entry["regions"]:
                offered.setdefault((flavor, region), []).append(provider)
    for (flavor, region), providers in sorted(offered.items()):
        if len(providers) > 1:
            raise AnsibleFilterError(
                f"semaphore_catalogs: region {region!r} of flavor {flavor} is "
                f"offered by {', '.join(providers)}; a provision could not tell "
                "which root to run"
            )
    return catalogs


class FilterModule:
    def filters(self):
        return {"semaphore_catalogs": semaphore_catalogs}
