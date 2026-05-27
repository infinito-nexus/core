# Hugo: Administration

## Force a rebuild

The Hugo site is built into the custom Docker image at `compose build` time. The build is content-keyed via the cloned `services/repository/` tree, so:

- **A change in `services.hugo.source_version`** invalidates the clone, which invalidates `COPY ./services/repository/` in the Dockerfile, which triggers a fresh `hugo` build on the next deploy.
- **A force rebuild** without a source-version change can be triggered by clearing the role's image cache:

  ```bash
  make compose-exec cmd="docker compose -f /opt/docker/web-app-hugo/docker-compose.yml build --no-cache"
  ```

  The next `make compose-deploy mode=update apps=web-app-hugo` will pull the image, restart nginx, and serve the freshly rendered output.

## Bumping the source version

1. Pick the new tag/commit in the upstream repository (default: [gohugoio/hugoDocs releases](https://github.com/gohugoio/hugoDocs/releases)).
2. Update `roles/web-app-hugo/meta/services.yml`:

   ```yaml
   hugo:
     source_version: <new-tag>
   ```

3. Re-deploy:

   ```bash
   make compose-deploy mode=update apps=web-app-hugo
   ```

4. Verify in the browser that the content reflects the new version.

## Debugging a failed Hugo build

The Hugo build runs inside `docker compose build`. If `hugo` exits non-zero, the play fails and the previous image keeps serving. To inspect the failure log:

```bash
make compose-exec cmd="docker compose -f /opt/docker/web-app-hugo/docker-compose.yml build --progress=plain --no-cache web-app-hugo 2>&1 | tail -200"
```

Common causes:

- **`hugo` reports unknown content / module errors**: the upstream repository moved a directory or a Hugo Module. Pin to a known-good tag in `source_version`.
- **`hugo` reports template execution errors**: the theme's templates are incompatible with the bundled Hugo binary. Bump `services.hugo.builder_version` (e.g. to a newer `exts-<version>` tag) or pin the source repo to a tag known to build with the current Hugo.
- **Module fetch fails (`go.mod` resolution)**: Hugo modules pull from `proxy.golang.org`. Network egress to that host must be allowed by the local firewall / proxy.

## Rotating the Hugo binary

To upgrade the extended Hugo binary independently of the content repo, edit `services.hugo.builder_version` in `meta/services.yml` (e.g. `exts-0.149.0`). The change invalidates only the builder layer, not the cloned repo, so the next `compose build` reuses the same content but with the new binary.
