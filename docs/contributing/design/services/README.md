# Services 🧱

This directory contains contributor guidance for Infinito.Nexus shared services.
Its scope is the model that defines how shared services are declared, discovered,
loaded, injected, and consumed, plus the per-service contracts that role authors
and consumers MUST follow.

## Pages 📚

| Page | Purpose |
|---|---|
| [layout.md](layout.md) | Per-role `meta/<topic>.yml` shape, file-root convention, services-inlining rule, `meta/schema.yml` (incl. the `default:` field), per-role `networks:` and per-entity `ports` shape, `run_after`/`lifecycle` placement. |
| [base.md](base.md)     | Service registration, discovery, load order, injection model, lookup plugins. |
| [email.md](email.md)   | `email` lookup plugin contract. |
