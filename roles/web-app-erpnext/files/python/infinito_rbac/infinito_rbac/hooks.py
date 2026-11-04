app_name = "infinito_rbac"
app_title = "Infinito RBAC"
app_publisher = "Kevin Veen-Birkenbach"
app_description = (
    "Refuses a Keycloak sign-in onto an account the directory does not own "
    "and applies the role groups of the sign-in to its account"
)
app_license = "Infinito.Nexus Community License (Non-Commercial)"

override_whitelisted_methods = {
    "frappe.integrations.oauth2_logins.login_via_keycloak": "infinito_rbac.login.login_via_keycloak",
    "frappe.integrations.oauth2_logins.custom": "infinito_rbac.login.custom",
}
