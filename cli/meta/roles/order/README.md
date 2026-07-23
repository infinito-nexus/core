# Order 📜

Show role execution order from both scheduling layers: `run` prints the group-file call order of the main pass (`tasks/groups/*.yml`), `preload` prints the sys-service-loader preload order (run_after topological sort over the service registry).
