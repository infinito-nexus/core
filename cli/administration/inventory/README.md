# Inventory 📋

Build, populate, and validate Ansible inventories: device groups for invokable applications, per-app credential generation, full one-shot provisioning, and pre-deploy validation.

## OpenBao references

- **Reference form.** `credentials --openbao <mount>/<prefix>` writes each generated credential to `<mount>/<prefix>/<application>/<credential>` with the single field `value`, and puts `{openbao: <mount>/<prefix>/<application>/<credential>#value}` into the inventory instead of a vault block. Nested credentials such as `recaptcha.key` become `.../recaptcha/key`.
- **Create-only rule.** Every write sets `cas` 0, so an existing secret and every one of its versions stay as they are, and a value the inventory already holds, a reference, a vault block or a plain value, is never replaced. The mode takes neither `--force` nor `--snippet`, and it needs no `--vault-password-file`.
- **Login order.** The mode logs in like the deploy: `SEMAPHORE_JWT` with `BAO_ROLE`, else `BAO_TOKEN`, at `BAO_ADDR`, with `BAO_CACERT` under `self_signed`.
- **Pre-flight.** A credential the inventory supplies as a reference but does not generate must already exist at its path; the deploy's pre-flight stops at it with its path ([deploy documentation](../deploy/README.md#openbao-references)).
- **User fields.** Of a user, only `password`, `email`, `firstname` and `lastname` may hold a reference. The store keeps the three personal fields in `tenant/ws-<id>/users/<name>` and erases a person by deleting that secret's metadata, after which a deploy at an older inventory commit stops at the pre-flight with the path ([deploy documentation](../deploy/README.md#openbao-references)).
