# Workspace

## Description

[openvscode-server](https://github.com/gitpod-io/openvscode-server) is the Code - OSS editor served in the browser. This role deploys it as a per-agent and per-user workspace with the Claude Code extension installed from [Open VSX](https://open-vsx.org/), reachable through single sign-on and sandboxed by the isolating container runtime.

## Overview

The role builds a custom openvscode-server image that adds the Claude Code extension, runs it as a single container pinned to the Kata or gVisor runtime that `svc-virt-kata` selects for the host, keeps its editor state in a persistent volume, and fronts it with an OAuth2 proxy and Keycloak sign-in when Keycloak is part of the deployment. The broker (`svc-ai-agent-broker`) clones this workspace per agent and per user from the same image and isolation contract.

## Features

- **Browser IDE:** The container serves openvscode-server on the LAN interface, with an HTTP health check against the editor root.
- **Claude Code extension:** The image install step pulls the Claude Code extension from Open VSX at build time, so every workspace ships with it.
- **Single sign-on:** When Keycloak is deployed, an OAuth2 proxy sits in front of the editor and admits only members of the administrator and agent-user groups of this application.
- **Isolating runtime:** The compose service is pinned to the sandbox runtime `svc-virt-kata` installs, and the deploy refuses a container that comes up under the shared host kernel.
- **Isolation contract:** `services.workspace.isolation` encodes no host home, no sibling repositories, no host Docker socket, no host credentials, own-stack-only Docker access, unprivileged nested Docker with a refused privileged fallback, an uplink-pinned nested MTU, an approval store kept off the agent's writable paths, and agent-firewall egress.
- **Connection token:** A generated token guards direct editor access behind the proxy.
- **Persistent state:** Editor settings and the opened workspace live in a volume mounted at the editor home and are included in the container volume backup when that service is deployed.
- **Compose and Swarm:** The role deploys in both modes.
