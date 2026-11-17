# Deployment Exceptions ⚠️

This page documents known cases where an Ansible role deliberately skips its work instead of failing,
and explains the conditions under which the skipped work will be completed on a subsequent run.

## Matomo Token Not Yet Available ⚠️

**Role:** [`roles/sys-front-inj-matomo`](../../../roles/sys-front-inj-matomo/)
**Variable:** `lookup('users', 'administrator').tokens['web-app-matomo']`

### Cause 🔍

The Matomo API token is generated during the Matomo bootstrap and persisted to disk by `sys-token-store`.
It is then resolved through `lookup('users')`, which hydrates tokens from the store at runtime.

On the **first deployment**, or after a factory reset, the token does not yet exist because the bootstrap
has not run yet. A second common cause is that [`roles/sys-service-loader/tasks/load_service.yml`](../../../roles/sys-service-loader/tasks/load_service.yml)
skips `load/app.yml` when the
Matomo container is already reachable. In that case the container is healthy but the token file is still
absent from the token store, so the variable arrives empty.

### Behaviour ⚙️

[`resolve_site.yml`](../../../roles/sys-front-inj-matomo/tasks/resolve_site.yml) resolves the token, queries
`SitesManager.getSitesIdFromSiteUrl`, registers the site when it is unknown, and leaves `matomo_site_id`
as the empty string whenever any of those steps cannot complete. An empty token short-circuits the API
call, and an API answer that is not a 200 list leaves the id unresolved the same way.

When `matomo_site_id` is empty, `sys-front-inj-matomo` still injects the tracker, whose text carries no
site id, with an empty `data-matomo-site-id` attribute. The tracker returns before it loads `matomo.js`
while that attribute is empty, and the play continues without error. A front svc-stack rendered this way
is recorded in `stack_matomo_unsited`, so [`web-app-matomo`](../../../roles/web-app-matomo/) gives it
the site id once its install path holds the token.

Failing instead of skipping would make the play non-idempotent on first deployment and would block every
other application from being configured just because Matomo's bootstrap has not completed yet.
Matomo tracking is a best-effort enhancement, not a hard runtime dependency of the target application.

### Resolution ✅

Once the Matomo bootstrap has run, either later in the same play or on the next Ansible invocation,
`sys-token-store` writes the token to disk. On the **next play run** the token is resolved from the store,
and `resolve_site.yml` registers the site at Matomo and renders its id into the tracker of the target
application.

No manual intervention is required. Re-running the play is sufficient.
