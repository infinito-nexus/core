# Neovim

## Description

Installs neovim CLI text editor on Pacman‑based systems.

## Overview

This role automates the installation of neovim, a CLI text editor, on Pacman‑based systems. It uses the `community.general.pacman` module to ensure the editor is installed and up to date.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Requirements

- Ansible 2.9 or higher  
- Access to the Pacman package manager (e.g., Arch Linux and derivatives)

## Role Variables

No additional role variables are required; this role solely manages the installation of the editor.

## Dependencies

None.

## Example Playbook

```yaml
- hosts: all
  roles:
    - desk-neovim
```

## Further Resources

- Official neovim documentation:
  <https://neovim.io/>

## Contributing

Contributions are welcome! Please follow standard Ansible role conventions and best practices.

## Other Resources

For more context on this role and its development, see the related ChatGPT conversation.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
