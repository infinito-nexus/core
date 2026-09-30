# User

## Description

This role configures a basic user environment (shell dotfiles and SSH authorized_keys)
for a user selected via `user_key`.

## Overview

This role executes common tasks for user environment configuration.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Reserved usernames 🔒

`meta/users.yml` lists the usernames that MUST NOT be registered in the identity
directory. An entry is marked reserved by carrying `accounts: []`; consumers read
the set through the `reserved_usernames` filter.

One further reservation per label of `DOMAIN_PRIMARY` is generated at runtime and
keyed `domain_label_<n>`. A deployment on `label-a.tld.test` therefore reserves
`label-a`, `tld` and `test`, at any domain depth.

## User data resolution

User data is resolved via `lookup('users', user_key)` and referenced via `user_key`.
Callers may pass `user_config` to override the resolved lookup result for one invocation.

Resolution rules:

- `user_username` is resolved from `lookup('users', user_key).username` (fallback: `user_key`)
- Home path and ownership are based on `user_username`
- SSH keys are read from `lookup('users', user_key).authorized_keys`

## Required input

- `user_key`

## Optional user fields

- `lookup('users', user_key).username` (defaults to `user_key`)
- `lookup('users', user_key).authorized_keys` (list; may be empty)
- optional include-role var `user_config` to override the lookup result for the current call
