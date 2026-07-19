#!/usr/bin/env python3
"""Runtime-only extras YAML for the swarm-NFS test pipeline.

Companion to the static ``inventories/development/swarm.yml``; both
are loaded by the deploy step. Generates an ed25519 keypair at
``KEY_PATH`` if missing so the public half can land in
``users.administrator.authorized_keys``.

Inputs (env): ``NFS_IP``, ``MGR_IP``, ``MGR``, ``OUT_PATH`` (default
``/tmp/swarm-nfs-extras.yml``), ``KEY_PATH`` (default
``/tmp/swarm-nfs-admin.key``). A second ed25519 keypair is generated at
``INFINITO_SWARM_BACKUP_KEY`` (SPOT: default.env) and its public half lands
in ``users.backup.authorized_keys`` so the DR drill's backup host can pull
over the ``user-backup`` ssh-wrapper. The ``applications`` block configures
the backup-host roles the drill triggers as real units:
``remote-2-local.backup_providers`` (manager + NFS server IPs) and the
``local-2-device`` mount/target/source device paths. The applications
block reaches the deploy through the provisioner's host_vars merge
(INFINITO_VARS_PAYLOAD), NOT through the extras file: extra-vars replace
the whole inventory ``applications`` dict and would strip every generated
credential. The deploy-facing twin ``<OUT_PATH stem>.deploy.yml`` therefore
carries everything except ``applications``; the full file stays for the
DR drill, which reads the device paths from it.
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path

from cli.meta.runtime import detect_runtime
from utils import PROJECT_ROOT
from utils.cache.yaml import dump_yaml, load_yaml
from utils.env.parser import parse_static_env
from utils.paths import DIR_BACKUPS

_DEFAULT_INVENTORY = PROJECT_ROOT / "inventories" / "development" / "default.yml"


def backup_applications_overrides(mgr_ip: str, nfs_ip: str) -> dict:
    """Application overrides for the backup-host roles the DR drill triggers.

    Args:
        mgr_ip: manager node IP (backup provider #1).
        nfs_ip: NFS server node IP (backup provider #2).

    Returns:
        dict with the ``applications`` subtree for svc-bkp-remote-2-local
        (backup_providers) and svc-bkp-local-2-device (device paths).
    """
    return {
        "svc-bkp-remote-2-local": {
            "services": {
                "remote-2-local": {
                    "backup_providers": [mgr_ip, nfs_ip],
                },
            },
        },
        "svc-bkp-local-2-device": {
            "services": {
                "local-2-device": {
                    "mount": "/mnt/backup-to-device",
                    "target": "/infinito",
                    "source": str(DIR_BACKUPS),
                },
            },
        },
    }


def _ensure_keypair(key_path: Path) -> str:
    if not key_path.is_file():
        subprocess.run(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-N",
                "",
                "-f",
                str(key_path),
                "-C",
                "swarm-test",
                "-q",
            ],
            check=True,
        )
    pub = Path(f"{key_path}.pub").read_text(encoding="utf-8")  # nocheck: cache-read
    return pub.strip()


def main() -> int:
    nfs_ip = os.environ["NFS_IP"]
    mgr_ip = os.environ["MGR_IP"]
    mgr = os.environ["MGR"]
    out_path = Path(os.environ.get("OUT_PATH", "/tmp/swarm-nfs-extras.yml"))  # noqa: S108 - ephemeral swarm-test path, overridable via OUT_PATH
    key_path = Path(os.environ.get("KEY_PATH", "/tmp/swarm-nfs-admin.key"))  # noqa: S108 - ephemeral swarm-test path, overridable via KEY_PATH

    admin_pubkey = _ensure_keypair(key_path)

    static_env = parse_static_env(PROJECT_ROOT / "default.env")

    default_users = copy.deepcopy(load_yaml(str(_DEFAULT_INVENTORY)).get("users", {}))
    admin = dict(default_users.get("administrator", {}))
    admin["authorized_keys"] = [admin_pubkey]
    default_users["administrator"] = admin

    backup_key_path = Path(
        os.environ.get("INFINITO_SWARM_BACKUP_KEY")
        or static_env["INFINITO_SWARM_BACKUP_KEY"]
    )
    backup_pubkey = _ensure_keypair(backup_key_path)
    backup = dict(default_users.get("backup", {"accounts": ["host"]}))
    backup["authorized_keys"] = [backup_pubkey]
    default_users["backup"] = backup

    extras = {
        "RUNTIME": detect_runtime(),
        "DOMAIN_PRIMARY": os.environ.get("INFINITO_DOMAIN")
        or static_env["INFINITO_DOMAIN"],
        "storage": {
            "backend": "nfs",
            "nfs": {
                "server": nfs_ip,
            },
        },
        "swarm": {
            "manager": {"advertise_addr": mgr_ip},
            "registry": {"host": mgr, "port": 5000},
            "network": {"encryption": True},
        },
        "nfs_server_ip": nfs_ip,
        "users": default_users,
        "applications": backup_applications_overrides(mgr_ip, nfs_ip),
    }

    dump_yaml(str(out_path), extras)
    deploy_extras = {k: v for k, v in extras.items() if k != "applications"}
    deploy_path = out_path.with_suffix(".deploy.yml")
    dump_yaml(str(deploy_path), deploy_extras)
    print(out_path.read_text())  # nocheck: cache-read — re-reads the file just written
    return 0


if __name__ == "__main__":
    sys.exit(main())
