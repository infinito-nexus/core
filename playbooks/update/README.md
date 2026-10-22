# Update Report 📋

This playbook collects the state of an Infinito.Nexus host of any version as the starting point of an update.
It only reads and changes nothing on the host.

## Run 🚀

Run from the repository root:

```bash
ansible-playbook -i <inventory> playbooks/update/report.yml
```

The report of every host is saved on the controller at `/tmp/infinito-update-report-<host>.txt`.
The host needs no Python, because the report runs as a plain shell script.

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
