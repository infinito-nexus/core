# TODO

- The collaborator mapping has no Playwright scenario yet. Fider's OAuth provider maps no groups claim, so `users.role` follows a role group change only when `files/sql/reconcile-roles.sql` runs through `sys-ctl-mtn-rbac-sync`; the Playwright runner now starts that sync every 60 seconds while the specs of an RBAC-hooked role run, so a spec can add a member to the collaborator group and wait for the role.
