# Custom Lookup Plugins for Infinito.Nexus

This directory contains custom **Ansible lookup plugins** used within the Infinito.Nexus project.

## When to Use a Lookup Plugin

- **Load external data:** Use lookups to retrieve data from files, APIs, databases, environment variables, or other external sources.
- **Context-aware data access:** Lookups can access the full Ansible context, including inventory, facts, and runtime variables.
- **Generate dynamic lists:** Lookups are often used to build inventories, secrets, or host lists dynamically.

### Examples

```yaml
# Load the contents of a file as a variable
my_secret: "{{ lookup('file', '/path/to/secret.txt') }}"

# Retrieve a list of hostnames from an external source
host_list: "{{ lookup('infinito_inventory_hosts', 'group_name') }}"
````

## When *not* to Use a Lookup Plugin

- If you only need to **manipulate or transform data already available** in your playbook, prefer a filter plugin instead.

## Further Reading

- [Ansible Lookup Plugins Documentation](https://docs.ansible.com/ansible/latest/plugins/lookup.html)
- [Developing Ansible Lookup Plugins](https://docs.ansible.com/ansible/latest/dev_guide/developing_plugins.html#developing-lookup-plugins)
