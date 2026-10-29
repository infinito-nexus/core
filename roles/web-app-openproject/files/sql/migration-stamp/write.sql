DO $$
BEGIN
    EXECUTE format(
        'COMMENT ON TABLE public.schema_migrations IS %L', %(image)s
    );
END
$$;
