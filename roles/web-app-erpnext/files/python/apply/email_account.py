import os

import frappe
from frappe.utils.password import remove_encrypted_password

SITE_NAME = os.environ["SITE_NAME"]
MAIL_FROM_NAME = os.environ["MAIL_FROM_NAME"]
MAIL_FROM_ADDRESS = os.environ["MAIL_FROM_ADDRESS"]
SMTP_HOST = os.environ["SMTP_HOST"]
SMTP_PORT = int(os.environ["SMTP_PORT"])
SMTP_TLS = os.environ["SMTP_TLS"] == "true"
SMTP_START_TLS = os.environ["SMTP_START_TLS"] == "true"
SMTP_AUTH_ENABLED = os.environ["SMTP_AUTH_ENABLED"] == "true"
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]

EMAIL_ACCOUNT_NAME = "ERPNext Outbound"


def upsert_outbound_account():
    if frappe.db.exists("Email Account", EMAIL_ACCOUNT_NAME):
        ea = frappe.get_doc("Email Account", EMAIL_ACCOUNT_NAME)
    else:
        ea = frappe.new_doc("Email Account")
        ea.email_account_name = EMAIL_ACCOUNT_NAME
    ea.email_id = MAIL_FROM_ADDRESS
    ea.enable_outgoing = 1
    ea.default_outgoing = 1
    ea.enable_incoming = 0
    ea.smtp_server = SMTP_HOST
    ea.smtp_port = SMTP_PORT
    ea.use_ssl_for_outgoing = int(SMTP_TLS and not SMTP_START_TLS)
    ea.use_tls = int(SMTP_TLS and SMTP_START_TLS)
    ea.login_id_is_different = int(SMTP_AUTH_ENABLED)
    ea.login_id = SMTP_USER if SMTP_AUTH_ENABLED else None
    ea.password = SMTP_PASS if SMTP_AUTH_ENABLED else None
    ea.sender_name = MAIL_FROM_NAME
    ea.flags.ignore_permissions = True
    ea.flags.ignore_validate = True
    ea.flags.no_check_in_db = True
    ea.no_smtp_authentication = int(not SMTP_AUTH_ENABLED)
    ea.flags.ignore_links = True
    ea.flags.ignore_mandatory = True
    try:
        ea.db_insert() if ea.is_new() else ea.db_update()
    except Exception:
        ea.save()
    if not SMTP_AUTH_ENABLED:
        # Exception: Frappe logs in whenever a password is stored, despite
        # no_smtp_authentication, and an MX without AUTH then fails every send.
        remove_encrypted_password("Email Account", EMAIL_ACCOUNT_NAME, "password")


frappe.init(site=SITE_NAME, sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()
try:
    upsert_outbound_account()
    frappe.db.commit()
    frappe.clear_cache()
finally:
    frappe.destroy()
