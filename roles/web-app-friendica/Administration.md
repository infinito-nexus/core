# Administration

## CLI

The CLI you reach via

```bash
compose exec --user www-data application bin/console
```

## Full Reset 🚫➡️✅

The following environment variables need to be defined for successful operation:

- `DB_ROOT_PASSWORD`: The root password for the MariaDB instance

To completely reset Friendica, including its database and volumes, run:

```bash
# Assuming containername is mariadb
docker exec -i mariadb mariadb -u root -p"${DB_ROOT_PASSWORD}" -e "DROP DATABASE IF EXISTS friendica; CREATE DATABASE friendica;"
docker compose down
rm -rv /mnt/hdd/data/docker/volumes/friendica_data
container volume rm friendica_data
```

## Reset Database 🗄️

## Manual Method

1. Connect to the MariaDB instance:

   ```bash
   docker exec -it mariadb mariadb -u root -p
   ```

2. Run the following commands:

   ```sql
   DROP DATABASE friendica;
   CREATE DATABASE friendica;
   exit;
   ```

## Automatic Method

```bash
DB_ROOT_PASSWORD="your_root_password"
docker exec -i mariadb mariadb -u root -p"${DB_ROOT_PASSWORD}" -e "DROP DATABASE IF EXISTS friendica; CREATE DATABASE friendica;"
```

## Enter the Application Container 🔍

To access the application container:

```bash
compose exec -it application sh
```

## Debugging Tools 🛠️

## Check Environment Variables

```bash
compose exec -it application printenv
```

## Inspect Volume Data

```bash
ls -la /var/lib/docker/volumes/friendica_data/_data/
```

## Autoinstall 🌟

Run the following command to autoinstall Friendica:

```bash
compose exec --user www-data -it application bin/console autoinstall
```

## Reinitialization 🔄

## Docker Only

```bash
compose up -d --force-recreate
```

## Full Reinitialization

```bash
compose up -d --force-recreate && sleep 2; compose exec --user www-data -it application bin/console autoinstall;
```

## Configuration Information ℹ️

## General Configuration

```bash
cat /var/lib/docker/volumes/friendica_data/_data/config/local.config.php
```

## Email Configuration

```bash
compose exec -it application cat /etc/msmtprc
```

## Email Debugging ✉️

To send a test email:

```bash
compose exec -it application msmtp --account=system_email -t test@test.de
```
