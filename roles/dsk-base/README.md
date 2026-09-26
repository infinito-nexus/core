# Base

## Description

This Ansible role carries the premise every desktop role shares: the login account whose home the desktop files live in, and whose name they are owned by.

It pulls in `user-workstation` and nothing else. Desktop roles declare it in their `meta/main.yml` dependencies instead of each reaching for the account themselves.

## Overview

This role guarantees the workstation account before any desktop role writes for it.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.
- **One premise, one place:** A second shared desktop prerequisite is added here rather than in every `dsk-*` role.

## Usage

Declare it as a dependency in the desktop role's `meta/main.yml`:

```yaml
dependencies:
  - dsk-base
```

Ansible resolves the dependency before the role's own tasks and runs it once per play, so no guard is needed at the call site.

## Variables

The role takes none of its own. `user-workstation` reads `WORKSTATION_USER` and the `users` entry it names.
