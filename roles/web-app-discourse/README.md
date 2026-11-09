# Discourse

## Description

Discourse is a popular open-source discussion platform designed to foster community engagement through modern, user-friendly features and robust moderation tools. It creates a dynamic space for discussions, offering seamless notifications and customizable interfaces to keep your community active and engaged.

## Overview

This role deploys Discourse using Docker, automating tasks such as container orchestration, service configuration, and routine administrative operations. It integrates key components like Redis and PostgreSQL, sets up domain routing with NGINX, and ensures streamlined updates for a reliable forum experience.

## Features

- **Modern Forum Experience:** Engage in interactive, real-time discussions with a responsive, mobile-friendly design.
- **Robust Moderation Tools:** Benefit from comprehensive tools for content management and community moderation.
- **Customizable Layouts & Themes:** Tailor your forum’s look and functionality to suit your community’s unique style.
- **Scalable Architecture:** Utilize a Docker-based deployment that adapts easily to increasing traffic and community size.
- **Extensive Plugin Support:** Enhance your forum with a wide range of plugins and integrations for additional functionality.

## Addons

Addons are declared in `meta/addons/` and read at deploy time via `lookup('config', application_id, 'addons')`.

| Addon | Mechanism | Default state | Bridges |
|---|---|---|---|
| `docker_manager` | plugin | enabled | none |
| `discourse-activity-pub` | plugin | enabled | `mastodon` |
| `discourse-akismet` | plugin | enabled | none (API key is operator-supplied) |
| `discourse-ai` | plugin | follows `services.litellm.enabled` | `litellm` |
| `discourse-bbb` | plugin | follows `services.bigbluebutton.enabled` | `bigbluebutton` |
| `discourse-jitsi` | plugin | follows `services.jitsi.enabled` | `jitsi` |
| `discourse-chat-integration` | plugin | follows `services.matrix.enabled` or `services.mattermost.enabled` | `matrix`, `mattermost` |
| `discourse-openid-connect` | plugin | follows `services.sso.enabled` | `sso` |
| `discourse-prometheus` | plugin | follows `services.prometheus.enabled` | `prometheus` |
| `discourse-ldap-auth` | plugin | follows `services.ldap.enabled` (currently off) | `ldap` |

The bridged partners are co-deployed by variant 1 of [`meta/variants.yml`](./meta/variants.yml); variant 0 is the baseline round and keeps them off to stay within its host budget.

`discourse-chat-integration` switches on `chat_integration_enabled` and the provider of each bridged partner the round deploys (`chat_integration_matrix_enabled`, `chat_integration_mattermost_enabled`), then reads the settings back. Channels, rules and the partner credentials (the Matrix access token, the Mattermost webhook URL) stay with the operator in the admin UI.

`discourse-akismet` ships the plugin but configures nothing: the role writes no akismet site setting, and `akismet_api_key` is a SaaS credential an operator enters in the admin UI. Its spec asserts only that the plugin's settings exist.

The `ldap` service block in [`meta/services.yml`](./meta/services.yml) is intentionally pinned to literal `false` (see [TODO.md](./TODO.md)): the `jonmbake/discourse-ldap-auth` plugin breaks Discourse bootstrap on recent versions. `discourse-ldap-auth` therefore resolves to disabled until that block is flipped back to the dynamic group-membership form.

## Web workers

`UNICORN_WORKERS` follows the host the same way in production and CI: two per vCPU as upstream's [setup wizard](https://github.com/discourse/discourse_docker/blob/775903891a8c34e87de66f747bd98ea48fa32eff/image/setup_wizard/lib/discourse_setup/resource_scaler.rb) sizes a dedicated host, but at most one per 4 GiB of host RAM, because the host is shared with the other applications and every web worker holds about 500 MiB. The count stays between 2 and upstream's ceiling of 8: a 4 vCPU runner with 16 GB gets 3, a host with at least 4 vCPU and 32 GiB visible RAM gets 8. Sidekiq keeps upstream's single process (`UNICORN_SIDEKIQS: 1`).

## Further Resources

- [Discourse Official Website](https://www.discourse.org/)
- [Discourse GitHub Repository](https://github.com/discourse/discourse_docker.git)
- [Discourse Meta Forum](https://meta.discourse.org/)
- [Discourse Documentation](https://meta.discourse.org/t/discourse-setup-guide/21966)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/X47CVFA5hqqrm6MbxxL5aN)
