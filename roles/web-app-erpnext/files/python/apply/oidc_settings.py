# nocheck: mirrored-unit-test - imports frappe and frappe.utils.password at module level
# and runs inside `bench execute`; the framework is not installable outside the ERPNext
# image
import json
import os

import frappe
from frappe.defaults import clear_default
from frappe.utils.password import get_decrypted_password

SITE_NAME = os.environ["SITE_NAME"]
PROVIDER_NAME = os.environ["PROVIDER_NAME"]
BUTTON_TEXT = os.environ["BUTTON_TEXT"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
ISSUER_URL = os.environ["ISSUER_URL"]
USER_ID_PROPERTY = os.environ["USER_ID_PROPERTY"]
SOCIAL_LOGIN_ENABLED = os.environ["SOCIAL_LOGIN_ENABLED"] == "true"

TRACKED_FIELDS = (
    "enable_social_login",
    "social_login_provider",
    "client_id",
    "base_url",
    "custom_base_url",
    "authorize_url",
    "access_token_url",
    "api_endpoint",
    "redirect_url",
    "auth_url_data",
    "user_id_property",
    "sign_ups",
    "icon",
)


def _tracked(doc):
    return {field: doc.get(field) for field in TRACKED_FIELDS}


def upsert_social_login_key():
    existed = bool(frappe.db.exists("Social Login Key", PROVIDER_NAME))
    if existed:
        existing = frappe.get_doc("Social Login Key", PROVIDER_NAME)
        if (existing.social_login_provider or "Custom") != "Keycloak":
            frappe.delete_doc(
                "Social Login Key", PROVIDER_NAME, force=True, ignore_permissions=True
            )
            frappe.db.commit()
            existed = False
    if not existed:
        slk = frappe.new_doc("Social Login Key")
        slk.provider_name = PROVIDER_NAME
        slk.social_login_provider = "Keycloak"
        before_fields = None
        before_secret = None
    else:
        slk = frappe.get_doc("Social Login Key", PROVIDER_NAME)
        before_fields = _tracked(slk)
        before_secret = get_decrypted_password(
            "Social Login Key", PROVIDER_NAME, "client_secret", raise_exception=False
        )
    slk.enable_social_login = 1 if SOCIAL_LOGIN_ENABLED else 0
    slk.sign_ups = "Deny"
    slk.icon = "fa fa-key"
    slk.client_id = CLIENT_ID
    slk.client_secret = CLIENT_SECRET
    slk.base_url = ISSUER_URL
    slk.custom_base_url = 1
    slk.authorize_url = "/protocol/openid-connect/auth"
    slk.access_token_url = "/protocol/openid-connect/token"  # noqa: S105
    slk.api_endpoint = "/protocol/openid-connect/userinfo"
    slk.redirect_url = (
        "/api/method/frappe.integrations.oauth2_logins.login_via_keycloak/keycloak"
    )
    slk.auth_url_data = json.dumps({"response_type": "code", "scope": "openid"})
    slk.user_id_property = USER_ID_PROPERTY
    slk.custom_button_text = BUTTON_TEXT
    slk.flags.ignore_permissions = True
    after_fields = _tracked(slk)
    slk.save()
    return (
        before_fields is None
        or before_fields != after_fields
        or before_secret != CLIENT_SECRET
    )


frappe.init(site=SITE_NAME, sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()
changed = False
try:
    changed = upsert_social_login_key()
    clear_default(key="erpnext_oidc_group_role_map")
    frappe.db.commit()
    frappe.clear_cache()
finally:
    frappe.destroy()

print("OIDC_SLK_CHANGED" if changed else "OIDC_SLK_UNCHANGED")
