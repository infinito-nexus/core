# Part of Infinito.Nexus. See LICENSE file for full copyright and licensing details.

import os

from odoo import SUPERUSER_ID, Command, models


def _text(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def _first(ldap_entry, attribute):
    values = ldap_entry[1].get(attribute) or []
    return _text(values[0]) if values else ""


class ResCompanyLdapProfile(models.Model):
    _inherit = "res.company.ldap"

    def _query(self, conf, ldap_filter, retrieve_attributes=None):
        if retrieve_attributes is None:
            retrieve_attributes = ["*", os.environ["ODOO_LDAP_ATTR_MEMBER_OF"]]
        return super()._query(conf, ldap_filter, retrieve_attributes)

    def _infinito_holds(self, ldap_entry):
        """Return the role predicate of an entry for infinito.rbac._authorize.

        Args:
            ldap_entry: (dn, attrs) tuple whose attrs carry ODOO_LDAP_ATTR_MEMBER_OF.
        """
        member_of = {
            _text(dn).lower()
            for dn in ldap_entry[1].get(os.environ["ODOO_LDAP_ATTR_MEMBER_OF"]) or []
        }
        return lambda role: role["dn"].lower() in member_of

    def _infinito_profile(self, ldap_entry):
        return self.env["infinito.rbac"]._profile(
            name=_first(ldap_entry, os.environ["ODOO_LDAP_ATTR_FULLNAME"]),
            email=_first(ldap_entry, os.environ["ODOO_LDAP_ATTR_MAIL"]),
            phone=_first(ldap_entry, os.environ["ODOO_LDAP_ATTR_PHONE"]),
            lang=_first(ldap_entry, os.environ["ODOO_LDAP_ATTR_LOCALE"]),
            tz=_first(ldap_entry, os.environ["ODOO_LDAP_ATTR_TIMEZONE"]),
        )

    def _infinito_sync(self, user, ldap_entry, managed, granted):
        """Write the directory profile and the role groups onto ``user``.

        Args:
            user: res.users record that signed in.
            ldap_entry: its (dn, attrs) directory entry.
            managed: every group a declared role can grant.
            granted: the groups the roles of the entry grant.
        """
        profile = self._infinito_profile(ldap_entry)
        if profile:
            user.sudo().write(profile)
        self.env["infinito.rbac"]._apply(user, managed, granted)

    def _map_ldap_attributes(self, conf, login, ldap_entry):
        data = super()._map_ldap_attributes(conf, login, ldap_entry)
        data["company_ids"] = [Command.link(data["company_id"])]
        data.update(self._infinito_profile(ldap_entry))
        granted = self.env.context.get("infinito_rbac_granted")
        if granted is not None:
            data["group_ids"] = [Command.set(granted)]
        return data

    def _get_or_create_user(self, conf, login, ldap_entry):
        """Find or create the user of a first LDAP sign-in as the superuser.

        Args:
            conf: LDAP configuration dict from _get_ldap_dicts.
            login: the login that signed in.
            ldap_entry: its (dn, attrs) directory entry.

        Returns:
            The res.users id.
        """
        ldap = self.with_user(SUPERUSER_ID)
        managed, granted = ldap.env["infinito.rbac"]._authorize(
            login, ldap._infinito_holds(ldap_entry)
        )
        scoped = ldap.with_context(infinito_rbac_granted=granted.ids)
        user_id = super(ResCompanyLdapProfile, scoped)._get_or_create_user(
            conf, login, ldap_entry
        )
        ldap._infinito_sync(
            ldap.env["res.users"].browse(user_id), ldap_entry, managed, granted
        )
        return user_id
