# Pixelfed Administration

## Accessing Services

### Application Access

To gain shell access to the application container, run the following command:

```bash
compose exec -it application bash
```

### Clear Cache

```bash
compose exec -it application php artisan cache:clear
```

### Database Access

To access the MariaDB instance in the database container, run the following command:

```bash
compose exec -it database mariadb -u pixelfed -p
```

### User Management via CLI in Pixelfed Docker Setup

To manage users in your Pixelfed instance running in a Docker container, as configured in Kevin Veen-Birkenbach's web-app-pixelfed role, you can follow these steps via the Command Line Interface (CLI):

1. **Access the Application Container:** First, gain shell access to the Pixelfed application container. Use the command provided in the README:

   ```bash
   compose exec -it application bash
   ```

   This command lets you access the bash shell inside the `application` Docker container where Pixelfed is running.

2. **Navigate to Pixelfed Directory:** Once inside the container, navigate to the Pixelfed directory. This is typically the root directory where Pixelfed is installed.

3. **Use Artisan Commands:** Pixelfed is built on Laravel, so you'll use Laravel's Artisan CLI for user management. Here are some common tasks:

   - **Create a New User:**

     ```bash
     php artisan user:create
     ```

     This command will prompt you to enter the user's details like username, email, and password.

   - **List Users:**

     ```bash
     php artisan user:list
     ```

     This command displays a list of all users.

   - **Delete a User:**

     ```bash
     php artisan user:delete {username}
     ```

     Replace `{username}` with the actual username of the user you wish to delete.

   - **Reset Password:**

     ```bash
     php artisan user:reset-password {username}
     ```

     This will initiate a password reset process for the specified user.

4. **Verify and Validate:** Depending on your Pixelfed's configuration, especially if email verification is required, you might need to perform additional steps to verify new accounts or modify user details.

5. **Exit the Container:** After completing your user management tasks, exit the Docker container shell by typing `exit`.

### Note

- **Commands Variability:** The available Artisan commands can vary based on your version of Pixelfed and Laravel. Always refer to the specific documentation for your version.
- **Permissions:** Ensure you have the necessary permissions and rights within the Docker container to perform these actions.
- **Environment Specifics:** The exact paths and commands may vary based on your Docker and Pixelfed setup, as defined in your `compose.yml` and other configuration files.

This process provides a streamlined way to manage Pixelfed users directly from the CLI in a Dockerized environment, ensuring that you can efficiently administer your Pixelfed instance without needing to access the Pixelfed web interface.

## Instagram Import Cleanup

If you have imported posts from Instagram, you can clean up the imported data and files as follows:

### Database Cleanup

Run these commands inside your MariaDB shell to remove import related data:

```bash
DELETE from import_posts WHERE 1;
DELETE from import_jobs WHERE 1;
DELETE from import_datas WHERE 1;
DELETE from statuses where created_at < "2022-12-01 22:15:39";
DELETE from media where deleted_at >= "2023-07-28 14:39:05";
```

### File System Cleanup

Run these commands to remove the imported files and trigger the cleanup job:

```bash
compose exec -u "www-data" application rm -rv "/var/www/storage/app/imports/1"
compose exec -u "www-data" application php artisan schedule:run
```

## Full Cleanup (Reset)

For a hard reset, which will delete all data and stop all services, use the following commands:

```bash
compose down
container volume rm pixelfed_application_data pixelfed_database pixelfed_redis
```

## Update Procedure

To update your Pixelfed instance, navigate to the directory where your `compose.yml` file is located and run these commands:

```bash
cd {{ DIR_COMPOSITIONS }}pixelfed/ &&
compose down &&
container network prune -f &&
compose pull &&
compose build &&
compose -p pixelfed up -d --force-recreate
```

## Inspecting the Services

To see the status of all services or follow the logs, use these commands:

```bash
compose ps -a
compose logs -f
```

## Debug

To debug the system set APP_DEBUG to true, like descriped [here](https://docs.pixelfed.org/).

```bash
nano config/app.php
php artisan cache:clear
php artisan route:cache
php artisan view:clear
php artisan config:cache
```

## Modifying files

```bash
apt update && apt upgrade && apt install nano
```
