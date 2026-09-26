# Laya

## Description

[Laya](https://laya.aay.sh/) is a local-first notification command center that aggregates Slack, mail, issue trackers and calendars into approvable action cards.

## Overview

The role installs the pinned upstream AppImage and puts it on `PATH`. Upstream signs its assets with the Tauri updater key and publishes no digest, so the role pins a sha256 taken from the released build itself and the download is verified against it. A rebuilt or replaced asset fails the deploy instead of being installed.

The pinned build is the amd64 AppImage, and the role refuses a host of another architecture rather than linking a binary that cannot run there.

Laya keeps its own settings in `~/.laya/`, including the model providers it talks to. This role does not render that file: upstream documents the provider types but not the on-disk schema, so the provider is an operator step in the application's own settings. Pointing it at the platform gateway means adding a provider of type `openai_compatible`.

## Features

- **Pinned and verified:** the AppImage version and its sha256 live in the role, and a mismatch aborts the deploy.
- **Architecture-guarded:** a host that is not amd64 aborts before the download.
- **Distribution-independent:** the AppImage runs on every supported family, so no vendor repository is needed.
- **No invented configuration:** the provider setup stays in the application, because its file schema is not documented upstream.
