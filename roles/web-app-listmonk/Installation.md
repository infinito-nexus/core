# Installation and Configuration

## Initial Database Setup

After the first setup, run the following command to initialize the Listmonk database:

```bash
docker compose run --rm application ./listmonk --install
```

## Start Services

Use the following command to start Listmonk services:

```bash
compose -p listmonk up -d --force-recreate
```
