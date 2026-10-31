import os

import frappe

SITE_NAME = os.environ["SITE_NAME"]
API_BOT_LOGIN = os.environ["API_BOT_LOGIN"]
API_BOT_EMAIL = os.environ["API_BOT_EMAIL"]
API_BOT_FIRSTNAME = os.environ["API_BOT_FIRSTNAME"]
API_BOT_LASTNAME = os.environ["API_BOT_LASTNAME"]
API_BOT_PASSWORD = os.environ["API_BOT_PASSWORD"]
API_KEY_SECRET = os.environ["API_KEY_SECRET"]
COUNTRY = os.environ["COUNTRY"]
CURRENCY = os.environ["CURRENCY"]
SERVER_SCRIPTS_ENABLED = {"true": True, "false": False}[
    os.environ["SERVER_SCRIPTS_ENABLED"].lower()
]
SCRIPT_MANAGER = "Script Manager"

API_KEY, API_SECRET = (
    API_KEY_SECRET[: len(API_KEY_SECRET) // 2],
    API_KEY_SECRET[len(API_KEY_SECRET) // 2 :],
)


def upsert_api_bot():
    if frappe.db.exists("User", API_BOT_EMAIL):
        user = frappe.get_doc("User", API_BOT_EMAIL)
    else:
        user = frappe.new_doc("User")
        user.email = API_BOT_EMAIL
    user.username = API_BOT_LOGIN
    user.first_name = API_BOT_FIRSTNAME
    user.last_name = API_BOT_LASTNAME
    user.send_welcome_email = 0
    user.enabled = 1
    user.user_type = "System User"
    user.new_password = API_BOT_PASSWORD
    user.api_key = API_KEY
    user.api_secret = API_SECRET
    user.flags.ignore_permissions = True
    user.flags.ignore_password_policy = True
    user.save()
    align_roles(user)


def align_roles(user):
    granted = ["System Manager", *([SCRIPT_MANAGER] if SERVER_SCRIPTS_ENABLED else [])]
    revoked = [] if SERVER_SCRIPTS_ENABLED else [SCRIPT_MANAGER]
    stale = [row for row in user.roles if row.role in revoked]
    for row in stale:
        user.roles.remove(row)
    held = {row.role for row in user.roles}
    missing = [role for role in granted if role not in held]
    for role in missing:
        user.append("roles", {"role": role})
    if stale or missing:
        user.save()


def bypass_setup_wizard():
    frappe.db.set_default("setup_complete", "1")
    if frappe.db.exists("DocType", "System Settings"):
        ss = frappe.get_doc("System Settings")
        ss.setup_complete = 1
        if not ss.language:
            ss.language = "en"
        if not ss.time_zone:
            ss.time_zone = "UTC"
        if not ss.country:
            ss.country = COUNTRY
        if not ss.currency:
            ss.currency = CURRENCY
        ss.flags.ignore_permissions = True
        ss.flags.ignore_mandatory = True
        ss.save()

    if frappe.db.table_exists("Installed Application"):
        for app in frappe.get_all("Installed Application", pluck="name"):
            frappe.db.set_value("Installed Application", app, "is_setup_complete", 1)
    if frappe.db.get_default("desktop:home_page") == "setup-wizard":
        frappe.db.set_default("desktop:home_page", "")


frappe.init(site=SITE_NAME, sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()
try:
    upsert_api_bot()
    bypass_setup_wizard()
    frappe.db.commit()
    frappe.clear_cache()
finally:
    frappe.destroy()
