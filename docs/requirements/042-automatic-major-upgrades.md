# 042 - Automatic Major Upgrades

## User Story

As an operator upgrading a long-running host across several major versions of its applications, I want every deploy to detect the version that the existing data was written by and to step through every mandatory intermediate version on its own, or to stop loudly where no forward path exists, so that one deploy brings old data to the pinned version without manual upgrade stops, silent downgrades or stale code and asset volumes.

## Acceptance Criteria

- [ ] `svc-db-postgres` detects the major version of an existing cluster from `PG_VERSION`, in the volume root, in `pgdata/` and in `<major>/docker`, without any inventory value.
- [ ] `svc-db-postgres` upgrades an older cluster major by major with `pg_upgrade --link` in an upgrade image that carries the old and the new server binaries and the extension packages the role declares, and starts the pinned major on the upgraded data.
- [ ] `svc-db-postgres` keeps a reflink copy of the old data directory before the first `pg_upgrade --link` where the filesystem supports reflinks, and otherwise stops with a message that names the missing backup confirmation.
- [ ] A compose deploy of `svc-db-postgres` on a PostgreSQL 17 volume in each of the three layouts ends on the pinned major with every database and role intact.
- [ ] `web-app-nextcloud` detects the installed version from `version.php` in its code volume and upgrades one major at a time up to the pinned version.
- [ ] A compose deploy of `web-app-nextcloud` on data written by Nextcloud 31 ends on the pinned major, and `occ status` reports it.
- [ ] `web-app-peertube` detects the version the existing data was written by without any inventory value and runs every `dist/scripts/migrations/peertube-X.Y.js` above that version up to the pinned version, in order, after the server migrations finished.
- [ ] `web-app-peertube` replaces the image-seeded `peertube_assets` volume whenever the deployed version changes.
- [ ] A compose deploy of `web-app-peertube` on data written by 7.3.0 ends on the pinned version, serves the client of the pinned version and keeps uploaded videos playable.
- [ ] `web-app-openproject` detects the schema stage of an existing database and passes through every major the upstream requires between it and the pinned major.
- [ ] A compose deploy of `web-app-openproject` on a database written by 15.x ends on the pinned major with the seeder exiting 0.
- [ ] `web-app-moodle` detects the release in its code volume and passes through every intermediate release that Moodle requires before the pinned release.
- [ ] A compose deploy of `web-app-moodle` on a code volume below the pinned release's minimum upgrade source ends on the pinned release.
- [ ] `web-app-joomla` detects the core version in its code volume and updates the core up to the pinned major, including the database schema.
- [ ] A compose deploy of `web-app-joomla` on a 5.x code volume ends on the pinned major with SSO enabled.
- [ ] `web-app-bluesky` stops with a message naming both versions when the PDS data carries migrations the pinned image does not know.
- [ ] `web-app-confluence` and `web-app-jira` stop with a message naming both build numbers when the home directory was written by a newer build than the pinned image.
- [ ] `web-app-mediawiki` replaces the image-seeded `mediawiki_extensions` volume and reinstalls its add-on extensions whenever the MediaWiki version changes.
- [ ] A compose deploy switches an existing `web-app-matrix` from `flavor: compose` on Synapse 1.144.0 to `flavor: ansible` with the same signing key id, the old media readable and Synapse running as uid 991.
- [ ] Every new mechanism has unit tests, and `make test` passes.
