# TODO

- Local deploy without LAM: `meta/variants.yml` variant 0 pins `services.lam` on while `meta/services.yml` declares no `lam` entry, so `disable=lam` writes no override and `make compose-deploy apps=web-app-openbao variant=0 disable=...,lam` aborts with "`disable` conflicts with the current inventory state"; without `lam` in the list the round deploys `web-app-lam` even when `ldap` is disabled. Declare `lam` in `meta/services.yml` with the `'web-app-lam' in group_names` flags, or let the services disabler flip keys that only a variant bakes.
