"""Render what the package cache needs beside its role, from the declarations.

The role deploys the frontend and owns the templates and their tuning; the dev
compose stack has no inventory to render them with and comes through here
instead. Every value still has one home: the hosts and repositories come from
the ``cache:`` declarations, the nginx tuning from the role's ``vars/main.yml``,
and only the backend address differs, because the dev stack reaches Nexus over
a compose network alias while the role reaches it by its configured container.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader, select_autoescape

from utils.cache.hosts import (
    host_records,
    hosts_serving,
    origin_of,
    repo_named,
    repo_records,
)
from utils.cache.pin import agreed
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VOLUMES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

ROLE = "svc-cache-package"
ROLE_DIR = PROJECT_ROOT / "roles" / ROLE
ROLE_VARS = ROLE_DIR / ROLE_FILE_VARS_MAIN
WEBSERVER_VARS = PROJECT_ROOT / "group_vars" / "all" / "04_webserver.yml"
TEMPLATE_DIRS = (ROLE_DIR / "templates", PROJECT_ROOT / "compose" / "templates")
UPSTREAMS_TEMPLATE = "upstreams.conf.j2"
CONSUMER_TEMPLATE = "cache-consumer.yml.jinja"
CONSUMER = "compose.cache-consumer.yml"

PYPI_REPO = "pypi-proxy"
NPM_REPO = "npm-proxy"

BACKEND = "http://package-cache:8081"
TEMPLATED = "{{"


def _mount_target(volume: str, service: str) -> str:
    """Return where *volume* is mounted on *service*, from meta/volumes.yml.

    The role reads the same value through the ``volume`` lookup, which needs
    an inventory; the dev stack has none and reads the declaration directly,
    so the mount point still has one home.

    Args:
        volume: the key in meta/volumes.yml.
        service: the service whose mount to return.
    """
    declared = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_VOLUMES)) or {}
    mounts = (declared.get(volume) or {}).get("mounts") or []
    return next(
        (
            m["target"]
            for m in mounts
            if m.get("service") == service and m.get("target")
        ),
        "",
    )


def _tuning() -> dict[str, str]:
    """Return the role's plain nginx settings, keyed as the template names them.

    A value the role builds from its inventory is skipped: it has no meaning
    without one, and the dev stack supplies its own.
    """
    loaded = load_yaml_any(str(ROLE_VARS), default_if_missing={}) or {}
    return {
        key: value
        for key, value in loaded.items()
        if key.startswith("CACHE_PACKAGE_") and TEMPLATED not in str(value)
    }


def _render(template: str, **context) -> str:
    env = Environment(
        loader=FileSystemLoader([str(path) for path in TEMPLATE_DIRS]),
        trim_blocks=True,
        keep_trailing_newline=True,
        autoescape=select_autoescape(default_for_string=False),
    )
    return env.get_template(template).render(**context)


def _webserver_http2() -> bool:
    return load_yaml_any(str(WEBSERVER_VARS))["WEBSERVER_HTTP2_ENABLED"]


def upstreams_conf() -> str:
    """Return the nginx frontend configuration the declarations produce."""
    return _render(
        UPSTREAMS_TEMPLATE,
        WEBSERVER_HTTP2_ENABLED=_webserver_http2(),
        CACHE_PACKAGE_UPSTREAMS=list(host_records().values()),
        CACHE_PACKAGE_REPOS=repo_records(),
        CACHE_PACKAGE_BACKEND=BACKEND,
        CACHE_PACKAGE_CERTS_DIR=_mount_target("frontend_certs", "frontend"),
        **_tuning(),
    )


def _served(served: Mapping[str, dict] | None) -> set[str]:
    """Args:
        served: the host records the pinned checkout declares, None for no pin.

    Returns:
        The declared hosts the frontend serves: all of them without a pin,
        else the ones the pin declares identically.
    """
    own = host_records()
    return set(own) if served is None else agreed(own, dict(served))


def cache_consumer_yml(served: Mapping[str, dict] | None = None) -> str:
    """Return the compose override that points every served host at the frontend.

    Args:
        served: the host records the pinned checkout declares, None for no pin.
    """
    hosts = _served(served)
    return _render(
        CONSUMER_TEMPLATE,
        CACHE_PACKAGE_HOSTNAMES=[
            host
            for host, record in host_records().items()
            if host in hosts and record["hijack"]
        ],
    )


def pip_conf() -> str:
    """Return the pip configuration pointing at the cached PyPI hosts."""
    repo = repo_named(PYPI_REPO)
    hosts = hosts_serving(PYPI_REPO)
    origin = origin_of(repo) if repo else ""
    index = next((entry for entry in hosts if entry.host == origin), None)
    if index is None:
        raise SystemExit(
            f"no cache: host declares itself the origin of {PYPI_REPO}, so pip "
            "has no index URL to point at"
        )
    return _render(
        "pip.conf.jinja",
        CACHE_PACKAGE_PYPI_INDEX=f"{index.scheme()}://{index.host}/simple/",
        CACHE_PACKAGE_PYPI_HOSTS=[entry.host for entry in hosts],
    )


def npmrc() -> str:
    """Return the npm configuration pointing at the cached registry."""
    hosts = hosts_serving(NPM_REPO)
    if not hosts:
        raise SystemExit(f"no cache: host serves {NPM_REPO}, so npm has no registry")
    registry = hosts[0]
    return _render(
        "npmrc.jinja",
        CACHE_PACKAGE_NPM_REGISTRY=f"{registry.scheme()}://{registry.host}/",
    )


def _write(target: Path, content: str) -> Path:
    """Write ``content`` to ``target``, replacing a file it cannot overwrite.

    A container rendering these carries its own uid into the bind mount, so it
    leaves a file the host may no longer write while the directory stays the
    host's. Unlinking needs the directory, not the file, which is why
    replacing the inode gets through where overwriting does not.

    Args:
        target: the generated file.
        content: what it should hold.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_text(content, encoding="utf-8")
    except PermissionError:
        target.unlink()
        target.write_text(content, encoding="utf-8")
    return target


def render_artifacts(
    repo_root: Path, conf_path: Path, served: Mapping[str, dict] | None = None
) -> list[Path]:
    """
    Args:
        repo_root: the checkout being generated for.
        conf_path: where INFINITO_CACHE_PACKAGE_FRONTEND_CONF points.
        served: the host records the pinned checkout declares, None for no
            pin file; only those hosts are hijacked to the frontend.

    Returns:
        Every generated file that was written.
    """
    consumer_dir = repo_root / "compose" / "package-cache"
    written = [
        _write(repo_root / CONSUMER, cache_consumer_yml(served)),
        _write(consumer_dir / "pip.conf", pip_conf()),
        _write(consumer_dir / "npmrc", npmrc()),
    ]
    if conf_path.is_relative_to(repo_root):
        written.append(_write(conf_path, upstreams_conf()))
    return written
