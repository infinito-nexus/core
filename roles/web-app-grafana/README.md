# Grafana

## Description

[Grafana](https://grafana.com/oss/grafana/) is the window onto the complete logs of every deployed application, stored in [Loki](../web-svc-loki/README.md), and onto the metrics of [Prometheus](../web-app-prometheus/README.md). Operators and auditors search, graph and alert on any application's logs without a shell on the host.

## Overview

Grafana runs as one container with its SQLite database on the node-local volume `grafana_data` (`nfs: false`, `placement: manager`); the entity declares `backup.stop_required: true`, so the backup stops it before copying the database.

Everything Grafana shows is provisioned from files and cannot be edited in the UI:

- **Datasources** (`templates/provisioning/datasources.yml.j2`): `Loki` (uid `loki`) through the shared network of the `loki` service bond, sending the tenant header `X-Scope-OrgID`, and `Prometheus` (uid `prometheus`) through the attached Prometheus network.
- **Central dashboard** (`files/dashboards/logs.json`, uid `infinito-logs`): a log volume graph and one log view per application, repeated over the `application` label of Loki, with a free-text line filter.
- **Alerting** (`templates/provisioning/alerting.yml.j2`): the rule `Critical line in an application log` fires on `services.loki.alerting.critical_pattern` of `web-svc-loki` and notifies the Alertmanager of `web-app-prometheus`, whose receivers (Telegram, Mattermost) are the existing alert channels. The Loki ruler raises the same alert independently.

## Features

- **Native OIDC:** Grafana signs in through Keycloak with `auth.generic_oauth` and auto-login. The role mapping reads the `RBAC.GROUP.CLAIM` claim: the `administrator` role group maps to the Admin role, the `auditor` role group of `meta/rbac.yml` maps to Viewer, and with `role_attribute_strict` every other account is refused. The RBAC sync grants and revokes both groups like every other role group; Grafana re-evaluates the role at each login.
- **Break-glass access:** the local account `web-app-grafana-breakglass` (`meta/users.yml`) is the only one that signs in without Keycloak, through `/login?disableAutoLogin=true`. Its password is the `breakglass_password` credential of `meta/secrets.yml`, applied with `grafana cli admin reset-admin-password --password-from-stdin` on every deploy.
- **Network contract:** the role is served on every network the node runs; the application port carries `ports.onion.grafana: false` and reaches the onion through the vhost only. It declares its CSP in `meta/csp.yml` and its limits and storage in `meta/services.yml`.

## Persona contract

- `guest` never reaches Grafana: auto-login sends it to Keycloak.
- `biber` joins the `auditor` role group for its persona journey and opens the central dashboard; `files/playwright/test-rbac.js` proves that biber without a role group is refused. With `sso` disabled Grafana knows only the break-glass account, so `PERSONA_BIBER_BLOCKED` is `true` then.
- `administrator` opens the datasource administration. `files/playwright/test-logs.js` writes a line into the reverse proxy's access log and finds it in Explore, and proves that an `auditor` member reads logs while every write to datasources, dashboards and alert rules is refused.

## Further Resources

- [Grafana generic OAuth](https://grafana.com/docs/grafana/latest/setup-grafana/configure-security/configure-authentication/generic-oauth/)
- [Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Grafana alerting provisioning](https://grafana.com/docs/grafana/latest/alerting/set-up/provision-alerting-resources/file-provisioning/)
