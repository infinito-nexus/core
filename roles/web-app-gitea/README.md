# Gitea

## Description

Boost your development journey with Gitea, a lightweight and energetic self-hosted Git service that offers efficient code collaboration, intuitive version control, and an agile environment for your projects. Ignite your coding spirit, innovate faster, and code with confidence!

## Overview

This role deploys Gitea using Docker. It automates the setup and update processes for your self-hosted Git service, integrating with a central MariaDB for the database. With functionalities for updating, recreating the container, variable management, database access, and shell access to the application container, this role streamlines the management of your Gitea instance. With Hermes Agent or OpenClaw deployed alongside it, the role adds a `gitea-mcp` sidecar and declares it as the MCP server of the deployment: an internal `/mcp` endpoint on the container network plus the Gitea personal access token that MCP clients present.

## Features

- **Lightweight and Fast:** Enjoy a minimal yet efficient Git service tailored for development teams.
- **Efficient Code Collaboration:** Manage repositories and workflows with an intuitive interface.
- **Automated Updates & Re-creation:** Simplify maintenance with automated update and container recreation procedures.
- **Built-in Database Access:** Seamlessly interact with the underlying MariaDB for your Git service.
- **Integrated Configuration:** Easily manage settings via environment variables and Docker Compose templates.
- **Patched OAuth2 callback:** The role builds `gitea_custom` instead of running `gitea/gitea` unchanged. The role [Dockerfile](./files/Dockerfile) compiles the backend from the `gitea-src` tarball of the pinned release with every patch in `GITEA_PATCH_FILES` applied, and replaces `/app/gitea/gitea` in the pinned upstream image. [oauth2/redirect-uri-public-url.patch](./files/patch/oauth2/redirect-uri-public-url.patch) takes the OAuth2 callback URL from the public URL the request arrived on instead of `ROOT_URL`, so an SSO sign-in started on the onion vhost returns to the onion callback. Drop that patch once a Gitea release carries the change.
- **Account linking by name only:** [oauth2/account-linking-by-name.patch](./files/patch/oauth2/account-linking-by-name.patch) removes the primary-email step of `ACCOUNT_LINKING=auto`, so an SSO sign-in links only to the account whose name equals its `preferred_username`; a collision on email alone is refused on the sign-in page.
- **Role Mapping:** Every realm user signs in as a regular Gitea user. Members of the `administrator` role group become Gitea administrators and members of the `restricted` role group become restricted users at each sign-in, through the LDAP admin and restricted filters and through the admin and restricted groups of the OIDC source, which reads the groups claim.
- **Directory Profile:** The LDAP source syncs name, mail, SSH keys and the `jpegPhoto` avatar, and accounts from LDAP or OIDC cannot change their username or full name or delete themselves in Gitea.
- **Login methods:** Each sign-in method follows `services.gitea.login.method.<method>.enabled` in `meta/services.yml`:
  - `sso`: the Keycloak OAuth source (`tasks/setup/oidc.yml`, removed by `tasks/cleanup/oidc.yml` when off). With it on, `[oauth2_client] ENABLE_AUTO_REGISTRATION=true` creates the Gitea account at the first sign-in and `ACCOUNT_LINKING=auto` links a Keycloak identity to the existing account of the same username, so directory accounts synced by the LDAP source and the platform administrator sign in through Keycloak without a link page.
  - `native` and `ldap`: `[service] ENABLE_PASSWORD_SIGNIN_FORM`, on when either is on. The form is shared: local and LDAP accounts sign in through the same form, and Gitea cannot refuse local accounts while LDAP accounts stay allowed. The LDAP source itself follows the `ldap` service and keeps syncing directory profiles in every mode.
  - `2fa`: `[admin] USER_DISABLED_FEATURES=manage_mfa` while off, so no account can enroll TOTP or security keys. While on, `login.method.2fa.enforced: true` sets `[security] TWO_FACTOR_AUTH=enforced`: an account without a second factor still signs in, but reaches no repository by web or API, the platform administrator included, and every page points it to the enrollment until it enrolls one. Variant 2 keeps the enforcement on, so [test-2fa-enrollment.js](./files/playwright/test-2fa-enrollment.js) proves this with a probe account, and variants 0 and 1 run its control without the enforcement. The administrator API and the `gitea admin` CLI stay open under the enforcement. The role's default is `false`, so Gitea only offers the second factor: enforcement takes repository access from every individual account without one, token requests included, and the MCP account the deploy provisions has none. An inventory that enforces it loses the MCP server's repository tools. While `2fa` and `passkey` are both off, `manage_mfa` is disabled and the environment sets `TWO_FACTOR_AUTH` empty, because any enforcement would then lock out every account that cannot enroll a second factor. While `2fa` is off and `passkey` is on, the environment carries no `TWO_FACTOR_AUTH`, so the deploy leaves that setting as an admin set it.
  - `passkey`: `[service] ENABLE_PASSKEY_AUTHENTICATION`.
  - `openid2`: `[openid] ENABLE_OPENID_SIGNIN` and `ENABLE_OPENID_SIGNUP` (OpenID 2.0, not the Keycloak source).
  - `registration`: `[service] DISABLE_REGISTRATION` and `ALLOW_ONLY_EXTERNAL_REGISTRATION`. With SSO on and registration off, only the OAuth source registers accounts and the navbar offers no Register entry.
  - With only `sso` on, Gitea redirects `/user/login` straight to the Keycloak source and never renders its own sign-in page.
- **Break-glass:** With the form off, the platform administrator keeps the HTTP API through basic authentication with the local password (`[service] ENABLE_BASIC_AUTHENTICATION` stays on) and the `gitea admin user` CLI inside the container. Setting `services.gitea.login.method.native.enabled: true` in the inventory brings the form back.
- **MCP server contract:** Declares the `/mcp` path over streamable HTTP as an internal, bearer-token-authenticated endpoint served by the `svc-ai-mcp-adapter` instance running as compose service `giteamcp`. The adapter listens on container port `8080` and is never published to a host port or fronted by the public reverse proxy; clients reach it as `http://giteamcp:8080/mcp` on the container network. It is off by default and switches on only where Hermes Agent or OpenClaw is part of the deployment.
- **Adapter in front of the sidecar:** The `gitea-mcp` sidecar runs as compose service `giteamcpupstream` on the role's own network only, so nothing but the adapter reaches it. It answers `initialize` and `tools/list` to any caller because it holds no credential of its own and expects each client to supply a Gitea token per request, which makes it unsafe to expose directly. The adapter is what authenticates: a client presents the `mcp_bearer` credential and is refused with 401 otherwise, and the adapter presents the minted Gitea token upstream via `ADAPTER_UPSTREAM_KEY`.
- **Administrator-issued token:** The role mints a Gitea personal access token named `gitea-mcp` for the `administrator` account with the read-only scope set `read:repository,read:issue,read:user,read:organization,read:notification`, and persists it in the token store MCP clients read. Every deploy asks the API whether the stored token still authenticates, revokes the stale entry under that name, and re-mints when the API rejects it. The deploy fails if the fresh token is rejected too.
- **Read-only tool surface:** The sidecar runs with `-r` and `GITEA_READONLY=true`, which hides every write tool. What remains are the read categories `user`, `repository`, `issue`, `pull_request`, `search`, `file`, `branch`, `tag`, `commit` and `release`, pinned through `GITEA_SCOPES`. Making the instance mutate anything through MCP is an explicit operator change to the command line and the token scopes.
- **Handshake verified against the sidecar:** After minting, the deploy sends a JSON-RPC `initialize` to `http://giteamcpupstream:8080/mcp` with that bearer and fails when the endpoint does not answer.
- **Contract probe:** The `svc-ai-mcp-adapter` probe presents the `mcp_bearer`, asserts the served tool surface matches the pinned contract, and separately asserts that an unauthenticated `initialize` is refused with a 4xx and discloses no tool inventory.
- **Pinned tool surface:** `files/mcp/tools.json` holds the 24 read-only tools captured from the sidecar, pinned twice: `tools.schema_sha256` over the parsed mapping the adapter rehashes at startup, and `adapter.specification_sha256` over the file bytes.

## Further Resources

- [Gitea Official Website](https://gitea.io/)
- [Gitea LDAP integration](https://docs.gitea.com/administration/authentication/)
- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/TM24gqSHJCqMMQDhS1kxyq)

## MCP Server

Gitea has no built-in MCP server. The role runs the project-owned `gitea-mcp`
package as a sidecar container next to Gitea and points it at the instance over
the container network. Because that sidecar authenticates nothing itself, the
`svc-ai-mcp-adapter` instance sits in front of it and is what clients address.

### Endpoint

| Property | Value |
| --- | --- |
| Transport | Streamable HTTP |
| URL | `http://giteamcp:8080/mcp` |
| Upstream | `http://giteamcpupstream:8080/mcp`, own network only |
| Exposure | `internal`, container network only |
| Implementation | `adapter` |

The image ships no `ENTRYPOINT`, so the compose `command` carries the binary
path followed by its flags.

### Auth

Clients present a Gitea personal access token as `Authorization: Bearer <token>`.
The token is issued against the administrator account and kept in
`sys-token-store`. Its `auth_subject` is `administrator`, so MCP calls run with
administrator rights rather than as the requesting user.

### Tool categories

The sidecar starts with `-r` (read-only) and a scope list covering user,
repository, issue, pull request, search, file, branch, tag, commit and release.

### Default state

Off. `mcp.enabled` is false unless `web-app-hermes`, `web-app-openclaw` or
`web-app-openwebui` is deployed alongside.

### Public vhost

The sidecar is never routed publicly. A bearerless probe of `/mcp` on the public
vhost is answered with an SSO redirect, never with an MCP response.

### How to disable

Remove the MCP client roles from the deployment, or pin
`mcp.enabled: false` for this role. The `giteamcp` service is then not
rendered into the compose file.

## Workspace repositories

An inventory that runs the store sets `services.gitea.workspaces.enabled: true` in its `web-app-gitea` configuration; the role's own value is `false`.
With the switch on, every deploy converges:

- **The organization `workspaces`** (`services.gitea.workspaces.organization`), private, created through `POST /admin/users/store/orgs` so that `store` is the only member of its `Owners` team. Its teams cannot create repositories, so only its owner can.
- **The store account `store`** (`services.gitea.workspaces.store.username`), created with `gitea admin user create --user-type bot`. A bot account has no password at all, so nothing is kept, and the OAuth2 account linking of [account-linking-by-name.patch](./files/patch/oauth2/account-linking-by-name.patch) only links individual users, so an SSO sign-in named `store` never reaches it. The deploy takes away the site admin flag and sets the account's own repository limit to 0, so it cannot create a repository in its own namespace. It is the only owner of `workspaces` and a member of nothing else. A `store` account the deploy did not create, an individual one or one that signs in through an external source, stops the deploy before it changes anything.
- **The store token**, which only `rotate store credentials` mints, through [tasks/utils/store_token.yml](./tasks/utils/store_token.yml). It carries exactly the scopes `write:organization`, `write:repository` and `read:user` (`services.gitea.workspaces.store.scopes`). It comes out of `gitea admin user generate-access-token --raw` on stdout, never on an argv, under `no_log`, and is named `store-<expires_at>`. The rotation writes it to `platform/data/store/gitea` as the two fields `token` and `expires_at`. Gitea gives an access token no expiry of its own, so only the rotation ends a token: each run deletes every store token whose name carries an `expires_at` that has passed, and no other token.

Through the API, the store creates per workspace the repository `workspaces/ws-<id>` and the team `ws-<id>`, adds its own write deploy key and the read-only deploy key whose public half `workspace apply` hands it as `read_key`, and syncs the team's members. Deploy keys work over SSH only, on Gitea's SSH port; the HTTPS remote stays for members.

### Workspace access

- **The team `ws-<id>`** has `permission` `read`, `units_map` `{"repo.code": "read"}` with every other unit `none`, `includes_all_repositories` false and `can_create_org_repo` false, and holds the workspace's repository only.
- **Its members** are the users in the organization groups `Owner`, `Admin`, `Operator` and `Viewer` of the workspace. A user who is only in `Billing` is not in the team, so the private repository stays hidden from them. A member reaches the inventory only through the store, which writes `main` alone.
- **Exactly two deploy keys and no collaborator:** the store's writing key and the read-only key of `workspace apply`; a member reaches the repository through the team only.
- **Every deploy checks it.** After the converge, [tasks/utils/workspaces/check.yml](./tasks/utils/workspaces/check.yml) reads every repository and team of `workspaces` and the account `store` from the database ([files/sql/workspaces-snapshot.sql](./files/sql/workspaces-snapshot.sql)) and fails the deploy, naming the object, when `store` is a site admin, may create a repository of its own, owns one, belongs to another organization or team, or signs in through an external source; when `Owners` holds another member; when a team holds more than `read`, another unit than `repo.code`, all repositories or the right to create one; or when a repository has a third deploy key, a second writing key or a collaborator. A widened grant, by a leaked store token or by hand, therefore stops the next platform deploy.

## LDAP coverage

With `ldap` on and Gitea's own LDAP login method on, [`files/playwright/test-rbac-ldap.js`](./files/playwright/test-rbac-ldap.js) signs `biber` in through the LDAP authentication source and asserts the administrator and restricted role group mappings. The administrator persona is the local account that [`tasks/01_manager_ops.yml`](./tasks/01_manager_ops.yml) creates with `gitea admin user create`, and Gitea checks its local password, never the LDAP source, so no administrator LDAP scenario exists.

## Persona contract opt-outs

With SSO on, the shared `biber` and `administrator` persona journeys run: the OAuth source registers or auto-links their Gitea accounts at the first sign-in.
Without SSO they are opted out via `PERSONA_BIBER_BLOCKED` / `PERSONA_ADMINISTRATOR_BLOCKED` in `templates/playwright.env.j2`, because the shared native persona path probes `/`, `/login`, `/admin` and `/accounts/login/` for a password field while Gitea serves its form at `/user/login` only.
