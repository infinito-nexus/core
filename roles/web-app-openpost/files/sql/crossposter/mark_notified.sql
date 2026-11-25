UPDATE crossposter.items
SET notified_at = now()
WHERE id = %(id)s;
