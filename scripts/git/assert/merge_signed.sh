#!/usr/bin/env bash
set -euo pipefail

# Pre-merge-commit gate: every commit the merge brings in (HEAD..MERGE_HEAD)
# must carry a signature. `git log %G?` yields N for unsigned; any other
# status counts as signed, matching the test-signed HEAD gate.

git_dir="$(git rev-parse --git-dir)"
if [ ! -f "${git_dir}/MERGE_HEAD" ]; then
	echo "❌ No merge in progress (MERGE_HEAD missing); this gate runs during git merge." >&2
	exit 1
fi

unsigned="$(git log --pretty='%H %G? %s' HEAD..MERGE_HEAD | awk '$2 == "N"')"
if [ -n "${unsigned}" ]; then
	echo "❌ Unsigned commit(s) coming in from the merged branch:" >&2
	printf '%s\n' "${unsigned}" >&2
	echo "Sign them (git rebase --exec 'git commit --amend --no-edit -S' or git-sign-push) and retry the merge." >&2
	exit 1
fi

count="$(git rev-list --count HEAD..MERGE_HEAD)"
echo "✅ All ${count} incoming commit(s) are signed."
