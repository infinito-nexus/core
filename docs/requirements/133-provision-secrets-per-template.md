# 133 - Provision Secrets Per Template

## User Story

As the operator of the Infinito.Nexus platform, I want each provision template of a workspace to read only the platform provider secrets its own run needs, so that a leak or code execution in one workspace's run cannot hand over a platform account token that reaches every other customer's servers, records or zones.

## Context (2026-11-18, IAM store round)

- Every workspace has one task token role, `ws-<id>-provision`, for its `provision`, `destroy`, `unlock` and `dns` templates ([105](105-openbao-task-jwt-auth-transit-tenant-kv-and-store-approle.md)). Its policy `provision-shared` grants `read` on `platform/data/provision/*`.
- That subtree holds platform account tokens: `hetzner`, `ionos`, `scs`, `proxmox-<host>`, `incus-<host>`, and one Cloudflare token per pool zone at `cloudflare/<zone>`. Each reaches every workspace that the platform account serves.
- The provision script hands its OpenBao token to OpenTofu as `BAO_TOKEN`, so the provider plugins of a run hold a token that can read all of them, whichever provider the line uses.
- [124](124-cloudflare-zone-lifecycle-per-line.md) already moved the account-wide zone token out of that reach: `zone ws-<id>` logs in with its own role `ws-<id>-zone`, whose per-workspace policy reads that token and its own state, transit key and snapshot record only, and `provision-shared` denies the token.

## Open Decisions

For the operator; nothing below is decided yet.

1. **Scope per run.** Either one role per template and provider (the `ws-<id>-zone` pattern of 124, one per-workspace policy each), or the script exchanging its task token for a child token limited to the one provider path of the line before OpenTofu starts.
2. **The DNS pool.** Whether a `dns` run reads only the `cloudflare/<zone>` token of the workspace's own zone, written into a per-workspace policy at `workspace apply`.
3. **Platform versus customer tokens.** Whether `PROVIDER_TOKEN=platform` stays available to every workspace or becomes a per-workspace grant the store switches on.

## Acceptance Criteria

- [ ] A `provision` or `destroy` run of a line on one provider gets 403 on the platform secret of every other provider and on the Cloudflare tokens of every zone but its workspace's own (`test_a_provision_run_reads_its_own_provider_only` in `tests/unit/python/roles/web-app-openbao/test_policies.py`, with a planted wildcard as its negative control).
- [ ] The OpenBao token OpenTofu receives reads no path outside the run's provider, state, transit key and snapshot record (`test_the_tofu_token_reaches_the_line_provider_only` in `tests/unit/python/roles/web-app-semaphore/files/test_provision_sh.py`).
- [ ] Live, a provision task token of one workspace gets 403 on `platform/data/provision/<other provider>` (`provision isolation: a provision task reads no foreign provider secret` in `roles/web-app-semaphore/files/playwright/test-provision.js`).
