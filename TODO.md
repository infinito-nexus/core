# Todos

- Implement multi language
- Implement rbac administration interface
- Enable IP6 for docker.
- backup docker to local für ca optimieren
- Fork [rpardini/docker-registry-proxy](https://github.com/rpardini/docker-registry-proxy) and teach the bundled nginx to handle GCP Artifact Registry redirect URLs (`/artifacts-downloads/namespaces/<ns>/repositories/<repo>/downloads/<token>`). Currently `gcr.io` blob pulls are bypassed via `NO_PROXY=…,gcr.io,storage.googleapis.com,googleusercontent.com` in [compose/registry-cache/proxy.conf](compose/registry-cache/proxy.conf), which is a workaround that disables caching for those registries. Long-term: rebase upstream's `proxy.conf` / `sub_filter` rules to recognise the new redirect shape, ship the fix in our fork, point `compose/registry-cache/Dockerfile` (or its image tag) at the fork, and drop the `NO_PROXY` bypass.

## Testing

- re-run with different credentials/configuration
- run over all distros for each app
- msg: can not use content with a dir as dest for NGINX multi distro
- split service database to postgres and mariadb
