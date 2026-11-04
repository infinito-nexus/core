# nocheck: mirrored-unit-test - an Odoo abstract model; every method resolves groups and writes users through a live registry
# Part of Infinito.Nexus. See LICENSE file for full copyright and licensing details.

import json
import logging
import os

from odoo import SUPERUSER_ID, Command, api, models
from odoo.exceptions import AccessDenied

_logger = logging.getLogger(__name__)


class InfinitoRbac(models.AbstractModel):
    _name = "infinito.rbac"
    _description = "Identity provider role and profile mapping"

    @api.model
    def _roles(self):
        """Return the declared roles rendered into ODOO_RBAC_ROLES.

        Returns:
            list of dicts with ``path`` (groups claim value), ``dn`` (LDAP
            group DN) and ``groups`` (Odoo group XML ids the role grants).
        """
        return json.loads(os.environ["ODOO_RBAC_ROLES"])

    @api.model
    def _groups(self, xmlids):
        groups = self.env["res.groups"].sudo()
        for xmlid in xmlids:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                groups |= group
        return groups

    @api.model
    def _is_protected(self, login):
        return (login or "").lower() == os.environ["ODOO_RBAC_PROTECTED_LOGIN"].lower()

    @api.model
    def _authorize(self, login, holds):
        """Resolve the Odoo groups of a sign-in, refusing it without a role.

        Args:
            login: the Odoo login of the user signing in.
            holds: predicate that is true for every role entry the user holds.

        Returns:
            (managed, granted): every group a declared role can grant, and the
            groups the held roles grant.
        """
        roles = self._roles()
        managed = self._groups([xmlid for role in roles for xmlid in role["groups"]])
        granted = self._groups(
            [xmlid for role in roles if holds(role) for xmlid in role["groups"]]
        )
        internal = self.env.ref("base.group_user")
        portal = self.env.ref("base.group_portal")
        if granted - portal:
            granted = (granted - portal) | internal
        if not granted:
            if not self._is_protected(login):
                _logger.info("RBAC: %s holds no declared role, sign-in refused", login)
                raise AccessDenied
            granted = internal
        return managed | internal | portal, granted

    @api.model
    def _apply(self, user, managed, granted):
        """Replace the managed groups of ``user`` with ``granted``.

        Args:
            user: res.users record.
            managed: every group a declared role can grant.
            granted: the groups the roles of ``user`` grant.
        """
        if user.id == SUPERUSER_ID or self._is_protected(user.login):
            return
        current = user.sudo().group_ids
        drop = (current & managed) - granted
        if self.env.ref("base.group_portal") in granted:
            internal = self.env.ref("base.group_user")
            drop |= current.filtered(lambda group: internal in group.all_implied_ids)
        commands = [Command.unlink(group.id) for group in drop]
        commands += [Command.link(group.id) for group in granted - current]
        if commands:
            user.sudo().write({"group_ids": commands})

    @api.model
    def _lang(self, value):
        if not value:
            return None
        installed = [
            code
            for code in self.env["res.partner"]._fields["lang"].get_values(self.env)
            if code
        ]
        wanted = value.replace("-", "_")
        for code in installed:
            if code.lower() == wanted.lower():
                return code
        language = wanted.split("_")[0].lower()
        for code in installed:
            if code.split("_")[0].lower() == language:
                return code
        return None

    @api.model
    def _profile(self, name, email, phone, lang, tz):
        """Return the res.users values for profile fields the database accepts.

        Args:
            name: display name.
            email: email address.
            phone: phone number.
            lang: locale such as ``de``, ``de-DE`` or ``de_DE``; dropped unless installed.
            tz: IANA time zone; dropped unless Odoo knows it.
        """
        values = {}
        if name:
            values["name"] = name
        if email:
            values["email"] = email
        if phone:
            values["phone"] = phone
        code = self._lang(lang)
        if code:
            values["lang"] = code
        if tz and tz in self.env["res.partner"]._fields["tz"].get_values(self.env):
            values["tz"] = tz
        return values
