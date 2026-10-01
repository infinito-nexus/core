# XWiki

## Description

Empower your organization with **XWiki**, an open-source enterprise wiki and knowledge management platform. XWiki provides powerful collaboration features, structured content management, and extensibility through applications and plugins, all under your control.

## Overview

This role deploys XWiki using Docker, automating the installation, configuration, and management of your XWiki server. It integrates with an relational database and a reverse proxy. The role supports advanced features such as global CSS injection, Matomo analytics, OIDC authentication, and centralized logout, making it a powerful and customizable solution within the Infinito.Nexus ecosystem.

## Features

- **Enterprise Wiki Platform:** Create, edit, and organize pages with a powerful WYSIWYG editor and structured content support.  
- **Advanced Rights Management:** Fine-grained permissions for users, groups, and spaces.  
- **Extensions & Applications:** Extend functionality with hundreds of available XWiki extensions and macros.  
- **Powerful Search:** Full-text and structured search to quickly find knowledge across spaces.  
- **Office Integration:** Import, export, and collaborate on Office documents (Word, Excel, PDF).  
- **Customization & Theming:** Adapt the look and feel of your wiki with skins, CSS, and scripting.  
- **Integration Ready:** Connect with external systems such as Keycloak (OIDC), LDAP, or analytics tools like Matomo.  

## Addons

Extensions are declared in `meta/addons/` under the unified addon contract.
Each one is installed through the XWiki Extension Manager and pins its upstream version; the Maven coordinate is carried under the addon's `config.id`:

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `oidc-authenticator` | `extension` | enabled whenever the `sso` service is present (`web-app-keycloak` co-deployed) | `sso` → `web-app-keycloak` |
| `ldap-authenticator` | `extension` | enabled whenever the `ldap` service is present (`svc-db-openldap` co-deployed) | `ldap` → `svc-db-openldap` |
| `matomo` | `extension` | enabled whenever the `matomo` service is present (`web-app-matomo` co-deployed) | `matomo` → `web-app-matomo` |

`oidc-authenticator` and `ldap-authenticator` are mutually exclusive auth backends (only one may be enabled; see [`tasks/01_validation.yml`](./tasks/01_validation.yml)), each deriving its enablement from its bridged service flag.
The OIDC/LDAP runtime configuration (provider URLs, bind DN, secrets) lives in the XWiki property templates and is read via `lookup('config', application_id, 'secrets.credentials.<name>')`; the addon `config:` carries only the installer coordinate.

## Further Resources

- [XWiki Official Website](https://www.xwiki.org/)  
- [XWiki Documentation](https://www.xwiki.org/xwiki/bin/view/Documentation/)  
- [XWiki GitHub Repository](https://github.com/xwiki/xwiki-platform)  

## Persona contract opt-outs

The administrator is provisioned as an `XWiki.XWikiUsers` object without a `password` property (see [`templates/xml/user/xwikiusers_object.xml.j2`](./templates/xml/user/xwikiusers_object.xml.j2)), and every privileged operation of the role authenticates as the built-in `superadmin` with `credentials.superadminpassword`. Neither credential is the Keycloak secret the shared persona helpers submit, and `biber` has no XWiki user page at all — only the administrator page is created ([`tasks/03_administrator.yml`](./tasks/03_administrator.yml)) — while the OIDC group mapping stays commented out in [`templates/xwiki.properties.j2`](./templates/xwiki.properties.j2).
[`templates/playwright.env.j2`](./templates/playwright.env.j2) therefore declares `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`. The Keycloak coupling is instead proven through XWiki's own login action by the addon spec [`files/playwright/addons/oidc-authenticator.spec.js`](./files/playwright/addons/oidc-authenticator.spec.js).
