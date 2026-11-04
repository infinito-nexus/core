# TODO

- The deployable server wraps the committed libraries and models the registry, lease table and audit chain in process, the same way `svc-ai-agent-orchestrator` does. The account creation against Keycloak and LDAP and the audit persistence to `svc-db-postgres` are the remaining runtime wiring: the connection parameters already reach the container through `templates/env.j2`, and the live I/O is proven on a cluster rather than in the static suite.
