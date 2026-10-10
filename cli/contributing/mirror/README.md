# Mirror 🪞

Plan and execute the GHCR image mirror pipeline: emit the `mirrors.yml` mapping that redirects role-declared images to the GHCR mirror, push images upstream-to-GHCR, and clean up stale mirror packages.

The sync also mirrors the images the CI runner pulls itself, outside every role: the tagged `image` literals of `compose.yml` and `compose/cache.override.yml`, and the image keys of `default.env` listed in `RUNNER_ENV_IMAGES` ([discovery.py](../../../utils/docker/image/discovery.py)). On a GitHub runner, [runner_mirror.py](../../administration/deploy/development/runner_mirror.py) layers a generated compose override that points those services at their mirror, and hands the certificate generator the mirrored init image.
