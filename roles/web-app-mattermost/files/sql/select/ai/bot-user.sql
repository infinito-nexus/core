SELECT count(*)
  FROM bots b
  JOIN users u ON u.id = b.userid
 WHERE u.username = %(bot_name)s;
