"""Remote device source: ``[user@]host:/device[:subpath][:gen][:/root]``.

A block device (remote path under ``/dev/``) is recovered on the host over
ssh (the host must carry the repo checkout), then the restored backup tree
is rsync-pulled. An image file is rsync-pulled and recovered locally. Either
way the result is a local backup root the caller then recovers from.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from cli.administration.recover import recoverers, stage

STAGE_PREFIX = "infinito-recover-device-"
IMAGE = "device.img"


def split_host(source: str) -> tuple[str, str]:
    """``[user@]host:/device[:segments]`` -> (host, ``/device[:segments]``)."""
    host, _, rest = source.partition(":")
    return host, rest


def is_block_device(source: str) -> bool:
    """Whether *source* names a block device on its host rather than an image."""
    return split_host(source)[1].split(":", 1)[0].startswith("/dev/")


def _reroot(device_source: str, new_device: str, restore_root: str) -> str:
    """Rebuild a device source with a new device path and a forced restore-root."""
    kept = [
        seg for seg in device_source.split(":")[1:] if seg and not seg.startswith("/")
    ]
    return ":".join([new_device, *kept, restore_root])


def commands(
    source: str,
    *,
    local_stage: Path,
    remote_stage: str,
    service_backup: bool,
    passphrase_stdin: bool,
) -> tuple[list[list[str]], Path]:
    """Steps that produce a local backup root from a remote device, and that root.

    Args:
        source: ``[user@]host:/device[:segments]``.
        local_stage: owner-only local directory the tree and image land in.
        remote_stage: owner-only directory on the host a block device is
            recovered into; unused for an image.
        service_backup: run the role's pre-recover backup unit.
        passphrase_stdin: an image's LUKS passphrase comes on stdin.
    """
    host, device_source = split_host(source)
    device_path = device_source.split(":", 1)[0]
    root = local_stage / stage.TREE
    if device_path.startswith("/dev/"):
        remote_root = f"{remote_stage}/{stage.TREE}"
        recover = recoverers.RECOVERERS["device"].command(
            _reroot(device_source, device_path, remote_root),
            service_backup=service_backup,
            passphrase_stdin=True,
        )
        return (
            [
                ["ssh", host, shlex.join(recover)],
                ["rsync", "-aHAX", f"{host}:{remote_root}/", f"{root}/"],
            ],
            root,
        )
    image = local_stage / IMAGE
    local = recoverers.RECOVERERS["device"].command(
        _reroot(device_source, str(image), str(root)),
        service_backup=service_backup,
        passphrase_stdin=passphrase_stdin,
    )
    return ([["rsync", "-a", f"{host}:{device_path}", str(image)], local], root)


def run(
    source: str,
    *,
    local_stage: Path,
    preview: bool,
    service_backup: bool,
    passphrase_stdin: bool,
) -> tuple[int, Path | None]:
    """Execute (or preview) the remote-device steps; return (exit code, local root).

    Args:
        source: ``[user@]host:/device[:segments]``.
        local_stage: owner-only local directory the caller owns and removes.
        preview: print the steps without running them.
        service_backup: run the role's pre-recover backup unit.
        passphrase_stdin: an image's LUKS passphrase comes on stdin.
    """
    host = split_host(source)[0]
    remote_stage = stage.REMOTE_PREVIEW
    created = None
    try:
        if is_block_device(source):
            print(f"# remote device: {shlex.join(['ssh', host, 'mktemp', '-d'])}")
            if not preview:
                created = stage.remote_private(host)
                if created is None:
                    print(
                        f"# remote device: no private stage could be created on {host}",
                        file=sys.stderr,
                    )
                    return 2, None
                remote_stage = created
        steps, root = commands(
            source,
            local_stage=local_stage,
            remote_stage=remote_stage,
            service_backup=service_backup,
            passphrase_stdin=passphrase_stdin,
        )
        for step in steps:
            print(f"# remote device: {shlex.join(step)}")
            if not preview:
                returncode = subprocess.run(step, check=False).returncode
                if returncode != 0:
                    return returncode, None
        return 0, root
    finally:
        if created is not None:
            stage.remote_remove(host, created)


def run_kept(
    source: str, *, preview: bool, service_backup: bool, passphrase_stdin: bool
) -> int:
    """The standalone ``device`` recovery: its pulled tree is the result.

    Args:
        source: ``[user@]host:/device[:segments]``.
        preview: print the steps without running them.
        service_backup: run the role's pre-recover backup unit.
        passphrase_stdin: an image's LUKS passphrase comes on stdin.
    """
    if preview:
        returncode, _root = run(
            source,
            local_stage=stage.preview(STAGE_PREFIX),
            preview=True,
            service_backup=service_backup,
            passphrase_stdin=passphrase_stdin,
        )
        return returncode
    kept = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX))
    root = None
    try:
        returncode, root = run(
            source,
            local_stage=kept,
            preview=False,
            service_backup=service_backup,
            passphrase_stdin=passphrase_stdin,
        )
    finally:
        if root is None:
            stage.remove(kept)
    if root is not None:
        (kept / IMAGE).unlink(missing_ok=True)
        print(f"# remote device: recovered backup root kept at {root}")
    return returncode
