# Custom Filter Plugins for Infinito.Nexus

This directory contains custom **Ansible filter plugins** used within the Infinito.Nexus project.

## When to Use a Filter Plugin

- **Transform values:** Use filters to transform, extract, reformat, or compute values from existing variables or facts.
- **Inline data manipulation:** Filters are designed for inline use in Jinja2 expressions (in templates, tasks, vars, etc.).
- **No external lookups:** Filters only operate on data you explicitly pass to them and cannot access external files, the Ansible inventory, or runtime context.

### Examples

```jinja2
{{ role_name | get_entity_name }}
{{ my_list | unique }}
{{ user_email | regex_replace('^(.+)@.*$', '\\1') }}
````

## When *not* to Use a Filter Plugin

- If you need to **load data from an external source** (e.g., file, environment, API), use a lookup plugin instead.
- If your logic requires **access to inventory, facts, or host-level information** that is not passed as a parameter.

## Schema 🗺️

How `csp_filters.py` assembles one application's Content-Security-Policy. Scope is the header build, not the other filters in this directory.

```mermaid
flowchart TD
    decl["meta/csp.yml<br/>whitelist, flags, hashes"]
    svc["meta/services.yml<br/>services.logout.enabled"]
    flags["csp_filters.py:136<br/>get_csp_flags"]
    grant["csp_filters.py:354<br/>logout grant"]
    wl["csp_filters.py:123<br/>get_csp_whitelist"]
    inj["sys-front-inj-dashboard,<br/>-javascript, -matomo, -logout<br/>add_csp_hash"]
    gate["csp_filters.py:366<br/>hash gate"]
    build["csp_filters.py:203<br/>build_csp_header"]
    header["set $csp<br/>nginx vhost"]

    decl -->|"1. flags read by"| flags
    flags -->|"2. tokens"| build
    svc -->|"3. read by"| grant
    decl -->|"3a. unsafe-inline: false<br/>on -elem or -attr vetoes"| grant
    grant -->|"4. adds 'unsafe-inline'<br/>to script-src-elem and -attr"| build
    decl -->|"5. whitelist read by"| wl
    wl -->|"6. tokens"| build
    inj -->|"7. snippets"| gate
    gate -->|"8. hashes, only when<br/>'unsafe-inline' is absent"| build
    build -->|"9. joined string"| header

    grant -.->|"TRIP-WIRE: the token it adds<br/>closes the gate below, so every<br/>registered hash is discarded"| gate
    svc -.->|"TRIP-WIRE: the flag derives from<br/>group_names, so the script policy<br/>follows the round, not the app"| grant
    grant -.->|"TRIP-WIRE: absent from the<br/>smart-defaults docstring, which<br/>names logout only for frame-ancestors"| build
```

Styles carry `'unsafe-inline'` by default; scripts do not. The logout grant is the only implicit path that puts it into a script directive. An application keeps it out of `script-src-elem` or `script-src-attr` by setting `unsafe-inline: false` on that directive in its `meta/csp.yml`.

## Further Reading

- [Ansible Filter Plugins Documentation](https://docs.ansible.com/ansible/latest/plugins/filter.html)
- [Developing Ansible Filter Plugins](https://docs.ansible.com/ansible/latest/dev_guide/developing_plugins.html#developing-filter-plugins)
