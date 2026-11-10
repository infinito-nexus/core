# SSH Service (Client)

## Description

This role installs the SSH client packages required to enable secure remote access and key-based authentication on Linux systems. It ensures that the appropriate SSH client is installed depending on the target distribution and that the installation is executed only once.

The role provides the foundation for SSH-based workflows and is designed to be used as a dependency by other roles that require SSH functionality.

## Overview

Optimized for portability and idempotency, this role performs the following tasks:

- Installs the SSH client using the system package manager
- Automatically selects the correct package name for the target Linux distribution
- Ensures the installation runs only once using a shared run-once mechanism
- Serves as a reusable system-level SSH dependency for other roles

## Purpose

The primary purpose of this role is to guarantee that an SSH client is available on the system before executing any SSH-related operations, such as key generation, remote access, or automated provisioning.

It is intentionally lightweight and does **not** configure the SSH server or modify SSH configuration files.

## Supported Distributions

The role installs the correct SSH client package for the following platforms:

- Debian / Ubuntu → `openssh-client`
- Arch Linux → `openssh`
- Fedora / Red Hat / CentOS → `openssh-clients`
- Alpine Linux → `openssh-client`

## Features

- **Distribution-aware package selection**
- **Idempotent execution** using a run-once flag
- **Minimal scope** (client-only, no server configuration)
- **Reusable dependency role** for higher-level SSH workflows
- **Best practices compliant** with modern SSH usage
