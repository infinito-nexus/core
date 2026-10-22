# Update Report 📋

This playbook collects the state of an Infinito.Nexus host of any version as the starting point of an update, and judges that state and the host's inventory against the code of this checkout.
It only reads and changes nothing on the host.

## Run 🚀

Run from the repository root:

```bash
ansible-playbook -i <inventory> --vault-password-file <file> -l <host> playbooks/update/report.yml
```

From a worktree, prefix the command with `PYTHONPATH="$PWD"`, otherwise the plugins import `utils` from the checkout the editable install points at and judge the host against that code.

The controller keeps two files per host:

| File | Content |
|---|---|
| `/tmp/infinito-update-report-<host>.txt` | The raw report, see [Content](#content-) |
| `/tmp/infinito-check-<host>.txt` | Every check of the [Check](#check-) by area, ✅ included |

The terminal shows the counts and every ⚠️ and ❌, and the play fails when one check is ❌.
The host needs no Python, because both collectors run as plain shell scripts.

## Check 🚦

[state.sh](files/state.sh) collects the host's state as tab-separated records, and the filter [update_check](../../plugins/filter/update_check.py) compares it with what `lookup('applications')` and `lookup('application_closure', group_names)` derive from the current code and the inventory.

| Area | ❌ | ⚠️ |
|---|---|---|
| inventory | The validator rejects a key, a role is end of life | A group names no application role, a role is deprecated, a credential of `meta/secrets.yml` has no value |
| volumes | A declared volume is missing while one that differs only in `-`/`_` or in its last `_` part exists | A declared volume is missing, a database volume lies on the mass storage, a volume belongs to no deployed role |
| data | `PG_VERSION`, `mysql_upgrade_info` or Nextcloud's `version.php` is newer than the pinned image | It is older, with the number of major steps |
| images | A container runs a newer image than the code pins | It runs an older one, with the skipped majors |
| ports | Two roles declare the same local port, a host process listens on a declared port | A foreign container binds a declared port, two containers bind the same port |
| networks | Two roles declare overlapping subnets | A foreign docker network overlaps a declared subnet |
| webserver | `openresty -t` fails | No OpenResty runs, a domain has no loaded server block, a loaded server block serves no deployed domain, a domain only the old layout serves is dropped |
| certificates | A certificate expires within 7 days | Within 21 days, a domain has no certificate |
| operations | The newest backup is older than 7 days, a disk is 95% full | A unit failed, a backup is older than 36 hours or empty, a disk is 85% full |

Run it before an update to see the gap to the current code, and after the deploy to confirm the gap is closed.

## Content 📄

| Section | Content |
|---|---|
| host | Hostname, OS release, kernel, CPU, memory, disks, `/opt` layout |
| infinito version | `INFINITO_VERSION` from `/etc/environment`, `pkgmgr`, every `infinito*` or `cymais*` checkout with its `pyproject.toml` version and last commit |
| docker | Engine, compose plugin, `docker-compose`, storage driver, root directory, swarm state |
| compose stacks | Every stack directory below `/opt/compose/` and `/opt/docker/` with its files |
| containers | Image, image ID, OCI version label, state, creation time, compose project and every mount with its host source |
| images | Every image with tag, ID, age and size |
| volumes | Every volume with driver, mountpoint and creation time |
| volume sizes | Size of every volume and the number of containers using it |
| networks | Every network with driver and scope |
| database data versions | `PG_VERSION` and `mysql_upgrade_info` found in volumes and stack directories |
| systemd | `*infinito*` and `*cymais*` unit files, every timer, failed units |
| webserver and certificates | Host `nginx` or `openresty`, its enabled sites, Let's Encrypt certificate names |
| backups | Newest backup of every backup repository below the current and the `/Backups` layout |

The report contains no container environments and no compose file contents.
