#!/usr/bin/env python3
import argparse
import subprocess
import sys


def get_disk_usage_percentages():
    """
    Returns a list of filesystem usage percentages as integers.
    Equivalent to: df --output=pcent | sed 1d | tr -d '%'
    """
    result = subprocess.run(
        ["df", "--output=pcent"], capture_output=True, text=True, check=True
    )

    lines = result.stdout.strip().split("\n")[1:]  # Skip header
    percentages = []

    for line in lines:
        value = line.strip().replace("%", "")
        if value.isdigit():
            percentages.append(int(value))

    return percentages


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
    subprocess.run(
        ["df"], check=False
    )  # Show the same df output as the original script

    errors = 0
    percentages = get_disk_usage_percentages()

    for usage in percentages:
        if usage > threshold:
            print(f"WARNING: {usage}% exceeds the limit of {threshold}%.")
            errors += 1

    sys.exit(errors)


if __name__ == "__main__":
    main()
