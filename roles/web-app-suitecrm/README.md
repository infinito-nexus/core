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
- SSO integration via SAML / OAuth2 configured inside SuiteCRM’s Administration Panel

With this role, you get a production-ready CRM environment that plugs into your existing IAM stack.

## Features

- **Sales & Service CRM:** Accounts, Contacts, Leads, Opportunities, Cases, Campaigns and more 📊  
- **Workflow Engine:** Automate business processes and notifications 🛠️  
- **LDAP Authentication:** Centralize user authentication against OpenLDAP 🔐  
- **SSO-Ready:** Integrates with SAML / OAuth2 providers (e.g. Keycloak as IdP) via SuiteCRM’s admin UI 🌐  
- **Config via Templates:** Fully customizable `.env` and `compose.yml` rendered via Jinja2 ⚙️  
- **Health Checks & Logging:** Integrates with Infinito.Nexus health checking and journald logging 📈  
- **Modular Role Composition:** Uses shared roles for DB, proxy and monitoring to keep your stack consistent 🔄  

## Further Resources

- [SuiteCRM Official Website](https://suitecrm.com/) 🌍  
- [SuiteCRM Documentation](https://docs.suitecrm.com/) 📖  
- [Infinito.Nexus Project Repository](https://s.infinito.nexus/code) 🔗  

## LDAP & SSO Notes

- **LDAP** is configured via environment variables (`AUTH_TYPE=ldap`, `LDAP_*`).  
  The role writes a `config_override.php` so SuiteCRM’s legacy backend
  uses LDAP for authentication against your OpenLDAP service.

- **SSO** in SuiteCRM 8 is handled via **SAML** (e.g. with Keycloak as IdP) and
  **OAuth providers** configured in the Administration panel (for outbound email and API access).
  This role does not implement full OIDC login flows; instead, you configure SAML/OAuth inside SuiteCRM’s admin UI.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
