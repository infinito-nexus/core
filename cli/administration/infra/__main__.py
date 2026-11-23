from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from cli.administration.deploy.development.extra_mounts import write_mounts_override
from cli.administration.deploy.development.profile import Profile
from cli.administration.deploy.development.stack import infra_compose_argv
from utils.cache.evict import CacheConfigError
from utils.cache.eviction.docker import build_cache_usage, run_command
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import dump_yaml, load_yaml
from utils.env.handlers.infinito.cache.paths import base, machine
from utils.env.handlers.infinito.cache.pin import ROOT_KEY as PIN_ROOT_KEY
from utils.infra import (
    BRIDGE_NAME,
    LEGACY_FORMAT,
    LEGACY_REGISTRY,
    LOCK_NAME,
    NETWORK,
    PROXY_FORMAT,
    ROOTS_KEY,
    ROOTS_OVERRIDE,
    RUNNER_CONTAINER_KEY,
    SERVICE,
    base_refusal,
    down,
    floor_refusal,
    foreign_base,
    inner_docker,
    inside_roots,
    legacy_refusal,
    legacy_running,
    proxy_bridge,
    read_bridge,
    status,
    up,
    worktree_roots,
    write_bridge,
)
from utils.infra_inventory import (
    CACHE_SERVICES,
    PRUNE_ACTION,
    cache_container,
    cache_port,
    deploy_commands,
    drop_roles,
    infra_roles,
    opted_out,
    render_inventory,
    unmounted,
)
from utils.infra_tools import (
    TOOLS_ACTIONS,
    UNIT_DIR,
    addressable,
    idle_units,
    timer_installs,
    tools_commands,
    write_units,
)
from utils.inventory.tools import (
    GATEWAY_ROLE,
    LIBRETRANSLATE_ROLE,
    LITELLM_ROLE,
    OLLAMA_ROLE,
    S1_ROLE,
)
from utils.inventory.tools_idle import GRACE_KEY, STAMP_DIR_KEY
from utils.roles.entity.name import entity_name

if TYPE_CHECKING:
    from collections.abc import Callable

IMAGE_KEY = "INFINITO_IMAGE"
VENV_KEY = "INFINITO_VENV_DIR"
GPU_KEY = "INFINITO_GPU_COUNT"
GPU_OVERRIDE = "compose/infra-gpu.override.yml"
PRIMARY = ["bash", "scripts/meta/resolve/repository/primary.sh"]
IMAGE = ["bash", "scripts/meta/resolve/image/local.sh"]
EVICT = [sys.executable, "-m", "cli.meta.cache.evict"]
INVENTORY_DIR = Path.home() / "inventories" / "infinito-infra"
TOOLS_ROLES = (LIBRETRANSLATE_ROLE, S1_ROLE, LITELLM_ROLE, OLLAMA_ROLE, GATEWAY_ROLE)
LIFECYCLE = ("up", "update", "down", "status")
ATTACH = "attach"
DOCKER = "docker"
CACHE_NAME = "cache-name"
CACHE_PORT = "cache-port"
RUNNING = "running"
RUNNER_DOWN = 3
STARTING = ("up", "update", ATTACH)
OUTER_TOOLS = {"tools-stop": "stop", "tools-pause": "pause", "tools-resume": "unpause"}
CACHE_APPLY = ("bash", "scripts/system/cache/apply.sh")
CACHE_PREPARE = (*CACHE_APPLY, "prepare")
FOREIGN_MAP = 4
CACHE_PIN_DOC = "docs/contributing/environment/cache.md"


def _pin_prepare() -> None:
    """
    Raises:
        SystemExit: no pin exists yet, `.env` predates the pin, or the pinned
            commit cannot be materialized; the cache frontend does not start.
    """
    print(
        "[infra] installing the pinned certificates and map of the cache frontend",
        file=sys.stderr,
        flush=True,
    )
    done = subprocess.run(
        CACHE_PREPARE, cwd=PROJECT_ROOT, stdout=sys.stderr, check=False
    )
    if done.returncode != 0:
        raise SystemExit(
            "[infra] ERROR: the cache stack does not start without its pin "
            f"(apply.sh prepare exited rc={done.returncode}, reason above). "
            "Run `make dotenv` if it names an unset key; before the first pin "
            "the declarer runs `make cache-declare ref=<commit>`. "
            f"See {CACHE_PIN_DOC}."
        )


def _pin_apply() -> None:
    print(
        "[infra] applying the pinned cache declarations to the cache stack",
        file=sys.stderr,
        flush=True,
    )
    done = subprocess.run(CACHE_APPLY, cwd=PROJECT_ROOT, stdout=sys.stderr, check=False)
    if done.returncode == 0:
        return
    if done.returncode == FOREIGN_MAP:
        hint = (
            "the cache frontend keeps serving its map from outside the pin "
            "root. Recreate it with `make infra-update`."
        )
    else:
        hint = "the cache frontend keeps serving the map it already had; see above."
    print(
        f"[infra] WARNING: cache apply exited rc={done.returncode}; {hint}",
        file=sys.stderr,
    )


def _resolved(command: list[str]) -> str:
    return subprocess.run(
        command, cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _prepare(bridge: tuple[str, str] | None) -> tuple[list[str], Path]:
    if not os.environ.get(IMAGE_KEY):
        os.environ[IMAGE_KEY] = _resolved(IMAGE)
    primary = Path(_resolved(PRIMARY))
    roots = worktree_roots(os.environ.get(ROOTS_KEY) or "", primary, Path.home())
    if not inside_roots(PROJECT_ROOT, roots):
        raise SystemExit(
            f"{PROJECT_ROOT} is outside the worktree roots of the infra runner; "
            f"add its root to {ROOTS_KEY} and run make infra-update"
        )
    override = write_mounts_override(
        PROJECT_ROOT, roots, service=SERVICE, override=ROOTS_OVERRIDE
    )
    overrides = [override]
    pair = bridge or read_bridge(machine() / BRIDGE_NAME)
    if pair:
        overrides.append(write_bridge(PROJECT_ROOT, *pair))
    if (os.environ.get(GPU_KEY) or "0").strip() not in ("", "0"):
        overrides.append(GPU_OVERRIDE)
    return infra_compose_argv(PROJECT_ROOT, overrides), primary


def _legacy_bridge() -> tuple[str, str] | None:
    proxies = run_command(["docker", "info", "--format", PROXY_FORMAT]) or ""
    inspect = ["docker", "inspect", "--format", LEGACY_FORMAT, LEGACY_REGISTRY]
    return proxy_bridge(proxies, run_command(inspect) or "")


def _running() -> bool:
    inspect = [
        "docker",
        "inspect",
        "--format",
        "{{.State.Running}}",
        os.environ[RUNNER_CONTAINER_KEY],
    ]
    return (run_command(inspect) or "").strip() == "true"


def _foreign() -> list[str]:
    if not _running():
        return foreign_base(base(), None)
    name = os.environ[RUNNER_CONTAINER_KEY]
    mounts = run_command(["docker", "inspect", "--format", "{{json .Mounts}}", name])
    if mounts is None:
        raise SystemExit(
            f"[infra] docker inspect {name} failed, so its cache base cannot be "
            "compared with the one of this call"
        )
    return foreign_base(base(), json.loads(mounts))


def _refusal(names: str | None, *, takeover: bool) -> list[str]:
    stopped = takeover and names is not None
    writable = base_refusal([machine(), base()])
    legacy = writable + ([] if stopped else legacy_refusal(names))
    try:
        return legacy + floor_refusal(os.environ, build_cache_usage(run_command))
    except CacheConfigError as exc:
        return [*legacy, f"[infra] {exc}; run 'make dotenv'"]


def _projects() -> list[str]:
    return [entity_name(role) for role in TOOLS_ROLES]


def _installs(argv: list[str], primary: Path) -> list[list[str]]:
    roles, pruned = infra_roles(os.environ), opted_out(os.environ)
    vars_file = render_inventory(PROJECT_ROOT, os.environ)
    unit_dir = base().joinpath(*UNIT_DIR)
    python = f"{os.environ[VENV_KEY]}/bin/python"
    idle = {key: os.environ[key] for key in (GRACE_KEY, STAMP_DIR_KEY)}
    write_units(unit_dir, idle_units(primary, python, idle))
    return [
        *deploy_commands(argv, PROJECT_ROOT, vars_file, INVENTORY_DIR, roles, pruned),
        *timer_installs(argv, unit_dir),
    ]


def _runner_state() -> int:
    """Returns:
    0 while the infra runner runs, RUNNER_DOWN while it does not, and 2
    while the host's ``docker ps`` cannot answer.
    """
    name = os.environ[RUNNER_CONTAINER_KEY]
    names = run_command(["docker", "ps", "--format", "{{.Names}}"])
    if names is None:
        print(
            f"[infra] docker ps failed, so it is unknown whether {name} runs",
            file=sys.stderr,
        )
        return 2
    return 0 if name in names.split() else RUNNER_DOWN


def _status() -> dict[str, object]:
    running = _running()
    reached: dict[str, bool] = {}
    if running:
        compose, _primary = _prepare(None)
        reached = addressable(_projects(), compose, run_command)
    return status(running, os.environ, reached)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make infra-*")
    parser.add_argument(
        "action",
        choices=(
            *LIFECYCLE,
            *OUTER_TOOLS,
            "tools-inside",
            ATTACH,
            DOCKER,
            CACHE_NAME,
            CACHE_PORT,
            RUNNING,
            PRUNE_ACTION,
        ),
    )
    parser.add_argument("--takeover", action="store_true")
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    run = partial(subprocess.run, check=True)
    if args.action in STARTING and not Profile().cache_stack_enabled():
        print("[infra] INFINITO_CACHE_STACK is off; no infra runner", file=sys.stderr)
        return 0
    if args.action in STARTING:
        try:
            infra_roles(os.environ)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    if args.action == CACHE_NAME:
        if args.rest[:1] not in ([kind] for kind in CACHE_SERVICES):
            parser.error(f"{CACHE_NAME} takes one of {', '.join(CACHE_SERVICES)}")
        print(cache_container(PROJECT_ROOT, args.rest[0]))
        return 0
    if args.action == CACHE_PORT:
        if len(args.rest) != 2 or args.rest[0] not in CACHE_SERVICES:
            kinds = ", ".join(CACHE_SERVICES)
            parser.error(f"{CACHE_PORT} takes one of {kinds}, then the protocol")
        print(cache_port(PROJECT_ROOT, *args.rest))
        return 0
    if args.action == RUNNING:
        return _runner_state()
    if args.action == PRUNE_ACTION:
        if not args.rest:
            parser.error(f"{PRUNE_ACTION} takes the inventory file, then the roles")
        return _prune(Path(args.rest[0]), args.rest[1:])
    if args.action == ATTACH:
        return _attach()
    if args.action == "status":
        print(json.dumps(_status(), sort_keys=True))
        return 0
    if args.action == "tools-inside":
        if args.rest[:1] not in ([verb] for verb in TOOLS_ACTIONS):
            parser.error(f"tools-inside takes one of {', '.join(TOOLS_ACTIONS)}")
        for command in tools_commands(_projects(), args.rest[0], []):
            run(command)
        return 0
    taking = args.takeover and args.action in ("up", "update")
    bridge = _legacy_bridge() if taking else None
    compose, primary = _prepare(bridge)
    if args.action == DOCKER:
        completed = subprocess.run(inner_docker(compose, args.rest), check=False)
        return completed.returncode
    if args.action in OUTER_TOOLS:
        for command in tools_commands(_projects(), OUTER_TOOLS[args.action], compose):
            run(command)
        return 0
    if args.action == "down":
        return down(compose, run, machine() / LOCK_NAME)
    return _up(
        compose,
        primary,
        run,
        recreate=args.action == "update",
        takeover=taking,
        bridge=bridge,
    )


def _prune(inventory: Path, roles: list[str]) -> int:
    content = load_yaml(inventory, default_if_missing={})
    dropped = drop_roles(content, roles)
    if dropped:
        dump_yaml(inventory, content)
        print(f"[infra] {inventory}: dropped {', '.join(dropped)}", file=sys.stderr)
    return 0


def _up(
    compose: list[str],
    primary: Path,
    run: Callable[..., object],
    *,
    recreate: bool,
    takeover: bool,
    bridge: tuple[str, str] | None,
) -> int:
    blocked = unmounted(base(), Path(os.environ[PIN_ROOT_KEY]), os.environ)
    if blocked:
        raise SystemExit("\n".join(blocked))
    names = run_command(["docker", "ps", "--format", "{{.Names}}"])
    return up(
        compose,
        refusal=partial(_refusal, names, takeover=takeover),
        foreign=_foreign,
        running=_running,
        run=run,
        lock=machine() / LOCK_NAME,
        base=base(),
        recreate=recreate,
        takeover=legacy_running(names or "") if takeover else [],
        bridge=bridge,
        installs=partial(_installs, compose, primary),
        prepare=_pin_prepare,
        apply=_pin_apply,
        evict=partial(run, EVICT),
    )


def _attach() -> int:
    compose, primary = _prepare(None)
    with contextlib.redirect_stdout(sys.stderr):
        code = _up(
            compose,
            primary,
            partial(subprocess.run, check=True, stdout=sys.stderr),
            recreate=False,
            takeover=False,
            bridge=None,
        )
    if code == 0:
        print(NETWORK)
    return code


if __name__ == "__main__":
    sys.exit(main())
