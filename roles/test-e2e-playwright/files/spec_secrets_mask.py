#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import errno
import os
import shutil
import signal
import stat
import subprocess
import sys
import threading
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

sys.path.append(str(Path(__file__).parent))

import spec_secrets
from spec_secrets_container import (
    check_container,
    cid_named,
    container_env,
    remove_container,
)
from spec_secrets_match import CHUNK, Stream, named, pump, relay, windows

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

UNSETTLED = 70
UNSETTLED_MARK = ".unsettled"
STAGED = "reports"
TEMP = ".masked."
OPEN_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
CREATE_FILE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
PUBLISHED_FILE = 0o644
PUBLISHED_DIR = 0o755
CREATE_MARK = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
USAGE = (
    "mask <run dir> <reports dir> -- <container command> -- [<argument>...]"
    " | scrub <run dir> <reports dir> <container cli> [<container name>]"
)


def open_root(root: Path) -> int | None:
    """Open a reports dir without following a link.

    Args:
        root: the directory.

    Returns:
        Its descriptor, or None when it is missing.

    Raises:
        SpecSecretsError: it is a link or no directory.
    """
    try:
        return os.open(root, spec_secrets.OPEN_DIR)
    except FileNotFoundError:
        return None
    except OSError:
        raise spec_secrets.SpecSecretsError(
            f"{root} is a link or no directory, it is not masked"
        ) from None


def walk(root: Path, failed: list[Exception]) -> Iterator[tuple[int, str]]:
    """List the files below a directory, never following a link.

    Args:
        root: the directory; a missing one holds nothing.
        failed: collects the errors of directories that cannot be read.

    Yields:
        Per file, ``TEMP`` ones included, its open directory until the next one.
    """

    def unreadable(error: OSError) -> None:
        if not isinstance(error, FileNotFoundError):
            failed.append(error)

    top = open_root(root)
    if top is None:
        return
    try:
        for _here, _dirs, files, at in os.fwalk(".", onerror=unreadable, dir_fd=top):
            for name in files:
                yield at, name
    finally:
        os.close(top)


def open_file(at: int, name: str) -> int | None:
    """Open a regular file of a directory without following a link.

    Args:
        at: the open directory.
        name: the file's name in it.

    Returns:
        Its descriptor, or None when it is gone, a link or no regular file.
    """
    try:
        if not stat.S_ISREG(os.stat(name, dir_fd=at, follow_symlinks=False).st_mode):
            return None
        descriptor = os.open(name, OPEN_FILE, dir_fd=at)
    except FileNotFoundError:
        return None
    except OSError as error:
        if error.errno == errno.ELOOP:
            return None
        raise
    if stat.S_ISREG(os.fstat(descriptor).st_mode):
        return descriptor
    os.close(descriptor)
    return None


def swap(at: int, name: str, mode: int, fill: Callable[[BinaryIO], object]) -> None:
    """Write a ``TEMP`` sibling of a name, then rename it over the name.

    Args:
        at: the open directory that holds the name.
        name: the name; a FIFO, device or hard link there is replaced, unopened.
        mode: the exact mode the file gets once written.
        fill: writes the file's bytes into the open sibling.
    """
    temp = f"{TEMP}{os.urandom(8).hex()}"
    written = os.open(temp, CREATE_FILE, 0o600, dir_fd=at)
    try:
        with os.fdopen(written, "wb") as target:
            fill(target)
            target.flush()
            os.fchmod(target.fileno(), mode)
        os.replace(temp, name, src_dir_fd=at, dst_dir_fd=at)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp, dir_fd=at)


def scrub_file(at: int, name: str, masks: frozenset[bytes]) -> bool:
    """Mask a regular file in place, streamed in chunks; links are left alone.

    Args:
        at: the open directory that holds the file.
        name: the file's name in it.
        masks: the windows to mask.

    Returns:
        Whether it held a window; only then ``swap`` masks it, its permission
        bits kept and any setuid, setgid or sticky bit dropped.
    """
    descriptor = open_file(at, name)
    if descriptor is None:
        return False
    with os.fdopen(descriptor, "rb") as source:
        read = partial(source.read, CHUNK)
        if not pump(read, lambda _data: None, Stream(masks)):
            return False
        source.seek(0)
        mode = stat.S_IMODE(os.fstat(source.fileno()).st_mode) & 0o777
        swap(at, name, mode, lambda target: pump(read, target.write, Stream(masks)))
    return True


def scrub(reports: Path, masks: frozenset[bytes]) -> int:
    """Mask every file of a run's reports dir, whatever its age.

    Args:
        reports: the reports dir.
        masks: the windows to mask.

    Returns:
        0, or 1 when a path could not be read or rewritten or the reports
        dir is a link, which is not walked.
    """
    failed: list[Exception] = []
    try:
        for at, name in walk(reports, failed) if masks else ():
            try:
                scrub_file(at, name, masks)
            except FileNotFoundError:
                continue
            except OSError as error:
                failed.append(error)
    except spec_secrets.SpecSecretsError as error:
        print(f"spec secrets: {error}", file=sys.stderr)
        failed.append(error)
    if failed:
        print(f"spec secrets: {len(failed)} paths not masked", file=sys.stderr)
    return 1 if failed else 0


def open_dir(name: str | Path, at: int | None = None) -> int:
    """Open one directory of the published reports, created when missing, never through a link.

    Args:
        name: its name in ``at``, or the reports dir itself.
        at: the open parent directory, None for the reports dir.

    Returns:
        Its descriptor, set to exactly ``PUBLISHED_DIR``, created or reused, so
        no setgid bit of a parent or an earlier run and no umask is left; the
        ``TEMP`` regular files a killed masker left in it are removed.

    Raises:
        OSError: it is a link or no directory, or its parent is missing.
    """
    with contextlib.suppress(FileExistsError):
        os.mkdir(name, PUBLISHED_DIR, dir_fd=at)
    descriptor = os.open(name, spec_secrets.OPEN_DIR, dir_fd=at)
    try:
        os.fchmod(descriptor, PUBLISHED_DIR)
        with os.scandir(descriptor) as entries:
            files = [e.name for e in entries if e.is_file(follow_symlinks=False)]
        for temp in (name for name in files if name.startswith(TEMP)):
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp, dir_fd=descriptor)
    except OSError:
        os.close(descriptor)
        raise
    return descriptor


def open_into(root: int, here: str) -> int:
    """Open the directory a published file goes into, one component at a time.

    Args:
        root: the open reports dir.
        here: the file's directory, relative to it.

    Returns:
        The open directory; ``open_dir`` created or reused each component
        relative to the one before, so no link on the way is followed.
    """
    into = os.dup(root)
    for part in Path(here).parts:
        try:
            inner = open_dir(part, into)
        finally:
            os.close(into)
        into = inner
    return into


def publish(staged: Path, reports: Path, masks: frozenset[bytes]) -> int:
    """Copy the regular files of the masked staged reports into the reports dir.

    Args:
        staged: the run's masked reports; links and special files stay there.
        reports: the collected reports dir, created when missing below an
            existing parent; it or a directory below it that is a link fails.
        masks: the windows no published path may hold.

    Returns:
        The number of files left unpublished because their path below
        ``staged`` holds a window; a directory is created only for a file.
    """
    root, top, refused = open_dir(reports), None, 0
    try:
        top = open_root(staged)
        walked = os.fwalk(".", dir_fd=top) if top is not None else ()
        for here, _dirs, files, at in walked:
            into = None
            try:
                for name in files:
                    if name.startswith(TEMP):
                        continue
                    if named(str(Path(here, name)), masks):
                        refused += 1
                        continue
                    source = open_file(at, name)
                    if source is None:
                        continue
                    with os.fdopen(source, "rb") as handle:
                        into = open_into(root, here) if into is None else into
                        copy = partial(shutil.copyfileobj, handle)
                        swap(into, name, PUBLISHED_FILE, copy)
            finally:
                if into is not None:
                    os.close(into)
    finally:
        os.close(root)
        if top is not None:
            os.close(top)
    return refused


def settle(
    directory: Path, reports: Path, masks: frozenset[bytes], gone: bool, name: str
) -> int:
    """Mask the reports a run staged in its directory, then publish or delete them.

    Args:
        directory: the run directory; the container wrote into its ``STAGED``.
        reports: the collected reports dir, which only ever gets masked files.
        masks: the windows to mask.
        gone: whether ``remove_container`` proved that no container writes
            into ``STAGED`` any more.
        name: the name ``remove_container`` got, which the message names
            while no ``CID`` names the container; empty for none.

    Returns:
        0 once every staged file is masked, published and deleted, else 1; the
        reports go unpublished when the container, which the message names, may
        still run or a file could not be masked.
    """
    staged = directory / STAGED
    failed = 1
    if not gone:
        print(
            f"spec secrets: container {cid_named(directory) or name or 'unnamed'}"
            " may still run, its reports were deleted unpublished",
            file=sys.stderr,
        )
    elif scrub(staged, masks):
        if os.path.lexists(staged):
            print(
                "spec secrets: the run's reports were deleted unpublished",
                file=sys.stderr,
            )
    else:
        try:
            refused = publish(staged, reports, masks)
        except (OSError, spec_secrets.SpecSecretsError) as error:
            print(
                f"spec secrets: publishing the reports failed: {error}", file=sys.stderr
            )
        else:
            failed = 1 if refused else 0
            if refused:
                print(
                    f"spec secrets: {refused} reports whose path holds a value"
                    " were not published",
                    file=sys.stderr,
                )
    shutil.rmtree(staged, ignore_errors=True)
    if os.path.lexists(staged):
        print("spec secrets: the staged reports were not deleted", file=sys.stderr)
        failed = 1
    return failed


def mask(directory: Path, reports: Path, command: list[str]) -> int:
    """Run the container command with its output and its reports masked.

    Args:
        directory: the run directory whose values get masked; ``CID`` in it
            names the container once the command wrote it there, and the
            command mounts its ``STAGED`` dir, created here, as the reports.
        reports: the collected reports dir, which must not be a link.
        command: the container command, run with ``container_env`` only;
            ``command[0] rm --force`` stops it.

    Returns:
        The command's exit code or 128 plus the signal that ended it;
        ``UNSETTLED``, which no Playwright failure exits with, whenever its
        container could not be proven gone or its reports not be masked and
        published. HUP, INT or TERM, which its PID 1 ignores, and the end of
        the command remove the container and prove it gone before the reports
        settle; a removal before ``CID`` named a container runs again.
    """
    masks = windows(spec_secrets.read_values(directory))
    root = open_root(reports)
    if root is not None:
        os.close(root)
    (directory / STAGED).mkdir(mode=spec_secrets.DIR_MODE, exist_ok=True)
    piped = subprocess.PIPE
    child = subprocess.Popen(command, stdout=piped, stderr=piped, env=container_env())
    removals: list[bool] = []

    def removed() -> bool:
        if removals:
            return removals[0]
        known = cid_named(directory)
        gone = remove_container(directory, command[0], "")
        if known:
            removals.append(gone)
        return gone

    def stop(received: int, _frame: object) -> None:
        removed()
        child.send_signal(received)

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    relays = [
        threading.Thread(target=relay, args=(pipe, out.buffer, masks))
        for pipe, out in ((child.stdout, sys.stdout), (child.stderr, sys.stderr))
    ]
    for thread in relays:
        thread.start()
    for thread in relays:
        thread.join()
    code = child.wait()
    scrubbed = settle(directory, reports, masks, removed(), "")
    return UNSETTLED if scrubbed else (code if code >= 0 else 128 - code)


def unsettled(directory: Path) -> None:
    """Leave ``UNSETTLED_MARK`` in a run directory, so its later scrub fails too.

    Args:
        directory: the run directory; a refused one gets no mark, its scrub
            refuses it anyway.
    """
    try:
        run = spec_secrets.open_run(directory)
    except spec_secrets.SpecSecretsError:
        return
    try:
        with contextlib.suppress(OSError):
            os.close(os.open(UNSETTLED_MARK, CREATE_MARK, 0o600, dir_fd=run))
    finally:
        os.close(run)


def guarded_mask(paths: list[Path], container: list[str], arguments: list[str]) -> int:
    """Run ``mask`` and mark the run when the masker itself failed.

    Args:
        paths: the run directory and the collected reports dir.
        container: the container command up to and including the image,
            which ``check_container`` holds against the one a run with spec
            secrets starts.
        arguments: the Playwright arguments; ``spec_secrets.playwright``
            checks them and appends the only command a run with spec secrets
            runs, so no variable a caller renders reaches the container.

    Returns:
        What ``mask`` returns, or ``UNSETTLED`` when it refused or failed.
    """
    try:
        check_container(container, paths[0])
        code = mask(*paths, [*container, *spec_secrets.playwright(arguments)])
    except spec_secrets.SpecSecretsError as error:
        print(f"spec secrets refused: {error}", file=sys.stderr)
        code = UNSETTLED
    except OSError as error:
        print(f"spec secrets failed: {error.strerror or 'error'}", file=sys.stderr)
        code = UNSETTLED
    if code == UNSETTLED:
        unsettled(paths[0])
    return code


def main(argv: list[str]) -> int:
    """Mask a run, never printing a key or a value.

    Args:
        argv: the program name and the words of ``USAGE``; ``scrub`` first
            removes the run's container with the tool and proves it gone,
            the one ``CID`` names or else the one of the name it got, if
            any. Both settle the staged reports into the reports dir only then.

    Returns:
        ``mask``: what ``guarded_mask`` returns; ``scrub``: 0, or 1 when the
        container could not be proven gone, the reports could not be
        settled or the run's ``mask`` left ``UNSETTLED_MARK``; 1 on a
        refused run directory, 2 on bad usage.
    """
    command = argv[1:]
    paths = [Path(path) for path in command[1:3]]
    split = command.index("--", 5) if "--" in command[5:] else 0
    if command[:1] == ["mask"] and command[3:4] == ["--"] and split:
        return guarded_mask(paths, command[4:split], command[split + 1 :])
    try:
        if command[:1] == ["scrub"] and len(command) in {4, 5}:
            name = command[4] if len(command) == 5 else ""
            masks = windows(spec_secrets.read_values(paths[0]))
            gone = remove_container(paths[0], command[3], name)
            settled = settle(paths[0], paths[1], masks, gone, name)
            if os.path.lexists(paths[0] / UNSETTLED_MARK):
                print(
                    "spec secrets: the run's masker could not settle its reports",
                    file=sys.stderr,
                )
                return 1
            return settled
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
