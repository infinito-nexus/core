#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import os
import re
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

PARENT = Path("/tmp/infinito-playwright-spec-secrets")  # noqa: S108 - each uid gets PARENT-<uid>, which open_owned refuses unless it is a 0700 dir of that uid, never followed
PREFIX = "run."
RENDERED = ".rendered"
KEY = re.compile(r"[A-Z][A-Z0-9_]*")
NAME_MAX = 255
MASK_MIN = 8
STALE_SECONDS = 86400
BREAKS = re.compile(
    "[\r\x0b\x0c\x1c\x1d\x1e\x85\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}]"
)
CONTROL = re.compile("[\x00-\x1f\x7f-\x9f]")
INVISIBLE = re.compile("[\N{ZERO WIDTH SPACE}\N{SOFT HYPHEN}]")
SPACES = re.compile(r"[\s\N{ZERO WIDTH NO-BREAK SPACE}]+")
DIR_MODE = 0o700
FILE_MODE = 0o400
OPEN_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
MASKER = "spec_secrets_mask.py"
PYTHON = ["python3", "-I", "-B"]
RUNNER = (
    "/bin/bash",
    "-lc",
    'exec "$@"',
    "playwright",
    "npx",
    "--no-install",
    "playwright",
    "test",
)
PATTERN = re.compile(r"[A-Za-z0-9_.:/][A-Za-z0-9 _.:/-]*")
NUMBER = re.compile(r"[0-9]+")
NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
SPEC = re.compile(r"(?!.*\.\.)[A-Za-z0-9_][A-Za-z0-9_./:-]*")
OPTIONS = {
    "--grep": PATTERN,
    "-g": PATTERN,
    "--grep-invert": PATTERN,
    "--retries": NUMBER,
    "--workers": NUMBER,
    "--max-failures": NUMBER,
    "--project": NAME,
}
ALLOWED = (
    "--grep, --grep-invert or -g with a pattern of [A-Za-z0-9 _.:/-], --retries,"
    " --workers or --max-failures with a number, --project with a name, and spec"
    " paths"
)
USAGE = (
    "prune | create | split <run dir> | arguments [<argument>...] | guard <command>..."
)


class SpecSecretsError(Exception):
    pass


def normalized(value: bytes) -> bytes:
    """Normalise a value as Playwright's ``normalizeWhiteSpace`` prints a name.

    Args:
        value: the value, UTF-8.

    Returns:
        It without zero-width spaces and soft hyphens, white space runs one
        space, trimmed.
    """
    text = value.decode("utf-8", "surrogateescape")
    text = SPACES.sub(" ", INVISIBLE.sub("", text)).strip(" ")
    return text.encode("utf-8", "surrogateescape")


def parse(text: str) -> dict[str, str]:
    """Map the rendered ``KEY=VALUE`` lines, naming a bad line by number only.

    Args:
        text: the rendered ``templates/playwright.secrets.j2``.

    Returns:
        Every key with its value, in template order. Lines end at ``\\n`` only;
        blank and ``#`` lines are skipped. A value is refused whose
        ``normalized`` form, as a report prints it, has fewer than
        ``MASK_MIN`` bytes, or that holds a C0 or C1 control character or DEL,
        which a report may drop and so split the value into pieces no window
        holds; that message names the key, never the value.
    """
    entries: dict[str, str] = {}
    for number, line in enumerate(text.split("\n"), start=1):
        if BREAKS.search(line):
            raise SpecSecretsError(f"line {number} holds a line break other than LF")
        if not line.strip() or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not KEY.fullmatch(key) or len(key) > NAME_MAX:
            raise SpecSecretsError(
                f"line {number} is not KEY=VALUE with KEY matching {KEY.pattern}"
                f" in at most {NAME_MAX} characters"
            )
        if key in entries:
            raise SpecSecretsError(f"line {number} repeats an earlier key")
        if CONTROL.search(value):
            raise SpecSecretsError(
                f"line {number}: the value of {key} holds a control character,"
                " which a report may drop; encode it in the template"
            )
        if len(normalized(value.encode("utf-8"))) < MASK_MIN:
            raise SpecSecretsError(
                f"line {number} holds a value of fewer than {MASK_MIN} bytes once"
                " white space is collapsed, which the masker cannot hide"
            )
        entries[key] = value
    return entries


def allowed(words: list[str]) -> bool:
    """Tell whether Playwright arguments stay inside ``OPTIONS`` and spec paths.

    Args:
        words: the arguments, each one word.

    Returns:
        Whether each word is an option of ``OPTIONS`` with a value its
        pattern accepts, inline after ``=`` or as the next word, or a spec
        path; anything else, a reporter, a trace or a config included, is
        refused.
    """
    expected = None
    for word in words:
        if expected is not None:
            if not expected.fullmatch(word):
                return False
            expected = None
            continue
        name, equals, value = word.partition("=")
        if name in OPTIONS:
            if equals and not OPTIONS[name].fullmatch(value):
                return False
            expected = None if equals else OPTIONS[name]
        elif not SPEC.fullmatch(word):
            return False
    return expected is None


def check_arguments(arguments: list[str]) -> None:
    """Refuse Playwright arguments a role with spec secrets does not accept.

    Args:
        arguments: the arguments, each one word.

    Raises:
        SpecSecretsError: one is outside ``ALLOWED``.
    """
    if not allowed(arguments):
        raise SpecSecretsError(f"a role with spec secrets accepts {ALLOWED} only")


def playwright(arguments: list[str]) -> list[str]:
    """Build the only command a container with spec secrets runs.

    Args:
        arguments: the Playwright arguments, each one word.

    Returns:
        ``RUNNER`` with the arguments, which its shell hands to Playwright as
        words without parsing them.

    Raises:
        SpecSecretsError: an argument is outside ``ALLOWED``.
    """
    check_arguments(arguments)
    return [*RUNNER, *arguments]


def read_values(directory: Path) -> list[bytes]:
    """Read the values of a run directory.

    Args:
        directory: a run directory below a parent of ``parent``.

    Returns:
        Every value; the split refuses one shorter than ``MASK_MIN`` bytes.
    """
    run = open_run(directory)
    values = []
    try:
        for name in filter(KEY.fullmatch, os.listdir(run)):
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=run)
            with os.fdopen(descriptor, "rb") as handle:
                values.append(handle.read())
    finally:
        os.close(run)
    return values


def parent(uid: int) -> Path:
    """Name the parent of one user's run directories.

    Args:
        uid: the user.

    Returns:
        ``PARENT`` with ``-<uid>`` appended, so root, a login user and an
        operator never need each other's parent.
    """
    return PARENT.with_name(f"{PARENT.name}-{uid}")


def run_owner(directory: Path) -> int:
    """Read the user a run directory's parent is named after.

    Args:
        directory: the run directory.

    Returns:
        The uid; this process must be that user or root.
    """
    suffix = directory.parent.name.removeprefix(f"{PARENT.name}-")
    uid = int(suffix) if NUMBER.fullmatch(suffix) else -1
    if not directory.name.startswith(PREFIX) or directory.parent != parent(uid):
        raise SpecSecretsError(
            f"{directory} is not a run directory below {PARENT}-<uid>"
        )
    if os.geteuid() not in (0, uid):
        raise SpecSecretsError(f"{directory} belongs to uid {uid}, not {os.geteuid()}")
    return uid


def open_owned(
    name: Path | str, dir_fd: int | None = None, uid: int | None = None
) -> int:
    """Open a directory without following a link, refusing one others can reach.

    Args:
        name: the directory, relative to ``dir_fd`` when one is given.
        dir_fd: an open directory to look ``name`` up in.
        uid: the user that must own it; None for this process's user.

    Returns:
        The open descriptor of the accepted directory.
    """
    owner = os.geteuid() if uid is None else uid
    try:
        descriptor = os.open(name, OPEN_DIR, dir_fd=dir_fd)
    except OSError as error:
        raise SpecSecretsError(f"{name} is not a directory: {error.strerror}") from None
    info = os.fstat(descriptor)
    problem = ""
    if info.st_uid != owner:
        problem = f"{name} is owned by uid {info.st_uid}, not {owner}"
    elif stat.S_IMODE(info.st_mode) != DIR_MODE:
        problem = (
            f"{name} has mode {stat.S_IMODE(info.st_mode):04o}, expected {DIR_MODE:04o}"
        )
    if problem:
        os.close(descriptor)
        raise SpecSecretsError(problem)
    return descriptor


def users() -> list[int]:
    """List the users whose parents this process prunes.

    Returns:
        Its own uid, and for root every uid a parent next to ``PARENT`` is
        named after, so a deploy's root prune also reaches the login user's.
    """
    if os.geteuid():
        return [os.geteuid()]
    try:
        names = os.listdir(PARENT.parent)
    except FileNotFoundError:
        return [0]
    prefix = f"{PARENT.name}-"
    suffixes = [name[len(prefix) :] for name in names if name.startswith(prefix)]
    return sorted({0, *map(int, filter(NUMBER.fullmatch, suffixes))})


def prune_parent(uid: int) -> int:
    """Remove the stale run directories of one user's parent.

    Args:
        uid: the user.

    Returns:
        The number removed; a missing parent removes nothing, and a run
        directory that cannot be removed whole, such as one holding files
        another user wrote, is named and skipped.
    """
    if not os.path.lexists(parent(uid)):
        return 0
    removed = 0
    top = open_owned(parent(uid), uid=uid)
    try:
        for name in os.listdir(top):
            if not name.startswith(PREFIX):
                continue
            try:
                run = open_owned(name, dir_fd=top, uid=uid)
            except SpecSecretsError:
                continue
            try:
                changed = os.fstat(run).st_mtime
            finally:
                os.close(run)
            if time.time() - changed < STALE_SECONDS:
                continue
            try:
                shutil.rmtree(name, dir_fd=top)
            except OSError as error:
                print(f"spec secrets prune skipped {name}: {error.strerror}")
                continue
            removed += 1
    finally:
        os.close(top)
    return removed


def prune() -> int:
    """Remove the run directories that only a killed run leaves.

    Returns:
        The number removed below the parents of ``users``: those unchanged
        for ``STALE_SECONDS``, a day; the age alone decides, no check tells a
        live run from a killed one.
        A foreign parent is skipped and named.
    """
    removed = 0
    for uid in users():
        try:
            removed += prune_parent(uid)
        except SpecSecretsError as error:
            print(f"spec secrets prune skipped: {error}")
        except OSError as error:
            print(f"spec secrets prune skipped {parent(uid)}: {error.strerror}")
    return removed


def create() -> Path:
    """Create a run directory below this user's parent.

    Returns:
        The new directory, mode 0700.
    """
    mine = parent(os.geteuid())
    with contextlib.suppress(FileExistsError):
        mine.mkdir(mode=DIR_MODE)
    try:
        os.close(open_owned(mine))
    except SpecSecretsError as error:
        raise SpecSecretsError(
            f"{error}; remove it with rm -rf -- {mine} so the next run recreates it"
        ) from None
    return Path(tempfile.mkdtemp(prefix=PREFIX, dir=mine))


def write(run: int, entries: dict[str, str]) -> None:
    """Write each value to a file named after its key, readable by its owner only.

    Args:
        run: the descriptor of the accepted run directory.
        entries: the parsed keys and values.
    """
    for key, value in entries.items():
        try:
            descriptor = os.open(
                key,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                FILE_MODE,
                dir_fd=run,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                os.fchmod(handle.fileno(), FILE_MODE)
                handle.write(value)
        except OSError as error:
            raise SpecSecretsError(f"writing a file failed: {error.strerror}") from None


def open_run(directory: Path) -> int:
    """Open a run directory below a user's parent without following a link.

    Args:
        directory: the run directory.

    Returns:
        The open descriptor of the accepted run directory: its parent and it
        belong to the uid the parent is named after, which is this process's
        or, for root, any user's, such as the login user a deploy's
        ``create`` ran as.
    """
    uid = run_owner(directory)
    top = open_owned(parent(uid), uid=uid)
    try:
        return open_owned(directory.name, dir_fd=top, uid=uid)
    finally:
        os.close(top)


def check_masked(argv: list[str]) -> None:
    """Refuse a run command that does not start with the masker shipped next to this helper.

    Args:
        argv: the command a run with spec secrets is about to execute.

    Raises:
        SpecSecretsError: it does not start with ``python3 -I -B``, the
            ``MASKER`` in this helper's directory, ``mask``, an accepted run
            directory, a reports dir and ``--``, so a variable turned the
            masker off or changed it.
    """
    masker = str(Path(__file__).with_name(MASKER))
    if argv[:5] != [*PYTHON, masker, "mask"] or argv[7:8] != ["--"]:
        raise SpecSecretsError(f"a run with spec secrets must start with {masker} mask")
    os.close(open_run(Path(argv[5])))


def split(directory: Path) -> int:
    """Turn the rendered template in a run directory into one file per key.

    Args:
        directory: a run directory below ``PARENT`` holding the rendered
            template as ``RENDERED``, which is removed before it is parsed.

    Returns:
        The number of files written; a refused template writes none.
    """
    run = open_run(directory)
    try:
        try:
            descriptor = os.open(RENDERED, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=run)
        except OSError as error:
            raise SpecSecretsError(
                f"reading {RENDERED} failed: {error.strerror}"
            ) from None
        with os.fdopen(descriptor, "rb") as handle:
            os.unlink(RENDERED, dir_fd=run)
            rendered = handle.read()
        try:
            entries = parse(rendered.decode("utf-8"))
        except UnicodeDecodeError:
            raise SpecSecretsError("the rendered template is not UTF-8") from None
        write(run, entries)
        return len(entries)
    finally:
        os.close(run)


def main(argv: list[str]) -> int:
    """Run one command and report paths or counts, never a key or a value.

    Args:
        argv: the program name and ``prune``, ``create``, ``split <run dir>``,
            ``arguments [<argument>...]`` or ``guard <command>...``, which
            replaces this process with the command once ``check_masked``
            accepted it, so the command it checks is the command that runs.

    Returns:
        0 on success and on a prune that skips a foreign parent or a run
        it cannot remove, 1 on a refused template, directory, argument or
        guarded command, 2 on bad usage.
    """
    command = argv[1:]
    try:
        if command[:1] == ["guard"]:
            check_masked(command[1:])
            os.execvp(command[1], command[1:])  # noqa: S606 - runs exactly the command check_masked accepted
        elif command[:1] == ["arguments"]:
            check_arguments(command[1:])
        elif command == ["prune"]:
            removed = prune()
            print(f"spec secrets removed: {removed}" if removed else "nothing to prune")
        elif command == ["create"]:
            print(create())
        elif len(command) == 2 and command[0] == "split":
            written = split(Path(command[1]))
            print(f"spec secrets files written: {written}")
        else:
            print(f"usage: {argv[0]} {USAGE}", file=sys.stderr)
            return 2
    except SpecSecretsError as error:
        print(f"spec secrets refused: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"spec secrets failed: {error.strerror or 'error'}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
