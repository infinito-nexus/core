# TODO

- Drop the custom image build once the pinned Mobilizon release ships the PostgreSQL 18 migration fix (upstream merge request 1683, milestone 5.3.0). The build of `files/Dockerfile` fails on that release and names the migration that no longer needs the patch. Then delete `files/Dockerfile`, the `build` block in `templates/compose.yml.j2`, `MOBILIZON_IMAGE` and `MOBILIZON_VERSION` in `vars/main.yml`, and `custom: true` in `meta/services.yml`.
