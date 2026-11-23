from __future__ import annotations

import json
import re
from functools import reduce
from operator import getitem
from typing import Any

from ansible.plugins.filter.core import FilterModule as CoreFilters
from ansible.plugins.filter.mathstuff import FilterModule as MathFilters
from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from plugins.lookup.compose_volumes import compose_volumes
from plugins.lookup.container_volumes import container_volumes
from plugins.lookup.volume import LookupModule as VolumeLookup
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.docker.paths_utils import get_docker_paths
from utils.roles.entity.name import entity_name
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

APPLICATION_ID = "svc-cache-package"
ROLE = PROJECT_ROOT / "roles" / APPLICATION_ID
FIXTURE = (
    PROJECT_ROOT
    / "tests"
    / "unit"
    / "python"
    / "roles"
    / APPLICATION_ID
    / "fixtures"
    / "today.json"
)
CERTS_ENV = ROLE / "templates" / "environment" / "certs.j2"
DIR_COMPOSITIONS = "/opt/compose/"
DIR_VAR_LIB = "/var/lib/infinito/"
TLS_HOSTS = ["pypi.org", "registry.npmjs.org"]
SERVICES = ("package", "frontend", "bootstrap")
COMPOSE_VARS = (
    "CACHE_PACKAGE_CONTAINER",
    "CACHE_PACKAGE_FRONTEND_CONTAINER",
    "CACHE_PACKAGE_BOOTSTRAP_CONTAINER",
    "CACHE_PACKAGE_BOOTSTRAP_ENABLED",
    "CACHE_PACKAGE_BOOTSTRAP_SCRIPT_TARGET",
    "CACHE_PACKAGE_FRONTEND_PORTS",
)
CERTS_VARS = (
    "CACHE_PACKAGE_CA_DIR_HOST",
    "CACHE_PACKAGE_CERTS_DIR_HOST",
    "CACHE_PACKAGE_INIT_IMAGE",
)
INCLUDES = {
    "roles/sys-svc-compose/templates/base.yml.j2": "services:\n\n",
    "roles/sys-svc-container/templates/base.yml.j2": "    base: {{ service_name }}\n\n",
}
_EXPRESSION = re.compile(r"\{\{\s*(.*?)\s*\}\}")
_COMBINE = CoreFilters().filters()["combine"]


def applications(override: dict[str, Any] | None = None) -> dict[str, Any]:
    """Args:
        override: the ``services`` keys an inventory sets for the role.

    Returns:
        The applications mapping with the role defaults merged under the override.
    """
    defaults = load_yaml(str(ROLE / ROLE_FILE_META_SERVICES))
    return {
        APPLICATION_ID: {"services": _COMBINE(defaults, override or {}, recursive=True)}
    }


def _config(
    environment: Environment, apps: dict[str, Any], application_id: str, path: str
) -> Any:
    value = reduce(getitem, path.split("."), apps[application_id])
    if isinstance(value, str) and "{{" in value:
        return environment.from_string(value).render()
    return value


def environment(override: dict[str, Any] | None = None) -> Environment:
    """Args:
        override: the ``services`` keys an inventory sets for the role.

    Returns:
        A Jinja environment whose ``config``, ``container`` and ``volume``
        lookups resolve like the role's, and whose other lookups echo their terms.
    """
    apps = applications(override)
    built = Environment(
        autoescape=select_autoescape(default_for_string=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        loader=DictLoader(INCLUDES),
    )
    built.filters.update(CoreFilters().filters())
    built.filters.update(MathFilters().filters())

    def lookup(name: str, *terms: Any, **kwargs: Any) -> Any:
        if name == "config":
            return _config(built, apps, *terms)
        if name == "container":
            return reduce(
                getitem,
                terms[1].split("."),
                get_docker_paths(terms[0], DIR_COMPOSITIONS),
            )
        if name == "volume":
            return VolumeLookup().run(list(terms))[0]
        passed = {key: value for key, value in kwargs.items() if value != {}}
        return f"{name}: {json.dumps([list(terms), passed], sort_keys=True)}"

    built.globals["lookup"] = lookup
    return built


def role_var(built: Environment, name: str) -> Any:
    """Args:
        built: the environment from ``environment()``.
        name: a variable of the role's vars/main.yml.

    Returns:
        The variable's value, native when it is a single expression.
    """
    raw = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))[name]
    match = _EXPRESSION.fullmatch(str(raw))
    if match:
        return built.compile_expression(match.group(1))(application_id=APPLICATION_ID)
    return built.from_string(str(raw)).render(application_id=APPLICATION_ID)


def compose(
    override: dict[str, Any] | None = None, names: tuple[str, ...] = COMPOSE_VARS
) -> str:
    """Args:
        override: the ``services`` keys an inventory sets for the role.
        names: the role variables the template reads.

    Returns:
        The role's compose template, rendered with echoing lookups.
    """
    built = environment(override)
    return built.from_string(read_text(str(ROLE / ROLE_FILE_TEMPL_COMPOSE))).render(
        application_id=APPLICATION_ID,
        entity_name=entity_name(APPLICATION_ID),
        IS_COMPOSE_MODE=True,
        **{name: role_var(built, name) for name in names},
    )


def _render_jinja(built: Environment):
    return lambda expression: built.from_string(expression).render(
        application_id=APPLICATION_ID
    )


def mounts(service: str, override: dict[str, Any] | None = None) -> str:
    """Args:
        service: the compose service whose mounts to render.
        override: the ``services`` keys an inventory sets for the role.

    Returns:
        The service's ``volumes:`` block as ``container_volumes`` renders it.
    """
    return container_volumes(
        applications(override),
        APPLICATION_ID,
        service,
        render_jinja=_render_jinja(environment(override)),
    )


def top_volumes(override: dict[str, Any] | None = None) -> str:
    """Args:
        override: the ``services`` keys an inventory sets for the role.

    Returns:
        The stack's top-level ``volumes:`` block as ``compose_volumes`` renders it.
    """
    return compose_volumes(
        applications(override),
        APPLICATION_ID,
        dir_var_lib=DIR_VAR_LIB,
        render_jinja=_render_jinja(environment(override)),
    )


def certs_env(override: dict[str, Any] | None = None) -> str:
    """Args:
        override: the ``services`` keys an inventory sets for the role.

    Returns:
        The certificate issuer's environment the deploy hands to certs.sh.
    """
    built = environment(override)
    return built.from_string(read_text(str(CERTS_ENV))).render(
        CACHE_PACKAGE_TLS_HOSTS=TLS_HOSTS,
        **{name: role_var(built, name) for name in CERTS_VARS},
    )


def renders(
    override: dict[str, Any] | None = None, names: tuple[str, ...] = COMPOSE_VARS
) -> dict[str, str]:
    """Args:
        override: the ``services`` keys an inventory sets for the role.
        names: the role variables the compose template reads.

    Returns:
        Every render the role's mount and port wiring reaches, keyed by name.
    """
    return {
        "compose": compose(override, names),
        "certs_env": certs_env(override),
        "volumes": top_volumes(override),
        **{f"mounts_{service}": mounts(service, override) for service in SERVICES},
    }


def fixture() -> dict[str, str]:
    """Returns:
    Every render captured before the paths and ports became configurable.
    """
    return json.loads(read_text(str(FIXTURE)))
