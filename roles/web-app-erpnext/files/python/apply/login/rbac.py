"""Install the login role mapping app on the site and write its settings.

Environment:
    SITE_NAME: the Frappe site.
    LOGIN_RBAC_APP: the Frappe app that maps the role groups at sign-in.
    LOGIN_RBAC_SETTINGS_JSON: JSON object the app reads from the site config key named after it.

Output:
    After what ``install_app`` prints, one ``CHANGED <what> <app>`` line per
    change, else ``UNCHANGED``.
"""

import json
import os

import frappe
from frappe.installer import install_app, update_site_config

SITES_PATH = "/home/frappe/frappe-bench/sites"
SETTINGS = (
    "groups_claim",
    "username_claim",
    "given_name_claim",
    "family_name_claim",
    "role_grants",
    "protected_users",
)


def parse_settings(raw):
    """Return the settings object, refusing one that lacks or adds a key.

    Args:
        raw: the JSON text of the settings.
    """
    settings = json.loads(raw)
    if not isinstance(settings, dict) or sorted(settings) != sorted(SETTINGS):
        raise ValueError(
            f"LOGIN_RBAC_SETTINGS_JSON must be an object with exactly {list(SETTINGS)}"
        )
    return settings


def converge(app, settings):
    """Install the app when the site lacks it, write its settings, return one line per change.

    Args:
        app: the Frappe app.
        settings: the settings the app reads from the site config.
    """
    lines = []
    if app not in frappe.get_installed_apps():
        install_app(app)
        lines.append(f"CHANGED installed {app}")
    if frappe.conf.get(app) != settings:
        update_site_config(app, settings)
        lines.append(f"CHANGED settings {app}")
    return lines


def main(environ):
    """Converge the site and print the result.

    Args:
        environ: the process environment.
    """
    site = environ["SITE_NAME"]
    app = environ["LOGIN_RBAC_APP"]
    settings = parse_settings(environ["LOGIN_RBAC_SETTINGS_JSON"])

    frappe.init(site=site, sites_path=SITES_PATH)
    frappe.connect()
    try:
        lines = converge(app, settings)
        frappe.db.commit()
    finally:
        frappe.destroy()
    print("\n".join(lines) if lines else "UNCHANGED")


if __name__ == "__main__":
    main(os.environ)
