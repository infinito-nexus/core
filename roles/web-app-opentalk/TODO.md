# web-app-opentalk TODO 📝

- [ ] Browser-walk an end-to-end meeting flow: log in via Keycloak, create a meeting, join from a second browser, and verify media flows over the LiveKit relay.
- [ ] Browser-walk an end-to-end recording flow: start a meeting, kick off a recording, and verify the recorder uploads the resulting MP4 to MinIO.
- [ ] Add MinIO bucket policy hardening and a dedicated service account (the controller currently uses MinIO root credentials).
- [ ] No admin role mapping: controller v0.34 has no administrator role (migration `V21__remove_administrator_role.sql`) and reads `realm_access.roles` only for service tokens; options: none until upstream reintroduces a role, the `x_grp` claim only syncs OpenTalk groups.
- [ ] Phone number not synced: the web frontend hardcodes `scope: "openid profile email"` (`ci/entrypoint.sh`) and the controller keeps `phone_number` only with a `[call_in]` section, which advertises a SIP dial-in number that this role does not deploy; options: once a SIP gateway is part of the role, add `phone` to the `defaultClientScopes` of the frontend client in `tasks/02_keycloak_client.yml` and render `[call_in]` in `templates/controller.toml.j2`.
- [ ] `opentalk-controller` exits five to six times with `Failed to init controller` after every create or recreate before it stays up (measured `RestartCount` 5 and 6 on 2026-10-09); afterwards it is stable. Options: let the compose service wait for its dependencies to be healthy instead of `service_started`, or find which dependency the init reaches too early.
