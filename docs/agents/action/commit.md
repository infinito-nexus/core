# Committing

- You MUST run `make autoformat` before every commit. If `make autoformat` modifies any files that were already staged, you MUST re-stage those files before running the commit.
- You MUST commit only after all required checks pass.
- You MUST NOT commit automatically without explicit confirmation from the user. You MUST ask before committing.
- `make test` is run automatically by pre-commit before every commit when staged changes include at least one file that is not `.md`, `.rst`, or `.txt`. You do NOT need to run it manually. The pre-commit hook enforces it.
- If the pre-commit hook fails, fix the underlying issue and retry the commit.
- You MUST NOT use `--no-verify` unless the user gives a direct, unambiguous instruction to bypass the hook (e.g. "skip the hook", "bypass pre-commit").
- Generic commit requests (such as "commit the changes", "commit", or any equivalent in any language) MUST NOT qualify. When in doubt, you MUST NOT use `--no-verify`.
- Permission to use `--no-verify` is valid for ONE commit only. You MUST NOT carry it over to subsequent commits unless the user explicitly grants it again.
- For markdown/reStructuredText/text-only changes, pre-commit skips `make test` automatically. You MUST NOT run it manually either.
