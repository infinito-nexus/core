# Todo

- Implement RBAC via LDAP
- `tasks/04_admin.yml:16` passes the administrator password as `-e OPENPROJECT_ADMIN_PASSWORD=<value>` in the `argv` of `container exec`, so a `-vv` deploy log prints it and `expand_argument_vars` rewrites a `$NAME` sequence inside it; forward it as `-e OPENPROJECT_ADMIN_PASSWORD` plus the task's `environment:`. The same task reports `changed` on every run; give it a `changed_when` on an output line the script prints only on a real change.
- `tasks/02_settings.yml:58` renders `OPENPROJECT_RAILS_SETTINGS` including `smtp_password` into the shell command line as `-e OPENPROJECT_RAILS_SETTINGS=<json>`; forward it as `-e OPENPROJECT_RAILS_SETTINGS` plus `environment:`, or feed the JSON on stdin.
- "Run database migrations" and "Set settings in OpenProject" report `changed` on every deploy, next to the admin task above (measured 2026-10-11 in two consecutive closing role syncs), so a deploy never shows the role idempotent. Options: a `changed_when` on output the migration and settings scripts print only when they changed something.
