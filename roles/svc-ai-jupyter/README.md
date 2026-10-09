# Jupyter

## Description

[Jupyter](https://jupyter.org/) runs code in a managed kernel and returns its output. This role provides that kernel as a backend for other services rather than as a notebook UI for people.

## Overview

The server starts with a token from the deployment's credential store, binds to the container network and publishes no port. Cross-site request checking is off and any origin is accepted, because the caller is a service on the same network that presents the token rather than a browser carrying a cookie.

The role declares no volume: a kernel that executes code a chat wrote gets a fresh filesystem on every restart. A consumer reaches it as `http://jupyter:8888` once it declares `jupyter` in its own `meta/services.yml` with `enabled` and `shared` set. `web-app-openwebui` ships that flag and sends `CODE_EXECUTION_ENGINE=jupyter` with it.

## Features

- **Token protected:** every request carries a token from the credential store; the token is never handed to a browser user.
- **Ephemeral:** no volume is mounted, so each restart discards whatever the executed code wrote.
- **Internal only:** no published port and no proxy entry, so the kernel is reachable from the container network alone.
