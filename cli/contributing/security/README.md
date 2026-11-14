# Security 🛡️

Repository-side vulnerability tooling over the pinned role images, built on the engine pipeline of [sys-ctl-hlth-runtime](../../../roles/sys-ctl-hlth-runtime/README.md).

| Command | What it does |
|---|---|
| `make test-security` | Runs `scan`: Syft builds an SBOM of every pinned image straight from the GHCR mirror, cached by digest under `build/security/sbom`, and Trivy, Grype and OSV scan that SBOM tree with the role's threshold and suppressions. Every finding at the threshold goes to `build/test-reports/security.json`, a suppressed one with its `suppressed_until` day. The scan fails only on an engine or mirror error; the unsuppressed findings reach the vulnerability issues instead. |
| `python -m cli.contributing.security.database --dir <dir> --engines <engine>...` | Downloads the Trivy, Grype and OSV databases a CI deploy reads. |
| `python -m cli.contributing.security.summary --report <file> --counts <file> --summary <file>` | Counts the failing findings of the report per image and per CVE, plus the suppressed total, into a JSON file and appends the tables to a Markdown summary. |
| `python -m cli.contributing.security.issues --report <file> --repo <owner/name>` | Opens one `vulnerability` issue per image of the report that lists its CVEs, suppressed ones with their `suppressed_until` day, updates it while it stays, and closes it once no engine reports a CVE for the image. The head line counts the CVEs per severity. |
| `python -m cli.meta.ci.runtime_vulnerabilities --run-id <id> --repo <owner/name> --ref <ref> --dir <dir>` | Run by the `report-main-failures` job of every `main` run, never for another ref: reads the hlth-runtime lines of the deploys' `rescue-diagnostics-*` journals into the same issue format under its own `vulnerability-runtime` label, one issue per image and one `host <distro>` issue per distro. It closes an issue only when a deploy of the run scanned that target without an engine error and reported nothing, so neither sync ever touches the other's issues. |
