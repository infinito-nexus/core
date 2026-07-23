# Installation and Configuration

## Initial Database Setup

The `listmonk` service command runs `./listmonk --install --idempotent --yes` on every container start, so the schema is seeded automatically on the first deploy.

## Start Services

Use the following command to start Listmonk services:

```bash
compose -p listmonk up -d --force-recreate
```
