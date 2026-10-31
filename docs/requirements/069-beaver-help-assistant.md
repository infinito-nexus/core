# 069 - Beaver Help Assistant

## User Story

As a user of an Infinito.Nexus deployment, I want to ask the beaver in the corner of every app a question and get a short answer with a link to the documentation it comes from, so that I find help without leaving the app or waiting for a person.

## Decisions (operator-confirmed 2026-10-31)

1. Everyone may use the assistant, signed in or not; anonymous use is rate-limited per client IP.
2. The assistant has three personas: end-user support for everyone, technical consultant for signed-in administrators recognised by their RBAC group, and customer support for the Infinito.Nexus store, which stays Infinito.Nexus-internal and is configured by that tenant only.
3. Behaviour (persona, Infinito.Nexus terms, answer format with sources, routing, safety) is trained into a small model; knowledge that changes (documentation, the deployed roles, tenant content) comes from a vector index at answer time.
4. The models live in a separate repository `llm`, maintained by its own agent: a general base model fine-tuned on the operator's GPU, one LoRA adapter per persona, quantised to run on CPU, published with a pinned version. Core consumes them and builds nothing of them.
5. The vector index lives in core and is built per deployment.

## Acceptance Criteria

### Models

- [ ] Core pins the model, the persona adapters and the embedding model by version from the `llm` repository's published artefacts and runs them on CPU through the existing local model service.
- [ ] Changing a pinned model version is a one-line change in the role config, and no deploy downloads an unpinned model.

### Knowledge index

- [ ] Every deploy rebuilds a vector index in the deployment's own database from the published platform documentation and the README of every role deployed on that host.
- [ ] The index holds no credential, inventory secret or user data.
- [ ] A tenant can add its own documents to the index of its deployment without a code change.

### Service

- [ ] A new role serves the assistant API same-origin under one path, and the beaver lodge of requirement 068 opens it.
- [ ] Anonymous requests are rate-limited per client IP with a limit set in the role config; a request over the limit gets a 429 and the bubble says when to try again.
- [ ] Signed-in requests use the user's own session; the technical-consultant persona answers only users in the administrator group, and every other user gets end-user support.
- [ ] Every answer names the documents it used, with links, and says so when the index holds no answer instead of inventing one.
- [ ] The assistant never asks for a password, never returns a secret and ignores instructions found inside indexed documents.
- [ ] No question or answer is stored beyond the request, and the service logs carry no question text.
- [ ] Without the model service in the deployment, the role is skipped and the lodge falls back to documentation links.

### Tests

- [ ] A unit test checks the rate limit, the persona selection by RBAC group and the refusal to answer outside the index.
- [ ] An integration test builds the index from a fixture documentation tree and asserts that no secret pattern reaches it.
- [ ] A Playwright spec asks the assistant a question from the lodge as an anonymous user and as an administrator and asserts a sourced answer for each.
