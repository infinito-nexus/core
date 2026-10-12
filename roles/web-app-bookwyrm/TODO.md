# Todos

- Store user exports in object storage instead of local container storage.
  Currently `USE_S3_FOR_EXPORTS=false` (templates/env.j2): media (avatars, covers)
  goes to the public objstore bucket, but private account exports stay on the
  container's local filesystem. They cannot share the media bucket: the objstore
  model gives one bucket per app and SeaweedFS enforces no per-prefix ACL, so an
  anonymous-readable (`public: true`) media bucket would also expose `exports/`.
  Clean fix requires extending the `objstore` lookup to resolve a second, named,
  private (`public: false`) bucket per app (e.g. `bookwyrm-exports`), provision it
  with the app's S3 key, and grant anon-read only on the media bucket. Then set
  `USE_S3_FOR_EXPORTS=true` + `EXPORTS_STORAGE_BUCKET_NAME` to that private bucket
  (BookWyrm already uses `default_acl: private` + `querystring_auth: True`, so
  signed-URL access keeps exports private). Touches shared objstore infra, so it
  belongs in its own PR alongside other private-data consumers.
- `REGISTRATION_OPEN` and `ALLOW_INVITE_REQUESTS` in `templates/env.j2` have no effect: BookWyrm v0.9.3 reads neither key (absent from `bookwyrm/settings.py`); registration and invite requests live in `SiteSettings.allow_registration` and `SiteSettings.allow_invite_requests` (the landing page shows the invite request form because the latter defaults to true). Options: drop both keys and the `registration_open`/`allow_invite_request` config, or converge the two `SiteSettings` fields in `files/python/site_design.py`.
- `PERSONA_ADMINISTRATOR_BLOCKED` in `templates/playwright.env.j2` still cites a missing staff account; `tasks/01_site.yml` now provisions the administrator as superuser with the `admin` and `moderator` groups, so only the icon-only logout dropdown remains as the blocker. Options: give the shared in-app-logout helper a match for `details#navbar-dropdown` or label the control, then unblock both personas.
- `files/playwright/test-seaweedfs.js` fails on a stack with `seaweedfs` on and `sso` off (measured: `input[type="file"]` never attaches on `/preferences/profile`, 3 of 3 attempts): the action only signs in through Keycloak, so without SSO it stays anonymous and lands on `/login`. Options: sign in through BookWyrm's own `/login` form with the provisioned administrator when `sso` is off, or skip unless `sso` is enabled.
- Without the object store (variant 1, `seaweedfs` off) BookWyrm serves no `/static` and no `/images` at all (read in v0.9.3: `DEBUG` false, `bookwyrm/urls.py` adds `static()` only in debug, no whitenoise, the role has no web server in front of gunicorn), so that variant renders without stylesheet, scripts and logos. Not measured on the design stack, which runs with `seaweedfs`. Options: serve `STATIC_ROOT` and `MEDIA_ROOT` with whitenoise or a small nginx sidecar when `seaweedfs` is off.
