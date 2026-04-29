# vars/

This directory contains variable definition files for the `svc-db-mariadb` Ansible role. It centralizes all configurable values related to MariaDB deployment and can be adjusted without modifying task logic.

---

## files and their purpose

### 1. `meta/services.yml`

The role's service config (file root IS the services map keyed by `<entity_name>`,
per [req-008](../../../docs/requirements/008-role-meta-layout.md)). For
`svc-db-mariadb` this carries the entity-keyed image, version, and hostname:

* **`version`** (string):

  * Default: `"latest"`
  * The MariaDB image tag to pull (e.g. `10.6`, `10.11`, or `latest`).

* **`hostname`** (string):

  * Default: `"central-mariadb"`
  * The container name and DNS alias within the `central_mariadb` network. Used by other services (like Moodle) to connect.

> **Tip:** Pin to a specific minor version (e.g., `10.6.12`) in production to avoid breaking changes on rebuilds.

---

### 2. `main.yml`

Minimal file defining the application identifier for the role.

* **`application_id`** (string):

  * Default: `"mariadb"`
  * Logical name used in templates, notifications, or paths when multiple roles/services may coexist.