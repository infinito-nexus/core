# Development Environment Setup 🛠️

Use the repository's real setup flow. The main source of truth is the [Makefile](../../../Makefile).

Important:

- Some local development commands change host settings such as [DNS](https://en.wikipedia.org/wiki/Domain_Name_System), [AppArmor](https://en.wikipedia.org/wiki/AppArmor), and [IPv6](https://en.wikipedia.org/wiki/IPv6).
- Some commands use `sudo`.
- Read the setup guides first if you are new to this environment.
- The local development workflow is mainly tested on Linux.

## Platform-Specific Instructions 🖥️

- [Linux](platform/linux.md)
- [macOS](platform/macos.md)
- [Windows (WSL2)](platform/windows-wsl2.md)

## Shared Repository Workflow 🔄

These steps are the shared repository workflow and apply regardless of whether you work on Linux, macOS, or Windows with WSL2.

### Bootstrap 🚀

Run these commands from the repository root:

```bash
make bootstrap
make environment-bootstrap
make compose-up
make network-trust-ca
```

#### Bootstrap Commands 📋

| Phase | Command | What it does |
|---|---|---|
| Initial setup | `make bootstrap` | Installs project dependencies and runs the first repository setup. |
| Host preparation | `make environment-bootstrap` | Prepares the local development machine for the project workflow. |
| Start stack | `make compose-up` | Starts the local development stack. |
| Browser trust | `make network-trust-ca` | Trusts the generated local [CA](https://en.wikipedia.org/wiki/Certificate_authority) so `*.infinito.example` works correctly in your browser. |

The `pre-commit` hooks are installed automatically by `make environment-bootstrap`.
Per-machine overrides go into the process environment before invoking `make` (e.g. `export INFINITO_FOO=…`); `make dotenv` honors caller-set values via setdefault semantics.

### Teardown 🧹

When you are done, use these commands to stop the stack and clean up the local environment:

```bash
make compose-down
make environment-teardown
```

#### Teardown Commands 📋

| Phase | Command | What it does |
|---|---|---|
| Stop stack | `make compose-down` | Stops the local development stack. |
| Host cleanup | `make environment-teardown` | Reverts local development environment changes where supported. |

### Full Development Flow 🔁

The repository already contains a modular environment test suite at [scripts/tests/environment/](../../../scripts/tests/environment/README.md). The commands from that suite are explained here as the intended end-to-end flow.

#### Flow Summary 📋

| Step | Command | Purpose in this flow |
|---|---|---|
| 1 | `make install` | Installs the dependencies needed before running the local development flow. |
| 2 | `make environment-bootstrap` | Prepares the host machine for local development. |
| 3 | `make compose-up` | Starts the development stack. |
| 4 | `make test` | Runs the main combined validation flow. |
| 5 | `make compose-deploy mode=reinstall apps=web-app-matomo` | Runs the baseline validation path for one concrete app. For the retry-loop policy, see [Role Loop](../../agents/action/iteration/role.md). |
| 6 | `make network-trust-ca` | Makes the generated local certificates trusted by the host browser. |
| 7 | `make compose-down` | Stops the running development stack. |
| 8 | `make environment-teardown` | Cleans up host-side development environment changes. |

Use this as a practical reference when you want to understand how local development is expected to work.

### Minimal Hardware Resources 💾

If you work on a machine with limited CPU, RAM, or disk space, use the guide at [hardware.md](hardware.md).
The public article with the same topic is [here](https://s.infinito.nexus/minpcdev).

For local deploy shortcuts and end-to-end checks, see [testing.md](../actions/testing.md).
