SELECT COUNT(*)
FROM information_schema.columns
WHERE table_schema = %(db_name)s
  AND table_name = 'user_oidc_mappings'
  AND column_name IN ('user_id', 'oidc_id', 'created_at', 'updated_at');
