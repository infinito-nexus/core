import json
import os

import frappe

SITE_NAME = os.environ["SITE_NAME"]
PROVIDER_NAME = os.environ["PROVIDER_NAME"]
BUTTON_TEXT = os.environ["BUTTON_TEXT"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
ISSUER_URL = os.environ["ISSUER_URL"]
GROUP_ROLE_MAP = json.loads(os.environ["GROUP_ROLE_MAP_JSON"])


def upsert_social_login_key():
    # social_login_provider is set_only_once; a non-Keycloak existing record blocks the update.
    if frappe.db.exists("Social Login Key", PROVIDER_NAME):
        existing = frappe.get_doc("Social Login Key", PROVIDER_NAME)
        if (existing.social_login_provider or "Custom") != "Keycloak":
            frappe.delete_doc(
                "Social Login Key", PROVIDER_NAME, force=True, ignore_permissions=True
            )
            frappe.db.commit()
    if not frappe.db.exists("Social Login Key", PROVIDER_NAME):
        slk = frappe.new_doc("Social Login Key")
        slk.provider_name = PROVIDER_NAME
        slk.social_login_provider = "Keycloak"
    else:
        slk = frappe.get_doc("Social Login Key", PROVIDER_NAME)
    slk.enable_social_login = 1
    slk.sign_ups = "Allow"
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
    slk.user_id_property = "preferred_username"
    slk.custom_button_text = BUTTON_TEXT
    slk.flags.ignore_permissions = True
    slk.save()


def store_group_role_map():
    frappe.db.set_default(
        "erpnext_oidc_group_role_map",
        json.dumps(GROUP_ROLE_MAP),
    )


frappe.init(site=SITE_NAME, sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()
try:
    upsert_social_login_key()
    store_group_role_map()
    frappe.db.commit()
    frappe.clear_cache()
finally:
    frappe.destroy()
