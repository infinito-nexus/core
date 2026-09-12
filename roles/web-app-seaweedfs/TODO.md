# TODO

## Object-store (S3) consumer integration — roles not yet wired

SeaweedFS is the shared S3 object store. A role becomes a consumer by declaring a
`seaweedfs` service in `meta/services.yml`, wiring its app config from
`lookup('objstore', application_id, ...)` (bucket / access_key / secret_key / url /
region), and shipping a gated `files/playwright/test-seaweedfs.js`. See
`web-app-mastodon`, `web-app-pixelfed`, and `web-app-nextcloud` for the reference
pattern. SeaweedFS S3 requires **path-style addressing** and the internal `http://`
endpoint.

The roles below are database-backed and their upstream app can store objects in S3,
so the integration is **fundamentally possible but not yet implemented**. Roles whose
upstream has no S3 backend, or whose S3 client is incompatible with SeaweedFS
path-style, are listed at the end.

### Possible via an upstream plugin/extension

| Role | Mechanism (verify exact upstream keys before wiring) |
|---|---|
| `web-app-moodle` | `tool_objectfs` object-file-storage plugin |
| `web-app-wordpress` | media-offload plugin (e.g. WP Offload Media) |
| `web-app-mediawiki` | `Extension:AWS` (S3 file backend) |
| `web-app-odoo` | S3 `ir_attachment` / attachment-storage module |
| `web-app-erpnext` | frappe S3 backups + file storage |
| `web-app-joomla` | S3 storage plugin |

### Possible — upstream S3 support still to confirm

| Role | Note |
|---|---|
| `web-app-jira` | Atlassian DC attachment store on S3 (edition/version dependent) |
| `web-app-confluence` | Atlassian DC attachment store on S3 (edition/version dependent) |
| `web-app-suitecrm` | confirm upstream S3 file-storage support |
| `web-app-espocrm` | confirm upstream S3 attachment support |
| `web-app-zammad` | confirm upstream storage-provider S3 support |
| `web-app-xwiki` | confirm S3 attachment store support |

### Blocked — possible only with a provider-side change

| Role | Blocker |
|---|---|
| `web-app-discourse` | Discourse's `aws-sdk-s3` defaults a custom endpoint to virtual-host addressing and exposes no `force_path_style`; it needs SeaweedFS to serve virtual-host/wildcard-DNS addressing (a global provider change affecting all path-style consumers) before it can use S3. |

### Not currently possible

| Role | Reason |
|---|---|
| `web-app-pretix` | Open-source pretix has no S3/object-store backend (local `MEDIA_ROOT` only; no django-storages/boto3, no config hook). |

Roles with no object-store surface at all (e.g. `web-app-keycloak`, `web-app-matomo`,
`web-app-pgadmin`, `web-app-phpmyadmin`, `web-app-yourls`, `web-app-stalwart`) keep their
`# nocheck: seaweedfs-required` exemption and are intentionally excluded.
