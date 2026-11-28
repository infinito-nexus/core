# Loki

## Description

[Grafana Loki](https://grafana.com/oss/loki/) is the full-log store of the platform. It keeps every log line of every deployed application for search, graphs and alerts in [Grafana](../web-app-grafana/README.md); security alerting stays with [Wazuh](../web-app-wazuh/README.md).

## Overview

The stack runs two containers:

- `loki`: the single-binary log store with `auth_enabled: true`, so every request names its tenant in `X-Scope-OrgID`.
- `gateway`: a [Grafana Alloy](https://grafana.com/docs/alloy/latest/) instance that receives pushes, applies the shared `LOG_REDACTION_RULES` of [22_logging.yml](../../group_vars/all/22_logging.yml) as the central redaction stage and writes the lines to `loki` for the configured tenant.

Every server host runs the [log collector](../sys-svc-log-collector/README.md), which pushes its journal to `https://loki.<DOMAIN_PRIMARY>/loki/api/v1/push`. The vhost serves only that path, only for `POST`, and only with the bearer token `push_token` from `meta/secrets.yml`; it keeps the token's SHA-256, answers `401` without a matching token and `403` for any tenant but `services.loki.tenant`. Every other path answers `404`. `meta/networks.yml` restricts the role to clearnet and the role declares no `tor` service, so the ingest endpoint never answers on an onion address.

Grafana reads Loki over the shared network of the `loki` service bond (`http://loki:3100`), and so does the role test, from a throwaway container on that network, so it reaches Loki in compose and swarm alike. The gateway binds to the local port `services.gateway.ports.local.push` for the front proxy; in compose the Loki API also binds to `services.loki.ports.local.loki`.

## Features

- **Storage follows the object store:** with `web-svc-seaweedfs` in `group_names`, Loki stores chunks and index in the bucket the `objstore` lookup provisions; otherwise on the node-local volume `loki_data` (`nfs: false`) of the manager. Chunks declare `backup: false`.
- **Retention per log class:** `services.loki.retention` maps each log class the collector assigns (`access`, `application`, `system`, `security`) to a duration (`<n>h`, `<n>d` or `<n>w`, at least `24h`), 7 days by default. The `loki_retention` filter turns the map into one `retention_stream` per class; the compactor deletes older lines.
- **Ruler:** `templates/rules.yaml.j2` raises the alert named by `LOKI_ALERTING_RULE_NAME` (`CriticalApplicationLogLine`) when a line of the `application` log class, which leaves out the reverse proxy's access log, matches `services.loki.alerting.critical_pattern` within `services.loki.alerting.window`. It raises the alert named by `LOKI_DRIFT_RULE_NAME` (`ManagedFieldOverwritten`) for every journal event with the identifier `FORMS_DRIFT_IDENTIFIER` of [22_logging.yml](../../group_vars/all/22_logging.yml), which [tasks/utils/forms/drift_report.yml](../../tasks/utils/forms/drift_report.yml) raises before a deploy overwrites a managed field of a role's `meta/forms.yml` that differs from its source, or a part of the WordPress corporate design that differs from what the last deploy wrote. Both alerts go to the Alertmanager of [web-app-prometheus](../web-app-prometheus/README.md) when that role is deployed.
- **Canary test:** `files/test/test.sh` proves that an unauthenticated push and a foreign tenant are refused, and that synthetic passwords and tokens pushed through the gateway and written by a container through the collector are stored redacted; `files/test/loki_probe.py` reads the Loki and Alertmanager answers. It also proves:
  - **Burst:** one container writes 20000 lines, and Loki stores every one of them.
  - **Self-exclusion:** a line labelled with this role's application id never reaches Loki, while a control line written after it does.
  - **Ruler:** a container's synthetic critical line fires the ruler alert for its own application label.
  - **Notification:** with the Alertmanager deployed, that alert is active there.

## Configuration

| Key | Meaning |
|---|---|
| `services.loki.tenant` | Tenant id every push and query names. |
| `services.loki.retention.<class>` | Retention of one log class. |
| `services.loki.ingestion.rate_mb`, `burst_mb` | Ingestion limits per tenant and per stream. |
| `services.loki.wal.disk_full_threshold` | Fraction of the data filesystem above which Loki refuses every push: `0.90` in production, `0.99` in the `meta/variants.yml` rounds of development and CI. |
| `services.loki.alerting.critical_pattern`, `window` | Log content the ruler and the Grafana alert fire on. |

## Further Resources

- [Loki documentation](https://grafana.com/docs/loki/latest/)
- [Loki retention](https://grafana.com/docs/loki/latest/operations/storage/retention/)
- [Alloy `loki.source.api`](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.api/)
