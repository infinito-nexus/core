# Deploy Guide 🚀

Use this guide to create inventories, run a full deploy, and redeploy an existing environment with `infinito` commands only. The audience is the operator running deploys against a managed (production or staging) host. Contributors iterating on a local development stack should follow [Local Deploy](../contributing/actions/deploy.md) instead.

## Full Deploy 📦

Create or refresh the inventory first, then deploy against the generated inventory file.

### Create or Refresh the Inventory 📝

```bash
infinito administration inventory provision /etc/infinito.nexus/inventories/production \
  --inventory-file /etc/infinito.nexus/inventories/production/devices.yml \
  --host localhost \
  --vars-file inventories/<env>/default.yml \
  --include 'web-app-nextcloud,web-app-keycloak'
```

### Run the Deploy 🛠️

```bash
infinito administration deploy dedicated /etc/infinito.nexus/inventories/production/devices.yml \
  --password-file /etc/infinito.nexus/inventories/production/.password \
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

## Custom Roles 🧩

An inventory MAY deploy application roles that live in their own, possibly private, repositories.

### Declare 📝

A custom role is an inventory group named `web-app-cst-<name>`; a host joins it like any `web-app-*` group. Its application values mark it and name its source:

```yaml
applications:
  web-app-cst-security-check:
    custom: true
    source:
      url: git@github.com:infinitonexus/php-landingpage.git
      version: v1.4.0
      path: ansible/roles/web-app-cst-security-check
```

- `url` is a Git URL over HTTPS or SSH. During development an absolute local directory MAY stand in for it; without `version` its working tree is copied, uncommitted changes included.
- `version` is a tag or a full commit SHA. A branch is refused.
- `path` is the role directory inside the repository. Its name and the `application_id` in its `vars/main.yml` MUST equal the group.
- Values MUST be literal strings; Jinja is not rendered.

### Pull 🔄

`infinito administration deploy dedicated` and `infinito administration deploy swarm` pull the declared roles into `roles/` of the controller's checkout before they read any role. Pass `--skip-pull` to deploy the roles already placed. The same steps run on their own:

```bash
make roles-pull inventory=/etc/infinito.nexus/inventories/production/devices.yml
infinito administration roles list
make roles-clean
```

A pull stages every role outside `roles/` and changes `roles/` only when all of them passed, so a refused pull leaves it as it was. It replaces or removes only the directories it placed itself, whose marker names them, and refuses a declared name that meets a symbolic link, a hand-placed directory or a copy of a placed role. `make roles-clean` removes every `roles/web-app-cst-*` directory the pull placed and reports every other one it leaves in place. Git ignores `roles/web-app-cst-*`, so a pulled role never enters a core commit.

For the local compose stack, `INFINITO_EXTRA_MOUNTS=<dir>[,<dir>]` mounts each directory read-only at the same path into the `infinito` container, so a local `url` resolves inside it.

### Private Repositories 🔐

Git fetches with the SSH agent or the SSH configuration of the controller, so a deploy key goes into the agent or into `~/.ssh/config`:

```text
Host github-landingpage
  HostName github.com
  User git
  IdentityFile ~/.ssh/landingpage-deploy-key
  IdentitiesOnly yes
```

The declaration then uses `url: github-landingpage:infinitonexus/php-landingpage.git`. A `url` that embeds a password or token is refused without being echoed, and a fetch that would ask for credentials fails instead of prompting.

For CLI installation prerequisites, see the [Installation Guide](installation.md).
For the local development deploy flow (make targets, matrix variants, single-variant pinning), see [Local Deploy](../contributing/actions/deploy.md).
