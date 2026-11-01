#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor

from utils.docker.image.discovery import ImageRef, iter_role_images
from utils.docker.image.runtime import (
    build_instructions,
    load_php_floors,
    php_finding,
    php_runtime,
)

from . import PROJECT_ROOT

WORKERS = 4
OS_NAME = "linux"
ARCHITECTURE = "amd64"


def _instructions(ref: ImageRef) -> list[str] | None:
    return build_instructions(
        f"{ref.registry}/{ref.name}",
        ref.version,
        os_name=OS_NAME,
        architecture=ARCHITECTURE,
    )


def report(refs: list[ImageRef], probed: list, floors: dict[str, str]) -> int:
    """Print one line per image that ships PHP and return the exit code.

    Args:
        refs: the pinned role images.
        probed: :func:`build_instructions` result per ref, in the same order.
        floors: see :func:`load_php_floors`.

    Returns:
        ``1`` when an image is below its floor or the registry gave no answer
        for one, ``0`` otherwise.
    """
    findings = 0
    unknown = []
    with_php = 0
    for ref, instructions in zip(refs, probed, strict=True):
        if instructions is None:
            unknown.append(f"{ref.role}:{ref.service} ({ref.source})")
            continue
        runtime = php_runtime(instructions)
        if runtime is None:
            continue
        with_php += 1
        if runtime.version:
            php = runtime.version
        elif runtime.lines:
            php = f"line {', '.join(runtime.lines)}"
        else:
            php = f"package {', '.join(runtime.packages)}"
        finding = php_finding(runtime, floors)
        if finding:
            findings += 1
            print(f"❌ {ref.role}:{ref.service} {ref.source} PHP {php}: {finding}")
        elif runtime.version:
            print(f"✅ {ref.role}:{ref.service} {ref.source} PHP {php}")
        else:
            print(
                f"❔ {ref.role}:{ref.service} {ref.source} PHP {php}: "
                "patch level not in the registry metadata"
            )
    for entry in unknown:
        print(f"⚠️ {entry}: the registry gave no answer")
    print(
        f"\n{len(refs)} image(s): {with_php} ship PHP, {findings} below the "
        f"floor, {len(unknown)} unanswered"
    )
    return 1 if findings or unknown else 0


def main(argv=None) -> int:
    argparse.ArgumentParser(
        description=(
            "List the PHP runtime of every pinned role image from registry "
            "metadata, without pulling, and fail on one below its security floor."
        )
    ).parse_args(argv)
    floors = load_php_floors()
    refs = sorted(iter_role_images(PROJECT_ROOT), key=lambda r: (r.role, r.service))
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        probed = list(pool.map(_instructions, refs))
    return report(refs, probed, floors)


if __name__ == "__main__":
    raise SystemExit(main())
