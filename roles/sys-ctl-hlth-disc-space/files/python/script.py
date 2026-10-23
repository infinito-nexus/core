#!/usr/bin/env python3
"""Report every filesystem a cleanup could still reclaim space on.

MIN_SIZE_KIB keeps the container runtimes out: the NVIDIA toolkit mounts a
4 KiB tmpfs per CDI hook holding one file, which reads 100% on every GPU host
and which no cleanup can ever change.
"""

import argparse
import subprocess
import sys

MIN_SIZE_KIB = 64 * 1024


def get_filesystem_usage():
    """Return one (usage percent, size in KiB, mountpoint) per filesystem.

    Returns:
        Every filesystem df lists, unfiltered; the caller decides which of
        them a cleanup could act on.
    """
    result = subprocess.run(
        ["df", "--output=pcent,size,target"],
        capture_output=True,
        text=True,
        check=True,
    )

    entries = []
    for line in result.stdout.strip().split("\n")[1:]:
        parts = line.split(maxsplit=2)
        if len(parts) != 3:
            continue
        percent, size, target = parts
        percent = percent.replace("%", "")
        if not percent.isdigit() or not size.isdigit():
            continue
        entries.append((int(percent), int(size), target))

    return entries


def main():
    parser = argparse.ArgumentParser(
        description="Check disk usage and report if any filesystem exceeds the given threshold."
    )

    parser.add_argument(
        "minimum_percent_cleanup_disk_space",
        type=int,
        help="Minimum free disk space percentage threshold that triggers a warning.",
    )

    args = parser.parse_args()
    threshold = args.minimum_percent_cleanup_disk_space

    print("Checking disk space usage...")
    subprocess.run(["df"], check=False)

    errors = 0
    for usage, size, target in get_filesystem_usage():
        if usage <= threshold:
            continue
        if size < MIN_SIZE_KIB:
            print(
                f"INFO: {target} at {usage}% holds {size} KiB in total, "
                "too small for a cleanup to reclaim anything."
            )
            continue
        print(f"WARNING: {target} at {usage}% exceeds the limit of {threshold}%.")
        errors += 1

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
