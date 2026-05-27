# Unified Service Failure Notifier

## Description

This role installs a systemd service that sends notifications via both [sys-ctl-alm-telegram](../sys-ctl-alm-telegram/README.md) and [sys-ctl-alm-email](../sys-ctl-alm-email/README.md) when any service fails.

## Overview

Optimized for prompt and comprehensive failure alerts, this role configures a unified notification service. It leverages the capabilities of both Telegram and Email notifications to ensure that administrators are quickly informed about service issues, enabling rapid troubleshooting.

## Purpose

The primary purpose of this role is to provide a centralized mechanism for service failure notifications. By integrating with both the Telegram and Email notifier roles, it delivers reliable alerts through multiple channels, enhancing overall system observability and responsiveness.

## Features

- **Unified Notification Service:** Installs a systemd service that triggers both Telegram and Email alerts.
- **Dependency Integration:** Works seamlessly with the [sys-ctl-alm-telegram](../sys-ctl-alm-telegram/README.md) and [sys-ctl-alm-email](../sys-ctl-alm-email/README.md) roles.
- **Automated Service Management:** Automatically restarts the notifier service upon configuration changes.
- **Centralized Alerting:** Provides a unified approach to monitor and notify about service failures.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
