from __future__ import annotations

import fcntl
import ipaddress
import os
import sys
import urllib.parse
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.evict import floor_violation, free_bytes, load_settings, usages
from utils.networks.infra import RUNNER_CONTAINER_KEY, SUBNET_KEY, runner_ip
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

    from utils.cache.evict import Usage

SERVICE = "runner"
NETWORK = "infinito-infra"
ROOTS_OVERRIDE = "build/compose/infra-roots.override.yml"
ROOTS_KEY = "INFINITO_WORKTREE_ROOTS"
GATEWAY_PORT_KEY = "INFINITO_TOOLS_TRANSLATE_PORT"
LOCK_NAME = "infra.lock"
OWNER_NAME = "infra.owner"
LEGACY_CONTAINERS = (
    "infinito-registry-cache",
    "infinito-package-cache",
    "infinito-package-cache-frontend",
)
LEGACY_REGISTRY = LEGACY_CONTAINERS[0]
LEGACY_FORMAT = (
    "{{range $name, $net := .NetworkSettings.Networks}}"
    "{{println $name $net.IPAddress}}{{end}}"
)
PROXY_FORMAT = "{{.HTTPSProxy}} {{.HTTPProxy}}"
STOP_GRACE = "120"
BRIDGE = "host-proxy"
BRIDGE_NAME = "infra.bridge"
BRIDGE_OVERRIDE = "build/compose/infra-bridge.override.yml"
LOOPBACK = "127.0.0.1"
INVENTORY_TEMPLATE = Path("inventories") / "development" / "infra.yml.j2"
INVENTORY_RENDERED = Path("inventories") / "development" / "infra.rendered.yml"
INVENTORY_KEYS = {
    "idle_days": "INFINITO_CACHE_MAX_IDLE_DAYS",
    "package_cap": "INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX",
    "package_data": "INFINITO_CACHE_PACKAGE_HOST_PATH",
    "package_port": "INFINITO_CACHE_PACKAGE_PORT",
    "frontend_ca": "INFINITO_CACHE_PACKAGE_FRONTEND_CA_DIR",
    "frontend_certs": "INFINITO_CACHE_PACKAGE_FRONTEND_CERTS_DIR",
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
CACHE_SERVICES = {
    "registry": ("svc-registry-cache", "cache"),
    "package": ("svc-cache-package", "package"),
    "frontend": ("svc-cache-package", "frontend"),
}
INFRA_UP = (sys.executable, "-m", "cli.administration.infra", "up")


def worktree_roots(raw: str, primary: Path, home: Path) -> list[Path]:
    """Args:
        raw: colon-separated INFINITO_WORKTREE_ROOTS value.
        primary: the primary checkout, mounted when ``raw`` is empty.
        home: home directory holding ``.local/share/worktrees``.

    Returns:
        The roots the runner sees, each at its host path.

    Raises:
        SystemExit: a declared root is not an absolute directory.
    """
    declared = [Path(part) for part in raw.split(":") if part.strip()]
    if not declared:
        return [primary, home / ".local" / "share" / "worktrees"]
    for root in declared:
        if not root.is_absolute() or not root.is_dir():
            raise SystemExit(
                f"{ROOTS_KEY}: {root} is not an existing absolute directory"
            )
    return declared


def floor_refusal(env: Mapping[str, str], build: Usage) -> list[str]:
    """Args:
        env: environment holding the cache caps, paths and disk floor.
        build: the measured host build cache.

    Returns:
        The refusal lines of cache-evict, or nothing when the floor holds.
    """
    settings = load_settings(env)
    paths = [cache.path for cache in settings.caches if cache.path is not None]
    return floor_violation(settings, usages(settings, build), free_bytes(paths))


def base_refusal(path: Path) -> list[str]:
    """Args:
        path: the cache base the lock, the owner marker and the idle units
            land in.

    Returns:
        The refusal line while this user cannot write *path*, naming the
        one-time step that hands it over; nothing otherwise.
    """
    if path.is_dir() and os.access(path, os.W_OK | os.X_OK):
        return []
    step = (
        f'sudo chown "$USER": {path}'
        if path.is_dir()
        else f'sudo install -d -o "$USER" {path}'
    )
    line = (
        f"[infra] this user cannot write the cache base {path}, where the lock, "
        f"the owner marker and the idle units land; hand it over once: {step}"
    )
    return [line]


def legacy_refusal(names: str | None) -> list[str]:
    """Args:
        names: the names of the running host containers, one per line; None
            when the host could not be asked.

    Returns:
        The refusal lines while a container of the per-checkout cache stack
        runs on the cache base the runner takes over, or the host cannot be
        asked; nothing otherwise.
    """
    if names is None:
        return [
            "[infra] docker ps failed, so the legacy cache stack cannot be ruled out"
        ]
    found = legacy_running(names)
    if not found:
        return []
    line = (
        f"[infra] the legacy cache stack still runs ({', '.join(found)}) on the "
        "cache base the infra runner takes over; stop it in the checkout that "
        "owns it first, or let make infra-up takeover=true stop it"
    )
    return [line]


def legacy_running(names: str) -> list[str]:
    """Args:
        names: the names of the running host containers, one per line.

    Returns:
        Every running container of the legacy cache stack, in LEGACY_CONTAINERS
        order.
    """
    return [name for name in LEGACY_CONTAINERS if name in names.split()]


def proxy_bridge(proxies: str, legacy: str) -> tuple[str, str] | None:
    """Args:
        proxies: the host daemon's HTTPS and HTTP proxy URLs, blank-separated,
            empty when it has none.
        legacy: one line per network of the running legacy registry cache,
            its name and that container's address there.

    Returns:
        The network and address of the legacy registry cache the host daemon
        pulls through, so the runner takes that address over; None while the
        daemon names no such address.
    """
    hosts = {urllib.parse.urlsplit(url).hostname for url in proxies.split()}
    for row in legacy.splitlines():
        name, _, address = row.strip().partition(" ")
        if name and name != NETWORK and address and address in hosts:
            return name, address
    return None


def read_bridge(path: Path) -> tuple[str, str] | None:
    """Args:
        path: the bridge record a takeover writes next to the lock.

    Returns:
        The network and address recorded there, None without a record.
    """
    if not path.is_file():
        return None
    record = path.read_text()  # nocheck: cache-read rewritten by each takeover
    network, _, address = record.strip().partition(" ")
    return network, str(ipaddress.IPv4Address(address))


def write_bridge(root: Path, network: str, address: str) -> str:
    """Args:
        root: repository root the compose files are relative to.
        network: the external host network the runner joins.
        address: the runner's fixed address on it.

    Returns:
        The override path relative to *root*.
    """
    from utils.cache.yaml import dump_yaml

    target = root / BRIDGE_OVERRIDE
    staged = target.with_suffix(".tmp")
    dump_yaml(
        staged,
        {
            "services": {SERVICE: {"networks": {BRIDGE: {"ipv4_address": address}}}},
            "networks": {BRIDGE: {"external": True, "name": network}},
        },
    )
    staged.replace(target)
    return BRIDGE_OVERRIDE


@contextmanager
def machine_lock(path: Path) -> Iterator[None]:
    """Args:
    path: lock file every checkout of the machine shares.
    """
    with path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def up(
    argv: Sequence[str],
    *,
    refusal: Callable[[], list[str]],
    running: Callable[[], bool],
    run: Callable[[list[str]], None],
    lock: Path,
    recreate: bool,
    takeover: Sequence[str],
    bridge: tuple[str, str] | None,
    installs: Callable[[], Sequence[list[str]]],
) -> int:
    """Args:
        argv: compose call of the infra stack.
        refusal: floor check, run before anything starts.
        running: whether the runner already runs.
        run: executes a command and raises on failure.
        lock: machine lock file; the owner marker OWNER_NAME lands next to it
            before the runner starts and stays after a failed start or a down,
            unless a takeover rolls back.
        recreate: apply changed inputs to a running runner (infra-update).
        takeover: running legacy cache containers, stopped inside the lock
            right after the marker, which recreates a running runner; when
            anything after that stop fails, the runner stops, they start
            again, and the marker and the bridge record go before the failure
            propagates.
        bridge: the legacy network and address *argv* joins the runner to,
            recorded as BRIDGE_NAME next to the lock so later calls keep it.
        installs: builds the commands run after the runner is up, such as the
            idle timer; called only then, so a refusal writes nothing.

    Returns:
        2 on a refusal, else 0.
    """
    lines = refusal()
    if lines:
        print("\n".join(lines), file=sys.stderr)
        return 2
    with machine_lock(lock):
        written = (lock.with_name(OWNER_NAME), lock.with_name(BRIDGE_NAME))
        written[0].write_text(f"{NETWORK}\n")
        try:
            if bridge:
                written[1].write_text(" ".join(bridge) + "\n")
            if takeover:
                run(["docker", "stop", "-t", STOP_GRACE, *takeover])
            if running() and not (recreate or takeover):
                print("the infra runner already runs", flush=True)
                return 0
            run([*argv, "up", "--detach", "--wait"])
            for command in installs():
                run(list(command))
        except BaseException:
            if takeover:
                _roll_back(argv, takeover, written, run)
            raise
    return 0


def _roll_back(
    argv: Sequence[str],
    names: Sequence[str],
    written: Sequence[Path],
    run: Callable[[list[str]], None],
) -> None:
    for command in ([*argv, "stop"], ["docker", "start", *names]):
        try:
            run(command)
        except Exception as exc:  # noqa: BLE001
            print(
                f"[infra] rollback: {' '.join(command)} failed: {exc}", file=sys.stderr
            )
    for path in written:
        path.unlink(missing_ok=True)
    print(
        f"[infra] takeover rolled back: {', '.join(names)} started again; "
        f"{' and '.join(path.name for path in written)} removed",
        file=sys.stderr,
    )


def down(argv: Sequence[str], run: Callable[[list[str]], None], lock: Path) -> int:
    """Args:
    argv: compose call of the infra stack.
    run: executes a command and raises on failure.
    lock: machine lock file.
    """
    with machine_lock(lock):
        run([*argv, "down"])
    return 0


def status(
    running: bool, env: Mapping[str, str], addressable: Mapping[str, bool]
) -> dict[str, object]:
    """Args:
        running: whether the runner runs.
        env: environment holding the runner name, the subnet and the gateway port.
        addressable: per tools project, whether ``docker compose -p`` reaches it.

    Returns:
        JSON-ready runner state with the gateway URL the i18n targets take.
    """
    return {
        "container": env[RUNNER_CONTAINER_KEY],
        "running": running,
        "tools_addressable": dict(addressable),
        "address": runner_ip(env[SUBNET_KEY]),
        "gateway": f"http://{LOOPBACK}:{env[GATEWAY_PORT_KEY]}",
    }


def render_inventory(root: Path, env: Mapping[str, str]) -> Path:
    """Args:
        root: repository root holding the template.
        env: environment holding the cache caps, paths, registries and idle window.

    Returns:
        The rendered host vars of the infra inventory, beside the template.

    Raises:
        KeyError: a cap, a path, the registries or the idle window is unset.
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
        env: environment holding the host paths the infra roles bind.

    Returns:
        One refusal per set host path outside the roots it may live in, which
        the runner's inner docker would resolve against its own filesystem.
        Cache data must lie below ``base``; a pin path below either root.
    """
    from utils.env.handlers.infinito.cache.conf import KEY as FRONTEND_CONF_KEY
    from utils.env.handlers.infinito.tools.models import KEY as MODELS_KEY

    data = (MODELS_KEY, *(INVENTORY_KEYS[name] for name in PATH_NAMES))
    checks = [*((key, (base,)) for key in data), (FRONTEND_CONF_KEY, (base, pins))]
    return [
        f"[infra] {key}={env[key]} lies outside "
        f"{' and '.join(str(root) for root in roots)}, which the infra runner "
        f"mounts; move it below {roots[-1]}"
        for key, roots in checks
        if env.get(key)
        and not any(Path(env[key]).is_relative_to(root) for root in roots)
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


def inner_docker(argv: Sequence[str], args: Sequence[str]) -> list[str]:
    """Args:
        argv: compose call of the infra stack.
        args: arguments of the docker call.

    Returns:
        The call that runs ``docker <args>`` against the runner's own daemon,
        the only daemon the cache containers run on.
    """
    return [*argv, "exec", "-T", SERVICE, "docker", *args]


def inside_roots(checkout: Path, roots: Sequence[Path]) -> bool:
    """Args:
        checkout: the checkout infra-up runs from.
        roots: the roots the runner mounts.

    Returns:
        Whether the runner sees the checkout at its host path.
    """
    return any(checkout.is_relative_to(root) for root in roots)


def deploy_commands(
    argv: Sequence[str],
    checkout: Path,
    vars_file: Path,
    inventory_dir: Path,
    roles: Sequence[str],
) -> list[list[str]]:
    """Args:
        argv: compose call of the infra stack.
        checkout: checkout inside the runner, at its host path.
        vars_file: rendered host vars, below ``checkout``.
        inventory_dir: inventory the runner provisions and deploys.
        roles: application ids the inventory includes.

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
