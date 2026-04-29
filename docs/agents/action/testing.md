# Testing

## Filesystem Scans — Use the Shared Cache

- When writing or modifying a test that scans the project tree, you MUST route the walk and file reads through [`utils.cache.files`](../../../utils/cache/files.py) — specifically `iter_project_files(...)`, `iter_project_files_with_content(...)`, or `read_text(...)`. You MUST NOT introduce raw `os.walk(<project-root>)`, `Path(<project-root>).rglob("*")`, or broad un-scoped globs on the repo tree in test code.
- Reason: pytest runs every test in one process. Without a shared cache each test re-walks the same tree and re-reads the same files; the walk cost multiplies by the number of tests that use it. Migrating a single test from a raw walk to `iter_project_files_with_content` dropped it from ~26 s to ~1.3 s because every subsequent test served the walk and the file contents from the process-level cache.
- When to skip the rule: narrow globs that hit a fixed small set of paths (e.g. `roles_dir.glob("*/meta/services.yml")`) do not benefit meaningfully; walks inside an isolated `tempfile.TemporaryDirectory()` fixture are out of scope because the cache is read-only by design. Even in those cases, use `utils.cache.files.read_text` for individual file contents so other tests reading the same path get a cache hit.
- API reference: `iter_project_files(extensions=…, exclude_tests=…, exclude_dirs=…)` yields absolute paths, the walk is cached once per process. `iter_project_files_with_content(…)` yields `(path, content)` with both layers cached. `read_text(path)` returns cached UTF-8 content. The walker automatically prunes `.git`, `.cache`, `.pytest_cache`, `.ruff_cache`, `.venv`, `venv`, `__pycache__`, and `node_modules`.

## Test Changes

- After every change to a test file, you MUST run the corresponding validation command before continuing with any further action. Use the suite-selection rules in [Testing and Validation](../../contributing/actions/testing.md).
- You MUST NOT run more than one unit test command at the same time. Unit tests MUST be executed serially, never in parallel.
- If a new test is created or an existing test has been changed since the last test run, you MUST rerun it after every subsequent action until it passes.
- If the last test run for a test failed, you MUST rerun it after every change until it succeeds.

## Commits

- `make test` is enforced automatically by the pre-commit hook before every commit for changes that include at least one file that is not `.md`, `.rst`, or `.txt`. You do NOT need to run it manually.
- For markdown/reStructuredText/text-only changes, the hook skips `make test` automatically.
- If the pre-commit hook warns about a staged file or its role, you MUST ask whether to fix that warning before you continue.
- Keep the follow-up limited to the roles touched by staged files so the change stays focused.

## On Failure
- If that validation fails, you MUST run `make clean` and rerun it.
- If the failure says `service "infinito" is not running`, restart the stack with [Development Environment Setup](../../contributing/environment/setup.md) and retry the validation.
