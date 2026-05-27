# Part of Infinito.Nexus. See LICENSE file for full copyright and licensing details.

import logging
import os

from odoo import api, models
from odoo.exceptions import AccessDenied

_logger = logging.getLogger(__name__)

# Configurable OIDC UID field via environment variable
# Defaults to 'preferred_username' which is the standard OIDC claim
# Set via ODOO_OIDC_UID_FIELD env var, sourced from OIDC.ATTRIBUTES.USERNAME
OIDC_UID_FIELD = os.environ.get("ODOO_OIDC_UID_FIELD", "preferred_username")


class ResUsersOAuthConfigurableUid(models.Model):
    """
    Override OAuth user authentication to use a configurable UID claim.

    Odoo's standard auth_oauth module uses the 'user_id' claim from the OAuth
    provider's userinfo response to identify users. However, this claim is not
    standard in OIDC - Keycloak maps the internal UUID as user_id by default.

    This override changes the lookup to use a configurable claim field
    (default: 'preferred_username'), set via the ODOO_OIDC_UID_FIELD env var.
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
    def _auth_oauth_signin(self, provider, validation, params):
        """Reimplement upstream signin, bypassing the broken template-copy path.

        Upstream _auth_oauth_signin delegates auto-provisioning to
        auth_signup.signup() → _create_user_from_template(), which performs
        template_user.copy(values) inside a savepoint. When that savepoint
        flushes, recompute of related binary fields triggers
        ir_attachment._check_contents() → env.user._get_group_ids() →
        ensure_one(). During the unauthenticated OAuth callback request, the
        flush runs under default_env with an empty user recordset, so
        ensure_one() raises and the signup gets converted to AccessDenied
        with no traceback at the controller level.

        We sidestep the template entirely by creating the new user directly
        via sudo().create(), adding the portal group explicitly. This keeps
        OAuth first-login auto-provisioning working across infinito.nexus
        without depending on the transient env in the signup flush path.

        The log ERROR branch remains: if create() raises, we surface the real
        cause before re-raising AccessDenied (which the controller turns into
        oauth_error=3).
        """
        oauth_uid = validation["user_id"]
        oauth_user = self.search(
            [("oauth_uid", "=", oauth_uid), ("oauth_provider_id", "=", provider)]
        )
        if oauth_user:
            assert len(oauth_user) == 1  # noqa: S101  mirrors upstream Odoo invariant; oauth_uid is unique per provider
            oauth_user.write({"oauth_access_token": params["access_token"]})
            return oauth_user.login
        if self.env.context.get("no_user_creation"):
            return None
        values = self._generate_signup_values(provider, validation, params)
        create_values = {k: v for k, v in values.items() if k != "oauth_access_token"}
        create_values["active"] = True
        # Align login with oauth_uid so provisioned users follow the same
        # seeded-admin pattern (login=preferred_username, not email).
        create_values["login"] = oauth_uid
        # Auto-provisioned OAuth users are internal users of the stack, not
        # portal customers. Portal-only (base.group_portal) lands the user on
        # the website root and blocks /web backend access.
        internal_group = self.env.ref("base.group_user", raise_if_not_found=False)
        if internal_group:
            create_values["group_ids"] = [(4, internal_group.id)]
        try:
            sudo_model = self.sudo().with_context(no_reset_password=True)
            new_user = sudo_model.create(create_values)
            new_user.sudo().write({"oauth_access_token": params["access_token"]})
            # Flush pending recomputes now, under the sudo env, so the
            # controller's subsequent cr.commit() doesn't trigger
            # ir_attachment._check_contents() → env.user._get_group_ids()
            # on an empty env.user (public/unauthenticated OAuth callback).
            sudo_model.env.flush_all()
        except Exception:
            _logger.exception(
                "OAuth signup failed for provider=%s user_id=%s email=%s values=%s",
                provider,
                oauth_uid,
                validation.get("email"),
                create_values,
            )
            raise AccessDenied from None
        _logger.info(
            "OAuth auto-provisioned user login=%s oauth_uid=%s provider=%s",
            new_user.login,
            oauth_uid,
            provider,
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
        configured claim (default: preferred_username) is present in the
        validation dict, replaces user_id with that claim. Standard Odoo
        _auth_oauth_signin then searches res_users.oauth_uid for the remapped
        value, matching the seeded administrator/biber accounts.
        """
        validation = super()._auth_oauth_validate(provider, access_token)
        if validation.get(OIDC_UID_FIELD):
            validation["user_id"] = validation[OIDC_UID_FIELD]
            _logger.debug(
                "OAuth: remapped user_id to %s '%s' for provider %s",
                OIDC_UID_FIELD,
                validation[OIDC_UID_FIELD],
                provider,
            )
        return validation
