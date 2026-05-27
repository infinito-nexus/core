# Administration

## View Logs

To check the latest logs of Akaunting.

```bash
compose exec -it akaunting tail -n 300 storage/logs/laravel.log 
```

## Access Containers

- Akaunting Container: `compose exec -it akaunting bash`
- Database Container: `compose exec -it akaunting-db /bin/mariadb -u admin --password=$akaunting_db_password akaunting`

## Manual Update

Execute PHP artisan commands in the following order for updating Akaunting:

```bash
php artisan about
php artisan cache:clear
php artisan view:clear
php artisan migrate:status
php artisan update:all
php artisan update:db
```

## Composer

To install Composer, a PHP dependency management tool:

```bash
curl https://getcomposer.org/download/2.4.1/composer.phar --output composer.phar
php composer.phar install
```
