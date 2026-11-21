#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import threading
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import spec_secrets
from spec_secrets_match import CHUNK, MASK_MIN, Automaton, Stream, pump

if TYPE_CHECKING:
    from collections.abc import Iterator

CID = ".cid"
STAGED = ".staged"
TEMP = ".masked."
WRITABLE = stat.S_IWGRP | stat.S_IWOTH
USAGE = (
    "baseline <stage dir>"
    " | mask <run dir> <stage dir> <reports dir> -- <command>"
    " | scrub <run dir> <stage dir> <reports dir> [<container cli>]"
)


def masked_values(directory: Path) -> list[bytes]:
    """Read the values of a run directory long enough to mask.

    Args:
        directory: a run directory below ``spec_secrets.PARENT``.

    Returns:
        Every value of ``MASK_MIN`` bytes or more.
    """
    run = spec_secrets.open_run(directory)
    values = []
    try:
        for name in filter(spec_secrets.KEY.fullmatch, os.listdir(run)):
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=run)
            with os.fdopen(descriptor, "rb") as handle:
                values.append(handle.read())
    finally:
        os.close(run)
    return [value for value in values if len(value) >= MASK_MIN]


def walk(root: Path, skipped: Path | None, failed: list[OSError]) -> Iterator[Path]:
    """List the files below a directory.

    Args:
        root: the directory; a missing one holds nothing.
        skipped: a directory below it to leave out, or None.
        failed: collects the errors of directories that cannot be read.

    Yields:
        Every file, the ``TEMP`` files of other scrubs included.
    """

    def unreadable(error: OSError) -> None:
        if not isinstance(error, FileNotFoundError):
            failed.append(error)

    for top, dirs, files in os.walk(root, onerror=unreadable):
        dirs[:] = [name for name in dirs if Path(top, name) != skipped]
        yield from (Path(top, name) for name in files)


def digest(path: Path) -> str | None:
    try:
        if stat.S_ISREG(path.lstat().st_mode):
            with path.open("rb") as handle:
                return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError:
        return None
    return None


def digests(stage: Path) -> dict[str, str]:
    """Take the digest of every file of a stage dir but its ``node_modules``.

    Args:
        stage: the stage dir.

    Returns:
        Each file's path below the stage dir with its sha256.
    """
    return {
        str(path.relative_to(stage)): found
        for path in walk(stage, stage / "node_modules", [])
        if (found := digest(path))
    }


def baseline(stage: Path) -> Path:
    return Path(f"{stage}{STAGED}")


def write_json(descriptor: int, data: dict[str, str]) -> None:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


def loaded(descriptor: int | None) -> dict[str, str]:
    """Read a digest list.

    Args:
        descriptor: an open file holding it, or None.

    Returns:
        Its digests, or none when it is missing or unreadable.
    """
    if descriptor is None:
        return {}
    with os.fdopen(descriptor, "rb") as handle:
        text = handle.read()
    with contextlib.suppress(ValueError):
        found = json.loads(text)
        if isinstance(found, dict):
            return {str(name): str(value) for name, value in found.items()}
    return {}


def private(info: os.stat_result) -> bool:
    return info.st_uid == os.geteuid() and not info.st_mode & WRITABLE


def base_dir(stage: Path) -> Path:
    """Check the dir that holds the stage dir and its digest list.

    Args:
        stage: the stage dir.

    Returns:
        The dir.

    Raises:
        SpecSecretsError: it is no directory that this user owns and alone
            can write.
    """
    info = stage.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or not private(info):
        raise spec_secrets.SpecSecretsError(
            f"{stage.parent} is not a directory only uid {os.geteuid()} can write"
        )
    return stage.parent


def keep_baseline(stage: Path) -> None:
    """Keep the digests of a freshly staged stage dir beside it.

    Args:
        stage: the stage dir; the list goes to ``<stage dir>.staged``, outside
            every mount a container gets, through a new file renamed over
            whatever was there, never written through it.
    """
    prefix = f".{stage.name}{STAGED}."
    descriptor, name = tempfile.mkstemp(prefix=prefix, dir=base_dir(stage))
    try:
        write_json(descriptor, digests(stage))
        Path(name).replace(baseline(stage))
    finally:
        with contextlib.suppress(FileNotFoundError):
            Path(name).unlink()


def read_baseline(stage: Path) -> dict[str, str]:
    """Read the digests the deploy kept of the fresh stage dir.

    Args:
        stage: the stage dir.

    Returns:
        The digests, or none when the list is missing or when another user
        could have written it or the dir that holds it.
    """
    try:
        base_dir(stage)
        descriptor = os.open(baseline(stage), os.O_RDONLY | os.O_NOFOLLOW)
    except (OSError, spec_secrets.SpecSecretsError):
        return {}
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or not private(info):
        os.close(descriptor)
        return {}
    return loaded(descriptor)


def record_staged(directory: Path, kept: dict[str, str]) -> None:
    """Keep the digests the masker took before the run in the run directory.

    Args:
        directory: the run directory, which keeps them as ``STAGED`` for a
            scrub after a kill.
        kept: the digests.
    """
    run = spec_secrets.open_run(directory)
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        descriptor = os.open(STAGED, flags, 0o600, dir_fd=run)
    finally:
        os.close(run)
    write_json(descriptor, kept)


def read_staged(directory: Path, stage: Path) -> dict[str, str]:
    """Read the digests of the stage files a scrub leaves alone.

    Args:
        directory: the run directory.
        stage: the stage dir.

    Returns:
        The digests the masker took before this run; without them, when no
        run started, those the deploy took of the fresh stage dir; without
        trusted ones, none, so every stage file holding a value is masked.
    """
    run = spec_secrets.open_run(directory)
    try:
        descriptor = os.open(STAGED, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=run)
    except FileNotFoundError:
        return read_baseline(stage)
    finally:
        os.close(run)
    return loaded(descriptor)


def remove_container(directory: Path, cli: str) -> None:
    """Force-remove the container the run directory's ``CID`` names.

    Args:
        directory: the run directory.
        cli: the container tool, such as ``container`` or ``docker``.
    """
    with contextlib.suppress(OSError):
        container = (directory / CID).read_text(encoding="utf-8").strip()
        if container:
            subprocess.run(
                [cli, "rm", "--force", container], capture_output=True, check=False
            )


def scrub_file(path: Path, automaton: Automaton) -> bool:
    """Mask a regular file in place, streamed in chunks; links are left alone.

    Args:
        path: the file.
        automaton: the values to mask.

    Returns:
        Whether it held a value; only then it is replaced, by a ``TEMP``
        sibling with its mode, which holds masked bytes only.
    """
    if not stat.S_ISREG(path.lstat().st_mode):
        return False
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as source:
        read = partial(source.read, CHUNK)
        if not pump(read, lambda _data: None, Stream(automaton)):
            return False
        source.seek(0)
        mode = stat.S_IMODE(os.fstat(source.fileno()).st_mode)
        descriptor, name = tempfile.mkstemp(prefix=TEMP, dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as target:
                os.fchmod(target.fileno(), mode)
                pump(read, target.write, Stream(automaton))
            Path(name).replace(path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                Path(name).unlink()
    return True


def scrub(
    stage: Path, reports: Path, automaton: Automaton, kept: dict[str, str]
) -> int:
    """Mask the files of a run's stage and reports dirs, whatever their age.

    Args:
        stage: the stage dir; its ``node_modules``, npm's install tree or the
            shared read-only mount, is left out, no reporter writes there.
        reports: the reports dir, every file of it.
        automaton: the values to mask.
        kept: the digests of the stage files to leave alone while unchanged.

    Returns:
        0, or 1 when a path could not be read or rewritten.
    """
    failed: list[OSError] = []
    roots = ((stage, stage / "node_modules"), (reports, None))
    for root, skipped in roots if automaton.grams else ():
        for path in walk(root, skipped, failed):
            name = str(path.relative_to(root))
            if root == stage and kept.get(name, "") == digest(path):
                continue
            try:
                scrub_file(path, automaton)
            except FileNotFoundError:
                continue
            except OSError as error:
                failed.append(error)
    if failed:
        print(f"spec secrets: {len(failed)} paths not masked", file=sys.stderr)
    return 1 if failed else 0


def relay(source, target, automaton: Automaton) -> None:
    """Copy a pipe masked, and keep draining it once the target is gone.

    Args:
        source: the child's binary pipe.
        target: this process's binary stream.
        automaton: the values to mask.
    """
    broken = []

    def write(data: bytes) -> None:
        if data and not broken:
            try:
                target.write(data)
                target.flush()
            except OSError as error:
                broken.append(error)

    pump(partial(source.read1, CHUNK), write, Stream(automaton))


def mask(directory: Path, stage: Path, reports: Path, command: list[str]) -> int:
    """Run the container command with its output and its files masked.

    Args:
        directory: the run directory whose values get masked; ``CID`` in it
            names the container once the command wrote it there.
        stage: the run's stage dir, whose digests are taken before the run.
        reports: the run's reports dir.
        command: the container command; ``command[0] rm --force`` stops it.

    Returns:
        The command's exit code, 128 plus the signal when a signal ended it.
        On HUP, INT or TERM the container is removed first, since its PID 1
        ignores them, and the files are masked before this returns, with
        the values and digests read before the run, so a run directory
        removed meanwhile changes nothing.
    """
    automaton = Automaton(masked_values(directory))
    kept = digests(stage)
    record_staged(directory, kept)
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def stop(received: int, _frame: object) -> None:
        remove_container(directory, command[0])
        child.send_signal(received)

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    relays = [
        threading.Thread(target=relay, args=(pipe, out.buffer, automaton))
        for pipe, out in ((child.stdout, sys.stdout), (child.stderr, sys.stderr))
    ]
    for thread in relays:
        thread.start()
    for thread in relays:
        thread.join()
    code = child.wait()
    scrub(stage, reports, automaton, kept)
    return code if code >= 0 else 128 - code


def main(argv: list[str]) -> int:
    """Mask a run, never printing a key or a value.

    Args:
        argv: the program name and ``baseline <stage dir>``, ``mask <run
            dir> <stage dir> <reports dir> -- <command>`` or ``scrub <run
            dir> <stage dir> <reports dir> [<container cli>]``; ``baseline``
            keeps the digests of a freshly staged stage dir for every later
            scrub; with the tool given, ``scrub`` first force-removes the
            run's container.

    Returns:
        ``mask``: the command's exit code; ``baseline`` and ``scrub``: 0, or
        1 when a path could not be read or masked; 1 on a refused run
        directory, 2 on bad usage.
    """
    command = argv[1:]
    paths = [Path(path) for path in command[1:4]]
    try:
        if command[:1] == ["baseline"] and len(command) == 2:
            keep_baseline(paths[0])
            return 0
        if command[:1] == ["mask"] and command[4:5] == ["--"] and command[5:]:
            return mask(*paths, command[5:])
        if command[:1] == ["scrub"] and len(command) in {4, 5}:
            automaton = Automaton(masked_values(paths[0]))
            for cli in command[4:]:
                remove_container(paths[0], cli)
            return scrub(*paths[1:], automaton, read_staged(*paths[:2]))
    except spec_secrets.SpecSecretsError as error:
        print(f"spec secrets refused: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"spec secrets failed: {error.strerror or 'error'}", file=sys.stderr)
        return 1
    print(f"usage: {argv[0]} {USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
