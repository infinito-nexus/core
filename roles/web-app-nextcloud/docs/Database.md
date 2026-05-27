# Database Management (local)

To manage the database if you installed it locally use the following comments. If you have created the database via the central database option, look for the related documentation.

## Database Access

To access the database, execute:

```bash
compose exec -it database mysql -u nextcloud -D nextcloud -p
```

### Recreate Database with New Volume

```bash
compose run --detach --name database --env MYSQL_USER="nextcloud" --env MYSQL_PASSWORD=PASSWORD --env MYSQL_ROOT_PASSWORD=PASSWORD --env MYSQL_DATABASE="nextcloud" -v nextcloud_database:/var/lib/mysql
```
