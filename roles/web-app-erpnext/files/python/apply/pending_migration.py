"""Name the apps whose image version differs from the site's recorded one.

Runs on the stdin of the bench Python inside the ERPNext backend container and
prints one JSON line {"pending": [<app>, ...]}.

Environment:
    SITE_NAME: Frappe site to check.
"""

import json
import os

import frappe
from frappe.utils import get_installed_apps_info

SITES_PATH = "/home/frappe/frappe-bench/sites"
UNVERSIONED = "UNVERSIONED"


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
        pending = sorted(
            app["app_name"]
            for app in get_installed_apps_info()
            if (app["version"] or UNVERSIONED) != recorded.get(app["app_name"])
        )
    finally:
        frappe.destroy()
    print(json.dumps({"pending": pending}))


if __name__ == "__main__":
    main()
