# sys-svc-container – Files Overview

This directory contains helper scripts and binaries that are installed on the host
to provide **container-related runtime functionality** for Infinito.Nexus.

The files here are **not application-specific**. They are **infrastructure helpers**
used by other roles, health checks, CI jobs, and runtime scripts that interact with
Docker containers in a controlled and reproducible way.

---

## container.py

**Purpose**

`container.py` is a **general-purpose Docker wrapper CLI** installed as:

```

/usr/local/bin/container

```

It provides a **stable, opinionated entry point** for container execution within
Infinito.Nexus.

**Why it exists**

- Centralizes container execution logic
- Injects **CA trust** only where it makes sense (`container run`)
- Avoids duplicating fragile `container run` logic across roles and scripts
- Provides predictable behavior in CI and production

**Key responsibilities**

- Implements `container run` with:
  - CA trust injection (`with-ca-trust.sh`)
  - ENTRYPOINT detection and recovery
  - `--pull` policy handling
- Passes through commands where wrapping does **not** make sense:
  - `container exec`
  - `container logs`
  - `container ps`
  - `container inspect`
  - `container pull`
- Provides a raw escape hatch:

  ```bash
  container docker <any docker args>

```

**Who uses it**

* Health-check scripts (e.g. CSP, DNS, HTTP checks)
* CI jobs running Docker-in-Docker
* Infrastructure roles that need reliable container execution
* Any script that would otherwise call `container run` directly

---

## test-dns.sh

**Purpose**

`test-dns.sh` is a **Docker-in-Docker DNS health check script**.

It validates that DNS resolution works correctly *inside containers*, which is
critical for:

* Node.js (`dns.lookup`, `getaddrinfo`)
* CSP checker containers
* Any service relying on outbound DNS

**What it tests**

1. Docker daemon availability (DinD readiness)
2. DNS resolution via BusyBox:

   * A record resolution
   * No `SERVFAIL` responses
3. DNS resolution via Node.js:

   * `dns.lookup()` behavior
   * Real-world behavior matching CSP checker usage

**Who uses it**

* CI pipelines
* System health checks
* Debugging DNS issues in containerized environments

---

## install-cli.sh

**Purpose**

`install-cli.sh` installs the **Docker CLI (client only)** in a
distribution-aware way.

It is intentionally limited to the CLI and does **not** start or manage the Docker
daemon.

**Supported distributions**

* Arch Linux
* Debian / Ubuntu
* Fedora
* CentOS / RHEL

**Who uses it**

* CI images
* Minimal container images
* Test environments where only `docker` client access is required
* Roles that need to interact with an external Docker daemon or DinD

---

## Design Principles

* **Separation "docker logic" from application logic**
* **One canonical container entry point** (`container`)
* **Minimal magic** – wrapping only where it is technically justified
* **CI-first design** (predictable behavior without a full system)

---

## Summary

| File             | Used by                 | Purpose                            |
| ---------------- | ----------------------- | ---------------------------------- |
| `container.py`   | Scripts, roles, CI      | Safe, CA-aware container execution |
| `test-dns.sh`    | CI, health checks       | Validate container DNS behavior    |
| `install-cli.sh` | CI images, test systems | Install Docker CLI only            |

This directory forms the **container runtime foundation** of Infinito.Nexus.
