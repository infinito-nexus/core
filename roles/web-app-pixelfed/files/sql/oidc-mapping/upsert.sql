INSERT INTO user_oidc_mappings (user_id, oidc_id, created_at, updated_at)
VALUES (%(user_id)s, %(oidc_id)s, NOW(), NOW())
ON DUPLICATE KEY UPDATE
  user_id = VALUES(user_id),
  updated_at = IF(user_id <> VALUES(user_id), NOW(), updated_at);
SELECT ROW_COUNT();
