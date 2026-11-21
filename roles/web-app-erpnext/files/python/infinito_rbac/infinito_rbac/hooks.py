app_name = "infinito_rbac"  # nocheck: forms-script
app_title = "Infinito RBAC"
app_publisher = "Kevin Veen-Birkenbach"
app_description = (
    "Refuses a Keycloak or LDAP sign-in onto an account the directory does not own "
    "and applies the role groups of the sign-in to its account"
)
app_license = "Infinito.Nexus Community License (Non-Commercial)"

override_whitelisted_methods = {
    "frappe.integrations.oauth2_logins.login_via_keycloak": "infinito_rbac.login.login_via_keycloak",
    "frappe.integrations.oauth2_logins.custom": "infinito_rbac.login.custom",
    "frappe.client.set_default": "infinito_rbac.login.refuse_default_write",
}

override_doctype_class = {
    "LDAP Settings": "infinito_rbac.login.DirectoryLDAPSettings",
}

doc_events = {
    "User": {
        "after_rename": "infinito_rbac.roles.carry_records",
        "on_trash": "infinito_rbac.roles.drop_records",
    },
}
