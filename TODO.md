# Todos

- Implement multi language
- Implement rbac administration interface
- Enable IP6 for docker.
- backup docker to local für ca optimieren
- Drop the `php_memory_unlimited` mount ([memory-unlimited.ini](roles/sys-svc-compose-php/files/memory-unlimited.ini), `memory_limit = -1`) from each role whose image ships PHP 8.2.35, 8.3.36, 8.4.27, 8.5.12 or later, and the file, its install task, `FILE_PHP_MEMORY_UNLIMITED_INI` and [its lint](tests/lint/ansible/roles/meta/test_php_memory_unlimited_reaches_fpm.py) once no role mounts it. It is the interim mitigation for CVE-2026-109618 and overrides the per-role `service_memory_mb` share, so a single request can exhaust the container instead of hitting a PHP limit. Still mounted by `web-app-magento` (`markoshust/magento-php:8.4-fpm`, PHP 8.4.21) and `web-app-mailu` (`ghcr.io/mailu/webmail:2024.06`, which every flavor runs). `web-app-fusiondirectory` (`nfrastack/fusiondirectory:1.5`, PHP 7.4.33 on Alpine 3.15, end of life and never patched) carries it as `PHP_MEMORY_LIMIT=-1` in `templates/env.j2` instead (the image's pool sets `php_admin_value[memory_limit]` from it, so a conf.d ini cannot reach FPM) and drops it under the same rule. `web-app-magento` keeps the 756M its `nginx.conf.sample` (`PHP_VALUE`) and `pub/.user.ini` set and keeps `post_max_size` below a quarter of that limit.
- Fork [rpardini/docker-registry-proxy](https://github.com/rpardini/docker-registry-proxy) and teach the bundled nginx to handle GCP Artifact Registry redirect URLs (`/artifacts-downloads/namespaces/<ns>/repositories/<repo>/downloads/<token>`). Currently `gcr.io` blob pulls are bypassed via `NO_PROXY=…,gcr.io,storage.googleapis.com,googleusercontent.com` in [compose/registry-cache/proxy.conf](compose/registry-cache/proxy.conf), which is a workaround that disables caching for those registries. Long-term: rebase upstream's `proxy.conf` / `sub_filter` rules to recognise the new redirect shape, ship the fix in our fork, point `compose/registry-cache/Dockerfile` (or its image tag) at the fork, and drop the `NO_PROXY` bypass.
- Move the self-built Python bases of `svc-ai-s1` and `svc-ai-nllb-engine` to the current Python minor and drop their `# nocheck: docker-version` hold in [svc-ai-s1](roles/svc-ai-s1/meta/services.yml) and [svc-ai-nllb-engine](roles/svc-ai-nllb-engine/meta/services.yml). `svc-ai-s1` stays on `3.12-slim` while `jeff` at the pinned ref requires Python `>=3.12,<3.13`; `svc-ai-nllb-engine` stays on `3.13-slim` while [build.sh](roles/svc-ai-nllb-engine/files/shell/build.sh) pins `torch==2.9.1`, which ships no cp315 wheel. Bump `jeff` and `torch` first, then the base; the updater's 3.15.2 bump broke both builds in main run 43131801262 (Discourse#1, translate#2).

## IAM line follow-ups (2026-11-01)

Open work of `feature/iam-profile-rbac` when the line stopped taking new assignments.

- Gate and roundtrip: `make quality-high` on the IAM tree, then the compose and swarm roundtrip. Live proofs still owed there: the Semaphore foreign deploy (needs the host disk below 90 %, an earlier PASS 1 failed on `hlth-disc-space` of the target), the shared target reset before every pass (920688de83), the Grafana profile-lock check in German (`test-profile-lock.js`), Gitea, and the runner build measurement of a provider-only Semaphore round.
- Uncommitted IAM bundles to commit after the gate, each on its own: the Keycloak email policy, the WordPress `site-owner` sites with served domains, the WordPress multisite spec fixes (multisite plugin screens, REST nonce, onion tenants, `script-src-attr`), the bootstrap admin name (`keycloakbootstrap`, `accounts: []`), the browser proxy bypass for served domains, the SSO linking audit docs, and the access-request service.
- Profile lock config SPOT: committed (e0f6cee93f, d9402c186a); unit tests pass (`make test-unit-php` 277 OK, the Python tests with a negative control). Still open are the deploys of `web-app-joomla` and `web-app-wordpress` with `test-profile-lock.js` and `test-profile-sync.js`, and the negative control of the PHP tests, which needs a PHP runtime: with `infinito_oidc_profile_write_is_guarded` returning `false`, `testTheConfiguredKeysKeepEveryStoredProfileFieldOfAnOidcAccount` and `testARemovedKeyUnlocksItsFieldOnEveryWrite` of `InfinitoOidcRbacMapperTest.php` must fail; with `self::MANAGED_PARAM` dropped from the params loop of `Keycloak::changedManagedFields`, `testEveryManagedColumnAndParamIsReportedWhenItChanges` and `testAChangeOfAnUnlockedFieldPassesWhileTheMarkerStaysGuarded` of `KeycloakTest.php` must fail.
- Bootstrap admin name: the live drill on a master realm seeded like production proved the fix (before: the bootstrap login with `kcbootstrap` answered `invalid_grant`; after the deploy the env names `keycloakbootstrap` and that login succeeds, `/tmp/kc-bootstrap-drill-n1.log`, `/tmp/kc-bootstrap-drill-p2.log`). Still open: the recovery run (permanent-admin password randomized, the deploy must recover through `keycloakbootstrap`) and an idempotence run, the commit, and the same change on `feature/agents`, which still names it `kcbootstrap`. The drill deploy also ended red at `hlth-container` in `sys-service-terminator` (`/tmp/kc-bootstrap-drill-1.log:66134`), unrelated to the fix and not triaged.
- Access request from the SSO 403 page: apply the frozen edits (catalog extract contexts, realm `adminPermissionsEnabled` and admin events, `realm_management` in the Keycloak RBAC meta, the fine-grained permission provisioning task, the oauth2-proxy custom template directory with its 403 error page and `email_domains`, the `PORT_BANDS.local.http` end from 8107 to 8199, the Zammad bot wiring), fix the lint findings (env keys `ACCESS_REQUEST_BASE_URL`, `KEPT_ROLE_JSON`, `DROPPED_ROLE_JSON` unused, mirrored unit tests, onion timeouts), then a deploy proof.
- Remote LiteLLM gateway: the spec draft sits uncommitted in the IAM tree. Open operator questions: failure behaviour when the mesh or the gateway is down (the draft says fail loud), key distribution between hosts, one key per host or per consumer, where a consuming host reads the chat model, a source filter on the mesh port, swarm, the hub forwarding dependency of the WireGuard mesh, and Open WebUI model grants on consuming hosts. Implementation waits for the operator's word; until then every host keeps its own `svc-ai-litellm`.
- Raspberry Pi host `hotelserver` (Pi 5, 8 GB, SSD, Raspberry Pi OS aarch64, LUKS root): Jellyfin with media on the SSD, retro gaming (`dsk-retroarch` on Raspberry Pi OS unverified), a local agent (Hermes or OpenClaw) using an auto-detected 360° camera, a microphone and a projector over HDMI and CEC. Analysis of 2026-11-01 (read-only, nothing built):
  - Fit: the pinned images of `web-app-jellyfin`, `web-app-hermes`, `web-app-openclaw`, `svc-ai-litellm` and the base server roles publish linux/arm64. Jellyfin transcodes in software only and keeps the media in a named volume without `backup: false`. `dsk-retroarch` installs only the `retroarch` packages (`tasks/main.yml` is empty: no cores, autostart, projector output or controllers).
  - Agent: Hermes (non-root, OpenAI chat-completions API, MCP servers tested at deploy, preferred by `svc-ai-robot`); its 64k context needs a remote model, and its default model must be set by hand.
  - Sandbox: Kata needs `/dev/kvm`, so the Pi runs gVisor `runsc`, which is unproven on the Pi 5 16K-page kernel (`kernel_2712.img`); check `getconf PAGE_SIZE`, `CONFIG_ARM64_VA_BITS` and a `runsc` hello-world first, with `kernel=kernel8.img` as fallback.
  - Devices: passing devices into the agent drops its runtime and is refused by the `svc-ai-robot` guard next to another `web-app-*`; build small device containers behind `svc-ai-mcp-adapter` instead (`drv-raspberrypi` for udev names and `config.txt`, `svc-ai-mcp-camera` with auto-detection over `/dev/v4l/by-id`, `svc-ai-mcp-cec` over `cec-ctl`, `svc-ai-voice` with wake word, whisper and Piper over PipeWire), plus a narrow allowance for state-changing tools in Hermes' read-only MCP client and one owner for the HDMI output.
  - LUKS: the update role never reboots Debian (only the Arch path of 2d04085e8b does), so a power cut or manual reboot stops at the passphrase prompt; recommended `dropbear-initramfs` with `cryptroot-unlock` over SSH (needs Ethernet) plus a reboot-pending alert, clevis and tang later.
  - Network: a394d4bf6b, e810319d00, 2d04085e8b and its base cc6c852748 are not on IAM; cherry-pick those four rather than merge the alphaserver line (66 more commits); leave `applications.update.services.update.reboot.enabled` out of the inventory until 2d04085e8b lands. echoserver is not in the WireGuard mesh yet.
  - Inventory: `hotelserver` in `svc-net-wireguard`, `svc-ai-litellm`, `svc-opt-swapfile`, `web-app-jellyfin`, `web-app-hermes`, `dsk-retroarch`, host_vars modelled on alphaserver, and a hotelserver peer on galaxyserver's hub interface.
  - Operator questions: Raspberry Pi OS Lite or Desktop and its release; Ethernet; dropbear or tang, and whether alphaserver is encrypted; domain and remote reach of Jellyfin; playback on the projector or other devices; media volume or host path and backup; the provider key for the interim LiteLLM; camera, microphone and speaker models and connections; projector CEC or PJLink; controllers; wake word or push-to-talk and what the agent may switch; cherry-pick or merge.
- Bluesky handle form (`fix/web-app-bluesky/handle-form-origin`): move the texts of `messages.js` into the core catalogs (register the file in `utils/i18n/extract.py`, `make i18n-extract domain=core`) in a catalog commit of its own; the handoff, 401, 409 and 500 texts of the broker are still inline.
- Dashboard card icons (`fix/web-app-dashboard/monochrome-card-icons`): `files/playwright/test-icons.js` still expects the simpleicons host to start with `icon.`, which fails against an inventory that renames it.
- Header-trust hotfix: the compose run of the nine forged-identity specs, the swarm run, the PR linking #1089, and on production the incident check and the session invalidation of the header-trust apps.
- ERPNext guard app (email takeover hotfix part 2): a store-i18n stack proof (deploy plus a takeover attempt) before its commit; production inventory `extra_roles` for the API bot (`Sales Master Manager`, `Item Manager`).
- #1326 runtime vulnerability scans: add the Grafana dashboard, the alert rule and the Wazuh localfile when the line merges it.

## Testing

- re-run with different credentials/configuration
- run over all distros for each app

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

- **joomla local-login fallback spec** — `test-oidc-fallback.js` (the
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
  likelihood); discourse is now confirmed and pinned (run 33445831564, job
  Nextcloud#7); jenkins, jira, confluence, odoo, openwebui,
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
