from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from cli.contributing.mirror.providers import GHCRProvider
from utils.docker.image.discovery import ImageRef, iter_role_images


def _validate_positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError("must be an integer") from e
    if n <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return n


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Wait until every role-declared image has been mirrored to the "
            "configured GHCR registry. Used on fork pull_request runs that depend "
            "on a pull_request_target mirror job populating the destination first."
        ),
    )
    parser.add_argument("--repo-root", default=".")
    GHCRProvider.add_args(parser)
    parser.add_argument(
        "--attempts",
        type=_validate_positive_int,
        required=True,
        help="Maximum number of polling attempts before giving up.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=_validate_positive_int,
        required=True,
        help="Seconds to wait between polling attempts.",
    )
    args = parser.parse_args()

    provider = GHCRProvider.from_args(args)
    repo_root = Path(args.repo_root).resolve()

    # Deduplicate by destination ref, keeping one ImageRef per ref to probe with.
    refs: dict[str, ImageRef] = {}
    for img in iter_role_images(repo_root):
        refs.setdefault(f"{provider.image_base(img)}:{img.version}", img)

    total = len(refs)
    if total == 0:
        print("No mirror refs found. Nothing to wait for.")
        return 0

    print(
        "Fork pull_request detected; waiting for mirrored images from "
        "pull_request_target."
    )
    print(f"Need {total} mirror refs.")

    missing: list[str] = []
    for attempt in range(1, args.attempts + 1):
        missing = [ref for ref, img in refs.items() if not provider.tag_exists(img)]
        if not missing:
            print("All mirrored images are available.")
            return 0

        print(
            f"[{attempt}/{args.attempts}] Missing {len(missing)}/{total} mirror refs. "
            f"Waiting {args.sleep_seconds}s...",
            flush=True,
        )
        print(f"Example missing: {missing[0]}", flush=True)
        if attempt < args.attempts:
            time.sleep(args.sleep_seconds)

    print("Timed out waiting for mirrored images.", file=sys.stderr)
    print("Still missing (first 20):", file=sys.stderr)
    for ref in missing[:20]:
        print(f" - {ref}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
