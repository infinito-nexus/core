# Run Cancellation 🚫

Shell helpers that cancel in-progress GitHub Actions workflow runs in response to repository lifecycle events.

## Scope 📋

This directory contains helpers invoked from workflows that listen on `pull_request_target: closed`, `pull_request_target: converted_to_draft`, and `delete`. The helpers call the GitHub Actions API to cancel runs whose original trigger is no longer relevant (a closed PR, a deleted branch). Helpers MUST NOT be called from workflows that have not received the corresponding lifecycle event, because cancelling unrelated runs would mask real failures and waste accumulated work.

For the workflow catalog that drives these calls see [workflows.md](../../../docs/contributing/tools/github/actions/workflows.md).
