INSERT INTO crossposter.cursors (route, cursor)
VALUES (%(route)s, %(cursor)s)
ON CONFLICT (route) DO UPDATE
    SET cursor = excluded.cursor, updated_at = now();
