"""Name the apps whose image version is newer than the site's recorded one.

Runs on the stdin of the bench Python inside the ERPNext backend container and
prints one JSON line {"pending": [<app>, ...]}. An app whose image version is
older than the recorded one exits non-zero instead: migrating a newer schema
with older code is a downgrade, which only a backup restore undoes.

Environment:
    SITE_NAME: Frappe site to check.
"""

import json
import os
import re
import sys

import frappe
from frappe.utils import get_installed_apps_info

SITES_PATH = "/home/frappe/frappe-bench/sites"
UNVERSIONED = "UNVERSIONED"
RELEASE = re.compile(r"\d+(?:\.\d+)*")


def _release(version):
    match = RELEASE.match(version or "")
    return tuple(int(part) for part in match.group().split(".")) if match else None


def _compare(recorded, shipped):
    pending, older = [], []
    for app in shipped:
        name = app["app_name"]
        image = app["version"] or UNVERSIONED
        site = recorded.get(name)
        if image == site:
            continue
        image_release, site_release = _release(image), _release(site)
        if image_release and site_release and image_release < site_release:
            older.append(f"{name} {image} < {site}")
        else:
            pending.append(name)
    return sorted(pending), sorted(older)


def main():
    frappe.init(site=os.environ["SITE_NAME"], sites_path=SITES_PATH)
    frappe.connect()
    try:
        recorded = {
            row.app_name: row.app_version
            for row in frappe.get_single(
                "Installed Applications"
            ).installed_applications
        }
        shipped = get_installed_apps_info()
    finally:
        frappe.destroy()
    pending, older = _compare(recorded, shipped)
    if older:
        sys.exit(
            f"The image is older than the site: {', '.join(older)}. "
            "Restore the site backup taken before the newer version, "
            "or pin the recorded version again."
        )
    print(json.dumps({"pending": pending}))


if __name__ == "__main__":
    main()
