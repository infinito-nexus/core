# 061 - Nextcloud Talk high-performance backend from pinned upstream components

## User Story

As an operator, I want the Nextcloud Talk high-performance backend and recording server to run as separate services built from semver-pinned upstream sources, with every configuration file rendered by `web-app-nextcloud`, so that the updater can raise their versions automatically and no upstream start script can overwrite the role's configuration.

## Acceptance Criteria

- [x] `roles/web-app-nextcloud/meta/services.yml` no longer references `nextcloud/aio-talk` or `nextcloud/aio-talk-recording`.
- [x] The signaling server runs as its own service from the upstream `nextcloud-spreed-signaling` project, pinned to a semver version without a `# nocheck: docker-version` marker.
- [x] Janus runs as its own service from an image the role builds from a semver git tag of `meetecho/janus-gateway`.
- [x] NATS runs as its own service from the official `nats` image pinned to a semver version.
- [x] The recording server runs as its own service from an image the role builds from a semver release tag of `nextcloud/nextcloud-talk-recording`.
- [x] The role renders the signaling `server.conf`, `janus.jcfg` and the recording `server.conf`; no file inside an image regenerates or overwrites them at container start.
- [x] The Janus config drift guard in `tasks/01_fullstack.yml` and the `janus_config_drift` filter are removed together with their tests.
- [ ] `utils/update` reports a newer upstream version for each of the four pins, and `tests/lint/ansible/services/test_version_pins_are_watched` passes for them.
- [ ] The public signaling endpoint stays `/standalone-signaling/`, and the Talk admin settings show the pinned signaling version as "Running version" with `chat-relay` not listed as missing.
- [ ] Direct media keeps working: with `services.talk.network_mode: host`, `nat_1_1_mapping` carries the public IP and `test-talk-call-capacity.js` passes.
- [ ] A recording started from a Talk call through the recording server produces a file, verified by a Playwright or CLI test.
- [ ] Each new service has its own healthcheck and resource limits, and in swarm the services Janus shares a network namespace with are placed on the same node.
- [ ] Deploying over an existing `aio-talk` installation removes the old container or swarm service and starts the new services with the existing signaling, TURN and recording secrets in one deploy.
- [x] No secret of the new services appears in a container's argv; secrets reach them through config files or environment.
- [ ] `web-app-nextcloud` with Talk enabled is green in a compose and a swarm roundtrip, including the Talk Playwright specs.
- [x] `roles/web-app-nextcloud/README.md` and `docs/Administration.md` describe the four services, their sources and how a version update reaches them.
