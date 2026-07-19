# sys-svc-mail-smtp

## Description

The `sys-svc-mail-smtp` role configures a **local SMTP relay** using [Postfix](https://www.postfix.org/), listening exclusively on `localhost`.  
It is designed to be used as a fallback when no central Mailu instance is available, enabling applications and system services to send email via `localhost:25` without additional configuration.

For general background on SMTP, see [SMTP on Wikipedia](https://en.wikipedia.org/wiki/Simple_Mail_Transfer_Protocol).  
For details about Postfix itself, see [Postfix on Wikipedia](https://en.wikipedia.org/wiki/Postfix_(software)).

## Overview

This role:

- Installs Postfix via `pacman` on Arch Linux.
- Configures it as a **loopback-only relay**, so it:
  - only listens on `127.0.0.1`,
  - does not perform local mailbox delivery,
  - and is safe to use as a simple outbound relay for the local host.
- Integrates seamlessly with the `sys-svc-mail` and `sys-svc-mail-msmtp` roles in the Infinito.Nexus stack.

Typically, `sys-svc-mail` decides whether to:

- Use Mailu (via `sys-svc-mail-msmtp`), **or**
- Fall back to this role (`sys-svc-mail-smtp`) and send via `localhost`.

## Cosmos

The diagram places sys-svc-mail-smtp in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [sys-svc-mail-smtp 💻]
        svc_svc_mail_smtp["svc-mail-smtp"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

The main goals of this role are:

- Provide a **minimal, secure SMTP relay** for hosts that do not run a full mail stack.
- Enable `msmtp` (and any other sendmail-compatible client) to send mail by talking to `localhost:25`.
- Avoid the complexity of a full MTA configuration while still supporting basic outbound notifications.

This is particularly useful for:

- Monitoring nodes,
- Utility hosts,
- Development or test environments without Mailu.

## Features

- 💾 **Postfix Installation on Arch Linux**  
  - Uses `community.general.pacman` to install the `postfix` package.

- 🔒 **Loopback-Only Configuration**  
  - Configures `inet_interfaces = loopback-only` to restrict the SMTP daemon to `127.0.0.1`.  
  - Defines `mynetworks = 127.0.0.0/8` for safe local relaying.

- 🚫 **No Local Mailbox Delivery**  
  - Sets `local_transport = error: local delivery disabled` to avoid storing mail locally.  
  - Focus is purely on **relaying** from localhost rather than full MTA behavior.

- 🧩 **Integration with Infinito.Nexus**  
  - Meant to be driven by `sys-svc-mail`, which decides when to enable this relay.  
  - Works hand in hand with `sys-svc-mail-msmtp`, which configures msmtp to talk to `localhost:25` when Mailu is not present.

## Further Resources

- SMTP & Mail Transfer:
  - SMTP (Wikipedia): <https://en.wikipedia.org/wiki/Simple_Mail_Transfer_Protocol>
- Postfix:
  - Official site: <https://www.postfix.org/>
  - Postfix on Wikipedia: <https://en.wikipedia.org/wiki/Postfix_(software)>
- Related Infinito.Nexus roles:
  - `sys-svc-mail`: central mail orchestration  
  - `sys-svc-mail-msmtp`: msmtp client and sendmail replacement

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
