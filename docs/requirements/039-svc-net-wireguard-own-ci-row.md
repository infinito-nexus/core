# 039 - svc-net-wireguard: Test Full Meshes on the Role's Own CI Row

## User Story

As a maintainer, I want the full-mesh WireGuard test to run only on the role's own CI row, so that no Compose app row spends deploy time on WireGuard while every role keeps its WireGuard support in production.

## Acceptance Criteria

- [x] Compose CI rows carry no 🚇 or 🛣️ glyph and never deploy `svc-net-wireguard`; the `vpn` axis covers swarm rows only, as before Compose support.
- [x] `INFINITO_COMPOSE_VPN` and its plumbing are gone.
- [x] `svc-net-wireguard` runs on a host exactly when the host is in the `svc-net-wireguard` group.
- [x] Outside swarm, a host in that group without a mesh is skipped with a visible message; in swarm it still fails hard.
- [x] A role's `meta/tests.yml` can name roles its CLI test requires under `cli.requires`, and `test-e2e-cli` includes them before the test runs.
- [ ] The CLI test of `svc-net-wireguard` requires `sys-svc-container`, and the role's own deploy row runs it to green with no other application deployed.
- [ ] Swarm deploys behave as before.
- [x] Every role keeps its `networks.meshes` field and Compose hosts can still join full meshes in production.
