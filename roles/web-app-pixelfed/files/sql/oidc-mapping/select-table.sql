SELECT table_name
FROM information_schema.tables
WHERE table_schema = %(db_name)s
  AND table_name = 'user_oidc_mappings'
LIMIT 1;
