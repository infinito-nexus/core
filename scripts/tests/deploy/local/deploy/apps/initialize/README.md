# Initialize 🌱

Create a fresh inventory and deploy the selected applications against the development stack.
Existing container state and shared entities are kept untouched.

## Entry Points 🚪

| Entry point | Scope |
|---|---|
| `all.sh` | every discovered application (filtered by `INFINITO_DEPLOY_TYPE` and optional `INFINITO_WHITELIST`) |
| `selection.sh <app-id>` | one or more apps passed via `apps` or as a positional argument |

## When to use 🎯

- First-time setup of a development environment for a given application set.
- Re-run after an inventory change when the running stack state SHOULD be preserved.
- Iterating on Ansible logic for an application without recycling its data.

For the destructive equivalent that cycles the stack and purges shared entities, see [reinstall/](../reinstall/README.md).
For redeploys that reuse the existing inventory, see [update/](../update/README.md).
