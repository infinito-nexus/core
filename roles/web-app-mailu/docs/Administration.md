# Administration 🕵️‍♂️

## Database Access 📂

To access the database, use the following command:

```bash
compose exec -it database mysql -u root -D mailu -p
```

## Container Access 🖥️

To access the front container, use this command:

```bash
compose exec -it front /bin/bash
```

## Restarting Services 🔄

To restart all services, use the following command:

```bash
compose restart
```

## Resending Queued Mails ✉️

To resend queued mails, use this command:

```bash
compose exec -it smtp postqueue -f
```

## Updates 🔄

For instructions on updating your Mailu setup, follow the official [Mailu maintenance guide](https://mailu.io/master/maintain.html).

## Queue Management 📬

To manage the Postfix email queue in Mailu, you can use the following commands:

- **Display the email queue**:

  ```bash
  compose exec -it smtp postqueue -p
  ```

- **Delete all emails in the queue**:

  ```bash
  compose exec -it smtp postsuper -d ALL
  ```
