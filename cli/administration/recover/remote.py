"""Remote device source: ``[user@]host:/device[:subpath][:gen][:/root]``.

A block device (remote path under ``/dev/``) is recovered on the host over
ssh (the host must carry the repo checkout), then the restored backup tree
is rsync-pulled. An image file is rsync-pulled and recovered locally. Either
way the result is a local backup root the caller then recovers from.
"""

from __future__ import annotations

import shlex
import subprocess

from cli.administration.recover import recoverers

IMAGE = "/tmp/infinito-recover-device.img"  # noqa: S108 - operator recovery staging
REMOTE_ROOT = "/tmp/infinito-recover-remote-root"  # noqa: S108 - operator recovery staging path, not attacker-controlled
LOCAL_ROOT = "/tmp/infinito-recover-device-root"  # noqa: S108 - operator recovery staging path, not attacker-controlled


def split_host(source: str) -> tuple[str, str]:
    """``[user@]host:/device[:segments]`` -> (host, ``/device[:segments]``)."""
    host, _, rest = source.partition(":")
    return host, rest


def _reroot(device_source: str, new_device: str, restore_root: str) -> str:
    """Rebuild a device source with a new device path and a forced restore-root."""
    kept = [
        seg for seg in device_source.split(":")[1:] if seg and not seg.startswith("/")
    ]
    return ":".join([new_device, *kept, restore_root])


def commands(
    source: str, *, service_backup: bool, passphrase_stdin: bool
) -> tuple[list[list[str]], str]:
    """Steps that produce a local backup root from a remote device, and that root."""
    host, device_source = split_host(source)
    device_path = device_source.split(":", 1)[0]
    if device_path.startswith("/dev/"):
        remote = recoverers.RECOVERERS["device"].command(
            _reroot(device_source, device_path, REMOTE_ROOT),
            service_backup=service_backup,
            passphrase_stdin=True,
        )
        return (
            [
                ["ssh", host, shlex.join(remote)],
                ["rsync", "-a", f"{host}:{REMOTE_ROOT}/", f"{LOCAL_ROOT}/"],
            ],
            LOCAL_ROOT,
        )
    local = recoverers.RECOVERERS["device"].command(
        _reroot(device_source, IMAGE, LOCAL_ROOT),
        service_backup=service_backup,
        passphrase_stdin=passphrase_stdin,
    )
    return ([["rsync", "-a", f"{host}:{device_path}", IMAGE], local], LOCAL_ROOT)


def run(
    source: str, *, preview: bool, service_backup: bool, passphrase_stdin: bool
) -> tuple[int, str | None]:
    """Execute (or preview) the remote-device steps; return (exit code, local root)."""
    steps, root = commands(
        source, service_backup=service_backup, passphrase_stdin=passphrase_stdin
    )
    for step in steps:
        print(f"# remote device: {shlex.join(step)}")
        if not preview:
            returncode = subprocess.run(step, check=False).returncode
            if returncode != 0:
                return returncode, None
    return 0, root
