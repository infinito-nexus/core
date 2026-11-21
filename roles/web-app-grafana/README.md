# Grafana

## Description

[Grafana](https://grafana.com/oss/grafana/) is the window onto the complete logs of every deployed application, stored in [Loki](../web-svc-loki/README.md), and onto the metrics of [Prometheus](../web-app-prometheus/README.md). Operators and auditors search, graph and alert on any application's logs without a shell on the host.

## Overview

Grafana runs one container per network the role is served on (`network_instances`): `grafana` for the canonical network and `grafana-onion` for the onion sibling. Grafana builds its OAuth callback and its links from the one `root_url` of its process, so each instance gets the root URL, domain, sign-out target and cookie flag of its network as container environment, and `templates/proxy.conf.j2` routes each vhost to the instance of its network. Each instance keeps its SQLite database on its own node-local volume (`grafana_data`, `grafana_data_onion`; `nfs: false`, `placement: manager`); the entity declares `backup.stop_required: true`, so the backup stops them before copying the databases. Both instances evaluate the provisioned alert rule, and the Alertmanager merges the identical alerts.

Everything Grafana shows is provisioned from files and cannot be edited in the UI:

- **Datasources** (`templates/provisioning/datasources.yml.j2`): `Loki` (uid `loki`) through the shared network of the `loki` service bond, sending the tenant header `X-Scope-OrgID`, and `Prometheus` (uid `prometheus`) through the attached Prometheus network.
- **Central dashboard** (`files/dashboards/logs.json`, uid `infinito-logs`): a log volume graph and one log view per application, repeated over the `application` label of Loki, with a free-text line filter.
- **Alerting** (`templates/provisioning/alerting.yml.j2`): the rule `GRAFANA_LOG_ALERT_TITLE` (`Critical line in an application log`) fires on `services.loki.alerting.critical_pattern` of `web-svc-loki` in the `application` log class and notifies the Alertmanager of `web-app-prometheus` through the contact point `GRAFANA_ALERTMANAGER_RECEIVER`; the Alertmanager's receivers (email, Telegram, Mattermost) are the existing alert channels. The Loki ruler raises the same alert independently. The reverse proxy's access log is the `access` log class (see [log collector](../sys-svc-log-collector/README.md)), so an access log line raises neither; a line of the proxy's error log that carries the request path still raises both. `files/playwright/test-alerting.js` uses that error log path to write a line with the word `critical`: it requests a file the CDN location `CDN_RELATIVE_ROOT` does not hold, which the proxy answers with 404 and logs with its path. It then waits until the rule fires for that application, and, with Prometheus deployed, until the contact point delivered the alert to the Alertmanager without error.

## Features

- **Native OIDC:** Grafana signs in through Keycloak with `auth.generic_oauth` and auto-login. The role mapping reads the `RBAC.GROUP.CLAIM` claim: the `administrator` role group maps to the Admin role, the `auditor` role group of `meta/rbac.yml` maps to Viewer, and with `role_attribute_strict` every other account is refused. The RBAC sync grants and revokes both groups like every other role group; Grafana re-evaluates the role at each login.
- **Login methods:** `services.grafana.login.method` declares `sso`, `native` and `registration` (see [Login Methods](../../docs/contributing/design/iam/login.md)). `sso` switches the `auth.generic_oauth` block of `templates/env.j2` with auto-login, `native` drives `GF_AUTH_DISABLE_LOGIN_FORM` (the local form is off while `native` is off) and `registration` drives `GF_USERS_ALLOW_SIGN_UP`. Grafana OSS has no second factor of its own, so the role declares no `2fa`, and it has no `ldap` service.
- **Break-glass access:** the local account `web-app-grafana-breakglass` (`meta/users.yml`) is the only one that signs in without Keycloak. Its password is the `breakglass_password` credential of `meta/secrets.yml`, applied with `grafana cli admin reset-admin-password --password-from-stdin` to every instance on every deploy. With `native` off, `GF_AUTH_DISABLE_LOGIN_FORM=true` removes the form and its server-side handler, so `/login?disableAutoLogin=true` shows the Keycloak entry only; the account then authenticates against the HTTP API with basic auth (`GF_AUTH_BASIC_ENABLED=true`, e.g. `curl -u <account>:<password> <url>/api/user`), which `files/playwright/test-login-methods.js` proves. Overriding `services.grafana.login.method.native.enabled: true` in the inventory brings the form back at `/login?disableAutoLogin=true`.
- **Read-only IdP fields:** every Keycloak login overwrites name, email and username. For an OAuth account Grafana renders the three profile fields disabled and refuses `PUT /api/user` and `PUT /api/users/:id` with HTTP 403 (`Cannot update external User`). The fields are declared as `sso.<claim>` fields in `meta/forms.yml`; the shared lock renderer of `sys-front-inj-javascript` adds the translated warning as their hover title in one of the UI languages listed in `services.sso.profile.languages`, and `files/playwright/test-profile-lock.js` proves both. The selectors match every disabled profile field, and Grafana also disables them for a local account while `native` is off; the break-glass account then has no UI session, because the login form is gone.
- **Network contract:** the role is served on every network the node runs; the application ports carry `ports.onion.grafana: false` and `ports.onion.grafana_onion: false` and reach the onion through the vhost only. It declares its CSP in `meta/csp.yml` and its limits and storage in `meta/services.yml`.

## Persona contract

- `guest` never reaches Grafana: auto-login sends it to Keycloak.
- `biber` joins the `auditor` role group for its persona journey and opens the central dashboard; `files/playwright/test-rbac.js` proves that biber without a role group is refused. With `sso` disabled Grafana knows only the break-glass account, so `PERSONA_BIBER_BLOCKED` is `true` then.
- `administrator` opens the datasource administration. `files/playwright/test-logs.js` writes a line into the reverse proxy's access log and finds it in Explore (the probe value travels in the request path; the proxy logs no query string), and proves that an `auditor` member reads logs while every write to datasources, dashboards and alert rules is refused.

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## Further Resources

- [Grafana generic OAuth](https://grafana.com/docs/grafana/latest/setup-grafana/configure-security/configure-authentication/generic-oauth/)
- [Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Grafana alerting provisioning](https://grafana.com/docs/grafana/latest/alerting/set-up/provision-alerting-resources/file-provisioning/)
