# NSS

## Description

This Ansible role guarantees that a target resolves the `*.localhost` names it serves, without going through DNS.

## Overview

A deployment that keeps the shipped `DOMAIN_PRIMARY` serves names under `infinito.localhost`. Those exist in no zone, so a task that reaches the deployment's own domain from the host depends on the `myhostname` NSS module, which maps any `*.localhost` name to loopback per RFC 6761.

- Installs the module where it is packaged separately (Debian family) and no-ops where it ships inside systemd (Arch, RedHat)
- Appends `myhostname` to the `hosts:` line of `/etc/nsswitch.conf`, idempotently
- Runs once per play

## Features

- **Distro-agnostic:** the package list is empty on families that ship the module with systemd
- **Idempotent:** both tasks are no-ops once the module is present
- **Narrow:** it configures name resolution and nothing else, so callers that only need resolution do not also change the system hostname
