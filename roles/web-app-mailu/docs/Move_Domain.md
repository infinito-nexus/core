# **How to Migrate Mailboxes to a New Domain in Mailu** 📖

When changing the primary email domain (e.g., from `cymais.cloud` to `infinito.nexus`), it is **not enough** to simply rename mailbox directories on disk. Mailu manages domain and user records in its internal database, and Dovecot maintains index files inside each Maildir. A blind rename will lead to login failures, rejected mail, or corrupted mail indices.

This guide explains the **safe procedure** for migrating user mailboxes to a new domain.

---

## Why renaming folders directly does not work 🔴

* Mailu keeps **domains, users, and aliases** in the `admin_data` database. If you rename folders only, Mailu will not recognize the new accounts.
* Dovecot generates `.dovecot.index*` and `dovecot-uidlist` files in each mailbox. These must be rebuilt when moving mailboxes; otherwise, users may see missing or broken mail.
* Postfix will refuse to deliver or relay messages for unknown domains.

---

## Correct migration procedure ✅

### 1. Add the new domain and users in Mailu

Use the Mailu CLI inside the `admin` container:

```bash
# Add new domain
compose exec admin flask mailu domain add infinito.nexus

# Add new user (repeat for each account)
compose exec admin flask mailu user kevinveenbirkenbach infinito.nexus 'NEW_PASSWORD'
```

---

### 2. Copy or move existing Maildir contents

Instead of renaming, copy the entire Maildir from the old domain to the new one:

```bash
rsync -aHAX --numeric-ids \
  /var/lib/docker/volumes/mailu_dovecot_mail/_data/kevinveenbirkenbach@cymais.cloud/ \
  /var/lib/docker/volumes/mailu_dovecot_mail/_data/kevinveenbirkenbach@infinito.nexus/
```

---

### 3. Remove old Dovecot index files

Ensure that Dovecot rebuilds indices cleanly:

```bash
find /var/lib/docker/volumes/mailu_dovecot_mail/_data/ -type f -name '.dovecot*' -print -delete
find /var/lib/docker/volumes/mailu_dovecot_mail/_data/ -type f -name 'dovecot-uidlist*' -print -delete

```

---

### 4. Fix file permissions

Make sure all mailbox files belong to the `mail:mail` user/group:

```bash
chown -R mail:mail /var/lib/docker/volumes/mailu_dovecot_mail/_data/kevinveenbirkenbach@infinito.nexus
```

---

### 5. Restart services and test login

After copying, restart Mailu services (or at least `imap` and `smtp`) and confirm that users can log in with their new addresses.

---

### 6. (Optional) Keep the old domain as an alias

To ensure incoming mail for the old domain is still accepted:

```bash
compose exec admin flask mailu domain alias add cymais.cloud infinito.nexus
```

This maps all `@cymais.cloud` addresses to their equivalents under `@infinito.nexus`.

---

## Summary 💡

* Do **not** just rename mailbox folders.
* Always create the new domain and user in Mailu first.
* Copy existing Maildir contents into the new user’s directory.
* Remove Dovecot indices and fix permissions.
* Optionally configure a **domain alias** so old addresses remain valid.
