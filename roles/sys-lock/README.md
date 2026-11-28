# System Maintenance Lock

## Description

This role provides a locking mechanism that delays maintenance activities such as updates, backups, or patch applications while conflicting services run. It waits for the specified services to stop, up to a timeout.

## Overview

The role performs the following:

- Waits until the specified services have stopped or the timeout runs out.
- Implements retry logic with a configurable timeout.
- Lets maintenance tasks start once the system is in a safe state; at the timeout it fails them, or lets them proceed when the caller asks for it.

## Purpose

The primary purpose of this role is to keep maintenance operations from overlapping with conflicting services. The wait is bounded per unit by its timeout.

## Features

- **Service Locking:** Delays maintenance tasks while critical services run. A unit counts as running while systemd reports its ActiveState as `activating`, `active`, `reloading` or `deactivating`, except in the sub-states `start-pre`, where it waits in this lock itself, and `exited`, where its process has finished. Two waiters therefore never block each other.
- **Timeout and Retry Logic:** Configurable wait time. When it runs out, the lock fails the unit; with `--proceed-on-timeout` it prints a warning and lets the unit proceed.
- **Conflict Avoidance:** Reduces interference between maintenance operations and running services. Waiters are not ordered: two units released by the same peer, or entering the lock together, can both proceed.
