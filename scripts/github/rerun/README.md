# Run Reruns 🔁

Shell helpers that restart the unfinished parts of GitHub Actions workflow runs that were cancelled rather than completed.

## Scope 📋

This directory contains helpers invoked from scheduled workflows. They call the GitHub Actions API to rerun the failed jobs of a cancelled run, never the run as a whole, so the work that already succeeded is kept. A run is a candidate only while it is recent and below its attempt ceiling; both bounds are passed in by the calling workflow, because a sweep without them would resurrect abandoned branches and retry a permanently cancelled run forever.

Helpers MUST NOT rerun a run whose conclusion is `failure`. A real defect has to be fixed, not retried, and the [cancel](../cancel/README.md) helpers exist precisely so that a cancellation means "interrupted", not "broken".

For the workflow catalog that drives these calls see [workflows.md](../../../docs/contributing/tools/github/actions/workflows.md).
