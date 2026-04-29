# DNS Helpers

This is the SPOT for DNS helpers under `scripts/system/network/dns/`.
The folder contains the local name-resolution setup and teardown logic used during development and environment preparation.
For the canonical Make target index that invokes these helpers, see [make.md](../../../../docs/contributing/tools/make.md).

## Areas

- [setup/](setup/) for DNS setup scripts
- [`remove.sh`](remove.sh) for DNS teardown
- [`common.sh`](common.sh) for shared DNS variables and helper functions

## Notes

- Canonical domains and aliases come from `roles/*/meta/server.yml`
- The CLI entrypoint lives in `cli/meta/domains/__main__.py`
- The reusable generator logic lives in `utils/domains/list.py`
- `DOMAIN_PRIMARY` is rendered before the list is emitted
- The DNS fallback calls the generator with `--alias --www`
- `INFINITO_DNS_HOSTS` can still override the generated list explicitly
