INSERT INTO roles (type, name, permissions)
SELECT 'user', :'role_name', ARRAY['campaigns:get_all', 'campaigns:get']
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name = :'role_name');

UPDATE roles
SET permissions = ARRAY['campaigns:get_all', 'campaigns:get']
WHERE name = :'role_name'
  AND permissions IS DISTINCT FROM ARRAY['campaigns:get_all', 'campaigns:get'];

INSERT INTO users (username, password_login, password, email, name, type, user_role_id, status)
SELECT :'username', false, :'token_hash', :'username' || '@api',
       'MCP read-only adapter', 'api',
       (SELECT id FROM roles WHERE name = :'role_name'), 'enabled'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE username = :'username');

UPDATE users
SET password = :'token_hash',
    user_role_id = (SELECT id FROM roles WHERE name = :'role_name'),
    status = 'enabled'
WHERE username = :'username' AND type = 'api'
  AND (password IS DISTINCT FROM :'token_hash'
       OR user_role_id IS DISTINCT FROM (SELECT id FROM roles WHERE name = :'role_name')
       OR status IS DISTINCT FROM 'enabled');
