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
from utils.env.handlers.infinito.infra import RUNNER_CONTAINER_KEY
from utils.networks.infra import SUBNET_KEY, runner_ip

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


def base_refusal(paths: Sequence[Path]) -> list[str]:
    """Args:
        paths: the machine-wide directory the lock, the owner marker and the
            bridge record land in, and the cache base the idle units land in.

    Returns:
        One refusal line per directory this user can neither write nor
        create, naming the one-time step that hands it over; nothing
        otherwise.
    """
    return [
        f"[infra] this user cannot write {path}, where the lock, the owner "
        f"marker, the bridge record or the idle units land; hand it over once: "
        + (
            f'sudo chown "$USER": {path}'
            if path.is_dir()
            else f'sudo install -d -o "$USER" {path}'
        )
        for path in dict.fromkeys(paths)
        if not _writable(path)
    ]


def prepare_base(base: Path) -> list[str]:
    """Args:
        base: the cache base every cache path derives from.

    Returns:
        The refusal line of :func:`base_refusal` while this user can neither
        write nor create *base*; nothing once *base* exists, created as this
        user before any bind with ``create_host_path`` lets the Docker daemon
        create it as root.
    """
    lines = base_refusal([base])
    if not lines:
        base.mkdir(parents=True, exist_ok=True)
    return lines


def _writable(path: Path) -> bool:
    existing = next(parent for parent in (path, *path.parents) if parent.exists())
    return existing.is_dir() and os.access(existing, os.W_OK | os.X_OK)


def foreign_base(
    base: Path, mounts: Sequence[Mapping[str, object]] | None
) -> list[str]:
    """Args:
        base: the cache base of this call.
        mounts: the ``Mounts`` docker inspect reports for the running runner;
            None while the runner does not run.

    Returns:
        The refusal line while the running runner does not bind *base* at
        its host path, since every leg of this call would then resolve
        against the runner's own filesystem; nothing otherwise.
    """
    if mounts is None:
        return []
    binds = {
        (str(mount.get("Source")), str(mount.get("Destination")))
        for mount in mounts
        if mount.get("Type") == "bind"
    }
    if (str(base), str(base)) in binds:
        return []
    bound = sorted(source for source, target in binds if source == target)
    line = (
        f"[infra] the running infra runner does not bind the cache base {base} "
        f"of this call (it binds {', '.join(bound) or 'nothing'} at its host "
        f"path); export INFINITO_INFRA_CACHE_DIR to the base it binds, or run "
        f"make infra-down first to move the runner to {base}"
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def up(
    argv: Sequence[str],
    *,
    refusal: Callable[[], list[str]],
    foreign: Callable[[], list[str]],
    running: Callable[[], bool],
    run: Callable[[list[str]], None],
    lock: Path,
    base: Path,
    recreate: bool,
    takeover: Sequence[str],
    bridge: tuple[str, str] | None,
    installs: Callable[[], Sequence[list[str]]],
    prepare: Callable[[], None],
    apply: Callable[[], None],
    evict: Callable[[], None],
) -> int:
    """Args:
        argv: compose call of the infra stack.
        refusal: floor check, run before anything starts.
        foreign: refusal while a running runner binds another cache base, run
            first inside the lock, so no other call starts one in between.
        running: whether the runner already runs.
        run: executes a command and raises on failure.
        lock: machine lock file; the owner marker OWNER_NAME lands next to it
            before the runner starts and stays after a failed start or a down,
            unless a takeover rolls back.
        base: the cache base the runner binds, prepared by
            :func:`prepare_base` before anything starts, since the bind's
            ``create_host_path`` would otherwise let the host daemon create it
            as root, and the idle units written into it after the start would
            then fail.
        recreate: apply changed inputs to a running runner (infra-update).
        takeover: running legacy cache containers, stopped inside the lock
            right after the marker, which recreates a running runner; when
            anything between that stop and the apply fails, the runner stops,
            they start again, and the marker and the bridge record go before
            the failure propagates.
        bridge: the legacy network and address *argv* joins the runner to,
            recorded as BRIDGE_NAME next to the lock so later calls keep it.
        installs: builds the commands run after the runner is up, such as the
            idle timer; called only then, so a refusal writes nothing.
        prepare: installs the pinned certificates and map of the cache
            frontend, called by a call that starts or recreates the runner
            right before it does, so the frontend its deploy starts serves the
            pin; raises when there is no pin, which starts nothing.
        apply: applies the pinned cache declarations, the only writer of the
            stack's repositories, on every call: by a call that finds the
            runner running, after the start and the installs, and after one of
            them raises an Exception unless a takeover rolls back, which then
            restores the legacy stack and applies nothing; never raises.
        evict: runs the cache eviction and raises on failure; called once the
            start and the installs succeeded and the apply returned, whether
            or not it applied, outside the takeover rollback, since on a fresh
            Nexus only the apply's bootstrap sets the admin password and
            schedules the tasks the eviction needs, so there an apply that
            failed fails the call through the eviction.

    Returns:
        2 on a refusal or a foreign base, else 0.
    """
    lines = refusal()
    if lines:
        print("\n".join(lines), file=sys.stderr)
        return 2
    with machine_lock(lock):
        lines = foreign() or prepare_base(base)
        if lines:
            print("\n".join(lines), file=sys.stderr)
            return 2
        written = (lock.with_name(OWNER_NAME), lock.with_name(BRIDGE_NAME))
        written[0].write_text(f"{NETWORK}\n")
        try:
            if bridge:
                written[1].write_text(" ".join(bridge) + "\n")
            if takeover:
                run(["docker", "stop", "-t", STOP_GRACE, *takeover])
            if running() and not (recreate or takeover):
                print("the infra runner already runs", flush=True)
                apply()
                return 0
            prepare()
            try:
                run([*argv, "up", "--detach", "--wait"])
                for command in installs():
                    run(list(command))
            except Exception:
                if not takeover:
                    apply()
                raise
            apply()
        except BaseException:
            if takeover:
                _roll_back(argv, takeover, written, run)
            raise
        evict()
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
