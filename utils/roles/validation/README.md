# Role Validation Helpers ✅

Validators that gate role inputs and outputs against project rules.

## Scope 📋

Modules in `utils/roles/validation/` MUST limit themselves to checking that role artefacts and their derived names obey the constraints documented in `docs/contributing/`: legal application identifiers, deployment-target invokability, container resource shape.

Validators MUST raise typed exceptions (or return the offending value with a clear message) so callers can surface the failure at the right layer (CLI exit code, lint test failure, runtime assertion).

Validators MUST stay independent of Ansible plugin loader behavior at import time so the same code runs from filter plugins, lookup plugins, the CLI, and tests.

## Modules 📦

| Module | Validates |
|---|---|
| [deploy_id.py](deploy_id.py) | Application id strings against the canonical `<bucket>-<entity>` shape and the active deploy-id grammar. |
| [invokable.py](invokable.py) | Whether an application can legitimately be invoked under a given deployment type (e.g. `server`, `workstation`, `universal`). |
| [resources.py](resources.py) | Container resource declarations (`cpus`, `mem_reservation`, `mem_limit`, `pids_limit`) for shape and unit consistency. |

## Example Imports ✍️

```python
from utils.roles.validation.deploy_id import validate_deploy_id
from utils.roles.validation.invokable import is_invokable_for
from utils.roles.validation.resources import validate_resource_block
```
