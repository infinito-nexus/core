# FreeLLMAPI validation

- [ ] Validate first-account setup, provider routing and a state-preserving update through the full compose deploy loop and add its Playwright smoke coverage before promoting the role to alpha.
- [ ] Run the LiteLLM upstream protocol validation against a configured FreeLLMAPI pool in the full Compose deploy loop; unit fixtures do not prove upstream compatibility.
- [ ] Exercise administrator password/email rotation and an unchanged redeploy against the pinned image in the full Compose loop, including its HTTP login gate.
