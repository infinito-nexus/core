# nocheck: mirrored-unit-test - an Odoo ORM model inheriting res.users; its methods run against a live cursor and recordset
# Part of Infinito.Nexus. See LICENSE file for full copyright and licensing details.

import logging
import os

from odoo import Command, api, models
from odoo.exceptions import AccessDenied

_logger = logging.getLogger(__name__)


class ResUsersOAuthConfigurableUid(models.Model):
    """
    Override OAuth user authentication to use a configurable UID claim.

    Odoo's standard auth_oauth module uses the 'user_id' claim from the OAuth
    provider's userinfo response to identify users. However, this claim is not
    standard in OIDC - Keycloak maps the internal UUID as user_id by default.

    This override changes the lookup to use the claim field the deploy names
    in ODOO_OIDC_UID_FIELD, rendered from OIDC.ATTRIBUTES.USERNAME.
    This aligns Odoo with how other applications in the infinito.nexus stack
    identify users:
    - Mastodon: OIDC_UID_FIELD = preferred_username
    - Pixelfed: PF_OIDC_FIELD_ID = preferred_username
    - EspoCRM: OIDC_USERNAME_CLAIM = preferred_username
    - Taiga: OIDC_USERNAME_CLAIM = preferred_username

    The oauth_uid stored in res_users is now the user's username (e.g., 'admin')
    rather than a UUID, making it human-readable and consistent across the stack.
    """

    _inherit = "res.users"

    @api.model
    def _oidc_profile(self, validation):
        return self.env["infinito.rbac"]._profile(
            name=validation.get(os.environ["ODOO_OIDC_NAME_CLAIM"]),
            email=validation.get(os.environ["ODOO_OIDC_EMAIL_CLAIM"]),
            phone=validation.get(os.environ["ODOO_OIDC_PHONE_CLAIM"]),
            lang=validation.get(os.environ["ODOO_OIDC_LOCALE_CLAIM"]),
            tz=validation.get(os.environ["ODOO_OIDC_ZONEINFO_CLAIM"]),
        )

    @api.model
    def _oidc_role_paths(self, validation):
        raw = validation.get(os.environ["ODOO_OIDC_GROUP_CLAIM"]) or []
        return {raw} if isinstance(raw, str) else set(raw)

    @api.model
    def _auth_oauth_signin(self, provider, validation, params):
        """Sign in or provision the user of a validated access token.

        Every sign-in refuses a user whose groups claim holds no declared role
        (the platform administrator excepted), replaces the managed Odoo groups
        with the groups the roles grant, and writes the profile claims.
        Provisioning creates the user directly instead of upstream's
        auth_signup template copy: that copy flushes under the empty user of
        the unauthenticated callback and fails in ensure_one().

        Args:
            provider: auth.oauth.provider id.
            validation: userinfo claims, ``user_id`` remapped by _auth_oauth_validate.
            params: callback parameters carrying ``access_token``.

        Returns:
            the login of the signed-in user, None when user creation is disabled.
        """
        rbac = self.env["infinito.rbac"]
        oauth_uid = validation["user_id"]
        paths = self._oidc_role_paths(validation)
        profile = self._oidc_profile(validation)

        oauth_user = self.sudo().search(
            [("oauth_uid", "=", oauth_uid), ("oauth_provider_id", "=", provider)]
        )
        if oauth_user:
            assert len(oauth_user) == 1  # noqa: S101  mirrors upstream Odoo invariant; oauth_uid is unique per provider
            managed, granted = rbac._authorize(
                oauth_user.login, lambda role: role["path"] in paths
            )
            oauth_user.write({"oauth_access_token": params["access_token"], **profile})
            rbac._apply(oauth_user, managed, granted)
            return oauth_user.login
        if self.env.context.get("no_user_creation"):
            return None

        _managed, granted = rbac._authorize(
            oauth_uid, lambda role: role["path"] in paths
        )
        values = self._generate_signup_values(provider, validation, params)
        create_values = {k: v for k, v in values.items() if k != "oauth_access_token"}
        create_values.update(profile)
        create_values["active"] = True
        create_values["login"] = oauth_uid
        create_values["group_ids"] = [Command.set(granted.ids)]
        try:
            sudo_model = self.sudo().with_context(no_reset_password=True)
            new_user = sudo_model.create(create_values)
            new_user.write({"oauth_access_token": params["access_token"]})
            sudo_model.env.flush_all()
        except Exception:
            _logger.exception(
                "OAuth signup failed for provider=%s user_id=%s email=%s",
                provider,
                oauth_uid,
                validation.get("email"),
            )
            raise AccessDenied from None
        _logger.info(
            "OAuth auto-provisioned user login=%s oauth_uid=%s provider=%s groups=%s",
            new_user.login,
            oauth_uid,
            provider,
            granted.mapped("name"),
        )
        return new_user.login

    @api.model
    def _auth_oauth_validate(self, provider, access_token):
        """
        Override OAuth validation to remap user_id to the configured OIDC claim.

        Odoo's upstream _auth_oauth_validate unifies the subject identity by
        popping 'sub', 'id', and 'user_id' from the validation dict and storing
        the first non-empty value back as validation['user_id']. For Keycloak
        and other OIDC providers, 'sub' is an opaque UUID which is not
        human-readable and does not align with how other applications in the
        infinito.nexus stack identify users.

        This override runs after the upstream unification and, when the
        configured claim is present in the validation dict, replaces user_id
        with that claim. Standard Odoo
        _auth_oauth_signin then searches res_users.oauth_uid for the remapped
        value, matching the seeded administrator/biber accounts.

        ODOO_OIDC_UID_FIELD is read here rather than at import time: env.j2
        writes it only while services.sso.enabled is true, and the addon
        stays installed after SSO is turned off, so a module-scope read would
        stop Odoo from loading the addon at all.
        """
        validation = super()._auth_oauth_validate(provider, access_token)
        uid_field = os.environ["ODOO_OIDC_UID_FIELD"]
        if validation.get(uid_field):
            validation["user_id"] = validation[uid_field]
            _logger.debug(
                "OAuth: remapped user_id to %s '%s' for provider %s",
                uid_field,
                validation[uid_field],
                provider,
            )
        return validation
