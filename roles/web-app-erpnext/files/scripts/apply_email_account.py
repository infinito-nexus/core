import os

import frappe

SITE_NAME = os.environ["SITE_NAME"]
MAIL_FROM_NAME = os.environ["MAIL_FROM_NAME"]
MAIL_FROM_ADDRESS = os.environ["MAIL_FROM_ADDRESS"]
SMTP_HOST = os.environ["SMTP_HOST"]
SMTP_PORT = int(os.environ["SMTP_PORT"])
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
    ea.use_tls = 1
    ea.login_id_is_different = 1
    ea.login_id = SMTP_USER
    ea.password = SMTP_PASS
    ea.sender_name = MAIL_FROM_NAME
    ea.flags.ignore_permissions = True
    ea.flags.ignore_validate = True
    ea.flags.no_check_in_db = True
    ea.no_smtp_authentication = 0
    ea.flags.ignore_links = True
    ea.flags.ignore_mandatory = True
    # Frappe's Email Account validate() opens a live SMTP socket and stalls the deploy
    # when the SMTP host is unreachable; db_insert/db_update bypasses it.
    try:
        ea.db_insert() if ea.is_new() else ea.db_update()
    except Exception:
        ea.save()


frappe.init(site=SITE_NAME, sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()
try:
    upsert_outbound_account()
    frappe.db.commit()
    frappe.clear_cache()
finally:
    frappe.destroy()
