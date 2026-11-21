# Help Assistant

## Description

The Infinito.Nexus help assistant answers a user's question with a short reply and links to the documents the reply comes from. It answers only from the documentation of the deployment it runs in, and says so when that documentation holds no answer. It is written in this repository and runs its models on CPU through [Ollama](https://ollama.com/), reached over the [`svc-ai-litellm`](../svc-ai-litellm/) gateway with the role's own virtual key.

## Overview

The role builds a small [FastAPI](https://fastapi.tiangolo.com/) service from `files/python/assistant/` and serves `POST <path>/ask`, with `<path>` set by `services.assistant.path` in [services.yml](./meta/services.yml). Its own vhost is `assistant.{{ DOMAIN_PRIMARY }}`; [location.conf.j2](./templates/nginx/location.conf.j2) is the location an app vhost includes to serve the same path same-origin, which is how the beaver lodge reaches it.

The role is skipped when [`svc-ai-ollama`](../svc-ai-ollama/) or the gateway is not part of the deployment, because without the model service there is nothing to answer with. It is also skipped while `services.assistant.models` names no model at all, so a deployment never builds, starts or indexes an assistant that has no pinned model to answer with.

Every deploy rebuilds the knowledge index in the deployment's own PostgreSQL through the `vector` extension. The index is built from:

| Source | Staged from | Linked to |
| --- | --- | --- |
| Platform documentation | `services.assistant.index.platform_docs` of this repository | `services.assistant.index.link_base` |
| Role READMEs | the `README.md` of every role deployed on the host | `services.assistant.index.link_base` |
| Tenant documents | each entry of `services.assistant.index.tenant_sources` | the entry's `url` |

A tenant adds its own documents in the inventory, without a code change:

```yaml
applications:
  web-svc-assistant:
    services:
      assistant:
        index:
          tenant_sources:
            - name: acme
              path: /srv/acme/help
              url: https://help.acme.example
```

Every indexed document can be quoted to an anonymous visitor: the persona changes the model, not the passages it may read. Add only documents that may be public.

## Features

- **Answers with sources:** every answer lists the documents it used, and a question the index holds nothing relevant for gets a fixed reply instead of a guess; `services.assistant.retrieval.threshold` sets how similar a passage must be to count.
- **Personas by role group:** a signed-in member of the role's `administrator` RBAC group gets the technical consultant, everyone else end-user support. The group is read from `X-Forwarded-Groups`, which only the oauth2 gate of the including vhost sets.
- **Anonymous rate limit:** an anonymous client gets `services.assistant.rate_limit.requests` questions per `window` seconds per address and a `429` with `Retry-After` beyond that.
- **Nothing kept:** no question or answer is stored, and the service log carries a fixed event name and counters only.
- **No secret in the index:** only Markdown outside every inventory, variable and secret path is read, and each passage passes the repository's secret patterns, a Vault filter and an e-mail filter before it is embedded.
- **Pinned models:** `services.assistant.models` holds one pinned gateway alias per persona model and one for the embedding model; once any of them is named, the service refuses to start on an empty reference, a bare name or a floating tag.

## Developer notes

The role is `pre-alpha`: the persona models and the embedding model are published by the separate `llm` repository, and `services.assistant.models` stays empty until it pins them, so the role skips itself until then.

## Further resources

- [LiteLLM proxy](https://docs.litellm.ai/docs/simple_proxy)
- [pgvector](https://github.com/pgvector/pgvector)
