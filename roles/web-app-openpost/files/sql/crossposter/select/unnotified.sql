SELECT *
FROM crossposter.items
WHERE state IN ('failed', 'dead_lettered') AND notified_at IS NULL
ORDER BY id;
