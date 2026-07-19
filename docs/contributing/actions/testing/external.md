# External Tests 🌐

External tests depend on live third-party systems such as Docker Hub,
GHCR, or other external services. Run them with `make test-external`.

## Goal 🎯

- You MUST use external tests only when the behavior depends on a live third-party
  system and a hermetic unit, lint, or integration test would not verify the
  real condition.
- You MUST keep external tests outside the default `make test` flow so normal
  validation stays reproducible without third-party network access.
- You SHOULD keep external tests focused, advisory, and easy to run on demand.

## Location 📁

- External tests MUST live under `tests/external/`.
- You SHOULD group them by dependency family such as `tests/external/update/`
  or `tests/external/github/` when more than one test exists.
- Every external test directory MUST contain `__init__.py` so repository-wide
  test structure checks keep passing.

## Requirements 📋

- You MUST document in the test file why the check is external and what live
  dependency it contacts.
- You MUST NOT move an external test into `tests/lint/`, `tests/unit/`, or
  `tests/integration/` just for convenience when it still depends on live
  third-party state.
- External tests MAY emit warnings instead of hard failures when the goal is
  advisory freshness reporting rather than merge-blocking correctness.
- You SHOULD keep network traffic narrow and query each external dependency only
  as much as needed for a meaningful result.
- [test_urls_reachable.py](../../../../tests/external/repository/test_urls_reachable.py)
  scans git-tracked plus untracked-but-not-ignored text files for literal
  public `http://` and `https://` URLs.
- The URL reachability check skips template placeholders and reserved local or
  example hosts such as `localhost` and `*.example`.
- The URL reachability check treats HTTP `401`, `403`, and `405` as reachable
  (auth-gated or method-restricted servers, not dead links).
- The URL reachability check emits warning annotations for HTTP `429`, `500`,
  and `503` (rate-limited or temporarily unavailable) via
  [`utils.annotations.message`](../../../../utils/annotations/message.py).
- The URL reachability check treats read and connect timeouts as warnings.
- All other `4xx`/`5xx` codes and connection errors (DNS, SSL) fail the test.

## Suppression Comments 🚫

Lint and external checks share a single per-item suppression syntax based on
`# noqa` / `# nocheck` markers. The full grammar, position semantics, and the
catalog of rule keys live at [suppression.md](suppression.md).

## Running 🏃

Use the dedicated make target:

```bash
make test-external
```

To scope the run to one file:

```bash
make test-external INFINITO_TEST_PATTERN=test_image_versions.py
```

## CI Workflow 🤖

External tests run inside `.github/workflows/test.yml` via `make test`.
It MAY be triggered manually and is intentionally separate from the default
`make test` flow. It is also wired into the orchestrated code-testing gate in
CI so the live check can run there without changing local default validation.
