# Log Collector

## Description

Host-level [Grafana Alloy](https://grafana.com/docs/alloy/latest/) collector that reads the journal of a server host and pushes every line to [Loki](../web-svc-loki/README.md).

## Overview

`tasks/stages/02_server.yml` includes the role on every server host, in compose and in swarm, including the NFS and backup hosts; it does nothing while no host of the inventory is in the `web-svc-loki` group. The collector is a node-local compose stack under `/opt/compose/svc-log-collector/`, started with the compose wrapper on each host independently of any swarm stack, so a host outside the swarm ships its journal too.

The journal is the single source because of the logging contract of `sys-svc-container` and `sys-svc-journalctl`: every container logs to journald with its application id as tag and as the `DOCKER_LOG_LABEL` label, and the journal is persistent.

## Features

- **Journal source:** `loki.source.journal` reads `/var/log/journal` (bind-mounted read-only) and keeps its position under `/opt/compose/svc-log-collector/data`, so a restart resumes where it stopped; `services.svc-log-collector.journal_max_age` bounds the first read.
- **Labels:** `application` (the `DOCKER_LOG_LABEL` journal field), `container`, `unit`, `identifier`, `level`, `host` and `log_class`. `log_class` is `application` for container lines, `security` for SSH, sudo, logind and polkit units and the auth syslog facilities, and `system` otherwise; Loki's retention is set per class.
- **Self-exclusion:** lines of the collector itself, of `web-svc-loki` and of `web-app-grafana` are dropped before they are sent.
- **Source redaction:** the shared `LOG_REDACTION_RULES` of [22_logging.yml](../../group_vars/all/22_logging.yml) run as `stage.replace` stages before a line leaves the host; the Loki gateway applies them again.
- **Authenticated push:** `loki.write` sends to `https://loki.<DOMAIN_PRIMARY>/loki/api/v1/push` with the `push_token` of `web-svc-loki` as bearer token, read from the `0600` env file, and with the tenant header `X-Scope-OrgID`. Pushes retry with backoff (`services.svc-log-collector.push`) while Loki is not reachable.

## Further Resources

- [Alloy `loki.source.journal`](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.journal/)
- [Alloy `loki.write`](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.write/)
