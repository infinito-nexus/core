-- pgcrypto is trusted since PostgreSQL 13, so the database owner creates it
-- without superuser rights.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

UPDATE users
SET password = crypt(:'pw', gen_salt('bf'))
WHERE username = 'administrator'
  AND (password IS NULL OR password <> crypt(:'pw', password));
