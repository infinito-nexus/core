# 060 - Grafana with the Complete Logs of Every Application

## User Story

As a platform operator, I want the complete logs of every deployed Infinito.Nexus application collected in one store and searchable, graphable and alertable in Grafana behind Keycloak, so that I can troubleshoot and audit any application on any node without a shell on the host.

## Decisions (operator-confirmed 2026-10-29; do not re-litigate)

1. **Loki is the full-log store, Wazuh stays security alerting.** Loki keeps every log line of every application for search and troubleshooting. The Wazuh agent of requirement 059 keeps forwarding the lines of its opted-in roles for security alerting. Both read the same journald under one logging contract that this requirement defines and 059 adopts.
2. **One logging contract in the base roles.** `sys-svc-container` and `sys-svc-journalctl` own it: journald is the Docker daemon's default log driver, every container carries an application tag and labels unconditionally, the journal is persistent, and the `docker.service` rate limit is raised so a burst does not drop lines. Applications that log only to files are switched to stdout or stderr, and nested Docker daemons (the Matrix ansible flavour, `svc-runner`) follow the same contract.
3. **A collector on every server host.** A host-level `sys-*` collector role runs in the server stage loop (`tasks/stages/02_server.yml`) on every server host, including the NFS and backup hosts, reads journald and pushes to Loki through an authenticated endpoint with a tenant header. The ingest endpoint is never served on an onion address. The containers of the collector, Loki and Grafana are not ingested again.
4. **Storage follows the object store.** Loki stores its chunks in S3 through the shared object-store lookup when the object store is deployed (decided by `group_names`, like every other object-store consumer), and on a node-local volume with `placement: manager` and `nfs: false` otherwise. Log chunks are not backed up; the Grafana database declares `backup.stop_required: true`.
5. **Access through native OIDC.** Grafana signs in through Keycloak with `auth.generic_oauth`. The role group `administrator` maps to the Grafana Admin role and a new role group `auditor` maps to Viewer; every other account is refused. A local admin exists only as break-glass access.
6. **Retention and redaction.** Retention is an inventory parameter per log class with a default of 7 days. Secrets are redacted at the source where an application emits them and again in a central pipeline stage; a canary test proves that a synthetic secret never reaches Loki. The 200-line log excerpt that `sys-ctl-hlth-container` sends with its alerts is redacted by the same rules.
7. **Grafana's scope.** Loki and Prometheus are provisioned datasources. Grafana provisions one central dashboard with a log view per application, and alerting on log content runs through the Loki ruler and Grafana alerting. Per-role dashboards are a follow-up requirement.

## Acceptance Criteria

### Logging contract

- [x] The Docker daemon configuration rendered by `sys-svc-container` sets `journald` as the default log driver, and a lint fails for any compose or swarm template that sets another `logging.driver` without a `# nocheck:` reason.
- [x] Every container log line in journald carries the application id as its tag and as a label, independent of whether Wazuh or Loki is deployed. `roles/sys-svc-container/templates/logging.yml.j2` sets both, `base.yml.j2` renders it outside any condition, and the daemon default tags a labelled container with its label ([test_logging_contract.py](../../tests/unit/python/roles/sys-svc-container/test_logging_contract.py)); the compose structure lint now fails a service body that carries neither, which caught the Nextcloud proxy, cron and task-processing services.
- [ ] `sys-svc-journalctl` makes the journal persistent and raises the `docker.service` rate limit, and a burst test of 20000 lines from one container loses no line.
- [x] Every container service that logged to `json-file` before this change logs to journald, including the oauth2-proxy sidecars, the local postgres sidecar, the dashboard, BigBlueButton, Bluesky, Moodle, Taiga, the Matrix compose flavour, the Discourse launcher, `svc-runner` and the Nextcloud major-upgrade container.
- [ ] Applications that write their logs only to files inside the container write them to stdout or stderr, and the nested Docker daemons of the Matrix ansible flavour and `svc-runner` forward to the host journal.

### Collection and storage

- [ ] A collector role runs on every server host through the server stage loop, in compose and in swarm, including the NFS and backup hosts.
- [ ] The collector pushes to Loki only through an authenticated endpoint with a tenant header, the ingest endpoint is not reachable on any onion address, and an unauthenticated push is refused.
- [x] The collector does not ingest the logs of its own container, of Loki or of Grafana. Two drop rules in `collector.alloy.j2` match the application label and the tag ([test_collector_alloy.py](../../tests/unit/python/roles/sys-svc-log-collector/templates/test_collector_alloy.py)); the Loki deploy test re-checks it live.
- [x] Loki stores its chunks in S3 through the object-store lookup when the object store is deployed and on a node-local manager volume with `nfs: false` otherwise, and its chunks declare no backup ([test_loki_storage.py](../../tests/unit/python/roles/web-svc-loki/test_loki_storage.py)).
- [ ] A log line written by an application on each node type (manager, worker, NFS host, backup host) is found in Loki within one minute.

### Grafana

- [ ] A Grafana role signs in through Keycloak with native OIDC, maps `administrator` to Admin and `auditor` to Viewer, refuses every other account, and keeps a local admin only for break-glass access.
- [ ] `roles/<grafana role>/meta/rbac.yml` declares the `auditor` role group, and the RBAC sync grants and revokes it.
- [x] Loki and Prometheus are provisioned datasources, and the central dashboard shows a log view per deployed application. The logs panel of `files/dashboards/logs.json` repeats over `label_values(application)`, the label the collector writes ([test_logs_provisioning.py](../../tests/unit/python/roles/web-app-grafana/templates/test_logs_provisioning.py)); `test-logs.js` checks the Prometheus datasource's health live.
- [ ] A Loki ruler rule and a Grafana alert on log content fire on a synthetic error line and notify through the existing alert channels.
- [x] The Grafana role follows the multi-network contract of `meta/networks.yml`, declares its CSP, its resource limits and its storage, and the Grafana database declares `backup.stop_required: true`.

### Data protection

- [ ] Retention is an inventory parameter per log class with a default of 7 days, and Loki deletes lines older than the configured retention.
- [ ] A canary test emits synthetic passwords and tokens through an application log and asserts that none of them is stored in Loki.
- [x] The log excerpt in `sys-ctl-hlth-container` alerts passes through the same redaction rules.

### Verification

- [x] A Playwright spec signs in as `administrator`, searches the logs of a deployed application in Grafana and finds a line the test wrote.
- [x] A Playwright spec signs in as a member of `auditor`, can read logs and cannot change datasources, dashboards or alert rules.
- [x] A Playwright spec asserts that `biber` without a Grafana role group is refused.
- [ ] Unit tests cover the logging-contract lint, the redaction rules and the retention parameter, and `make test` passes.
- [ ] The Grafana, Loki and collector roles deploy green in compose and in swarm.
- [x] Each new role carries a `README.md` describing what it does and how it is wired.

## Cross-linking

- Implementing PR: *to be linked*.
- Security alerting on the same journald: 059 (Wazuh agent and container logs, PR #1231).
- Metrics datasource: `roles/web-app-prometheus`.
- Storage rules: [023-docker-swarm-nfs.md](023-docker-swarm-nfs.md).
