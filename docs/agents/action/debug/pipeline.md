# Pipeline Debugging

Use this page for the fully automated triage of a GitHub Actions / CI run failure where the agent fetches all logs and artefacts itself via `gh`. For local deploy failures, see [local.md](local.md). If the operator has manually placed log files in the repository workdir, see [log.md](log.md) instead.

## Triage

- If a CI run is still progressing and the user has not asked you to change course, you MUST wait for it to finish before starting triage.

1. You MUST identify the failing parent run from the GitHub Actions URL the operator provided. Extract `<run-id>` from the last numeric path segment of `.../actions/runs/<run-id>`.
   - You MUST enumerate every failed job under the parent run, including matrix jobs and reusable-workflow jobs, via `gh run view <run-id> --json jobs --jq '.jobs[] | select(.conclusion=="failure")'`.
   - You MUST also enumerate any failed sibling runs dispatched from the same commit via `gh run list --commit "$(gh run view <run-id> --json headSha --jq .headSha)" --json databaseId,name,conclusion --jq '.[] | select(.conclusion=="failure")'`, then repeat the job enumeration for each.
   - For each failed run you MUST download the logs of every failed job via `gh run view <child-run-id> --log-failed > /tmp/<child-run-id>-job-logs.txt`, and the uploaded artefacts via `gh run download <child-run-id> --dir /tmp/<child-run-id>-artefacts`.
   - The broader CI debugging workflow is documented in [ci.md](../../../contributing/actions/debugging/ci.md). You MUST NOT proceed with partial coverage.
2. You MUST inspect each downloaded log directly and categorize what each failure is about (failing run, failing job, role, step, error class). If the error class is a Playwright failure, you MUST follow [Playwright Failures](#playwright-failures) for the asset analysis before continuing.
3. You MUST determine whether each failure is specific to the current branch or also reproduces elsewhere:
   - You MUST determine the comparison branch automatically when possible (the PR base branch from `gh pr view --json baseRefName`, or the configured upstream from `git rev-parse --abbrev-ref @{u}`). If neither is available, you MUST ask the operator which branch to compare against before proceeding.
   - You MUST `git fetch` the resolved comparison branch and inspect its recent commits and CI history.
   - You MUST evaluate whether the failure could plausibly originate from commits on the current branch.
4. You MUST classify each failure into one of two buckets:
   - Branch-caused: the failure is plausibly produced by commits on the current branch and MUST be debugged locally per [Branch-Caused Failures](#branch-caused-failures).
   - External: the failure reproduces independently of the current branch and MUST be reported as an issue per [External Failures](#external-failures).
5. You MUST process the buckets in order: first complete the initial-pass actions under [External Failures](#external-failures) for every failure classified as external, then iterate over [Branch-Caused Failures](#branch-caused-failures). Issues filed afterwards for unresolvable branch-caused failures (per the last bullet of [Branch-Caused Failures](#branch-caused-failures)) reuse the External Failures procedure but are NOT part of this initial pass.

## External Failures

- For each external failure, you MUST first search [s.infinito.nexus/issues](https://s.infinito.nexus/issues) for a matching open issue using `gh issue list --search "<exact error message>"`. A match requires the exact same error message line from the log to appear in the existing issue. Looser symptom-only matches MUST NOT be treated as duplicates.
- If a matching issue exists, you MUST add a comment via `gh issue comment <issue-number> --body-file <log-excerpt-file>` that contains the relevant log excerpt and links the full GitHub Actions run URL for every newly observed run.
- If no matching issue exists, you MUST file a new one via `gh issue create --title <title> --body-file <body-file> --label <labels>`. The YAML issue form [bug_report.yml](../../../../.github/ISSUE_TEMPLATE/bug_report.yml) cannot be populated headlessly through `--template`, so `<title>`, `<labels>`, and the section structure inside `<body-file>` MUST mirror exactly what that template prescribes. You MUST place the relevant log excerpt under the section that template dedicates to logs and link the full GitHub Actions run URL for every affected job.
- If multiple runs across multiple branches share the same external failure, you MUST link all of them in the issue body or comment.

## Branch-Caused Failures

- If the current branch is `main` or `master`, before any debug iteration begins you MUST file a tracking issue for every observed failure using the [External Failures](#external-failures) procedure (search first, comment if matched, otherwise create new). For branch-caused failures, the resulting issue number MUST be used as `<ticket-id>` when creating the working branch with the `fix/` prefix per [branch.md](../../../contributing/artefact/git/branch.md). All iteration work, commits, and the push at the end MUST happen on that fix branch.
- You MUST iterate on each branch-caused failure per [Role Loop](../iteration/role.md), processing affected roles in ascending alphabetical order until the root cause is fixed.
- If multiple roles share the same root cause, you MUST first deploy them together via the `apps="<role-a> <role-b>"` form described in [Role Loop](../iteration/role.md), then run the alphabetically first role of the batch individually as the exemplary single-app deploy.
- You MUST NOT pass more than 7 roles to a single `apps=...` invocation, regardless of how many roles share the same root cause. If more than 7 roles share a root cause, you MUST split them into batches of at most 7. Within each batch, list roles in ascending alphabetical order. Process batches in ascending alphabetical order of their first role, sequentially. Once the shared root cause is verified fixed in one batch, you MUST skip all remaining batches that share that same root cause.
- After each grouped-apps deploy plus its exemplary single-app deploy, you MUST ask the operator to commit the fix per [commit.md](../commit.md).
- If the operator declines the commit request or signals to skip, you MUST continue with the next root cause without committing and proceed until all root causes are addressed.
- Once all branch-caused failures are addressed, you MUST `git push` the branch on which you iterated to the operator's fork. For any root cause you could not resolve, you MUST file a separate issue per [External Failures](#external-failures) describing what was attempted and why it remains unresolved.

## Playwright Failures

This section describes how to analyze Playwright failures within a CI triage. Playwright assets are downloaded as part of Step 1's `gh run download` invocation and live under `/tmp/<child-run-id>-artefacts/`.

- You MUST output the storage path of the Playwright assets for the affected `<child-run-id>`.
- You MUST analyze the Playwright assets together with the matching `/tmp/<child-run-id>-job-logs.txt`.
