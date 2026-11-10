# Upgrade

Every deploy brings existing data to the pinned `services.peertube.version` without manual upgrade stops:

1. Before the pinned image starts, the role reads the release it recorded in `peertube.release` in the compose instance directory and `application.migrationVersion` from the database. `LAST_MIGRATION_VERSIONS` in [peertube_upgrade.py](filter_plugins/peertube_upgrade.py) maps the migration version to the release that wrote the data. The older of the two is the release the data is on.
2. The deploy waits up to 30 minutes for the server migrations and checks that the database reached the migration version of the pinned release.
3. It runs every `dist/scripts/migrations/peertube-X.Y.js` of the pinned image above the release of the data, oldest first.
4. When the `peertube_assets` volume may hold the client of another release, it empties the volume and recreates the container, so Docker seeds the volume from the pinned image.
5. It records the pinned release in `peertube.release`.

Data written by a newer release than the pinned one stops the deploy.
A pin missing from `LAST_MIGRATION_VERSIONS` fails the unit tests and the deploy. Add the `LAST_MIGRATION_VERSION` of the new release from `server/core/initializers/constants.ts` of its tag.

See the [upstream Docker guide](https://docs.joinpeertube.org/install/docker) for the manual procedure.
