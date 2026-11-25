UPDATE crossposter.items
SET
    state = %(state)s,
    publication_id = %(publication_id)s,
    attempts = %(attempts)s,
    last_error = %(error)s,
    next_attempt_at = %(next_attempt_at)s,
    updated_at = now()
WHERE id = %(id)s;
