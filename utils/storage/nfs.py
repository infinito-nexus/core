from __future__ import annotations

from pathlib import PurePosixPath


def state_path(export_base, subdir):
    return str(PurePosixPath(str(export_base)) / str(subdir))


def fstype(version):
    return "nfs4" if int(version) >= 4 else "nfs"


def mount_opts(version, runtime):
    reliability = (
        "soft,timeo=50,retrans=3" if runtime in ("dev", "act") else "hard,timeo=600"
    )
    locking = "local_lock=flock" if int(version) >= 4 else "nolock"
    return f"vers={version},rw,{reliability},{locking}"


def client_src(server, version, flavor, state_path_value):
    use_root = flavor == "kernel" and int(version) >= 4
    return f"{server}:{'/' if use_root else state_path_value}"
