# Custom Modules (`library/`)

This directory contains project-specific Ansible modules used by Infinito.Nexus.

## What Belongs Here

Use `library/` for idempotent module logic that represents concrete automation actions.

Typical cases:

- managing resources that have no suitable built-in/community module,
- wrapping internal APIs or internal infrastructure semantics,
- implementing reusable module interfaces for role/playbook consumption.

## What Does Not Belong Here

- Shared helper code used by multiple modules/plugins goes to `utils/`.
- Jinja transformations belong to `plugins/filter/`.
- Runtime value retrieval belongs to `plugins/lookup/`.
- Task execution wrappers belong to `plugins/action/`.

## Usage

Ansible searches `library/` for custom modules. In playbooks, call them like built-in modules.

```yaml
- name: Run a custom Infinito module
  infinito_custom_module:
    option_one: value
    option_two: value
```

## Implementation Notes

- Keep modules idempotent and predictable.
- Validate input early and return structured failure messages.
- Move duplicated helpers into `utils/`.

### Shebang Requirement for Custom Modules

Files in `library/` should use:

```python
#!/usr/bin/python
```

Ansible rewrites this interpreter path to the configured host interpreter for module execution.

## References

- Developing modules: <https://docs.ansible.com/ansible/latest/dev_guide/developing_modules.html>
- Module utilities: <https://docs.ansible.com/ansible/latest/dev_guide/developing_module_utilities.html>
