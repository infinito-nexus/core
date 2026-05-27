# Backup Remote to Local

## Description

A scheduled pull-style backup that replicates the backup trees of one or more remote provider hosts onto this host via SSH + rsync.
The receiving side is the trust anchor: each retrieval is a discrete snapshot, hard-linked against the previous one, with a retry loop guarding against transient network failures.

## Overview

This role deploys the Python pull script that talks to each remote provider, installs the systemd service that drives it on the configured schedule (`SYS_SCHEDULE_BACKUP_REMOTE_TO_LOCAL`), and serialises the run against the rest of the manipulation group via `sys-lock`.
The remote side must expose a chrooted SSH/SFTP endpoint that publishes its backup tree: deploy [user-backup](../user-backup/) for the chrooted pull account and [sys-ctl-cln-bkps](../sys-ctl-cln-bkps/) to keep the published tree bounded.

## Features

- **Pull-only trust model:** the local host owns the SSH session; provider hosts never gain credentials on this side.
- **Retry-with-backoff:** transient SSH/rsync failures retry up to twelve times across a long window before surfacing as a hard failure.
- **Snapshot-aware:** rsync `--link-dest` against the previous local snapshot deduplicates unchanged files.
- **Schedule-coordinated:** the systemd unit is part of the global manipulation group, so it never races backup/cleanup/repair jobs on the same host.

## Further Resources

- [How I backup dedicated root servers](https://blog.veen.world/2020/12/26/how-i-backup-dedicated-root-servers/)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
