# Windows (WSL2)

On Windows, use [WSL2](https://learn.microsoft.com/en-us/windows/wsl/about) as the development environment and run the repository commands inside WSL2, not directly in [PowerShell](https://learn.microsoft.com/en-us/powershell/).
Use Ubuntu 24.04 with [Docker Desktop WSL2 integration](https://docs.docker.com/desktop/features/wsl/), enable [`systemd`](https://systemd.io/), and expect a few Windows-specific follow-up steps around [certificate authority (CA)](https://en.wikipedia.org/wiki/Certificate_authority) trust and local name resolution.

Keep these WSL2 specifics in mind:

- Trust the generated [CA](https://en.wikipedia.org/wiki/Certificate_authority) in Windows, not only inside WSL2.
- If `*.infinito.test` does not resolve correctly, check Windows-side [DNS](https://en.wikipedia.org/wiki/Domain_Name_System) or hosts configuration.
- If container or security setup behaves differently than on Linux, the WSL2 guide covers the usual [Docker Buildx](https://docs.docker.com/reference/cli/docker/buildx/), [DNS](https://en.wikipedia.org/wiki/Domain_Name_System), and [AppArmor](https://en.wikipedia.org/wiki/AppArmor)-related workarounds.

More information and detailed instructions [here](https://s.infinito.nexus/wsl2env).
