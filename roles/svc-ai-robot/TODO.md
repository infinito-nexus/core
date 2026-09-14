# TODO

- Never deployed: `lifecycle: pre-alpha`. The admission checks and the device binding are covered by static analysis and a compose-mode matrix round, but no run has attached real hardware, so the passthrough is proven only against a placeholder device.

- Swarm: the device grant renders in compose mode only, matching the cadvisor precedent, because `docker stack deploy` drops `devices`. An embodied device is single-node by definition, so this is consistent rather than a gap, but the swarm path of the agent roles is never exercised with the robot role present.

- Self-exploration (requirement 034 decision 4) now has its prerequisite: the agent reaches the listed devices. Whether an agent turn can usefully drive them is untested and needs a model backend plus a real sensor or actuator.
