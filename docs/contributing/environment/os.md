# Supported Operation Systems

This page defines which operating systems deployments, scripts, and programs MUST support.
Following this policy ensures that Infinito Nexus runs reliably across a broad range of server
environments, from community-managed long-term-support servers to enterprise
[Red Hat](https://www.redhat.com) deployments and cutting-edge rolling-release development machines.

## Deployed Systems

All deployment roles, Ansible tasks, and programs that run inside a deployed system MUST be compatible with the following distributions.

Supporting this set gives operators a choice between stable community servers, enterprise-grade
Red Hat-compatible systems, and a rolling-release target for early-integration testing.

| Distribution | Family | Purpose | Advantages | Disadvantages |
|---|---|---|---|---|
| [**Debian**](https://www.debian.org) | Debian | Preferred for stable, long-term community production deployments | Exceptional stability, large community, predictable release cadence, broad package availability | Packages lag behind upstream; slower to adopt new software versions |
| [**Ubuntu**](https://ubuntu.com) | Debian | Primary CI and development target; widely used on cloud infrastructure | Large ecosystem, good tooling support, frequent LTS releases, broad cloud image availability | Canonical-managed; some divergence from pure Debian behaviour |
| [**Fedora**](https://fedoraproject.org) | Red Hat | Required for Red Hat compatibility validation | Close to RHEL/CentOS Stream upstream; early access to new packages; strong SELinux support | Shorter support window; not suitable for production long-term deployments |
| [**CentOS**](https://www.centos.org) | Red Hat | Required for Red Hat enterprise compatibility | RHEL-compatible; used in enterprise environments; long support cycles (Stream variant) | CentOS Stream is rolling; classic CentOS EOL; smaller community than Debian/Ubuntu |
| [**Arch Linux**](https://archlinux.org) | Arch | Required for rolling-release development and early-integration testing | Always up-to-date packages; minimal base; fast feedback on upstream changes | No stable release; higher breakage risk; not suitable for production servers |

**Why this set?**
[Debian](https://www.debian.org) is preferred for stable community-operated servers because it
offers long-term support without commercial backing requirements.
[Fedora](https://fedoraproject.org) and [CentOS](https://www.centos.org) are required to ensure
compatibility with [Red Hat Enterprise Linux (RHEL)](https://www.redhat.com/en/technologies/linux-platforms/enterprise-linux)
environments. Red Hat support MUST be guaranteed because enterprise customers operate under SLA
and security compliance requirements that mandate a RHEL-compatible platform, including certified
package versions, SELinux enforcement, and vendor-backed security advisories.
[Arch Linux](https://archlinux.org) is included to catch integration problems with newer software
versions early in the development cycle before they reach stable distributions.

### Requirements

- Deployment roles and programs MUST work on all five distributions listed above.
- Roles MUST NOT rely on distribution-specific package names without an explicit per-family
  branch or variable.
- [Debian](https://www.debian.org) SHOULD be the primary reference distribution when behaviour
  differs across families.
- [Arch Linux](https://archlinux.org) support MAY use the latest available package versions
  where no stable equivalent exists.

## Local Test and Setup Environment

Scripts used for local testing and setup (under `scripts/tests/` and `scripts/install/`) MUST
support all five deployed distributions above and additionally MUST support:

| Platform | Purpose | Advantages | Disadvantages |
|---|---|---|---|
| [**WSL2**](https://learn.microsoft.com/en-us/windows/wsl/) (Windows Subsystem for Linux) | Required for Windows-based developer machines | Allows contributors on Windows to run the full local stack without a separate VM | Requires systemd configuration; networking differences from native Linux |
| [**Homebrew**](https://brew.sh) (macOS) | Required for macOS-based developer machines | Standard package manager on macOS; widely used in CI runners | Package names and paths differ from Linux distributions; some tools behave differently |

### Requirements

- Local setup and test scripts MUST work on all five deployed distributions.
- Local setup and test scripts MUST additionally support [WSL2](https://learn.microsoft.com/en-us/windows/wsl/) and [Homebrew](https://brew.sh) (macOS).
- Scripts SHOULD use `command -v` or equivalent to detect available tools rather than
  assuming a specific package manager.
- Scripts SHOULD skip steps silently when a tool is not available only if a working alternative
  exists or the step is purely informational. Scripts MUST fail hard when a required tool is
  missing and no alternative is available.
- Scripts MUST NOT hard-code paths that only exist on one distribution family (e.g.
  `/usr/lib/python3` without a fallback).
- [WSL2](https://learn.microsoft.com/en-us/windows/wsl/)-specific steps MUST be guarded by a WSL2 detection check before execution.
- macOS-specific steps MUST be guarded by an `uname` or `command -v brew` check before
  execution.
