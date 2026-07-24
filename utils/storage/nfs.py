from __future__ import annotations

import re
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
    locking = "local_lock=flock" if int(version) >= 4 else "nolock"
    return f"vers={version},rw,{reliability},{locking}"


def client_src(server, version, flavor, state_path_value):
    use_root = flavor == "kernel" and int(version) >= 4
    return f"{server}:{'/' if use_root else state_path_value}"
