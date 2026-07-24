# Local Deploy Debugging

Use this page when a local deploy fails. For automated GitHub Actions / CI triage, see [ci.md](ci.md). For inspecting log files the operator has manually placed in the repository workdir, see [log.md](log.md).

- You MUST debug from the live local output and local logs.
- If a local deploy is still progressing and the user has not asked you to change course, you MUST wait for it to finish instead of interrupting it.

## Retry Loop

- For the shared local retry loop, you MUST follow [Compose Loop](../iteration/compose.md).
