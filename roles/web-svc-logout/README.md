# Universal Logout

This folder contains an Ansible role to deploy and configure the **Universal Logout Service**.

## Description

This role sets up the universal logout proxy service, a Dockerized Python Flask container that coordinates logout requests across multiple OIDC-integrated applications. It also configures the necessary NGINX proxy snippets and environment variables to enable unified logout flows.

It solves the common challenge of logging a user out from all connected apps with a single action, especially in environments where apps live on multiple subdomains and use OIDC authentication.

## Overview

- Deploys the universal logout service container based on the official [universal-logout GitHub repository](https://github.com/kevinveenbirkenbach/universal-logout).
- Configures the logout domains dynamically based on application inventory and features using custom Ansible filters.
- Provides an NGINX `/logout` proxy configuration snippet that handles CORS and forwards logout requests to the logout service.
- Supplies a user-friendly logout conductor UI that requests logout on all configured domains and shows live status.
- Designed to be used as the Front Channel Logout URL for Keycloak or other OpenID Connect providers, enabling a seamless, service-spanning logout experience.

## Features

- Automatic discovery of logout domains from applications with the `features.logout` flag enabled.
- Centralized logout proxy that clears cookies and sessions across all configured subdomains.
- Status page with live feedback on logout progress for each domain.
- Built-in support for Docker Compose deployment and integration with the Infinito.Nexus ecosystem.
- Includes security-conscious headers (CORS, CSP) for smooth cross-domain logout operations.

## Logout choices

Every logout control lands on the Keycloak logout confirmation page, and the "Account" menu of the dashboard offers the same two choices.
The corporate login theme renders both choices server side, so they also work without JavaScript; with the stock theme the Keycloak logout panel adds "Log out everywhere" next to the stock submit.
The confirmation page offers "Log out everywhere" only while the dashboard with OIDC is part of the deployment.

| Choice | What it does | Sessions it ends |
| --- | --- | --- |
| Log out on this device | Ends this browser's Keycloak session. Keycloak then runs the front-channel conductor sweep of every network for the shared client, sends a back-channel logout token to every application with its own back-channel client, and each oauth2-proxy gate fails its next `cookie_refresh`. | Every session of this browser on the clearnet and the onion network. No session of another device or browser context. |
| Log out everywhere | A link to the dashboard with the `#logout-everywhere` fragment. The dashboard uses only the user's own access token: it lists the user's applications through the Keycloak Account REST API, revokes the offline token of every application with offline access, ends every other session of the user, and then runs "Log out on this device". | Every session of the user on every device, including offline tokens. |

The dashboard signs in through its own public Keycloak client (PKCE S256, no service account, declared under `services.sso.oidc.clients` of `web-app-dashboard`). Only that client's access tokens carry the `allowed-origins` claim, which the Account REST API needs to answer the dashboard's cross-origin calls; the shared client and the realm's `web-origins` scope keep the claim out of every other access token.
When an Account REST call fails, times out or answers with a non-2xx status, the dashboard still runs "Log out on this device" and, after the redirect back, tells the user that other devices may still be signed in.
Neither choice uses a Keycloak service account, a `realm-management` role, the Keycloak admin REST API, stored realm events or a Keycloak extension.

## Back-channel logout per role

Each role with an `sso` service, whether its pinned upstream receives OIDC back-channel logout tokens, and how long its session lives on another network or device when nothing ends it.
An application that receives logout tokens declares its own Keycloak client under `services.sso.oidc.clients`; every other one stays on the shared client.

| Role | Flavor | Back-channel logout | Endpoint | Upstream documentation | Session on another network or device |
| --- | --- | --- | --- | --- | --- |
| `svc-ai-agent-broker` | oidc | to verify | to verify | to verify | to verify |
| `svc-ai-agent-provisioner` | oidc | to verify | to verify | to verify | to verify |
| `web-app-agent-fixture` | - | to verify | to verify | to verify | to verify |
| `web-app-akaunting` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-baserow` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-bigbluebutton` | oidc | to verify | to verify | to verify | to verify |
| `web-app-bluesky` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-bookwyrm` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-bridgy-fed` | - | to verify | to verify | to verify | to verify |
| `web-app-checkmk` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-chess` | - | to verify | to verify | to verify | to verify |
| `web-app-confluence` | - | to verify | to verify | to verify | to verify |
| `web-app-dashboard` | oidc | no | - | [keycloak-js](https://www.keycloak.org/securing-apps/javascript-adapter) | ends with the Keycloak session at the next `check-sso` or token refresh |
| `web-app-decidim` | oidc | to verify | to verify | to verify | to verify |
| `web-app-discourse` | oidc | to verify | to verify | to verify | to verify |
| `web-app-docs` | - | to verify | to verify | to verify | to verify |
| `web-app-erpnext` | oidc | to verify | to verify | to verify | to verify |
| `web-app-espocrm` | oidc | to verify | to verify | to verify | to verify |
| `web-app-fediwall` | - | to verify | to verify | to verify | to verify |
| `web-app-fider` | oidc | to verify | to verify | to verify | to verify |
| `web-app-flowise` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-friendica` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-funkwhale` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-fusiondirectory` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-gitea` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-gitlab` | oidc | to verify | to verify | to verify | to verify |
| `web-app-grafana` | oidc | to verify | to verify | to verify | to verify |
| `web-app-hermes` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-homeassistant` | - | to verify | to verify | to verify | to verify |
| `web-app-hugo` | - | to verify | to verify | to verify | to verify |
| `web-app-jellyfin` | oidc | to verify | to verify | to verify | to verify |
| `web-app-jenkins` | oidc | to verify | to verify | to verify | to verify |
| `web-app-jira` | - | to verify | to verify | to verify | to verify |
| `web-app-jitsi` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-joomla` | oidc | to verify | to verify | to verify | to verify |
| `web-app-kix` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-lam` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-listmonk` | oidc | to verify | to verify | to verify | to verify |
| `web-app-litellm` | oidc | to verify | to verify | to verify | to verify |
| `web-app-littlejs` | - | to verify | to verify | to verify | to verify |
| `web-app-magento` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-mailu` | oidc | to verify | to verify | to verify | to verify |
| `web-app-map-animator` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-mastodon` | oidc | to verify | to verify | to verify | to verify |
| `web-app-matomo` | oidc | to verify | to verify | to verify | to verify |
| `web-app-matrix` | oidc | yes | `/_synapse/client/oidc/backchannel_logout` on the Synapse origin | [Synapse](https://element-hq.github.io/synapse/latest/usage/configuration/config_documentation.html#oidc_providers) | ends with the Keycloak session through its own client |
| `web-app-mattermost` | oidc | to verify | to verify | to verify | to verify |
| `web-app-mediawiki` | oidc | to verify | to verify | to verify | to verify |
| `web-app-meta` | - | to verify | to verify | to verify | to verify |
| `web-app-mini-qr` | - | to verify | to verify | to verify | to verify |
| `web-app-minio` | oidc | to verify | to verify | to verify | to verify |
| `web-app-mobilizon` | oidc | to verify | to verify | to verify | to verify |
| `web-app-moodle` | oidc | to verify | to verify | to verify | to verify |
| `web-app-n8n` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-navigator` | - | to verify | to verify | to verify | to verify |
| `web-app-nextcloud` | oidc | to verify | to verify | to verify | to verify |
| `web-app-odoo` | oidc | to verify | to verify | to verify | to verify |
| `web-app-openbao` | oidc | to verify | to verify | to verify | to verify |
| `web-app-openclaw` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-opencloud` | oidc | to verify | to verify | to verify | to verify |
| `web-app-openproject` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-opentalk` | oidc | to verify | to verify | to verify | to verify |
| `web-app-openwebui` | oidc | to verify | to verify | to verify | to verify |
| `web-app-peertube` | oidc | to verify | to verify | to verify | to verify |
| `web-app-penpot` | oidc | to verify | to verify | to verify | to verify |
| `web-app-pgadmin` | oidc | to verify | to verify | to verify | to verify |
| `web-app-phpldapadmin` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-phpmyadmin` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-pihole` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-pixelfed` | oidc | to verify | to verify | to verify | to verify |
| `web-app-postmarks` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-pretix` | oidc | to verify | to verify | to verify | to verify |
| `web-app-prometheus` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-roulette-wheel` | - | to verify | to verify | to verify | to verify |
| `web-app-seaweedfs` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-semaphore` | oidc | to verify | to verify | to verify | to verify |
| `web-app-shopware` | oidc | to verify | to verify | to verify | to verify |
| `web-app-snipe-it` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-socialhome` | - | to verify | to verify | to verify | to verify |
| `web-app-stalwart` | oidc | to verify | to verify | to verify | to verify |
| `web-app-suitecrm` | saml | to verify | to verify | to verify | to verify |
| `web-app-taiga` | oidc | to verify | to verify | to verify | to verify |
| `web-app-wazuh` | oidc | to verify | to verify | to verify | to verify |
| `web-app-weblate` | oidc | to verify | to verify | to verify | to verify |
| `web-app-wordpress` | oidc | to verify | to verify | to verify | to verify |
| `web-app-workspace` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-xwiki` | oidc | to verify | to verify | to verify | to verify |
| `web-app-yourls` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-app-zammad` | oidc | to verify | to verify | to verify | to verify |
| `web-svc-api` | - | to verify | to verify | to verify | to verify |
| `web-svc-libretranslate` | oauth2 | no, gated by oauth2-proxy | - | [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview) | until the gate's next `cookie_refresh` fails |
| `web-svc-simpleicons` | - | to verify | to verify | to verify | to verify |

When a back-channel endpoint is unreachable or refuses the token, Keycloak still ends the user session and names the client in its log; that application keeps its session until its own expiry as listed above.

## Further Resources

- [Universal Logout GitHub Repository](https://github.com/kevinveenbirkenbach/universal-logout)  
- [Infinito.Nexus Project](https://infinito.nexus)  
- [Author: Kevin Veen-Birkenbach](https://veen.world)  
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/SVvxgvJNBEZosR3BXkYyPm)  

---

*This role is licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).*

## Persona contract opt-outs

[`meta/services.yml`](./meta/services.yml) declares no `sso` service, so this role is never registered as a Keycloak client. Its only HTTP surface is the anonymous logout conductor and the `/logout` endpoints proxied by [`templates/logout-proxy.conf.j2`](./templates/logout-proxy.conf.j2) — there is no login form, no account and no session to end.
[`templates/playwright.env.j2`](./templates/playwright.env.j2) therefore declares `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`. The service's real coverage is per consumer: [`files/playwright/playwright.spec.js`](./files/playwright/playwright.spec.js) parameterises the injected logout JS over `roles_with_service('logout')`.
