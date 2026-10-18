# web-app-opentalk TODO 📝

- [ ] Browser-walk an end-to-end meeting flow: log in via Keycloak, create a meeting, join from a second browser, and verify media flows over the LiveKit relay.
- [ ] Browser-walk an end-to-end recording flow: start a meeting, kick off a recording, and verify the recorder uploads the resulting MP4 to MinIO.
- [ ] Add MinIO bucket policy hardening and a dedicated service account (the controller currently uses MinIO root credentials).
- [ ] `opentalk-controller` exits five to six times with `Failed to init controller` after every create or recreate before it stays up (measured `RestartCount` 5 and 6 on 2026-10-09); afterwards it is stable. Options: let the compose service wait for its dependencies to be healthy instead of `service_started`, or find which dependency the init reaches too early.
