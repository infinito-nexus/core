# To-dos

- Verify the web SAPI where an image splits it from the CLI. `web-app-lam` mounts the hardening ini into both `/etc/php/8.4/apache2/conf.d` and `/etc/php/8.4/cli/conf.d`, and the probe reads only the CLI copy, so a wrong Apache target would still pass.
- Restore the workspace drills' databases in `call-test-workspace.yml` from the Actions cache of the `vulnerability-db` job instead of refreshing them in the job.
- Let Trivy read a container image without an export. `trivy image --image-src docker` still makes the daemon stage the image and saves it into Trivy's temp directory, so a Trivy run needs twice the image on disk; its `rootfs` mode over the image mount Syft reads would avoid that, but merges the layers whose Red Hat content manifests Trivy reads per layer.
