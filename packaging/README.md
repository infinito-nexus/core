# Packaging Layout

This directory follows the same high-level structure as `package-manager`:

- `packaging/debian/`
- `packaging/fedora/`
- `packaging/arch/`

The package metadata in these folders is used to keep Infinito.Nexus host
dependencies explicit and distro-specific.

`scripts/install/package.sh` builds and installs the local package for
the current distro (Arch, Debian/Ubuntu, Fedora), so dependency resolution is
performed by the distro package manager from package metadata.

## Local Test Environment 🧪

These package definitions are required to bootstrap and run the local
development/test environment reliably. 🚀

Bootstrap tooling is provided via Kevin's Package Manager:
<https://github.com/kevinveenbirkenbach/package-manager>

Scope of declared dependencies:

- Core developer workflow (`make install`, `make setup`)
- Local/CI deployment helpers (`docker`, `jq`, `ansible`, `ssh` tooling)
- Basic shell/Python helper tooling used by scripts

Optional lint/test extras are declared as `Recommends`/`optdepends` where
supported.
