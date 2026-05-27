# Network 🌐

Contributor-side network tooling: probe the live container network stack, suggest free per-role subnets, and suggest free host-bound ports.

## Subcommands 🧭

| Path | Purpose |
|---|---|
| [diagnose/](diagnose/) | Run `python -m cli.contributing.network.diagnose` to print a structured DNS / TCP / TLS / PMTU report (IPv4 + IPv6) plus interface MTU, `/etc/resolv.conf`, `/etc/hosts`, proxy env vars, and CA bundle summaries from inside the running infinito container. Exposed as `make diagnose-network`. |
| [address/](address/) | `cli contributing network address suggest`: propose the next free per-role IPv4 subnet(s) gap-first within the established umbrella blocks. |
| [ports/](ports/) | `cli contributing network ports suggest`: propose free host-bound ports inside `PORT_BANDS.<scope>.<category>`. |

## Related Documentation 📚

- [docs/contributing/actions/debugging/network.md](../../../docs/contributing/actions/debugging/network.md) explains how to read the diagnose output and how to fix MTU / IPv6 / connectivity issues.
- [docs/contributing/tools/network/](../../../docs/contributing/tools/network/) covers the contract of the `address` and `ports` suggesters.
