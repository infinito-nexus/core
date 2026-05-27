# TLS Administration Scripts 🔒

This directory contains scripts for managing TLS/PKI concerns in the Infinito Nexus development environment.
For the canonical Make target index that invokes these helpers, see [make.md](../../../docs/contributing/tools/make.md).

---

## Subdirectories 📁

### [`trust/`](trust/) 🔐

Scripts for installing the Infinito self-signed Root CA into the trust stores of the developer's machine.

- **`linux.sh`**. installs the CA into the Linux system trust store
- **`wsl2.sh`**. installs the CA into the Windows trust store and updates the Windows hosts file (WSL2 only)

---

## Related 🔗

- `roles/sys-ca-selfsigned/`. role that generates the self-signed Root CA inside the container
