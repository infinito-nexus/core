# nocheck: mirrored-unit-test - an Odoo addon manifest, a bare dict literal the registry reads; there is no behaviour to exercise
{  # noqa: B018  Odoo addon manifests are bare dict expressions at module level by design
    "name": "Infinito.Nexus RBAC & Profile Mapping",
    "version": "1.0.0",
    "category": "Authentication",
    "summary": "Map identity provider roles and profile fields onto Odoo users",
    "description": """
Infinito.Nexus RBAC & Profile Mapping
=====================================

Shared helpers for the sign-in overrides of auth_oauth_https and
auth_ldap_profile:

* resolves the declared roles of the deployment (ODOO_RBAC_ROLES) into Odoo
  groups and refuses a sign-in that holds none of them, the platform
  administrator (ODOO_RBAC_PROTECTED_LOGIN) excepted;
* replaces the managed groups of a user with the groups its roles grant;
* validates profile values (name, email, phone, language, time zone) against
  what the database accepts before they are written.
    """,
    "author": "Infinito.Nexus",
    "website": "https://infinito.nexus",
    "depends": ["base"],
    "data": [],
    "installable": True,
    "auto_install": False,
    "application": False,
    "license": "Other proprietary",
}
