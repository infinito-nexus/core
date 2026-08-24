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
