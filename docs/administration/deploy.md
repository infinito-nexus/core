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

### Manifest 📌

[custom_roles.yml](../../meta/custom_roles.yml) pins the public custom roles every core checkout carries, so their roles, tests and service providers are always loaded. One entry has this shape:

```yaml
web-app-cst-example:
  url: https://github.com/example/example-role.git
  version: v1.0.0
  commit: 0123456789abcdef0123456789abcdef01234567
  path: ansible/roles/web-app-cst-example
```

- `url`, `version` and `path` follow the inventory `source` above, with two limits: `url` MUST be the `https` URL of a public repository without credentials, and `version` MUST be a release tag `vX.Y.Z` or `X.Y.Z`. A moving tag such as `latest`, a prerelease, a branch and a commit are refused. A private role, and every role that needs SSH, stays in the inventory.
- `commit` is the full 40-hex commit the tag resolves to; an annotated tag counts by the commit it peels to. A tag that resolves to another commit stops the pull with a message naming the role and both commits, like `pip --hash`.
- A host whose inventory declares `applications.web-app-cst-<name>.source` gets that source instead of the manifest's, with or without `custom: true`. A pinned group needs neither `custom: true` nor a `source` in the inventory; `custom: false` keeps the pin and ignores the inventory `source`.
- The `update-custom-roles` job of [cron-update.yml](../../.github/workflows/cron-update.yml) runs `python -m cli.contributing.update.custom_roles` and opens a PR that moves each pin to the newest release tag of its repository and its commit.

### Pull 🔄

`infinito administration deploy dedicated` and `infinito administration deploy swarm` pull the pinned and the declared roles into `roles/` of the controller's checkout before they read any role. Pass `--skip-pull` to deploy the roles already placed. The same steps run on their own:

```bash
make roles-pull inventory=/etc/infinito.nexus/inventories/production/devices.yml
infinito administration roles list
make roles-clean
```

`make roles-pull` without `inventory` places only the pinned roles that are missing or were placed from another pin, and removes nothing; a role an inventory placed stays. `make test`, `make lint` and `make compose-up` run it that way first, so the first run of a checkout needs network access to the pinned repositories and every later one none.

A pull stages every role outside `roles/` and changes `roles/` only when all of them passed, so a refused pull leaves it as it was. It replaces or removes only the directories it placed itself, whose marker names them, and refuses a declared name that meets a symbolic link, a hand-placed directory or a copy of a placed role. `make roles-clean` removes every `roles/web-app-cst-*` directory the pull placed and reports every other one it leaves in place. Git ignores `roles/web-app-cst-*`, so a pulled role never enters a core commit.

The pull also records the version the source repository declares at the pinned commit, or in a local checkout: `Cargo.toml`, else `pyproject.toml`, else `package.json`. A role pins the images its own repository publishes with it, so no release has to bump them by hand:

```yaml
security-check:
  image: ghcr.io/infinito-nexus/security/web
  version: "{{ lookup('role_version', 'web-app-cst-security-check') }}"
```

A role with an `sso` service declares its row of the back-channel logout table in [web-svc-logout's README](../../roles/web-svc-logout/README.md) in its own repository's `meta/services.yml`, as `sso.backchannel` with the string values `logout` (starting with `yes` or `no`), `endpoint`, `documentation` and `session`, while its `sso.flavor` fills the flavor cell. Quote every value, because YAML reads a bare `yes` or `no` as a boolean, a bare number as an integer, and an unquoted `-` does not parse; an empty cell, `to verify` or `TBD` in any cell and an unknown key are refused, and `sso.backchannel` on a core role is a finding, since a core role keeps its row in the README.

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
