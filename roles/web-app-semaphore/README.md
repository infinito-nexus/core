# Semaphore UI

## Description

[Semaphore UI](https://semaphoreui.com/) is a modern web UI and API for running Ansible playbooks, Terraform/OpenTofu plans, and shell scripts on a schedule or on demand. This role deploys the official [`semaphoreui/semaphore`](https://github.com/semaphoreui/semaphore) container behind the Infinito.Nexus reverse proxy with central PostgreSQL, native Keycloak OIDC Single Sign-On, and optional LDAP login.

## Overview

The role deploys the Semaphore server and a dedicated task runner and wires them into the platform via `SEMAPHORE_*` environment variables. The setup wizard is bypassed by seeding the initial admin from rendered secrets, so a fresh deploy lands directly on the Semaphore login page. When SSO is enabled, the Keycloak `administrator` is created at deploy time as an external Semaphore admin via `semaphore user add --admin --external`; the OIDC callback matches it by email and signs the operator in as a Semaphore admin. As the last step of every deploy the role converges the `Infinito.Nexus` project, whose stop and start templates let members of the `operator` role group pause and resume the applications of the host through [sys-svc-app-control](../sys-svc-app-control/).

## Features

- **Central PostgreSQL:**
  `SEMAPHORE_DB_DIALECT=postgres` against the shared `svc-db-postgres` (or a per-role engine when not shared), with centralised backup and monitoring.

- **Native OIDC SSO:**
  Semaphore renders its own "Sign in with Keycloak" button via `SEMAPHORE_OIDC_PROVIDERS`; the Keycloak client is auto-provisioned by `web-app-keycloak`.

- **Login methods:**
  `services.semaphore.login.method.*` of [meta/services.yml](./meta/services.yml) switches each sign-in method on its own. `sso` renders the Keycloak provider through `SEMAPHORE_OIDC_PROVIDERS`; `ldap` sets `SEMAPHORE_LDAP_ENABLE`; `native` and `ldap` share one form, which `SEMAPHORE_PASSWORD_LOGIN_DISABLED` hides while both are off; `2fa` offers TOTP enrollment through `SEMAPHORE_TOTP_ENABLED`. With SSO on, the sign-in page shows only the Keycloak entry and LDAP accounts sign in through Keycloak's LDAP federation.

- **LDAP login:**
  With the `ldap` method on (SSO off and `svc-db-openldap` present), Semaphore's login form binds against the central OpenLDAP directory (`SEMAPHORE_LDAP_*`). The form is then LDAP-only: Semaphore cannot tell local from LDAP accounts at the form, so no local account signs in, the break-glass account included.

- **LDAP role gate:**
  The LDAP search filter only finds members of the `administrator`, `operator` and `user` role groups (`memberOf` under the roles OU), so a directory account without one of them cannot sign in through the form.

- **OIDC role gate:**
  The provider's `email_claim` is a Go template rendered from `templates/oidc/email_claim.j2`. It yields the email only when the groups claim holds the `administrator`, `operator` or `user` role group and the `email_verified` claim is true, so Semaphore refuses the Keycloak sign-in of every other realm account, and of an account with an unverified address, with a missing email claim and returns it to the login page. Semaphore links a Keycloak sign-in to its account by that email.

- **Role group sync:**
  With SSO or LDAP, [files/sql/rbac/reconcile.sql](./files/sql/rbac/reconcile.sql) runs through `psql` in the database container as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer, so a group change reaches Semaphore within one timer interval. The same run creates every member of the `administrator` and `operator` role groups that has an e-mail and no account yet as an external Semaphore account, admin only for `administrator`, so a member added between deploys has its account within one timer interval.

- **Admin flag reconcile:**
  The hook converges the admin flag of every account to the `administrator` role group. The break-glass account and the platform administrator are never demoted.

- **Operator role:**
  The `operator` role of [meta/rbac.yml](./meta/rbac.yml) maps to the Semaphore project role `task_runner` in the `Infinito.Nexus` project. The hook grants it to every account of an `operator` member and revokes it from every other account, so an operator can run the stop and start templates while a non-admin account outside the group neither sees the project nor runs its templates. Only `administrator` members are Semaphore admins.

- **Directory profile reconcile:**
  The hook writes the directory email, and the full name when the member list carries one, into every external account of an `administrator`, `operator` or `user` member. An email another account already holds is left in place.

- **Outsider sign-out:**
  The hook expires the sessions and API tokens of every external account that belongs to none of the role groups. The break-glass account and the platform administrator are exempt.

- **Break-glass local admin:**
  `SEMAPHORE_ADMIN*` seeds a local admin from the `web-app-semaphore-breakglass` user in every variant. With the `native` method on it signs in through the login form. With SSO on the form is hidden, and the account signs in through the login API, which `SEMAPHORE_PASSWORD_LOGIN_DISABLED` leaves open: `POST /api/auth/login` with `{"auth": "<username>", "password": "<password>"}` sets the session cookie, after which the UI opens signed in. With the `ldap` method on the account cannot sign in.

- **Dedicated runner:**
  Templates never run inside the server container: the server sets `SEMAPHORE_USE_REMOTE_RUNNER=true` and hands every task to the `task-runner` service, which signs in with the runner token the deploy seeds. Its image is an Infinito.Nexus image (`SOFTWARE_IMAGE`) plus the `semaphore` binary of the pinned server image, tagged with the tag of that Infinito.Nexus image. It mounts no Docker socket, runs as an unprivileged user, and reaches hosts only over SSH with the key held in the key store of the project.

- **Runner build:**
  A deploy that names `web-app-semaphore` among its apps (`PRIMARY_APPS` of the matrix deploy, the `--id` list otherwise, every inventory group without one, read as `lookup('deployment').primary`) builds the runner on the Infinito.Nexus image of that deploy (`SOFTWARE_IMAGE_TAG`: `ci-<sha>` in CI, `dev-<sha>` locally, the release version in production, never `latest`), so the foreign-server deploy and the app-control templates run that checkout. A deploy that pulls Semaphore in only as a provider of another application reads the runner it deployed from the compose file on the stack host and keeps it, building neither the runner nor its base image, as long as the stack host still holds both images and the runner image carries the `nexus.infinito.semaphore.runner.inputs` label of this checkout. That label is the sha256 of every build argument but the base image: the digest of the [runner Dockerfile](./files/runner/Dockerfile), the digest of the scripts in `files/shell/repository/`, the pinned server image, the runner user, its UID and GID, the repository link and the temporary directory. A missing image, a missing label or another digest rebuilds the runner on the image of this deploy, like Semaphore's own round, and a kept runner whose tag differs from `SOFTWARE_IMAGE_TAG` is reported by a warning task. With `SOFTWARE_IMAGE_BUILD` the base image is built from the checkout only when the stack host lacks it. After the compose stack is up, the deploy untags every tag of the runner image on the stack host and, with `SOFTWARE_IMAGE_BUILD`, every tag of `SOFTWARE_IMAGE`, except the runner and base image it runs; an image a container still uses keeps its layers. The Playwright environment carries `SEMAPHORE_RUNNER_IMAGE_TAG`, and every template run of the specs logs it.

- **Control flag:**
  Every invokable role declares `services.semaphore` with `enabled`, `shared`, `control` and `status`. `enabled` and `shared` follow `'web-app-semaphore' in group_names`; `control: true` puts the application under Semaphore control; `status` is `started` or `stopped` and only decides the state the deploy creates the application in, while a redeploy keeps the state Semaphore last set.

- **Control-plane exemptions:**
  `web-app-semaphore`, `web-app-keycloak`, `svc-db-postgres`, `svc-db-openldap`, `svc-prx-openresty` and `web-app-gitea` declare `control: false` and `status: started` with a `# nocheck:` reason, so no Semaphore run can cut off its own way back. Shared providers that other roles consume, such as `web-app-matomo` or `web-app-prometheus`, stay out of control as well. In `web-app-semaphore` the entry is the Semaphore container itself, so its `enabled` stays the container flag.

- **Stop and start templates:**
  The `Infinito.Nexus` project holds `stop <application_id>` and `start <application_id>` for every application the host registered with `control: true`, plus `stop all` and `start all` over exactly that set. The deploy converges the project, its SSH key, inventory, repository, environment and templates idempotently through a short-lived API token, and removes the templates of applications the host no longer holds.

- **App-control SSH path:**
  Each template runs `app-control.sh stop|start <application_id>|all` in the runner, which signs in over SSH as the host account `app-control` with the `app_control_ssh_key` credential and a pinned host key. The `authorized_keys` entry of that account is `restrict`ed to a forced command that accepts only `app-control stop|start <application_id>|all`, and sudo lets the account run exactly those two subcommands as root.

- **Paused page:**
  While an application is paused, nginx answers every one of its vhosts with HTTP 503 and a self-contained page with a beaver sleeping behind a pause sign, the paused notice and the contact channels of `service_provider.contact`. The page is rendered from the `core` gettext catalogs in every language they translate, picked from `Accept-Language`, with English as the fallback.

## Foreign-Server Deploy

Semaphore deploys Infinito.Nexus to foreign servers from an inventory repository once the inventory of the Semaphore host declares the optional `deploy` block:

```yaml
applications:
  web-app-semaphore:
    services:
      semaphore:
        deploy:
          repository:
            url: ssh://git@git.example.org:2222/infra/inventory.git
            branch: main
            key: "<OpenSSH private key with read access to the repository>"
          vault_password: "<vault password of that inventory>"
```

- **Mandatory keys:**
  Without the block the role converges no deploy project and registers no deploy app. Once the block is present, `repository.url`, `repository.branch`, `repository.key` and `vault_password` are all mandatory and none has a default, so a deploy with one of them missing fails.

- **Deploy project:**
  The deploy converges a second project, `Infinito.Nexus Deploy`, next to `Infinito.Nexus`. It holds the template `deploy`, the inventory `deploy` carrying the deploy key, the repository `inventory` and an environment named `deploy <digest>`. The hook grants every Semaphore admin, whose flag it keeps in step with the `administrator` role group, the project role `owner` in it and revokes every other membership, so `operator` and `user` members neither see the project nor run its template.

- **Private repositories:**
  Semaphore clones the repository over its SSH URL with `repository.key`, which the deploy stores as an SSH key of the project, so a private repository is the default case: register the public half of `repository.key` as a read-only deploy key of the repository. The repository holds the inventory the way `infinito administration inventory provision` writes it, with `devices.yml` at its root, and `vault_password` is the password its vault values are encrypted with.

- **Keys:**
  The deploy signs in to every host the inventory lists as `root` with the `deploy_ssh_key` credential, so authorize its public half for `root` there. It is a key of its own: the `app_control_ssh_key` credential reaches only the `app-control` account of the Semaphore host through its forced command and never leaves that host. Every key is stored under a name that ends in its fingerprint, so the deploy that brings a rotated key stores it next to its predecessor and removes the predecessor. The vault password is a Semaphore secret of the deploy environment, whose name ends in a digest keyed with the deploy key, so a changed password replaces the environment the same way.

- **Runner path:**
  The block also registers the Semaphore app `infinito` through `SEMAPHORE_APPS`. The `deploy` template runs it in the dedicated runner as `bash /opt/app-control/deploy.sh devices.yml`, with the checkout of the inventory repository as working directory. [deploy.sh](./files/shell/repository/deploy.sh) writes the vault password from `DEPLOY_VAULT_PASSWORD` into a `0400` file of a temporary directory it removes on exit, pins the host keys of `DEPLOY_KNOWN_HOSTS` through `ANSIBLE_SSH_COMMON_ARGS` when the environment carries any, and runs `infinito administration deploy dedicated <checkout>/devices.yml --password-file <file> --skip-build -u root` with the deploy key in the SSH agent Semaphore starts for the inventory. The runner runs the Infinito.Nexus image of the deploy that last built it (see **Runner build**), so a foreign server receives the release of that deploy. Outside the test fixture the environment pins no host keys, and a deploy accepts every host key it does not know yet under the `accept-new` policy of `ansible.cfg`.

- **Test variant:**
  Variant 0 of [meta/variants.yml](./meta/variants.yml) deploys `web-app-gitea` next to Semaphore and declares the block with the private repository `target-inventory` of the platform administrator on the SSH port of that Gitea, the branch `main`, the `deploy_ssh_key` credential as repository key and a fixed vault password. On the `dev`, `act` and `github` runtimes, with Gitea and the block present, [tasks/utils/project/fixture.yml](./tasks/utils/project/fixture.yml) runs before the projects converge: it reads the address, pinned host keys and public root key of the [shared target](../../compose/target/README.md) from the holder, authorizes the deploy key for `root` on the target, recreates the repository whenever its `.infinito-fixture` marker no longer matches the repository key, vault password, host, application and variables, with an inventory for the host `target` that includes `web-svc-html` under `TLS_MODE` `self_signed` and the `DOMAIN_PRIMARY` of the stack, and binds the public half of the repository key to the repository as a read-only deploy key. The `deploy` environment then pins the host keys of the target. [test-foreign-deploy.js](./files/playwright/test-foreign-deploy.js) signs in as `administrator` through Keycloak, requires that port 443 of the target still refuses, runs `deploy`, waits up to 60 minutes for the task, and opens `https://html.<DOMAIN_PRIMARY>/` in a browser that resolves that name to the target. It runs in the sync pass only, the pass the target is reset for.

## Further Resources

- [Semaphore UI Official Website](https://semaphoreui.com/)
- [Semaphore Documentation](https://docs.semaphoreui.com/)
- [OIDC / Keycloak configuration](https://docs.semaphoreui.com/administration-guide/openid/keycloak/)
- [Semaphore GitHub Repository](https://github.com/semaphoreui/semaphore)
- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/7gHWVy5u3jmoA9qni7W5Zi)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/4aT9GCukcd6kTnWzqTwwc4)
