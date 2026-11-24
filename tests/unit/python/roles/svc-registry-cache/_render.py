from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from typing import Any
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.template import Templar
from jinja2 import DictLoader, StrictUndefined
from jinja2.nativetypes import NativeEnvironment

from plugins.lookup import container_healthcheck
from utils import PROJECT_ROOT
from utils.cache import applications as applications_cache
from utils.cache.files import read_text
from utils.cache.reset import _reset_rendered_caches_for_tests
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles" / "svc-registry-cache"
TEMPLATES = ROLE / "templates"
FIXTURE = (
    PROJECT_ROOT
    / "tests"
    / "unit"
    / "python"
    / "roles"
    / "svc-registry-cache"
    / "fixtures"
    / "registry.json"
)
VOLUMES = ROLE / ROLE_FILE_META_VOLUMES
CORE_TASKS = ROLE / "tasks" / "00_core.yml"
ENV_INCLUDE = {"roles/sys-svc-container/templates/env.j2": "TZ=stub\nLANG=C.UTF-8\n"}
ENTRYPOINT_TARGET = "/usr/local/bin/infinito-registry-cache-entrypoint.sh"

_VENDOR = importlib.import_module(
    "tests.unit.python.roles.svc-registry-cache.test_vendor_caches"
)
GATEWAY = _VENDOR.GATEWAY
VENDORS = _VENDOR.VENDORS
role_var = _VENDOR._role_var


def cache_defaults() -> dict[str, Any]:
    """Returns:
    The ``cache`` service defaults of the role's meta/services.yml.
    """
    return load_yaml(str(ROLE / ROLE_FILE_META_SERVICES))["cache"]


def flavor_of(override: dict[str, Any]) -> str:
    """Args:
        override: the ``services.cache`` keys an inventory sets.

    Returns:
        The flavor the merged config resolves, the role default when the inventory sets none.
    """
    return {**cache_defaults(), **override}["flavor"]


class _Config:
    """Args:
    services: the ``services`` mapping the ``config`` lookup reads; a value
        that is one Jinja expression renders natively, as the config SPOT
        renders it.
    """

    def __init__(self, services: dict[str, Any]) -> None:
        self.services = services
        self.environment = NativeEnvironment(undefined=StrictUndefined)
        self.environment.globals["lookup"] = lambda _name, _app, path: self.value(path)

    def value(self, path: str, *default: Any) -> Any:
        """Args:
            path: the dotted config path below the application.
            default: the value of an absent path; without it an absent path raises.

        Returns:
            The value at *path*, rendered when it is a template.
        """
        node: Any = {"services": self.services}
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                if default:
                    return default[0]
                raise KeyError(path)
            node = node[part]
        if isinstance(node, str) and "{{" in node:
            return self.environment.from_string(node).render()
        return node

    def run(self, terms: list[Any], variables: Any = None) -> list[Any]:
        return [self.value(*terms[1:])]


def healthcheck(flavor: str, declared: Any = None) -> str:
    """Args:
        flavor: the value of ``services.cache.flavor``.
        declared: a replacement ``services.cache.healthcheck`` value, for the
            pre-selection shape and for negative controls.

    Returns:
        The block ``lookup('container_healthcheck', 'cache')`` renders.
    """
    cache = {**cache_defaults(), "flavor": flavor}
    if declared is not None:
        cache["healthcheck"] = declared
    config = _Config({"cache": cache})
    loader = SimpleNamespace(get=lambda name, **_: {"config": config}[name])
    with mock.patch.object(container_healthcheck, "lookup_loader", loader):
        return container_healthcheck.LookupModule().run(
            ["cache"], variables={"application_id": "svc-registry-cache"}
        )[0]


def config_healthcheck(flavor: str, declared: str | None = None) -> Any:
    """Args:
        flavor: the ``services.cache.flavor`` the inventory sets.
        declared: an inventory override of ``services.cache.healthcheck``, for
            negative controls.

    Returns:
        What the ``config`` lookup plugin hands ``container_healthcheck`` for
        ``services.cache.healthcheck``, called the way that lookup calls it,
        with a real Ansible templar. The eager render of every application is
        held back, so the config lookup's own ``_render_with_templar`` renders
        the value.
    """
    cache = {"flavor": flavor, **({"healthcheck": declared} if declared else {})}
    variables = {
        "applications": {"svc-registry-cache": {"services": {"cache": cache}}},
        "group_names": ["svc-registry-cache"],
    }
    loader = DataLoader()
    lookup_loader.add_directory(str(PROJECT_ROOT / "plugins" / "lookup"))
    config = lookup_loader.get(
        "config", loader=loader, templar=Templar(loader=loader, variables=variables)
    )
    _reset_rendered_caches_for_tests()
    try:
        with mock.patch.object(
            applications_cache, "_render_with_templar", new=lambda value, **_: value
        ):
            return config.run(
                ["svc-registry-cache", "services.cache.healthcheck", {}],
                variables=variables,
            )[0]
    finally:
        _reset_rendered_caches_for_tests()


def fixture() -> dict[str, str]:
    """Returns:
    Every template render of the registry flavor captured before the flavor existed.
    """
    return json.loads(read_text(str(FIXTURE)))


def render(
    name: str,
    flavor: str,
    vendors: list[str] | None = None,
    multi_proxy: dict[str, Any] | None = None,
    template: str | None = None,
) -> str:
    """Args:
        name: the template file below the role's templates/.
        flavor: the value of ``services.cache.flavor``.
        vendors: the vendor registries the registry flavor serves.
        multi_proxy: ``services.cache.multi_proxy`` keys overriding the role defaults.
        template: a replacement template text, for negative controls.

    Returns:
        The rendered template.
    """
    vendors = vendors or []
    defaults = cache_defaults()
    proxy = {**defaults["multi_proxy"], **(multi_proxy or {})}
    environment = _VENDOR._environment()
    environment.loader = DictLoader({**_VENDOR.INCLUDES, **ENV_INCLUDE})
    source = template if template is not None else read_text(str(TEMPLATES / name))
    return environment.from_string(source).render(
        application_id="svc-registry-cache",
        entity_name="cache",
        IS_COMPOSE_MODE=True,
        REGISTRY_CACHE_FLAVOR=flavor,
        REGISTRY_CACHE_CONTAINER="cache-registry",
        REGISTRY_CACHE_DATA_TARGET=_VENDOR.DATA_TARGET,
        REGISTRY_CACHE_PROXY_REMOTE_URL=defaults["proxy"]["remote_url"],
        REGISTRY_CACHE_PROXY_TTL=f"{int(defaults['max_idle_days']) * 24}h",
        REGISTRY_CACHE_VENDORS=vendors,
        REGISTRY_CACHE_VENDOR_SERVICES=_VENDOR._vendor_services(vendors),
        REGISTRY_CACHE_VENDOR_ENV_FILES=_VENDOR._vendor_env_files(vendors),
        REGISTRY_CACHE_VENDOR_PORT=5000,
        REGISTRY_CACHE_FRONT_CONTAINER="cache-registry-front",
        REGISTRY_CACHE_FRONT_HOST=GATEWAY,
        REGISTRY_CACHE_FRONT_LISTEN_PORT=443,
        REGISTRY_CACHE_FRONT_TLS_TARGET="/etc/nginx/tls",
        REGISTRY_CACHE_FRONT_CERT_NAME=f"{GATEWAY}.crt",
        REGISTRY_CACHE_FRONT_KEY_NAME=f"{GATEWAY}.key",
        REGISTRY_CACHE_FRONT_RESOLVER="127.0.0.11",
        REGISTRY_CACHE_MULTI_PROXY_IMAGE=proxy["image"],
        REGISTRY_CACHE_MULTI_PROXY_VERSION=proxy["version"],
        REGISTRY_CACHE_MULTI_PROXY_REGISTRIES=proxy["registries"],
        REGISTRY_CACHE_MULTI_PROXY_MAX_SIZE=proxy["max_size"],
        REGISTRY_CACHE_MULTI_PROXY_AUTH=proxy["auth"],
        REGISTRY_CACHE_MULTI_PROXY_IDLE_DAYS=proxy.get(
            "max_idle_days", defaults["max_idle_days"]
        ),
        REGISTRY_CACHE_MULTI_PROXY_ENTRYPOINT=ENTRYPOINT_TARGET,
    )


def env_values(text: str) -> dict[str, str]:
    """Args:
        text: a rendered env file.

    Returns:
        Its ``KEY=value`` assignments.
    """
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def volume_mount(key: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Args:
        key: the volume key in the role's meta/volumes.yml.

    Returns:
        The volume entry and its only mount.
    """
    volume = load_yaml(str(VOLUMES))[key]
    (mount,) = volume["mounts"]
    return volume, mount


def multi_proxy_files() -> list[dict[str, Any]]:
    """Returns:
    The files the role ships to the multi-proxy, as its vars list them.
    """
    return load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))[
        "REGISTRY_CACHE_MULTI_PROXY_FILES"
    ]


def multi_proxy_block() -> dict[str, Any]:
    """Returns:
    The task block that ships the multi-proxy files.
    """
    return next(
        task
        for task in load_yaml_any(str(CORE_TASKS))
        if task.get("when") == "REGISTRY_CACHE_FLAVOR == 'multi-proxy'"
    )
