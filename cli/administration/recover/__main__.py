"""Uniform recover CLI for the svc-bkp-* backup roles.

    python3 -m cli.administration.recover <type> <source> <target> [--preview]

Run the steps in order (device -> nfs -> volume -> secrets), or use the
``full`` type to recover every backup-stored type (nfs -> volume -> secrets)
at once from a local backup-root or a pulled remote host. A source not
starting with ``/`` is a remote ``[user@]host[:/path]`` that rsync pulls
(nfs / volume / full only). A trailing ``:/absolute/path`` on a local source
overrides the restore destination; for device the source additionally
accepts a relative
``:subpath`` (on-device snapshot dir) and a ``:YYYYMMDDHHMMSS`` generation to
restore (default: newest), classified by shape. ``--preview`` prints the
commands without running them. The device LUKS passphrase is prompted
interactively on a terminal, or read from stdin when piped (no flag).
Destructive (rsync --delete); needs root on the target host.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys

from cli.administration.recover import full, recoverers, remote

_EXAMPLES = """\
examples:
  # NFS export subtree, default destination (/srv/nfs/infinito-state):
  recover nfs /var/lib/infinito/backup/HASH/backup-nfs-to-local/GEN/files host01

  # NFS into a specific export subtree (absolute :target overrides the default):
  recover nfs /snap/files:/srv/nfs/infinito-state/matomo_data host01

  # Docker volume (name taken from the .../<volume>/files source path):
  recover volume /backup/HASH/backup-docker-to-local/GEN/matomo_data/files host01

  # Host secrets (restores to fixed system paths: secrets, CA, Let's Encrypt, ACME):
  recover secrets /backup/HASH/backup-secrets-to-local/GEN/files host01

  # Device: newest generation, default restore-root (/var/lib/infinito/backup):
  recover device /dev/sdb1 host01

  # Device with on-device subpath + a specific generation + a custom restore-root:
  recover device /dev/sdb1:usb-backup:20260710153000:/tmp/restored host01

  # NFS pulled from a remote host (source not starting with / -> rsync over ssh):
  recover nfs user@srchost:/var/lib/infinito/backup/HASH/backup-nfs-to-local/GEN/files host01

  # full: every backup-stored type (nfs -> volume -> secrets) from a local backup-root:
  recover full /var/lib/infinito/backup host01

  # full: pull a source host's whole backup tree and recover it onto the target:
  recover full user@srchost host01

  # full from a LUKS device/image (device step first, then nfs -> volume -> secrets):
  recover full /dev/sdb1:usb-backup host01

  # Device on a remote host: a block device is recovered over ssh on the host, then pulled:
  recover device user@srchost:/dev/sdb1:usb-backup host01

  # A device image on a remote host is pulled and recovered locally:
  recover device user@srchost:/backup/usb.img:usb-backup host01

  # Skip the pre-recover safety backup (only when the target is empty/disposable):
  recover nfs /snap host01 --no-safety-backup

  # Print the commands without running them:
  recover device /dev/sdb1 host01 --preview

source colon segments (device classifies each by shape):
  :/absolute/path    restore destination, overrides the derived default target
  :subpath           device on-device snapshot subpath (relative, device only)
  :YYYYMMDDHHMMSS     device generation to restore (all-digit, default: newest)

The device LUKS passphrase is prompted interactively, or read from stdin
when piped (e.g. `printf '%s' "$pass" | recover device ...`).
"""


def _local(cmd: list[str], target: str, preview: bool) -> int:
    print(f"# {target}: {shlex.join(cmd)}")
    if preview:
        return 0
    if os.geteuid() != 0:
        print("! not root -- recover.py needs root (systemctl/rsync/mount/cryptsetup)")
    return subprocess.run(cmd, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cli.administration.recover",
        description="Uniform recover step: <type> <source> <target> [--preview].",
        epilog=_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "type",
        choices=[*recoverers.ORDER, "full"],
        help="recovery type ('full' = every backup-stored type in order)",
    )
    parser.add_argument(
        "source",
        help=(
            "local path, or a remote '[user@]host[:/path]' (rsync pull) for nfs/volume/full. "
            "a ':/absolute/path' suffix on a local path overrides the restore target. "
            "device: '<device>[:subpath][:YYYYMMDDHHMMSS][:/restore-dir]'"
        ),
    )
    parser.add_argument("target", help="host to restore onto")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="print the commands without running them",
    )
    parser.add_argument(
        "--no-safety-backup",
        action="store_true",
        help="skip the pre-recover safety backup of the current target "
        "(only when it holds nothing worth saving: fresh host / empty / disposable)",
    )
    args = parser.parse_args(argv)
    if args.type == "full":
        return full.run(
            args.source,
            args.target,
            preview=args.preview,
            service_backup=not args.no_safety_backup,
        )
    if args.type == "device" and recoverers.is_remote(args.source):
        returncode, _ = remote.run(
            args.source,
            preview=args.preview,
            service_backup=not args.no_safety_backup,
            passphrase_stdin=not sys.stdin.isatty(),
        )
        return returncode
    recoverer = recoverers.RECOVERERS[args.type]
    try:
        cmd = recoverer.command(
            args.source,
            service_backup=not args.no_safety_backup,
            passphrase_stdin=not sys.stdin.isatty(),
            target=args.target,
        )
    except ValueError as exc:
        parser.error(str(exc))
    return _local(cmd, args.target, args.preview)


if __name__ == "__main__":
    raise SystemExit(main())
