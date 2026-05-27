# defaults/

This directory contains default variable definition files for the `svc-db-mariadb` Ansible role. It centralizes all configurable values related to MariaDB deployment and can be adjusted without modifying task logic.

---

## files and their purpose

### `main.yml`

Defines default values for how the MariaDB database should be created.

* **`database_encoding`** (string):

  * **Default:** `"utf8mb4"`
  * **Reasoning:**

    * **Full Unicode support**: `utf8mb4` is the only MySQL/MariaDB character set that fully implements 4‑byte UTF‑8, allowing storage of emojis, supplementary symbols, and all global scripts without data loss.
    * **Future‑proof:** Modern applications and standards have converged on UTF‑8; using `utf8mb4` avoids migration challenges later.
    * **Performance trade‑off:** While slightly more storage might be used compared to `latin1`, the universality of `utf8mb4` outweighs the cost for most deployments.

* **`database_collation`** (string):

  * **Default:** `"utf8mb4_unicode_ci"`
  * **Reasoning:**

    * **Accurate sorting & comparison:** This collation uses full Unicode algorithm rules, ensuring linguistically correct comparisons across many languages.
    * **Case‑insensitive (`ci`):** Most web apps expect case‑insensitive matching for usernames, emails, and search queries, improving usability.
    * **Neutral choice:** Unlike language‑specific collations, `unicode_ci` works robustly in multilingual contexts without bias.

> **Tip:** If you have a legacy application requiring a different charset or collation (e.g., for backward compatibility with existing data), simply override `database_encoding` and `database_collation` in your playbook-level variables.

## Overriding default variables

To customize any of these values without editing role defaults:

1. Create or update a playbook-level vars file (e.g. `group_vars/all/svc-db-mariadb.yml`).
2. Set the desired values, for example:

   ```yaml
   database_encoding: "latin1"
   database_collation: "latin1_swedish_ci"
   ```

3. Run your playbook. Ansible’s variable precedence ensures your overrides take effect.
