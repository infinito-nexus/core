# nocheck: mirrored-unit-test - an Odoo ORM model inheriting res.users; its credential check runs against a live registry and directory
# Part of Infinito.Nexus. See LICENSE file for full copyright and licensing details.

from odoo import models


class ResUsersLdapProfile(models.Model):
    _inherit = "res.users"

    def _check_credentials(self, credential, env):
        result = super()._check_credentials(credential, env)
        if result.get("auth_method") != "ldap":
            return result
        user = self.env.user
        ldap = self.env["res.company.ldap"].sudo()
        for conf in ldap._get_ldap_dicts():
            dn, entry = ldap._get_entry(conf, user.login)
            if dn:
                managed, granted = self.env["infinito.rbac"]._authorize(
                    user.login, ldap._infinito_holds(entry)
                )
                ldap._infinito_sync(user, entry, managed, granted)
                break
        return result
