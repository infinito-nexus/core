UPDATE users
   SET password_hash = %(password_hash)s
 WHERE lower(email) = lower(%(email)s)
   AND password_hash IS DISTINCT FROM %(password_hash)s;
