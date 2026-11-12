# To-dos

- Verify the web SAPI where an image splits it from the CLI. `web-app-lam` mounts the hardening ini into both `/etc/php/8.4/apache2/conf.d` and `/etc/php/8.4/cli/conf.d`, and the probe reads only the CLI copy, so a wrong Apache target would still pass.
- Restore the workspace drills' databases in `call-test-workspace.yml` from the Actions cache of the `vulnerability-db` job instead of refreshing them in the job.
