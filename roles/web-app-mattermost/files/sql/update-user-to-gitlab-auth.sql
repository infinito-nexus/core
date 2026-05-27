UPDATE users
   SET authservice = 'gitlab',
       authdata    = %(authdata)s,
       password    = ''
WHERE email = %(email)s;
