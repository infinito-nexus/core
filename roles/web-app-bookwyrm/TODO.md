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
