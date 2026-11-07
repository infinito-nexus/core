# 076 - Remote LiteLLM Gateway

## User Story

As an operator of several hosts, I want galaxyserver, hotelserver and every further host to use the one LiteLLM gateway on echoserver over the WireGuard mesh, each host with its own virtual key, so that models, provider keys and spend live in one place and a small host such as a Raspberry Pi runs no gateway of its own.

## Decisions (2026-11-01)

1. One central `svc-ai-litellm` on echoserver (`infinito.nexus`) serves every consuming host. galaxyserver and the Raspberry Pi host `hotelserver` are the first consuming hosts. A consuming host runs no `svc-ai-litellm` of its own.
2. Each consuming host gets its own LiteLLM virtual key on the gateway.
3. Consuming hosts reach the gateway over the WireGuard mesh only. The gateway is not exposed on a public domain for them.
4. Until this requirement is implemented, every host keeps its own `svc-ai-litellm`.
5. Implementation starts only on the operator's word.

## Current State (2026-11-01)

- `LITELLM_USABLE` is true only when the host itself carries `svc-ai-litellm` and that gateway serves a chat model.
- Container consumers read `LITELLM_BASE_LOCAL_URL` or `LITELLM_OPENAI_BASE_LOCAL_URL`, the gateway's container name on its internal port. Host-mode consumers (`dsk-gnt-claude`, `dsk-gnt-codex`, `dsk-gnt-pi`) read `LITELLM_OPENAI_BASE_LOOPBACK_URL`.
- The consumer contract in `svc-ai-litellm` refuses every other base URL: a dotted host, a port other than the internal one, or a non-loopback host in host mode.
- The gateway registers one virtual key per consumer role at its deploy, with the gateway's master key. The alias is the application id and the value is the consumer's `credentials.litellm_api_key` from the same host's inventory.
- A consumer whose `services.litellm` is enabled and shared pulls `svc-ai-litellm` in as a provider.
- The gateway publishes its port only on `DOCKER_BIND_HOST`, which is the loopback address outside development containers.
- The `dsk-gnt-*` roles already accept a hand-carried `gateway_url` and `gateway_key` for a gateway deployed from another inventory.
- `svc-net-wireguard` names mesh peers by inventory hostname. `cli.administration.inventory.mesh` writes each host's mesh address, keys and peers into that host's `host_vars` in one pass over every inventory, and `lookup('mesh_address', <host>)` returns a host's primary mesh address, IPv4 only.
- Spoke-to-spoke forwarding through a compose hub is still an open criterion of requirement 043.

## Acceptance Criteria

### Inventory

- [x] An inventory value in `roles/svc-ai-litellm/meta/services.yml`, empty by default, names the gateway host of a consuming host by its inventory hostname. `services.litellm.gateway_host: ""`, read once as `LITELLM_GATEWAY_HOST` in `group_vars/all/16_ai.yml`; [test_litellm_remote_gateway.py](../../tests/unit/python/group_vars/test_litellm_remote_gateway.py) renders both values.
- [ ] A host whose value is empty deploys and uses its own `svc-ai-litellm` exactly as before. **Static half held:** every gateway variable resolves to its previous expression while the value is empty (`test_a_host_without_a_gateway_value_resolves_as_before`, and [test_litellm_chat_model.py](../../tests/unit/python/group_vars/test_litellm_chat_model.py) through the new wrapper); the deploy half is any existing gateway round.
- [x] One inventory pass over every inventory of the deploy writes the gateway's mesh URL and the host's virtual key into each consuming host's `host_vars`, and the key of every consuming host into the gateway host's `host_vars`, each key vault-encrypted with the vault password of the host that holds it. `python -m cli.administration.inventory.gateway`; [test_cli.py](../../tests/unit/python/cli/administration/inventory/gateway/test_cli.py) decrypts both halves, each with its holder's password.
- [x] Re-running the pass changes no file, and its rotation option replaces the key of the one named consuming host and no other. `--rotate HOST`; `test_a_rerun_changes_no_file` compares every file byte for byte, `test_rotation_replaces_the_key_of_the_named_host_only` the other host's file and its gateway entry.
- [x] The pass fails with a message naming both hosts when the gateway host or a consuming host holds no mesh address. `test_a_missing_mesh_address_names_both_hosts`, which also proves nothing is written.
- [ ] The gateway host and each consuming host deploy from an inventory that holds only that host. Every value a consuming host needs is in its own host_vars and the contract reads the gateway's mesh address from the host's own interface peers, never from another host's hostvars; only a deploy proves it.

### Gateway

- [ ] The gateway answers on the gateway host's mesh address at its published port (`ports.local.http`), and a connection to that port on any public address of the gateway host is refused. `compose.yml.j2` publishes the port on the loopback and the mesh address only, once the host holds a consuming host's key; compose only, since swarm ignores a bind address.
- [ ] After a reboot of the gateway host, the gateway answers on its mesh address without a redeploy. **Blocked:** `svc-net-wireguard` raises each interface with `wg-quick up` and enables no `wg-quick@<mesh>` unit, so after a reboot the mesh address does not exist until a redeploy, and the engine cannot bind a published port to an address that does not exist yet.
- [ ] The gateway's deploy adds no vhost, domain or certificate for consuming hosts. The role declares no `meta/server.yml` and the remote path adds none; only a deploy shows the proxy untouched.
- [x] The gateway's deploy registers the key of each consuming host under an alias that names the host and differs from the alias of every local consumer. `host:<hostname>` through `litellm_gateway_keys` in [gateway.py](../../plugins/filter/litellm/gateway.py), which refuses a repeated alias or a shared key; [test_gateway.py](../../tests/unit/python/plugins/filter/litellm/test_gateway.py).
- [ ] Removing a host's gateway value, re-running the pass and redeploying the gateway host deletes that host's key, and the gateway refuses the key afterwards. **Static half held:** the pass drops both halves (`test_removing_the_value_drops_the_host_on_both_sides`) and `ensure_keys.py` deletes every `host:` alias no longer listed (`TestRevokeStaleHostKeys`); the refusal afterwards is the gateway's.
- [ ] Revoking the key of one consuming host leaves every other consuming host and every local consumer of the gateway answering. Each host holds its own key and revocation deletes by alias, but only a running gateway shows the others answering.
- [x] Local consumers on the gateway host keep the container-network URL and their own per-consumer keys. `test_a_host_without_a_gateway_value_resolves_as_before`, `test_beside_its_own_gateway_a_consumer_presents_its_own_key` in [test_litellm_api_key.py](../../tests/unit/python/plugins/lookup/test_litellm_api_key.py), and `test_without_consuming_hosts_the_local_list_is_unchanged`.
- [x] No `host_vars` of a consuming host and no file rendered on a consuming host holds the gateway's master key. The pass writes only `gateway_key` there (`test_a_consuming_host_never_receives_the_master_key`), and the master key is read by `svc-ai-litellm` alone, which refuses to run on a consuming host.

### Consuming host

- [ ] A host that carries `svc-ai-litellm` and names a gateway host fails the deploy with a message naming both hosts. The first task of `tasks/00_core.yml` fails with both names; no test runs an Ansible task, so a deploy proves it.
- [ ] On a consuming host, inventory provisioning adds no `svc-ai-litellm`, no consumer pulls it in as a shared provider, and no gateway container runs. **Static half held:** provisioning drops the role before credentials are minted ([test_remote_gateway.py](../../tests/unit/python/cli/administration/inventory/provision/test_remote_gateway.py)), and every consumer's `services.litellm.shared` is `LITELLM_SHARED`, false on a consuming host (`test_a_consuming_host_shares_no_local_gateway`), so neither the service loader nor a network attachment asks for the gateway; that no container runs is a deploy observation.
- [x] On a consuming host, `LITELLM_USABLE` is true when the host holds the gateway's mesh URL and its key, and every consumer gated on it is enabled. `test_a_consuming_host_is_usable_without_a_gateway_of_its_own`; it also needs the carried chat model, without which no consumer could name one.
- [x] On a consuming host, every consumer's gateway base URL is `http://<gateway mesh address>:<published port>`, with `/v1` where the consumer uses the OpenAI path, resolved in one place in `group_vars`, and no consumer role holds a branch of its own for the remote gateway. `LITELLM_BASE_LOCAL_URL`, `LITELLM_OPENAI_BASE_LOCAL_URL` and `LITELLM_BASE_LOOPBACK_URL` resolve to the carried URL; `test_a_consuming_host_points_every_consumer_at_the_mesh_url`.
- [x] Every consumer on a consuming host authenticates with that host's key, and the gateway mints no key per consumer of a consuming host. Every consumer reads its key through `lookup('litellm_api_key', application_id)`, which answers with `credentials.gateway_key` on a consuming host (`test_on_a_consuming_host_every_consumer_presents_the_host_key`); the gateway registers one `host:` key per host.
- [x] Host-mode consumers (`dsk-gnt-claude`, `dsk-gnt-codex`, `dsk-gnt-pi`) on a consuming host reach the gateway on the same mesh URL with the host key. They read `LITELLM_OPENAI_BASE_LOOPBACK_URL`, which resolves to the mesh URL there, and the same key lookup.
- [x] On a consuming host, the consumer contract accepts only the gateway's mesh URL (plain `http`, the gateway host's mesh IPv4 address, the published port) and refuses every other base URL, including the domain of `web-app-litellm`. `litellm_gateway_refusal` in `mesh` mode; `TestMesh` in [test_gateway.py](../../tests/unit/python/plugins/filter/litellm/test_gateway.py).
- [ ] On a consuming host, every consumer is configured with the gateway host's `LITELLM_CHAT_MODEL`. Consumers read `LITELLM_CHAT_MODEL`, which is the carried `gateway_model` there, and the deploy stops unless the gateway lists it; the pass takes the value from `--chat-model` rather than deriving it from the gateway host's `group_vars`.

### Failure behaviour

- [ ] Before it configures any consumer, the deploy of a consuming host requests the gateway's model list over the mesh with the host key, and fails with a message naming the gateway host and its mesh URL when the gateway does not answer, refuses the key, or does not list the configured chat model. `roles/svc-ai-litellm/tasks/utils/remote_gateway.yml`, included by `tasks/stages/01_constructor.yml` before the shared services preload; a deploy proves it.
- [ ] While the mesh or the gateway is down, an AI request of a consumer on a consuming host fails with an error, and no consuming host starts a local gateway or sends the request to another endpoint. Every consumer URL resolves to the mesh URL only and the gateway role refuses to run there, so no fallback exists to take; only a stopped gateway shows the error.

### Tests

- [x] Unit tests cover the consumer contract for the container-network, loopback and mesh URL, including a refused public domain and a refused mesh address of another host. [test_gateway.py](../../tests/unit/python/plugins/filter/litellm/test_gateway.py).
- [x] Unit tests cover the inventory pass: first write, unchanged re-run, rotation of one host, removal of one host and a missing mesh address. [test_cli.py](../../tests/unit/python/cli/administration/inventory/gateway/test_cli.py).
- [x] A unit test asserts the gateway's key list for local consumers and consuming hosts, with distinct aliases. `TestGatewayKeys` in [test_gateway.py](../../tests/unit/python/plugins/filter/litellm/test_gateway.py).
- [ ] An end-to-end test joins a gateway host and a consuming host on one mesh, deploys both, and asserts that a consumer on the consuming host receives an answer from the gateway's mock model and that the consuming host runs no `svc-ai-litellm` container.
- [ ] An end-to-end test stops the gateway and asserts that the deploy of the consuming host fails with the message naming the gateway host.

### Documentation

- [x] `roles/svc-ai-litellm/README.md` documents how a host is pointed at the central gateway, that the gateway host deploys first, and how the key of one host is rotated and revoked. Section "Central gateway for several hosts".

### Rollout

- [ ] galaxyserver and hotelserver name echoserver as their gateway host, run no `svc-ai-litellm`, and their AI consumers answer through the gateway on echoserver.
