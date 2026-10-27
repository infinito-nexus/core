# 040 - Wazuh Agent and Container Logs

## User Story

As a platform operator, I want every opted-in app's logs, Docker events, host file changes, vulnerability findings and GitHub security events to reach Wazuh with their app identity, without silent loss, so that I can detect and investigate attacks on my Infinito.Nexus hosts.

## Acceptance Criteria

### A. Coverage

- [x] Under normal load, 1,000 of 1,000 numbered events from an opted-in app arrive in the Wazuh archive, none missing and none duplicated.
- [x] Every deploy sends an HTTP canary through each opted-in app's real log path, and the deploy fails if the matching alert does not reach the alert index in time.
- [ ] Each further app is opted in and covered by the canary.

### B. App identity and context

- [x] Every event carries its app tag as a decoded field, and identical message text from two tags stays two separate alerts.
- [x] CI rejects an opted-in role whose tag is empty, used by another role, reserved, or contains `systemd`.
- [x] Docker lifecycle events (start, stop, die, exec) are attributed to their app through the compose project or swarm stack label, and health-check execs raise no alert.
- [ ] A live OOM kill is attributed to its app on a real host (proven by logtest only; the dev stack's nested Docker emits no `oom` event).

### C. Application log sources

- [x] Pixelfed logs through stdout and stderr to journald with a stable tag, and its access log keeps tokens and secrets out of the log.
- [ ] Keycloak auth events and the front proxy's logs reach Wazuh, attributed to the right app.
- [ ] File-only apps log to a host path the agent reads, never through both paths for the same events.

### D. Custom rules

- [x] Each opted-in role ships its own decoders, rules and samples in its reserved rule-ID block, and CI rejects duplicate, out-of-block or unscoped rule IDs.
- [x] The ruleset is tested before the manager restarts and rolled back on failure, and the base ruleset loads before every app's files.
- [x] `wazuh-logtest` matches every sample to its rule ID.

### E. Enrollment and modes

- [x] Agents are pre-registered with vault-generated keys, port 1515 is not published, and a second deploy with unchanged keys registers nothing.
- [x] The installed agent version equals the manager version, and a newer agent fails the deploy before any change.
- [x] On a host that runs the manager, the agent is installed after the manager and its pre-registration.
- [x] The agent role deploys and passes on Debian, Arch Linux (source build with per-library dependency pins) and CentOS Stream 10.
- [ ] The agent works on multi-node swarm hosts.

### F. Host file integrity

- [x] A manual change to a monitored host path raises an FIM alert, with deploy start and end markers logged as context.
- [ ] User and process are reported through who-data where the kernel supports it reliably.

### G. Source integrity (GitHub)

- [x] Signed GitHub webhook deliveries for force pushes, branch deletions, workflow changes, branch protection and ruleset changes, new collaborators, org members and deploy keys, secret-scanning and Dependabot alerts each raise their alert; unsigned, replayed, oversized and malformed deliveries are rejected and alerted.
- [x] A push to a default branch without a merged pull request raises an alert.
- [x] An hourly check reports drift of the GitHub settings against a reviewed expected state, and a failed check is its own alert, never "no drift".
- [x] On hosts with a git checkout, a local change, a commit not on main or a commit GitHub does not verify raises an alert.
- [ ] Production hosts without a checkout record the deployed commit and are checked the same way.
- [ ] The org webhook and both read-only bot tokens are set up on GitHub, and the expected state is generated with `--print-current` and reviewed.

### H. OWASP coverage

- [ ] Each OWASP Top 10:2025 category with a detectable signal maps to a rule or module, with a logtest sample and an owasp group tag.

### I. Secrets

- [x] Synthetic passwords, bearer tokens, API keys and reset tokens sent through Pixelfed never appear in alerts, archives or indexed documents.

### J. Per-app switch

- [x] Only opted-in tags are forwarded, also after container recreation, and Wazuh's own containers are not re-ingested.

### K. Reliability

- [x] Bursts of 20,000 and 80,000 events arrive complete with the agent buffer at Wazuh's maximum (queue 100,000, 1,000 events per second).
- [x] Manager outages of 5 and 15 minutes lose no events, because the log collector is frozen while the agent is offline and resumes from its journal position.
- [x] An agent restart, also while frozen, loses no events.
- [x] An agent outage raises an alert from a health check outside Wazuh, and app errors in journald do not fail the host journal check.

### L. Disaster recovery

- [x] After backup, teardown of all Wazuh volumes and restore, the same set of vulnerability findings comes back and the agent reconnects with its old key; the procedure and its recovery time are documented.
- [ ] The dashboard never shows a clean host while recovery is still running.
