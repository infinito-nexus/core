# Deploy Guide 🚀

Use this guide to create inventories, run a full deploy, and redeploy an existing environment with `infinito` commands only. The audience is the operator running deploys against a managed (production or staging) host. Contributors iterating on a local development stack should follow [Local Deploy](../contributing/actions/deploy.md) instead.

## Full Deploy 📦

Create or refresh the inventory first, then deploy against the generated inventory file.

### Create or Refresh the Inventory 📝

```bash
infinito administration inventory provision /etc/infinito.nexus/inventories/prod \
  --inventory-file /etc/infinito.nexus/inventories/prod/devices.yml \
  --host localhost \
  --vars-file inventories/<env>/default.yml \
  --include 'web-app-nextcloud,web-app-keycloak'
```

### Run the Deploy 🛠️

```bash
infinito administration deploy dedicated /etc/infinito.nexus/inventories/prod/devices.yml \
  --password-file /etc/infinito.nexus/inventories/prod/.password \
  --log /etc/infinito.nexus/logs \
  --diff \
  -vv
```

## Redeploy 🔁

When you need to redeploy after changes, repeat the same two `infinito` commands:

1. Re-run `infinito administration inventory provision ...` to refresh the inventory file and included app list.
2. Re-run `infinito administration deploy dedicated ...` against the same inventory file.

## Inventory Notes 📒

- Keep one inventory directory per environment.
- Store the password file next to the inventory file.
- Update `--include` whenever the target app set changes.
- Use a `--vars-file` that matches the target environment. Production deploys MUST NOT point at the development sample file.

For CLI installation prerequisites, see the [Installation Guide](installation.md).
For the local development deploy flow (make targets, matrix variants, single-variant pinning), see [Local Deploy](../contributing/actions/deploy.md).
