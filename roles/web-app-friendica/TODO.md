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
5. Drop `services.sso.enabled` for friendica — SAML handles SSO end-to-
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

## First frio scheme save of a fresh account is dropped

- An account whose `user.theme` is still empty (every account the role or a visitor creates) loses the frio scheme on its first save of `/settings/display`: `src/Module/Settings/Display.php:194` calls `theme_post()` only when the posted theme equals the stored one, so the first post only stores `theme = frio` (measured 2026-10-14: a post with `frio_scheme=dark` while the stored theme differed left the scheme at `---`; the second post stored it); options: report upstream to compare against `$user['theme'] ?: system.theme`, or let the role store `theme = frio` for the accounts it provisions.

## Identity sync

- A change to the `administrator` role group reaches `config.admin_email` only on the next deploy, and a changed directory name or email never reaches an existing account, because the list is rendered into `FRIENDICA_ADMIN_MAIL` at deploy time and `ldapauth` reads the directory only when it creates the account; options: the `saml` addon migration above with an attribute and group map, or a cron that refreshes the account and the list from LDAP.

## Open self-registration

- `/register` serves the sign-up form to every visitor because the installer writes `'register_policy' => \Friendica\Module\Register::OPEN` into `config/local.config.php:27` (`bin/console config config register_policy` reports `2`), while upstream's own default in `static/settings.config.php:27` is `CLOSED`; options: set `config.register_policy` to `CLOSED` (or `APPROVE`) from the role through `bin/console config` or a mounted `config/*.config.php`, or make it an inventory switch.

## Flaky native administrator login

- `files/playwright/test-native-login-administrator.js` failed its first attempt in the B1 compose round of 2026-11-01 on the 60 s wait for `/network` after the sign-in (`files/playwright/_shared.js`) and passed on retry (log `/tmp/compose-deploy-iam-15.log:312348`); options: wait for the session cookie and the post-login redirect response instead of the `/network` render, or raise the cause in Friendica's post-login page load first.

## Missing smiley icon upstream

- `files/playwright/test-smiley-icons.js` exempts `/addon/smiley_pack/icons/opensource/vivaldi.png` (`UPSTREAM_MISSING_ICON`), which the `smiley_pack` addon references but does not ship. The fix PR friendica/friendica-addons#1390 on GitHub was closed unmerged on 2026-11-01 because the repository moved to <https://git.friendi.ca/friendica/friendica-addons>. Open the PR again there (it needs an account on git.friendi.ca; the instance offers OpenID 2.0, which Keycloak does not provide), then put an `upstream:` directive with the new PR URL back above `UPSTREAM_MISSING_ICON`.
