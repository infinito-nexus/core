# Nextcloud Applications

Details on specific apps like Cospend, including related SQL queries and debugging tips.

## receive Plugin Information

To receive the relevant configuration options for a plugin type:

```bash
compose exec -u www-data application php occ config:list oidc_login
```

## App Relevant Tables 🗃️

- `oc_appconfig`
- `oc_migrations`

## LDAP

## Cospend

### Relevant SQL Commands for Cospend

Debugguging Migrations:

<https://github.com/julien-nc/cospend-nc/issues/325>

```sql
-- Show all Cospend Tables
SHOW TABLES where Tables_in_nextcloud LIKE "%cospend%";
-- Show Cospend Configuration
SELECT * FROM `oc_appconfig` WHERE appid LIKE "%cospend%";
-- Show Cospend Database Migrations 
SELECT * FROM `oc_migrations` WHERE app LIKE "%cospend%";
```
