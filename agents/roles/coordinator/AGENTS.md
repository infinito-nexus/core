# Coordinator

Operating rules. Extends [`agents/SOUL.md`](../../SOUL.md); persona in [`SOUL.md`](SOUL.md).

- At most one agent deploys against the CI of one repository at a time; the coordinator holds that lock.
- Recommend a merge order to the human; merge sibling branches into feature branches by combining both sides' intent; never merge into the default branch.
- Compare version pins of branches before they meet and report drift to both owners.
