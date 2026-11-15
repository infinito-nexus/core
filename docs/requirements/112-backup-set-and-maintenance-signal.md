# 112 - Backup Set and Maintenance Signal

## User Story

As the operator of a platform whose workspaces span Semaphore, OpenBao, SeaweedFS, Gitea and Keycloak, I want one backup generation plus the inventory's secrets to restore all of them together, proven by a drill, and a signal the store can read while a backup stops one of them, so that a restore never leaves a state undecryptable or a key unreadable, and no task starts against a stopped service.

## Background

The store's requirement 062 (`infinito-nexus/gui: docs/requirements/062-slim-store-orders-provisioned-through-platform-roles.md`, criteria 062:146 and 062:179) needs this core side.

### Today

- `svc-bkp-volume-2-local` copies every container's volumes into one generation per run, dumps the databases that consumers registered, keeps containers with `stop_required: false` running and stops the others briefly (`roles/svc-bkp-volume-2-local/README.md`). On a btrfs data root it stops nothing and copies from one snapshot (`README.md`). A systemd unit runs it on a schedule and waits for the other backup groups through `sys-lock` (`README.md`). The no-stop list is built from the services files (`roles/svc-bkp-volume-2-local/vars/main.yml`).
- What stops during a live copy:

  | Application | `stop_required` | Source |
  | --- | --- | --- |
  | OpenBao | true | `roles/web-app-openbao/meta/services.yml` |
  | SeaweedFS | true | `roles/web-svc-seaweedfs/meta/services.yml` |
  | Semaphore and its runner | false | `roles/web-app-semaphore/meta/services.yml` |
  | Gitea | false | `roles/web-app-gitea/meta/services.yml` |

  So store item 11's "OpenBao, SeaweedFS or Gitea down for a backup" holds for OpenBao and SeaweedFS only.
- Two secrets a restore needs are not in any volume. Semaphore's access key encryption key is an inventory credential (`roles/web-app-semaphore/meta/secrets.yml`, `roles/web-app-semaphore/vars/main.yml`, `roles/web-app-semaphore/templates/env.j2`); without it every key stored in Semaphore's database stays unreadable. OpenBao's static seal key is one as well (`roles/web-app-openbao/meta/secrets.yml`, decided in [053](053-web-app-openbao.md)); without it the restored storage never unseals.
- The role's deploy drill backs up, seeds a marker, takes every project down, restores and lets the host's container health service judge (`roles/svc-bkp-volume-2-local/files/test/README.md`, `restore_cycle.sh`).
- Nothing tells another service that a backup has stopped a container.

## Decisions

1. **The backup set is one generation plus the inventory.** A restore takes one generation of `svc-bkp-volume-2-local`, which holds every volume and database dump of the stack host, and the inventory's credentials, the access key encryption key and the seal key among them. The workspace resources of 102 to 111 live in these. No second backup of any of them is part of the set.
2. **`workspace apply` after a restore.** Some files live on the host, outside the volumes: the runner compose projects and token files (102), `identities.d` of SeaweedFS (108) and the egress lists. After a restore, `workspace apply` runs for every workspace project in Semaphore and rebuilds them from Semaphore's database and OpenBao. It keeps every token and key that OpenBao and the database hold, as a second `apply` always does.
3. **The maintenance signal (fields: operator pick, 2026-11-13).** Before its first container stop, the backup unit writes `/run/infinito/maintenance/backup.json` by atomic rename. The document is a JSON object with exactly three fields:
   - `applications`: the application ids (`web-app-openbao`, `web-svc-seaweedfs`) of the applications this run stops, taken from their `stop_required`;
   - `started`: the start time of the run;
   - `until`: the start plus `SYS_TIMEOUT_BACKUP_SERVICES`.

   Both times are RFC 3339 with a numeric offset in UTC (`2026-11-13T02:00:00+00:00`). After the last start the unit writes the document with an empty `applications`, and an `ExecStopPost` does the same when the run fails. On a snapshot run, which stops nothing, the list stays empty. `/run` is a `tmpfs`, so a reboot clears the document. A reader MUST treat a missing document, an empty list and a document past its `until` as no maintenance. A reader MUST take the stopped applications from the list and MUST NOT assume a fixed set: Gitea and Semaphore keep running during a copy (`roles/web-app-gitea/meta/services.yml`, Today), so they appear only when their `stop_required` turns true.
4. **Who reads it.** A role that sets `services.maintenance.enabled` in its `meta/services.yml` gets `/run/infinito/maintenance` mounted read-only. The store's role sets it. The document is not served on any public vhost: unlike `/status.json` (`roles/sys-ctl-hlth-webserver/README.md`), it would publish the platform's backup window.
5. **The drill covers the workspace set.** The deploy drill of `svc-bkp-volume-2-local` gains a workspace pass. It runs when the stack holds `web-app-semaphore`, `web-app-openbao`, `web-svc-seaweedfs` and `web-app-gitea` with workspaces on.

## Acceptance Criteria

### Backup set

- [ ] A generation taken on a stack with two workspaces holds the Semaphore database dump, the Keycloak database dump, and the volumes of OpenBao, SeaweedFS and Gitea (`test_one_generation_holds_the_workspace_set` in `tests/unit/python/roles/svc-bkp-volume-2-local/test_workspace_set.py`, over the backup subjects the role derives; the generation listing in the drill log). The derived half holds in compose and swarm-local (`test_workspace_set.py`); the drill log listing (`workspace drill: step 3` in `files/test/workspace/pass.sh`) waits for a live run.
- [ ] The README of `svc-bkp-volume-2-local` names the two inventory credentials a restore needs beside the generation. A new `roles/web-app-semaphore/Administration.md` names Semaphore as a single point of failure for every workspace, with the restore time the drill measured (store criterion 062:179; `test_the_readme_names_the_restore_credentials` in `tests/unit/python/roles/svc-bkp-volume-2-local/test_readme.py` and `test_administration_names_the_single_point_of_failure` in `tests/unit/python/roles/web-app-semaphore/test_administration.py`). Both names hold (`test_readme.py`; `web-app-semaphore/test_administration.py`); the measured restore time waits for the drill's `workspace drill: restore took <seconds>s` line.

### Restore drill

- [ ] The workspace pass of the drill runs these steps:
  1. Create two workspaces.
  2. Provision one server through the Incus e2e target (109), so a state exists.
  3. Back up.
  4. Take every project down and restore the generation.
  5. Run `workspace apply` for both workspaces.

  It then proves each of these: a workspace task clones its repository with the key stored in Semaphore; OpenBao unseals with the inventory's seal key; the transit key decrypts the state, so `tofu plan` reports no change; SeaweedFS serves every object version of the state bucket; Gitea serves both repositories; and Keycloak holds both organizations with their groups. Each step and proof logs its own line (`workspace drill: one generation restores every workspace` in `roles/svc-bkp-volume-2-local/files/test/restore_cycle.sh`, its lines in the drill log).
- [ ] A drill against a restore without the access key encryption key fails at the clone step, and one without the seal key fails at the unseal step. Both are negative controls of the same pass (`workspace drill: a missing inventory secret fails the restore` in `restore_cycle.sh`).

### Maintenance signal

- [ ] During a live backup run, `backup.json` lists `web-app-openbao` and `web-svc-seaweedfs` before either stops, never `web-app-gitea` or `web-app-semaphore`, and lists nothing after both run again. The drill polls it during a forced run and records both states in order (`maintenance: the signal leads every stop and trails every start` in `roles/svc-bkp-volume-2-local/files/test/verify/maintenance.sh`, its lines in the drill log).
- [x] The rendered document holds exactly `applications`, `started` and `until`, and both times parse as RFC 3339 with a numeric offset. A planted fourth field and a time without an offset must fail (`test_the_signal_holds_its_three_fields` and its controls in `tests/unit/python/roles/svc-bkp-volume-2-local/test_maintenance.py`). (`test_maintenance.py`.)
- [x] A failed run leaves the document with no applications. The reader helper the store uses reports no maintenance for a missing document, an empty list and a document past its `until`, one case each (`test_a_failed_run_clears_the_signal` and `test_a_signal_past_until_is_stale` in `tests/unit/python/roles/svc-bkp-volume-2-local/test_maintenance.py`).- [x] On a snapshot run the document lists no application during the whole run (`test_a_snapshot_run_announces_no_stop` in `test_maintenance.py`). (`test_maintenance.py`; `probe/snapshot.sh` asserts `[]` per snapshot case on the deployed launcher.)
- [x] Only roles that set `services.maintenance.enabled` mount the directory, read-only, and no vhost serves the document (`test_the_signal_is_mounted_read_only_for_its_consumers` and `test_no_vhost_serves_the_signal` in `tests/unit/python/roles/svc-bkp-volume-2-local/test_maintenance.py`). (`test_maintenance.py`.)

### Documentation

- [x] The [README](../../roles/svc-bkp-volume-2-local/README.md) documents the backup set, the restore order with `workspace apply`, the signal's path, fields and lifetime, and its consumer flag (`test_the_readme_names_the_maintenance_signal` in `tests/unit/python/roles/svc-bkp-volume-2-local/test_readme.py`). (`test_readme.py`.)
