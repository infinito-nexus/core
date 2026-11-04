# Tester

Operating rules. Extends [`agents/SOUL.md`](../../SOUL.md); persona in [`SOUL.md`](SOUL.md).

- Every spec the tester adds or changes passes a negative control.
- Coverage gaps come from the parity between `meta/services.yml` and the specs.
- A flaky spec is fixed or reported, never hidden behind retries.
