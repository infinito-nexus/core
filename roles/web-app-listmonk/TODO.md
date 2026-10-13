# To-dos

- Three settings keys in `vars/main.yml` are silent no-ops on v6.2.0:
  `security.enable_captcha`, `security.captcha_key` and `security.captcha_secret`.
  The live `settings` table carries a single `security.captcha` object
  (`{"altcha": {…}, "hcaptcha": {"key", "secret", "enabled"}}`), so all three
  `UPDATE`s match zero rows and neither `ON_ERROR_STOP` nor the reaper notices.
  hCaptcha has therefore never been active, which also makes the
  `HCAPTCHA_SERVICE_ENABLED` rationale in `templates/playwright.env.j2` describe
  protection that is not there. Rewrite the three keys as one object, then
  decide whether a captcha on the public subscription form is wanted at all.
- Unblock the `biber` persona. Listmonk matches OIDC users by e-mail and the
  role provisions no biber account; `cmd/auth.go` `OIDCFinish` 404s unless
  `security.oidc.auto_create_users` is true, and `createOIDCUser` passes
  `UserRoleID` as a plain int, so `default_user_role_id` must name a real role.
  The seeded database holds exactly one (`id=1 Super Admin`), so unblocking
  biber means first creating a limited Listmonk user role. It buys no coverage
  the administrator persona does not already buy.
- Add `files/playwright/test-seaweedfs.js` now that the administrator persona
  runs. The only bucket-write surface is the admin Media view; the model is
  `roles/web-app-pixelfed/files/playwright/test-seaweedfs.js`. The
  `# nocheck: seaweedfs-playwright` marker in `meta/services.yml` comes off with
  it.
- The task "Apply all Listmonk settings" in `tasks/02_manager_ops.yml` reports
  `changed` on every run (`changed_when: true`) and notifies
  `container-recreate`, so every role sync recreates the container even when no
  setting moved. Option: add `AND value IS DISTINCT FROM '<value>'::jsonb` to
  the `UPDATE` and derive `changed_when` from `UPDATE 1` in its output.
- The same task renders each setting value into the `shell:` heredoc, so the
  SMTP password, the OIDC client secret, the hCaptcha secret and the S3 secret
  key travel in the `bash -c` argv; `no_log` follows `MASK_CREDENTIALS_IN_LOGS`,
  which local deploys disable. Option: send the SQL on `stdin:` to
  `LISTMONK_EXEC_DATABASE`, as the administrator password task does.
- `LISTMONK_DESIGN_BRANDING` in `vars/main.yml` and the `DESIGN_*_URL` keys in
  `templates/playwright.env.j2` read `LISTMONK_DESIGN.urls` unguarded. The
  design lookup builds those URLs for every slot, while
  `roles/sys-front-inj-design/tasks/assets.yml` publishes the files only when
  `design.logo` is a string, so with the logo replacement switched off
  `app.logo_url` and `app.favicon_url` point at files that do not exist and the
  design spec asserts them anyway. Option: take the `fallback` for both keys
  unless `LISTMONK_DESIGN.logo is string`, render the URL keys empty in that
  case like the other roles, and skip the logo assertions on empty keys.
