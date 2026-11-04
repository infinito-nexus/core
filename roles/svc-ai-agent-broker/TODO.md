# TODO

- Swarm agent networks are a fixed pool: `ensure_pool()` creates `MAX_RUNNING` overlays named `<entity>-agent-<slot>` and adds them to the broker's own service spec, which reschedules the broker task once per deploy before it serves. `network_for()` then hands an agent the lowest overlay no running agent occupies. A deployment that wants more concurrent agents raises `max_running`, so the ceiling is one number rather than a network per owner. Verify on a swarm cluster that the self-update converges in one reschedule and that an agent restarted after an idle stop reclaims a slot.
