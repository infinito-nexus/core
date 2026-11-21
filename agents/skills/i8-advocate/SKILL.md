---
name: i8-advocate
description: >
  Review the whole project for legal soundness: licence compatibility of code,
  dependencies and shipped images, attribution, copied code, data protection
  and trademarks. Infinito.Nexus specific.
routines:
  - legal_audit
---

Run the `advocate` skill over the whole tree instead of the staging index:
the project licence declarations, every dependency manifest and lockfile with
the transitive dependencies of the resolved versions, the images and packages
the roles ship, vendored and copied code, attribution, data protection and
trademarks. The deterministic steps and the order are the `legal_audit`
routine; see `python -m agents.routines show legal_audit`. Harden every blocker
with the `dialectic` skill before filing it, and state in one line that the
report is no legal advice.
