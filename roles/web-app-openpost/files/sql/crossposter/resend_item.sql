UPDATE crossposter.items
SET
    state = 'pending',
    resends = resends + 1,
    publication_id = '',
    attempts = %(attempts)s,
    last_error = %(error)s,
    next_attempt_at = %(next_attempt_at)s,
    updated_at = now()
WHERE id = %(id)s;
