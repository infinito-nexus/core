# 119 - State Backend Keys from a Private File

## User Story

As the operator of a platform whose provision runs keep their state in SeaweedFS and may also write Route 53 records, I want OpenTofu's S3 backend to take its keys from a private file of the task, so that the backend keys never sit in an environment variable another provider reads, never appear on a command line and do not outlive the task.

## Background

The store found that the backend keys collide with the `route53` flavor when both use `AWS_*` variables, and asked on 2026-11-13, as item (d) of its OpenTofu follow-ups, for `-backend-config`; the operator took it the same day.

### Today

- The S3 backend of a provision run uses the workspace's state bucket ([104](104-runner-image-opentofu-and-root-modules.md) decision 7). Its keys are those of the identity `ws-<id>-provision` at `tenant/data/ws-<id>-provision/s3` ([108](108-seaweedfs-per-workspace-state-buckets.md) decision 2). 104 does not say how they reach OpenTofu.
- Under the `route53` flavor the `dns` module's `hashicorp/aws` provider writes the record with the workspace's IAM user (104 decision 9). In the store's modules (core sidetree `feature/iam-reqs/062-tofu-root-modules`, commit `286b3689f1`, `modules/dns-route53/main.tf.json`) that provider sets only its region, so it takes its keys from the `AWS_*` environment.
- The provision script clears every `TF_*` variable it did not set itself (104 decision 6).

### Upstream

| Fact | Source |
| --- | --- |
| The OpenTofu `v1.10.0` S3 backend takes `access_key` and `secret_key` as configuration attributes, and without them falls back to the AWS default chain, `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` first; so does the `hashicorp/aws` provider. | [backend.go:147-156](https://github.com/opentofu/opentofu/blob/v1.10.0/internal/backend/remote-state/s3/backend.go#L147-L156), [:724-731](https://github.com/opentofu/opentofu/blob/v1.10.0/internal/backend/remote-state/s3/backend.go#L724-L731), [OpenTofu S3 backend](https://opentofu.org/docs/language/settings/backends/s3/) |
| `tofu init` stores the whole backend configuration, values from `-backend-config` included, in `.terraform/terraform.tfstate` of the working directory. | [meta_backend.go:566](https://github.com/opentofu/opentofu/blob/v1.10.0/internal/command/meta_backend.go#L566), [:1073-1088](https://github.com/opentofu/opentofu/blob/v1.10.0/internal/command/meta_backend.go#L1073-L1088) |

## Decisions

1. **A private backend file.** The provision script, and the script of `dns ws-<id>` ([115](115-dns-record-for-bring-your-own-servers.md)), read the state keys from `tenant/data/ws-<id>-provision/s3` with the task's OpenBao token, write `access_key` and `secret_key` into a file in the task directory with mode `0600` under `umask 077`, and pass only its path to `tofu init` as `-backend-config=<path>`. The backend configuration names the keys itself, so it never falls back to the environment (Upstream).
2. **No key on an argument or in `AWS_*`.** No backend key is passed as `-backend-config=<key>=<value>` or in any other argument, and none is put into an environment variable. The script clears every `AWS_*` variable it did not set itself. Under `route53` it sets only the workspace IAM user's keys in `AWS_*`, for the `hashicorp/aws` provider (104 decision 9).
3. **Nothing outlives the task.** The script removes the task directory on every exit, success or failure, and with it the backend file and `.terraform/terraform.tfstate`, which holds the same keys (Upstream).

Rejected:

- Backend keys in `AWS_*`: the `hashicorp/aws` provider of `route53` would take them as its own, or the backend would take the Route 53 keys.
- `-backend-config=access_key=...` on the command line: every process of the runner's UID reads it from `/proc`, and a task log that records the command holds it.
- Keys in the backend block of the root: the root is core code shared by every workspace.

## Acceptance Criteria

- [x] The script writes the backend file with mode `0640` (`sandbox.FILE_MODE`, so the run's sandbox reads it through the group of its uid and no other uid does, [135](135-opentofu-sandbox-per-run.md)), passes exactly one `-backend-config` argument whose value is that path, and a shim that records argv and environment of `tofu` finds no key in either; under `route53` the environment holds only the IAM user's `AWS_*` keys. Negative controls pass a key on argv and in `AWS_ACCESS_KEY_ID`, and each must fail (`test_backend_keys_come_from_a_private_file`, `test_negative_control_a_key_on_argv_fails`, `test_negative_control_a_key_in_aws_access_key_id_fails` and `test_route53_sets_only_the_iam_user_keys` in `tests/unit/python/roles/web-app-semaphore/files/test_provision_sh.py`, 22 tests green at the lane tip; the planted regressions that put the key on argv, keep `AWS_*` from the environment or write the file world-readable fail the first).
- [x] After a successful and after a failed run, the task directory, the backend file and `.terraform/` are gone (`test_the_task_directory_is_removed_on_every_exit` in `test_provision_sh.py`, over a success and failures in `init` and `apply`; the planted regression that keeps the task directory fails it).
- [ ] Under `route53`, on a row with AWS credentials, one provision writes its state to SeaweedFS and its record to Route 53 (`provision: route53 and the state backend keep their own keys` in `roles/web-app-semaphore/files/playwright/test-provision.js`).
- [x] The [README](../../roles/web-app-semaphore/README.md) documents where the backend keys come from and that they never enter the environment or an argument (`roles/web-app-semaphore/README.md`).
