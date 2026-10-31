# To-dos

- Extend `HEALTH_RUNTIME_FLOORS`, the container probe and `make security-runtimes` to `node`, `python`, `ruby` and `java`.
- Verify the web SAPI where an image splits it from the CLI. `web-app-lam` mounts the hardening ini into both `/etc/php/8.4/apache2/conf.d` and `/etc/php/8.4/cli/conf.d`, and the probe reads only the CLI copy, so a wrong Apache target would still pass.
- Run `make security-runtimes` in a scheduled CI workflow.
- Scan the pinned images for CVEs (Trivy or Grype) in the scheduled CI and report new criticals as issues.
