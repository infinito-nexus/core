# QBittorrent

## Description

Installs the qBittorrent torrent client from the distribution repositories.

## Overview

This README is for the `dsk-qbittorrent` role within the `infinito` repository. This role is specifically crafted for installing qBittorrent, a popular open-source torrent client, on personal computers.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Role Tasks

The `main.yml` file in the `dsk-qbittorrent` role includes the following task:

1. **Install Torrent Software**:
   - This task calls `package_install` with the `qbittorrent` id; the per-distribution names are declared in [`meta/packages.yml`](meta/packages.yml).

## Purpose and Usage

The `dsk-qbittorrent` role is tailored for users who require a reliable and user-friendly torrent client for downloading and sharing files via the BitTorrent protocol. qBittorrent is known for its balance of features, simplicity, and minimal impact on system resources.

## Prerequisites

- **Ansible**: Required for running this role.
- **Supported distribution**: Arch, Debian, Ubuntu, Fedora or CentOS Stream, where CentOS resolves `qbittorrent` through EPEL.

## Running the Role

To utilize this role:

1. Clone the `infinito` repository.
2. Navigate to the `roles/dsk-qbittorrent` directory.
3. Execute the role using Ansible, ensuring you have the required system permissions for package installation.

## Customization

This role is primarily focused on installing qBittorrent, but it can be customized to include additional configurations or related software packages as needed.

## Support and Contributions

For support, feedback, or contributions, such as enhancing the role or adding additional torrent-related functionality, please open an issue or submit a pull request in the `infinito` repository. Contributions that enhance the usability or features of qBittorrent within this role are highly appreciated.
