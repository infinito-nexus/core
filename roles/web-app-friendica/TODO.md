# TODOs

## Migrate auth to the `saml` addon (replaces oauth2-proxy + ldapauth + double-login)

**Why:** Friendica currently authenticates in two steps: oauth2-proxy gates
the vhost (Keycloak-Authorization-Code-Flow, 2FA-enforceable), then the user
must fill Friendica's own `/login` form because stock Friendica has **no
header-trusted auto-login** — Owa.php / OAuth/Token.php only read
`HTTP_AUTHORIZATION` for API endpoints, never for the web session. The
ldapauth addon stays enabled solely as a first-login bootstrap that
materialises the `friendica.user` row from openldap.

The double-login is UX-hostile (creds typed twice) and the second hop
silently bypasses any 2FA Keycloak enforced on the first hop — anyone with
the LDAP password can reach the app even when WebAuthn/OTP is required at
the IdP. Friendica's stock `saml` addon (already on disk under
`/var/www/html/addon/saml/`) supports a SAML2 AuthnRequest → IdP-initiated
SSO with auto-account-creation, which collapses the chain to a single
2FA-gated round-trip.

**Migration outline (~4-6h):**

1. Enable `addons.saml: {}` in `meta/services.yml` (and drop `addons.ldapauth: {}`
   plus `services.oauth2` once SAML autocreate is verified).
2. Template `saml.config.php.j2` analogous to `ldapauth.config.php.j2`:
   IdP-metadata-URL, SP-Entity-ID, SP-ACS-URL, NameID format, attribute map
   (`email`/`firstName`/`lastName`/`groups`), signing/encryption cert paths.
3. Mount the rendered `saml.config.php` in `compose.yml.j2` (analogous to
   ldapauth).
4. Provision a SAML client in Keycloak (extend `roles/web-app-keycloak`'s
   client-provisioning logic which currently only handles OIDC clients).
   Attribute mappers, SP-metadata import, signing certificate alignment.
5. Drop `services.oauth2.enabled` for friendica — SAML handles SSO end-to-
   end, oauth2-proxy in front would double-gate.
6. Rewrite `files/playwright/playwright.spec.js` to use the generic admin/biber
   persona flows (remove `PERSONA_*_BLOCKED=true` from
   `templates/playwright.env.j2`, drop the bespoke `loginViaOauth2ProxyAndFriendica`
   helper, drop the FRIENDICA_BASE_URL env var).

**Risks / unknowns:**

- Friendica's `saml` addon is community-maintained — last-commit recency
  AND config-format compatibility need verification before committing to
  it as the canonical SSO path.
- SAML cert lifecycle (rotation, alignment between Friendica SP and
  Keycloak IdP) is a new maintenance burden — clarify ownership before
  shipping.
- First-login autocreate via SAML's `auto_register` option must be tested
  with both the `administrator` and `biber` openldap-sourced identities
  before ldapauth is removed.
