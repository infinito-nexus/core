\set ON_ERROR_STOP on
\set db_extensions ''
\getenv db_name DB_NAME
\getenv db_user DB_USER
\getenv db_password DB_PASSWORD
\getenv db_extensions DB_EXTENSIONS

SELECT format('CREATE DATABASE %I', :'db_name')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name') \gexec

SELECT format('CREATE ROLE %I', :'db_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'db_user') \gexec

SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'db_user', :'db_password') \gexec

SELECT format('GRANT ALL PRIVILEGES ON DATABASE %I TO %I', :'db_name', :'db_user') \gexec

\connect :"db_name"

SELECT format('GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO %I', :'db_user') \gexec

SELECT format('CREATE EXTENSION IF NOT EXISTS %I', extension)
FROM unnest(string_to_array(:'db_extensions', ',')) AS extension
WHERE extension <> '' \gexec
