# Fakeroot

## Description

This Ansible role installs **fakeroot** for the current Linux distribution. Fakeroot enables non-privileged users to simulate root-level file manipulations, making it ideal for building packages or performing file operations that normally require root permissions.

Learn more about fakeroot on the [Debian Wiki](https://wiki.debian.org/FakeRoot) and [fakeroot on Debian](https://packages.debian.org/stable/fakeroot).

## Overview

This role automates the installation of fakeroot via the OS package manager, ensuring that users can simulate superuser operations without requiring elevated privileges.

## Purpose

The purpose of this role is to automate the installation of fakeroot so that users can simulate superuser operations without requiring elevated privileges. This is particularly useful in development environments and during package building processes.

## Features

- **Automated Installation:** Installs fakeroot via the OS package manager.
- **Idempotent Execution:** Ensures that fakeroot is installed and remains up to date.
- **Simplified Setup:** Minimizes manual installation steps for environments where fakeroot is required.
