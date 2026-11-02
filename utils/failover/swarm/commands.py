"""Pure pieces of the Swarm adapter: names, host commands, listings, lab sizes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.failover.checker import INTERVAL_S, TIMEOUT_S
from utils.roles.db.backup import BACKUP_ROLE
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

if TYPE_CHECKING:
    from pathlib import Path

DATA_DIR = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "swarm" / "data"
LAB_SIZES = PROJECT_ROOT / "compose" / "swarm" / "failover" / "lab-sizes.yml"
CHECKER_SCRIPT = DATA_DIR / "checker.sh"
PROBE_SCRIPT = DATA_DIR / "probe.sh"
CHECKER_PATH = "/failover/checker.sh"
PROBE_PATH = "/failover/probe.sh"
SECRET_TARGET = "failover-checker"  # noqa: S105 - docker secret mount name, not a credential
COORDINATION_ROLE = "svc-dcs-etcd"
MARKER_DATABASE = {"postgres": "postgres", "mariadb": "failover"}

DEPLOY_TIMEOUT_S = 3600
BACKUP_TIMEOUT_S = 1800
SETTLE_TIMEOUT_S = 180
QUORUM_TIMEOUT_S = 600
NAME_FILES = ("/etc/resolv.conf", "/etc/hosts")
ARRANGE_ATTEMPTS = 6
RAFT_ARRANGE_ATTEMPTS = 15


def secret_name(engine: str) -> str:
    return f"failover-checker-{engine}"


def config_name(run_id: str) -> str:
    return f"failover-checker-{run_id}"


def service_name(engine: str) -> str:
    return f"failover-checker-{engine}"


def probe_service_name(engine: str) -> str:
    return f"failover-probe-{engine}"


_PATRONI_PRIMARY = (
    "import os,urllib.request;urllib.request.urlopen("
    '"http://127.0.0.1:%s/primary" % os.environ["DB_PATRONI_API_PORT"],timeout=3)'
)
_ELECTOR_WRITER = (
    "import os,urllib.request;urllib.request.urlopen("
    '"http://127.0.0.1:%s/writer" % os.environ["ELECTOR_PORT"],timeout=3)'
)
_SENTINEL_MASTER_IS_SELF = (
    'REDISCLI_AUTH=$(cat "$REDIS_HA_SENTINEL_PASSWORD_FILE"); export REDISCLI_AUTH; '
    "for s in $REDIS_HA_SENTINELS; do "
    'm=$(timeout 3 redis-cli -h "$s" -p "$REDIS_HA_SENTINEL_PORT" --raw '
    'SENTINEL get-master-addr-by-name "$REDIS_HA_MASTER_NAME" 2>/dev/null | head -1); '
    '[ -n "$m" ] && break; done; '
    '[ "${m%%.*}" = "${REDIS_HA_SELF%%.*}" ]'
)
_SENTINEL_FAILOVER = (
    'REDISCLI_AUTH=$(cat "$SENTINEL_PASSWORD_FILE") '
    'exec redis-cli -p "$SENTINEL_PORT" SENTINEL FAILOVER "$SENTINEL_MASTER_NAME"'
)


def sentinel_failover_argv() -> list[str]:
    """Return the in-container command asking a Sentinel for a planned failover."""
    return ["sh", "-c", _SENTINEL_FAILOVER]


def is_instance_service(engine: str, name: str) -> bool:
    """Whether a Swarm service is one of the engine's per-host HA instances.

    Args:
        engine: engine under test.
        name: full Swarm service name (``<stack>_<service>``).
    """
    prefix = f"{engine}_{engine}-"
    return name.startswith(prefix) and not name.startswith(f"{prefix}sentinel-")


def primary_probe_argv(engine: str, *, node: str, container: str) -> list[str]:
    """Return the host command that exits 0 only inside the current primary.

    Args:
        engine: engine under test.
        node: DinD container of the Swarm node running the instance.
        container: instance container inside ``node``.
    """
    if engine == "postgres":
        probe = ["python3", "-c", _PATRONI_PRIMARY]
    elif engine == "redis":
        probe = ["sh", "-c", _SENTINEL_MASTER_IS_SELF]
    else:
        probe = ["python3", "-c", _ELECTOR_WRITER]
    return ["docker", "exec", node, "docker", "exec", container, *probe]


def in_container_argv(
    node: str,
    container: str,
    argv: list[str],
    *,
    user: str | None = None,
    interactive: bool = False,
) -> list[str]:
    """Return the host command that runs ``argv`` inside a container of a node.

    Args:
        node: DinD container of the Swarm node.
        container: container id inside ``node``.
        argv: command inside the container.
        user: optional ``--user``.
        interactive: keep stdin open (``-i``) on both hops.
    """
    hop = ["-i"] if interactive else []
    who = ["--user", user] if user else []
    return [
        "docker",
        "exec",
        *hop,
        node,
        "docker",
        "exec",
        *hop,
        *who,
        container,
        *argv,
    ]


def inject_argv(
    injection: str, *, node: str, network: str, container: str | None = None
) -> list[str]:
    """Return the host command that injects one fault.

    Args:
        injection: ``kill`` (the instance container), ``node`` or ``leader``
            (crash), ``hang`` (freeze) or ``partition`` (leave the lab network).
        node: DinD container of the Swarm node.
        network: lab network name.
        container: instance container inside ``node``; required for ``kill``.
    """
    if injection == "kill":
        if not container:
            raise ValueError("inject_argv: kill needs the instance container")
        return ["docker", "exec", node, "docker", "kill", container]
    if injection in ("node", "leader"):
        return ["docker", "kill", node]
    if injection == "hang":
        return ["docker", "pause", node]
    if injection == "partition":
        return ["docker", "network", "disconnect", network, node]
    raise ValueError(f"inject_argv: unknown injection {injection!r}")


def heal_argv(
    injection: str, *, node: str, network: str, ip: str | None = None
) -> list[str] | None:
    """Return the host command that undoes a node fault, or None for ``kill``.

    Args:
        injection: as for ``inject_argv``.
        node: DinD container of the Swarm node.
        network: lab network name.
        ip: the node's fixed lab address, required to heal ``partition``.
    """
    if injection == "kill":
        return None
    if injection in ("node", "leader"):
        return ["docker", "start", node]
    if injection == "hang":
        return ["docker", "unpause", node]
    if injection == "partition":
        if not ip:
            raise ValueError("heal_argv: partition needs the node's lab ip")
        return ["docker", "network", "connect", "--ip", ip, network, node]
    raise ValueError(f"heal_argv: unknown injection {injection!r}")


def oneshot_service_argv(
    *,
    name: str,
    manager: str,
    spare: str,
    image: str,
    network: str,
    engine: str,
    config: str,
    script_path: str,
    env: dict[str, str],
    scratch_dirs: list[str] | None = None,
) -> list[str]:
    """Return the command that starts a one-shot suite service on the spare worker.

    Args:
        name: Swarm service name.
        manager: DinD container of a reachable manager.
        spare: hostname of the spare worker the suite never faults.
        image: the engine's own image, which ships its client tools.
        network: overlay network the engine's write endpoint is on.
        engine: engine under test; selects the connection secret.
        config: Docker config holding the script.
        script_path: where the script is mounted.
        env: environment of the script.
        scratch_dirs: the image's declared ``VOLUME`` paths; each gets a
            tmpfs, so the service leaves no anonymous volume behind.
    """
    env_args = [
        arg for key, value in env.items() for arg in ("--env", f"{key}={value}")
    ]
    mount_args = [
        arg
        for path in scratch_dirs or []
        for arg in ("--mount", f"type=tmpfs,destination={path}")
    ]
    return [
        "docker",
        "exec",
        manager,
        "docker",
        "service",
        "create",
        "--detach",
        "--name",
        name,
        "--restart-condition",
        "none",
        "--no-healthcheck",
        "--constraint",
        f"node.hostname=={spare}",
        "--network",
        network,
        "--secret",
        f"source={secret_name(engine)},target={SECRET_TARGET}",
        "--config",
        f"source={config},target={script_path},mode=0555",
        *mount_args,
        *env_args,
        "--env",
        f"SECRET_FILE=/run/secrets/{SECRET_TARGET}",
        "--entrypoint",
        "sh",
        image,
        script_path,
    ]


def checker_service_argv(
    *,
    engine: str,
    manager: str,
    spare: str,
    image: str,
    network: str,
    run_id: str,
    duration_s: int,
    scratch_dirs: list[str] | None = None,
) -> list[str]:
    """Return the command that starts one checker run as a Swarm service.

    Args:
        engine: engine under test.
        manager: DinD container of a reachable manager.
        spare: hostname of the spare worker the suite never faults.
        image: the engine's own image, which ships its client tools.
        network: overlay network the engine's write endpoint is on.
        run_id: unique id of this run.
        duration_s: seconds the checker keeps writing.
        scratch_dirs: see ``oneshot_service_argv``.
    """
    return oneshot_service_argv(
        name=service_name(engine),
        manager=manager,
        spare=spare,
        image=image,
        network=network,
        engine=engine,
        config=config_name(run_id),
        script_path=CHECKER_PATH,
        env={
            "ENGINE": engine,
            "RUN_ID": run_id,
            "DURATION_S": str(duration_s),
            "INTERVAL_S": str(INTERVAL_S),
            "TIMEOUT_S": str(TIMEOUT_S),
        },
        scratch_dirs=scratch_dirs,
    )


def raft_leader(node_listing: str) -> str | None:
    """Return the hostname ``docker node ls`` marks as Raft leader.

    Args:
        node_listing: ``docker node ls --format '{{.Hostname}} {{.ManagerStatus}}'``.
    """
    for line in node_listing.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "Leader":
            return parts[0]
    return None


def node_status(node_listing: str, hostname: str) -> str | None:
    """Return the status of one node in ``docker node ls --format '{{.Hostname}} {{.Status}}'``."""
    for line in node_listing.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == hostname:
            return parts[1]
    return None


def load_lab_sizes() -> dict:
    return load_yaml(str(LAB_SIZES))


def filter_lab_overrides(raw: dict, *, roles_dir: Path) -> dict:
    """Keep only overrides for roles and services that exist.

    Args:
        raw: the lab-size document (``applications.<role>.services.<key>``).
        roles_dir: the ``roles/`` directory to check against.

    Returns:
        The same shape without absent roles or undeclared service keys.
    """
    out: dict = {}
    for app_id, app in (raw.get("applications") or {}).items():
        declared = load_yaml_any(
            str(roles_dir / app_id / ROLE_FILE_META_SERVICES), default_if_missing=None
        )
        if not isinstance(declared, dict):
            continue
        services = {
            key: value
            for key, value in ((app or {}).get("services") or {}).items()
            if key in declared
        }
        if services:
            out.setdefault("applications", {})[app_id] = {"services": services}
    return out


def backup_search_root() -> str:
    """Return the host directory baudolo generations live under (``DIR_VAR_LIB``)."""
    paths = load_yaml(str(PROJECT_ROOT / "group_vars" / "all" / "05_paths.yml"))
    return str(paths["DIR_VAR_LIB"])


def backup_repo_name() -> str:
    role_vars = load_yaml(
        str(PROJECT_ROOT / "roles" / BACKUP_ROLE / ROLE_FILE_VARS_MAIN)
    )
    return str(role_vars["BKP_VOLUME_2_LOCAL_REPO_NAME"])
