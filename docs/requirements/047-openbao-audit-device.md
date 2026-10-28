# 047 - OpenBao Audit Device

## User Story

As an operator of applications that keep customer credentials in [`web-app-openbao`](../../roles/web-app-openbao/), I want every request to OpenBao recorded with the accessing identity and a timestamp, so that each read of a stored secret can be traced to the person or machine that made it.

## Background

OpenBao writes nothing about who read which secret unless an audit device is enabled. OpenBao 2.7 refuses to create audit devices through the API (`cannot enable audit device via API; use declarative, config-based audit device management instead`), so the device is declared in the server configuration. Once any audit device is enabled, OpenBao refuses requests it cannot log. The device therefore writes to the server's stdout, which cannot block. That output reaches the same container log as the rest of the server output. By default OpenBao replaces secret values in audit entries with salted HMACs, so the audit trail does not contain credentials.

## Acceptance Criteria

- [ ] The server configuration declares `audit "file" "stdout"` with `file_path = "stdout"`.
- [ ] The `ansible-admin` policy grants `read` and `sudo` on `sys/audit` to list audit devices, and no other policy of the role gains access to `sys/audit`.
- [ ] Every deploy fails unless `bao audit list` reports `stdout/` of type `file`; the check never reports changed.
- [ ] The deploy reads a probe secret with its AppRole session and fails unless the container log then holds an audit response entry for that read, carrying the request path, the `read` operation, a `display_name` and a `time`.
- [ ] Audit entries carry no plaintext secret value: the probe secret's value does not appear in the container log.
- [ ] The role README documents the audit device, its stdout destination and the deploy probe.
- [ ] `make compose-deploy` of `web-app-openbao` is green on a fresh stack and on a re-run.
