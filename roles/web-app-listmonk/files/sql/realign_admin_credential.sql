-- pgcrypto is trusted since PostgreSQL 13, so the database owner creates it
-- without superuser rights.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

\getenv pw LISTMONK_REALIGN_PASSWORD

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
         WHEN :ROW_COUNT = 1 THEN '[CHANGED]'
         ELSE '[UNCHANGED]'
       END AS realign;
