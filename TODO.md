# Todos

- Implement multi language
- Implement rbac administration interface
- Enable IP6 for docker.
- backup docker to local für ca optimieren
- Fork [rpardini/docker-registry-proxy](https://github.com/rpardini/docker-registry-proxy) and teach the bundled nginx to handle GCP Artifact Registry redirect URLs (`/artifacts-downloads/namespaces/<ns>/repositories/<repo>/downloads/<token>`). Currently `gcr.io` blob pulls are bypassed via `NO_PROXY=…,gcr.io,storage.googleapis.com,googleusercontent.com` in [compose/registry-cache/proxy.conf](compose/registry-cache/proxy.conf), which is a workaround that disables caching for those registries. Long-term: rebase upstream's `proxy.conf` / `sub_filter` rules to recognise the new redirect shape, ship the fix in our fork, point `compose/registry-cache/Dockerfile` (or its image tag) at the fork, and drop the `NO_PROXY` bypass.

## Testing

- re-run with different credentials/configuration
- run over all distros for each app
- msg: can not use content with a dir as dest for NGINX multi distro
- split service database to postgres and mariadb

## Onion e2e (feature/svc-net-tor) — remaining failures

Status after deploy-matrix run 29657147883 (commit 407b8a8a1). Every fixable
failure class from that run is committed (hlth-csp onion-sibling skip,
onion-aware Playwright request timeouts + lint guard, joomla server-side OIDC
reachability). The items below are the ones that are NOT fixed yet. Runs
31756400129 and 31756560361 have since moved several of them; entries corrected
against those runs say so inline.

- **https on the onion IdP — investigated and REJECTED, do not re-derive.** OIDC
  Discovery / RFC 8414 want an https issuer, and an onion-exclusive Keycloak has
  none, so strict client libraries refuse it. Serving TLS on the onion is blocked
  on four independent things, in this order: (1) `roles/svc-net-tor/templates/torrc.j2`
  publishes only `HiddenServicePort 80`, and no role declares 443 in
  `ports.public`/`ports.local`, so `lookup('tor_ports')` can never emit it —
  flipping TLS on first makes Keycloak unreachable over Tor entirely, because
  `nginx_ssl_header.j2` is one if/else and port 80 disappears; (2)
  `roles/sys-front-tls-selfsigned/tasks/00_core.yml` writes an unguarded CN, which
  overflows X.509's 64-byte cap on a 62-char v3 onion — `group_vars/all/02_tls.yml`
  already guards exactly this for the root CA and nowhere else; (3)
  `nginx_ssl_header.j2` emits HSTS in the same branch, and browsers offer no
  click-through on an HSTS host with an untrusted chain, so a self-signed interim
  locks real users out while staying invisible to Playwright's
  `ignoreHTTPSErrors`; (4) it fixes zero libcurl consumers, because RFC 7686
  refusal happens at name resolution and is scheme-independent. Unblocking needs a
  CA that issues for v3 `.onion` (HARICA, CA/B Forum ballot 144) — procurement,
  not code. Until then the per-consumer fixes stand: SOCKS proxy for libcurl
  clients. peertube is no longer among them - it is a clearnet-only role.

- **dual-family providers** — the one real remaining design gap. On a CI onion
  node, tor-enabled providers (e.g. mastodon) are onion-exclusive: their domain
  list contains only the `.onion` canonical, no clearnet sibling. The
  family-alignment resolver (`utils/tls_common.py:align_domain_to_consumer`,
  wired into `plugins/lookup/tls.py`) correctly bails in that case, so a
  clearnet-pinned consumer still receives an onion URL it can neither resolve
  nor reach. First hard evidence: `web-app-fediwall` variant 2 (tor=false)
  renders `microblog.<onion>` into `wall-config.json.servers`; the clearnet
  browser (no SOCKS) times out waiting for mastodon wall items
  (`test-walls-surface-posts.js:24`, deterministic across retries). The same
  class is expected to keep `web-app-bigbluebutton`, `web-app-nextcloud`,
  `web-app-opentalk` and `web-app-jitsi` red (clearnet-pinned apps whose peer
  refs — OIDC/cdn/matomo/logout — resolve onion-primary). Fix direction:
  providers must publish BOTH families (clearnet sibling alongside the onion
  canonical) so the resolver has something to align to; includes re-applying
  the deferred `KC_HOSTNAME` onion-gate for Keycloak that was dropped from the
  earlier bundle because it is only needed once dual-family exists.
- **joomla local-login fallback spec** — `test-oidc-fallback.js:52` (the
  `?fallback=local` emergency hatch: local Joomla admin form login must reach
  the control panel). Root cause UNCONFIRMED. It is independent of the fixed
  OIDC-login spec: the fallback path short-circuits before the plugin's
  server-side discovery, so the committed `extra_hosts` fix does not cover it.
  The `secure => true` sticky-cookie hypothesis was rejected (`.onion` is a
  potentially-trustworthy origin and the e2e Firefox sets
  `dom.securecontext.allowlist_onions`, so Secure cookies are accepted over
  plain-http onion). Next step when it fails again post-fix: isolate the
  post-submit URL — Keycloak redirect (cookie lost) vs. form reject vs. slow
  control-panel render.
- **matomo container health flake (checkmk batch)** — in the checkmk job the
  4th deploy play failed at `Wait for Matomo container to be healthy` with
  `container inspect: map has no entry for key "State"` for the whole retry
  window (container started, then vanished — likely crash + prune). Plays 1–3
  in the SAME job deployed matomo healthy, so classified transient
  (resource/prune pressure after ~3h). No code fix derivable. If it recurs,
  investigate as a real matomo crash/OOM (container logs, mem_limit).
- **server-side OIDC reachability candidates** — joomla failed because its app
  container performs server-side OIDC discovery against `http://auth.<onion>`
  without an `extra_hosts` mapping. Roles with the same mechanic and no
  `container_extra_hosts` lookup yet (fix is the same one-line lookup,
  apply on CI evidence): wordpress (daggerhart plugin) and mediawiki
  (PluggableAuth) are structurally identical PHP in-app plugins (high
  likelihood); discourse, jenkins, jira, confluence, odoo, openwebui,
  pretix, zammad, semaphore, jellyfin, listmonk, xwiki, mastodon consume the
  issuer server-side too (unverified network path). oauth2-proxy-based apps
  are NOT affected (proven green: prometheus admin SSO). Two names have left
  this list on evidence: mobilizon got the lookup in 0e39f3fad after its
  code-to-token call raised OAuth2.Error Connection refused twenty-four times,
  and gitlab was NEVER a member - run 31756560361 shows it resolving and
  connecting (peeraddr=172.30.0.10:443); its failure was the openid_connect gem
  rebuilding the discovery URL over https regardless of the issuer scheme,
  fixed in 2389b6e38.
- **baseline exclusions** — `web-app-fider` and `web-app-bookwyrm` (also
  keycloak-job, n8n) were red before the tor branch and stay out of scope for
  it; bookwyrm fails its oauth2 trusted-header session spec, fider its
  baseline. Fix separately from the onion work. espocrm has left this list: its
  onion variant failed in the shared admin persona (fixed in b97cf8888) and its
  clearnet variant returns HTTP 500 on GET /api/v1/App/user, cause still open.
- **test-development environment jobs** — all 5 distro jobs
  (arch, debian, ubuntu, fedora, centos) hit the 4h30m cap under congestion
  while still progressing (playwright image pull). Environmental, no code fix -
  distinct from the distro sweep's own budget, which did have one: 508669809
  books a budget SIGKILL as skipped, which ad9222630 had only done for SIGTERM;
  note that onion e2e inherently lengthens the routine (×5 onion timeouts,
  circuit waits), so under congestion these jobs are the first to hit the cap.
