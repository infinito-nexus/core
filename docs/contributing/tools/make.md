# Makefile Commands 🛠️

Use these commands from the repository root.

```bash
make help
```

prints the full list of targets, one row per target with a one-line description. Treat its output as the authoritative target list.

For rules on how to write and structure the `Makefile` itself, see [makefile.md](../artefact/files/makefile.md).

## Focused guides 📋

These pages drill into a single workflow rather than enumerate every target. `make help` is the authoritative list of available targets:

- [Network debugging](../actions/debugging/network.md): `make diagnose-network` (DNS / TCP / TLS / PMTU diagnostics inside the dev container) plus MTU / IPv6 / connectivity troubleshooting.
- For app-level local deploy flows and end-to-end checks, see [Development & Testing](../actions/testing.md).

## Git 🔐

Remote setup and signed pushes are handled by [git-maintainer-tools](https://github.com/kevinveenbirkenbach/git-maintainer-tools), installed through `make install-python-dev` (see [remotes.md](../artefact/git/remotes.md)). The tool's `git-setup-remotes` and `git-sign-push` CLIs MUST be invoked directly; there are no `make` wrappers in this repo. Direct `git push` is denied in [settings.json](../../../.claude/settings.json), and agents MUST instruct the operator to run `git-sign-push` outside the Claude sandbox.
