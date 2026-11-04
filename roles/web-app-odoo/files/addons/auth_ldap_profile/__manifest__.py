# nocheck: mirrored-unit-test - an Odoo addon manifest, a bare dict literal the registry reads; there is no behaviour to exercise
{  # noqa: B018  Odoo addon manifests are bare dict expressions at module level by design
    "name": "LDAP Profile & Role Mapping",
    "version": "1.0.0",
    "category": "Authentication",
    "summary": "Map directory profile attributes and role groups onto Odoo users on every LDAP sign-in",
    "description": """
LDAP Profile & Role Mapping
===========================

auth_ldap fills only the name from ``cn`` and sets the email only when the
login itself looks like an address, and it never touches an existing user
again. This module:

* maps name, email, phone, language and time zone from the directory
  attributes the deploy names in ODOO_LDAP_ATTR_* on creation and on every
  later LDAP sign-in; a language that is not installed or an unknown time
  zone is left out;
* reads the role groups of the entry (ODOO_LDAP_ATTR_MEMBER_OF) and refuses
  a sign-in that holds none of the declared roles (ODOO_RBAC_ROLES), the
  platform administrator excepted;
* replaces the managed Odoo groups of the user with the groups its roles
  grant.
    """,
    "author": "Infinito.Nexus",
    "website": "https://infinito.nexus",
    "depends": ["auth_ldap", "infinito_rbac"],
    "data": [],
    "installable": True,
    "auto_install": False,
    "application": False,
    "license": "Other proprietary",
}
