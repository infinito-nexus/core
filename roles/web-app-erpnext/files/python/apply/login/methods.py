# nocheck: mirrored-unit-test - imports frappe at module level and runs inside `bench
# execute`; the framework is not installable outside the ERPNext image
import os

import frappe

SITE_NAME = os.environ["SITE_NAME"]
NATIVE = os.environ["LOGIN_NATIVE"] == "true"
EMAIL_LINK = os.environ["LOGIN_EMAIL"] == "true"
SECOND_FACTOR = os.environ["LOGIN_2FA"] == "true"
REGISTRATION = os.environ["LOGIN_REGISTRATION"] == "true"


def apply_system_settings():
    settings = frappe.get_doc("System Settings")
    settings.login_with_email_link = 1 if EMAIL_LINK else 0
    settings.enable_two_factor_auth = 1 if SECOND_FACTOR else 0
    settings.disable_user_pass_login = 0 if NATIVE else 1
    settings.flags.ignore_permissions = True
    settings.flags.ignore_mandatory = True
    settings.save()


def apply_website_settings():
    frappe.db.set_single_value(
        "Website Settings", "disable_signup", 0 if REGISTRATION else 1
    )


frappe.init(site=SITE_NAME, sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()
try:
    apply_system_settings()
    apply_website_settings()
    frappe.db.commit()
    frappe.clear_cache()
finally:
    frappe.destroy()
