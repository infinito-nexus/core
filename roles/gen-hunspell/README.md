# Hunspell

## Description

Installs Hunspell and configured language packs on Pacman-based systems for spell checking in multiple languages.

## Overview

This README accompanies the Hunspell Playbook, located within the `infinito` repository. The playbook is focused on installing Hunspell, a widely-used spell checker, along with various language packages to enhance its functionality.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Playbook Contents

The `main.yml` file in the `hunspell` role includes two primary tasks:

1. **Install Hunspell**: Utilizes the `community.general.pacman` module to ensure that the `hunspell` package is installed on the system.

2. **Install Hunspell Language Packages**: Again using the `community.general.pacman` module, this task installs multiple Hunspell language packages. The specific languages to be installed are determined by the `{{hunspell_languages}}` variable, which should be defined as a list of language codes.

## Purpose and Usage

This playbook is tailored for users who need a powerful and flexible spell-checking tool on their systems. Hunspell is particularly popular among writers, editors, and developers who work with text in various languages. By automating the installation of Hunspell and its language-specific packages, this playbook simplifies the setup process, allowing users to quickly get up and running with an advanced spell-checking tool.

## Prerequisites

- **Ansible**: This playbook requires Ansible to be installed on your system.
- **Arch Linux or Similar**: Given the use of the `pacman` package manager, this playbook is designed for systems based on Arch Linux or similar distributions.

## How to Run the Playbook

To utilize this playbook:

1. Ensure you have cloned the `infinito` repository.
2. Navigate to the `roles/hunspell` directory within the repository.
3. Execute the playbook using Ansible, ensuring you provide a list of language codes to the `{{hunspell_languages}}` variable.

## Customization

Users are encouraged to customize the `{{hunspell_languages}}` variable based on their specific language requirements. This variable accepts a list of language codes (e.g., 'en_US', 'de_DE').

## Support and Contributions

For any support requests, suggestions, or contributions, please open an issue or a pull request in the `infinito` repository. Contributions, especially those that enhance the playbook's functionality or extend its language support, are highly welcomed.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
