from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from utils.env.handlers.infinito.cache.paths import machine
from utils.env.parser import CUSTOM_ENV
from utils.orchestrator.locks import hold

from .stack import normalize, stack_name

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import TextIO

REGISTRY_NAME = "stacks"
LOCK_NAME = "slots"
LEGACY_KEY = "INFINITO_INSTANCE"
DOTENV = ".env"
FIRST_SLOT = 1

_PIN = re.compile(rf"^{LEGACY_KEY}=(\d+)\s*$")


class SlotError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class Entry:
    stack: str
    slot: int
    checkout: str


def registry_root() -> Path:
    """Returns:
    The machine-wide slot registry below the cache base the paths SPOT names,
    outside every cache folder, so neither ``make cache-evict`` nor
    ``make clean-cache`` touches it.
    """
    return machine() / REGISTRY_NAME


def default_stack(checkout: Path) -> str:
    """Args:
        checkout: the checkout whose stack is meant.

    Returns:
        The stack the checkout addresses without ``INFINITO_STACK_NAME``.
    """
    return stack_name(checkout.resolve(), {})


def legacy_slot(checkout: Path) -> int | None:
    """Args:
        checkout: the checkout whose ``custom.env``, then ``.env``, is read.

    Returns:
        The last numeric ``INFINITO_INSTANCE=`` line of the first of the two
        that has one, or None; a missing or unreadable file pins nothing.
    """
    for name in (CUSTOM_ENV, DOTENV):
        try:
            with (checkout / name).open(encoding="utf-8", errors="replace") as handle:
                pins = [match[1] for match in map(_PIN.match, handle) if match]
        except OSError:
            continue
        if pins:
            return int(pins[-1])
    return None


def _checked(stack: str) -> str:
    if not stack or normalize(stack) != stack:
        raise SlotError(
            f"'{stack}' is no compose project name: use lowercase letters, "
            "digits, '_' and '-', starting with a letter or digit"
        )
    return stack


def _path(root: Path, stack: str) -> Path:
    return root / f"{stack}.json"


def _write(root: Path, entry: Entry) -> Entry:
    staged = root / f".{entry.stack}.json"
    with staged.open("w", encoding="utf-8") as handle:
        json.dump(dataclasses.asdict(entry), handle, sort_keys=True)
    staged.replace(_path(root, entry.stack))
    return entry


def _read(path: Path) -> Entry:
    with path.open(encoding="utf-8") as handle:
        entry = Entry(**json.load(handle))
    if not (
        entry.stack == path.stem
        and type(entry.slot) is int
        and isinstance(entry.checkout, str)
    ):
        raise ValueError("its stack, slot or checkout does not fit its file name")
    return entry


def entries(root: Path) -> dict[str, Entry]:
    """Args:
        root: the registry directory.

    Returns:
        Every recorded entry by its stack name; a damaged entry file is
        reported on stderr and counts as absent until its stack is written again.
    """
    if not root.is_dir():
        return {}
    found: dict[str, Entry] = {}
    for path in sorted(root.glob("*.json")):
        if path.name.startswith("."):
            continue
        try:
            entry = _read(path)
        except (ValueError, TypeError) as exc:
            print(
                f"WARNING: ignoring the damaged slot registry entry {path}: {exc}",
                file=sys.stderr,
            )
            continue
        found[entry.stack] = entry
    return found


def _live(entry: Entry, listed: set[str]) -> bool:
    return entry.checkout in listed or Path(entry.checkout).is_dir()


def _claim(root: Path, entry: Entry, home: Path, listed: set[str]) -> Entry:
    if entry.checkout == str(home):
        return entry
    if _live(entry, listed):
        raise SlotError(
            f"stack {entry.stack} holds slot {entry.slot} for {entry.checkout}; "
            f"{home} addresses the same compose project, so release that "
            "checkout with make worktree-down first"
        )
    return _write(root, dataclasses.replace(entry, checkout=str(home)))


def _pins(
    root: Path, current: dict[str, Entry], known: list[Path], last: int
) -> set[int]:
    pinned: set[int] = set()
    for home in known:
        slot = legacy_slot(home)
        if slot is None or not FIRST_SLOT <= slot <= last:
            continue
        pinned.add(slot)
        name = default_stack(home)
        if not name or name in current:
            continue
        if slot not in {entry.slot for entry in current.values()}:
            current[name] = _write(root, Entry(name, slot, str(home)))
    return pinned


def allocate(
    root: Path,
    stack: str,
    checkout: Path,
    known: Iterable[Path],
    taken: Iterable[int],
    last: int,
) -> int:
    """Args:
        root: the registry directory.
        stack: the stack the slot is recorded under.
        checkout: the existing checkout the stack runs from.
        known: every checkout ``git worktree list`` names; each one's current
            ``INFINITO_INSTANCE`` pin is never handed out, a pin whose default
            stack has no entry yet is recorded under it, and an entry of a
            listed checkout stays even while its directory is unreachable.
        taken: slots whose subnets a Docker network holds.
        last: the highest slot whose subnets stay valid.

    Returns:
        The slot the registry holds for the stack: its recorded one unless
        another checkout of ``known`` now pins it, else the lowest slot no
        entry, no pin of ``known`` and no network holds.

    Raises:
        SlotError: the name is no compose project name, the checkout does not
            exist, another live checkout holds the stack, or no slot is free.
        OSError: the registry cannot be written.
    """
    _checked(stack)
    home = checkout.resolve()
    if not home.is_dir():
        raise SlotError(f"{home} does not exist, so stack {stack} gets no slot")
    homes = [path.resolve() for path in known]
    listed = {str(path) for path in homes}
    with hold(root, LOCK_NAME):
        current = entries(root)
        own = current.get(stack)
        if own is not None:
            claimed = _claim(root, own, home, listed)
            foreign = {legacy_slot(path) for path in homes if path != home}
            if claimed.slot not in foreign:
                return claimed.slot
            _path(root, stack).unlink()
            del current[stack]
        for entry in list(current.values()):
            if not _live(entry, listed):
                _path(root, entry.stack).unlink()
                del current[entry.stack]
        pinned = _pins(root, current, homes, last)
        if stack in current:
            return _claim(root, current[stack], home, listed).slot
        used = {entry.slot for entry in current.values()} | pinned | set(taken)
        for slot in range(FIRST_SLOT, last + 1):
            if slot not in used:
                return _write(root, Entry(stack, slot, str(home))).slot
    raise SlotError(
        f"no free slot left in {FIRST_SLOT}..{last}; "
        "tear down a worktree with make worktree-down"
    )


def release(root: Path, checkout: Path) -> list[Entry]:
    """Args:
        root: the registry directory.
        checkout: the checkout whose stacks give their slots back.

    Returns:
        The removed entries, one per stack recorded for the checkout.

    Raises:
        OSError: the registry cannot be written.
    """
    home = str(checkout.resolve())
    with hold(root, LOCK_NAME):
        freed = [entry for entry in entries(root).values() if entry.checkout == home]
        for entry in freed:
            _path(root, entry.stack).unlink()
    return freed


def _refusal(root: Path, exc: OSError) -> str:
    handover = (
        f'sudo chown -R "$USER": {root}'
        if root.is_dir()
        else f'sudo install -d -o "$USER" {root}'
    )
    return (
        f"FAILURE: this user cannot write the slot registry {root} "
        f"({exc.strerror}); hand it over once: {handover}"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record the slot of each stack in the machine-wide registry."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    allocating = commands.add_parser(
        "allocate", help="print the slot of a checkout's default stack"
    )
    allocating.add_argument("checkout", type=Path)
    allocating.add_argument("--last", type=int, required=True)
    allocating.add_argument("--known", type=Path, nargs="*", required=True)
    allocating.add_argument("--taken", type=int, nargs="*", required=True)
    releasing = commands.add_parser(
        "release", help="free the slots of every stack of a checkout"
    )
    releasing.add_argument("checkout", type=Path)
    return parser


def run(argv: list[str], root: Path, out: TextIO, err: TextIO) -> int:
    """Args:
        argv: ``allocate <checkout> --last <n> --known <paths> --taken <slots>``
            or ``release <checkout>``.
        root: the registry directory.
        out: where the slot or the released slots go.
        err: where a refusal goes.

    Returns:
        0 on success, 1 on a refusal or a registry this user cannot write.
    """
    args = _parser().parse_args(argv)
    try:
        if args.command == "allocate":
            stack = default_stack(args.checkout)
            slot = allocate(
                root, stack, args.checkout, args.known, args.taken, args.last
            )
            print(slot, file=out)
            return 0
        freed = release(root, args.checkout)
    except SlotError as exc:
        print(f"FAILURE: {exc}", file=err)
        return 1
    except OSError as exc:
        print(_refusal(root, exc), file=err)
        return 1
    for entry in freed:
        print(f"Slot {entry.slot} of stack {entry.stack} released.", file=out)
    if not freed:
        print(f"No slot recorded for {args.checkout.resolve()}.", file=out)
    return 0


def main() -> int:
    return run(sys.argv[1:], registry_root(), sys.stdout, sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
