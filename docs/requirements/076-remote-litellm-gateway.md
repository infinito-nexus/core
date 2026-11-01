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

- [ ] An inventory value in `roles/svc-ai-litellm/meta/services.yml`, empty by default, names the gateway host of a consuming host by its inventory hostname.
- [ ] A host whose value is empty deploys and uses its own `svc-ai-litellm` exactly as before.
- [ ] One inventory pass over every inventory of the deploy writes the gateway's mesh URL and the host's virtual key into each consuming host's `host_vars`, and the key of every consuming host into the gateway host's `host_vars`, each key vault-encrypted with the vault password of the host that holds it.
- [ ] Re-running the pass changes no file, and its rotation option replaces the key of the one named consuming host and no other.
- [ ] The pass fails with a message naming both hosts when the gateway host or a consuming host holds no mesh address.
- [ ] The gateway host and each consuming host deploy from an inventory that holds only that host.

### Gateway

- [ ] The gateway answers on the gateway host's mesh address at its published port (`ports.local.http`), and a connection to that port on any public address of the gateway host is refused.
- [ ] After a reboot of the gateway host, the gateway answers on its mesh address without a redeploy.
- [ ] The gateway's deploy adds no vhost, domain or certificate for consuming hosts.
- [ ] The gateway's deploy registers the key of each consuming host under an alias that names the host and differs from the alias of every local consumer.
- [ ] Removing a host's gateway value, re-running the pass and redeploying the gateway host deletes that host's key, and the gateway refuses the key afterwards.
- [ ] Revoking the key of one consuming host leaves every other consuming host and every local consumer of the gateway answering.
- [ ] Local consumers on the gateway host keep the container-network URL and their own per-consumer keys.
- [ ] No `host_vars` of a consuming host and no file rendered on a consuming host holds the gateway's master key.

### Consuming host

- [ ] A host that carries `svc-ai-litellm` and names a gateway host fails the deploy with a message naming both hosts.
- [ ] On a consuming host, inventory provisioning adds no `svc-ai-litellm`, no consumer pulls it in as a shared provider, and no gateway container runs.
- [ ] On a consuming host, `LITELLM_USABLE` is true when the host holds the gateway's mesh URL and its key, and every consumer gated on it is enabled.
- [ ] On a consuming host, every consumer's gateway base URL is `http://<gateway mesh address>:<published port>`, with `/v1` where the consumer uses the OpenAI path, resolved in one place in `group_vars`, and no consumer role holds a branch of its own for the remote gateway.
- [ ] Every consumer on a consuming host authenticates with that host's key, and the gateway mints no key per consumer of a consuming host.
- [ ] Host-mode consumers (`dsk-gnt-claude`, `dsk-gnt-codex`, `dsk-gnt-pi`) on a consuming host reach the gateway on the same mesh URL with the host key.
- [ ] On a consuming host, the consumer contract accepts only the gateway's mesh URL (plain `http`, the gateway host's mesh IPv4 address, the published port) and refuses every other base URL, including the domain of `web-app-litellm`.
- [ ] On a consuming host, every consumer is configured with the gateway host's `LITELLM_CHAT_MODEL`.

### Failure behaviour

- [ ] Before it configures any consumer, the deploy of a consuming host requests the gateway's model list over the mesh with the host key, and fails with a message naming the gateway host and its mesh URL when the gateway does not answer, refuses the key, or does not list the configured chat model.
- [ ] While the mesh or the gateway is down, an AI request of a consumer on a consuming host fails with an error, and no consuming host starts a local gateway or sends the request to another endpoint.

### Tests

- [ ] Unit tests cover the consumer contract for the container-network, loopback and mesh URL, including a refused public domain and a refused mesh address of another host.
- [ ] Unit tests cover the inventory pass: first write, unchanged re-run, rotation of one host, removal of one host and a missing mesh address.
- [ ] A unit test asserts the gateway's key list for local consumers and consuming hosts, with distinct aliases.
- [ ] An end-to-end test joins a gateway host and a consuming host on one mesh, deploys both, and asserts that a consumer on the consuming host receives an answer from the gateway's mock model and that the consuming host runs no `svc-ai-litellm` container.
- [ ] An end-to-end test stops the gateway and asserts that the deploy of the consuming host fails with the message naming the gateway host.

### Documentation

- [ ] `roles/svc-ai-litellm/README.md` documents how a host is pointed at the central gateway, that the gateway host deploys first, and how the key of one host is rotated and revoked.

### Rollout

- [ ] galaxyserver and hotelserver name echoserver as their gateway host, run no `svc-ai-litellm`, and their AI consumers answer through the gateway on echoserver.
