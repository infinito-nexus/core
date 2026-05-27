# Templating Utilities 🧩

Strict Jinja renderers used by lookup plugins, library modules, and the YAML cache layer.

## Scope 📋

Modules in `utils/templating/` MUST limit themselves to rendering `{{ ... }}` and `{% ... %}` constructs found in YAML values, lookups, and templated config strings.

Both renderers fail loudly when Jinja markers cannot be resolved so generated configs never silently leak unrendered placeholders.

## Modules 📦

| Module | Engine | When to use |
|---|---|---|
| [ansible.py](ansible.py) | Ansible's internal `Templar` (with `TrustedAsTemplate` tagging for Ansible 2.19+) | When the caller already has Ansible's variable stack and wants tag-aware rendering with shortcuts for `lookup('env', ...)`, simple `var.path` lookups, and literal coercion. |
| [jinja.py](jinja.py) | Standalone `jinja2.Environment` | When the caller runs in a context where Templar can silently leave markers untouched (some lookup plugin entry points). Renders multiple passes so nested vars (`A.x = "{{ B.y }}"`, `B.y = "{{ C.z }}"`) collapse fully. |

## Example Imports ✍️

```python
from utils.templating.ansible import render_ansible_strict
from utils.templating.jinja import render_strict
```
