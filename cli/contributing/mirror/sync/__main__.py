from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from cli.contributing.mirror.providers import GHCRProvider
from utils.docker.image.discovery import iter_role_images


def _validate_positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError("must be an integer") from e
    if n <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return n


def _throttle_before_next_copy(
    *, images_per_hour: int | None, last_start_ts: float | None
) -> float:
    """
    If images_per_hour is set, ensure at least (3600 / images_per_hour) seconds
    have elapsed since last_start_ts before returning.

    Returns the (possibly updated) start timestamp for the next copy.
    """
    if not images_per_hour:
        return time.monotonic()

    min_interval = 3600.0 / float(images_per_hour)
    now = time.monotonic()

    if last_start_ts is not None:
        elapsed = now - last_start_ts
        remaining = min_interval - elapsed
        if remaining > 0:
            print(
                f"[mirror] throttling: sleeping {remaining:.1f}s "
                f"(limit={images_per_hour} images/hour)",
                flush=True,
            )
            time.sleep(remaining)

    return time.monotonic()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Mirror every role-declared image to the configured GHCR registry, "
            "optionally throttled and optionally skipping already-mirrored "
            "tags."
        ),
    )
    parser.add_argument("--repo-root", default=".")
    GHCRProvider.add_args(parser)
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Mirror only images that do not exist in the destination registry.",
    )
    parser.add_argument(
        "--images-per-hour",
        type=_validate_positive_int,
        default=None,
        help="Optional throttle: max images to mirror per hour (best-effort).",
    )
    args = parser.parse_args()

    provider = GHCRProvider.from_args(args)
    repo_root = Path(args.repo_root).resolve()

    failures: list[str] = []
    total = 0

    last_start_ts: float | None = None

    for img in iter_role_images(repo_root):
        # Optional throttling (only when --images-per-hour is set)
        last_start_ts = _throttle_before_next_copy(
            images_per_hour=args.images_per_hour,
            last_start_ts=last_start_ts,
        )

        total += 1
        src = f"docker://{img.source}"
        dest = f"docker://{provider.image_base(img)}:{img.version}"
        label = f"{img.role}:{img.service} ({img.name}:{img.version})"

        try:
            if args.only_missing and provider.tag_exists(img):
                print(
                    f"[mirror] {label}: destination exists, skipping ({dest})",
                    flush=True,
                )
                continue

            print(f"[mirror] {label}: {src} -> {dest}", flush=True)
            provider.mirror(img)

        except subprocess.CalledProcessError as e:
            # keep going, but remember the failure
            msg = (
                f"{label}: FAILED (exit={e.returncode})\n"
                f"  cmd: {' '.join(map(str, e.cmd))}"
            )
            failures.append(msg)
            print(
                f"[mirror] {label}: FAILED, continuing...",
                file=sys.stderr,
                flush=True,
            )
        except Exception as e:
            msg = f"{label}: FAILED (unexpected error: {e!r})"
            failures.append(msg)
            print(
                f"[mirror] {label}: FAILED (unexpected), continuing...",
                file=sys.stderr,
                flush=True,
            )

    if failures:
        print("\n[mirror] SUMMARY: some images failed:", file=sys.stderr)
        for f in failures:
            print(f"- {f}", file=sys.stderr)
        print(f"\n[mirror] Result: {len(failures)}/{total} failed.", file=sys.stderr)
        return 1

    print(f"\n[mirror] Result: {total}/{total} succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
