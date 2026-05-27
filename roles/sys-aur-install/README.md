# sys-aur-install

## Description

Installs one or more AUR packages using `kewlfft.aur.aur` and the `yay` helper.

## Overview

This role wrapper role to install AUR packages via kewlfft.aur.aur using yay.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Variables

- `yay_install_packages` (required for direct role usage): list of AUR package names
- `yay_install_upgrade` (optional): set `true` to upgrade all packages (mutually exclusive with `yay_install_packages`)
- `yay_install_use` (optional): helper binary, default `yay`
- `yay_install_become_user` (optional): user to execute AUR install, default `aur_builder`
- `SYS_AUR_PACKAGES` (inventory default): list used by constructor auto-install flow

## Example

```yaml
- name: Install MSI packages
  include_role:
    name: sys-aur-install
  vars:
    yay_install_packages:
      - msi-perkeyrgb
```

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
