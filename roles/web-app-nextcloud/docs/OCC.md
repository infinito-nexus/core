
# OCC (Nextcloud Command Line) 🔧

Reference for frequently used OCC commands, including user and app management.

## General Use

To use OCC, run:

```bash
compose exec -it -u www-data application /var/www/html/occ
```

## App Administration

```bash
compose exec -u www-data application php occ config:list {{app_name}}
```

## Initialize Duplicates

```bash
compose exec -it -u www-data application /var/www/html/occ duplicates:find-all --output
```

## Unlock Files

```bash
compose exec -it -u www-data application /var/www/html/occ maintenance:mode --on
compose exec -it nextcloud_database_1 mysql -u nextcloud -pPASSWORD1234132 -D nextcloud -e "delete from oc_file_locks where 1"
compose exec -it -u www-data application /var/www/html/occ maintenance:mode --off
```
