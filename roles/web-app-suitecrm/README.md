# SuiteCRM

## Description

Manage your customer relationships with SuiteCRM, a powerful open-source CRM platform extending SugarCRM with advanced modules, workflows, and integrations. This role integrates SuiteCRM into the Infinito.Nexus ecosystem with centralized database, mail and LDAP-ready single sign-on integration. 🚀💼

## Overview

This Ansible role deploys SuiteCRM using Docker and the Infinito.Nexus shared stack. It handles:

- MariaDB database provisioning via the `sys-svc-rdbms` role  
- NGINX domain and reverse-proxy configuration  
- Environment variable management through Jinja2 templates  
- Docker Compose orchestration for the **SuiteCRM** application container  
- Native **LDAP** authentication via Symfony’s LDAP configuration  
- Declarative **SAML** SSO against Keycloak (`AUTH_TYPE=saml`, wired entirely from env vars — no admin-panel step)

With this role, you get a production-ready CRM environment that plugs into your existing IAM stack.

## Features

- **Sales & Service CRM:** Accounts, Contacts, Leads, Opportunities, Cases, Campaigns and more 📊  
- **Workflow Engine:** Automate business processes and notifications 🛠️  
- **LDAP Authentication:** Centralize user authentication against OpenLDAP 🔐  
- **SSO-Ready:** SuiteCRM's own SAML login against Keycloak, configured declaratively from the rendered env 🌐  
- **Config via Templates:** Fully customizable `.env` and `compose.yml` rendered via Jinja2 ⚙️  
- **Health Checks & Logging:** Integrates with Infinito.Nexus health checking and journald logging 📈  
- **Modular Role Composition:** Uses shared roles for DB, proxy and monitoring to keep your stack consistent 🔄  

## Further Resources

- [SuiteCRM Official Website](https://suitecrm.com/) 🌍  
- [SuiteCRM Documentation](https://docs.suitecrm.com/) 📖  
- [Infinito.Nexus Project Repository](https://s.infinito.nexus/code) 🔗  

## LDAP & SSO Notes

- **LDAP** is configured via environment variables (`AUTH_TYPE=ldap`, `LDAP_*`) in
  [`templates/env.j2`](./templates/env.j2). The role additionally renders
  [`templates/ldap.yaml.j2`](./templates/ldap.yaml.j2) into the container's
  `extensions/<software>/config/services/ldap/`, which maps the LDAP attributes onto
  SuiteCRM's user fields for auto-created accounts.

- **SSO** is SuiteCRM's own SAML login against Keycloak (`sso.flavor: saml` in
  [`meta/services.yml`](./meta/services.yml)), not a proxy in front of it. Unauthenticated
  requests hit the Symfony firewall's SAML entry point, which redirects to Keycloak;
  the assertion comes back to `/saml/acs` and establishes a real SuiteCRM session, so the
  app renders its own authenticated UI including its logout control. Accounts are created
  on first login from the assertion (`SAML_AUTO_CREATE`), and the IdP signing certificate
  is read from Keycloak's realm descriptor by
  [`files/shell/docker-entrypoint.sh`](./files/shell/docker-entrypoint.sh) at boot, over
  the Tor SOCKS proxy whenever the issuer is an onion, because a `.onion` issuer is
  unresolvable directly. `/auth` stays reachable as the local break-glass login.

## Persona contract opt-outs

[`templates/env.j2`](./templates/env.j2) seeds only the administrator into SuiteCRM (`SUITECRM_ADMIN_USERNAME` / `SUITECRM_ADMIN_PASSWORD`); `biber` reaches the app through SuiteCRM's own SAML login against Keycloak, where `SAML_AUTO_CREATE` mints the account on first assertion. In the `services.sso.enabled: false` matrix variants there is no SAML entry point and `biber` has no native account, so [`templates/playwright.env.j2`](./templates/playwright.env.j2) renders `PERSONA_BIBER_BLOCKED=true` for the generic persona journeys (the LDAP spec still signs `biber` in from the directory). The `administrator` persona keeps its native login via `ADMIN_NATIVE_PASSWORD` and runs in every variant.
