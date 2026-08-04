# Install Scripts

This directory contains scripts that install and bootstrap host-side tooling used by the project.

- 📦 Install Python, Ansible, and lint dependencies for supported environments
- 🐧 Install ad-hoc APT packages for CI and workflow jobs via `apt.sh`
- 📦 Build and install distro package metadata via `package.sh` (Arch/Debian/Ubuntu/Fedora)
- 🏖️ Install OS-level Claude Code sandbox dependencies (`bubblewrap`, `socat`) via `sandbox.sh`, covering Debian, Ubuntu, Fedora, CentOS/RHEL/Rocky/Alma, and Arch; also exposed as `make install-agent`
- 🧊 Install the ext4, btrfs and zfs userlands via `filesystem.sh` (distro packages, EPEL for btrfs on CentOS, the AUR PKGBUILD for zfs on Arch, the zfsonlinux repository on Fedora/CentOS); the kernel side comes from the host
- 🐍 Bootstrap virtual environments and editable project dependencies
- 🛠️ Keep host preparation separate from lint, build, and test execution

The scope of this folder is installation and bootstrap.
Lint execution, build workflows, and test orchestration should stay in their dedicated script directories.
