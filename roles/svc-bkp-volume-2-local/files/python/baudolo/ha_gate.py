#!/usr/bin/env python3
"""Run baudolo so that only the primary or writer of a database cluster dumps.

Usage:
    baudolo-ha-gate --config FILE --backups-dir DIR --repo-name NAME -- CMD...

Exit codes: baudolo's own code when it fails, 3 when an expected dump is
missing, 4 when a local instance could not be probed, 64 on bad usage,
0 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

PRIMARY = "primary"
REPLICA = "replica"
UNKNOWN = "unknown"
ABSENT = "absent"
EXCLUDE_FLAG = "--volumes-no-backup-required"
MANIFEST_FILE = "manifest.json"
FILES_DIR = "files"
MISSING_DUMP = 3
USAGE = 64
TIMEOUT = 30
MACHINE_ID_FILE = Path("/etc/machine-id")

PROBE_FAILED = 4
PROBE_REPLICA_RC = 1
PROBE_ABSENT_RC = 3

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def report(message: str) -> None:
    print(f"baudolo-ha-gate: {message}", file=sys.stderr, flush=True)


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(argv), capture_output=True, text=True, check=False, timeout=TIMEOUT
    )


def probe_role(instance: dict, runner: Runner = _run) -> str:
    """Return PRIMARY, REPLICA, ABSENT or UNKNOWN for one local instance.

    ABSENT means the instance's service is not deployed yet, as while a
    standalone engine migrates to the HA form; it holds nothing to back up.

    Args:
        instance: ``{"service", "probe", ...}`` from the gate config, where
            ``probe`` is the argv of the engine's primary probe for it.
        runner: executes an argv and returns the completed process.
    """
    probe = instance.get("probe")
    if not isinstance(probe, list) or not probe:
        raise ValueError(f"no probe argv for {instance.get('service')!r}")
    answer = runner(probe)
    if answer.returncode == 0:
        return PRIMARY
    if answer.returncode == PROBE_REPLICA_RC:
        return REPLICA
    if answer.returncode == PROBE_ABSENT_RC:
        return ABSENT
    return UNKNOWN


def plan(instances: Sequence[dict], roles: dict[str, str]) -> tuple[list, list]:
    """Split local instances into volumes to dump and volumes to skip.

    Args:
        instances: local instances from the gate config.
        roles: service name to PRIMARY/REPLICA/UNKNOWN.

    Returns:
        ``(dump_volumes, skip_volumes)``; anything not confirmed primary is
        skipped, because the primary elsewhere backs it up. A primary whose
        engine has no SQL dump (``sql: false``) is backed up but expects none.
    """
    dump, skip = [], []
    for instance in instances:
        if roles.get(instance["service"]) != PRIMARY:
            skip.append(instance["volume"])
        elif instance.get("sql", True):
            dump.append(instance["volume"])
    return dump, skip


def with_excluded(argv: Sequence[str], volumes: Sequence[str]) -> list[str]:
    """Return ``argv`` with ``volumes`` merged into its exclusion flag.

    argparse keeps only the last occurrence of a flag, so a second
    ``--volumes-no-backup-required`` would drop the role's own exclusions.
    """
    argv = list(argv)
    if not volumes:
        return argv
    if EXCLUDE_FLAG not in argv:
        return [*argv, EXCLUDE_FLAG, *volumes]
    at = argv.index(EXCLUDE_FLAG) + 1
    end = at
    while end < len(argv) and not argv[end].startswith("-"):
        end += 1
    merged = list(dict.fromkeys(argv[at:end] + list(volumes)))
    return argv[:at] + merged + argv[end:]


def machine_hash(machine_id_file: Path) -> str:
    """Return the directory name baudolo files this machine's backups under.

    Args:
        machine_id_file: the host's machine-id file.
    """
    return hashlib.sha256(machine_id_file.read_bytes()).hexdigest()


def newest_generation(backups_dir: Path, machine: str, repo_name: str) -> Path | None:
    """Return the most recently written generation of this machine's ``repo_name``.

    Args:
        backups_dir: the backup root holding one directory per machine.
        machine: this machine's directory name, from ``machine_hash``.
        repo_name: the backup repository name.
    """
    generations = [
        path for path in (backups_dir / machine / repo_name).glob("*") if path.is_dir()
    ]
    return max(generations, key=lambda p: p.stat().st_mtime, default=None)


def missing_dumps(generation: Path | None, volumes: Sequence[str]) -> list[str]:
    """Return every expected volume the generation holds no SQL dump for.

    Args:
        generation: newest generation directory, or None when none exists.
        volumes: data volumes of local primaries.
    """
    if not volumes:
        return []
    if generation is None:
        return list(volumes)
    try:
        manifest = json.loads((generation / MANIFEST_FILE).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return list(volumes)
    state = manifest.get("volumes", {})
    return [v for v in volumes if not state.get(v, {}).get("dumped")]


def purge_file_copies(generation: Path | None, volumes: Sequence[str]) -> None:
    """Remove the file-level fallback baudolo wrote for undumped volumes."""
    if generation is None:
        return
    files_dir = FILES_DIR
    try:
        manifest = json.loads((generation / MANIFEST_FILE).read_text("utf-8"))
        files_dir = manifest.get("layout", {}).get("files_dir") or FILES_DIR
    except (OSError, json.JSONDecodeError):
        pass
    for volume in volumes:
        shutil.rmtree(generation / volume / files_dir, ignore_errors=True)


def main(argv: Sequence[str] | None = None, runner: Runner = _run) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--" not in args:
        report(
            "usage: baudolo-ha-gate --config F --backups-dir D --repo-name N -- CMD..."
        )
        return USAGE
    split = args.index("--")
    parser = argparse.ArgumentParser(prog="baudolo-ha-gate")
    parser.add_argument("--config", required=True)
    parser.add_argument("--backups-dir", required=True)
    parser.add_argument("--repo-name", required=True)
    parser.add_argument("--machine-id-file", default=str(MACHINE_ID_FILE))
    options = parser.parse_args(args[:split])
    command = args[split + 1 :]
    if not command:
        report("no command after --")
        return USAGE

    config_path = Path(options.config)
    instances = []
    if config_path.is_file():
        instances = json.loads(config_path.read_text("utf-8")).get("instances", [])
    roles = {i["service"]: probe_role(i, runner) for i in instances}
    for service, role in sorted(roles.items()):
        report(f"{service} is {role}")
    unknown = sorted(s for s, role in roles.items() if role == UNKNOWN)
    if unknown:
        report(
            "could not tell primary from replica for "
            + ", ".join(unknown)
            + "; refusing to run so no primary goes unbacked."
        )
        return PROBE_FAILED
    dump, skip = plan(instances, roles)

    result = subprocess.run(with_excluded(command, skip), check=False)
    if result.returncode != 0:
        return result.returncode

    generation = newest_generation(
        Path(options.backups_dir),
        machine_hash(Path(options.machine_id_file)),
        options.repo_name,
    )
    missing = missing_dumps(generation, dump)
    if missing:
        purge_file_copies(generation, missing)
        report(
            "no SQL dump for primary volume(s) "
            + ", ".join(missing)
            + "; refusing the file copy. Check the consumer rows in databases.csv."
        )
        return MISSING_DUMP
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
