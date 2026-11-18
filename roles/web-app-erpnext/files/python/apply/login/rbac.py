"""Environment:
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
    "group_roles",
    "protected_users",
    "protected_owners",
    "directory_provider",
    "uuid_attribute",
    "directory_ids",
)


def parse_settings(raw):
    """Args:
        raw: the JSON text of the settings.

    Returns:
        The settings object.

    Raises:
        ValueError: the object lacks or adds a key of ``SETTINGS``.
    """
    settings = json.loads(raw)
    if not isinstance(settings, dict) or sorted(settings) != sorted(SETTINGS):
        raise ValueError(
            f"LOGIN_RBAC_SETTINGS_JSON must be an object with exactly {list(SETTINGS)}"
        )
    return settings


def converge(app, settings):
    """Args:
        app: the Frappe app.
        settings: the settings the app reads from the site config.

    Returns:
        One line per change: the app installed, its settings written, the
        ``LDAP Settings`` disabled while ``directory_ids`` is false.
    """
    lines = []
    if app not in frappe.get_installed_apps():
        install_app(app)
        lines.append(f"CHANGED installed {app}")
    if frappe.conf.get(app) != settings:
        update_site_config(app, settings)
        lines.append(f"CHANGED settings {app}")
    if not settings["directory_ids"] and frappe.db.get_single_value(
        "LDAP Settings", "enabled"
    ):
        frappe.db.set_single_value("LDAP Settings", "enabled", 0)
        lines.append("CHANGED disabled LDAP Settings")
    return lines


def main(environ):
    """Args:
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
        frappe.clear_cache()
    finally:
        frappe.destroy()
    print("\n".join(lines) if lines else "UNCHANGED")


if __name__ == "__main__":
    main(os.environ)
