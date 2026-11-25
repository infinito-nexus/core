SELECT s.id,
       SHA2(s.cfg, 256)
FROM login_source s
WHERE s.type = 6
ORDER BY s.id;
