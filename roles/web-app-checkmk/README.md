# Checkmk

## Description

[Checkmk](https://checkmk.com/) (Raw / Community edition, 100% open source) is an IT and application monitoring system. This role deploys the official all-in-one `checkmk/check-mk-raw` container behind the Infinito.Nexus reverse proxy, with Keycloak SSO via the oauth2-proxy gate and native LDAP user management.

## Overview

Checkmk Raw bundles its own monitoring core (Nagios), RRD storage, and an Apache-served web GUI, so it needs no external database. All state lives on one persistent volume mounted at `/omd/sites`, and the GUI is served under the OMD site path (`/cmk/check_mk/`). The image `checkmk/check-mk-raw` is pinned in `meta/services.yml`; Checkmk renamed the Raw image to `check-mk-community` from 2.5, so bump the tag only after reviewing the upstream [version notes](https://docs.checkmk.com/latest/en/cmk_versions.html).

## Features

- **Open-source monitoring:**
  Hosts, services, metrics, and alerting from the Checkmk Raw all-in-one container.

- **Keycloak SSO:**
  Fronted by the platform oauth2-proxy gate; the authenticated user is passed to Checkmk via the trusted `X-Remote-User` header (`auth_by_http_header`), so no second login prompt appears.

- **Native LDAP:**
  A central-OpenLDAP connection supplies user records, roles, and contact groups; the header user (Keycloak `preferred_username`) resolves to a real Checkmk user.

- **Role groups:**
  The oauth2-proxy gate admits only members of the `administrator`, `user` and `guest` role groups, and the LDAP user filter finds only those members. The LDAP `groups_to_roles` plug-in maps the groups onto the Checkmk roles Administrator, Normal monitoring user and Guest user.

- **Profile sync:**
  The LDAP sync copies mail, full name and the directory phone number (Checkmk pager address) into every user record.

- **No external database:**
  Self-contained on a single persistent volume.

- **Agent receiver:**
  Container port 8000 is mapped to a host port (`local.agent`); customer hosts register no agent, Checkmk pulls theirs over SSH (see below).

- **Break-glass `cmkadmin`:**
  Seeded on first run via `CMK_PASSWORD` and re-converged onto the running site on every deploy; reachable via the local login form only when the SSO gate is absent.

- **Runner pool host:**
  Only the infra inventory sets `services.checkmk.local_check_dir`, with `INFINITO_INFRA_CHECKMK=true`, to the directory the infra runner's `infinito-pool-checkmk` timer rewrites `pool.txt` in every minute. The role mounts it read-only at `/etc/infinito/pool` and [register_pool_host.py](./files/python/register_pool_host.py) converges host `infinito-infra` with a `datasource_programs` rule that runs `cat /etc/infinito/pool/pool.txt`, then a `fix_all` service discovery: one service per pool runner (critical when `failed`), per held job, per cache and for the disk floor.

- **Workspace monitoring user:**
  With Semaphore and OpenBao in the inventory, [provision/monitoring_identity.py](./files/python/provision/monitoring_identity.py) converges the automation user `monitoring` of the Semaphore template `monitoring` (requirement 138). Its role `workspaces` may manage hosts, folders, services and rules, run service discovery and activate its own changes; every other permission, the ones inherited from `user` and `wato.add_or_modify_executables` included, is an explicit `no`, so it can never write a rule that runs a program. The folder `/workspaces` alone grants its contact group write access, recursively. The deploy writes the user's login to OpenBao at `platform/monitoring/checkmk`, which only that template's task token reads.

- **Workspace agents over SSH (requirement 138 Decision 6):**
  The deploy generates the platform monitoring key once inside the site ([monitoring_agent.sh](./files/shell/monitoring_agent.sh)); the private half stays at `~/.ssh/infinito_monitoring` of the site user, and only the public half is written to OpenBao at `platform/monitoring/agent-key` (`public_key`). It installs [infinito_agent_ssh.py](./files/python/infinito_agent_ssh.py) as `~/local/bin/infinito_agent_ssh` and keeps one `datasource_programs` rule on `/workspaces` that calls it with `$HOSTNAME$ $HOSTADDRESS$`. The program reads the host's labels `infinito/ssh_user`, `infinito/ssh_port`, `infinito/ssh_host_key_type` and `infinito/ssh_host_key`, which the template sets from the workspace inventory, checks each again and runs ssh without a shell, with that key, `StrictHostKeyChecking=yes`, no known_hosts file and the inventory's host key pinned through `KnownHostsCommand`. It passes the agent output on only when it starts with the `<<<infinito_workspace>>>` section naming the workspace of the host's `workspace` label, which only the template sets; otherwise it prints nothing and exits non-zero. `services.checkmk.monitoring.tls_expiry` holds the warn and crit days of the TLS expiry check the template sets up per instance domain.

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## Further Resources

- [Checkmk Docker docs](https://docs.checkmk.com/latest/en/introduction_docker.html)
- [LDAP user management](https://docs.checkmk.com/latest/en/ldap.html)
- [HTTP header authentication (Werk #7819)](https://checkmk.com/werk/7819)
- [Checkmk GitHub Repository](https://github.com/Checkmk/checkmk)
- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/Y4XB35NChLhHhvvjNfGGJW)

## Persona contract opt-outs

Both authenticated Playwright personas are blocked while `services.sso.enabled` is false. Without SSO, `files/configure-sso.sh` skips the `auth_by_http_header` snippet, so the OMD site falls back to its own login form.

The only account that form accepts is Checkmk's built-in `cmkadmin`, whose password comes from `credentials.cmk_password` (`CMK_PASSWORD` in the container env) — a site-local secret unrelated to the Keycloak credentials the personas use. No Checkmk user is provisioned for a non-admin identity at all. With SSO enabled both personas run through the header-auth chain; the biber persona joins the `guest` role group for its journey, because the gate refuses an account without a Checkmk role group.
