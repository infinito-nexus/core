"""The cache roles inside the infra runner: their inventory, host paths, containers and deploy."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from utils.env.handlers.infinito.cache.conf import KEY as FRONTEND_CONF_KEY
from utils.infra import SERVICE
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

INVENTORY_TEMPLATE = Path("inventories") / "development" / "infra.yml.j2"
INVENTORY_RENDERED = Path("inventories") / "development" / "infra.rendered.yml"
INVENTORY_KEYS = {
    "idle_days": "INFINITO_CACHE_MAX_IDLE_DAYS",
    "package_cap": "INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX",
    "package_data": "INFINITO_CACHE_PACKAGE_HOST_PATH",
    "package_port": "INFINITO_CACHE_PACKAGE_PORT",
    "frontend_ca": "INFINITO_CACHE_PACKAGE_FRONTEND_CA_DIR",
    "frontend_certs": "INFINITO_CACHE_PACKAGE_FRONTEND_CERTS_DIR",
    "frontend_map": FRONTEND_CONF_KEY,
    "registry_cap": "INFINITO_CACHE_REGISTRY_MAX_SIZE",
    "registry_auth": "INFINITO_CACHE_REGISTRY_AUTH",
    "registry_mirror": "INFINITO_CACHE_REGISTRY_HOST_PATH",
    "registry_ca": "INFINITO_CACHE_REGISTRY_CA_HOST_PATH",
}
PATH_NAMES = (
    "package_data",
    "frontend_ca",
    "frontend_certs",
    "registry_mirror",
    "registry_ca",
)
REGISTRIES_KEY = "INFINITO_CACHE_REGISTRIES"
CACHE_ROLES = ("svc-registry-cache", "svc-cache-package")
OPT_IN_ROLES = {
    "INFINITO_INFRA_SEMAPHORE": "web-app-semaphore",
    "INFINITO_INFRA_CHECKMK": "web-app-checkmk",
}
OPT_IN_VALUES = ("", "true", "false")
PRUNE_MODULE = "cli.administration.infra"
PRUNE_ACTION = "inventory-prune"
CACHE_SERVICES = {
    "registry": ("svc-registry-cache", "cache"),
    "package": ("svc-cache-package", "package"),
    "frontend": ("svc-cache-package", "frontend"),
}


def infra_roles(env: Mapping[str, str]) -> tuple[str, ...]:
    """Args:
        env: environment holding the opt-in of every optional infra role.

    Returns:
        The cache roles, then each role of :data:`OPT_IN_ROLES` whose opt-in
        is ``true``; an unset or ``false`` opt-in adds nothing.

    Raises:
        ValueError: an opt-in is set to anything but ``true`` or ``false``.
    """
    return (*CACHE_ROLES, *(role for role, on in _opt_ins(env).items() if on))


def opted_out(env: Mapping[str, str]) -> tuple[str, ...]:
    """Args:
        env: environment holding the opt-in of every optional infra role.

    Returns:
        Each role of :data:`OPT_IN_ROLES` whose opt-in is unset or ``false``.

    Raises:
        ValueError: an opt-in is set to anything but ``true`` or ``false``.
    """
    return tuple(role for role, on in _opt_ins(env).items() if not on)


def _opt_ins(env: Mapping[str, str]) -> dict[str, bool]:
    values = {key: (env.get(key) or "").strip() for key in OPT_IN_ROLES}
    invalid = [
        f"{key}={value!r}"
        for key, value in values.items()
        if value not in OPT_IN_VALUES
    ]
    if invalid:
        raise ValueError(f"[infra] {', '.join(invalid)}: set true or false")
    return {role: values[key] == "true" for key, role in OPT_IN_ROLES.items()}


def drop_roles(inventory: dict, roles: Sequence[str]) -> list[str]:
    """Args:
        inventory: an ``all.children`` inventory mapping, changed in place.
        roles: the application ids whose groups go.

    Returns:
        The roles whose group was present and is removed.
    """
    children = (inventory.get("all") or {}).get("children") or {}
    dropped = [role for role in roles if role in children]
    for role in dropped:
        del children[role]
    return dropped


def render_inventory(root: Path, env: Mapping[str, str]) -> Path:
    """Args:
        root: repository root holding the template.
        env: environment holding the cache caps, paths, registries and idle window.

    Returns:
        The rendered host vars of the infra inventory, beside the template.

    Raises:
        KeyError: a cap, a path, the pinned frontend map, the registries or
            the idle window is unset.
    """
    from jinja2 import (
        Environment,
        FileSystemLoader,
        StrictUndefined,
        select_autoescape,
    )

    template = root / INVENTORY_TEMPLATE
    jinja = Environment(
        loader=FileSystemLoader(str(template.parent)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        variable_start_string="[[",
        variable_end_string="]]",
        block_start_string="[%",
        block_end_string="%]",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=select_autoescape(default_for_string=False),
    )
    values = {name: env[key] for name, key in INVENTORY_KEYS.items()}
    body = jinja.get_template(template.name).render(
        registries=env[REGISTRIES_KEY].split(), **values
    )
    rendered = root / INVENTORY_RENDERED
    rendered.write_text(body, encoding="utf-8")
    return rendered


def unmounted(base: Path, pins: Path, env: Mapping[str, str]) -> list[str]:
    """Args:
        base: the cache base the runner mounts read-write at its host path.
        pins: the pin root the runner mounts read-only at its host path.
        env: environment holding the host paths the infra roles, the tools
            services and the idle units bind or read inside the runner.

    Returns:
        One refusal per set host path outside the roots it may live in, which
        the runner's inner docker would resolve against its own filesystem.
        Cache data, the tools models and the tools stamps must lie below
        ``base``; the frontend map below ``pins``, the only root whose map
        ``make cache-apply`` replaces.
    """
    from utils.env.handlers.infinito.tools.idle import STAMP_DIR_KEY
    from utils.env.handlers.infinito.tools.models import KEY as MODELS_KEY

    data = (MODELS_KEY, STAMP_DIR_KEY, *(INVENTORY_KEYS[name] for name in PATH_NAMES))
    checks = [*((key, base) for key in data), (FRONTEND_CONF_KEY, pins)]
    return [
        f"[infra] {key}={env[key]} lies outside {root}, which the infra runner "
        f"mounts for it; move it below {root}"
        for key, root in checks
        if env.get(key) and not Path(env[key]).is_relative_to(root)
    ]


def cache_container(root: Path, kind: str) -> str:
    """Args:
        root: repository root.
        kind: ``registry``, ``package`` or ``frontend``.

    Returns:
        The container name the cache role gives that service inside the runner.
    """
    from utils.cache.yaml import load_yaml

    role, key = CACHE_SERVICES[kind]
    return load_yaml(root / "roles" / role / ROLE_FILE_META_SERVICES)[key]["name"]


def cache_port(root: Path, kind: str, protocol: str) -> int:
    """Args:
        root: repository root.
        kind: ``registry``, ``package`` or ``frontend``.
        protocol: the key below ``ports.internal``, such as ``http``.

    Returns:
        The port that service listens on inside its own container, which a
        ``docker exec`` into it reaches on loopback.

    Raises:
        KeyError: the service declares no internal port for *protocol*.
    """
    from utils.cache.yaml import load_yaml

    role, key = CACHE_SERVICES[kind]
    services = load_yaml(root / "roles" / role / ROLE_FILE_META_SERVICES)
    return services[key]["ports"]["internal"][protocol]


def deploy_commands(
    argv: Sequence[str],
    checkout: Path,
    vars_file: Path,
    inventory_dir: Path,
    roles: Sequence[str],
    pruned: Sequence[str] = (),
) -> list[list[str]]:
    """Args:
        argv: compose call of the infra stack.
        checkout: checkout inside the runner, at its host path.
        vars_file: rendered host vars, below ``checkout``.
        inventory_dir: inventory the runner provisions and deploys.
        roles: application ids the inventory includes.
        pruned: application ids whose groups leave the inventory between the
            provision and the deploy.

    Returns:
        The commands that deploy ``roles`` inside the runner. The runner image
        is the toolchain stage, whose venv and collections are built in, and it
        mounts ``checkout`` read-only, so no command reinstalls from a tree or
        runs the deploy's build step, which writes into it. ``PYTHONPATH`` is
        ``checkout``, as ``scripts/meta/env/python.sh`` sets it on a host.
    """
    pythonpath = f"PYTHONPATH={checkout}"
    inside = [*argv, "exec", "-T", "-w", str(checkout), "-e", pythonpath, SERVICE]
    python = [*inside, "python", "-m"]
    return [
        [*inside, "systemctl", "daemon-reload"],
        [
            *python,
            "cli.administration.inventory.provision",
            str(inventory_dir),
            "--include",
            *roles,
            "--vars-file",
            str(vars_file),
        ],
        *(
            [
                [
                    *python,
                    PRUNE_MODULE,
                    PRUNE_ACTION,
                    str(inventory_dir / "devices.yml"),
                    *pruned,
                ]
            ]
            if pruned
            else []
        ),
        [
            *python,
            "cli.administration.deploy.dedicated",
            str(inventory_dir / "devices.yml"),
            "--password-file",
            str(inventory_dir / ".password"),
            "--skip-backup",
            "--skip-build",
            "--skip-cleanup",
            "--skip-pull",
        ],
    ]
