# nocheck: mirrored-unit-test - imports frappe at module level and runs inside `bench
# execute`; the framework is not installable outside the ERPNext image
import json
import os

import frappe

SITE_NAME = os.environ["SITE_NAME"]
LDAP_HOST = os.environ["LDAP_HOST"]
LDAP_PORT = int(os.environ["LDAP_PORT"])
LDAP_BASE_DN = os.environ["LDAP_BASE_DN"]
LDAP_ROLES_DN = os.environ["LDAP_ROLES_DN"]
LDAP_BIND_DN = os.environ["LDAP_BIND_DN"]
LDAP_BIND_PW = os.environ["LDAP_BIND_PW"]
LDAP_UID_ATTR = os.environ["LDAP_UID_ATTR"]
LDAP_MAIL_ATTR = os.environ["LDAP_MAIL_ATTR"]
LDAP_FIRSTNAME_ATTR = os.environ["LDAP_FIRSTNAME_ATTR"]
LDAP_SURNAME_ATTR = os.environ["LDAP_SURNAME_ATTR"]
LDAP_PHONE_ATTR = os.environ["LDAP_PHONE_ATTR"]
LDAP_MOBILE_ATTR = os.environ["LDAP_MOBILE_ATTR"]
LDAP_MEMBER_OF_ATTR = os.environ["LDAP_MEMBER_OF_ATTR"]
LDAP_GROUP_OBJECTCLASS = os.environ["LDAP_GROUP_OBJECTCLASS"]
LDAP_GROUP_MEMBER_ATTR = os.environ["LDAP_GROUP_MEMBER_ATTR"]
LDAP_GROUP_PREFIX = os.environ["LDAP_GROUP_PREFIX"]
ROLE_GRANTS = json.loads(os.environ["ROLE_GRANTS_JSON"])
LDAP_LOGIN_ENABLED = os.environ["LDAP_LOGIN_ENABLED"] == "true"


def role_group_cn(role):
    return f"{LDAP_GROUP_PREFIX}{role}"


def search_string():
    members = "".join(
        f"({LDAP_MEMBER_OF_ATTR}=cn={role_group_cn(role)},{LDAP_ROLES_DN})"
        for role in sorted(ROLE_GRANTS)
    )
    return f"(&({LDAP_UID_ATTR}={{0}})(|{members}))"


def upsert_ldap_settings():
    ls = frappe.get_doc("LDAP Settings")
    ls.enabled = 1 if LDAP_LOGIN_ENABLED else 0
    ls.ldap_server_url = f"ldap://{LDAP_HOST}:{LDAP_PORT}"
    ls.base_dn = LDAP_BIND_DN
    ls.password = LDAP_BIND_PW
    ls.ldap_search_string = search_string()
    ls.ldap_search_path_user = LDAP_BASE_DN
    ls.ldap_search_path_group = LDAP_ROLES_DN
    ls.ldap_email_field = LDAP_MAIL_ATTR
    ls.ldap_username_field = LDAP_UID_ATTR
    ls.ldap_first_name_field = LDAP_FIRSTNAME_ATTR
    ls.ldap_last_name_field = LDAP_SURNAME_ATTR
    ls.ldap_phone_field = LDAP_PHONE_ATTR
    ls.ldap_mobile_field = LDAP_MOBILE_ATTR
    ls.ldap_directory_server = "Custom"
    ls.ldap_group_objectclass = LDAP_GROUP_OBJECTCLASS
    ls.ldap_group_member_attribute = LDAP_GROUP_MEMBER_ATTR
    ls.ldap_custom_group_search = f"{LDAP_UID_ATTR}={{0}},{LDAP_BASE_DN}"
    ls.set(
        "ldap_groups",
        [
            {"ldap_group": role_group_cn(role), "erpnext_role": erpnext_role}
            for role, erpnext_roles in sorted(ROLE_GRANTS.items())
            for erpnext_role in erpnext_roles
        ],
    )
    ls.require_trusted_certificate = "No"
    ls.default_user_type = "Website User"
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
