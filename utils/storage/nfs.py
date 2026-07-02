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
    return f"vers={version},rw,{reliability},nolock"


def client_src(server, version, flavor, state_path_value):
    # kernel-v4 exports the state dir at fsid=0, so clients mount the bare ':/' root;
    # ganesha (Pseudo == real path) and v3 mount the full state path.
    use_root = flavor == "kernel" and int(version) >= 4
    return f"{server}:{'/' if use_root else state_path_value}"
