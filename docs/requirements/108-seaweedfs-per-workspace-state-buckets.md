# 108 - SeaweedFS Per-Workspace State Buckets

## User Story

As the operator of a platform that keeps each workspace's OpenTofu state in SeaweedFS, I want `web-svc-seaweedfs` to create a versioned bucket and an S3 identity per workspace while it runs, to never answer an S3 request before its identities are loaded, and to hold OpenTofu's lock when two writers race, so that each workspace's state is reachable only by its own provision runs and survives a lost lock or an overwrite.

## Background

The store's requirement 062 (`infinito-nexus/gui: docs/requirements/062-slim-store-orders-provisioned-through-platform-roles.md`, decision 11, criteria 062:84 and 062:134) needs this core side. The state layout is in 104.

### Today

- The S3 identities are rendered once per deploy: the admin and one identity per object-store consumer with `Read`, `Write`, `WriteAcp`, `List` and `Tagging` on its bucket (`roles/web-svc-seaweedfs/templates/s3.json.j2`).
- Buckets are created by the deploy through `weed shell s3.bucket.create` (`roles/web-svc-seaweedfs/tasks/01_init_consumer.yml`).
- The server runs `weed server ... -filer -s3 -s3.config=<file>` (`plugins/filter/seaweedfs.py`, used at `roles/web-svc-seaweedfs/templates/compose.yml.j2`). The file is a single-file bind mount (`roles/web-svc-seaweedfs/meta/volumes.yml`).
- `-volume.max` is sized at deploy time for the deploy's consumers: `(collections + 1) * 7` (`volume_slots`, `plugins/filter/seaweedfs.py`; the count at `compose.yml.j2`). A bucket created later gets no slot of its own.
- SeaweedFS `4.53` is pinned (`roles/web-svc-seaweedfs/meta/services.yml`) and stops for its backup (`services.yml`).

### Upstream

| Fact | Source |
| --- | --- |
| With no identity configured, the S3 gateway allows every request. | [SeaweedFS S3 credentials](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API) |
| The `-s3.config` file is read at start and again on `SIGHUP`. An identity source of higher priority replaces a lower one without merging; the file outranks the filer-stored configuration. | [SeaweedFS S3 credentials](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API) |
| Bucket versioning and the conditional headers of `PutObject` (`If-None-Match`) are supported. | [SeaweedFS S3 API](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API) |
| A conditional `PutObject` on a versioned bucket was accepted but unreadable after a racing `DELETE` up to 4.52, reported by an OpenTofu `use_lockfile` user; the fix ships in 4.53. | [seaweedfs#12453](https://github.com/seaweedfs/seaweedfs/issues/12453), [seaweedfs#12454](https://github.com/seaweedfs/seaweedfs/pull/12454) |
| `fs.configure` sets the collection and the volume growth count for a path prefix. | [SeaweedFS path-specific configuration](https://github.com/seaweedfs/seaweedfs/wiki/Path-Specific-Configuration) |
| A file bind-mounted on its own keeps the inode it had when the container started, so a host-side rename replaces nothing inside the container. | [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/) |

## Decisions

1. **A bucket per workspace at runtime.** `workspace apply` (102) runs the role's `tasks/workspace.yml`. It creates the bucket `ws-<id>-state` through `weed shell s3.bucket.create`, as the deploy does for consumers, and turns versioning on with the admin identity. It needs no redeploy and no container restart.
2. **An identity per workspace.** `apply` creates the identity `ws-<id>-provision` with `Read`, `Write` and `List` on that bucket only: no `Admin`, no `WriteAcp`, no `Tagging`. It generates the keys once. It keeps them in OpenBao at `tenant/data/ws-<id>-provision/s3` (105), which the provision runner reads, and in `identities.d/ws-<id>.json`, mode `0600`, in the role's volume directory. A second `apply` keeps the keys.
3. **Fail-closed reload.** `s3.json` is assembled from the inventory identities of `s3.json.j2` plus every file of `identities.d`. It always holds the admin identity, so it is never empty and the gateway never falls back to allowing every request. The container mounts the directory that holds `s3.json`, not the file alone. `apply` and the deploy write the new file next to it, rename it into place and send `SIGHUP`. The filer-stored identity configuration stays unused, because a server started without the file would allow every request until the filer copy loads.
4. **Volume slots.** Workspace buckets grow one volume at a time: `fs.configure -locationPrefix=/buckets/ws- -volumeGrowthCount=1`. `-volume.max` reserves one slot per workspace up to `services.seaweedfs.workspaces.max`, a key of `roles/web-svc-seaweedfs/meta/services.yml`. `apply` refuses a workspace beyond it with a message that names the key.
5. **The lock.** The pin stays at 4.53 or later, the first release with the fix for conditional writes on versioned buckets. A test holds that floor. The two-writer test runs against a versioned bucket, the case the bug hit.
6. **Destroy.** `workspace destroy` first removes the identity and reloads, so access ends at once. It then deletes every object version and the bucket, and refuses while the bucket still holds a state file, because 104's destroy runs first.

## Acceptance Criteria

### Buckets and identities

- [ ] `workspace apply` creates `ws-<id>-state` with versioning `Enabled` (as `GetBucketVersioning` reports it) and the identity `ws-<id>-provision`. The SeaweedFS container's start time is unchanged by it (`workspace buckets: apply creates a versioned bucket without a restart` in `roles/web-svc-seaweedfs/files/playwright/test-workspace-buckets.js`).
- [ ] The workspace identity reads, writes and lists its own bucket. It gets `AccessDenied` on another workspace's bucket, on a consumer bucket, on `CreateBucket` and on `PutBucketAcl` (`workspace buckets: an identity reaches only its own bucket` in `test-workspace-buckets.js`).
- [ ] A second `apply` keeps the keys and the bucket's objects (`workspace buckets: a second apply changes nothing` in `test-workspace-buckets.js`).
- [x] The rendered identity of a workspace has exactly `Read`, `Write` and `List` on its bucket (`test_a_workspace_identity_holds_three_actions_on_its_bucket` in `tests/unit/python/roles/web-svc-seaweedfs/templates/test_s3_identities.py`). _(Renders `templates/s3.json.j2` with one workspace record; the base template and a template that skips `seaweedfs_s3_identities` each turn the test red.)_

### Fail-closed

- [x] The assembled `s3.json` always holds the admin identity, also with no consumer and no workspace. An assembly without it fails the render (`test_the_assembly_always_holds_the_admin` and `test_an_assembly_without_the_admin_fails` in `test_s3_identities.py`). _(The `seaweedfs_s3_identities` filter refuses an identity set without the `Admin` identity; the base template and a template that skips the filter each render without failing and turn the test red.)_
- [x] The compose service mounts the directory of `s3.json`, never the file alone (`test_the_s3_config_is_mounted_as_a_directory` in `tests/unit/python/roles/web-svc-seaweedfs/test_volumes.py`). _(`meta/volumes.yml` binds the `s3` directory read-only at `/etc/seaweedfs/s3`; the base single-file config and a bind target on `s3.json` each turn the test red.)_
- [ ] An anonymous `PutObject` sent in a loop while the server restarts never succeeds: every answer is a refusal or no answer at all (`check_restart_serves_no_anonymous_write` of the stack-host probe `roles/web-svc-seaweedfs/files/test/probe.py`, which restarts the container and requires the loop to meet the engine down and back; `test_no_anonymous_write_is_served_across_a_restart` and its negative control `test_negative_control_a_write_served_before_the_identities_load_is_caught` in `tests/unit/python/roles/web-svc-seaweedfs/files/test_probe.py`). SeaweedFS stays out of app-control.
- [ ] After `apply` adds an identity, the next request with its keys succeeds without a restart. After `destroy` removes it, the next request fails (`workspace buckets: reload adds and removes identities live` in `test-workspace-buckets.js`).

### Lock

- [ ] On a versioned workspace bucket, two concurrent `PutObject` calls with `If-None-Match: *` for the same `.tflock` key end with one `200` and one `412`, and the stored object is readable (`workspace buckets: one of two conditional writers wins` in `test-workspace-buckets.js`).
- [x] The pinned version is 4.53 or later (`test_the_pin_carries_the_conditional_write_fix` in `tests/unit/python/roles/web-svc-seaweedfs/meta/test_version_pin.py`). _(A planted pin of 4.52 turns the test red.)_
- [ ] The OpenTofu two-writer test and the stale lock recovery of 104 pass against this bucket (104, `provision: a second writer waits for the lock` and `provision: unlock clears only a stale lock`).

### Capacity and destroy

- [x] `-volume.max` grows by one slot per workspace up to `services.seaweedfs.workspaces.max`, and `apply` refuses the workspace after the last slot with a message naming the key (`test_volume_slots_reserve_one_per_workspace` in `tests/unit/python/plugins/filter/test_seaweedfs.py`; `test_apply_refuses_a_workspace_beyond_the_maximum` in `tests/unit/python/roles/web-svc-seaweedfs/test_workspace.py`). _(`volume_slots` adds `services.seaweedfs.workspaces.max` to the consumer slots; the apply slot check runs before any write and evaluates the real `that` expression. The base `volume_slots`, a slot check that admits every workspace and a slot check moved after the writes each turn a test red.)_
- [ ] `destroy` refuses while the bucket holds a `.tfstate` object, and otherwise leaves neither the identity, the bucket nor any object version (`workspace buckets: destroy removes access first and then the bucket` in `test-workspace-buckets.js`).

### Documentation

- [x] The [README](../../roles/web-svc-seaweedfs/README.md) documents the workspace buckets, the identity actions, the fail-closed reload, the slot maximum and the version floor. _(Section "Workspace buckets" with "Fail-closed reload", "Slot maximum" and "Version floor".)_
