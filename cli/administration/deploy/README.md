# Deploy 🚀

Run Ansible deploys against a dedicated inventory, a CI container image, or the development matrix that iterates per-role variants.

- [development/](development/README.md): matrix deploy, include resolution, `disable` and orphan pruning (with diagrams).
- [ci/](ci/README.md): CI container image deploy.

## OpenBao references

- **Reference form.** A credential leaf under `applications.<id>.secrets.credentials` may be the mapping `{openbao: <mount>/<path>#<field>}`, for example `openbao: tenant/ws-<id>/ssh#private_key`. `lookup('config', ...)` resolves it to the field's value ([plugins/lookup/config.py](../../../plugins/lookup/config.py), [utils/openbao_client.py](../../../utils/openbao_client.py)); a vault block and a plain value keep their meaning. A mapping with a second key beside `openbao`, or a value of another form, is refused with the credential's name.
- **Login order.** `infinito administration deploy dedicated` logs in once per run, before the play: with `SEMAPHORE_JWT` and `BAO_ROLE` through `auth/jwt/login` when a Semaphore task runs it, otherwise with the operator's `BAO_TOKEN`. `BAO_ADDR` names the platform's OpenBao, an `https://` URL, and under `TLS_MODE` `self_signed` `BAO_CACERT` names the deployment CA, trusted beside the system store. The token reaches the play only as `BAO_TOKEN` in the controller's environment, never in a file, an argument or a host.
- **Pre-flight.** Before the first play, [dedicated/openbao.py](dedicated/openbao.py) reads every reference of the inventory once and discards the values. A missing (404) or denied (403) path, a missing field and a missing login each stop the deploy with the credential, path and field, never the value, and no host is contacted. A reference that fails later fails its task with the same message.
- **No vault password without vault blocks.** An inventory without a `!vault` block deploys without `--password-file`.
- **Create-only.** `infinito administration inventory credentials --openbao <mount>/<prefix>` writes every value it generates create-only (`cas` 0) and only the reference into the inventory; see the [inventory documentation](../inventory/README.md#openbao-references).
