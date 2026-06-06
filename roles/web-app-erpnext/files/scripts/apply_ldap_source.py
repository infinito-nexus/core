import os

import frappe

SITE_NAME = os.environ["SITE_NAME"]
LDAP_HOST = os.environ["LDAP_HOST"]
LDAP_PORT = int(os.environ["LDAP_PORT"])
LDAP_BASE_DN = os.environ["LDAP_BASE_DN"]
LDAP_BIND_DN = os.environ["LDAP_BIND_DN"]
LDAP_BIND_PW = os.environ["LDAP_BIND_PW"]
LDAP_UID_ATTR = os.environ["LDAP_UID_ATTR"]


def upsert_ldap_settings():
    ls = frappe.get_doc("LDAP Settings")
    ls.enabled = 1
    ls.ldap_server_url = f"ldap://{LDAP_HOST}:{LDAP_PORT}"
    ls.base_dn = LDAP_BIND_DN
    ls.password = LDAP_BIND_PW
    ls.ldap_search_string = f"({LDAP_UID_ATTR}={{0}})"
    ls.ldap_search_path_user = LDAP_BASE_DN
    ls.ldap_search_path_group = LDAP_BASE_DN
    ls.ldap_first_name_field = "givenName"
    ls.ldap_email_field = "mail"
    ls.ldap_username_field = LDAP_UID_ATTR
    ls.ldap_directory_server = "OpenLDAP"
    ls.require_trusted_certificate = "No"
    ls.default_user_type = "System User"
    ls.flags.ignore_permissions = True
    ls.flags.ignore_mandatory = True
    ls.save()


frappe.init(site=SITE_NAME, sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()
try:
    upsert_ldap_settings()
    frappe.db.commit()
    frappe.clear_cache()
finally:
    frappe.destroy()
