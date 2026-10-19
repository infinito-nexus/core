#!/usr/bin/env python3
import os
import sys

EXPORT_DIR = "/run/systemd/units"
SETTINGS = ("log-rate-limit-interval", "log-rate-limit-burst")


def read(unit, setting):
    try:
        return os.readlink(os.path.join(EXPORT_DIR, f"{setting}:{unit}"))
    except OSError:
        return "-"


def main():
    """Print the journald log rate limit systemd handed to a running unit.

    systemd exports a unit's limit when the unit starts, as symlinks in /run/systemd/units.

    Args:
        argv[1]: the unit name, e.g. docker.service.

    Prints:
        "<interval usec> <burst>", each "-" when the unit started without its own limit.
    """
    unit = sys.argv[1]
    print(" ".join(read(unit, setting) for setting in SETTINGS))


if __name__ == "__main__":
    main()
