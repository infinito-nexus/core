SELECT *
FROM crossposter.items
WHERE state = 'pending' AND next_attempt_at <= now()
ORDER BY id;
