# nocheck: mirrored-unit-test - imports frappe at module level and runs inside `bench
# execute`; the framework is not installable outside the ERPNext image
import json
import os

import frappe

SITE_NAME = os.environ["SITE_NAME"]
MODE = os.environ["LOGIN_MODE"]
SYSTEM_SETTINGS = json.loads(os.environ["SYSTEM_SETTINGS"])
WEBSITE_SETTINGS = json.loads(os.environ["WEBSITE_SETTINGS"])
SECOND_FACTOR = os.environ["LOGIN_2FA"] == "true"
SECOND_FACTOR_ENFORCED = os.environ["LOGIN_2FA_ENFORCED"] == "true"
EVERY_USER_ROLE = "All"
MODES = ("read", "converge")
FORMS = {
    "system_settings": ("System Settings", SYSTEM_SETTINGS),
    "website_settings": ("Website Settings", WEBSITE_SETTINGS),
}

if MODE not in MODES:
    raise ValueError(f"LOGIN_MODE must be one of {list(MODES)}")


def stored_settings():
    return {
        form: {field: frappe.db.get_single_value(doctype, field) for field in fields}
        for form, (doctype, fields) in FORMS.items()
    }


def apply_system_settings():
    settings = frappe.get_doc("System Settings")
    settings.update(SYSTEM_SETTINGS)
    settings.flags.ignore_permissions = True
    settings.flags.ignore_mandatory = True
    settings.save()


def apply_website_settings():
    for field, value in WEBSITE_SETTINGS.items():
        frappe.db.set_single_value("Website Settings", field, value)


def apply_role_settings():
    frappe.db.set_value(
        "Role", EVERY_USER_ROLE, "two_factor_auth", 1 if SECOND_FACTOR_ENFORCED else 0
    )


def release_role_settings():
    if frappe.db.get_value("Role", EVERY_USER_ROLE, "two_factor_auth"):
        frappe.db.set_value("Role", EVERY_USER_ROLE, "two_factor_auth", 0)


frappe.init(site=SITE_NAME, sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()
try:
    if MODE == "read":
        print(json.dumps(stored_settings(), sort_keys=True))
    else:
        apply_system_settings()
        apply_website_settings()
        if SECOND_FACTOR:
            apply_role_settings()
        else:
            release_role_settings()
        frappe.db.commit()
        frappe.clear_cache()
finally:
    frappe.destroy()
