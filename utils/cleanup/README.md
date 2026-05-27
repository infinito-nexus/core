# Cleanup Utilities 🧹

This directory contains helpers that mutate persistent on-host state during purge flows.

## Scope 📋

Modules under `utils/cleanup/` MUST limit themselves to wiping or normalising state that survives compose and volume purges (for example secrets, token stores, cached registry data) so the surrounding entity-keyed purge primitives stay focused on stack-level cleanup.

Modules under `utils/cleanup/` MUST NOT take over responsibilities that belong to the entity-keyed purge primitives in [scripts/container/purge/entity/](../../scripts/container/purge/entity/) (database drop, compose down, filesystem removal).

## Usage 🛠️

Every module here SHOULD expose a callable function for in-process use and a `__main__` shim so the same code path is reachable from shell orchestrators via `python -m utils.cleanup.<module>`.

The host-side purge flow invokes these modules through the app-keyed orchestrator [apps.sh](../../scripts/container/purge/apps.sh).
