# sys-ctl-hlth-msmtp

## Description

This Ansible role sends periodic health check emails using **msmtp** to verify that your mail transport agent is operational. It deploys a simple script and hooks it into a systemd service and timer, with failure notifications sent via Telegram.

## Overview

Optimized for Archlinux, this role creates the required directory structure, installs and configures the sys-ctl-hlth-check script, and integrates with the **sys-ctl-alm-telegram** role. It uses the **sys-timer** role to schedule regular checks based on your customizable `OnCalendar` setting.

## Cosmos

The diagram places sys-ctl-hlth-msmtp in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [sys-ctl-hlth-msmtp 💻]
        svc_msmtp["msmtp"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

The **sys-ctl-hlth-msmtp** role ensures that your mail transport system stays available by sending a test email at defined intervals. If the email fails, a Telegram alert is triggered, allowing you to detect and address issues before they impact users.

## Features

- **Directory & Script Deployment:** Sets up `sys-ctl-hlth-msmtp/` and deploys a templated Bash script to send test emails via msmtp.  
- **Systemd Service & Timer:** Provides `.service` and `.timer` units to run the check and schedule it automatically.  
- **Failure Notifications:** Leverages **sys-ctl-alm-telegram** to push alerts when the script exits with an error.  
- **Configurable Schedule:** Define your desired check frequency using the `on_calendar_health_msmtp` variable.  
- **Email Destination:** Specify the recipient via the `lookup('users', 'administrator').email` variable.

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
