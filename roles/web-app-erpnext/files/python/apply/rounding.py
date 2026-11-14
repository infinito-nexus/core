import json
import os

import frappe

SITES_PATH = "/home/frappe/frappe-bench/sites"
SYSTEM_SETTINGS = "System Settings"
ACCOUNTS_SETTINGS = "Accounts Settings"
MODES = ("read", "converge")

SITE_NAME = os.environ["SITE_NAME"]
MODE = os.environ["ROUNDING_MODE"]
FORMS = {
    "system_rounding": (SYSTEM_SETTINGS, json.loads(os.environ["SYSTEM_ROUNDING"])),
    "accounts_rounding": (
        ACCOUNTS_SETTINGS,
        json.loads(os.environ["ACCOUNTS_ROUNDING"]),
    ),
}

if MODE not in MODES:
    raise ValueError(f"ROUNDING_MODE must be one of {list(MODES)}")


def stored_settings():
    return {
        form: {field: frappe.db.get_single_value(doctype, field) for field in fields}
        for form, (doctype, fields) in FORMS.items()
    }


def drifted(doctype, fields):
    """Args:
        doctype: single DocType that stores the fields.
        fields: each field mapped to the value the deployment pins.

    Returns:
        The fields whose stored value differs from the pinned one.
    """
    return {
        field: value
        for field, value in fields.items()
        if frappe.db.get_single_value(doctype, field) != value
    }


def write_system_settings(fields):
    settings = frappe.get_doc(SYSTEM_SETTINGS)
    settings.update(fields)
    settings.flags.ignore_permissions = True
    settings.flags.ignore_mandatory = True
    settings.save()


def write_accounts_settings(fields):
    for field, value in fields.items():
        frappe.db.set_single_value(ACCOUNTS_SETTINGS, field, value)


WRITERS = {
    SYSTEM_SETTINGS: write_system_settings,
    ACCOUNTS_SETTINGS: write_accounts_settings,
}


def converge():
    """Returns:
    ``<DocType>::<field>`` of every field the run wrote.
    """
    changed = []
    for doctype, fields in FORMS.values():
        stale = drifted(doctype, fields)
        if stale:
            WRITERS[doctype](stale)
            changed.extend(f"{doctype}::{field}" for field in stale)
    if changed:
        frappe.db.commit()
        frappe.clear_cache()
    return changed


frappe.init(site=SITE_NAME, sites_path=SITES_PATH)
frappe.connect()
try:
    if MODE == "read":
        print(json.dumps(stored_settings(), sort_keys=True))
    else:
        print(json.dumps({"changed": converge()}))
finally:
    frappe.destroy()
