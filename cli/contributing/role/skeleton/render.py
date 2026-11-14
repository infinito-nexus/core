from __future__ import annotations

import ipaddress
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jinja2

from cli.contributing.network.address.suggest.__main__ import (
    gap_first_subnets,
    smallest_prefix,
)
from cli.contributing.network.ports.suggest.__main__ import suggest_single_ports
from utils.agents.naming import IAM_USERNAME_MAX_LENGTH
from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.distros import galaxy_platforms
from utils.licensing.rights import table
from utils.meta.port_bands import PortBandsError
from utils.meta.scan import iter_role_dirs, iter_subnets
from utils.roles.custom import PREFIX
from utils.roles.entity.name import entity_name
from utils.roles.mapping import ROLE_FILE_META_DOMAINS

if TYPE_CHECKING:
    from cli.contributing.role.skeleton.manifest import Manifest

TEMPLATE_DIR = PROJECT_ROOT / "templates" / "roles" / "skeleton"
NETWORKS_FILE = PROJECT_ROOT / "group_vars" / "all" / "08_networks.yml"
STACK_BRIDGE = PROJECT_ROOT / "roles" / "svc-stack" / "files" / "bridge.yml"
VERBATIM = {"tasks/utils/stack.yml": STACK_BRIDGE}
SUFFIX = ".tmpl"
SUBNET_CLIENTS = 254
PORT_SCOPE = "local"
PORT_CATEGORY = "http"
DOMAIN_TEMPLATE = "{name}.{{{{ DOMAIN_PRIMARY }}}}"
BRAND_ROLE = "web-app-cst-brand"
SERVICE_KEYS = frozenset(
    {
        "container_backup",
        "dashboard",
        "design",
        "docs",
        "email",
        "ldap",
        "logout",
        "mariadb",
        "matomo",
        "openresty",
        "postgres",
        "prometheus",
        "redis",
        "semaphore",
        "sso",
        "stack",
        "tor",
    }
)


class RenderError(Exception):
    """The manifest cannot be rendered into the target core checkout.

    Args:
        errors: one ``<field>: <problem>`` line per reason.
    """

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


def application_id(manifest: Manifest) -> str:
    """Return the role name a manifest renders to.

    Args:
        manifest: the validated manifest.
    """
    return f"{PREFIX}{manifest.name}"


def canonical_domain(manifest: Manifest) -> str:
    """Return the canonical domain entry of the rendered ``meta/domains.yml``.

    Args:
        manifest: the validated manifest.
    """
    return DOMAIN_TEMPLATE.format(name=manifest.name)


def _domains(role_dir: Path) -> set[str]:
    data = load_yaml_any(str(role_dir / ROLE_FILE_META_DOMAINS), default_if_missing={})
    if not isinstance(data, dict):
        return set()
    found: set[str] = set()
    for key in ("canonical", "aliases"):
        value = data.get(key)
        entries = list(value.values()) if isinstance(value, dict) else value
        for entry in entries if isinstance(entries, list) else []:
            items = entry if isinstance(entry, list) else [entry]
            found.update(item for item in items if isinstance(item, str))
    return found


def collisions(manifest: Manifest) -> list[str]:
    """Return why the manifest's names clash with the roles of the core checkout.

    Args:
        manifest: the validated manifest.

    Returns:
        One ``name: <problem>`` line per role whose entity name or domain the
        rendered role would take over, and one when the entity name is a
        service key of the skeleton's ``meta/services.yml``.
    """
    role = application_id(manifest)
    entity = entity_name(role)
    domain = canonical_domain(manifest)
    errors = []
    if entity in SERVICE_KEYS:
        errors.append(
            f"name: entity name '{entity}' is a service key of the rendered "
            "meta/services.yml; pick another name"
        )
    for role_dir in iter_role_dirs():
        if role_dir.name == role:
            continue
        if entity_name(role_dir.name) == entity:
            errors.append(
                f"name: entity name '{entity}' collides with the in-tree role "
                f"{role_dir.name}"
            )
        if domain in _domains(role_dir):
            errors.append(
                f"name: canonical domain '{domain}' is already served by {role_dir.name}"
            )
    return errors


def _subnet_pool() -> ipaddress.IPv4Network:
    data = load_yaml_any(str(NETWORKS_FILE), default_if_missing={}) or {}
    pool = data.get("NETWORK_ROLE_SUBNET_POOL")
    if isinstance(pool, str) and "{{" in pool:
        pool = jinja2.Template(
            pool, autoescape=jinja2.select_autoescape(default_for_string=False)
        ).render(**data)
    return ipaddress.IPv4Network(str(pool).strip())


def allocate_subnet() -> str:
    """Return the first free role subnet of ``NETWORK_ROLE_SUBNET_POOL``.

    Returns:
        A ``/24`` that overlaps no ``local.subnet`` or stream relay subnet of
        the core checkout.

    Raises:
        RenderError: the pool holds no free subnet.
    """
    pool = _subnet_pool()
    prefix = smallest_prefix(SUBNET_CLIENTS)
    occupied = [net for _owner, net in iter_subnets()]
    for candidate in gap_first_subnets(pool, prefix, occupied):
        if not any(candidate.overlaps(net) for net in occupied):
            return str(candidate)
    raise RenderError([f"networks: {pool} holds no free /{prefix} subnet"])


def allocate_port() -> int:
    """Return the lowest free local HTTP port of ``PORT_BANDS``.

    Raises:
        RenderError: the band is exhausted or not declared.
    """
    try:
        ports, _gaps = suggest_single_ports(PORT_SCOPE, PORT_CATEGORY, 1, None)
    except (SystemExit, PortBandsError) as exc:
        raise RenderError([f"port: {exc}"]) from exc
    return ports[0]


def _yaml_scalar(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _title(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("-"))


def context(manifest: Manifest, local_port: int, subnet: str) -> dict[str, Any]:
    """Return the variables every skeleton template is rendered with.

    Args:
        manifest: the validated manifest.
        local_port: the allocated local HTTP port.
        subnet: the allocated role subnet.
    """
    role = application_id(manifest)
    return {
        "kind": manifest.kind,
        "name": manifest.name,
        "brand": BRAND_ROLE,
        "application_id": role,
        "entity": entity_name(role),
        "prefix": entity_name(role).upper().replace("-", "_"),
        "run_once": "run_once_" + role.replace("-", "_"),
        "title": _title(manifest.name),
        "domain": canonical_domain(manifest),
        "description": manifest.description,
        "homepage": manifest.homepage,
        "license": manifest.license,
        "license_url": table()[manifest.license]["url"],
        "repository": manifest.repository,
        "version": manifest.version,
        "port": manifest.port,
        "local_port": local_port,
        "subnet": subnet,
        "database": manifest.database,
        "login": manifest.login,
        "username_max_length": IAM_USERNAME_MAX_LENGTH,
        "features": manifest.features,
        "environment": [
            (key, json.dumps(value, ensure_ascii=False))
            for key, value in manifest.environment
        ],
        "volumes": manifest.volumes,
        "platforms": galaxy_platforms(),
    }


def _environment() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        block_start_string="[%",
        block_end_string="%]",
        variable_start_string="[[",
        variable_end_string="]]",
        comment_start_string="[#",
        comment_end_string="#]",
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=jinja2.StrictUndefined,
        autoescape=jinja2.select_autoescape(),
    )
    env.filters["yaml"] = _yaml_scalar
    return env


def render_files(variables: dict[str, Any]) -> dict[str, str]:
    """Render every skeleton template.

    Args:
        variables: the result of :func:`context`.

    Returns:
        Role-relative path to file content; a template that renders blank is
        left out, which is how a file exists only for some manifests. Every
        ``VERBATIM`` file is copied unchanged from core.
    """
    env = _environment()
    out: dict[str, str] = {}
    for source in sorted(TEMPLATE_DIR.rglob(f"*{SUFFIX}")):
        relative = source.relative_to(TEMPLATE_DIR).as_posix()
        text = env.get_template(relative).render(**variables)
        if text.strip():
            out[relative.removesuffix(SUFFIX)] = text
    for relative, source in VERBATIM.items():
        out[relative] = read_text(str(source))
    return out


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _write(role_dir: Path, files: dict[str, str]) -> None:
    role_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{role_dir.name}.", dir=role_dir.parent))
    try:
        staging.chmod(0o755)
        for relative, text in files.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        if os.path.lexists(role_dir):
            _remove(role_dir)
        staging.rename(role_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def render(manifest: Manifest, target: Path, *, force: bool) -> Path:
    """Write ``<target>/web-app-cst-<name>/`` from a validated manifest.

    Args:
        manifest: the validated manifest.
        target: the directory the role directory is created in.
        force: replace an existing role directory.

    Returns:
        The absolute path of the written role directory.

    Raises:
        RenderError: a name clashes with the core checkout, the role directory
            exists without ``force``, or no port or subnet is free; nothing is
            written then.
    """
    role_dir = Path(target).absolute() / application_id(manifest)
    errors = collisions(manifest)
    if os.path.lexists(role_dir) and not force:
        errors.append(f"target: {role_dir} exists; pass --force to replace it")
    if errors:
        raise RenderError(errors)
    container = manifest.kind == "container"
    files = render_files(
        context(
            manifest,
            allocate_port() if container else 0,
            allocate_subnet() if container else "",
        )
    )
    _write(role_dir, files)
    return role_dir
