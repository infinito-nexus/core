SELECT count(*)
FROM pg_catalog.pg_database
WHERE datname = %(name)s;
