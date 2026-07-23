# User Administration

## Promoting an OIDC User to Admin 🧑‍💼

If your administrator logs in via OpenID Connect (OIDC) and you don't want to create a separate local user, you can promote the existing OIDC-authenticated user to a global admin directly in the Mailu database using the CLI.

Follow these steps:

1. Enter the Mailu `admin` container shell:

   ```bash
   docker exec -it mailu-admin-1 flask shell
   ```

2. Inside the interactive shell, run the following commands:

   ```python
   from mailu import models, db

   user = models.User.query.filter_by(email="admin@example.com").first()
   user.global_admin = True
   db.session.commit()
   ```

   Replace `admin@example.com` with the OIDC email address used to log in.

3. Exit the shell:

   ```python
   exit()
   ```

Your OIDC-authenticated user is now a full **global admin** and has access to all administrative functions in the Mailu interface.

> 💡 Tip: This method is useful when you're using federated login and want to avoid managing separate local admin credentials.

## Changing the Primary Domain of a Mailu Account (MariaDB) 🌐

Mailu links user accounts to specific domains, so changing a user's primary domain cannot be done via the admin interface. You need to update it manually via the database.

> ⚠️ **Warning:** Always back up your database before performing manual operations.

### Steps for MariaDB

1. Connect to the Mailu MariaDB container:

   ```bash
   compose exec -it database mariadb -u mailu -p
   ```

   Enter the password when prompted (you can find it in your `compose.yml` or `.env` file).

2. Select the Mailu database (usually named `mailu`):

   ```sql
   USE mailu;
   ```

3. Update the user's domain and email:

   ```sql
   UPDATE user SET email='newname@newdomain.com', domain_name='newdomain.com' WHERE email='oldname@olddomain.com';
   ```

   If needed, also update the local part (username):

   ```sql
   UPDATE user SET localpart='newname' WHERE email='newname@newdomain.com';
   ```

4. If the new domain does not exist yet, insert it into the `domain` table:

   ```sql
   INSERT INTO domain (name, max_users, max_aliases, max_quota_bytes, comment, enabled)
   VALUES ('newdomain.com', 100, 100, 10737418240, 'New domain', true);
   ```

5. If the user had aliases, update the `alias` table accordingly.

---

### Alternative: Recreate the User

If you prefer not to modify the database manually:

- Delete the old user via the admin UI
- Create a new user under the desired domain
- Migrate emails using IMAP tools (e.g. `imapsync`)

---

### Update DNS and Mailu Configuration

Ensure that the new domain is correctly set up:

- Add it to `HOSTNAMES` in your `compose.yml`
- Set up proper DNS records (MX, SPF, DKIM, DMARC)
- If using Let's Encrypt (`TLS_FLAVOR=cert`), make sure the domain is included in `LETSENCRYPT_HOSTS`

> 💡 **Tip:** Mailu must be aware of the domain both in its configuration and the database for mail routing and certificate issuance to work correctly.
