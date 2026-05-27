# Administration

## database

If you use a local instead of a central database you can use the following commands.

### access database

To access the database execute:

```bash
  compose exec -it database /bin/mysql -u wordpress -p
```

### upgrade database

To upgrade the database execute:

```bash
  compose exec -it database /bin/mysql_upgrade --user=root --password=
```

## change database root password

- <https://wolfgang.gassler.org/reset-password-mariadb-mysql-docker/>
- <https://www.digitalocean.com/community/tutorials/how-to-reset-your-mysql-or-mariadb-root-password>

## shell in docker

To execute the commands in the container container execute:

```bash
compose exec -it application /bin/sh
```

## Test Email

To test the email execute:

```bash
compose exec -it application /bin/sh -c 'echo "Test Email" | sendmail -v your-email@example.com'
```
