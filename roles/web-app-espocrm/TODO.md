# Todos

- `templates/env.j2` sets `ESPOCRM_CONFIG_DEFAULT_CURRENCY` to the host currency (measured `EUR`) while `currencyList` and `baseCurrency` stay at the upstream `USD`, so `POST api/v1/Opportunity` with the default currency fails with `Field validation failure; entityType: Opportunity, field: amount, type: validCurrency`. Options: also set `ESPOCRM_CONFIG_CURRENCY_LIST` and `ESPOCRM_CONFIG_BASE_CURRENCY` to the host currency, or keep the upstream default currency.
- `tasks/01_patch_config.yml` passes the database password in argv (`-e CONFIG_VALUE=<value>`), so a `-vv` deploy log prints it; forward it as `-e CONFIG_VALUE` plus `environment:` or prepend it to the script on stdin.
- `tasks/02_manager_ops.yml` reports "Realign the administrator password EspoCRM persisted at install" as changed on every run (`changed_when: rc == 0`), so a second deploy is never idempotent. Options: compare the stored hash first with a PHP check, as `files/php/set_siteurl.php` does for `siteUrl`.
