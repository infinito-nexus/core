DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public'
           AND p.proname = 'immutable_lower_unaccent'
    ) THEN
        EXECUTE 'ALTER FUNCTION public.immutable_lower_unaccent(text)'
                ' SET search_path = public, pg_catalog';
    END IF;
END
$$;

SELECT datname
  FROM pg_database
 WHERE NOT datistemplate
   AND datname <> current_database();
