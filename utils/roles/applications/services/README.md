# Application Service Helpers 🧩

Helpers that resolve and reason about per-application service declarations from `roles/<role>/meta/services.yml`.

## Scope 📋

Modules in `utils/roles/applications/services/` MUST limit themselves to the service-graph derived from `meta/services.yml`: registry construction, dependency resolution between provider and consumer roles, and database backend selection per application.

Modules in `utils/roles/applications/services/` MUST NOT take over wider application-config concerns that belong to the sibling `config` module (path-driven `applications.<id>.<dotted>` reads, schema validation).

## Modules 📦

- [registry.py](registry.py) builds the service registry from roles and resolves shared-service auto-include edges (`services.<X>.enabled` AND `services.<X>.shared`) to provider role names.
- [database.py](database.py) resolves the active database backend for an application (`mariadb`, `postgres`, ...) from its services map.

## Example Import ✍️

```python
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
    resolve_service_dependency_roles_from_config,
)
from utils.roles.applications.services.database import resolve_database_service_key
```
