"""Input set and tag hash of the root Dockerfile's toolchain stage.

The toolchain stage's ``COPY`` sources are the only list of what the local
image is built from: ``scripts/meta/resolve/image/local.sh`` hashes them into
the tag, ``scripts/image/build.sh`` stages exactly them as the build context,
and ``tests/lint/repository/test_toolchain_stage_inputs.py`` keeps the stage's
``RUN`` steps inside them.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

DOCKERFILE = "Dockerfile"
TOOLCHAIN_STAGE = "toolchain"
GLOBAL_SCOPE = ""
HASH_LENGTH = 16

_COPY_FLAGS_WITH_VALUE = ("--chown", "--chmod", "--from", "--exclude", "--parents")


@dataclass(frozen=True)
class Instruction:
    """One Dockerfile instruction with its continuation lines joined.

    Args:
        keyword: the upper-cased instruction (``COPY``, ``RUN``, ...).
        args: everything after the keyword.
        line: 1-based line the instruction starts on.
    """

    keyword: str
    args: str
    line: int


def instructions(text: str) -> list[Instruction]:
    """Split a Dockerfile into instructions, dropping comments and joining continuations.

    Args:
        text: the Dockerfile's content.
    """
    parsed: list[Instruction] = []
    buffer: list[str] = []
    start = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not buffer and (not stripped or stripped.startswith("#")):
            continue
        if buffer and stripped.startswith("#"):
            continue
        if not buffer:
            start = number
        if stripped.endswith("\\"):
            buffer.append(stripped[:-1])
            continue
        buffer.append(stripped)
        joined = " ".join(part.strip() for part in buffer if part.strip())
        buffer = []
        keyword, _, args = joined.partition(" ")
        parsed.append(Instruction(keyword.upper(), args.strip(), start))
    return parsed


def stages(text: str) -> dict[str, list[Instruction]]:
    """Group the instructions by build stage.

    Args:
        text: the Dockerfile's content.

    Returns:
        Stage name to its instructions, ``FROM`` included; the instructions
        before the first ``FROM`` sit under ``GLOBAL_SCOPE``.
    """
    grouped: dict[str, list[Instruction]] = {GLOBAL_SCOPE: []}
    current = GLOBAL_SCOPE
    for instruction in instructions(text):
        if instruction.keyword == "FROM":
            words = instruction.args.split()
            current = (
                words[-1]
                if len(words) >= 3 and words[-2].upper() == "AS"
                else f"#{len(grouped)}"
            )
            grouped[current] = []
        grouped[current].append(instruction)
    return grouped


def stage_base(text: str, stage: str) -> str:
    """Return the image or stage a stage starts ``FROM``.

    Args:
        text: the Dockerfile's content.
        stage: the stage name.
    """
    return stages(text)[stage][0].args.split()[0]


def _copy_operands(instruction: Instruction) -> tuple[list[str], bool]:
    words = shlex.split(instruction.args)
    operands: list[str] = []
    from_stage = False
    skip_value = False
    for word in words:
        if skip_value:
            skip_value = False
            continue
        if word.startswith("--"):
            name = word.split("=", 1)[0]
            from_stage = from_stage or name == "--from"
            skip_value = name in _COPY_FLAGS_WITH_VALUE and "=" not in word
            continue
        operands.append(word)
    return operands, from_stage


def copy_sources(text: str, stage: str = TOOLCHAIN_STAGE) -> list[str]:
    """Return the build-context paths the stage's ``COPY`` and ``ADD`` read.

    Args:
        text: the Dockerfile's content.
        stage: the stage whose sources are wanted.

    Raises:
        KeyError: the Dockerfile has no such stage.
    """
    sources: list[str] = []
    for instruction in stages(text)[stage]:
        if instruction.keyword not in {"COPY", "ADD"}:
            continue
        operands, from_stage = _copy_operands(instruction)
        if from_stage:
            continue
        for source in operands[:-1]:
            normalized = source.strip("/") or "."
            if normalized not in sources:
                sources.append(normalized)
    return sources


def build_arg_names(text: str, stage: str = TOOLCHAIN_STAGE) -> list[str]:
    """Return the ``ARG`` names in scope of the stage, the global ones included.

    Args:
        text: the Dockerfile's content.
        stage: the stage whose arguments are wanted.
    """
    grouped = stages(text)
    names: list[str] = []
    for instruction in [*grouped[GLOBAL_SCOPE], *grouped[stage]]:
        if instruction.keyword != "ARG":
            continue
        name = instruction.args.split("=", 1)[0].strip()
        if name not in names:
            names.append(name)
    return names


def _listed_files(root: Path, sources: list[str]) -> set[str]:
    try:
        out = subprocess.run(
            [
                "git",
                "-c",
                "safe.directory=*",
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                *sources,
            ],
            cwd=str(root),
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return _walked_files(root, sources)
    return {rel for rel in out.decode("utf-8", errors="replace").split("\0") if rel}


def _walked_files(root: Path, sources: list[str]) -> set[str]:
    found: set[str] = set()
    for source in sources:
        base = root / source
        if base.is_file():
            found.add(source)
            continue
        for directory, dirnames, filenames in os.walk(base):
            dirnames[:] = [name for name in dirnames if name != "__pycache__"]
            for filename in filenames:
                found.add((Path(directory) / filename).relative_to(root).as_posix())
    return found


def input_files(root: Path = PROJECT_ROOT) -> list[str]:
    """Return the repository files the toolchain stage copies, sorted.

    Tracked and untracked-but-not-ignored files below the ``COPY`` sources,
    as ``git ls-files`` sees them; without git, every file below them except
    ``__pycache__``. A tracked file deleted from the working tree is left out,
    because the build could not copy it either.

    Args:
        root: the checkout whose Dockerfile and files are read.
    """
    text = (root / DOCKERFILE).read_text(encoding="utf-8")  # nocheck: cache-read
    listed = _listed_files(root, copy_sources(text))
    return sorted(rel for rel in listed if (root / rel).is_file())


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def input_hash(
    root: Path,
    environ: Mapping[str, str],
    parent_id: str,
    files: Iterable[str] | None = None,
) -> str:
    """Return the tag hash of the toolchain image this checkout builds.

    Args:
        root: the checkout whose Dockerfile and files are hashed.
        environ: environment holding the values of the stage's build arguments.
        parent_id: ID of the parent image as pulled; empty when it is absent.
        files: the input set, defaults to :func:`input_files` of ``root``.

    Returns:
        The first ``HASH_LENGTH`` hex digits of a SHA-256 over the Dockerfile,
        every input file's path, executable bit and content, every build
        argument with its value and the parent image ID.
    """
    text = (root / DOCKERFILE).read_text(encoding="utf-8")  # nocheck: cache-read
    digest = hashlib.sha256()
    digest.update(f"dockerfile\0{_file_digest(root / DOCKERFILE)}\n".encode())
    for rel in input_files(root) if files is None else files:
        path = root / rel
        mode = "x" if os.access(path, os.X_OK) else "-"
        digest.update(f"file\0{rel}\0{mode}\0{_file_digest(path)}\n".encode())
    for name in sorted(build_arg_names(text)):
        digest.update(f"arg\0{name}={environ.get(name, '')}\n".encode())
    digest.update(f"parent\0{parent_id}\n".encode())
    return digest.hexdigest()[:HASH_LENGTH]


def main(argv: list[str] | None = None) -> int:
    """Print the input set (``files``) or the tag hash (``hash``) of this checkout.

    Args:
        argv: ``files`` or ``hash --parent-id <id>``.

    Returns:
        0 on success.
    """
    parser = argparse.ArgumentParser(prog="python -m utils.docker.image.toolchain")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("files")
    hashing = commands.add_parser("hash")
    hashing.add_argument("--parent-id", required=True)
    args = parser.parse_args(argv)
    if args.command == "files":
        print("\n".join(input_files()))
        return 0
    print(input_hash(PROJECT_ROOT, os.environ, args.parent_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
