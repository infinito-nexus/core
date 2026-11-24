from __future__ import annotations

import itertools
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from cli.administration.deploy.development.stack import COMPOSE_KEY
from cli.administration.deploy.pool import teardown
from utils.runner.loop import (
    CHECKOUT_KEY,
    IMAGE_KEY,
    INSTALL_KEY,
    ROOTS_KEY,
    Runner,
    serve,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

QUEUE_KEY = "INFINITO_RUNNER_QUEUE_DIR"
SRC_KEY = "RUNNER_SRC_DIR"
POLL_SECONDS = 2.0


def _overlap(one: Path, other: Path) -> bool:
    return one.is_relative_to(other) or other.is_relative_to(one)


def _problems(paths: dict[str, str], roots: list[str]) -> list[str]:
    problems = [
        f"{key}={path!r} is no absolute path"
        for key, path in paths.items()
        if not path.startswith("/")
    ]
    if problems:
        return problems
    problems = [
        f"{key}={path} is or lies below a link"
        for key, path in paths.items()
        if os.path.realpath(path) != os.path.normpath(path)
    ]
    spaces = {
        QUEUE_KEY: Path(paths[QUEUE_KEY]),
        INSTALL_KEY: Path(paths[INSTALL_KEY]),
        **{f"{ROOTS_KEY} {root}": Path(root) for root in roots},
    }
    problems += [
        f"{one} and {other} overlap"
        for one, other in itertools.combinations(spaces, 2)
        if not (one.startswith(ROOTS_KEY) and other.startswith(ROOTS_KEY))
        and _overlap(spaces[one], spaces[other])
    ]
    src, checkout = Path(paths[SRC_KEY]), Path(paths[CHECKOUT_KEY])
    if not any(src.is_relative_to(root) for root in roots):
        problems.append(f"{SRC_KEY}={src} lies outside every worktree root")
    if any(_overlap(src, spaces[key]) for key in (QUEUE_KEY, INSTALL_KEY)):
        problems.append(f"{SRC_KEY}={src} overlaps the queue or the install directory")
    if checkout.parent != spaces[INSTALL_KEY]:
        problems.append(f"{CHECKOUT_KEY}={checkout} is no folder of {INSTALL_KEY}")
    return problems


def settings(env: Mapping[str, str]) -> tuple[Path, Runner]:
    """Args:
        env: the pool runner's environment, from its per-instance ``.env``.

    Returns:
        The queue directory and the runner: its name, which is its job
        stack's compose project, its worktree roots, its install directory,
        the folder of it its jobs run from and its environment.

    Raises:
        SystemExit: a value is unset or no absolute path, a path is or lies
            below a link, the queue, the install directory and the worktree
            roots overlap, the loop's checkout lies outside every root or
            overlaps the queue or the install directory, or the job folder
            is no folder of the install directory.
    """
    name = (env.get(COMPOSE_KEY) or "").strip()
    image = (env.get(IMAGE_KEY) or "").strip()
    roots = [part for part in (env.get(ROOTS_KEY) or "").split(":") if part.strip()]
    paths = {
        key: (env.get(key) or "").strip()
        for key in (QUEUE_KEY, INSTALL_KEY, CHECKOUT_KEY, SRC_KEY)
    }
    paths.update({f"{ROOTS_KEY} {root}": root for root in roots})
    problems = (
        _problems(paths, roots)
        if name and roots and image
        else [f"{COMPOSE_KEY}, {ROOTS_KEY} and {IMAGE_KEY} must be set"]
    )
    if problems:
        raise SystemExit(
            "[runner] this pool runner does not start: " + "; ".join(problems)
        )
    runner = Runner(
        name=name,
        roots=tuple(Path(root) for root in roots),
        install=Path(paths[INSTALL_KEY]),
        checkout=Path(paths[CHECKOUT_KEY]),
        image=image,
        env=dict(env),
    )
    return Path(paths[QUEUE_KEY]), runner


def main() -> int:
    root, runner = settings(os.environ)
    print(f"[runner] {runner.name} takes jobs from {root}", flush=True)
    serve(
        root,
        runner,
        subprocess.run,
        time.time,
        time.sleep,
        POLL_SECONDS,
        teardown,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
