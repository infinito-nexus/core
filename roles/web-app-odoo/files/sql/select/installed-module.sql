SELECT name, latest_version FROM ir_module_module WHERE name = %(module)s AND state = 'installed';
