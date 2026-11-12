# Lint Scripts

This directory contains scripts that run repository lint checks.

- 🧹 Execute focused lint checks for workflows, Ansible, Python, and shell scripts
- 🔎 Keep lint entry points small, explicit, and callable from `make`
- ✅ Separate lint execution from tool installation and environment bootstrap

## Changed files only 🎯

Outside CI, [wrapper.sh](wrapper.sh) lists every file changed since the merge-base of `HEAD` and `INFINITO_LINT_DIFF_BASE` (default `origin/main`, untracked files included) and hands the list to the container as `LINT_DIFF_FILES`. The `ansible`, `javascript`, `markdown`, `mermaid`, `shellcheck` and `sql` lints, and the matching workers of `autoformat`, then check only those files. They check every file again when the list names their own configuration or a shared lint script, when `INFINITO_LINT_DIFF_BASE` is empty or has no merge-base, and in CI. The rules live in [diff/files.sh](diff/files.sh).

`lint-ansible` additionally skips ansible-lint while the tree matches the last green run, which `autoformat` records after a clean `ansible-lint --fix` ([ansible/stamp.sh](ansible/stamp.sh)); the playbook syntax check always runs.

The scope of this folder is lint execution.
Tool installation belongs in `scripts/install`, while build and test workflows should stay in their dedicated script directories.
