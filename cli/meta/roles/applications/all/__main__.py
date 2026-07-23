#!/usr/bin/env python3
# cli/meta/roles/applications/all.py

import argparse
import sys

try:
    from plugins.filter.get.all.application_ids import get_all_application_ids
except ImportError:
    sys.stderr.write(
        "Filter plugin `get_all_application_ids` not found. Ensure `plugins/filter/get/all/application_ids.py` is in your PYTHONPATH.\n"
    )
    sys.exit(1)


def find_application_ids():
    """
    Legacy function retained for reference.
    Delegates to the `get_all_application_ids` filter plugin.
    """
    return get_all_application_ids()


def main():
    parser = argparse.ArgumentParser(
        description="Output a list of all application_id values defined in roles/*/vars/main.yml"  # nocheck: role-file-spot
    )
    parser.parse_args()

    try:
        ids = find_application_ids()
    except Exception as e:
        sys.stderr.write(f"Error retrieving application IDs: {e}\n")
        sys.exit(1)

    for app_id in ids:
        print(app_id)


if __name__ == "__main__":
    main()
