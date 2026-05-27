# Git

## Description

This Ansible role installs Git on the target system using the Pacman package manager. It ensures that Git is installed only once, even when the role is applied to multiple hosts or executed in a multi-task scenario.

## Overview

Designed for Arch Linux systems, this role leverages the `pacman` module to install Git. It uses a fact (`run_once_dev_git`) to control task execution, ensuring that the Git installation is performed only once per run.

## Purpose

The purpose of this role is to automate the installation of Git in a consistent and idempotent manner. It is especially useful in environments where Git is a prerequisite for further automation or development tasks.

## Features

- **Git Installation:** Uses the Pacman package manager to install Git.
- **Idempotent Execution:** Sets a fact to guarantee that the installation tasks are executed only once.
- **Optimized Deployment:** Suitable for use in multi-host environments to avoid redundant installations.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
