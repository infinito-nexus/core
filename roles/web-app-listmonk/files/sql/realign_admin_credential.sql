-- pgcrypto is trusted since PostgreSQL 13, so the database owner creates it
-- without superuser rights.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

\getenv pw LISTMONK_REALIGN_PASSWORD

\if :create
INSERT INTO users (username, password_login, password, email, name, type, user_role_id, status)
SELECT :'login', :'password_login'::boolean, crypt(:'pw', gen_salt('bf')), :'email', :'login',
       'user', 1, 'enabled'
WHERE length(:'pw') > 0
  AND NOT EXISTS (SELECT 1 FROM users WHERE username = :'login')
  AND NOT EXISTS (SELECT 1 FROM users WHERE lower(email) = lower(:'email'))
  AND EXISTS (SELECT 1 FROM users WHERE type = 'user' AND user_role_id = 1);
\set created :ROW_COUNT
\else
\set created 0
\endif

UPDATE users
SET password = crypt(:'pw', gen_salt('bf'))
WHERE username = :'login'
  AND length(:'pw') > 0
  AND (password IS NULL OR password <> crypt(:'pw', password));

SELECT CASE
         WHEN length(:'pw') = 0
           THEN '[FAIL] LISTMONK_REALIGN_PASSWORD did not reach the container'
         WHEN NOT EXISTS (SELECT 1 FROM users WHERE username = :'login')
           THEN '[FAIL] no account named ' || :'login'
         WHEN :created = 1 THEN '[CHANGED] the Super Admin ' || :'login' || ' was created'
         WHEN :ROW_COUNT = 1 THEN '[CHANGED]'
         ELSE '[UNCHANGED]'
       END AS realign;
