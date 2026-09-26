# EspoCRM

## Description

Enhance your sales and service processes with EspoCRM, an open-source CRM featuring workflow automation, LDAP/OIDC single sign-on, and a sleek, lightweight UI! 🚀💼

## Overview

This Ansible role deploys EspoCRM using Docker. It handles:

- MariaDB database provisioning via the `sys-svc-rdbms` role  
- NGINX domain setup with WebSocket and reverse-proxy configuration  
- Environment variable management through Jinja2 templates  
- Docker Compose orchestration for **web**, **daemon**, and **websocket** services  
- Automatic OIDC scope configuration within the EspoCRM container  

With this role, you'll have a production-ready CRM environment that's secure, scalable, and real-time.

## Features

- **Workflow Automation:** Create and manage automated CRM processes with ease 🛠️  
- **LDAP/OIDC SSO:** Integrate with corporate identity providers for seamless login 🔐  
- **WebSocket Notifications:** Real-time updates via ZeroMQ and WebSockets 🌐  
- **Config via Templates:** Fully customizable `.env` and `compose.yml` with Jinja2 ⚙️  
- **Health Checks & Logging:** Monitor service health and logs with built-in checks and journald 📈  
- **Modular Role Composition:** Leverages central roles for database and NGINX, ensuring consistency across deployments 🔄  

## AI Assistance

This role deploys no AI surface and declares no `litellm` service, because EspoCRM's open-source distribution does not ship one. At the pinned version `10.0.4`, `application/Espo/Modules` contains only `Crm`, `application/Espo/Resources/metadata/app/config.json` declares no AI key, and the release ZIP the image is built from leaves `custom/Espo/Modules` empty. The AI features (Summary, Intelligent Paste, AI Email Composer, AI formula functions) live exclusively in the commercial [Intelligence extension](https://www.espocrm.com/extensions/intelligence/), which is closed source, requires a purchased license, and is published in no `espocrm` GitHub repository. Bumping the version does not change this: the extension is documented as requiring EspoCRM 10.0.3 or greater, so newer cores stay hosts for it rather than absorbing it.

To connect EspoCRM to the platform gateway once a license is available:

1. Obtain the extension ZIP and make it reachable from the stack host at deploy time.
2. Install it inside the container with `bin/command extension --file="path/to/package.zip"`, or through Administration > Extensions, and confirm it with `bin/command extension --list`.
3. Create the AI model entry under Administration > Intelligence panel > Settings, selecting the `Custom OpenAI-compatible` provider, and enter the API credentials under Administration > Integrations.
4. Use `LITELLM_OPENAI_BASE_LOCAL_URL` as the base URL, `LITELLM_CHAT_MODEL` as the model name, and the role's own virtual key from `lookup('config', application_id, 'credentials.litellm_api_key')` as the API key. Re-add that credential to `meta/secrets.yml` and the `litellm` service to `meta/services.yml` in the same change, so the gateway mints the key only once a consumer presents it.

The field names on the provider record are only discoverable by unpacking the purchased artifact, so step 3 has to be measured against the extension actually installed rather than assumed from this note.

## Further Resources

- [EspoCRM Official Website](https://www.espocrm.com/) 🌍  
- [EspoCRM Documentation](https://docs.espocrm.com/) 📖  
- [Infinito.Nexus Project Repository](https://s.infinito.nexus/code) 🔗  

## Persona contract opt-outs

`biber` only ever exists inside EspoCRM through OIDC auto-provisioning (`ESPOCRM_CONFIG_OIDC_CREATE_USER=true`, [`templates/env.j2`](./templates/env.j2)); the role itself seeds only the administrator account. In the `services.sso.enabled: false` matrix variants that provisioning path is gone and no native `biber` user exists, so [`templates/playwright.env.j2`](./templates/playwright.env.j2) renders `PERSONA_BIBER_BLOCKED=true`. The `administrator` and `guest` personas run in every variant.
