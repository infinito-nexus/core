# Agentbox Workspace

## Description

Installs [agentbox](https://github.com/kevinveenbirkenbach/agentbox), the local agent workspace: a per-project dev-container sandbox that runs the `dsk-gnt-*` coding agents and the editor installed by `dsk-code` inside a box instead of on the host.

## Overview

The role installs the `agentbox` CLI and the host tools it drives. Docker comes from `dsk-docker`, which also puts the workstation user in the `docker` group, and `npm` provides the `npx` the devcontainer CLI runs through. From there a human runs `agentbox up` and `agentbox run <agent>` per project, and an agent runs the same commands autonomously.

Each box reaches only its own project directory and talks to its own Docker daemon, so the agent gets no host home, no sibling repositories, no host Docker socket and no host credentials. Configuration keys that would widen that reach (mounts, run args, init commands) stay behind an approval agentbox records outside the project, under `~/.config/agentbox/`.

Code - OSS ships no matching remote server, so `dsk-code` uses the `vscodium` flavor when this workspace is enabled.

## Features

- **Local sandbox:** installs the agentbox CLI so agents and the editor run in a per-project dev container, not on the host.
- **Shared isolation contract:** a box exposes only the project directory and its own Docker daemon, the same rules as the server workspace.
- **Human and agent:** the same box is usable interactively by a human and autonomously by an agent.
- **Unprivileged nesting:** containers the agent starts run through the box's own daemon; sysbox keeps that nesting unprivileged on the host.
