# Zoom

## Description

[Zoom](https://zoom.us/) is a popular video conferencing application for online meetings, webinars, and collaboration.

## Overview

This role installs Zoom through `package_install` with the `zoom` id. [`meta/packages.yml`](meta/packages.yml) declares it as an AUR package on Arch Linux and as a deliberate no-op on the Debian and RedHat families, which do not archive the proprietary client.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Further Resources

- [AUR package page for Zoom](https://aur.archlinux.org/packages/zoom)
- [AUR package page for Teams](https://aur.archlinux.org/packages?K=teams)
