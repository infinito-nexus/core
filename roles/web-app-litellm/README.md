# LiteLLM Admin UI

## Description

[LiteLLM](https://docs.litellm.ai/) is an LLM gateway that puts a single OpenAI-compatible API in front of many model providers. Its admin UI is the gateway's built-in web interface for virtual API keys, teams, budgets and rate limits, model routing, and request and spend logs.

## Overview

This role deploys the LiteLLM admin UI as the browser-facing entry point of the headless LiteLLM Gateway. It runs in host mode and starts no container of its own: it claims a canonical domain, terminates TLS, applies the platform Content-Security-Policy, and reverse-proxies that domain to the local HTTP port the gateway publishes. Visitors sign in with the gateway's own UI credentials.

## Features

- **Dedicated domain:** The admin UI is reachable on its own canonical hostname under the primary domain.
- **Host-mode front proxy:** The role renders an OpenResty virtual host that terminates TLS and forwards to the gateway's local HTTP port, without deploying a container.
- **Keycloak sign-in:** With Keycloak in the deployment, the role sets `services.sso.flavor: oidc` and the LiteLLM Gateway reads the platform's OIDC endpoints from `GENERIC_CLIENT_ID`, `GENERIC_CLIENT_SECRET`, `GENERIC_AUTHORIZATION_ENDPOINT`, `GENERIC_TOKEN_ENDPOINT` and `GENERIC_USERINFO_ENDPOINT`. Sign in at `/sso/key/generate`; `PROXY_ADMIN_ID` carries the administrator's username. LiteLLM serves SSO for up to five accounts in `litellm_usertable` and refuses beyond that without `LITELLM_LICENSE`.
- **Restricted sign-in:** With SSO, the gateway sets `general_settings.ui_access_mode` to `restricted_sso_group` on the `web-app-litellm` administrator group path in the groups claim, so the SSO login refuses every other Keycloak account with `403` before LiteLLM stores a user row; a refused login takes none of the five free SSO seats.
- **Identity mapping:** `GENERIC_USER_ID_ATTRIBUTE`, `GENERIC_USER_EMAIL_ATTRIBUTE`, `GENERIC_USER_DISPLAY_NAME_ATTRIBUTE`, `GENERIC_USER_FIRST_NAME_ATTRIBUTE` and `GENERIC_USER_LAST_NAME_ATTRIBUTE` name the OIDC username, email, name, given name and family name claims, so the LiteLLM user id is the Keycloak username that `PROXY_ADMIN_ID` matches. LiteLLM reads no role from the claims and keeps the role it stored at the first sign-in, so [files/python/rbac_reconcile.py](./files/python/rbac_reconcile.py) runs as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer: members of the administrator role group become `proxy_admin`, every other `proxy_admin` falls back to `internal_user`, and the platform administrator and `default_user_id` keep their role.
- **Gateway credentials:** Without Keycloak, access is gated by the LiteLLM UI username and password that the LiteLLM Gateway provisions. That pair keeps working alongside SSO as a break-glass login.
- **Login methods:** `services.litellm.login.method` declares `sso` and `native`. `sso` decides in [svc-ai-litellm](../svc-ai-litellm/vars/main.yml) (`LITELLM_UI_SSO`) whether the gateway receives the `GENERIC_*` OIDC settings and the restricted `ui_access_mode`; with them, the UI sends every unauthenticated visitor from `/ui` through `/sso/key/generate` straight to Keycloak and shows no password form. `native` is the `UI_USERNAME` and `UI_PASSWORD` form: LiteLLM has no switch that removes it, it is the sign-in page only while `sso` is off, and LiteLLM has no LDAP, second factor or self-registration of its own.
- **Break-glass path:** `/fallback/login` keeps serving the `UI_USERNAME` and `UI_PASSWORD` form while SSO is on, so the gateway administrator signs in there when Keycloak is unavailable.
- **Scoped Content-Security-Policy:** The UI's inline bootstrap scripts pass through a `script-src-elem` flag, and no external font or connect sources are whitelisted.
- **Dashboard tile:** The application contributes a dashboard card when the platform dashboard is part of the deployment.
- **Guest smoke test:** A Playwright spec asserts that the UI answers behind the proxy and gates unauthenticated visitors: it expects the handover to Keycloak when SSO is on and the UI's own password form when it is off.
- **SSO round-trip test:** `test-oidc-login.js` drives `/sso/key/generate` through the Keycloak login form and asserts the UI no longer falls back to its own password gate.

## Further Resources

- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/PqsSt2x3UCHzRrCXhkgdgw)
