from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import PurePosixPath

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES

STATE_SUBDIR = "infinito-state"

NFS_SERVER_SERVICES_YML = str(
    PROJECT_ROOT / "roles" / "svc-storage-nfs-server" / ROLE_FILE_META_SERVICES
)
NFS_CLIENT_SERVICES_YML = str(
    PROJECT_ROOT / "roles" / "svc-storage-nfs-client" / ROLE_FILE_META_SERVICES
)


def _read_spot_value(services_yml: str, key: str) -> str:
    """Read a scalar entity value via line parse.

    Exception: stdlib-only on purpose - these SPOTs feed the .env
    generation, which bootstraps fresh hosts before PyYAML exists.

    Args:
        services_yml: repo-relative services.yml path.
        key: two-space-indented scalar key to read.
    """
    pattern = re.compile(rf"^  {re.escape(key)}:\s*(\S+)\s*$")
    for line in read_text(services_yml).splitlines():
        match = pattern.match(line)
        if match:
            return match.group(1)
    raise KeyError(f"{key} not found in {services_yml}")


def get_export_base() -> str:
    """NFS export base from the provider's services.yml SPOT."""
    return _read_spot_value(NFS_SERVER_SERVICES_YML, "export_base")


def get_client_version() -> int:
    """NFS mount protocol version from the client's services.yml SPOT."""
    return int(_read_spot_value(NFS_CLIENT_SERVICES_YML, "nfs_version"))


def state_path(export_base, subdir):
    return str(PurePosixPath(str(export_base)) / str(subdir))


def fstype(version):
    return "nfs4" if int(version) >= 4 else "nfs"


def mount_opts(version, runtime):
    reliability = (
        "soft,timeo=50,retrans=3"
        if runtime in ("dev", "act", "github")
        else "hard,timeo=600"
    )
    locking = "" if int(version) >= 4 else ",nolock"
    return f"vers={version},rw,noresvport,{reliability}{locking}"


def client_src(server, version, flavor, state_path_value):
    use_root = flavor == "kernel" and int(version) >= 4
    return f"{server}:{'/' if use_root else state_path_value}"


def _role_forces_other_mode(application_id):
    """True unless the role certainly runs at the cluster's deployment mode.

    ``compose_mode_force`` overrides the cluster mode for one role only
    (roles/sys-svc-compose/defaults/main.yml). A value this function cannot
    resolve statically - a Jinja expression - counts as forcing, so an
    unknown mode keeps a volume backed up rather than silently dropping it
    from both capture paths.

    Args:
        application_id: role whose ``vars/main.yml`` is read.
    """
    from utils import PROJECT_ROOT
    from utils.cache.yaml import load_yaml_any
    from utils.roles.mapping import ROLE_FILE_VARS_MAIN

    path = PROJECT_ROOT / "roles" / str(application_id) / ROLE_FILE_VARS_MAIN
    if not path.is_file():
        return False
    loaded = load_yaml_any(str(path))
    if not isinstance(loaded, Mapping):
        return False
    forced = loaded.get("compose_mode_force")
    if forced is None:
        return False
    forced = str(forced).strip()
    if not forced:
        return False
    if "{{" in forced or "{%" in forced:
        return True
    return forced.lower() != "swarm"


def swarm_nfs_backed(entry, *, application_id, deployment_mode, storage_backend):
    """True when the swarm NFS rewrite backs this ``meta/volumes.yml`` entry.

    Args:
        entry: volume entry mapping; ``nfs: false`` opts it out of the rewrite.
        application_id: role the volume belongs to; a manager-pinned role or one
            forcing a non-swarm mode keeps its volumes node-local.
        deployment_mode: cluster-wide ``compose`` or ``swarm``.
        storage_backend: the ``storage.backend`` value, e.g. ``local`` or ``nfs``.
    """
    if str(deployment_mode).strip().lower() != "swarm":
        return False
    if str(storage_backend).strip().lower() != "nfs":
        return False
    if not isinstance(entry, Mapping):
        return False
    if entry.get("nfs") is False:
        return False
    from utils.roles.meta_lookup import get_role_placement

    if str(get_role_placement(application_id) or "").strip().lower() == "manager":
        return False
    return not _role_forces_other_mode(application_id)


def volume_dir(semantic_name, entry):
    """Directory under the NFS state path the swarm rewrite binds a volume to.

    Args:
        semantic_name: the volume's key in the compose ``volumes:`` block.
        entry: the volume's spec; a pinned ``name`` wins over the key.
    """
    pinned = entry.get("name") if isinstance(entry, Mapping) else None
    return str(pinned) if pinned else str(semantic_name)


def backup_disabled_dirs(applications, *, deployment_mode, storage_backend):
    """State-path directories of the NFS-backed volumes declared ``backup: false``.

    Args:
        applications: merged applications mapping whose ``volumes`` carry the
            canonical ``meta/volumes.yml`` entries.
        deployment_mode: cluster-wide ``compose`` or ``swarm``.
        storage_backend: the ``storage.backend`` value, e.g. ``local`` or ``nfs``.

    Returns:
        The sorted directory names, without any a backed-up volume also binds to.
    """
    disabled: set[str] = set()
    kept: set[str] = set()
    for app_id, app in applications.items():
        volumes = app.get("volumes") if isinstance(app, Mapping) else None
        if not isinstance(volumes, Mapping):
            continue
        for semantic_name, entry in volumes.items():
            if (
                not isinstance(entry, Mapping)
                or entry.get("type", "volume") != "volume"
            ):
                continue
            if not swarm_nfs_backed(
                entry,
                application_id=str(app_id),
                deployment_mode=deployment_mode,
                storage_backend=storage_backend,
            ):
                continue
            target = disabled if entry.get("backup") is False else kept
            target.add(volume_dir(semantic_name, entry))
    return sorted(disabled - kept)
