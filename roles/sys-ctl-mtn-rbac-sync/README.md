# RBAC Sync

## Description

Reconciles the role mapping of every application that cannot read its role groups at sign-in with the members those groups hold in the directory now, so a group change in Keycloak or LDAP reaches the application within one timer interval instead of at its next deploy.

## Overview

An application registers its reconcile as a hook through [tasks/utils/rbac/sync.yml](../../tasks/utils/rbac/sync.yml). The util writes `hooks/<application_id>/` under `DIR_RBAC_SYNC`, root-only, with `hook.json`, the hook's script and the modules a host hook imports, and runs the hook once with the members the deploy resolved. The timer runs [files/python/script.py](./files/python/script.py) on `SYS_SCHEDULE_MAINTANANCE_RBAC_SYNC`; it reads the members of each hook's role groups anonymously from the directory and runs every hook whose container runs on the node.

A `container` hook pipes its script into a command inside the application's container, for applications whose image ships a scripting runtime. A `host` hook runs its script with the node's Python beside its modules and reaches the container through `$RBAC_SYNC_CONTAINER_BIN exec ... $RBAC_SYNC_CID`, for applications that only expose a CLI or an HTTP API inside the container. A hook runs on the node of the one container it names and reaches nothing else: in swarm no `ports.local` port is published, so an application whose hook acts on its database cannot also call its own HTTP API from there. Such work runs at deploy time inside the application's network namespace, as [web-app-peertube](../web-app-peertube/README.md) creates its accounts, and the hook keeps the SQL.

## Features

- **One execution path:** the deploy and the timer run the same hook through the same script; only the source of the members differs.
- **Directory lookup without packages:** members come from the `ldap_client` module of `svc-db-openldap`, a standard-library LDAP client. It connects to the `ldapi` socket `svc-db-openldap` bind-mounts on its node (`LDAP.SERVER.SOCKET_URI`), the address the role's own provisioning uses in both modes; swarm publishes no `ports.local` port, so the loopback port reaches nothing there.
- **Mailbox seed:** under the `mailbox` email policy of `web-app-keycloak`, `svc-db-openldap` installs the timer. Only once the deploy has applied the mailbox layout, which in a deploy with Keycloak happens after Keycloak accepted the realm's policy, [tasks/mailbox.yml](./tasks/mailbox.yml) writes the root-only `mailbox.json` under `DIR_RBAC_SYNC`; under the `external` policy `svc-db-openldap` removes it. While it exists, each run without `--only` gives every account of the users OU that holds no `mail` the address `<uid>@<DOMAIN_PRIMARY>` and the class `infinitoMailboxUser` before the hooks read the members. An existing `mail` value is never changed. The address comes from the `ldap_mailbox` module the deploy's mailbox layout uses. The run binds as `LDAP.DN.ADMINISTRATOR.DATA`; its password lives in `mailbox.json`, never in argv, the log, `config.json`, or the `RBAC_SYNC_LDAP` a host hook receives. Every deploy that installs the timer rewrites an existing `mailbox.json` before it starts the run, so a password the deploy rotated reaches the seed before the first bind, long before Keycloak applies the layout again.
- **Node-local execution:** a hook runs only where its container runs; on any other node the script reports it as skipped. The script and its modules are installed on every swarm node, because the deploy-time run happens on the node of the hook's container.
- **Reads follow the socket:** the socket exists only on the node OpenLDAP runs on, and OpenLDAP can only start on a host of `svc-db-openldap`, the only hosts where that role creates the socket's bind-mount source. The timer runs on each of them. A missing socket is one `SKIPPED` line with no hook run only where slapd is not expected: on a node outside `svc-db-openldap`, or while the backup's maintenance signal (`FILE_MAINTENANCE_BACKUP`, read by the `maintenance` module of [svc-bkp-volume-2-local](../svc-bkp-volume-2-local/README.md)) lists `svc-db-openldap` as stopped. On any other host of `svc-db-openldap`, including one whose signal cannot be read, a missing socket or a socket that does not answer fails the run in one `FAILED` line. A host hook that reads `RBAC_SYNC_LDAP` on a node without the socket fails with `SocketMissingError` naming the socket.
- **Runs only on change:** a hook registered with `skip_unchanged` runs when its definition or the members it receives changed since its last successful run, and at least once per `RBAC_SYNC_REFRESH_SECONDS`. An application that grants roles at sign-in MUST register with `skip_unchanged: false`: a member who joins and leaves a group between two runs leaves the member digest as it was, so a skipped hook would keep the sign-in grant until the refresh.
- **Single run per cluster:** in swarm the timer only uses the container of task slot 1.
- **Secrets stay out of argv:** forwarded variables reach `container exec` by name, their values travel in the environment.
- **Timer only with a directory:** without `svc-db-openldap` on `STACK_HOST`, and on every host outside `svc-db-openldap`, the service stays installed for the deploy-time run and the timer stays off.
- **Failure notification:** a failed hook fails the unit, which triggers `sys-ctl-alm-compose`.

## Hook file

| Key | Meaning |
| --- | --- |
| `application_id` | application whose role mapping the hook reconciles |
| `kind` | `container` or `host` |
| `roles` | role names whose members the hook receives; `@users` stands for every account of the users OU, for hooks that refresh profiles |
| `container` | `{"name": ...}` in compose, `{"swarm_service": ...}` in swarm |
| `user` | user a `container` hook's command runs as, empty for the image's user |
| `argv` | command a `container` hook runs inside the container, empty for a `host` hook |
| `script` | file in the hook directory: piped to a `container` hook's command, run by a `host` hook; empty for none |
| `env` | variables the hook receives |
| `members_env` | `{name, role, field}` entries; `role: "*"` passes `{role: members}`, an empty `field` passes whole members |
| `skip_unchanged` | whether the timer skips the hook while its inputs are unchanged and its last run is younger than `RBAC_SYNC_REFRESH_SECONDS` |

## Further Resources

- [systemd.timer(5) manual](https://www.freedesktop.org/software/systemd/man/systemd.timer.html)
