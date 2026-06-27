# GitHub Workflow Helpers 🔧

This directory holds the shell helpers that GitHub Actions workflows under [`.github/workflows/`](../../.github/workflows/) call. Helpers are grouped by responsibility into subfolders so each workflow file pulls only from the clusters it actually needs.

## Subfolders 🗂️

| Subfolder | Responsibility |
|---|---|
| [runner/](runner/) | Host-runner hygiene around image builds and deploys (disk, swap, Docker daemon, diagnostics). |
| [cancel/](cancel/) | Cancellation of in-progress workflow runs on PR-close and branch-delete events. |
| [cleanup/](cleanup/) | Scheduled repository maintenance that prunes stale GitHub resources. |
| [resolve/](resolve/) | Derivation of structured workflow inputs and outputs from repository state. |
| [sync/](sync/) | Ref synchronization before workflow jobs derive CI scope from git history. |
| [update/](update/) | The scheduled `Update: Versions` pipeline (version bumps and PR open/refresh). |
| [release/](release/) | Release-time gates that decide whether a tagged commit may be released. |

A new helper MUST live in the subfolder that matches its responsibility. New responsibilities MAY motivate a new subfolder, but MUST NOT flatten back into the top level.

For the workflow catalog see [workflows.md](../../docs/contributing/tools/github/actions/workflows.md). For the repository Make target index see [make.md](../../docs/contributing/tools/make.md).
