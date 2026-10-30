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
- **Role mapping:** Members of the `administrator` role group join `XWiki.XWikiAdminGroup` at every OIDC login and leave it when the membership is gone (`oidc.groups.mapping`); under LDAP the same group is mapped by its DN `cn=web-app-xwiki-administrator` in the roles OU.
- **Profile sync:** Every OIDC login rewrites first name, last name, email, phone, locale, time zone and website of the XWiki profile from the `profile`, `email` and `phone` claims, and composes the address field from the `street_address`, `postal_code`, `locality` and `country` members of the `address` claim through `oidc.user.mapping` (one line for the street, one for postal code and locality, one for the country; an absent member stays empty); an LDAP login maps names, email, phone, website and organisation.
- **Open editing:** Every account that signs in joins `XWiki.XWikiAllGroup`, which XWiki grants edit by default; the role maps no separate `editor` role.
- **Login methods:** `services.xwiki.login.method` declares `sso`, `ldap`, `native` and `registration`. `sso` renders `security.authentication.authService=oidc` into `xwiki.properties`, so the login action hands every visitor to Keycloak. `ldap` renders `authService=ldap`, which only applies while OIDC is off. `native` sets `xwiki.authentication.ldap.trylocal` in LDAP mode, so with its default `false` only directory accounts and the built-in `superadmin` pass the form; without SSO and LDAP the standard XWiki form serves the local accounts. `registration` keeps or removes a global rights object that denies the `register` right to `XWiki.XWikiGuest` (`tasks/08_registration.yml`), which hides the Register entry and refuses `XWiki.XWikiRegister`. **Break-glass:** with SSO on, `/bin/login/XWiki/XWikiLogin?oidc.skipped=true` opens the local form (the OIDC authenticator honours it while `oidc.tryLocal` keeps its default `true`), and `superadmin` with `credentials.superadminpassword` signs in there or through REST basic auth.

## Addons

Extensions are declared in `meta/addons/` under the unified addon contract.
Each one is installed through the XWiki Extension Manager and pins its upstream version; the Maven coordinate is carried under the addon's `config.id`:

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `oidc-authenticator` | `extension` | enabled whenever the `sso` service is present (`web-app-keycloak` co-deployed) | `sso` → `web-app-keycloak` |
| `ldap-authenticator` | `extension` | enabled whenever the `ldap` service is present (`svc-db-openldap` co-deployed) | `ldap` → `svc-db-openldap` |
| `ai-llm` | `extension` | enabled whenever the `litellm` service is usable (`web-app-litellm` co-deployed) | `litellm` → `web-app-litellm` |

`oidc-authenticator` and `ldap-authenticator` are mutually exclusive auth backends (only one may be enabled; see [`tasks/01_validation.yml`](./tasks/01_validation.yml)), each deriving its enablement from its bridged service flag.
The OIDC/LDAP runtime configuration (provider URLs, bind DN, secrets) lives in the XWiki property templates and is read via `lookup('config', application_id, 'secrets.credentials.<name>')`; the addon `config:` carries only the installer coordinate.

## Further Resources

- [XWiki Official Website](https://www.xwiki.org/)  
- [XWiki Documentation](https://www.xwiki.org/xwiki/bin/view/Documentation/)  
- [XWiki GitHub Repository](https://github.com/xwiki/xwiki-platform)  
- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/F8XKp2u85ENaT8NVoVTmg6)  

## Persona contract opt-outs

The administrator is provisioned as an `XWiki.XWikiUsers` object without a `password` property (see [`templates/xml/user/xwikiusers_object.xml.j2`](./templates/xml/user/xwikiusers_object.xml.j2)), and every privileged operation of the role authenticates as the built-in `superadmin` with `credentials.superadminpassword`. Neither credential is the Keycloak secret the shared persona helpers submit.
[`templates/playwright.env.j2`](./templates/playwright.env.j2) therefore declares `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`. The Keycloak coupling is instead proven through XWiki's own login action by the addon spec [`files/playwright/addons/oidc-authenticator.spec.js`](./files/playwright/addons/oidc-authenticator.spec.js), and biber's OIDC journey, its `XWikiAdminGroup` mapping and its profile sync by [`files/playwright/test-rbac-oidc.js`](./files/playwright/test-rbac-oidc.js).
