# 074 - Header-trust backends reachable only through openresty

## User Story

As an operator, I want every application that logs a user in from a proxy-set identity header to be reachable only through openresty, and openresty to clear or overwrite that header on every location, so that no client can impersonate a user, for example with `X-Forwarded-Preferred-Username: administrator`.

Implements [infinito-nexus/core#1089](https://github.com/infinito-nexus/core/issues/1089).

## Acceptance Criteria

### Inventory

- [ ] A list in [rbac.md](../contributing/design/iam/rbac.md) names every header-trust role, the header it trusts, the file that trusts it, whether a proxy secret also gates it, and the config key that switches it on. Initial set: `web-app-snipe-it` (secret-gated), `web-app-checkmk`, `web-app-openproject` (secret-gated), `web-app-yourls`, `web-app-bookwyrm`, `web-app-bluesky` login broker, `web-app-baserow`, `web-app-n8n`, `web-app-postmarks`.
- [ ] Each candidate the inventory rejects (`web-app-kix`, `web-app-funkwhale`, `web-app-fusiondirectory`, `web-app-openclaw`, `web-app-akaunting`) is listed with the reason it does not trust a header, or is moved into the list once it does.

### Header strips at openresty

- [ ] Every proxying `location` that a role template renders into a front-proxy vhost includes `roles/sys-svc-proxy/templates/headers/identity_request_strips.conf.j2` or the SSO `following_directives.conf.j2`. That covers health (`/healthz/ready`, `/_live_probe`), API, MCP, websocket, upload, oauth2 and ACL exception paths. `tests/lint/ansible/jinja/test_proxy_location_strips.py::test_proxying_locations_clear_client_identity` enforces it for every role template and `files/**/*.conf` fragment, openresty vhosts with their own `server` block included.
- [ ] `roles/sys-svc-proxy/templates/headers/untrusted_identity_strips.conf.j2` blanks every header any inventoried role trusts. That includes `X-Remote-User` (Checkmk, OpenProject), `Remote-User`, `Remote-Email` and `X-Auth-Request-*`. The header list is `TRUSTED_IDENTITY_HEADERS` in `utils/roles/header_trust.py`, checked by `tests/lint/ansible/roles/test_location_identity_strips.py`.
- [ ] A request to `/healthz/ready` on a header-trust vhost with `X-Forwarded-Preferred-Username: administrator` sets no session cookie and logs nobody in.
- [ ] With SSO switched off after an SSO deploy, a forged `X-Remote-User` on Checkmk logs nobody in.

### Backend ports

- [ ] In swarm, no backend port of a header-trust role answers on any node address from outside the swarm. A probe from a host that is not a swarm node gets no TCP connect on `ports.local.<proto>` of each inventoried role.
- [ ] In swarm, `container_ports` publishes no `ports.local` port carrying a host ip. The decision runs on the effective mode (`compose_mode_force` or `DEPLOYMENT_MODE`). Edge proxy, mail, TURN and SSH ports stay published.
- [ ] Host-side provisioning that today reaches an app through its routing-mesh port in swarm (central Postgres and MariaDB init, OpenLDAP, Fider, the Nextcloud integration addons and the other roles listed in #1089) reaches it through container exec or the overlay instead, so the previous criterion holds without a failing deploy.
- [ ] `web-app-litellm` and `web-app-discourse` reach their backends without a published loopback port in swarm.
- [ ] A lint fails when a `container_ports` term that passes `DOCKER_BIND_HOST` resolves its published port from `ports.public`. The swarm ingress guard in `roles/svc-swarm-node/templates/nftables.conf.j2` exempts public ports, so such a term would stay open.
- [ ] Once `container_ports` publishes no loopback port in swarm, a lint fails for every swarm-rendered `container_ports` term that carries `DOCKER_BIND_HOST` and no exemption.
- [ ] Production compose (no `DOCKER_IN_CONTAINER`) binds every header-trust backend to `127.0.0.1`. A unit test renders each inventoried role's `compose.yml.j2` with `DOCKER_BIND_HOST=127.0.0.1` and asserts no `0.0.0.0` or bare-port binding.
- [ ] The DiD/dev case is decided and documented in [sandbox.md](../contributing/tools/agents/claude/sandbox.md) or the deploy docs. `DOCKER_BIND_HOST` is `0.0.0.0` under `DOCKER_IN_CONTAINER` (`group_vars/all/00_general.yml`) because host-side provisioning reaches apps through `DOCKER_REACH_HOST`, the docker bridge gateway (`roles/sys-svc-container/tasks/00_core.yml`). The outer `compose.yml` publishes no backend port, so the exposure stays inside the outer bridge network. Either a test asserts that `compose.yml` publishes no `ports.local` port, or `DOCKER_BIND_HOST` moves to the bridge gateway.

### End-to-end checks

- [ ] A shared Playwright helper, `probeForgedIdentity` in `roles/test-e2e-playwright/files/personas/utils/forged-identity.js`, forges every trusted header (`X-Forwarded-User`, `X-Forwarded-Preferred-Username`, `X-Forwarded-Email`, `X-Forwarded-Groups`, `Remote-User`, `Remote-Email`, `X-Remote-User`, `X-Auth-Request-*`) against `/`, `/healthz/ready`, each ACL exception path and each API path of a vhost. It asserts that no session cookie is set and that no logged-in page is served. `roles/web-app-postmarks/files/playwright/test-oidc-security.js` is the model.
- [ ] Every inventoried role runs that helper in its Playwright suite, including `web-app-n8n` and `web-app-bluesky`, which have no forged-header spec today. Each role requires `files/playwright/test-forged-identity.js`; `tests/lint/ansible/roles/test_header_trust_forged_identity_spec.py` fails for a role that `utils/roles/header_trust.py` detects as header-trust without it.

### Documentation

- [ ] No role document claims header trust is safe because the port is bound to `127.0.0.1` or to the internal container network. That covers `web-app-postmarks/README.md`, `web-app-postmarks/files/sso/header_auth.js`, `web-app-bookwyrm/files/sso/header_auth.py`, `web-app-n8n/files/javascript/hooks.js` and `web-app-yourls/files/sso/infinito_sso.php`. Each names openresty as the trust boundary and the published port as the residual path.
