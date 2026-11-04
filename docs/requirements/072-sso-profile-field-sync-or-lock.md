# 072 - SSO Profile Field Sync or Lock

## User Story

As a user signed in through SSO, I want every profile field an application lets me edit to either reach my central account or be visibly locked with a reason, so that no change I make silently disappears at my next login.

## Decisions (2026-11-01)

1. Every application with SSO is inventoried for profile fields the user can edit in the application, that the next SSO login overwrites, and that the application does not write back to Keycloak or LDAP.
2. Where the application can write such a field back on its own, write-back is switched on; otherwise the field is rendered read-only and shows a warning when the pointer rests on it.
3. Joomla keeps overwriting groups from Keycloak and locks its profile fields.
4. A field overwritten by a timer or a deploy counts as overwritten, the same as one overwritten at login.

## Inventory (2026-11-01)

| Role | Field | Editable in app | Overwritten (login, timer or deploy) | Written back | Existing lock | Treatment | Evidence |
|---|---|---|---|---|---|---|---|
| web-app-akaunting | (no SSO-managed profile: one seeded Laravel admin behind the gate) | n/a | no | no | n/a | none needed | read: roles/web-app-akaunting/templates/playwright.env.j2:44 |
| web-app-baserow | first name | yes | yes (login, `X-Forwarded-Name`) | no | none | lock | read: roles/web-app-baserow/files/sso/infinito_sso.py:97-104,243-245 |
| web-app-baserow | language | yes | yes (login, `locale` claim) | no | none | lock | read: roles/web-app-baserow/files/sso/infinito_sso.py:107-119,181-183 |
| web-app-baserow | email | unverified | no (set only when empty) | no | none | none needed | read: roles/web-app-baserow/files/sso/infinito_sso.py:240-242 |
| web-app-baserow | staff/superuser | admin-only | yes (login; bootstrap admin exempt) | no | none | lock | read: roles/web-app-baserow/files/sso/infinito_sso.py:137-148,246-250 |
| web-app-bigbluebutton | name | no for SSO accounts | yes (ResyncOnLogin default true) | no | upstream (UI + API) | keep lock | read: roles/web-app-bigbluebutton/templates/env.j2:119-123; upstream: <https://github.com/bigbluebutton/greenlight/blob/release-3.9.0.1/app/controllers/api/v1/users_controller.rb#L204-L214> |
| web-app-bigbluebutton | email | no | yes | no | upstream | keep lock | upstream: <https://github.com/bigbluebutton/greenlight/blob/release-3.8.0/app/javascript/components/users/user/forms/UpdateUserForm.jsx#L75-L76> |
| web-app-bigbluebutton | language, avatar | yes | no (language first login only; no picture claim) | no | none | none needed | upstream: <https://github.com/bigbluebutton/greenlight/blob/release-3.9.0.1/app/controllers/external_controller.rb#L69> |
| web-app-bigbluebutton | role | admin-only | yes (timer, reconcile_roles.rb) | no | none | lock | read: roles/web-app-bigbluebutton/README.md:20 |
| web-app-bluesky | display name | yes | yes (login broker writes `name` claim) | no | none | lock | read: roles/web-app-bluesky/files/login-broker/server.js:371-402 |
| web-app-bluesky | avatar, banner, description, handle, email | yes | no | no | none | none needed | read: roles/web-app-bluesky/files/login-broker/server.js:349-357,385-391 |
| web-app-bookwyrm | display name, language, time zone | yes | yes (every new session, headers) | no | none | lock | read: roles/web-app-bookwyrm/files/sso/header_auth.py:129-130,153-165 |
| web-app-bookwyrm | groups, is_staff | admin-only (unverified) | yes (login) | no | none | lock | read: roles/web-app-bookwyrm/files/sso/header_auth.py:142-152 |
| web-app-bookwyrm | email, avatar, summary | yes | no (email at provisioning only) | no | none | none needed | read: roles/web-app-bookwyrm/files/sso/header_auth.py:241-251 |
| web-app-checkmk | full name, email, pager | no once LDAP-synced | yes (LDAP sync) | no | upstream (LDAP connector locks synced attributes) | keep lock | read: roles/web-app-checkmk/files/shell/configure-sso.sh:38-41; upstream (commit list only, own-profile page unverified) |
| web-app-checkmk | roles | no when synced | yes (LDAP sync) | no | upstream | keep lock | read: roles/web-app-checkmk/files/shell/configure-sso.sh:42-46 |
| web-app-checkmk | language, personal settings | yes | no | no | none | none needed | read: roles/web-app-checkmk/files/shell/configure-sso.sh:8-13 |
| web-app-dashboard | (no own accounts, browser `oidc.js` only) | n/a | n/a | n/a | n/a | none needed | read: roles/web-app-dashboard/README.md:29 |
| web-app-decidim | name, nickname, email, locale, avatar, URL, about | yes | no | no | none | none needed | upstream: <https://github.com/decidim/decidim/blob/develop/decidim-core/app/commands/decidim/create_omniauth_registration.rb> |
| web-app-decidim | admin flag, user_manager | admin-only | yes (login) | no | none | lock | read: roles/web-app-decidim/files/ruby/initializers/infinito_rbac.rb:25-26,32 |
| web-app-discourse | name | no | yes | no | yes (`auth_overrides_name`, server Guardian) | keep lock | read: roles/web-app-discourse/files/ruby/apply_settings.rb:31 |
| web-app-discourse | email | no | yes | no | yes (`email_editable=false`, `auth_overrides_email`) | keep lock | read: roles/web-app-discourse/files/ruby/apply_settings.rb:29-30; roles/web-app-discourse/files/ruby/verify_settings.rb:27 |
| web-app-discourse | username | staff only | no (`auth_overrides_username=false`) | no | n/a | none needed | read: roles/web-app-discourse/files/ruby/apply_settings.rb:18,32 |
| web-app-discourse | avatar, bio, location, website, locale | yes | no (filled only when blank) | no | none | none needed | upstream: <https://github.com/discourse/discourse/blob/main/lib/auth/managed_authenticator.rb> |
| web-app-discourse | admin/moderator flags | staff only | yes (login + timer) | no | none | lock | read: roles/web-app-discourse/files/ruby/plugins/infinito-rbac-login/plugin.rb:28-38,44 |
| web-app-discourse | associated groups | yes (public groups) / admin | yes (login, interaction with manual joins unverified) | no | none | unverified | read: roles/web-app-discourse/README.md:19 |
| web-app-erpnext | first name, last name | yes | yes (OIDC role app; LDAP `update_user_fields`) | no | none | lock | read: roles/web-app-erpnext/files/python/infinito_rbac/infinito_rbac/login.py:60-79,120-121; roles/web-app-erpnext/files/python/apply/ldap_source.py:52-53 |
| web-app-erpnext | phone, mobile | yes | yes (LDAP login) | no | none | lock (LDAP variant) | read: roles/web-app-erpnext/files/python/apply/ldap_source.py:54-55 |
| web-app-erpnext | email | account key (editability unverified) | no, but a changed email makes the next sign-in create a second account | no | none | lock (identity key) | read: roles/web-app-erpnext/TODO.md:3 |
| web-app-erpnext | language, time zone, avatar | yes | no | no | none | none needed | read: roles/web-app-erpnext/files/python/infinito_rbac/infinito_rbac/login.py:108-109 |
| web-app-erpnext | roles | System Manager | yes (OIDC + LDAP `sync_roles`) | no | none | lock | read: roles/web-app-erpnext/files/python/infinito_rbac/infinito_rbac/login.py:123-131 |
| web-app-espocrm | first/middle/last name, email, phone, gender | yes (upstream, unverified) | yes (OIDC, `ESPOCRM_CONFIG_OIDC_SYNC=true`); LDAP no | no | none | lock | read: roles/web-app-espocrm/templates/env.j2:70; upstream: <https://github.com/espocrm/espocrm/blob/master/application/Espo/Core/Authentication/Oidc/UserProvider/Sync.php> |
| web-app-espocrm | teams, user type | admin-only | yes (OIDC + LDAP hook) | no | none | lock | read: roles/web-app-espocrm/files/php/rbac/group_user_provider.php:51-53,73-86; roles/web-app-espocrm/files/php/rbac/ldap_role_groups.php:81-94 |
| web-app-espocrm | avatar, language, time zone | yes | no | no | none | none needed | upstream: <https://github.com/espocrm/espocrm/blob/master/application/Espo/Core/Authentication/Oidc/UserProvider/DefaultUserInfoPopulator.php> |
| web-app-fider | name, avatar, email | yes | no | no | none | none needed | read: roles/web-app-fider/README.md:24 |
| web-app-fider | role | admin-only | yes (timer) | no | none | lock | read: roles/web-app-fider/README.md:25 |
| web-app-flowise | (single instance account behind gate, no in-app OIDC) | n/a | no | no | n/a | none needed | read: roles/web-app-flowise/README.md:67 |
| web-app-friendica | name, nickname, email, avatar, location, language, time zone | yes | no (ldapauth reads LDAP only at account creation) | no | none | none needed (side effect: admin list rendered from Keycloak emails at deploy) | read: roles/web-app-friendica/TODO.md:58; roles/web-app-friendica/templates/ldapauth.config.php.j2:18-22 |
| web-app-funkwhale | email | yes | yes (LDAP sign-in, `AUTH_LDAP_ALWAYS_UPDATE_USER`) | no | none | lock | read: roles/web-app-funkwhale/templates/settings.py.j2:4; roles/web-app-funkwhale/templates/env.j2:55 |
| web-app-funkwhale | first/last name, username | unverified | yes (LDAP map) | no | none | lock if editable (unverified) | read: roles/web-app-funkwhale/templates/env.j2:55 |
| web-app-funkwhale | permission flags | admin-only | yes (LDAP sign-in) | no | none | lock | read: roles/web-app-funkwhale/templates/settings.py.j2:5; roles/web-app-funkwhale/vars/main.yml:17-22 |
| web-app-funkwhale | avatar, summary, privacy | yes | no | no | none | none needed | read: roles/web-app-funkwhale/templates/env.j2:55 |
| web-app-fusiondirectory | all LDAP attributes (name, mail, uid, phone, address, groups) | yes (ACL holders) | no (edits LDAP live) | yes (native, LDAP) | n/a | write-back (native) | read: roles/web-app-fusiondirectory/README.md:18,22,24 |
| web-app-gitea | full name | no for external users | yes (daily LDAP sync; OAuth2 login no) | no | yes (`EXTERNAL_USER_DISABLE_FEATURES change_full_name`) | keep lock | read: roles/web-app-gitea/templates/env.j2:98 |
| web-app-gitea | email | no for external users | yes (LDAP sync) | no | yes (`manage_credentials`) | keep lock | read: roles/web-app-gitea/templates/env.j2:98 |
| web-app-gitea | username | no for external users | set at registration | no | yes (`change_username`) | keep lock | read: roles/web-app-gitea/templates/env.j2:85,98 |
| web-app-gitea | avatar | yes | yes (LDAP sync when the photo attribute is set; OAuth2 no) | no | none | lock (LDAP users) | read: roles/web-app-gitea/vars/main.yml:21 |
| web-app-gitea | admin/restricted flag | admin-only | yes (OAuth2 group claim + LDAP filters) | no | none | lock | read: roles/web-app-gitea/vars/main.yml:14-15,31-33 |
| web-app-gitea | description, website, location, language | yes | no | no | none | none needed | read: roles/web-app-gitea/vars/main.yml:5-33 |
| web-app-gitlab | name, email | no | yes | no | yes (`sync_profile_attributes`) | keep lock | read: roles/web-app-gitlab/templates/config/gitlab.yml.j2:70-71; roles/web-app-gitlab/files/playwright/playwright.spec.js:117-120 |
| web-app-gitlab | username, avatar, locale, time zone, bio, website | yes | no | no | none | none needed | read: roles/web-app-gitlab/templates/config/gitlab.yml.j2:71 |
| web-app-gitlab | admin/external flags | admin-only | yes (timer) | no | none | lock | read: roles/web-app-gitlab/README.md:18 |
| web-app-grafana | name, email, login | UI disabled; `PUT /api/user` and `PUT /api/users/:id` answer 403 "Cannot update external User" for OAuth accounts (13.3.0) | yes (every login) | no | upstream (UI + API) | keep lock; add warning | read: roles/web-app-grafana/templates/env.j2:29-31; upstream: <https://github.com/grafana/grafana/blob/main/pkg/api/user.go> (user.go:243-247, utils.go:30-53) |
| web-app-grafana | org role | admin-only | yes (`role_attribute_path`, strict) | no | upstream server refusal | keep lock | read: roles/web-app-grafana/templates/env.j2:32-34 |
| web-app-grafana | preferences (theme, time zone, language) | yes | no | no | none | none needed | read: roles/web-app-grafana/templates/env.j2:21-39 |
| web-app-hermes | (one shared dashboard account) | n/a | n/a | n/a | n/a | none needed | read: roles/web-app-hermes/README.md:58 |
| web-app-homeassistant (LDAP only) | display name | admin-only | first login only | no | none | none needed | read: roles/web-app-homeassistant/files/python/ldap_login.py:158-159 |
| web-app-homeassistant | group, active flag | admin-only | yes (timer, align_ldap_users.py) | no | none | lock | read: roles/web-app-homeassistant/files/python/align_ldap_users.py:63-68 |
| web-app-homeassistant | language, time zone, theme | yes | no | no | none | none needed | read: roles/web-app-homeassistant/templates/configuration.yaml.j2:35-44 |
| web-app-jellyfin | avatar | yes | yes, LDAP variant only (photo_sync.py on deploy and timer) | no | none | lock (LDAP variant) | read: roles/web-app-jellyfin/TODO.md:3; roles/web-app-jellyfin/files/shell/configure-auth.sh:178-179 |
| web-app-jellyfin | administrator flag | admin-only | yes (SSO + LDAP login) | no | none | lock | read: roles/web-app-jellyfin/files/shell/configure-auth.sh:171,200,204,211 |
| web-app-jellyfin | preferences, language | yes | no | no | none | none needed | read: roles/web-app-jellyfin/files/shell/configure-auth.sh:195-215 |
| web-app-jenkins | full name | yes | yes (OIDC + LDAP) | no | none | lock | read: roles/web-app-jenkins/templates/casc.yaml.j2:21,35 |
| web-app-jenkins | email | yes | yes (OIDC + LDAP) | no | none | lock | read: roles/web-app-jenkins/templates/casc.yaml.j2:22,36 |
| web-app-jenkins | description, time zone | yes | no | no | none | none needed | read: roles/web-app-jenkins/templates/casc.yaml.j2:20-23 |
| web-app-jitsi | display name, email (meeting profile) | yes (per browser) | yes with keycloak_adapter (token on next join, unverified) | no | none (upstream `readOnlyName`/`disableProfile` unused) | lock | read: roles/web-app-jitsi/templates/keycloak_adapter/context.ts.j2:8-23; upstream: <https://github.com/jitsi/jitsi-meet/blob/master/config.js> |
| web-app-joomla | name, email | no for SSO accounts | yes | no | yes (readonly + server restore, `keycloak_managed`) | keep lock | read: roles/web-app-joomla/files/joomla-oidc-plugin/plg_system_keycloak/src/Extension/Keycloak.php:51-57,120-145,151-159,439 |
| web-app-joomla | language, time zone | no for SSO accounts | yes | no | yes | keep lock | read: roles/web-app-joomla/files/joomla-oidc-plugin/plg_system_keycloak/src/Extension/Keycloak.php:55-56,417-418,437-438 |
| web-app-joomla | profile phone, address, website | no for SSO accounts | yes | no | yes (`managedFields()` from env) | keep lock | read: roles/web-app-joomla/files/joomla-oidc-plugin/plg_system_keycloak/src/Extension/Keycloak.php:165-172,198 |
| web-app-joomla | username | yes | no, but lookup by username: a rename orphans the account | no | none | lock (identity key; 072 Joomla criterion) | read: roles/web-app-joomla/files/joomla-oidc-plugin/plg_system_keycloak/src/Extension/Keycloak.php:52-57,428-430 |
| web-app-joomla | groups | admin-only | yes | no | none | none (Decision 3 keeps overwrite) | read: roles/web-app-joomla/files/joomla-oidc-plugin/plg_system_keycloak/src/Extension/Keycloak.php:413,435 |
| web-app-joomla (LDAP variant) | name, email | yes | no (creation only, upstream unverified) | no | none | none needed | read: roles/web-app-joomla/README.md:37 |
| web-app-keycloak (IdP) | name, email, contact attributes, locale, zoneinfo | yes (account console) | n/a (source) | yes (LDAP WRITABLE) | n/a | none needed (write-back target) | read: roles/web-app-keycloak/vars/main.yml:198-217 |
| web-app-keycloak | username; organization attributes | no (`editUsernameAllowed: false`); admin-only | n/a | yes | realm / user-profile `edit: ["admin"]` | none needed | read: roles/web-app-keycloak/templates/import/realm.json.j2:38 |
| web-app-kix | contact name, email, login, title, phones, address, comment | yes (role rights unverified) | yes (LDAP contact sync on every LDAP sign-in) | no | none | lock | read: roles/web-app-kix/vars/main.yml:50-63,78-84 |
| web-app-kix | roles | admin-only | yes (sign-in) | no | none | lock | read: roles/web-app-kix/vars/main.yml:64-70 |
| web-app-kix | language, preferences | yes | no | no | none | none needed | read: roles/web-app-kix/vars/main.yml:50-63 |
| web-app-lam | all LDAP attributes | yes (admins) | no (LDAP editor) | yes (native, LDAP) | n/a | write-back (native) | read: roles/web-app-lam/README.md:17-18 |
| web-app-listmonk | name | yes | no | no | none | none needed | upstream: <https://github.com/knadh/listmonk/blob/master/cmd/auth.go#L296-L320> |
| web-app-listmonk | email, avatar | no for SSO accounts | n/a (matched by email; picture only from claim) | no | upstream side effect | none needed | read: roles/web-app-listmonk/files/sql/rbac_reconcile.sql:64-65 |
| web-app-listmonk | role, status | admin-only | yes (timer) | no | none | lock | read: roles/web-app-listmonk/files/sql/rbac_reconcile.sql:54-61,73-79 |
| web-app-litellm | email | admin-only | yes (`upsert_sso_user`) | no | none | lock | read: roles/svc-ai-litellm/templates/env.j2:20-24; upstream: <https://raw.githubusercontent.com/BerriAI/litellm/main/litellm/proxy/management_endpoints/ui_sso.py> |
| web-app-litellm | display name (user_alias) | admin-only | first login only | no | none | none needed | upstream: (ui_sso.py above) |
| web-app-litellm | role | admin-only | yes (timer) | no | none | lock | read: roles/web-app-litellm/files/python/rbac_reconcile.py:63 |
| web-app-magento | admin account settings | yes | no | no | none | none needed | read: roles/web-app-magento/README.md:26,37 |
| web-app-magento | admin active state | admin-only | yes (timer) | no | none | lock | read: roles/web-app-magento/files/php/rbac/reconcile_admin_users.php:61-80 |
| web-app-mailu | display name | yes | unverified | no | none | none (Mailu EOL, no fixes) | read: roles/web-app-mailu/templates/env.j2:50-63 |
| web-app-map-animator | (no editable profile) | n/a | n/a | n/a | n/a | none needed | read: roles/web-app-map-animator/README.md:11,17 |
| web-app-mastodon | display name, bio, avatar, email, language, time zone | yes | no (set at creation) | no | none | none needed | upstream: <https://raw.githubusercontent.com/mastodon/mastodon/main/app/models/concerns/user/omniauthable.rb> |
| web-app-mastodon | role | admin-only | yes (login) | no | none | lock | read: roles/web-app-mastodon/files/ruby/zz_oidc_role_sync.rb:5,25-33 |
| web-app-matomo | email, language | yes | no | no | none | none needed | read: roles/web-app-matomo/vars/main.yml:51-67 |
| web-app-matomo | superuser, site access | admin-only | yes (login, existing accounts only; accounts from reconcile) | no | none | lock | read: roles/web-app-matomo/files/php/infinito_rbac_login.php:21,38,132-164; roles/web-app-matomo/TODO.md:4 |
| web-app-matrix | display name | yes | yes (`update_profile_information: true`) | no | none | lock (Synapse `enable_set_displayname: false`) | read: roles/web-app-matrix/templates/flavor/compose/synapse/homeserver.yaml.j2:96; upstream: <https://element-hq.github.io/synapse/latest/usage/configuration/config_documentation.html> |
| web-app-matrix | email (3PID), avatar | yes | no | no | none | none needed | read: roles/web-app-matrix/README.md:24 |
| web-app-matrix | server admin | API only | yes (timer) | no | none | none needed (no in-app form) | read: roles/web-app-matrix/README.md:32 |
| web-app-mattermost | first/last name, username | no for OAuth | yes | no | upstream | keep lock | read: roles/web-app-mattermost/templates/env.j2:58-63; upstream: <https://docs.mattermost.com/administration-guide/onboard/sso-gitlab.html> |
| web-app-mattermost | email | unverified | yes | no | upstream, unverified | lock if editable | upstream: <https://raw.githubusercontent.com/mattermost/mattermost/master/server/channels/app/user.go> |
| web-app-mattermost | nickname, position, avatar, language, time zone | yes | no | no | none | none needed | upstream: (user.go above) |
| web-app-mattermost | system_admin | admin-only | yes (timer) | no | none | lock | read: roles/web-app-mattermost/README.md:16 |
| web-app-mediawiki | real name, email | no (PluggableAuth default) | yes | no | upstream | keep lock | read: roles/web-app-mediawiki/templates/oidc.php.j2:23-49; upstream: <https://www.mediawiki.org/wiki/Extension:PluggableAuth> |
| web-app-mediawiki | language, time zone | no | yes (UserLoggedIn hook) | no | yes (GetPreferences `disabled`) | keep lock | read: roles/web-app-mediawiki/templates/oidc.php.j2:51-86 |
| web-app-mediawiki | groups | admin-only | yes (groupsyncs) | no | none | lock | read: roles/web-app-mediawiki/templates/oidc.php.j2:35-44 |
| web-app-minio | (no user profile) | n/a | n/a | n/a | n/a | none needed | read: roles/web-app-minio/vars/main.yml:18-28 |
| web-app-mobilizon | email | no for provider users | first login | no | upstream | keep lock | upstream: <https://framagit.org/framasoft/mobilizon/-/raw/main/src/views/Settings/AccountSettings.vue> |
| web-app-mobilizon | display name, username, avatar, language, time zone | yes | no (unverified) | no | none | none needed | read: roles/web-app-mobilizon/templates/config.exs.j2:264 |
| web-app-mobilizon | role | admin-only | yes (timer, rbac.exs) | no | none | lock | read: roles/web-app-mobilizon/TODO.md:3 |
| web-app-moodle | name parts, email, phones, address, city, country, institution, department, description, ID number, URL, language, time zone, phonetic names | no | yes (OIDC + LDAP login) | no (`field_updateremote_*` only in the LDAP-only variant) | yes (`field_lock_*: locked`) | keep lock | read: roles/web-app-moodle/tasks/04_oidc.yml:41-97; roles/web-app-moodle/tasks/06_ldap_sync.yml:35-91 |
| web-app-moodle | avatar | yes | no | no | none | none needed | read: roles/web-app-moodle/tasks/04_oidc.yml:41-97 |
| web-app-moodle | Manager, course creator, site admin | admin-only | yes (LDAP login + timer) | no | none | lock | read: roles/web-app-moodle/tasks/06_ldap_sync.yml:93-102 |
| web-app-n8n | first/last name | yes (unverified) | yes (every new session, hook) | no | none | lock | read: roles/web-app-n8n/files/javascript/hooks.js:86-102,141-153 |
| web-app-n8n | email | yes (unverified) | no, but lookup by email header: a change creates a second account | no | none | lock (identity key) | read: roles/web-app-n8n/files/javascript/hooks.js:121-140 |
| web-app-n8n | global role | admin-only | no | no | none | none needed | read: roles/web-app-n8n/files/javascript/hooks.js:129-133 |
| web-app-nextcloud (sociallogin) | display name | yes | yes (`update_profile_on_login`) | no | none (lock rendered for oidc_login only) | lock | read: roles/web-app-nextcloud/meta/addons/sociallogin.yml:80-81; roles/web-app-nextcloud/templates/config/oidc.config.php.j2:5,11 |
| web-app-nextcloud (sociallogin) | email | yes | yes | no | none | lock | read: roles/web-app-nextcloud/meta/addons/sociallogin.yml:80-81 |
| web-app-nextcloud (sociallogin) | address, phone, website | yes | yes if claim present (scope `openid groups`, unverified) | no | none | lock (or none needed if claims absent) | read: roles/web-app-nextcloud/meta/addons/sociallogin.yml:44 |
| web-app-nextcloud (sociallogin) | admin group | admin-only | yes | no | none | lock | read: roles/web-app-nextcloud/meta/addons/sociallogin.yml:45-47,62-63 |
| web-app-nextcloud (LDAP) | display name, email | no | yes (from LDAP) | no | yes (config + read-only LDAP backend) | keep lock | read: roles/web-app-nextcloud/templates/config/oidc.config.php.j2:11; roles/web-app-nextcloud/meta/addons/user_ldap.yml:78,84 |
| web-app-nextcloud (LDAP) | phone, website, organisation, role, biography, quota, avatar | no (user_ldap-mapped) | yes (LDAP login + ldap_refresh.py) | no | upstream read-only | keep lock | read: roles/web-app-nextcloud/meta/addons/user_ldap.yml:59-75; roles/web-app-nextcloud/files/playwright/test-ldap-profile.js:30 |
| web-app-nextcloud (LDAP) | address | yes (set by ldap_refresh.py, not user_ldap) | yes (timer/deploy, ldap_refresh.py) | no | none | lock | read: roles/web-app-nextcloud/TODO.md:4; roles/web-app-nextcloud/files/python/ldap_refresh.py:101-111 |
| web-app-nextcloud | language, locale, headline | yes | no | no | none | none needed | read: roles/web-app-nextcloud/files/playwright/test-ldap-profile.js:28 |
| web-app-odoo | name, email, phone, language, time zone | yes (unverified) | yes (Keycloak + LDAP sign-in) | no | none | lock | read: roles/web-app-odoo/files/addons/auth_oauth_https/models/res_users.py:41-52; roles/web-app-odoo/files/addons/auth_ldap_profile/models/res/company_ldap.py:42-44,69 |
| web-app-odoo | avatar, signature | yes | no | no | none | none needed | read: roles/web-app-odoo/README.md:57 |
| web-app-odoo | managed access groups | admin-only | yes | no | none | lock | read: roles/web-app-odoo/files/addons/infinito_rbac/models/rbac.py:110-131 |
| web-app-openbao | (no self-service profile; alias metadata and groups from claims) | no | yes | no | n/a | none needed | read: roles/web-app-openbao/tasks/utils/oidc.yml:39-41 |
| web-app-openclaw | (identity per request from header) | n/a | n/a | n/a | n/a | none needed | read: roles/web-app-openclaw/README.md:15-16 |
| web-app-opencloud | name, email | no (LDAP read-only; edit link goes to Keycloak) | n/a (read live) | n/a | yes | keep lock | read: roles/web-app-opencloud/templates/env.j2:41,62 |
| web-app-opencloud | language | yes | no | no | none | none needed | read: roles/web-app-opencloud/templates/env.j2:10,30-42 |
| web-app-opencloud | role | admin-only | yes (oidc role driver) | no | none (upstream block unverified) | lock | read: roles/web-app-opencloud/vars/main.yml:21-34 |
| web-app-openproject | first/last name, email, login | yes (unverified for LDAP users) | yes (LDAP sync job, every 24 h) | no | none | lock | read: roles/web-app-openproject/vars/ldap.yml:9-14; upstream: <https://www.openproject.org/docs/system-admin-guide/authentication/ldap-connections/> |
| web-app-openproject | admin flag | admin-only | yes (timer) | no | none | lock | read: roles/web-app-openproject/tasks/06_rbac.yml:2-21 |
| web-app-opentalk | display name, names, email, avatar, groups | unverified | unverified | no | none | unverified | read: roles/web-app-opentalk/templates/controller.toml.j2:15-30; upstream: <https://docs.opentalk.eu/admin/controller/core/oidc/> |
| web-app-openwebui | name | yes | yes (`OAUTH_UPDATE_NAME_ON_LOGIN=true`) | no | none | lock | read: roles/web-app-openwebui/templates/env.j2:121 |
| web-app-openwebui | email | admin-only | yes (`OAUTH_UPDATE_EMAIL_ON_LOGIN=true`) | no | none | lock | read: roles/web-app-openwebui/templates/env.j2:122 |
| web-app-openwebui | role, groups | admin-only | yes (OAuth role and group management) | no | none | lock | read: roles/web-app-openwebui/templates/env.j2:124-131 |
| web-app-openwebui | avatar | yes | no | no | none | none needed | upstream: <https://docs.openwebui.com/features/authentication-access/auth/sso.md> |
| web-app-pixelfed | name, email, username, bio, website, avatar, locale | yes | no | no | none | none needed | upstream: <https://raw.githubusercontent.com/pixelfed/pixelfed/dev/app/Http/Controllers/RemoteOidcController.php> |
| web-app-pixelfed | is_admin | admin-only (unverified) | yes (login) | no | none | lock | read: roles/web-app-pixelfed/files/php/rbac/oidc_login.php:37-58 |
| web-app-penpot | full name | yes | yes (timer/deploy, reconcile.sql) | no | none | lock | read: roles/web-app-penpot/files/sql/rbac/reconcile.sql:10-20; roles/web-app-penpot/TODO.md:4 |
| web-app-penpot | email | yes | no, but it is the profile key: a change detaches the account | no | none | lock (identity key) | read: roles/web-app-penpot/TODO.md:4; roles/web-app-penpot/vars/main.yml:73,85 |
| web-app-penpot | avatar, language, theme | yes | no (no LDAP photo support) | no | none | none needed | read: roles/web-app-penpot/TODO.md:3 |
| web-app-peertube | display name, language | yes | no (creation only, no `userUpdater`) | no | none | none needed | read: roles/web-app-peertube/TODO.md:7; roles/web-app-peertube/vars/oidc-settings.yml:8-9 |
| web-app-peertube | email, avatar, description | yes (email unverified) | no | no | none | none needed | upstream: <https://cdn.jsdelivr.net/npm/peertube-plugin-auth-openid-connect/main.js> |
| web-app-peertube | role | admin-only | yes (timer, reconcile-roles.sql) | no | none | lock | read: roles/web-app-peertube/TODO.md:7; roles/web-app-peertube/tasks/05_rbac.yml:2-20 |
| web-app-pgadmin | email | admin-only | no | no | none | none needed | upstream: <https://raw.githubusercontent.com/pgadmin-org/pgadmin4/master/web/pgadmin/authenticate/oauth2.py> |
| web-app-pgadmin | role | admin-only | yes (timer) | no | none | lock | read: roles/web-app-pgadmin/README.md:30 |
| web-app-phpldapadmin | all LDAP attributes | yes (admins) | no (LDAP editor) | yes (native) | n/a | write-back (native; role EOL) | read: roles/web-app-phpldapadmin/README.md:3,27 |
| web-app-phpmyadmin / pihole / postmarks / prometheus / seaweedfs / workspace / yourls / web-svc-libretranslate | (oauth2-proxy gate only, no own user profile) | n/a | n/a | n/a | n/a | none needed | read: roles/web-app-phpmyadmin/README.md:25; roles/web-app-pihole/README.md:15-16; roles/web-app-postmarks/README.md:20-29; roles/web-app-prometheus/README.md:9; roles/web-app-seaweedfs/README.md:6; roles/web-app-workspace/README.md:5; roles/web-app-yourls/files/sso/infinito_sso.php:103-118; roles/web-svc-libretranslate/README.md:41-44 |
| web-app-pretix | full name | yes | unverified (pinned pretix-oidc 2.3.1 unread) | no | none | lock if set-always confirmed | read: roles/web-app-pretix/vars/main.yml:33-34 |
| web-app-pretix | email | no (upstream form) | unverified | no | upstream | keep lock | upstream: <https://raw.githubusercontent.com/pretix/pretix/master/src/pretix/base/forms/user.py> |
| web-app-pretix | locale, time zone | yes | no | no | none | none needed | upstream: (user.py above) |
| web-app-pretix | SSO team membership, staff flag | admin-only | yes (login) | no | none | lock | read: roles/web-app-pretix/README.md:19 |
| web-app-semaphore | name, email | yes (unverified) | yes (timer, reconcile.sql; login unverified) | no | none | lock | read: roles/web-app-semaphore/files/sql/rbac/reconcile.sql:108-113 |
| web-app-semaphore | username | yes (unverified) | no | no | none | none needed (lock if a rename breaks the match, unverified) | read: roles/web-app-semaphore/files/sql/rbac/reconcile.sql:21-22 |
| web-app-semaphore | admin flag, project role | admin-only | yes (timer) | no | none | lock | read: roles/web-app-semaphore/files/sql/rbac/reconcile.sql:71-77,172-173 |
| web-app-shopware | first/last name, email, locale, time zone, avatar | yes | yes (`keepUserUpdated: true`) | no | none | lock | read: roles/web-app-shopware/files/php/oidc/client.php:143; upstream: <https://raw.githubusercontent.com/HEPTACOM/HeptacomShopwarePlatformAdminOpenAuth/main/src/Service/UserResolver.php> |
| web-app-shopware | username | yes | no | no | none | none needed | upstream: (UserResolver.php above) |
| web-app-shopware | admin flag, ACL roles | admin-only | yes (login + timer) | no | none | lock | read: roles/web-app-shopware/files/php/oidc/client.php:184,190 |
| web-app-snipe-it | first/last name, phone | yes | yes (timer/deploy, `snipeit:ldap-sync`) | no | none | lock | read: roles/web-app-snipe-it/files/php/apply/ldap_config.php:42-61; roles/web-app-snipe-it/vars/main.yml:66-78 |
| web-app-snipe-it | email, job title, department, address, mobile, employee number | admin-only | yes (timer) | no | none | lock | read: roles/web-app-snipe-it/vars/main.yml:67-78 |
| web-app-snipe-it | website, locale, avatar | yes | no | no | none | none needed | upstream: <https://github.com/grokability/snipe-it/blob/master/app/Console/Commands/LdapSync.php> |
| web-app-snipe-it | admin permission, permission group | admin-only | yes (login, SyncRolesOnLogin + timer) | no | none | lock | read: roles/web-app-snipe-it/files/php/login_rbac/src/sync_roles_on_login.php:35,126-149 |
| web-app-stalwart | display name | admin-only | yes (`claimName`) | no | none | lock | read: roles/web-app-stalwart/templates/jmap/directory/create_oidc.json.j2:9 |
| web-app-stalwart | group membership | admin-only | yes (`claimGroups`) | no | none | lock | read: roles/web-app-stalwart/templates/jmap/directory/set_claim_groups.json.j2:3 |
| web-app-stalwart | Roundcube identity, language | yes | no | no | none | none needed | read: roles/web-app-stalwart/templates/roundcube-oauth.inc.php.j2:36 |
| web-app-suitecrm | first/last name | yes | yes (SAML + LDAP sign-in) | no | none | lock | read: roles/web-app-suitecrm/files/php/iam/saml_directory_sync.php:95-109,137-159; roles/web-app-suitecrm/files/php/iam/profile_ldap_user_provider.php:70-107 |
| web-app-suitecrm | phone, mobile, title, department, address | yes | yes (SAML + LDAP sign-in) | no | none | lock | read: roles/web-app-suitecrm/vars/main.yml:60-71 |
| web-app-suitecrm | email, username | yes / no | first login only | no | none | none needed | read: roles/web-app-suitecrm/templates/env.j2:44 |
| web-app-suitecrm | language, time zone | yes | no | no | none | none needed | read: roles/web-app-suitecrm/vars/main.yml:60-76 |
| web-app-suitecrm | is_admin | admin-only | yes (SAML sign-in + timer) | no | none | lock | read: roles/web-app-suitecrm/files/php/iam/saml_directory_sync.php:106-108,124-135 |
| web-app-taiga | full name | yes | yes (OIDC `update_user` + LDAP) | no | none | lock | read: roles/web-app-taiga/templates/settings/config.append.py.j2:49,74 |
| web-app-taiga | email | yes | OIDC no; LDAP yes | no | none | lock (LDAP path) | read: roles/web-app-taiga/templates/settings/config.append.py.j2:73 |
| web-app-taiga | username | yes | no at pinned ref; LDAP lookup by username | no | none | lock (identity key) | read: roles/web-app-taiga/README.md:49; roles/web-app-taiga/TODO.md:6 |
| web-app-taiga | language, time zone | yes (time zone UI unverified) | not at pinned ref; yes after ref bump | no | none | lock (with the ref bump) | read: roles/web-app-taiga/templates/settings/config.append.py.j2:50-51; roles/web-app-taiga/TODO.md:6 |
| web-app-taiga | bio, photo, theme | yes | no | no | none | none needed | read: roles/web-app-taiga/templates/settings/config.append.py.j2:30-75 |
| web-app-taiga | superuser/staff | admin-only | yes (timer) | no | none | lock | read: roles/web-app-taiga/README.md:47-48 |
| web-app-wazuh | (no stored profile, built per request) | n/a | n/a | n/a | n/a | none needed | read: roles/web-app-wazuh/templates/config.yml.j2:22-48 |
| web-app-weblate | full name, email, username, language, avatar | yes | no (name only when empty; email protected) | no | none | none needed | upstream: <https://raw.githubusercontent.com/WeblateOrg/weblate/main/weblate/accounts/pipeline.py> |
| web-app-weblate | superuser, team membership | admin-only | yes (timer) | no | none | lock | read: roles/web-app-weblate/tasks/utils/rbac.yml:2-23 |
| web-app-wordpress | first/last name, email, website, display name, locale | yes, but locked for SSO users | yes (every login) | no | yes (JS readOnly/disabled + `$_POST` restore) | keep lock; add warning | read: roles/web-app-wordpress/files/mu-plugins/infinito-oidc-rbac-mapper.php:24-38,266-297,310-338 |
| web-app-wordpress | same fields, admin editing another user + REST `/wp/v2/users` | yes | yes | no | missing (only `show_user_profile`/`personal_options_update` hooked) | extend lock | read: roles/web-app-wordpress/files/mu-plugins/infinito-oidc-rbac-mapper.php:31-32 |
| web-app-wordpress | nickname, bio, avatar | yes | no (nickname at creation, unverified at pin) | no | none | none needed | read: roles/web-app-wordpress/meta/addons/daggerhart-openid-connect-generic.yml:31 |
| web-app-wordpress | role, blog membership, super admin | admin-only | yes (login) | no | none | lock | read: roles/web-app-wordpress/files/mu-plugins/infinito-oidc-rbac-mapper.php:17-23,121-214 |
| web-app-xwiki | first/last name, email, phone, address, website, language, time zone | yes | yes (every OIDC login) | no | none | lock | read: roles/web-app-xwiki/README.md:21; roles/web-app-xwiki/vars/main.yml:71-77; upstream: <https://raw.githubusercontent.com/xwiki-contrib/oidc/master/oidc-authenticator/src/main/java/org/xwiki/contrib/oidc/auth/internal/OIDCUserManager.java> |
| web-app-xwiki | company | yes | LDAP mode only | no | none | lock (LDAP mode) | read: roles/web-app-xwiki/vars/main.yml:57-58 |
| web-app-xwiki | administrator first/last name, email, active (deploy-provisioned) | yes | not stored at deploy (malformed object XML) | no | none | none needed for 072 (provisioning bug tracked) | read: roles/web-app-xwiki/TODO.md:6 |
| web-app-xwiki | about, avatar | yes | no | no | none | none needed | read: roles/web-app-xwiki/vars/main.yml:72-77 |
| web-app-xwiki | XWikiAdminGroup | admin-only | yes (OIDC groups mapping; LDAP group_mapping) | no | none | lock | read: roles/web-app-xwiki/templates/xwiki.properties.j2:20 |
| web-app-zammad | first/last name, email, phone | admin and agents only | yes (OIDC sign-in + LDAP import) | no | none | lock | read: roles/web-app-zammad/templates/zz/oidc/group_role_mapping.rb.j2:44-66,118-128 |
| web-app-zammad | address | API only (inactive attributes) | yes | no | hidden by default | lock (API) | read: roles/web-app-zammad/vars/main.yml:90-94 |
| web-app-zammad | mobile, department, note, login | admin and agents | yes (LDAP import schedule) | no | none | lock (LDAP mode) | read: roles/web-app-zammad/vars/main.yml:102-111 |
| web-app-zammad | roles | admin-only | yes (login + LDAP import) | no | none | lock | read: roles/web-app-zammad/templates/zz/oidc/group_role_mapping.rb.j2:68-95 |
| web-app-zammad | language, avatar | yes | no | no | none | none needed | read: roles/web-app-zammad/vars/main.yml:85-94 |
| web-svc-xmpp | vCard fields | no (read-only from LDAP) | read live | no | yes (upstream ejabberd) | none needed | read: roles/web-svc-xmpp/templates/configuration.yml.j2:79-81 |
| web-svc-xmpp | avatar (PEP) | yes | no | no | none | none needed | unverified |
| svc-ai-agent-broker / svc-ai-agent-provisioner | (API services, no profile UI) | n/a | n/a | n/a | n/a | none needed | read: roles/svc-ai-agent-broker/README.md:9,14; roles/svc-ai-agent-provisioner/README.md:5,9 |

Existing locks to reuse:

- Joomla managed-user switch and field list: roles/web-app-joomla/files/joomla-oidc-plugin/plg_system_keycloak/src/Extension/Keycloak.php:51-57,165-172,439
- Joomla readonly form fields: roles/web-app-joomla/files/joomla-oidc-plugin/plg_system_keycloak/src/Extension/Keycloak.php:120-129
- Joomla server-side restore of submitted values: roles/web-app-joomla/files/joomla-oidc-plugin/plg_system_keycloak/src/Extension/Keycloak.php:131-145,151-159
- WordPress field selectors and managed-user check: roles/web-app-wordpress/files/mu-plugins/infinito-oidc-rbac-mapper.php:37-38,303-305
- WordPress client lock and `$_POST` restore: roles/web-app-wordpress/files/mu-plugins/infinito-oidc-rbac-mapper.php:310-338
- Moodle `field_lock_*: locked`: roles/web-app-moodle/tasks/04_oidc.yml:41-97 and roles/web-app-moodle/tasks/06_ldap_sync.yml:35-91
- MediaWiki GetPreferences `disabled`: roles/web-app-mediawiki/templates/oidc.php.j2:80-86
- GitLab `sync_profile_attributes`: roles/web-app-gitlab/templates/config/gitlab.yml.j2:70-71
- Discourse `auth_overrides_*` and `email_editable`: roles/web-app-discourse/files/ruby/apply_settings.rb:29-32
- Gitea `EXTERNAL_USER_DISABLE_FEATURES`: roles/web-app-gitea/templates/env.j2:98
- Nextcloud `allow_user_to_change_display_name`, oidc_login flavour only: roles/web-app-nextcloud/templates/config/oidc.config.php.j2:11
- Nextcloud LDAP-mapped read-only fields: roles/web-app-nextcloud/meta/addons/user_ldap.yml:59-84
- OpenCloud read-only LDAP and account-edit link to Keycloak: roles/web-app-opencloud/templates/env.j2:41,62
- Keycloak `editUsernameAllowed: false`: roles/web-app-keycloak/templates/import/realm.json.j2:38
- ejabberd vCards from LDAP: roles/web-svc-xmpp/templates/configuration.yml.j2:79-81
- Client-side injection carrier (page only, needs a server guard per app): roles/web-app-suitecrm/templates/javascript.js.j2:2

Open classification:

- web-app-opentalk: no profile-sync code in the role; the docs do not say whether later logins refresh names, email, avatar or groups.
- web-app-pretix: the pinned pretix-oidc 2.3.1 source could not be fetched, so the full-name overwrite is unknown.
- web-app-mailu: later-login behaviour of the heviat OIDC fork is unverified (Mailu EOL).
- web-app-discourse: how the login refresh of associated groups interacts with manual membership is unverified.
- web-app-mattermost: the email lock for GitLab-slot users is not confirmed upstream.
- web-app-nextcloud: whether phone, address and picture claims arrive in the sociallogin flavour with scope `openid groups` is unproven.
- web-app-openwebui: whether the LDAP login overwrites name or email is unverified.
- web-app-semaphore: whether the login itself overwrites name and email, and whether external users can edit their own profile, are unverified.
- web-app-taiga: the pinned ref differs from the README claim, and the LDAP plugin 0.5.0 source is unconfirmed.
- web-app-funkwhale: whether first name, last name and username are editable is unverified.
- web-app-xwiki: only the master source of the OIDC authenticator was read, not the pinned version.
- web-app-espocrm: own-profile editability is not confirmed upstream.
- web-app-odoo: own-profile editability is not confirmed upstream.
- web-app-openproject: own-profile editability for LDAP users is not confirmed upstream.
- web-app-kix: which roles may edit their own contact record is not confirmed upstream.
- web-app-baserow: email editability is unverified.
- web-app-n8n: whether an email change needs the password the user never saw is unverified.
- web-app-jitsi: whether a new token join replaces a name changed in the browser is unverified.
- web-app-checkmk: whether the user's own profile page respects the LDAP lock is unverified.
- web-app-gitea: the per-login re-sync of the admin flag comes from helper functions; the function that applies it was not read.
- web-app-wordpress: nickname set only at creation is unverified at the pinned plugin version.

## Acceptance Criteria

### Inventory

- [x] This requirement holds a table with one row per application with SSO, naming each user-editable profile field, whether the next SSO login overwrites it, whether the application writes it back, and the chosen treatment.
- [x] The table covers at least name, email, username, language, time zone, avatar, address and group membership.

### Treatment

- [ ] Every field the inventory marks as overwritten and not written back is either written back to Keycloak or LDAP, or rendered read-only.
- [x] Each role declares its locked fields in one config key, and one shared mechanism renders the lock and the warning for every role that uses it (`services.sso.profile.locked` in `roles/web-app-grafana/meta/services.yml:12`, `roles/web-app-joomla/meta/services.yml:11` and `roles/web-app-wordpress/meta/services.yml:13`; the server guards read the same key through `roles/web-app-joomla/templates/env.j2:40` and `roles/web-app-wordpress/templates/env.j2:21`; each role's `templates/javascript.js.j2:1` includes `roles/sys-front-inj-javascript/templates/profile_lock.js.j2:2`; proven by `tests/lint/ansible/roles/meta/test_sso_profile_lock.py:647`, `tests/unit/python/roles/sys-front-inj-javascript/test_profile_lock.py`, `tests/unit/python/roles/web-app-joomla/test_profile_lock_fields.py` and `tests/unit/python/roles/web-app-wordpress/test_profile_lock_fields.py`).
- [ ] The warning text comes from the i18n catalog and appears in the user's language.
- [ ] A locked field cannot be changed by submitting the form directly, not only in the rendered page.
- [x] Joomla renders name, username and email read-only for SSO users and still lets the break-glass administrator edit them.
- [ ] A field written back appears changed in Keycloak after the user saves it in the application.

### Tests

- [ ] A lint fails when a role with SSO declares neither write-back nor a lock for a field the inventory lists as overwritten.
- [ ] A Playwright spec per treated application asserts either the read-only state with its warning, or the changed value in Keycloak after saving.
