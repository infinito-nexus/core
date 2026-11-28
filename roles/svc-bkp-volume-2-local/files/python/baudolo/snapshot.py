#!/usr/bin/env python3
"""Launch baudolo, adding the snapshot flags only when a snapshot will work.

baudolo states the snapshot kind rather than probing it, so a wrong kind or an
unfaithful layout costs a whole backup run. This launcher makes that call on the
host immediately before each run - deploy time cannot see a volume added later.
In ``auto`` it hands the plain live-copy command through whenever anything is
unproven; when the operator forced a kind it aborts instead, because naming the
kind rules the live copy out.

Usage:
    baudolo-snapshot --mode {auto,never,btrfs,zfs} -- baudolo [ARG ...]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

MOUNTINFO = Path("/proc/self/mountinfo")
BTRFS_SUBVOLUME_INODE = 256
BTRFS_STALE = ".baudolo-"
ZFS_STALE = "@baudolo-"
TIMEOUT = 30
VOLUMES = "volumes"
AUTO_KINDS = ("btrfs", "zfs")
UNQUOTABLE = set(" \t\n'\"\\$`;&|<>()*?[]{}!#~")
ESCAPES = (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\"))


class Mount(NamedTuple):
    """One /proc/self/mountinfo entry, reduced to the fields snapshots need."""

    point: Path
    options: str
    fstype: str
    source: str


class Subject(NamedTuple):
    """The docker data root, as docker names it and as the kernel sees it.

    Attributes:
        stated: the string baudolo receives. It stays byte-identical to what
            docker reports, because baudolo compares it against the volume
            mountpoints with os.path.relpath and never follows symlinks - a
            resolved subject against unresolved mountpoints aborts every run.
        real: the resolved path, used only for mountinfo and stat lookups,
            which need the target rather than the link.
    """

    stated: str
    real: Path


class Volume(NamedTuple):
    """A docker volume, as ``docker volume inspect`` declares it."""

    name: str
    driver: str
    options: dict
    mountpoint: str


def report(message: str) -> None:
    """Print on stderr, where systemd files the line in the journal."""
    print(f"baudolo-snapshot: {message}", file=sys.stderr, flush=True)


def run(argv: list[str]) -> str | None:
    """Return the stdout of ``argv``, or None when it fails, hangs or is missing."""
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, check=False, timeout=TIMEOUT
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def unescape(field: str) -> str:
    """Decode the octal escapes mountinfo applies to path fields."""
    for code, char in ESCAPES:
        field = field.replace(code, char)
    return field


def read_mounts() -> list[Mount]:
    """Return every mount of the current namespace, in mountinfo order."""
    mounts = []
    for line in MOUNTINFO.read_text().splitlines():
        left, separator, right = line.partition(" - ")
        fields, tail = left.split(), right.split()
        if not separator or len(fields) < 6 or len(tail) < 2:
            continue
        mounts.append(
            Mount(Path(unescape(fields[4])), fields[5], tail[0], unescape(tail[1]))
        )
    return mounts


def mount_of(path: Path, mounts: list[Mount]) -> Mount | None:
    """Return the mount covering ``path``: longest mountpoint, last one wins."""
    found = None
    for mount in mounts:
        if path != mount.point and mount.point not in path.parents:
            continue
        if found is None or len(mount.point.parts) >= len(found.point.parts):
            found = mount
    return found


def docker_root() -> Subject | None:
    """Return the docker data root as the daemon reports it."""
    reported = (run(["docker", "info", "--format", "{{.DockerRootDir}}"]) or "").strip()
    return Subject(reported, Path(reported).resolve()) if reported else None


def as_volume(reported: str, name: str) -> Volume:
    """Build a Volume from one ``docker volume inspect --format '{{json .}}'`` line."""
    data = json.loads(reported)
    return Volume(
        data.get("Name") or name,
        data.get("Driver") or "",
        data.get("Options") or {},
        data.get("Mountpoint") or "",
    )


def volumes() -> list[Volume] | None:
    """Return every docker volume, or None when the daemon cannot be asked."""
    names = run(["docker", "volume", "ls", "--quiet"])
    if names is None:
        return None
    listed = names.split()
    if not listed:
        return []
    batched = run(["docker", "volume", "inspect", "--format", "{{json .}}", *listed])
    if batched is not None:
        return [as_volume(line, "") for line in batched.splitlines() if line.strip()]
    found = []
    for name in listed:
        reported = run(["docker", "volume", "inspect", "--format", "{{json .}}", name])
        if reported is not None:
            found.append(as_volume(reported, name))
    return found


def volumes_reason(subject: Subject, mounts: list[Mount]) -> str | None:
    """Return why the docker volumes are not all captured by a snapshot.

    A volume backed by anything other than the data root - an NFS or CIFS
    local-driver volume, a foreign driver - is a separate filesystem a snapshot
    of the data root cannot contain, and it appears inside the snapshot as an
    existing empty directory, so the copy succeeds and the backup holds nothing.
    Docker mounts those lazily and unmounts on the last container stop, so the
    declaration is what gets checked: it is true at every moment, where the
    mount table is only true while a container happens to hold the volume.
    """
    declared = volumes()
    if declared is None:
        return "the docker volume list could not be read"
    subject_mount = mount_of(subject.real, mounts)
    for volume in declared:
        if volume.driver != "local":
            return f"volume {volume.name} uses the {volume.driver} driver"
        if volume.options:
            return (
                f"volume {volume.name} declares its own backing store {volume.options}"
            )
        if not volume.mountpoint:
            return f"volume {volume.name} reports no mountpoint"
        stated = Path(volume.mountpoint)
        if Path(subject.stated) not in stated.parents:
            return f"volume mountpoint {stated} lies outside {subject.stated}"
        real = stated.resolve()
        if mount_of(real, mounts) != subject_mount:
            return f"volume mountpoint {stated} sits on its own mount"
        if real.stat().st_dev != subject.real.stat().st_dev:
            return f"volume mountpoint {stated} crosses a filesystem boundary"
        if any(mount.point == real or real in mount.point.parents for mount in mounts):
            return f"something is mounted inside volume mountpoint {stated}"
    return None


def btrfs_reason(subject: Subject, mounts: list[Mount]) -> str | None:
    """Return why ``subject`` cannot serve as a btrfs snapshot source."""
    if shutil.which("btrfs") is None:
        return "the btrfs command is not installed"
    if subject.real.stat().st_ino != BTRFS_SUBVOLUME_INODE:
        return f"{subject.real} is a plain directory, not a btrfs subvolume root"
    if mount_of(subject.real, mounts) is None:
        return f"no mount covers {subject.real}"
    if not os.access(subject.real, os.W_OK):
        return f"{subject.real} is not writable, so no snapshot can be carved inside it"
    carved = nested_subvolume(subject)
    if carved is not None:
        return f"{carved} is a subvolume of its own, which a snapshot captures as empty"
    return None


def volume_paths(subject: Subject) -> list[Path]:
    """Return the directories a snapshot has to carry: every volume and its payload."""
    volumes = subject.real / VOLUMES
    if not volumes.is_dir():
        return []
    found = []
    for volume in sorted(volumes.iterdir()):
        if not volume.is_dir() or volume.is_symlink():
            continue
        found.append(volume)
        found.extend(child for child in sorted(volume.iterdir()) if child.is_dir())
    return found


def nested_subvolume(subject: Subject) -> Path | None:
    """Return the first volume directory that is a subvolume root of its own.

    Only the volume tree is inspected, never the whole data root: the storage
    driver carves a subvolume per image layer under <root>/btrfs, and those are
    rebuilt from the registry rather than restored, so their absence from a
    snapshot costs nothing. A subvolume inside the volume tree does cost
    everything - it appears in the snapshot as an existing empty directory, so
    the copy succeeds and the backup holds none of that volume's data.
    """
    return next(
        (
            path
            for path in volume_paths(subject)
            if path.stat().st_ino == BTRFS_SUBVOLUME_INODE
        ),
        None,
    )


def in_init_mount_namespace() -> bool:
    """Return whether this process shares the mount namespace of pid 1."""
    try:
        return Path("/proc/self/ns/mnt").readlink() == Path("/proc/1/ns/mnt").readlink()
    except OSError:
        return False


def zfs_reason(subject: Subject, mounts: list[Mount]) -> str | None:
    """Return why ``subject`` cannot serve as a zfs snapshot source."""
    if shutil.which("zfs") is None:
        return "the zfs command is not installed"
    if not in_init_mount_namespace():
        return "zfs automounts snapshots in the init mount namespace, which is not this one"
    listed = (
        run(["zfs", "list", "-H", "-o", "name,mountpoint", subject.stated]) or ""
    ).split()
    if len(listed) < 2 or Path(listed[1]) != subject.real:
        return f"{subject.stated} is not the mountpoint of a zfs dataset"
    dataset = listed[0]
    snapdir = run(["zfs", "get", "-H", "-o", "value", "snapdir", dataset])
    if snapdir is None:
        return f"the snapdir property of {dataset} could not be read"
    if snapdir.strip() == "disabled":
        return f"{dataset} has snapdir disabled, so its snapshots cannot be read"
    carried = subject.real / VOLUMES
    for mount in mounts:
        if mount.fstype == "zfs" and carried in mount.point.parents:
            return f"the child dataset at {mount.point} would be empty in a snapshot of {dataset}"
    return None


CHECKS = {"btrfs": btrfs_reason, "zfs": zfs_reason}


def kind_reason(kind: str, subject: Subject, mounts: list[Mount]) -> str | None:
    """Return why ``subject`` cannot be snapshotted as ``kind``, None when it can."""
    return CHECKS[kind](subject, mounts) or volumes_reason(subject, mounts)


def detect(subject: Subject, mounts: list[Mount]) -> tuple[str | None, str]:
    """Return the snapshot kind ``subject`` supports, and why when it supports none."""
    mount = mount_of(subject.real, mounts)
    if mount is None:
        return None, f"no mount covers {subject.real}"
    if mount.fstype not in AUTO_KINDS:
        return None, (
            f"{subject.real} is on {mount.fstype}, which takes no snapshots; "
            f"auto covers {', '.join(AUTO_KINDS)}"
        )
    reason = kind_reason(mount.fstype, subject, mounts)
    return (None, reason) if reason else (mount.fstype, "")


def reap(subject: Subject, kind: str) -> None:
    """Delete snapshots a killed run left behind, which nothing else removes.

    baudolo removes its snapshot in a ``finally``, which a SIGKILL, an OOM kill
    or a reboot skips. A read-only btrfs snapshot of the data root pins every
    block the live root later frees and `rm -rf` cannot remove it, so leftovers
    accumulate inside the data root until the disc-space cleanup starts deleting
    backup generations to reclaim space they hold. Only one backup unit runs at
    a time, so nothing reachable here belongs to a live run.
    """
    if kind == "btrfs":
        for entry in sorted(subject.real.iterdir()):
            if not entry.name.startswith(BTRFS_STALE) or not entry.is_dir():
                continue
            report(f"removing the stale snapshot {entry} of an interrupted run")
            run(["btrfs", "subvolume", "delete", str(entry)])
        return
    for name in (
        run(["zfs", "list", "-H", "-t", "snapshot", "-o", "name"]) or ""
    ).split():
        if ZFS_STALE not in name:
            continue
        report(f"removing the stale snapshot {name} of an interrupted run")
        run(["zfs", "destroy", name])


def refuse(forced: bool, reason: str) -> list[str]:
    """Fall back to the live copy, or abort when the operator forced a kind."""
    if forced:
        report(f"aborting, the stated snapshot mode cannot be delivered: {reason}")
        sys.exit(2)
    report(f"live copy, {reason}")
    return []


def snapshot_flags(mode: str) -> list[str]:
    """Return the baudolo snapshot flags for ``mode``, empty to copy live.

    A stated kind skips the fstype lookup only. Its own filesystem checks, the
    volume guard and the root check still run, because stating the kind says
    nothing about what is mounted underneath, and skipping those would hand out
    empty volume backups.
    """
    forced = mode != "auto"
    subject = docker_root()
    if subject is None:
        return refuse(forced, "the docker data root could not be resolved")
    if UNQUOTABLE & set(subject.stated):
        return refuse(
            forced, f"{subject.stated} holds characters baudolo does not quote"
        )
    if os.geteuid() != 0:
        return refuse(forced, "filesystem snapshots require root")
    mounts = read_mounts()
    if forced:
        reason = kind_reason(mode, subject, mounts)
        kind = None if reason else mode
    else:
        kind, reason = detect(subject, mounts)
    if kind is None:
        return refuse(forced, reason)
    reap(subject, kind)
    return ["--snapshot", kind, "--snapshot-subject", subject.stated]


def guarded_flags(mode: str) -> list[str]:
    """Return the snapshot flags, treating an unexpected probe failure as a decline.

    Catching everything is the contract: a host condition must never fail a run
    that would otherwise succeed. SystemExit derives from BaseException and so
    passes through, which is how a forced mode still aborts.
    """
    try:
        flags = snapshot_flags(mode)
    except Exception as error:
        return refuse(mode != "auto", f"the probe failed: {error!r}")
    else:
        return flags


def without_hard_restart(command: list[str]) -> list[str]:
    """Return ``command`` without --hard-restart-projects and its values.

    The flag exists for compose stacks whose database cannot be backed up hot,
    which is exactly what a snapshot removes, so the restart of a large stack
    would be paid for nothing. baudolo 3.2.1 rejects the combination outright.
    """
    if "--hard-restart-projects" not in command:
        return command
    start = command.index("--hard-restart-projects")
    end = start + 1
    while end < len(command) and not command[end].startswith("--"):
        end += 1
    return command[:start] + command[end:]


def main() -> None:
    """Decide on the snapshot flags, then become the baudolo process."""
    parser = argparse.ArgumentParser(
        description="Launch baudolo with or without filesystem snapshots."
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "never", "btrfs", "zfs"),
        required=True,
        help="auto probes the host and falls back to the live copy, never snapshots, "
        "btrfs/zfs state the kind and abort the run when the host cannot deliver it",
    )
    argv = sys.argv[1:]
    if "--" not in argv:
        parser.error("the baudolo command must follow a '--' separator")
    cut = argv.index("--")
    args = parser.parse_args(argv[:cut])
    command = argv[cut + 1 :]
    if not command:
        parser.error("no baudolo command was given after '--'")
    flags = [] if args.mode == "never" else guarded_flags(args.mode)
    if flags:
        command = without_hard_restart(command) + flags
    os.execvp(command[0], command)  # noqa: S606 - argv comes from the unit file, not from input


if __name__ == "__main__":
    main()
