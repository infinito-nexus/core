# Upstream References 🔗

A patch or workaround for an upstream defect MUST carry an `upstream:` directive that names the upstream issue or pull request whose resolution makes it removable. The repository then notices when that item closes.

## Directive 📐

Place the directive on the workaround's line or directly above it, as the last line of the comment block that explains the workaround. Write one URL per directive and nothing after it. Several directives MAY stack when several items hold the workaround in place.

| File kind                                   | Form                                                                      |
| ------------------------------------------- | ------------------------------------------------------------------------- |
| Python, YAML, shell, Dockerfile, Ruby, conf | `# upstream: <url>`                                                       |
| JavaScript, TypeScript, Go, PHP             | `// upstream: <url>`                                                      |
| CSS                                         | `/* upstream: <url> */`                                                   |
| Jinja2                                      | `{# upstream: <url> #}`                                                   |
| Markdown, HTML                              | `<!-- upstream: <url> -->`                                                |
| `.patch`, `.diff`                           | `upstream: <url>` as a header line above the first `diff` or `---` line  |

- The comment prefix MUST open the line or follow whitespace. A prefix quoted at the start of a string literal or inside a markdown code span is not a directive.
- `<url>` MUST name one issue or pull request on a forge the external check can ask:

| Forge          | Hosts                                                      | Shape                                                                          |
| -------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------ |
| GitHub         | `github.com`                                               | `https://github.com/<owner>/<repo>/issues/<n>` or `.../pull/<n>`               |
| GitLab         | `gitlab.com` and self-hosted instances, subgroups allowed  | `https://<host>/<group>/<project>/-/issues/<n>` or `.../-/merge_requests/<n>`  |
| Forgejo, Gitea | `codeberg.org`, `gitea.com` and self-hosted instances      | `https://<host>/<owner>/<repo>/issues/<n>` or `.../pulls/<n>`                  |

- A fragment such as `#issuecomment-1` MAY follow the number. A query, a port, credentials or a deeper path such as `/files` MUST NOT.
- A GitLab work item URL (`/-/work_items/<n>`) MUST be written as `/-/issues/<n>`, which names the same item.
- An item on a tracker outside these forges (Jira, Bugzilla, Launchpad, Phabricator, Trac, a forum) cannot be referenced. Name it in the comment that explains the workaround instead.
- A directive MUST NOT be written before its upstream item exists. A placeholder fails the lint below.

## Checks 🔍

| Check                                                                                                  | Suite                           | Effect                                                                                                                                                         |
| ------------------------------------------------------------------------------------------------------ | ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [test_comments_valid.py](../../../../tests/lint/repository/test_comments_valid.py)                     | lint                            | Accepts a comment whose text opens with `upstream:` as a tool directive, like `nocheck:`.                                                                     |
| [test_upstream_directives.py](../../../../tests/lint/repository/test_upstream_directives.py)           | lint                            | Fails on a directive whose text is not exactly one accepted URL. Its negative control proves that every rejected shape is reported in every comment syntax. |
| [test_upstream_references.py](../../../../tests/external/repository/test_upstream_references.py)       | external, `make test-external`  | Asks each item's tracker whether it is still open, as described below.                                                                                        |
| [test_directive.py](../../../../tests/unit/python/utils/upstream/test_directive.py), [test_trackers.py](../../../../tests/unit/python/utils/upstream/test_trackers.py), [test_upstream_references.py](../../../../tests/unit/python/tests/external/repository/test_upstream_references.py) | unit | Cover the grammar, the URL shapes, every adapter's state mapping and the rate-limit skip, with HTTP mocked.                                                    |

The external check collects every directive in the files `git ls-files` lists, tracked and untracked-not-ignored, without the generated catalogs under `locale/`. It asks each item's tracker once and:

- fails when an item is closed in any way: a pull or merge request merged or closed unmerged, an issue closed as completed, as not planned or as a duplicate. The message names the directive's `file:line`, the URL, the state and the merge or close date. Check that the pinned version contains the fix, then remove the patch together with its directive. When the item closed while the workaround is still needed, reference the open item that tracks the defect now.
- fails when the tracker answers 404 or 410, because the URL names no item.
- fails when an item could not be asked: a timeout, a connection error or a 5xx answer after three attempts with a doubling pause, an auth wall, or an answer that is not a JSON object. A run that verified nothing does not pass.
- skips an item behind an exhausted rate limit: HTTP 429 after the retries, or HTTP 403 with `X-RateLimit-Remaining: 0` or `Retry-After`. The skip reason names the URL, the directive's `file:line` and when the limit resets. `GITHUB_TOKEN` or `GH_TOKEN` avoids it. A run with a failing item still fails and lists the skipped ones.
- passes when every item answered open, and skips when no directive exists.

| Forge          | Request                                                                      | Token                                                                                                       |
| -------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| GitHub         | `GET /repos/<owner>/<repo>/issues/<n>` on `api.github.com`, pulls included   | `GITHUB_TOKEN`, else `GH_TOKEN`, when set. Without one, GitHub answers 60 requests per hour and address.   |
| GitLab         | `GET /api/v4/projects/<path>/issues/<n>` or `.../merge_requests/<n>`         | `GITLAB_TOKEN` when set, sent to `gitlab.com` only.                                                         |
| Forgejo, Gitea | `GET /api/v1/repos/<owner>/<repo>/issues/<n>` or `.../pulls/<n>`             | None.                                                                                                       |

Implementation: [directive.py](../../../../utils/upstream/directive.py) holds the grammar and the URL shapes, [trackers.py](../../../../utils/upstream/trackers.py) the adapters.
