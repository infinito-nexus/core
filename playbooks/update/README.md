# Update 🔄

These playbooks prepare the update of an Infinito.Nexus host of any version to the code of this checkout.
[report.yml](report.yml) collects the state of the host as the starting point of the update, and judges that state and the host's inventory against the code.
It only reads and changes nothing on the host.
[pull.yml](pull.yml) pulls the images the deploy of the host runs, see [Pull](#pull-).

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

[state.sh](files/state.sh) collects the host's state as tab-separated records, and the filter [update_check](../../plugins/filter/update/check.py) compares it with what `lookup('applications')` and `lookup('application_closure', group_names)` derive from the current code and the inventory.

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

## Pull 📥

[pull.yml](pull.yml) pulls every image the deploy of the host runs onto the host, also while the host still runs an older version.
Run it from the repository root, with the `PYTHONPATH` prefix of [Run](#run-) in a worktree:

```bash
ansible-playbook -i <inventory> --vault-password-file <file> -l <host> playbooks/update/pull.yml
```

The filter [update_pull_images](../../plugins/filter/update/pull.py) lists every service with an `image` and a `version` that `lookup('applications')` gives a role of `lookup('application_closure', group_names)`, without the shared services another role provides, as the images area of the [Check](#check-) does.
A service that declares `custom` runs the `<name>_custom` image its role builds: the playbook skips that image, lists it as built by the role, and pulls the `image` and `version` the service declares, the base of the build.
A role that builds an image without declaring `custom` names no built image in its configuration: its declared images are pulled, its built image is neither pulled nor listed.
The list holds no sidecar image a compose template takes from a role outside the closure: the redis of a role with an embedded redis or an SSO proxy (`svc-db-redis`), the memcached of OpenProject and Zammad (`svc-db-memcached`), an app-local database its role pins no image for (`svc-db-postgres`, `svc-db-mariadb`), and a local object store.
The deploy pulls these small images itself when the host lacks them.

[pull.sh](files/pull.sh) runs `docker pull` for every image, also for one the host already has, and touches no container.
A failed pull is retried three times, ten seconds apart, and an attempt that runs longer than an hour, scaled by `TIMEOUT_FACTOR`, fails without a retry.
The play ends with the images pulled, the images whose pull changed nothing, the images the roles build, and every image whose pull still failed with the registry's error.
One failed image fails the play, so `failed=0` means every listed image is present on the host.
