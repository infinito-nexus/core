# To-dos

- Ask upstream to trust an identity header and the client address from a reverse proxy, then drop the second login and the shared login lockout described in the README.
- Ask upstream to set the `Secure` cookie flag behind a TLS-terminating proxy.
- Report upstream that `safeNext` in `server/server.mjs` accepts `/\host`, which browsers read as `//host` after login.
- Add a per-user storage quota once upstream offers one; until then `keep_days` and `max_queued_per_user` bound the disk use.
- The oauth2 gate returns to `/` after the Keycloak login instead of the requested `/renders/`, because `roles/web-app-keycloak/templates/sso_proxy/endpoint.conf.j2` passes no `X-Auth-Request-Redirect`; fix it there for every gated role.
- Unblock the administrator persona if upstream adds an admin tier.
- Serve the map tiles from a local VersaTiles server instead of `tiles.versatiles.org`.
- Pin a semver tag once upstream publishes `v*-server` releases.
