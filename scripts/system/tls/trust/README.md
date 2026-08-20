# CA Trust Scripts 🔐

This directory contains platform-specific scripts for trusting the Infinito Root CA certificate on the developer's machine.
For the canonical Make target index that invokes these helpers, see [make.md](../../../../docs/contributing/tools/make.md).

All scripts extract the Root CA from a running Infinito container and install it into the appropriate system trust store, so that browsers and tools accept `*.infinito.test` TLS certificates without warnings.

---

## Scripts 📄

### `linux.sh` 🐧

Trusts the Infinito Root CA on the **Linux host system**.

1. Extracts `root-ca.crt` from the running Infinito container via `docker cp`
2. Places it under `/etc/infinito.nexus/ca/root-ca.crt`
3. Installs it into the system trust store via `roles/sys-ca-selfsigned/files/with-ca-trust.sh`

Requires `INFINITO_CONTAINER` to be set to the name of the running container.

### `wsl2.sh` 🪟

Trusts the Infinito Root CA on **Windows** from inside a WSL2 environment. Only executes when running on WSL2 (detected via `/proc/version`).

1. Extracts `root-ca.crt` from the running container and copies it to the Windows `Downloads` folder
2. Imports the certificate into the Windows **CurrentUser Root** trust store via PowerShell (no admin required)
3. Discovers all configured domains from the nginx config inside the container
4. Updates the **Windows hosts file** (`C:\Windows\System32\drivers\etc\hosts`) with `127.0.0.1` entries for all discovered domains (requires one UAC confirmation)

---

## Related 🔗

- [`../`](../). TLS administration scripts
- `roles/sys-ca-selfsigned/`. generates the self-signed Root CA inside the container
